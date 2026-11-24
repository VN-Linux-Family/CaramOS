"""The admin window's draft of the policy: the company's settings, the departments with theirs, the members, and the
settings of single machines, plus the pictures and Wi-Fi passwords picked since the last save. Apart from GTK so that
it can be tested without a display.

Every section is opt-in (PROTOCOL.md part 2): absent means not managed. A department or a machine either uses what
applies above it (the section absent from its layer), has its own (a value), or turns the section off (null). A
section gets its defaults, such as the usual office hours, only when the admin switches it on."""

from __future__ import annotations

import copy
import re
import unicodedata
from typing import Any

from . import admin, presets, protocol
from .i18n import _

COMPANY = "company"
INHERIT, OWN, OFF = "inherit", "own", "off"

# Weekdays most offices work: Monday to Saturday.
WORKDAYS = [1, 2, 3, 4, 5, 6]


def defaults(section: str) -> Any:
    """A section's value when the admin switches it on: the form starts from this."""

    values: dict[str, Any] = {
        "wallpaper": {"default": None, "periods": [], "lock": False},
        "folders": {"share": "", "tidy": True},
        "shares": [],
        "browser": {"homepage": None, "bookmarks": [], "block": [], "block_hours": copy.deepcopy(presets.OFFICE_HOURS),
                    "safe_search": False},
        "printers": [],
        "power": {"shutdown": shutdown_defaults(), "wake": None},
        "apps": {"required": [], "forbidden": []},
        "usb": {"storage": "read-only"},
        "screen_lock": {"idle_minutes": 10, "on_suspend": True},
        "firewall": {"enabled": True},
        "inventory": {"enabled": True},
        "wifi": [],
        # Part 3: guest on, freeze off, maintenance Sunday 02:00 for 60 minutes; snapshots weekly, 3, before updates.
        "shared": {"guest": True, "freeze": False, "maintenance": maintenance_defaults(), "low_memory_ok": False},
        "snapshots": {"schedule": "weekly", "keep": 3, "before_update": True},
    }
    return copy.deepcopy(values[section])


def maintenance_defaults() -> dict[str, Any]:
    return {"days": [7], "time": "02:00", "max_minutes": 60}


def shutdown_defaults() -> dict[str, Any]:
    return {"days": list(WORKDAYS), "time": "18:30", "warn_minutes": 10, "postpone_minutes": 30, "max_postpones": 2,
            "laptops": "skip"}


def wake_defaults() -> dict[str, Any]:
    return {"days": list(WORKDAYS), "time": "07:30"}


def slug(name: str) -> str:
    """A department id from its name: 'Kế toán' gives 'ke-toan'."""

    text = unicodedata.normalize("NFKD", name.replace("đ", "d").replace("Đ", "D"))
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:32].strip("-") or "phong"


def scope_kind(scope: str) -> str:
    return scope.split(":", 1)[0]


def scope_key(scope: str) -> str:
    return scope.split(":", 1)[1] if ":" in scope else ""


class Draft:
    def __init__(self, policy: dict[str, Any]) -> None:
        # Counts the times the draft's values were replaced (load, revert): an editor built before holds values that
        # are no longer the draft's, so its page is built again (a change made there was lost, without a save bar,
        # after "Lưu và gửi" in 0.3.1).
        self.generation = 0
        self.load(policy)

    def load(self, policy: dict[str, Any]) -> None:
        self.generation += 1
        self.serial = int(policy.get("serial", 0) or 0)
        self.saved = admin.draft_from_policy(policy)
        for department in self.saved["departments"].values():  # so that reading a layer never looks like a change
            department.setdefault("settings", {})
        self.data = copy.deepcopy(self.saved)
        self.files = set(policy.get("files") or {})
        self.pictures: dict[str, str] = {}
        self.passphrases: dict[str, str] = {}

    def revert(self) -> None:
        self.generation += 1
        self.data = copy.deepcopy(self.saved)
        self.pictures.clear()
        self.passphrases.clear()

    @property
    def dirty(self) -> bool:
        return self.data != self.saved or bool(self.passphrases)

    # - layers -

    def settings(self, scope: str, create: bool = False) -> dict[str, Any] | None:
        kind, key = scope_kind(scope), scope_key(scope)
        if kind == COMPANY:
            return self.data.setdefault("settings", {})
        group = self.data.setdefault("departments" if kind == "department" else "machines", {})
        if key not in group:
            if not create or kind == "department":
                return None
            group[key] = {"settings": {}}
        return group[key].setdefault("settings", {})

    def has(self, scope: str, section: str) -> bool:
        settings = self.settings(scope)
        return settings is not None and section in settings

    def get(self, scope: str, section: str) -> Any:
        settings = self.settings(scope)
        return None if settings is None else settings.get(section)

    def mode(self, scope: str, section: str) -> str:
        """The company: OWN (on) or OFF (absent or null). A department or machine: INHERIT, OWN or OFF."""

        if not self.has(scope, section):
            return OFF if scope == COMPANY else INHERIT
        return OFF if self.get(scope, section) is None else OWN

    def set(self, scope: str, section: str, value: Any) -> None:
        settings = self.settings(scope, create=True)
        if settings is None:
            raise KeyError(scope)
        settings[section] = value

    def unset(self, scope: str, section: str) -> None:
        settings = self.settings(scope)
        if settings is not None:
            settings.pop(section, None)
        if scope_kind(scope) == "machine" and settings == {}:
            self.data.get("machines", {}).pop(scope_key(scope), None)

    def switch(self, scope: str, section: str, mode: str) -> None:
        """Changes how a scope takes a section. OWN starts from what applied before (or the defaults)."""

        if mode == INHERIT or (mode == OFF and scope == COMPANY):
            self.unset(scope, section)
        elif mode == OFF:
            self.set(scope, section, None)
        elif self.mode(scope, section) != OWN:
            above, _source = self.above(scope, section)
            self.set(scope, section, copy.deepcopy(above) if above is not None else defaults(section))

    def above(self, scope: str, section: str) -> tuple[Any, str | None]:
        """What a scope would get without its own setting: (value, the scope it comes from); (None, None) when the
        section is not managed above it."""

        kind = scope_kind(scope)
        chain = []
        if kind == "machine":
            department = self.department_of(scope_key(scope))
            if department:
                chain.append(f"department:{department}")
        if kind != COMPANY:
            chain.append(COMPANY)
        for candidate in chain:
            if self.has(candidate, section):
                return self.get(candidate, section), candidate
        return None, None

    def as_policy(self) -> dict[str, Any]:
        return {"settings": self.data.get("settings", {}), "departments": self.data.get("departments", {}),
                "members": self.data.get("members", {}), "machines": self.data.get("machines", {})}

    def effective(self, machine_id: str) -> dict[str, Any]:
        return protocol.effective_settings(self.as_policy(), machine_id)

    def sources(self, machine_id: str) -> dict[str, str]:
        return protocol.setting_sources(self.as_policy(), machine_id)

    # - departments and members -

    def departments(self) -> dict[str, Any]:
        return self.data.setdefault("departments", {})

    def add_department(self, name: str) -> str:
        name = name.strip()
        if not name or len(name) > protocol.MAX_NAME:
            raise protocol.ProtocolError(_("A department's name has 1 to 60 characters."))
        if len(self.departments()) >= protocol.MAX_DEPARTMENTS:
            raise protocol.ProtocolError(_("At most 50 departments."))
        if any(item.get("name", "").casefold() == name.casefold() for item in self.departments().values()):
            raise protocol.ProtocolError(_("There is a department with this name already."))
        base = slug(name)
        key, number = base, 2
        while key in self.departments():
            suffix = f"-{number}"
            key = base[:32 - len(suffix)] + suffix
            number += 1
        self.departments()[key] = {"name": name, "settings": {}}
        return key

    def rename_department(self, key: str, name: str) -> None:
        name = name.strip()
        if not name or len(name) > protocol.MAX_NAME:
            raise protocol.ProtocolError(_("A department's name has 1 to 60 characters."))
        self.departments()[key]["name"] = name

    def remove_department(self, key: str) -> None:
        self.departments().pop(key, None)
        members = self.data.setdefault("members", {})
        for machine_id in [machine for machine, department in members.items() if department == key]:
            del members[machine_id]

    def department_of(self, machine_id: str) -> str | None:
        department = self.data.get("members", {}).get(machine_id)
        return department if department in self.departments() else None

    def set_department(self, machine_id: str, department: str | None) -> None:
        members = self.data.setdefault("members", {})
        if department:
            members[machine_id] = department
        else:
            members.pop(machine_id, None)

    def scope_title(self, scope: str, machines: dict[str, Any] | None = None) -> str:
        kind, key = scope_kind(scope), scope_key(scope)
        if kind == COMPANY:
            return _("Whole company")
        if kind == "department":
            return self.departments().get(key, {}).get("name", key)
        return _("Machine %s") % admin.machine_name(machines or {}, key)

    def machine_scopes(self) -> list[str]:
        return [f"machine:{key}" for key, value in self.data.get("machines", {}).items()
                if isinstance(value, dict) and value.get("settings")]

    # - pictures and passwords -

    def new_picture(self, path: str) -> str:
        name = f"new:{len(self.pictures) + 1}"
        while name in self.pictures:
            name = f"new:{int(name[4:]) + 1}"
        self.pictures[name] = path
        return name

    def saved_networks(self) -> dict[str, str]:
        return admin.wifi_networks(self.saved)

    def password_state(self, ssid: str) -> str:
        """"new" (typed, not sent), "saved" (the admin keeps it), "missing" or "open"."""

        security = admin.wifi_networks(self.data).get(ssid)
        if security != "wpa-psk":
            return "open"
        if ssid in self.passphrases:
            return "new"
        return "saved" if self.saved_networks().get(ssid) == "wpa-psk" else "missing"

    # - saving -

    def validate(self, machines: dict[str, Any] | None = None) -> None:
        """The checks of the helper that need no root, so that mistakes show before the password is asked. With the
        machines (the approved ones), the draft is first kept to what the helper saves of it, as the helper does."""

        files = {sha: {} for sha in self.files} | {name: {} for name in self.pictures}
        policy = self.as_policy()
        layers = [(COMPANY, policy["settings"])]
        layers += [(f"department:{key}", value.get("settings") or {}) for key, value in policy["departments"].items()]
        layers += [(f"machine:{key}", value.get("settings") or {}) for key, value in policy["machines"].items()]
        for scope, settings in layers:
            protocol.validate_settings(settings, files, scope)
        # Freezing with snapshots, with folders tidy or without a maintenance time, for any machine or department: 0.3.1
        # refused it only after the password.
        problem = admin.freeze_problem(admin.clean_draft(policy, machines) if machines is not None else policy)
        if problem:
            raise protocol.ProtocolError(problem[1], section="shared", scope=problem[0])
        for ssid, security in admin.wifi_networks(self.data).items():
            if security == "wpa-psk" and self.password_state(ssid) == "missing":
                raise protocol.ProtocolError(_("Type the password of the Wi-Fi network “%s”.") % ssid, section="wifi")
        for passphrase in self.passphrases.values():
            if not protocol.valid_passphrase(passphrase):
                raise protocol.ProtocolError(_("A Wi-Fi password has 8 to 63 letters, digits or signs, without "
                                               "Vietnamese accents."), section="wifi")

    def payload(self) -> dict[str, Any]:
        """What the helper's policy command reads on stdin."""

        used = set()
        for _scope, settings in admin._layers_of(self.data):  # noqa: SLF001 - the same walk as the helper's
            wallpaper = settings.get("wallpaper") if isinstance(settings, dict) else None
            if isinstance(wallpaper, dict):
                used.add(wallpaper.get("default"))
                used.update(period.get("image") for period in wallpaper.get("periods") or [])
        networks = admin.wifi_networks(self.data)
        return dict(copy.deepcopy(self.as_policy()),
                    pictures={name: path for name, path in self.pictures.items() if name in used},
                    wifi_passphrases={ssid: value for ssid, value in self.passphrases.items() if ssid in networks})

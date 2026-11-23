"""The admin machine's state (PROTOCOL.md "Files", admin, parts 1 to 3): its keys, the policy and the signed one,
the pictures, the paired, pending and removed machines, the options, commands and their results, inventories and
assets, health first-seen times and the audit log. Tickets, enrolment tokens and the licence register have their own
modules (tickets.py, pairing.py, licences.py).

The root helper and the server write it; the window reads it as the user. The state folder is readable by the
sudo group only (the users polkit lets run the helper); secrets.json, the Wi-Fi passphrases, only by root."""

from __future__ import annotations

import base64
import copy
import datetime
import grp
import hashlib
import json
import os
import pwd
import time
import uuid
from pathlib import Path
from typing import Any

from . import ADMIN_BOX_KEY, ADMIN_KEY, ADMIN_STATE, PAIRING, pairing, protocol
from .i18n import _
from .store import append_line, read_json, read_lines, write_atomic, write_json

POLICY = "policy.json"
SIGNED = "signed-policy.json"
MACHINES = "machines.json"
FILES = "files"
COMMANDS = "commands.json"
RESULTS = "results.json"
INVENTORY = "inventory"
ASSETS = "assets.json"
AUDIT = "audit.jsonl"
OPTIONS = "options.json"      # {"approve_machines": bool}
HEALTH = "health.json"
SECRETS = "secrets.json"      # 0600 root: the Wi-Fi passphrases by network, to seal them for each machine
REMOVED = "removed.json"      # machines taken out of the company, with their key and signed notice, REMOVED_DAYS
PUBLIC_KEY = "public-key"
MAGIC = ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG\r\n\x1a\n", "png"))

MAX_COMMANDS = 1000
COMMAND_DAYS = 7
REMOVED_DAYS = 365
# How long a command waits for an offline machine (minutes): never more than a day (PROTOCOL.md), and short for
# what must not happen hours later, when someone turns the machine on.
COMMAND_MINUTES = {"sync": 10, "inventory": 60, "lock": 10, "message": 240, "logout": 10, "restart": 10,
                   "shutdown": 10, "cancel": 10, "update": 24 * 60, "remote_help": 3, "usb_unlock": 30}
ASSET_FIELDS = ("asset_code", "purchase_date", "price_vnd", "warranty_until", "holder", "location", "note")
ASSET_KINDS = ("computer", "laptop", "monitor", "printer", "other")
ASSET_STATES = ("in_stock", "in_use", "repair", "disposed")
ASSET_EVENTS = ("received", "assigned", "returned", "repair", "disposed", "note", "handover")
MAX_HISTORY = 200


def now_iso(now: datetime.datetime | None = None) -> str:
    return (now or datetime.datetime.now().astimezone()).isoformat(timespec="seconds")


def parse_iso(text: Any) -> datetime.datetime | None:
    try:
        value = datetime.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.astimezone()


# -- keys ---------------------------------------------------------------------------------------------------------

def ensure_key(path: Path = ADMIN_KEY, state: Path = ADMIN_STATE) -> Any:
    """The admin's Ed25519 key, made on first use (root only). Its public half goes to state/public-key, for the
    window to show the pairing code."""

    try:
        key = protocol.key_from_pem(path.read_bytes())
    except FileNotFoundError:
        key = protocol.new_key()
        write_atomic(path, protocol.key_to_pem(key), mode=0o600)
    public = base64.b64encode(protocol.public_bytes(key)) + b"\n"
    try:
        current = (state / PUBLIC_KEY).read_bytes()
    except OSError:
        current = b""
    if current != public:
        write_atomic(state / PUBLIC_KEY, public)
    return key


def read_public_key(state: Path = ADMIN_STATE) -> bytes:
    key = base64.b64decode((state / PUBLIC_KEY).read_text(encoding="ascii").strip(), validate=True)
    if len(key) != 32:
        raise ValueError("not an Ed25519 public key")
    return key


def ensure_box_key(path: Path = ADMIN_BOX_KEY) -> bytes:
    """The admin's X25519 box key, raw 32 bytes, made on first use (0600)."""

    try:
        private = path.read_bytes()
        if len(private) == 32:
            return private
    except FileNotFoundError:
        pass
    private = protocol.new_box_key()
    write_atomic(path, private, mode=0o600)
    return private


def read_box_key(path: Path = ADMIN_BOX_KEY) -> bytes:
    private = path.read_bytes()
    if len(private) != 32:
        raise ValueError("not an X25519 key")
    return private


# -- pictures ----------------------------------------------------------------------------------------------------------

def image_type(data: bytes) -> str | None:
    for magic, kind in MAGIC:
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def add_image(source: Path, state: Path = ADMIN_STATE) -> dict[str, Any]:
    """Copies a JPEG, PNG or WebP picture into the admin's files: {"sha256", "size", "type"}."""

    size = source.stat().st_size
    if not 0 < size <= protocol.MAX_FILE:
        raise protocol.ProtocolError(_("A picture must be at most 20 MB."))
    data = source.read_bytes()
    kind = image_type(data)
    if kind is None:
        raise protocol.ProtocolError(_("Not a JPEG, PNG or WebP picture."))
    sha = hashlib.sha256(data).hexdigest()
    target = state / FILES / sha
    if not target.exists():
        write_atomic(target, data)
    return {"sha256": sha, "size": len(data), "type": kind}


def used_files(policy: dict[str, Any], state: Path) -> dict[str, dict[str, Any]]:
    """The files entry for the pictures any layer's wallpaper uses, from the copies in state/files."""

    files = {}
    for sha in protocol.used_images(policy):
        try:
            data = (state / FILES / sha).read_bytes()
        except OSError as exc:
            raise protocol.ProtocolError(_("A picture is missing: choose it again."), section="wallpaper") from exc
        kind = image_type(data)
        if kind is None or hashlib.sha256(data).hexdigest() != sha:
            raise protocol.ProtocolError(_("A picture is damaged: choose it again."), section="wallpaper")
        files[sha] = {"size": len(data), "type": kind}
    return files


def remove_unused_files(state: Path = ADMIN_STATE) -> None:
    """Pictures no policy uses any more (the window adds one for every pick)."""

    keep = set(read_policy(state).get("files", {}))
    directory = state / FILES
    if not directory.is_dir():
        return
    for path in directory.iterdir():
        if path.name not in keep and len(path.name) == 64:
            if time.time() - path.stat().st_mtime > 3600:  # a picture just picked may belong to a draft not saved yet
                path.unlink(missing_ok=True)


# -- the policy --------------------------------------------------------------------------------------------------------

def empty_draft() -> dict[str, Any]:
    return {"settings": {}, "departments": {}, "members": {}, "machines": {}}


def from_format_1(policy: dict[str, Any]) -> dict[str, Any]:
    """A 0.1 policy.json (format 1) as format 2: its wallpaper and folders become company settings."""

    settings = {key: policy[key] for key in ("wallpaper", "folders") if policy.get(key) is not None}
    return {"format": protocol.FORMAT, "serial": policy.get("serial", 0), "issued": policy.get("issued", ""),
            "admin": policy.get("admin", ""), "files": policy.get("files", {}), "settings": settings,
            "departments": {}, "members": {}, "machines": {}}


def read_policy(state: Path = ADMIN_STATE) -> dict[str, Any]:
    """The policy saved last (format 2), or an empty one with serial 0."""

    policy = read_json(state / POLICY)
    if not isinstance(policy, dict):
        return dict(empty_draft(), format=protocol.FORMAT, serial=0, files={})
    if policy.get("format") == 1:
        return from_format_1(policy)
    return policy


def draft_from_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """What the window edits: the settings layers and the members, without the sealed secrets."""

    machines = {}
    for machine_id, machine in (policy.get("machines") or {}).items():
        if isinstance(machine, dict) and machine.get("settings"):
            machines[machine_id] = {"settings": copy.deepcopy(machine["settings"])}
    return {"settings": copy.deepcopy(policy.get("settings") or {}),
            "departments": copy.deepcopy(policy.get("departments") or {}),
            "members": dict(policy.get("members") or {}), "machines": machines}


def read_secrets(state: Path = ADMIN_STATE) -> dict[str, Any]:
    secrets = read_json(state / SECRETS, {})
    if not isinstance(secrets, dict) or not isinstance(secrets.get("wifi", {}), dict):
        return {"wifi": {}}
    return {"wifi": dict(secrets.get("wifi", {}))}


def read_removed(state: Path = ADMIN_STATE) -> dict[str, dict[str, Any]]:
    """{machine_id: {"time", "name", "box_key", "notice"}}; a 0.2 entry (just a time) has no key and no notice."""

    removed = read_json(state / REMOVED, {})
    if not isinstance(removed, dict):
        return {}
    return {key: value if isinstance(value, dict) else {"time": value} for key, value in removed.items()
            if isinstance(key, str)}


def read_options(state: Path = ADMIN_STATE) -> dict[str, Any]:
    options = read_json(state / OPTIONS, {})
    options = options if isinstance(options, dict) else {}
    return {"approve_machines": options.get("approve_machines") is True}


def write_options(options: Any, state: Path = ADMIN_STATE) -> dict[str, Any]:
    if not isinstance(options, dict) or not isinstance(options.get("approve_machines"), bool):
        raise protocol.ProtocolError(_("The options could not be read."))
    value = {"approve_machines": options["approve_machines"]}
    write_json(state / OPTIONS, value)
    return value


def approved(entry: Any) -> bool:
    """A machine that may read the company's settings: approved, or paired before approval existed (0.2)."""

    return isinstance(entry, dict) and entry.get("state", "approved") == "approved"


def _layers_of(draft: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    found = [("company", draft.get("settings") or {})]
    for department_id, department in (draft.get("departments") or {}).items():
        found.append((f"department:{department_id}", (department or {}).get("settings") or {}))
    for machine_id, machine in (draft.get("machines") or {}).items():
        found.append((f"machine:{machine_id}", (machine or {}).get("settings") or {}))
    return found


def wifi_networks(draft: dict[str, Any]) -> dict[str, str]:
    """Every Wi-Fi network any layer lists: {ssid: security}."""

    found: dict[str, str] = {}
    for _scope, settings in _layers_of(draft):
        for network in settings.get("wifi") or []:
            if isinstance(network, dict) and isinstance(network.get("ssid"), str):
                found[network["ssid"]] = network.get("security", "")
    return found


def clean_draft(draft: Any, machines: dict[str, Any]) -> dict[str, Any]:
    """The window's draft, kept to what can be saved: members and machine settings only for approved machines,
    members only of departments that exist."""

    if not isinstance(draft, dict):
        raise protocol.ProtocolError(_("The settings could not be read."))
    result = empty_draft()
    for key in ("settings", "departments", "members", "machines"):
        value = draft.get(key, {})
        if not isinstance(value, dict):
            raise protocol.ProtocolError(_("The settings could not be read."))
        result[key] = copy.deepcopy(value)
    result["members"] = {machine_id: department for machine_id, department in result["members"].items()
                         if approved(machines.get(machine_id)) and department in result["departments"]}
    kept = {}
    for machine_id, machine in result["machines"].items():
        if approved(machines.get(machine_id)) and isinstance(machine, dict) and machine.get("settings"):
            kept[machine_id] = {"settings": machine["settings"]}
    result["machines"] = kept
    return result


def _merged(*layers: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for layer in layers:
        result.update(layer or {})
    return result


def freeze_problem(policy: dict[str, Any]) -> tuple[str, str] | None:
    """The admin's rules of part 3 for `shared` (it never signs otherwise): (scope, sentence) of the first machine,
    department or company whose effective settings freeze without a maintenance time, or freeze together with
    folders tidy or with snapshots."""

    settings = policy.get("settings") or {}
    departments = policy.get("departments") or {}
    cases: list[tuple[str, dict[str, Any]]] = [("company", settings)]
    for department_id, department in departments.items():
        cases.append((f"department:{department_id}", _merged(settings, (department or {}).get("settings"))))
    for machine_id in set(policy.get("members") or {}) | set(policy.get("machines") or {}):
        cases.append((f"machine:{machine_id}", protocol.effective_settings(policy, machine_id)))
    for scope, effective in cases:
        shared = effective.get("shared") or {}
        if not shared.get("freeze"):
            continue
        if not shared.get("maintenance"):
            return scope, _("A frozen machine needs a maintenance time, when it takes its updates.")
        if (effective.get("folders") or {}).get("tidy"):
            return scope, _("Freezing and tidying Desktop and Documents onto the server cannot be on together: the "
                            "tidied files would come back at every reboot.")
        if effective.get("snapshots"):
            return scope, _("Freezing and system snapshots cannot be on together: Timeshift would write to the disk "
                            "under the frozen system.")
    return None


def seal_for_machines(policy: dict[str, Any], machines: dict[str, Any], passphrases: dict[str, str],
                      box_private: bytes) -> None:
    """Puts each paired machine's Wi-Fi passphrases, sealed with its box key, in policy["machines"][id]["sealed"]:
    only the networks of its effective settings."""

    for machine_id, entry in machines.items():
        box_key = entry.get("box_key") if isinstance(entry, dict) else None
        if not box_key or not approved(entry):
            continue
        networks = protocol.effective_settings(policy, machine_id).get("wifi") or []
        wifi = {network["ssid"]: passphrases[network["ssid"]] for network in networks
                if network.get("security") == "wpa-psk" and network["ssid"] in passphrases}
        if not wifi:
            continue
        _mac_key, seal_key = protocol.machine_keys(box_private, protocol.unb64(box_key, 32))
        machine = policy["machines"].setdefault(machine_id, {})
        machine["sealed"] = protocol.seal(seal_key, machine_id, {"wifi": wifi})


def build_policy(draft: dict[str, Any], state: Path, *, serial: int, name: str, box_private: bytes,
                 now: datetime.datetime | None = None) -> dict[str, Any]:
    policy: dict[str, Any] = {
        "format": protocol.FORMAT,
        "serial": serial,
        "issued": now_iso(now),
        "admin": name[:64],
        "admin_box_key": protocol.b64(protocol.box_public(box_private)),
    }
    policy.update(settings=draft["settings"], departments=draft["departments"], members=draft["members"],
                  machines=copy.deepcopy(draft["machines"]))
    policy["files"] = used_files(policy, state)
    return policy


def save_policy(draft: dict[str, Any], key: Any, name: str, state: Path = ADMIN_STATE,
                now: datetime.datetime | None = None, *, box_private: bytes | None = None,
                passphrases: dict[str, str] | None = None, min_serial: int = 0) -> dict[str, Any]:
    """Saves the window's draft as the next serial, its Wi-Fi passphrases sealed for each machine, signed: what
    GET /policy answers from now on. passphrases are the ones typed since the last save (by network); the others
    come from secrets.json. Call it with locked(state)."""

    now = now or datetime.datetime.now().astimezone()
    box_private = box_private if box_private is not None else read_box_key()
    machines = read_machines(state)
    draft = clean_draft(draft, machines)
    secrets = read_secrets(state)
    networks = wifi_networks(draft)
    for ssid, passphrase in (passphrases or {}).items():
        if ssid in networks:
            if not protocol.valid_passphrase(passphrase):
                raise protocol.ProtocolError(_("A Wi-Fi password has 8 to 63 letters, digits or signs, without "
                                               "Vietnamese accents."), section="wifi")
            secrets["wifi"][ssid] = passphrase
    secrets["wifi"] = {ssid: value for ssid, value in secrets["wifi"].items() if networks.get(ssid) == "wpa-psk"}
    for ssid, security in networks.items():
        if security == "wpa-psk" and ssid not in secrets["wifi"]:
            raise protocol.ProtocolError(_("Type the password of the Wi-Fi network “%s”.") % ssid, section="wifi")
    old = read_policy(state)
    policy = build_policy(draft, state, serial=max(int(old.get("serial", 0)) + 1, min_serial), name=name,
                          box_private=box_private, now=now)
    problem = freeze_problem(policy)
    if problem:
        raise protocol.ProtocolError(problem[1], section="shared", scope=problem[0])
    seal_for_machines(policy, machines, secrets["wifi"], box_private)
    signed = protocol.sign_policy(key, policy)  # validates, and refuses over 1 MiB
    write_json(state / SECRETS, secrets, mode=0o600)
    write_json(state / POLICY, policy)
    write_json(state / SIGNED, signed)
    for machine_id in machines:  # the inventory is opt-in: none is kept where it is no longer on
        if not protocol.effective_settings(policy, machine_id).get("inventory"):
            (state / INVENTORY / f"{machine_id}.json").unlink(missing_ok=True)
    return policy


def needs_seal(policy: dict[str, Any], machine_id: str) -> bool:
    """Whether a machine has Wi-Fi passphrases to get but no sealed secrets in the policy (it paired after the last
    save)."""

    networks = protocol.effective_settings(policy, machine_id).get("wifi") or []
    wants = any(network.get("security") == "wpa-psk" for network in networks)
    return wants and not ((policy.get("machines") or {}).get(machine_id) or {}).get("sealed")


def changes(old: dict[str, Any], new: dict[str, Any]) -> list[tuple[str, str]]:
    """What a save changed, for the audit log: [(scope, section)]; section "departments" and "members" for those."""

    found = []
    old_layers, new_layers = dict(_layers_of(old)), dict(_layers_of(new))
    for scope in list(dict.fromkeys(list(old_layers) + list(new_layers))):
        before, after = old_layers.get(scope, {}), new_layers.get(scope, {})
        for section in list(dict.fromkeys(list(before) + list(after))):
            if section not in protocol.SECTIONS:
                continue
            if (section in before) != (section in after) or before.get(section) != after.get(section):
                found.append((scope, section))
    names = lambda draft: {key: (value or {}).get("name") for key, value in (draft.get("departments") or {}).items()}
    if names(old) != names(new):
        found.append(("company", "departments"))
    if (old.get("members") or {}) != (new.get("members") or {}):
        found.append(("company", "members"))
    return found


# -- pairing and machines ----------------------------------------------------------------------------------------------

def open_pairing(seconds: int = protocol.PAIRING_SECONDS, path: Path = PAIRING, now: float | None = None
                 ) -> dict[str, Any]:
    """A new pairing window with a new random code (pairing.py): {"code", "until"}."""

    return pairing.open_pairing(path, seconds, now)


def close_pairing(path: Path = PAIRING) -> None:
    pairing.close_pairing(path)


def pairing_open(path: Path = PAIRING, now: float | None = None) -> bool:
    return pairing.read_pairing(path, now) is not None


def read_machines(state: Path = ADMIN_STATE) -> dict[str, Any]:
    machines = read_json(state / MACHINES, {})
    return machines if isinstance(machines, dict) else {}


def register(machine: dict[str, str], box_key: str, state: Path = ADMIN_STATE,
             now: datetime.datetime | None = None, *, via: str = "code", pending: bool = False,
             department: str | None = None, replaced: list[str] | None = None) -> str:
    """Adds a machine that paired (with a code, or "enroll:<token_id>"), with its public box key; its machine_id.
    A pending machine waits for "Duyệt"; it keeps the token's department until then. The ids of the entries it
    replaces (the same computer pairing again) go into replaced. Call it with locked(state)."""

    machines = read_machines(state)
    machine_id = str(uuid.uuid4())
    # The same computer pairing again replaces its old entry; its asset details move to the new one, and what it
    # reported goes (it reports again).
    for old_id, entry in list(machines.items()):
        if entry.get("machine", {}).get("mac") and entry["machine"].get("mac") == machine.get("mac"):
            del machines[old_id]
            carry_over(old_id, machine_id, state)
            if replaced is not None:
                replaced.append(old_id)
    machines[machine_id] = {"machine": machine, "box_key": box_key, "paired": now_iso(now), "last_seen": now_iso(now),
                            "policy_serial": None, "users": [], "health": None, "capabilities": [],
                            "state": "pending" if pending else "approved", "via": via}
    if department:
        machines[machine_id]["department"] = department
    write_json(state / MACHINES, machines)
    return machine_id


def carry_over(old_id: str, new_id: str, state: Path) -> None:
    """A machine paired again: its asset record moves to its new id; its inventory and health of the old pairing go.
    Call it with locked(state)."""

    stored = read_assets(state)
    if isinstance(stored.get(old_id), dict) and new_id not in stored:
        entry = stored.pop(old_id)
        if entry.get("machine_id"):
            entry["machine_id"] = new_id
        stored[new_id] = entry
        write_json(state / ASSETS, stored)
    (state / INVENTORY / f"{old_id}.json").unlink(missing_ok=True)
    records = read_json(state / HEALTH, {})
    if isinstance(records, dict) and records.pop(old_id, None) is not None:
        write_json(state / HEALTH, records)


def approve_machine(machine_id: str, state: Path = ADMIN_STATE) -> dict[str, Any] | None:
    """A pending machine becomes approved; its entry. Call it with locked(state)."""

    machines = read_machines(state)
    entry = machines.get(machine_id)
    if not isinstance(entry, dict) or approved(entry):
        return None
    entry["state"] = "approved"
    write_json(state / MACHINES, machines)
    return entry


def reject_machine(machine_id: str, state: Path = ADMIN_STATE) -> dict[str, Any] | None:
    """A pending machine is deleted, without a removal notice (it never got anything). Call it with locked(state)."""

    machines = read_machines(state)
    entry = machines.get(machine_id)
    if not isinstance(entry, dict) or approved(entry):
        return None
    del machines[machine_id]
    write_json(state / MACHINES, machines)
    return entry


def check_in(machine_id: str, report: dict[str, Any], state: Path = ADMIN_STATE,
             now: datetime.datetime | None = None) -> dict[str, Any] | None:
    """Records a check-in (validated by protocol.validate_checkin); the machine's entry, or None when unknown.
    Health and capabilities stay as they were when a check-in has none. Call it with locked(state)."""

    machines = read_machines(state)
    entry = machines.get(machine_id)
    if not isinstance(entry, dict):
        return None
    previous = (entry.get("machine") or {}).get("mac")
    entry.update(machine=report["machine"], last_seen=now_iso(now), policy_serial=report["policy_serial"],
                 users=report["users"])
    mac = report["machine"].get("mac")
    if mac:
        # The cards it reported from lately, and when it changed card: back and forth within minutes is two machines
        # with a cloned disk (health.py).
        seen = {key: value for key, value in (entry.get("macs") or {}).items() if isinstance(value, str)}
        seen[mac] = now_iso(now)
        entry["macs"] = dict(sorted(seen.items(), key=lambda item: item[1])[-8:])
        if previous and previous != mac:
            switches = [value for value in entry.get("mac_switches") or [] if isinstance(value, str)]
            entry["mac_switches"] = [*switches, now_iso(now)][-8:]
    for key in ("health", "capabilities"):
        if key in report:
            entry[key] = report[key]
    write_json(state / MACHINES, machines)
    return entry


def forget_machine(machine_id: str, state: Path = ADMIN_STATE, now: datetime.datetime | None = None, *,
                   key: Any = None, admin_name: str = "", by: str = "") -> bool:
    """Takes a machine out ("Gỡ khỏi công ty"): its entry, inventory and health go. removed.json keeps it for
    REMOVED_DAYS with its box key and a removal notice signed with key, which the server answers its GET /policy
    with, so that its agent puts everything back. Its asset record, when the admin typed anything into it, stays as a
    thing without a machine (asset-<uuid4>, named after the machine): the computer is still the company's, and its
    history and the leaver's steps are what IT needs afterwards. Call it with locked(state)."""

    machines = read_machines(state)
    entry = machines.pop(machine_id, None)
    if entry is None:
        return False
    write_json(state / MACHINES, machines)
    (state / INVENTORY / f"{machine_id}.json").unlink(missing_ok=True)
    now = now or datetime.datetime.now().astimezone()
    health = read_json(state / HEALTH, {})
    if isinstance(health, dict) and health.pop(machine_id, None) is not None:
        write_json(state / HEALTH, health)
    assets = read_json(state / ASSETS, {})
    if isinstance(assets, dict) and machine_id in assets:
        record = assets.pop(machine_id)
        if isinstance(record, dict) and (record.get("history") or any(record.get(field) for field in ASSET_FIELDS)):
            history = [item for item in record.get("history") or [] if isinstance(item, dict)]
            history.append({"time": now_iso(now), "event": "note", "by": by, "note": _("Taken out of the company.")})
            assets[f"asset-{uuid.uuid4()}"] = dict(record, machine_id=None, history=history[-MAX_HISTORY:],
                                                   name=machine_name({machine_id: entry}, machine_id))
        write_json(state / ASSETS, assets)
    removed = {key_: value for key_, value in read_removed(state).items()
               if (since := parse_iso(value.get("time"))) and now - since < datetime.timedelta(days=REMOVED_DAYS)}
    record: dict[str, Any] = {"time": now_iso(now), "name": machine_name({machine_id: entry}, machine_id)}
    if isinstance(entry, dict) and entry.get("box_key") and key is not None:
        record["box_key"] = entry["box_key"]
        record["notice"] = protocol.sign_notice(key, machine_id, admin_name, record["time"])
    removed[machine_id] = record
    write_json(state / REMOVED, removed)
    return True


def machine_name(machines: dict[str, Any], machine_id: str) -> str:
    entry = machines.get(machine_id) or {}
    return (entry.get("machine") or {}).get("name") or machine_id[:8]


# -- commands and results ----------------------------------------------------------------------------------------------

def read_commands(state: Path = ADMIN_STATE) -> dict[str, Any]:
    store = read_json(state / COMMANDS, {})
    if not isinstance(store, dict) or not isinstance(store.get("commands"), list):
        return {"seq": int(store.get("seq", 0)) if isinstance(store, dict) else 0, "commands": []}
    return store


def command_of(envelope: Any) -> dict[str, Any] | None:
    """The command inside an envelope the helper wrote (no signature check: the window reads its own state)."""

    try:
        command = json.loads(envelope["command"])
    except (TypeError, KeyError, ValueError):
        return None
    return command if isinstance(command, dict) else None


def prune_commands(store: dict[str, Any], now: datetime.datetime) -> dict[str, Any]:
    """Only the last 7 days, at most 1000."""

    kept = []
    for envelope in store["commands"]:
        command = command_of(envelope)
        issued = parse_iso(command.get("issued")) if command else None
        if issued and now - issued <= datetime.timedelta(days=COMMAND_DAYS):
            kept.append(envelope)
    store["commands"] = kept[-MAX_COMMANDS:]
    return store


def make_command(targets: dict[str, Any], action: str, args: dict[str, Any], seq: int,
                 now: datetime.datetime | None = None, minutes: int | None = None) -> dict[str, Any]:
    now = now or datetime.datetime.now().astimezone()
    lifetime = min(minutes or COMMAND_MINUTES.get(action, 10), 24 * 60)
    return {"seq": seq, "id": str(uuid.uuid4()), "targets": targets, "action": action, "args": args,
            "issued": now_iso(now), "expires": now_iso(now + datetime.timedelta(minutes=lifetime))}


def queue_command(key: Any, targets: dict[str, Any], action: str, args: dict[str, Any],
                  state: Path = ADMIN_STATE, now: datetime.datetime | None = None,
                  minutes: int | None = None) -> dict[str, Any]:
    """Signs a command with the next seq and puts it in commands.json, for /wait. Call it with locked(state)."""

    now = now or datetime.datetime.now().astimezone()
    store = read_commands(state)
    command = make_command(targets, action, args, int(store.get("seq", 0)) + 1, now, minutes)
    envelope = protocol.sign_command(key, command)  # validates
    store["seq"] = command["seq"]
    store["commands"].append(envelope)
    write_json(state / COMMANDS, prune_commands(store, now))
    results = read_results(state)
    known = {command_of(item)["id"] for item in store["commands"] if command_of(item)}
    if set(results) - known:
        write_json(state / RESULTS, {key_: value for key_, value in results.items() if key_ in known})
    return command


def read_results(state: Path = ADMIN_STATE) -> dict[str, Any]:
    results = read_json(state / RESULTS, {})
    return results if isinstance(results, dict) else {}


def record_result(machine_id: str, result: dict[str, Any], known_ids: set[str], state: Path = ADMIN_STATE,
                  now: datetime.datetime | None = None) -> bool:
    """Keeps a machine's result of a command that is still in commands.json. Call it with locked(state)."""

    if result["id"] not in known_ids:
        return False
    results = read_results(state)
    results.setdefault(result["id"], {})[machine_id] = dict(result, received=now_iso(now))
    write_json(state / RESULTS, results)
    return True


# -- inventory and assets ----------------------------------------------------------------------------------------------

def write_inventory(machine_id: str, inventory: dict[str, Any], state: Path = ADMIN_STATE,
                    now: datetime.datetime | None = None) -> None:
    write_json(state / INVENTORY / f"{machine_id}.json", dict(inventory, received=now_iso(now)))


def read_inventory(machine_id: str, state: Path = ADMIN_STATE) -> dict[str, Any] | None:
    if not protocol.UUID.match(machine_id):
        return None
    inventory = read_json(state / INVENTORY / f"{machine_id}.json")
    return inventory if isinstance(inventory, dict) else None


def read_assets(state: Path = ADMIN_STATE) -> dict[str, Any]:
    assets = read_json(state / ASSETS, {})
    return assets if isinstance(assets, dict) else {}


def _date_or_empty(value: Any) -> bool:
    if value == "":
        return True
    try:
        datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return isinstance(value, str) and len(value) == 10


def validate_asset(asset: Any) -> dict[str, Any]:
    """The fields the admin types for a machine (assets.json): dates as YYYY-MM-DD, the price in đồng."""

    if not isinstance(asset, dict):
        raise protocol.ProtocolError(_("The asset details could not be read."))
    result: dict[str, Any] = {}
    for field, limit in (("asset_code", 40), ("holder", 60), ("location", 60), ("note", 300)):
        value = asset.get(field, "")
        if not protocol._clean_text(value, limit, newlines=field == "note"):  # noqa: SLF001 - the same rule
            raise protocol.ProtocolError(_("A field is too long."))
        result[field] = value.strip()
    for field in ("purchase_date", "warranty_until"):
        value = asset.get(field, "")
        if not _date_or_empty(value):
            raise protocol.ProtocolError(_("Write dates as day/month/year, such as 15/3/2024."))
        result[field] = value
    price = asset.get("price_vnd")
    if price is not None and not (protocol._int(price) and 0 <= price <= 10 ** 12):  # noqa: SLF001
        raise protocol.ProtocolError(_("The price is a whole number of đồng."))
    result["price_vnd"] = price
    return result


def set_asset(machine_id: str, asset: dict[str, Any], state: Path = ADMIN_STATE) -> None:
    """Call it with locked(state)."""

    assets = read_assets(state)
    assets[machine_id] = asset
    write_json(state / ASSETS, assets)


# -- health ------------------------------------------------------------------------------------------------------------

def read_health(state: Path = ADMIN_STATE) -> dict[str, Any]:
    health = read_json(state / HEALTH, {})
    return health if isinstance(health, dict) else {}


# -- the audit log -----------------------------------------------------------------------------------------------------

def pkexec_user() -> str:
    """The account that ran the window, from PKEXEC_UID (pkexec sets it)."""

    try:
        return pwd.getpwuid(int(os.environ["PKEXEC_UID"])).pw_name
    except (KeyError, ValueError):
        return os.environ.get("SUDO_USER", "root")


def audit(action: str, summary: str, user: str, state: Path = ADMIN_STATE,
          now: datetime.datetime | None = None, /, **details: Any) -> None:
    """One line of audit.jsonl. details are keyword-only, so that none of them is taken for state or now."""

    line = {"time": now_iso(now), "user": user, "action": action, "summary": summary[:500]}
    if details:
        line["details"] = details
    append_line(state / AUDIT, line)


def read_audit(state: Path = ADMIN_STATE, limit: int = 500) -> list[dict[str, Any]]:
    return [line for line in read_lines(state / AUDIT, limit) if isinstance(line, dict)]


# -- the state folder --------------------------------------------------------------------------------------------------

def prepare_state(state: Path = ADMIN_STATE) -> None:
    """The state folder: readable by the sudo group, whose members polkit lets run the helper (the window runs as
    the user); by everyone where there is no such group."""

    state.mkdir(parents=True, exist_ok=True)
    try:
        group = grp.getgrnam("sudo").gr_gid
    except KeyError:
        os.chmod(state, 0o755)
    else:
        if os.geteuid() == 0:
            os.chown(state, 0, group)
        os.chmod(state, 0o750)
    for name in (FILES, INVENTORY):
        (state / name).mkdir(exist_ok=True)
        os.chmod(state / name, 0o755)


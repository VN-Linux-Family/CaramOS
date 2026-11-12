"""Print Screen and Super+Shift+S start Flameshot's capture, as CaramOS has meant them to since its first builds.

CaramOS takes the screenshot keys away from Cinnamon (99_caramos.gschema.override empties the media-keys) and
gives them to Flameshot through two custom shortcuts: custom0 (Super+Shift+S) and custom1 (Print). Their values
were in that override too, under [schema:/path/] groups. GLib reads the part after the colon as a desktop name,
not a path, so the values never applied and neither key did anything. Custom shortcuts live at relocatable paths,
whose defaults only dconf can give: the system defaults are now /etc/dconf/db/local.d/02-caramos-screenshot-keys
(new users, ISO builds, the same file as the ISO's), and every existing user gets the two shortcuts through
gsettings, unless
- the slot is set: the user's own shortcut there, or the system defaults already apply;
- the key already does something else for that user, such as their own shortcut on Print.
Cinnamon reads the custom shortcuts again only when custom-list changes, so the list is written again: the keys
work at once, without a new login.

Cinnamon 6.6 crashes when the system dconf database is rebuilt (`dconf update`) under a running session (see
20261012180000_add_help_applet): with someone logged in, the database waits for a later `dconf update`.
"""

from __future__ import annotations

import ast
import os
import pwd
import re
import subprocess
from pathlib import Path
from typing import Any, NamedTuple

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Make Print Screen and Super+Shift+S start Flameshot"

FLAMESHOT = Path("/usr/bin/flameshot")
DCONF_FILE = Path("/etc/dconf/db/local.d/02-caramos-screenshot-keys")
KEYBINDINGS = "org.cinnamon.desktop.keybindings"
CUSTOM_SCHEMA = "org.cinnamon.desktop.keybindings.custom-keybinding"
CUSTOM_PATH = "/org/cinnamon/desktop/keybindings/custom-keybindings/"
# Cinnamon's own shortcuts: a key one of them uses is not given to Flameshot.
CINNAMON_SCHEMAS = ("org.cinnamon.desktop.keybindings.media-keys", "org.cinnamon.desktop.keybindings.wm",
                    "org.cinnamon.muffin.keybindings")
MODIFIERS = {"primary": "control", "ctrl": "control", "control": "control", "mod1": "alt", "mod4": "super"}


# NamedTuple, not @dataclass: the runner loads migrations without registering them in sys.modules.
class Shortcut(NamedTuple):
    slot: str
    name: str
    command: str
    key: str


SHORTCUTS = (
    Shortcut("custom0", "Flameshot", "flameshot gui", "<Super><Shift>s"),
    Shortcut("custom1", "Flameshot Print", "flameshot gui", "Print"),
)


def gvariant_string(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def gvariant_strv(items: list[str]) -> str:
    return "[" + ", ".join(gvariant_string(item) for item in items) + "]" if items else "@as []"


def parse(value: str) -> Any:
    """A value gsettings printed ('text', ['a', 'b'], @as []), or None when it is not one."""

    text = value.strip()
    if text.startswith("@"):
        text = text.split(None, 1)[1] if " " in text else ""
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None


def accelerator(text: str) -> tuple[frozenset[str], str] | None:
    """A GTK accelerator ("<Super><Shift>s", "<Mod4><Shift>S", "Print") as (modifiers, key), to compare them."""

    key = re.sub(r"<[^>]*>", "", text).strip().lower()
    if not key:
        return None
    modifiers = frozenset(MODIFIERS.get(name.lower(), name.lower()) for name in re.findall(r"<([^>]*)>", text))
    return modifiers, key


def accelerators(value: Any) -> set[tuple[frozenset[str], str]]:
    """The keys of a keybinding value: a string or a list of strings."""

    items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return {key for item in items if isinstance(item, str) for key in [accelerator(item)] if key is not None}


def dconf_defaults() -> str:
    """The system dconf defaults of the two shortcuts (also the ISO's 02-caramos-screenshot-keys)."""

    lines = ["# CaramOS: Print Screen and Super+Shift+S start Flameshot's capture (custom-list is in",
             "# 99_caramos.gschema.override; Cinnamon's own screenshot keys are emptied there). Custom shortcuts",
             "# live at relocatable paths, whose defaults gschema overrides cannot set: dconf sets them here."]
    for shortcut in SHORTCUTS:
        lines += ["", f"[{CUSTOM_PATH.strip('/')}/{shortcut.slot}]",
                  f"name={gvariant_string(shortcut.name)}",
                  f"command={gvariant_string(shortcut.command)}",
                  f"binding={gvariant_strv([shortcut.key])}"]
    return "\n".join(lines) + "\n"


def list_writes(current: list[str], final: list[str]) -> list[list[str]]:
    """The custom-list values to write so Cinnamon reads the custom shortcuts again, ending with final.

    A list that changes is written once. Otherwise it is written in another order first, so the user's own
    shortcuts stay in the list whatever happens between the two writes.
    """

    if final != current:
        return [final]
    if len(final) > 1:
        return [list(reversed(final)), final]
    return [[], final]


def _desktop_users() -> list[tuple[str, int, Path]]:
    """People who log in: not system users, nor the dynamic users of services such as earlyoom (uid 61184+)."""

    users = []
    for entry in pwd.getpwall():
        if not 1000 <= entry.pw_uid < 60000 or entry.pw_shell.endswith(("/nologin", "/false")):
            continue
        if entry.pw_dir not in ("", "/", "/nonexistent") and Path(entry.pw_dir).is_dir():
            users.append((entry.pw_name, entry.pw_uid, Path(entry.pw_dir)))
    return sorted(users, key=lambda item: item[1])


def _session_bus(uid: int) -> Path:
    return Path(f"/run/user/{uid}/bus")


def _user_environment(username: str, uid: int, home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update({"HOME": str(home), "USER": username, "LOGNAME": username})
    runtime_dir = _session_bus(uid).parent
    if _session_bus(uid).exists():
        # A running session sees the change at once: Cinnamon binds the keys without a new login.
        env.update({"XDG_RUNTIME_DIR": str(runtime_dir), "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime_dir}/bus"})
    else:
        env.pop("DBUS_SESSION_BUS_ADDRESS", None)
    return env


def _gsettings(username: str, env: dict[str, str], args: list[str]) -> subprocess.CompletedProcess[str]:
    command = ["runuser", "-u", username, "--"]
    if "DBUS_SESSION_BUS_ADDRESS" not in env:
        command += ["dbus-run-session", "--"]
    return subprocess.run([*command, "gsettings", *args], check=False, capture_output=True, text=True, env=env)


def _slot_schema(slot: str) -> str:
    return f"{CUSTOM_SCHEMA}:{CUSTOM_PATH}{slot}/"


def _fix_for_user(context: MigrationContext, username: str, uid: int, home: Path) -> None:
    env = _user_environment(username, uid, home)

    def get(schema: str, key: str) -> Any:
        result = _gsettings(username, env, ["get", schema, key])
        return parse(result.stdout) if result.returncode == 0 else None

    slots = get(KEYBINDINGS, "custom-list")
    if not isinstance(slots, list) or not all(isinstance(slot, str) for slot in slots):
        context.log(f"warning: could not read the custom shortcuts of {username}; leave them as they are")
        return
    taken: set[tuple[frozenset[str], str]] = set()
    for schema in CINNAMON_SCHEMAS:
        result = _gsettings(username, env, ["list-recursively", schema])
        for line in result.stdout.splitlines() if result.returncode == 0 else ():
            parts = line.split(None, 2)
            if len(parts) == 3:
                taken |= accelerators(parse(parts[2]))
    for slot in slots:
        taken |= accelerators(get(_slot_schema(slot), "binding"))

    final = list(slots)
    done = []
    for shortcut in SHORTCUTS:
        schema = _slot_schema(shortcut.slot)
        command, binding = get(schema, "command"), get(schema, "binding")
        if not isinstance(command, str) or not isinstance(binding, list):
            context.log(f"warning: could not read {shortcut.slot} of {username}; leave it as it is")
            continue
        if command or binding:
            context.log(f"{shortcut.slot} of {username} is set ({command!r}, {binding}): leave it as it is")
            continue
        key = accelerator(shortcut.key)
        if key in taken:
            context.log(f"{shortcut.key} does something else for {username}: leave {shortcut.slot} empty")
            continue
        values = (("name", gvariant_string(shortcut.name)), ("command", gvariant_string(shortcut.command)),
                  ("binding", gvariant_strv([shortcut.key])))
        failed = [result.stderr.strip() for name, value in values
                  for result in [_gsettings(username, env, ["set", schema, name, value])] if result.returncode != 0]
        if failed:
            context.log(f"warning: could not set {shortcut.slot} of {username}: {failed[0]}")
            continue
        taken.add(key)
        if shortcut.slot not in final:
            final.append(shortcut.slot)
        done.append(shortcut.key)
    if not done:
        return
    for value in list_writes(slots, final):
        result = _gsettings(username, env, ["set", KEYBINDINGS, "custom-list", gvariant_strv(value)])
        if result.returncode != 0:
            context.log(f"warning: could not write the custom shortcut list of {username}: {result.stderr.strip()}")
            return
    context.log(f"{' and '.join(done)} start Flameshot for {username}")


def run(context: MigrationContext) -> None:
    if not FLAMESHOT.exists():
        context.log(f"{FLAMESHOT} is not installed; the screenshot keys are left as they are")
        return
    users = _desktop_users()
    content = dconf_defaults()
    defaults_changed = not (DCONF_FILE.is_file() and DCONF_FILE.read_text(encoding="utf-8") == content)
    context.write_file_if_changed(DCONF_FILE, content)
    if context.dry_run:
        context.log("make Print Screen and Super+Shift+S start Flameshot for every desktop user")
        return
    if defaults_changed:
        logged_in = [username for username, uid, _home in users if _session_bus(uid).exists()]
        if logged_in:
            context.log(f"{', '.join(logged_in)} logged in: dconf update waits, Cinnamon would crash under it")
        else:
            context.run_command(["dconf", "update"], allow_fail=True)
    for username, uid, home in users:
        _fix_for_user(context, username, uid, home)

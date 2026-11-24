"""Print Screen copies the whole screen to the clipboard, with a short notification, as on Windows 10 (tickets H-1188
and H-1193): caramos-print-screen (this package). Super+Shift+S still opens Flameshot to pick a part of the screen.

Before, Print Screen opened Flameshot's capture, the same as Super+Shift+S (migration 20261112100000).

- Cinnamon: the custom shortcut on Print, custom1. CaramOS's system defaults (/etc/dconf/db/local.d/02-caramos-
  screenshot-keys, the ISO's file) change where they are still 20261112100000's, and each user whose shortcut on
  Print still runs "flameshot gui" gets the new command through gsettings, as in that migration; Cinnamon reads the
  custom shortcuts again when their list changes, so the list is written again and the key works at once.
- Xfce: Print in CaramOS's default shortcuts (the ISO's xfce4-keyboard-shortcuts.xml), and for each user with
  shortcuts of their own whose Print still runs "flameshot gui", through xfconf-query as migration 20261120100000
  does; Xfce takes it at once.

A Print shortcut someone changed stays theirs. Cinnamon 6.6 crashes when the system dconf database is rebuilt under a
running session: with someone logged in, `dconf update` waits for a later one (see 20261112100000).
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Any

from caramos_ota_update.context import MigrationContext
from caramos_ota_update.desktop import CINNAMON, XFCE, current_desktop

DESCRIPTION = "Print Screen copies the whole screen to the clipboard"

screenshot = importlib.import_module("caramos_ota_update.migrations.20261112100000_screenshot_shortcuts.migration")
clipboard = importlib.import_module("caramos_ota_update.migrations.20261120100000_clipboard_history.migration")
accelerator = screenshot.accelerator

COMMAND = "caramos-print-screen"
FLAMESHOT = "flameshot gui"
NAME = "Screenshot to clipboard"  # the shortcut's name in Cinnamon's keyboard settings
KEY = "Print"
DCONF_FILE = screenshot.DCONF_FILE
SHORTCUTS = tuple(shortcut._replace(name=NAME, command=COMMAND) if shortcut.key == KEY else shortcut
                  for shortcut in screenshot.SHORTCUTS)
XFCE_SHORTCUTS = clipboard.XFCE_SHORTCUTS
XFCE_BEFORE = f'<property name="{KEY}" type="string" value="{FLAMESHOT}"/>'
XFCE_AFTER = f'<property name="{KEY}" type="string" value="{COMMAND}"/>'


def dconf_defaults() -> str:
    """CaramOS's system defaults of the two screenshot shortcuts (also the ISO's 02-caramos-screenshot-keys)."""

    lines = ["# CaramOS: Super+Shift+S starts Flameshot's capture, and Print Screen copies the whole screen to the",
             "# clipboard (caramos-print-screen). custom-list is in 99_caramos.gschema.override, where Cinnamon's own",
             "# screenshot keys are emptied. Custom shortcuts live at relocatable paths, whose defaults gschema",
             "# overrides cannot set: dconf sets them here."]
    for shortcut in SHORTCUTS:
        lines += ["", f"[{screenshot.CUSTOM_PATH.strip('/')}/{shortcut.slot}]",
                  f"name={screenshot.gvariant_string(shortcut.name)}",
                  f"command={screenshot.gvariant_string(shortcut.command)}",
                  f"binding={screenshot.gvariant_strv([shortcut.key])}"]
    return "\n".join(lines) + "\n"


def cinnamon_defaults(context: MigrationContext, users: list[tuple[str, int, Path]], path: Path = DCONF_FILE) -> None:
    try:
        current = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = None
    except (OSError, UnicodeDecodeError):
        context.log(f"{path} cannot be read; left alone")
        return
    if current == dconf_defaults():
        context.log(f"{path} has Print Screen to the clipboard already")
        return
    if current is not None and current != screenshot.dconf_defaults():
        context.log(f"{path} was changed by hand; left alone")
        return
    context.write_file_if_changed(path, dconf_defaults())
    if context.dry_run:
        return
    logged_in = [username for username, uid, _home in users if screenshot._session_bus(uid).exists()]
    if logged_in:
        context.log(f"{', '.join(logged_in)} logged in: dconf update waits, Cinnamon would crash under it")
    else:
        context.run_command(["dconf", "update"], allow_fail=True)


def cinnamon_user(context: MigrationContext, username: str, uid: int, home: Path) -> None:
    env = screenshot._user_environment(username, uid, home)

    def get(schema: str, key: str) -> Any:
        result = screenshot._gsettings(username, env, ["get", schema, key])
        return screenshot.parse(result.stdout) if result.returncode == 0 else None

    slots = get(screenshot.KEYBINDINGS, "custom-list")
    if not isinstance(slots, list) or not all(isinstance(slot, str) for slot in slots):
        context.log(f"warning: could not read the custom shortcuts of {username}; leave them as they are")
        return
    changed = []
    for slot in slots:
        schema = screenshot._slot_schema(slot)
        command, binding = get(schema, "command"), get(schema, "binding")
        if command != FLAMESHOT or accelerator(KEY) not in screenshot.accelerators(binding):
            continue
        failed = [result.stderr.strip() for setting, value in (("name", screenshot.gvariant_string(NAME)),
                                                               ("command", screenshot.gvariant_string(COMMAND)))
                  for result in [screenshot._gsettings(username, env, ["set", schema, setting, value])]
                  if result.returncode != 0]
        if failed:
            context.log(f"warning: could not change {slot} of {username}: {failed[0]}")
            return
        changed.append(slot)
    if not changed:
        context.log(f"Print Screen of {username} does not run Flameshot's capture: left as it is")
        return
    # Cinnamon binds custom shortcuts again when their list changes.
    for value in screenshot.list_writes(slots, slots):
        result = screenshot._gsettings(username, env, ["set", screenshot.KEYBINDINGS, "custom-list",
                                                       screenshot.gvariant_strv(value)])
        if result.returncode != 0:
            context.log(f"warning: could not write the custom shortcut list of {username}: {result.stderr.strip()}")
            return
    context.log(f"Print Screen copies the screen to the clipboard for {username} ({', '.join(changed)})")


def xfce_defaults_updated(text: str) -> str:
    """CaramOS's Xfce shortcuts with Print running caramos-print-screen; "" when Print does not run Flameshot's capture
    there, or the file is not as expected."""

    if clipboard._commands_default(text) is None:
        return ""
    matches = [match for match in re.finditer(rf"^([ \t]*){re.escape(XFCE_BEFORE)}[ \t]*$", text, re.M)]
    if len(matches) != 1:
        return ""
    new = text[:matches[0].start()] + matches[0].group(1) + XFCE_AFTER + text[matches[0].end():]
    default = clipboard._commands_default(new)
    if default is None or not any(item.get("name") == KEY and item.get("value") == COMMAND for item in default):
        return ""
    return new


def xfce_defaults(context: MigrationContext, path: Path = XFCE_SHORTCUTS) -> None:
    try:
        new = xfce_defaults_updated(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        context.log(f"no {path}")
        return
    except (OSError, UnicodeDecodeError):
        new = ""
    if new:
        context.write_file_if_changed(path, new)
    else:
        context.log(f"{path}: Print does not run Flameshot's capture, or the file is not as expected; left alone")


def xfce_user(context: MigrationContext, username: str, uid: int, runtime_root: Path = clipboard.RUNTIME_ROOT) -> None:
    runtime = runtime_root / str(uid)
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "XDG_CONFIG_DIRS": clipboard.XFCE_CONFIG_DIRS}
    prefix = ["runuser", "-u", username, "--"]
    if clipboard._logged_in(uid, runtime_root):
        env.update(XDG_RUNTIME_DIR=str(runtime), DBUS_SESSION_BUS_ADDRESS=f"unix:path={runtime}/bus")
    else:
        prefix += ["dbus-run-session", "--"]
    listed = context.run_command([*prefix, *clipboard.XFCE_QUERY, "-l", "-v"], allow_fail=True, env=env)
    if listed is None:
        return
    properties = clipboard.xfce_properties(listed.stdout) if listed.returncode == 0 else {}
    names = [name for name, value in properties.items() if name.startswith("/commands/custom/")
             and accelerator(name[len("/commands/custom/"):]) == accelerator(KEY) and value == FLAMESHOT]
    if not names:
        context.log(f"Print Screen of {username} does not run Flameshot's capture, or uses the defaults")
        return
    for name in names:
        result = context.run_command([*prefix, *clipboard.XFCE_QUERY, "-p", name, "-t", "string", "-s", COMMAND],
                                     allow_fail=True, env=env)
        if result is not None and result.returncode != 0:
            context.log(f"warning: could not set {name} for {username}: {result.stderr.strip()}")
        else:
            context.log(f"Print Screen copies the screen to the clipboard for {username}")


def run(context: MigrationContext, desktop: str | None = None) -> None:
    desktop = current_desktop() if desktop is None else desktop
    users = clipboard._desktop_users()
    if desktop == CINNAMON:
        cinnamon_defaults(context, users)
        if context.dry_run:
            context.log("give Print Screen to caramos-print-screen for every Cinnamon user")
            return
        for username, uid, home in users:
            cinnamon_user(context, username, uid, home)
    elif desktop == XFCE:
        xfce_defaults(context)
        if context.dry_run:
            context.log("give Print Screen to caramos-print-screen for every Xfce user")
            return
        for username, uid, _home in users:
            xfce_user(context, username, uid)
    else:
        context.log(f"desktop {desktop}: no keyboard shortcut to change")

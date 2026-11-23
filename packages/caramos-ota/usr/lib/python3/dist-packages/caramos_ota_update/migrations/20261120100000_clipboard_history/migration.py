"""Super+V shows the clipboard history, as Win+V does on Windows (ticket H-1182).

caramos-clipboard (caramos-ota) shows the latest copied items under the mouse pointer and pastes the one picked.
CopyQ keeps the history. It is installed again where it is missing (installs from 1.3.0 on had none; about 3 MB to
download), but it does not start at login: the first Super+V starts it and turns that on (see caramos-clipboard),
so nothing more runs for someone who never presses it.

The key goes to every user whose Super+V does nothing yet, on both editions:
- Cinnamon: a custom shortcut. CaramOS's system defaults have it in custom2 (/etc/dconf/db/local.d/03-caramos-
  clipboard-key, the ISO's file) and custom2 in the custom-list of 99_caramos.gschema.override, for accounts made
  later. Each existing user gets it in the first free customN with gsettings, as in migration 20261112100000, which
  also makes Cinnamon read the list again: the key works at once.
- Xfce: /commands/custom/<Super>v of the xfce4-keyboard-shortcuts channel, written with xfconf-query as each user,
  through the xfconfd of their session when they are logged in, as in migration 20261119100200. CaramOS's system
  defaults get it in commands/default, which an account copies at its first login.
A user who already has Super+V for something else keeps it.

On Xfce, Super+V also opened the Start menu, which took the keyboard and closed the history's list: CaramOS 1.4.0
bound Super_L itself to the menu, and Xfce 4.18 runs that at the start of every Super+<key> shortcut (Super+E opened
Files and the menu). xcape is installed for caramos-super-key (/etc/xdg/autostart/caramos-xfce-super-key.desktop),
which at the next login gives Alt+F1 to the menu, removes the Super_L shortcut and starts xcape, which sends Alt+F1
for a lone Super. The system defaults change the same way here, for accounts made later.

Cinnamon 6.6 crashes when the system dconf database is rebuilt (`dconf update`) under a running session (see
20261012180000_add_help_applet): with someone logged in, the database waits for a later `dconf update`.
Compiling the GSettings schemas is safe under a session; package updates do it all the time.
"""

from __future__ import annotations

import importlib
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any

from caramos_ota_update.context import MigrationContext, MigrationContextError
from caramos_ota_update.desktop import CINNAMON, XFCE, current_desktop

DESCRIPTION = "Super+V shows the clipboard history (CopyQ)"

COMMAND = "caramos-clipboard"
KEY = "<Super>v"
NAME = "CopyQ"  # the shortcut's name in Cinnamon's keyboard settings, as the screenshot ones are "Flameshot"

DCONF_FILE = Path("/etc/dconf/db/local.d/03-caramos-clipboard-key")
SLOT = "custom2"
SCHEMAS = Path("/usr/share/glib-2.0/schemas")
OVERRIDE = SCHEMAS / "99_caramos.gschema.override"
LIST_BEFORE = "custom-list=['custom0', 'custom1']"
LIST_AFTER = "custom-list=['custom0', 'custom1', 'custom2']"

XFCE_SHORTCUTS = Path("/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml")
XFCE_PROPERTY = f'<property name="&lt;Super&gt;v" type="string" value="{COMMAND}"/>'
XFCE_MENU = "xfce4-popup-whiskermenu"
ALT_F1_APPS = '<property name="&lt;Alt&gt;F1" type="string" value="xfce4-popup-applicationsmenu"/>'
ALT_F1_MENU = f'<property name="&lt;Alt&gt;F1" type="string" value="{XFCE_MENU}"/>'
SUPER_L_MENU = f'<property name="Super_L" type="string" value="{XFCE_MENU}"/>'
XFCE_QUERY = ("xfconf-query", "-c", "xfce4-keyboard-shortcuts")
XFCE_CONFIG_DIRS = "/etc/xdg/caramos-xfce:/etc/xdg/xdg-xfce:/etc/xdg"  # an Xfce session's (Xsession.d 61caramos-xfce)
RUNTIME_ROOT = Path("/run/user")

screenshot = importlib.import_module("caramos_ota_update.migrations.20261112100000_screenshot_shortcuts.migration")
accelerator = screenshot.accelerator
gvariant_string = screenshot.gvariant_string
gvariant_strv = screenshot.gvariant_strv


def dconf_defaults() -> str:
    """CaramOS's system default of custom2 (also the ISO's 03-caramos-clipboard-key)."""

    return "\n".join([
        "# CaramOS: Super+V shows the clipboard history (caramos-clipboard, with CopyQ), as Win+V does on Windows.",
        "# custom2 is in the custom-list of 99_caramos.gschema.override. Custom shortcuts live at relocatable paths,",
        "# whose defaults gschema overrides cannot set: dconf sets them here.",
        "",
        f"[{screenshot.CUSTOM_PATH.strip('/')}/{SLOT}]",
        f"name={gvariant_string(NAME)}",
        f"command={gvariant_string(COMMAND)}",
        f"binding={gvariant_strv([KEY])}",
    ]) + "\n"


def override_with_slot(text: str) -> str:
    """99_caramos.gschema.override with custom2 in its custom-list, or "" when its list is not CaramOS's of 1.4.0."""

    lines = text.splitlines(keepends=True)
    found = [index for index, line in enumerate(lines) if line.rstrip("\n") == LIST_BEFORE]
    if len(found) != 1:
        return ""
    lines[found[0]] = LIST_AFTER + "\n"
    return "".join(lines)


def _commands_default(text: str) -> Any:
    try:
        return ElementTree.fromstring(text.encode("utf-8")).find("property[@name='commands']/property[@name='default']")
    except ElementTree.ParseError:
        return None


def xfce_defaults_updated(text: str) -> str:
    """CaramOS's Xfce keyboard shortcuts with, in commands/default, Super+V for the clipboard history, and Alt+F1 for
    the Start menu instead of Super_L (xcape opens it with a lone Super, see caramos-super-key). "" when there is
    nothing to change or the file is not as expected.

    Alt+F1 changes only from Linux Mint's applications menu, and Super_L goes only once Alt+F1 opens the Start menu.
    """

    default = _commands_default(text)
    if default is None:
        return ""
    lines = text.splitlines(keepends=True)
    opened = next((index for index, line in enumerate(lines) if '<property name="commands"' in line), None)
    if opened is None:
        return ""
    start = next((index for index in range(opened, len(lines)) if '<property name="default"' in lines[index]), None)
    if start is None:
        return ""
    end = next((index for index in range(start + 1, len(lines)) if lines[index].strip() == "</property>"), None)
    if end is None or end == start + 1:
        return ""
    block = [line.replace(ALT_F1_APPS, ALT_F1_MENU) if line.strip() == ALT_F1_APPS else line
             for line in lines[start + 1:end]]
    if any(line.strip() == ALT_F1_MENU for line in block):
        block = [line for line in block if line.strip() != SUPER_L_MENU]
    if not any(accelerator(item.get("name", "")) == accelerator(KEY) for item in default):
        last = block[-1]
        block.append(f"{last[:len(last) - len(last.lstrip())]}{XFCE_PROPERTY}\n")
    if block == lines[start + 1:end]:
        return ""
    new = "".join(lines[:start + 1] + block + lines[end:])
    check = _commands_default(new)
    if check is None or not any(accelerator(item.get("name", "")) == accelerator(KEY) for item in check):
        return ""
    return new


def _desktop_users() -> list[tuple[str, int, Path]]:
    return screenshot._desktop_users()


def _logged_in(uid: int, runtime_root: Path = RUNTIME_ROOT) -> bool:
    return (runtime_root / str(uid) / "bus").exists()


def _installed(context: MigrationContext, package: str) -> bool:
    result = context.run_command(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", package], allow_fail=True)
    return result is not None and result.returncode == 0 and result.stdout.startswith("ii")


def install_packages(context: MigrationContext, desktop: str) -> None:
    """CopyQ and its plugins (pictures, such as a screenshot copied from Flameshot, stay in the history only with
    them); on Xfce xcape too, which opens the Start menu with a lone Super (caramos-super-key)."""

    wanted = ["copyq", "copyq-plugins"] + (["xcape"] if desktop == XFCE else [])
    missing = [package for package in wanted if not _installed(context, package)]
    if not missing:
        context.log(f"{', '.join(wanted)} installed")
        return
    try:
        context.apt_install(missing, recommends=False)
    except MigrationContextError as exc:
        context.log(f"could not install {', '.join(missing)} ({exc}); Super+V says how to install CopyQ")


# Cinnamon ------------------------------------------------------------------------------------------------------


def free_slot(slots: list[str], read: Any) -> str | None:
    """The slot for the shortcut: custom2 when it is listed but empty, else the first customN from custom2 on that
    is not in the list and is empty or already this shortcut.

    custom2 is listed but empty for a user who keeps the default list once the new 99_caramos.gschema.override is
    compiled and before `dconf update` gives custom2 its values: another slot there would bind Super+V twice later,
    and the menu would open and close at once.
    """

    if SLOT in slots and read(SLOT) == ("", []):
        return SLOT
    for number in range(2, 100):
        slot = f"custom{number}"
        if slot in slots:
            continue
        command, binding = read(slot)
        if (command, binding) in (("", []), (COMMAND, [KEY])):
            return slot
    return None


def cinnamon_user(context: MigrationContext, username: str, uid: int, home: Path) -> None:
    env = screenshot._user_environment(username, uid, home)

    def get(schema: str, key: str) -> Any:
        result = screenshot._gsettings(username, env, ["get", schema, key])
        return screenshot.parse(result.stdout) if result.returncode == 0 else None

    def read(slot: str) -> tuple[Any, Any]:
        schema = screenshot._slot_schema(slot)
        return get(schema, "command"), get(schema, "binding")

    slots = get(screenshot.KEYBINDINGS, "custom-list")
    if not isinstance(slots, list) or not all(isinstance(slot, str) for slot in slots):
        context.log(f"warning: could not read the custom shortcuts of {username}; leave them as they are")
        return
    taken: set[tuple[frozenset[str], str]] = set()
    for slot in slots:
        command, binding = read(slot)
        if command == COMMAND:
            context.log(f"{slot} of {username} already shows the clipboard history")
            return
        taken |= screenshot.accelerators(binding)
    for schema in screenshot.CINNAMON_SCHEMAS:
        result = screenshot._gsettings(username, env, ["list-recursively", schema])
        for line in result.stdout.splitlines() if result.returncode == 0 else ():
            parts = line.split(None, 2)
            if len(parts) == 3:
                taken |= screenshot.accelerators(screenshot.parse(parts[2]))
    if accelerator(KEY) in taken:
        context.log(f"{KEY} does something else for {username}: leave it")
        return
    slot = free_slot(slots, read)
    if slot is None:
        context.log(f"warning: no free custom shortcut for {username}")
        return
    schema = screenshot._slot_schema(slot)
    values = (("name", gvariant_string(NAME)), ("command", gvariant_string(COMMAND)), ("binding", gvariant_strv([KEY])))
    for name, value in values:
        result = screenshot._gsettings(username, env, ["set", schema, name, value])
        if result.returncode != 0:
            context.log(f"warning: could not set {slot} of {username}: {result.stderr.strip()}")
            return
    final = slots if slot in slots else [*slots, slot]
    # The list changes, or is written twice when it does not: Cinnamon binds custom shortcuts when it changes.
    for value in screenshot.list_writes(slots, final):
        result = screenshot._gsettings(username, env, ["set", screenshot.KEYBINDINGS, "custom-list",
                                                       gvariant_strv(value)])
        if result.returncode != 0:
            context.log(f"warning: could not write the custom shortcut list of {username}: {result.stderr.strip()}")
            return
    context.log(f"{KEY} shows the clipboard history for {username} ({slot})")


def cinnamon_defaults(context: MigrationContext, users: list[tuple[str, int, Path]], override: Path = OVERRIDE,
                      dconf_file: Path = DCONF_FILE, runtime_root: Path = RUNTIME_ROOT) -> None:
    content = dconf_defaults()
    changed = not (dconf_file.is_file() and dconf_file.read_text(encoding="utf-8") == content)
    context.write_file_if_changed(dconf_file, content)
    if changed and not context.dry_run:
        logged_in = [username for username, uid, _home in users if _logged_in(uid, runtime_root)]
        if logged_in:
            context.log(f"{', '.join(logged_in)} logged in: dconf update waits, Cinnamon would crash under it")
        else:
            context.run_command(["dconf", "update"], allow_fail=True)
    try:
        new = override_with_slot(override.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        new = ""
    if not new:
        context.log(f"{override}: no CaramOS custom-list without {SLOT}; left alone")
        return
    context.write_file_if_changed(override, new)
    context.run_command(["glib-compile-schemas", str(override.parent)], allow_fail=True)


# Xfce ----------------------------------------------------------------------------------------------------------


def xfce_properties(listing: str) -> dict[str, str]:
    """`xfconf-query -l -v` output as {property: value}."""

    properties = {}
    for line in listing.splitlines():
        parts = line.strip().split(None, 1)
        if parts and parts[0].startswith("/"):
            properties[parts[0]] = parts[1] if len(parts) == 2 else ""
    return properties


def xfce_plan(properties: dict[str, str]) -> str:
    """What to do for a user with these shortcuts: "set", or why not."""

    custom = {name: value for name, value in properties.items() if name.startswith("/commands/custom/")}
    if not custom:
        return "no shortcuts of their own yet: the defaults apply at their first login"
    if COMMAND in custom.values():
        return "already shows the clipboard history"
    for name in properties:
        parts = name.split("/")
        if len(parts) >= 4 and parts[1] in ("commands", "xfwm4") and parts[2] == "custom":
            if accelerator(parts[3]) == accelerator(KEY):
                return f"{KEY} does something else: leave it"
    return "set"


def xfce_user(context: MigrationContext, username: str, uid: int, runtime_root: Path = RUNTIME_ROOT) -> None:
    runtime = runtime_root / str(uid)
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "XDG_CONFIG_DIRS": XFCE_CONFIG_DIRS}  # runuser sets HOME
    prefix = ["runuser", "-u", username, "--"]
    if _logged_in(uid, runtime_root):
        # Through the xfconfd of their session: it keeps the channel in memory, and xfsettingsd grabs the key at once.
        env.update(XDG_RUNTIME_DIR=str(runtime), DBUS_SESSION_BUS_ADDRESS=f"unix:path={runtime}/bus")
    else:
        prefix += ["dbus-run-session", "--"]
    listed = context.run_command([*prefix, *XFCE_QUERY, "-l", "-v"], allow_fail=True, env=env)
    if listed is None:
        return
    plan = xfce_plan(xfce_properties(listed.stdout)) if listed.returncode == 0 else "no keyboard shortcuts channel"
    if plan != "set":
        context.log(f"Xfce shortcuts of {username}: {plan}")
        return
    result = context.run_command([*prefix, *XFCE_QUERY, "-p", f"/commands/custom/{KEY}", "-n", "-t", "string",
                                  "-s", COMMAND], allow_fail=True, env=env)
    if result is not None and result.returncode != 0:
        context.log(f"warning: could not set {KEY} for {username}: {result.stderr.strip()}")
    else:
        context.log(f"{KEY} shows the clipboard history for {username}")


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
        context.log(f"{path} needs no change, or is not as expected; left alone")


def run(context: MigrationContext, desktop: str | None = None) -> None:
    desktop = current_desktop() if desktop is None else desktop
    install_packages(context, desktop)
    users = _desktop_users()
    if desktop == XFCE:
        xfce_defaults(context)
        if context.dry_run:
            context.log(f"give {KEY} to the clipboard history of every Xfce user")
            return
        for username, uid, _home in users:
            xfce_user(context, username, uid)
    elif desktop == CINNAMON:
        # Users first: until then the default list of the users who keep it has no custom2 (see free_slot).
        if context.dry_run:
            context.log(f"give {KEY} to the clipboard history of every Cinnamon user")
        else:
            for username, uid, home in users:
                cinnamon_user(context, username, uid, home)
        cinnamon_defaults(context, users)
    else:
        context.log(f"desktop {desktop}: no keyboard shortcut to add")


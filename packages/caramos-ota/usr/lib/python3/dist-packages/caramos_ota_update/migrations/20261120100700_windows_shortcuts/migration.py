"""Shortcuts as on Windows, the same on both editions (a company using CaramOS asked for keys to lock, shut down and
search, 2026-11-20):

- Super+L locks the screen, and so does Ctrl+Alt+L. On Cinnamon Super+L opened Looking Glass, Cinnamon's debugger
  (Alt+F2 then "lg" still does); on Xfce it did nothing.
- Ctrl+Alt+Delete opens the dialog to log out, as on Cinnamon (where Ctrl+Alt+End opens the one to shut down). On
  Xfce Ctrl+Alt+Delete locked the screen; it now opens Xfce's dialog, which has every choice, shutting down included.
  Ctrl+Alt+End stays the Xfce window manager's (a window to the next workspace): no key the window manager uses is
  taken.
- Super alone already opens the Start menu, ready to search.

Cinnamon: defaults in CaramOS's gschema override (the ISO's file), compiled again; a key a user set stays theirs.
Xfce: CaramOS's default shortcuts (the ISO's file), and the same keys for each user who has shortcuts of their own,
through xfconf-query as migration 20261120100000 does; a key a user gave to something else stays. On Cinnamon and for
Xfce users without shortcuts of their own this shows from the next login; for the others at once.
"""

from __future__ import annotations

import importlib
import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Shortcuts as on Windows: Super+L locks, Ctrl+Alt+Delete opens the log out dialog on both editions"

clipboard = importlib.import_module("caramos_ota_update.migrations.20261120100000_clipboard_history.migration")
accelerator = clipboard.accelerator

OVERRIDE = clipboard.OVERRIDE
SCHEMAS = clipboard.SCHEMAS
# (section, key, setting, comment)
CINNAMON_KEYS = (
    ("[org.cinnamon.desktop.keybindings.media-keys]", "screensaver",
     "screensaver=['<Control><Alt>l', '<Super>l', 'XF86ScreenSaver']",
     "# Super+L locks the screen, as on Windows, and Ctrl+Alt+L (Cinnamon's own)."),
    ("[org.cinnamon.desktop.keybindings]", "looking-glass-keybinding",
     "looking-glass-keybinding=@as []",
     "# Super+L opened Looking Glass, Cinnamon's debugger: Alt+F2 then lg still does."),
)

XFCE_SHORTCUTS = clipboard.XFCE_SHORTCUTS
LOCK = "xflock4"
SESSION = "xfce4-session-logout"
XFCE_KEYS = (("<Super>l", LOCK), ("<Primary><Alt>l", LOCK), ("<Primary><Alt>Delete", SESSION))
# What CaramOS 1.4.0 gave these keys: replaced only while they still do that.
XFCE_BEFORE = {"<Primary><Alt>Delete": LOCK}
_PROPERTY = re.compile(r'^(\s*)<property name="([^"]+)" type="string" value="([^"]*)"/>\s*$')


def override_with_keys(text: str) -> str:
    """The gschema override with the keys of CINNAMON_KEYS, each after the last setting of its section."""

    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    for section, key, setting, comment in CINNAMON_KEYS:
        start = next((index for index, line in enumerate(lines) if line.strip() == section), None)
        if start is None:
            lines += ["\n", f"{section}\n", f"{comment}\n", f"{setting}\n"]
            continue
        end = next((index for index in range(start + 1, len(lines)) if lines[index].lstrip().startswith("[")),
                   len(lines))
        if any(re.match(rf"\s*{re.escape(key)}\s*=", line) for line in lines[start + 1:end]):
            continue
        last = max((index for index in range(start + 1, end)
                    if lines[index].strip() and not lines[index].lstrip().startswith("#")), default=start)
        lines[last + 1:last + 1] = [f"{comment}\n", f"{setting}\n"]
    return "".join(lines)


def _xml_name(key: str) -> str:
    return key.replace("<", "&lt;").replace(">", "&gt;")


def _xfwm4_default(text: str) -> set:
    """The keys of the window manager's default shortcuts."""

    try:
        root = ElementTree.fromstring(text.encode("utf-8"))
    except ElementTree.ParseError:
        return set()
    default = root.find("property[@name='xfwm4']/property[@name='default']")
    return {accelerator(item.get("name", "")) for item in default} if default is not None else set()


def xfce_defaults_updated(text: str) -> str:
    """CaramOS's Xfce shortcuts with XFCE_KEYS in commands/default; "" when there is nothing to change or the file is
    not as expected."""

    if clipboard._commands_default(text) is None:
        return ""
    lines = text.splitlines(keepends=True)
    opened = next((index for index, line in enumerate(lines) if '<property name="commands"' in line), None)
    start = next((index for index in range(opened, len(lines)) if '<property name="default"' in lines[index]),
                 None) if opened is not None else None
    end = next((index for index in range(start + 1, len(lines)) if lines[index].strip() == "</property>"),
               None) if start is not None else None
    if end is None or end == start + 1:
        return ""
    block = list(lines[start + 1:end])
    window_manager = _xfwm4_default(text)
    bound = {}
    for index, line in enumerate(block):
        match = _PROPERTY.match(line)
        if match:
            name = match.group(2).replace("&lt;", "<").replace("&gt;", ">")
            bound[accelerator(name)] = (index, name, match.group(3))
    indent = _PROPERTY.match(block[-1]).group(1) if _PROPERTY.match(block[-1]) else "      "
    for key, command in XFCE_KEYS:
        found = bound.get(accelerator(key))
        if found is None and accelerator(key) in window_manager:
            continue
        if found is None:
            block.append(f'{indent}<property name="{_xml_name(key)}" type="string" value="{command}"/>\n')
        elif XFCE_BEFORE.get(key) == found[2]:
            index = found[0]
            block[index] = block[index].replace(f'value="{found[2]}"', f'value="{command}"')
    if block == lines[start + 1:end]:
        return ""
    new = "".join(lines[:start + 1] + block + lines[end:])
    check = clipboard._commands_default(new)
    if check is None:
        return ""
    values = {accelerator(item.get("name", "")): item.get("value") for item in check}
    if any(accelerator(key) not in values for key, _command in XFCE_KEYS):
        return ""
    return new


def xfce_user_plan(properties: dict[str, str]) -> list[tuple[str, str]] | str:
    """The (property, command) pairs to set for a user with shortcuts of their own, or why there are none."""

    if not any(name.startswith("/commands/custom/") for name in properties):
        return "no shortcuts of their own: the defaults apply from their next login"
    bound = {}
    for name, value in properties.items():
        parts = name.split("/", 3)
        if len(parts) == 4 and parts[1] in ("commands", "xfwm4") and parts[2] == "custom":
            bound[accelerator(parts[3])] = (name, value)
    changes = []
    for key, command in XFCE_KEYS:
        found = bound.get(accelerator(key))
        if found is None:
            changes.append((f"/commands/custom/{key}", command))
        elif found[0].startswith("/commands/custom/") and XFCE_BEFORE.get(key) == found[1]:
            changes.append((found[0], command))
    return changes or "has these keys already, or gave them to something else"


def cinnamon_defaults(context: MigrationContext, override: Path = OVERRIDE, schemas: Path = SCHEMAS) -> None:
    try:
        text = override.read_text(encoding="utf-8")
    except FileNotFoundError:
        context.log(f"no {override}")
        return
    new = override_with_keys(text)
    if new == text:
        context.log("Cinnamon's default shortcuts are as on Windows already")
        return
    context.write_file_if_changed(override, new)
    if context.dry_run:
        return
    result = context.run_command(["glib-compile-schemas", str(schemas)], allow_fail=True)
    if result is None or result.returncode != 0:
        context.log(f"warning: glib-compile-schemas failed: {result.stderr.strip() if result is not None else ''}")


def xfce_defaults(context: MigrationContext, path: Path = XFCE_SHORTCUTS) -> None:
    try:
        new = xfce_defaults_updated(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        context.log(f"no {path}: not the Xfce edition")
        return
    except (OSError, UnicodeDecodeError):
        new = ""
    if new:
        context.write_file_if_changed(path, new)
    else:
        context.log(f"{path}: the Windows shortcuts are there already, or the file is not as expected")


def xfce_user(context: MigrationContext, username: str, uid: int,
              runtime_root: Path = clipboard.RUNTIME_ROOT) -> None:
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
    plan = xfce_user_plan(clipboard.xfce_properties(listed.stdout)) if listed.returncode == 0 \
        else "no keyboard shortcuts channel"
    if isinstance(plan, str):
        context.log(f"Xfce shortcuts of {username}: {plan}")
        return
    for name, command in plan:
        result = context.run_command([*prefix, *clipboard.XFCE_QUERY, "-p", name, "-n", "-t", "string", "-s", command],
                                     allow_fail=True, env=env)
        if result is not None and result.returncode != 0:
            context.log(f"warning: could not set {name} for {username}: {result.stderr.strip()}")
        else:
            context.log(f"{name.rsplit('/', 1)[-1]} runs {command} for {username}")


def run(context: MigrationContext) -> None:
    cinnamon_defaults(context)
    xfce_defaults(context)
    if not XFCE_SHORTCUTS.exists():
        return
    if context.dry_run:
        context.log("set the Windows shortcuts for every Xfce user who has shortcuts of their own")
        return
    for username, uid, _home in clipboard._desktop_users():
        xfce_user(context, username, uid)

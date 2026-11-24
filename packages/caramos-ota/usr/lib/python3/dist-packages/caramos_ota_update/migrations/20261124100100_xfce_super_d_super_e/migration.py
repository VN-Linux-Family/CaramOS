"""Super+D shows the desktop and Super+E opens Files on the Xfce edition, as on Windows and on the Cinnamon edition
(tickets H-1201 and H-1202; H-1185 found Thunar where Files was expected).

- Super+D: the window manager's Show desktop (xfwm4's show_desktop_key, which Xfce gives Ctrl+Alt+D; that stays).
  Pressed again, it brings the windows back. Super alone belongs to xcape since 1.5.0 (it opens the Start menu only
  when released alone, see caramos-super-key), so Super+D no longer opens the Start menu as well: the clash ticket
  H-1202 saw in 1.4.0.
- Super+E: Xfce's own default ran Thunar, the file manager CaramOS keeps only for Xfce's tools. It now runs the file
  manager of Default Applications (exo-open --launch FileManager): Files (Nemo) on CaramOS, in the home folder.

CaramOS's default shortcuts (the ISO's xfce4-keyboard-shortcuts.xml) get both keys, for accounts made later, and each
user with shortcuts of their own gets them through xfconf-query, as migration 20261120100700 does: Xfce takes them at
once. Super+E changes only where it still runs Thunar, and Super+D is added only where the key is free: a key someone
gave to something else stays theirs.
"""

from __future__ import annotations

import importlib
import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Xfce: Super+D shows the desktop, Super+E opens Files"

clipboard = importlib.import_module("caramos_ota_update.migrations.20261120100000_clipboard_history.migration")
windows = importlib.import_module("caramos_ota_update.migrations.20261120100700_windows_shortcuts.migration")
accelerator = clipboard.accelerator

XFCE_SHORTCUTS = clipboard.XFCE_SHORTCUTS
FILES = "exo-open --launch FileManager"
THUNAR = "thunar"
SHOW_DESKTOP = "show_desktop_key"
# (provider, key, value): commands are programs, xfwm4 entries the window manager's actions.
KEYS = (("commands", "<Super>e", FILES), ("xfwm4", "<Super>d", SHOW_DESKTOP))
# What Xfce gave these keys before: replaced only while they still do that.
BEFORE = {"<Super>e": THUNAR}
_PROPERTY = re.compile(r'^(\s*)<property name="([^"]+)" type="string" value="([^"]*)"/>\s*$')


def _block(lines: list[str], provider: str) -> tuple[int, int] | None:
    """(first, end) line numbers of <provider>/default's properties, or None."""

    opened = next((index for index, line in enumerate(lines) if f'<property name="{provider}"' in line), None)
    if opened is None:
        return None
    start = next((index for index in range(opened, len(lines)) if '<property name="default"' in lines[index]), None)
    if start is None:
        return None
    end = next((index for index in range(start + 1, len(lines)) if lines[index].strip() == "</property>"), None)
    return (start + 1, end) if end is not None and end > start + 1 else None


def _bound(lines: list[str], block: tuple[int, int]) -> dict:
    keys = {}
    for index in range(*block):
        match = _PROPERTY.match(lines[index])
        if match:
            name = match.group(2).replace("&lt;", "<").replace("&gt;", ">")
            keys[accelerator(name)] = (index, name, match.group(3))
    return keys


def defaults_updated(text: str) -> str:
    """CaramOS's Xfce shortcuts with Super+E and Super+D; "" when there is nothing to change or the file is not as
    expected."""

    lines = text.splitlines(keepends=True)
    blocks = {provider: _block(lines, provider) for provider in ("commands", "xfwm4")}
    if None in blocks.values():
        return ""
    bound = {provider: _bound(lines, block) for provider, block in blocks.items()}
    taken = {key for keys in bound.values() for key in keys}
    edits: dict[int, str] = {}
    additions: dict[str, list[str]] = {"commands": [], "xfwm4": []}
    planned = []
    for provider, key, value in KEYS:
        found = bound[provider].get(accelerator(key))
        if found is not None:
            if BEFORE.get(key) == found[2]:
                edits[found[0]] = lines[found[0]].replace(f'value="{found[2]}"', f'value="{value}"')
                planned.append((provider, key, value))
            continue
        if accelerator(key) in taken:
            continue
        last = _PROPERTY.match(lines[blocks[provider][1] - 1])
        indent = last.group(1) if last else "      "
        additions[provider].append(f'{indent}<property name="{windows._xml_name(key)}" type="string" '
                                   f'value="{value}"/>\n')
        planned.append((provider, key, value))
    if not planned:
        return ""
    new = []
    for index, line in enumerate(lines):
        new.append(edits.get(index, line))
        for provider, (_first, end) in blocks.items():
            if index == end - 1:
                new.extend(additions[provider])
    result = "".join(new)
    try:
        root = ElementTree.fromstring(result.encode("utf-8"))
    except ElementTree.ParseError:
        return ""
    for provider, key, value in planned:
        default = root.find(f"property[@name='{provider}']/property[@name='default']")
        values = {accelerator(item.get("name", "")): item.get("value") for item in default} \
            if default is not None else {}
        if values.get(accelerator(key)) != value:
            return ""
    return result


def user_plan(properties: dict[str, str]) -> list[tuple[str, str]] | str:
    """The (property, value) pairs to set for a user with shortcuts of their own, or why there are none."""

    if not any(name.startswith(("/commands/custom/", "/xfwm4/custom/")) for name in properties):
        return "no shortcuts of their own: the defaults apply from their next login"
    bound = {}
    for name, value in properties.items():
        parts = name.split("/", 3)
        if len(parts) == 4 and parts[1] in ("commands", "xfwm4") and parts[2] == "custom" and \
                not parts[3].endswith("/startup-notify") and parts[3] != "override":
            bound[accelerator(parts[3])] = (name, value)
    changes = []
    for provider, key, value in KEYS:
        found = bound.get(accelerator(key))
        if found is None:
            changes.append((f"/{provider}/custom/{key}", value))
        elif found[0].startswith(f"/{provider}/custom/") and BEFORE.get(key) == found[1]:
            changes.append((found[0], value))
    return changes or "has these keys already, or gave them to something else"


def xfce_defaults(context: MigrationContext, path: Path = XFCE_SHORTCUTS) -> None:
    try:
        new = defaults_updated(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        context.log(f"no {path}: not the Xfce edition")
        return
    except (OSError, UnicodeDecodeError):
        new = ""
    if new:
        context.write_file_if_changed(path, new)
    else:
        context.log(f"{path}: Super+D and Super+E are there already, or the file is not as expected")


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
    plan = user_plan(clipboard.xfce_properties(listed.stdout)) if listed.returncode == 0 \
        else "no keyboard shortcuts channel"
    if isinstance(plan, str):
        context.log(f"Xfce shortcuts of {username}: {plan}")
        return
    for name, value in plan:
        result = context.run_command([*prefix, *clipboard.XFCE_QUERY, "-p", name, "-n", "-t", "string", "-s", value],
                                     allow_fail=True, env=env)
        if result is not None and result.returncode != 0:
            context.log(f"warning: could not set {name} for {username}: {result.stderr.strip()}")
        else:
            context.log(f"{name.rsplit('/', 1)[-1]} runs {value} for {username}")


def run(context: MigrationContext) -> None:
    xfce_defaults(context)
    if not XFCE_SHORTCUTS.exists():
        return
    if context.dry_run:
        context.log("give Super+D and Super+E to every Xfce user who has shortcuts of their own")
        return
    for username, uid, _home in clipboard._desktop_users():
        xfce_user(context, username, uid)

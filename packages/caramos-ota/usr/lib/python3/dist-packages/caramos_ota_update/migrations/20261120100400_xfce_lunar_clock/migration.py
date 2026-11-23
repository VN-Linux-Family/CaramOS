"""CaramOS Xfce: the clock's calendar shows lunar dates, as on Cinnamon (ticket H-1178, migration 20261120100200).

Xfce's clock plugin opens GTK's calendar, which cannot show them. The clock of the right island is now the Control
Center's (caramos-ota's /usr/share/caramos-ota/xfce/control-center, clock.py), beside its button: it looks like
Xfce's clock did, and a click opens a calendar with the lunar day under each day. The Control Center shows its clock
only where no panel holds Xfce's clock, so this takes Xfce's clock out of the panel that holds the Control Center:

- in CaramOS's system defaults (/etc/xdg/caramos-xfce/.../xfce4-panel.xml, the ISO's file), for accounts made later
  and for users whose panels are still the defaults;
- for each user whose panels are their own (~/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml), with
  xfconf-query as that user: through the xfconfd of their session when they are logged in, else through a D-Bus
  session of its own, as migration 20261120100000 does. The whole list of the panel's plugins is written: removing
  the user's value would bring back the system default, which another layout may not match (see
  backends/taskbar.py).

Plugins are found by their type, not their number: panels made or changed by hand number them otherwise. A clock on
another panel stays, and then the Control Center shows none. xfce4-panel reads its plugins only when it starts, so
the new clock shows from the next login.
"""

from __future__ import annotations

import importlib
import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Xfce: the clock's calendar shows lunar dates"

CLOCK = "clock"
CONTROL_CENTER = "caramos-control-center"
PANEL_DEFAULTS = Path("/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml")
USER_PANELS = Path(".config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml")
QUERY = ("xfconf-query", "-c", "xfce4-panel")

clipboard = importlib.import_module("caramos_ota_update.migrations.20261120100000_clipboard_history.migration")


def plan(panels: list[int], plugin_ids: dict[int, list[int]], names: dict[int, str]) -> tuple[int, list[int]] | None:
    """(panel, its plugins without Xfce's clock) for the panel that holds the Control Center; None when it has no
    clock, or no panel holds the Control Center."""

    for panel in panels:
        ids = plugin_ids.get(panel, [])
        if any(names.get(plugin) == CONTROL_CENTER for plugin in ids):
            kept = [plugin for plugin in ids if names.get(plugin) != CLOCK]
            return (panel, kept) if kept != ids else None
    return None


def _layout(root: ElementTree.Element) -> tuple[list[int], dict[int, list[int]], dict[int, str]] | None:
    panels_node = root.find("property[@name='panels']")
    plugins_node = root.find("property[@name='plugins']")
    if panels_node is None or plugins_node is None:
        return None
    try:
        panels = [int(value.get("value", "")) for value in panels_node.findall("value")]
        plugin_ids = {}
        for panel in panels:
            ids = panels_node.find(f"property[@name='panel-{panel}']/property[@name='plugin-ids']")
            plugin_ids[panel] = [int(value.get("value", "")) for value in ids.findall("value")] if ids is not None else []
    except ValueError:
        return None
    names = {int(node.get("name").split("-")[1]): node.get("value", "") for node in plugins_node.findall("property")
             if re.fullmatch(r"plugin-\d+", node.get("name") or "")}
    return panels, plugin_ids, names


def defaults_without_clock(text: str) -> str:
    """The system defaults without Xfce's clock in the Control Center's panel: its id out of that panel's plugin-ids
    and its settings gone, the rest of the file (comments too) as it was. "" when there is nothing to change or the
    file is not as expected."""

    try:
        layout = _layout(ElementTree.fromstring(text))
    except ElementTree.ParseError:
        return ""
    found = plan(*layout) if layout else None
    if found is None:
        return ""
    panel, kept = found
    removed = [plugin for plugin in layout[1][panel] if plugin not in kept]
    try:
        panel_start = text.index(f'<property name="panel-{panel}" type="empty">')
        ids_start = text.index('<property name="plugin-ids" type="array">', panel_start)
        ids_end = text.index("</property>", ids_start)
    except ValueError:
        return ""
    ids = text[ids_start:ids_end]
    for plugin in removed:
        ids, count = re.subn(rf'\n[ \t]*<value type="int" value="{plugin}"/>', "", ids)
        if count != 1:
            return ""
    new = text[:ids_start] + ids + text[ids_end:]
    for plugin in removed:
        new, count = re.subn(rf'\n([ \t]*)<property name="plugin-{plugin}" type="string" value="{CLOCK}"'
                             rf'(?:/>|>.*?\n\1</property>)', "", new, flags=re.S)
        if count != 1:
            return ""
    try:
        after = _layout(ElementTree.fromstring(new))
    except ElementTree.ParseError:
        return ""
    if after is None or plan(*after) is not None or after[1][panel] != kept:
        return ""
    return new


def array(output: str) -> list[int] | None:
    """xfconf-query's answer for an array of ints ("Value is an array with 3 items:", a blank line, one per line)."""

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines or not lines[0].startswith("Value is an array"):
        return None
    try:
        return [int(line) for line in lines[1:]]
    except ValueError:
        return None


def xfce_defaults(context: MigrationContext, path: Path = PANEL_DEFAULTS) -> None:
    try:
        new = defaults_without_clock(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        context.log(f"no {path}")
        return
    except (OSError, UnicodeDecodeError):
        new = ""
    if new:
        context.write_file_if_changed(path, new)
    else:
        context.log(f"{path}: no Xfce clock beside the Control Center, or not as expected; left alone")


def xfce_user(context: MigrationContext, username: str, uid: int, home: Path,
              runtime_root: Path = clipboard.RUNTIME_ROOT) -> None:
    if not (home / USER_PANELS).is_file():
        context.log(f"Xfce panels of {username}: still the defaults")
        return
    runtime = runtime_root / str(uid)
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "XDG_CONFIG_DIRS": clipboard.XFCE_CONFIG_DIRS}
    prefix = ["runuser", "-u", username, "--"]
    if clipboard._logged_in(uid, runtime_root):
        env.update(XDG_RUNTIME_DIR=str(runtime), DBUS_SESSION_BUS_ADDRESS=f"unix:path={runtime}/bus")
    else:
        prefix += ["dbus-run-session", "--"]

    def query(*args: str) -> str | None:
        result = context.run_command([*prefix, *QUERY, *args], allow_fail=True, env=env)
        return result.stdout if result is not None and result.returncode == 0 else None

    listed = query("-l", "-v")
    panels = array(query("-p", "/panels") or "")
    if listed is None or panels is None:
        context.log(f"Xfce panels of {username}: could not be read; left alone")
        return
    properties = clipboard.xfce_properties(listed)
    names = {int(name.rsplit("-", 1)[1]): value for name, value in properties.items()
             if re.fullmatch(r"/plugins/plugin-\d+", name)}
    plugin_ids = {}
    for panel in panels:
        ids = array(query("-p", f"/panels/panel-{panel}/plugin-ids") or "")
        if ids is None:
            context.log(f"Xfce panels of {username}: panel {panel} could not be read; left alone")
            return
        plugin_ids[panel] = ids
    found = plan(panels, plugin_ids, names)
    if found is None:
        context.log(f"Xfce panels of {username}: no Xfce clock beside the Control Center")
        return
    panel, kept = found
    values = [arg for plugin in kept for arg in ("-t", "int", "-s", str(plugin))]
    result = context.run_command([*prefix, *QUERY, "-p", f"/panels/panel-{panel}/plugin-ids", "--force-array",
                                  *values], allow_fail=True, env=env)
    if result is None or result.returncode != 0:
        context.log(f"warning: could not take Xfce's clock out of the panel of {username}: "
                    f"{result.stderr.strip() if result is not None else 'not run'}")
    else:
        context.log(f"the Control Center's clock, with lunar dates, replaces Xfce's for {username} "
                    "from the next login")


def run(context: MigrationContext) -> None:
    xfce_defaults(context)
    if context.dry_run:
        context.log("take Xfce's clock out of the Control Center's panel of every Xfce user")
        return
    for username, uid, home in clipboard._desktop_users():
        xfce_user(context, username, uid, home)

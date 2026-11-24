"""Show desktop at the very end of the taskbar, as on Windows and in Linux Mint (tickets H-1189 and H-1192).

Feedback & Help stays the last icon of the right island. After it, at the edge of the screen, a thin strip shows the
desktop when clicked and brings the windows back when clicked again; pointing at it shows a thin line and the tooltip.

- Cinnamon: Cinnamon's corner bar applet (cornerbar@cinnamon.org, which Linux Mint has at the end of its panel), last
  in the panel that holds Feedback & Help. It takes the 8 px that Feedback & Help kept free at the round end of the
  island; its look is in Feedback & Help's stylesheet. CaramOS's system defaults
  (/etc/dconf/db/local.d/01-caramos-task17-panel, the ISO's file) get it, and each user's panel through gsettings,
  which Cinnamon applies at once. In a session that is running, Feedback & Help reloads first, with its new
  stylesheet, so the strip never shows Cinnamon's own grey bar.
- Xfce: the CaramOS panel plugin caramos-show-desktop (xfce4-caramos-plugin 1.1.0, upgraded here when it is older),
  a strip 4 px wide after the island. Xfce's own Show Desktop plugin is as wide as the panel is high. CaramOS's system
  defaults (/etc/xdg/caramos-xfce/.../xfce4-panel.xml, the ISO's file) get it, and each user whose panels are their
  own, with xfconf-query as migration 20261120100400 does. xfce4-panel reads its plugins when it starts, so the strip
  shows from the next login.

A panel that has a show-desktop button already (Cinnamon's corner bar or show-desktop applet, Xfce's Show Desktop
plugin) is left as it is, and so is a panel without Feedback & Help (Cinnamon) or the Control Center (Xfce): someone
changed it by hand. Cinnamon 6.6 crashes when the system dconf database is rebuilt under a running session: with
someone logged in, `dconf update` waits (see 20261012180000_add_help_applet).
"""

from __future__ import annotations

import ast
import importlib
import re
import subprocess
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from caramos_ota_update.context import MigrationContext, MigrationContextError
from caramos_ota_update.desktop import CINNAMON, XFCE, current_desktop

DESCRIPTION = "Show desktop at the end of the taskbar on both editions"

help_applet = importlib.import_module("caramos_ota_update.migrations.20261012180000_add_help_applet.migration")
clipboard = importlib.import_module("caramos_ota_update.migrations.20261120100000_clipboard_history.migration")
lunar_clock = importlib.import_module("caramos_ota_update.migrations.20261120100400_xfce_lunar_clock.migration")

# Cinnamon --------------------------------------------------------------------------------------------------------

CORNER_BAR = "cornerbar@cinnamon.org"
HELP = help_applet.APPLET_UUID
# Applets that show the desktop already: a panel with one of them gets no corner bar.
SHOWS_DESKTOP = (CORNER_BAR, "show-desktop@cinnamon.org")
CORNER_BAR_DIR = Path("/usr/share/cinnamon/applets") / CORNER_BAR
PANEL_DCONF_FILE = help_applet.PANEL_DCONF_FILE


def add_corner_bar(enabled_applets: str) -> str | None:
    """enabled-applets with the corner bar last in the right zone of the panel that holds Feedback & Help.

    The value comes back as it is when a panel shows the desktop already or no panel holds Feedback & Help, and None
    when its format is unknown. Entries are panel:zone:position:uuid:instance; the new instance id is not used by any
    applet.
    """

    value = enabled_applets.strip()
    if value.startswith("@as "):
        value = value[4:].lstrip()
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(parsed, list) or any(not isinstance(entry, str) for entry in parsed):
        return None
    entries = [entry.split(":") for entry in parsed]
    if any(len(parts) < 4 for parts in entries):
        return None
    if any(parts[3] in SHOWS_DESKTOP for parts in entries):
        return value
    helper = next((parts for parts in entries if parts[3] == HELP and parts[1] == "right"), None)
    if helper is None:
        return value
    panel = helper[0]
    position = max((int(parts[2]) for parts in entries if parts[0] == panel and parts[1] == "right"
                    and parts[2].isdigit()), default=-1) + 1
    ids = [int(parts[4]) for parts in entries if len(parts) >= 5 and parts[4].isdigit()]
    entry = f"{panel}:right:{position}:{CORNER_BAR}:{max(ids, default=-1) + 1}"
    return f"[{', '.join(repr(item) for item in [*parsed, entry])}]"


def updated_defaults(source: str) -> str | None:
    """The panel defaults file with the corner bar; None when it has no enabled-applets to add to."""

    lines = source.splitlines()
    in_section = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == f"[{help_applet.CINNAMON_SECTION}]"
            continue
        if in_section and stripped.startswith("enabled-applets="):
            updated = add_corner_bar(stripped.split("=", 1)[1])
            if updated is None:
                return None
            lines[index] = f"enabled-applets={updated}"
            return "\n".join(lines) + "\n"
    return None


def cinnamon_defaults(context: MigrationContext, users: list[tuple[str, int, Path]],
                      path: Path = PANEL_DCONF_FILE) -> None:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        context.log(f"no panel defaults at {path}; leave them as they are")
        return
    updated = updated_defaults(source)
    if updated is None or updated == source:
        context.log(f"{path}: Show desktop is there already, or the panel is not CaramOS's; left alone")
        return
    context.write_file_if_changed(path, updated)
    if context.dry_run:
        return
    logged_in = [username for username, uid, _home in users if help_applet._session_bus(uid).exists()]
    if logged_in:
        context.log(f"{', '.join(logged_in)} logged in: dconf update waits, Cinnamon would crash under it")
    else:
        context.run_command(["dconf", "update"], allow_fail=True)


def _reload_help(username: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Feedback & Help again, with the stylesheet that draws the corner bar (this package's)."""

    return subprocess.run(["runuser", "-u", username, "--", "dbus-send", "--session", "--dest=org.Cinnamon",
                           "--type=method_call", "--print-reply", "/org/Cinnamon", "org.Cinnamon.ReloadXlet",
                           f"string:{HELP}", "string:APPLET"],
                          check=False, capture_output=True, text=True, env=env, timeout=30)


def cinnamon_user(context: MigrationContext, username: str, uid: int, home: Path) -> None:
    env = help_applet._user_environment(username, uid, home)
    current = help_applet._gsettings(username, env, ["get", "org.cinnamon", "enabled-applets"])
    if current.returncode != 0:
        context.log(f"warning: could not read the panel of {username}: {current.stderr.strip()}")
        return
    updated = add_corner_bar(current.stdout)
    if updated is None:
        context.log(f"warning: unexpected panel applets for {username}; leave the panel as it is")
        return
    if updated == current.stdout.strip().removeprefix("@as ").lstrip():
        context.log(f"Show desktop is on the panel of {username} already, or it has no Feedback & Help")
        return
    if "DBUS_SESSION_BUS_ADDRESS" in env and not context.unattended:
        try:
            reloaded = _reload_help(username, env)
            if reloaded.returncode != 0:
                context.log(f"Feedback & Help of {username} did not reload: {reloaded.stderr.strip()[:200]}")
        except subprocess.TimeoutExpired:
            context.log(f"Feedback & Help of {username} did not reload in time")
    result = help_applet._gsettings(username, env, ["set", "org.cinnamon", "enabled-applets", updated])
    if result.returncode == 0:
        context.log(f"Show desktop is at the end of the panel of {username}")
    else:
        context.log(f"warning: could not add Show desktop for {username}: {result.stderr.strip()}")


def run_cinnamon(context: MigrationContext) -> None:
    if not (CORNER_BAR_DIR / "applet.js").is_file():
        context.log(f"{CORNER_BAR_DIR} is missing; the panel is left as it is")
        return
    users = help_applet._desktop_users()
    cinnamon_defaults(context, users)
    if context.dry_run:
        context.log("add Show desktop to the end of the panel of every Cinnamon user")
        return
    for username, uid, home in users:
        cinnamon_user(context, username, uid, home)


# Xfce ------------------------------------------------------------------------------------------------------------

STRIP = "caramos-show-desktop"
STRIP_PLUGIN = Path("/usr/share/xfce4/panel/plugins") / f"{STRIP}.desktop"
PLUGIN_PACKAGE = "xfce4-caramos-plugin"
CONTROL_CENTER = lunar_clock.CONTROL_CENTER
# Plugins that show the desktop already.
XFCE_SHOWS_DESKTOP = (STRIP, "showdesktop")
# Linux Mint's own panel defaults (/etc/xdg/xdg-xfce) number their plugins up to 14, and Xfce merges them with
# CaramOS's: a new plugin gets a number above.
MINT_PLUGINS = 14
PANEL_DEFAULTS = lunar_clock.PANEL_DEFAULTS


def plan(panels: list[int], plugin_ids: dict[int, list[int]], names: dict[int, str]) -> tuple[int, int, bool] | None:
    """(panel, plugin number, whether that plugin is new) for the strip: last in the panel that holds the Control
    Center. A plugin named caramos-show-desktop that no panel holds is used again. None when that panel shows the
    desktop already, or no panel holds the Control Center."""

    panel = next((panel for panel in panels
                  if any(names.get(plugin) == CONTROL_CENTER for plugin in plugin_ids.get(panel, []))), None)
    if panel is None:
        return None
    if any(names.get(plugin) in XFCE_SHOWS_DESKTOP for plugin in plugin_ids[panel]):
        return None
    used = {plugin for ids in plugin_ids.values() for plugin in ids}
    spare = sorted(plugin for plugin, name in names.items() if name == STRIP and plugin not in used)
    if spare:
        return panel, spare[0], False
    return panel, max([*names, *used, MINT_PLUGINS]) + 1, True


def defaults_with_strip(text: str) -> str:
    """CaramOS's system defaults with the strip last in the Control Center's panel, the rest of the file (comments
    too) as it was; "" when there is nothing to change or the file is not as expected."""

    try:
        layout = lunar_clock._layout(ElementTree.fromstring(text))
    except ElementTree.ParseError:
        return ""
    found = plan(*layout) if layout else None
    if found is None or not found[2]:
        return ""
    panel, plugin, _new = found
    try:
        panel_start = text.index(f'<property name="panel-{panel}" type="empty">')
        ids_start = text.index('<property name="plugin-ids" type="array">', panel_start)
        ids_end = text.index("</property>", ids_start)
        plugins_start = text.index('<property name="plugins" type="empty">')
    except ValueError:
        return ""
    last_value = list(re.finditer(r'\n([ \t]*)<value type="int" value="\d+"/>', text[ids_start:ids_end]))
    if not last_value:
        return ""
    at = ids_start + last_value[-1].end()
    new = f'{text[:at]}\n{last_value[-1].group(1)}<value type="int" value="{plugin}"/>{text[at:]}'
    # The plugin's own line goes last among the plugins, before the block's closing tag.
    plugins_start = new.index('<property name="plugins" type="empty">')
    indent = re.match(r"[ \t]*", new[new.rindex("\n", 0, plugins_start) + 1:]).group(0)
    closing = new.find(f"\n{indent}</property>", plugins_start)
    if closing < 0:
        return ""
    new = f'{new[:closing]}\n{indent}  <property name="plugin-{plugin}" type="string" value="{STRIP}"/>{new[closing:]}'
    try:
        after = lunar_clock._layout(ElementTree.fromstring(new))
    except ElementTree.ParseError:
        return ""
    if after is None or after[1].get(panel, [])[-1:] != [plugin] or after[2].get(plugin) != STRIP:
        return ""
    if [ids for key, ids in sorted(after[1].items()) if key != panel] != \
            [ids for key, ids in sorted(layout[1].items()) if key != panel]:
        return ""
    return new


def xfce_defaults(context: MigrationContext, path: Path = PANEL_DEFAULTS) -> None:
    try:
        new = defaults_with_strip(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        context.log(f"no {path}")
        return
    except (OSError, UnicodeDecodeError):
        new = ""
    if new:
        context.write_file_if_changed(path, new)
    else:
        context.log(f"{path}: Show desktop is there already, or the panels are not as expected; left alone")


def xfce_user(context: MigrationContext, username: str, uid: int, home: Path,
              runtime_root: Path = clipboard.RUNTIME_ROOT) -> None:
    if not (home / lunar_clock.USER_PANELS).is_file():
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
        result = context.run_command([*prefix, *lunar_clock.QUERY, *args], allow_fail=True, env=env)
        return result.stdout if result is not None and result.returncode == 0 else None

    listed = query("-l", "-v")
    panels = lunar_clock.array(query("-p", "/panels") or "")
    if listed is None or panels is None:
        context.log(f"Xfce panels of {username}: could not be read; left alone")
        return
    names = {int(name.rsplit("-", 1)[1]): value
             for name, value in clipboard.xfce_properties(listed).items()
             if re.fullmatch(r"/plugins/plugin-\d+", name)}
    plugin_ids = {}
    for panel in panels:
        ids = lunar_clock.array(query("-p", f"/panels/panel-{panel}/plugin-ids") or "")
        if ids is None:
            context.log(f"Xfce panels of {username}: panel {panel} could not be read; left alone")
            return
        plugin_ids[panel] = ids
    found = plan(panels, plugin_ids, names)
    if found is None:
        context.log(f"Xfce panels of {username}: Show desktop there already, or no Control Center")
        return
    panel, plugin, new = found
    if new:
        made = context.run_command([*prefix, *lunar_clock.QUERY, "-p", f"/plugins/plugin-{plugin}", "-n",
                                    "-t", "string", "-s", STRIP], allow_fail=True, env=env)
        if made is None or made.returncode != 0:
            context.log(f"warning: could not add Show desktop for {username}: "
                        f"{made.stderr.strip() if made is not None else 'not run'}")
            return
    values = [arg for item in [*plugin_ids[panel], plugin] for arg in ("-t", "int", "-s", str(item))]
    result = context.run_command([*prefix, *lunar_clock.QUERY, "-p", f"/panels/panel-{panel}/plugin-ids",
                                  "--force-array", *values], allow_fail=True, env=env)
    if result is None or result.returncode != 0:
        context.log(f"warning: could not add Show desktop to the panel of {username}: "
                    f"{result.stderr.strip() if result is not None else 'not run'}")
    else:
        context.log(f"Show desktop ends the taskbar of {username} from the next login")


def _plugin_ready(context: MigrationContext, plugin: Path = STRIP_PLUGIN) -> bool:
    """Whether xfce4-panel can load the strip, after upgrading xfce4-caramos-plugin when it is older."""

    if plugin.exists():
        return True
    if not clipboard._installed(context, PLUGIN_PACKAGE):
        context.log(f"{PLUGIN_PACKAGE} is not installed: no CaramOS taskbar to add Show desktop to")
        return False
    try:
        context.apt_install([PLUGIN_PACKAGE], recommends=False)
    except MigrationContextError as exc:
        context.log(f"could not upgrade {PLUGIN_PACKAGE} ({exc})")
    if context.dry_run or plugin.exists():
        return True
    context.log(f"{plugin} is missing after the upgrade: the taskbar is left as it is")
    return False


def run_xfce(context: MigrationContext) -> None:
    if not _plugin_ready(context):
        return
    xfce_defaults(context)
    if context.dry_run:
        context.log("add Show desktop to the end of the taskbar of every Xfce user")
        return
    for username, uid, home in clipboard._desktop_users():
        xfce_user(context, username, uid, home)


def run(context: MigrationContext, desktop: str | None = None) -> None:
    desktop = current_desktop() if desktop is None else desktop
    if desktop == CINNAMON:
        run_cinnamon(context)
    elif desktop == XFCE:
        run_xfce(context)
    else:
        context.log(f"desktop {desktop}: no taskbar to add Show desktop to")

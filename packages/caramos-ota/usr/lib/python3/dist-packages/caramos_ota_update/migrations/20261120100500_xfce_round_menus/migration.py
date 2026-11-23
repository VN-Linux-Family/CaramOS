"""CaramOS Xfce: the CaramOS menu (Whisker) with round corners, like the islands and the Control Center (users asked
for it after 1.4.0; the right-click menus of both editions are migration 20261120100600).

The look is CSS in caramos-ota's /usr/share/caramos-ota/xfce/panel-islands.css and panel-islands-dark.css, which the
theme imports on Xfce. Whisker, though, leaves the corners outside its round ones clear only when its window has
transparency, which it gives the window when its menu opacity is under 100; at 100 those corners are black. So the
opacity becomes 99, which looks opaque:

- in CaramOS's system default for the menu (/etc/xdg/caramos-xfce/xfce4/panel/whiskermenu-1.rc, the ISO's file), for
  users who never changed it;
- for each logged-in Xfce user, through the xfconfd of their session: Whisker takes the value at once, so the menu
  cannot show black corners if the session reloads the theme before the next login (a change to dark mode does);
- for a user whose own setting is 100 when not logged in, through a D-Bus session of its own, as migration
  20261120100000 does.

An opacity the user chose under 100 stays. Whisker's settings are xfconf properties of the panel
(/plugins/plugin-N/menu-opacity), its rc file only gives their defaults. The round look shows from the next login.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Xfce: round corners for the CaramOS menu"

WHISKER = "whiskermenu"
WHISKER_DEFAULTS = Path("/etc/xdg/caramos-xfce/xfce4/panel/whiskermenu-1.rc")
USER_PANELS = Path(".config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml")
QUERY = ("xfconf-query", "-c", "xfce4-panel")
OPACITY = 99
# The ISO's lines (config/includes.chroot.xfce/.../whiskermenu-1.rc), so a 1.4.0 file ends up the same.
OPACITY_LINES = (
    "# 99, not 100: Whisker gives its window transparency only under 100, and the round corners of CaramOS's look\n"
    "# (caramos-ota's panel-islands.css) need it. 99 looks opaque.\n"
    f"menu-opacity={OPACITY}\n"
)

clipboard = importlib.import_module("caramos_ota_update.migrations.20261120100000_clipboard_history.migration")


def defaults_with_opacity(text: str) -> str:
    """The menu's defaults with an opacity of 99, unless they give it one under 100 already."""

    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        key, equals, value = line.partition("=")
        if equals and key.strip() == "menu-opacity":
            if value.strip() == "100":
                lines[index] = f"menu-opacity={OPACITY}\n"
            return "".join(lines)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + OPACITY_LINES


def to_set(properties: dict[str, str], logged_in: bool) -> list[int]:
    """The Whisker plugins whose opacity becomes 99: those set to 100, and, in a running session, those that follow
    the default, because the running menu read the old default (100) when it started."""

    plugins = []
    for name, value in properties.items():
        match = re.fullmatch(r"/plugins/plugin-(\d+)", name)
        if not match or value != WHISKER:
            continue
        opacity = properties.get(f"{name}/menu-opacity")
        if opacity == "100" or (opacity is None and logged_in):
            plugins.append(int(match.group(1)))
    return sorted(plugins)


def xfce_defaults(context: MigrationContext, path: Path = WHISKER_DEFAULTS) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        context.log(f"no {path}")
        return
    except (OSError, UnicodeDecodeError) as exc:
        context.log(f"warning: {path} could not be read ({exc}); left alone")
        return
    context.write_file_if_changed(path, defaults_with_opacity(text))


def xfce_user(context: MigrationContext, username: str, uid: int, home: Path,
              runtime_root: Path = clipboard.RUNTIME_ROOT) -> None:
    logged_in = clipboard._logged_in(uid, runtime_root)
    if not logged_in and not (home / USER_PANELS).is_file():
        context.log(f"the CaramOS menu of {username}: still the defaults")
        return
    runtime = runtime_root / str(uid)
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "XDG_CONFIG_DIRS": clipboard.XFCE_CONFIG_DIRS}
    prefix = ["runuser", "-u", username, "--"]
    if logged_in:
        env.update(XDG_RUNTIME_DIR=str(runtime), DBUS_SESSION_BUS_ADDRESS=f"unix:path={runtime}/bus")
    else:
        prefix += ["dbus-run-session", "--"]
    listed = context.run_command([*prefix, *QUERY, "-l", "-v"], allow_fail=True, env=env)
    if listed is None or listed.returncode != 0:
        context.log(f"the CaramOS menu of {username}: its settings could not be read; left alone")
        return
    plugins = to_set(clipboard.xfce_properties(listed.stdout), logged_in)
    if not plugins:
        context.log(f"the CaramOS menu of {username}: nothing to change")
    for plugin in plugins:
        result = context.run_command([*prefix, *QUERY, "-p", f"/plugins/plugin-{plugin}/menu-opacity", "-n",
                                      "-t", "int", "-s", str(OPACITY)], allow_fail=True, env=env)
        if result is None or result.returncode != 0:
            context.log(f"warning: the CaramOS menu of {username} keeps its square corners: "
                        f"{result.stderr.strip() if result is not None else 'not run'}")
        else:
            context.log(f"the CaramOS menu of {username} (plugin {plugin}): opacity {OPACITY}, for its round corners")


def run(context: MigrationContext) -> None:
    xfce_defaults(context)
    if context.dry_run:
        context.log(f"set the CaramOS menu's opacity to {OPACITY} for every Xfce user whose menu is at 100")
        return
    for username, uid, home in clipboard._desktop_users():
        xfce_user(context, username, uid, home)

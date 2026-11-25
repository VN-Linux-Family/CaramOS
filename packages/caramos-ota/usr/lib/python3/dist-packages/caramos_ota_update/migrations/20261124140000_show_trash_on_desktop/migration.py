"""The Trash on the desktop on both editions, as on Windows (ticket H-1210): open it to see or restore deleted files, or
to empty it. Up to 1.5.0 CaramOS hid it on purpose, with the other icons of the file manager's desktop.

Cinnamon (nemo-desktop, org.nemo.desktop trash-icon-visible):
- CaramOS's default (99_caramos.gschema.override, the ISO's file) says true, compiled again.
- /usr/bin/caramos-theme-apply, the ISO's first-login script (once per account), set it to false for every account.
  It now sets true, for accounts made later.
- Every account where it is still false gets true. That false came from the first-login script, not from the person,
  so it changes once for everyone. Someone who does not want the Trash unticks Sọt rác in Cài đặt Hệ thống > Màn hình
  chính. A logged-in desktop shows it at once; in an automatic update, a logged-in account gets it at its next login
  instead (deferred.wait_for_login, LOGIN_ACTIONS), before the desktop starts.

Xfce (xfdesktop, xfce4-desktop /desktop-icons/file-icons/show-trash):
- CaramOS's default (/etc/xdg/caramos-xfce/.../xfce4-desktop.xml, the ISO's file) says true. Users' own files have only
  a blank placeholder (type="empty") there, so it shows from their next login.
- A logged-in user without a value of their own gets it at once (xfconf-query): xfconfd keeps the old default until
  the next login. In an automatic update they get the new default at their next login, like the others.
- A value of their own (Desktop Settings > Icons > Trash) stays.

An automatic update runs it while people work ("unattended": "anytime"): nothing changes on an open desktop.
"""

from __future__ import annotations

import importlib
import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from caramos_ota_update import deferred
from caramos_ota_update.context import MigrationContext
from caramos_ota_update.desktop import CINNAMON, XFCE, current_desktop

DESCRIPTION = "The Trash on the desktop on both editions"
MIGRATION = Path(__file__).resolve().parent.name
LOGIN_STEP = "trash-icon"

help_applet = importlib.import_module("caramos_ota_update.migrations.20261012180000_add_help_applet.migration")
clipboard = importlib.import_module("caramos_ota_update.migrations.20261120100000_clipboard_history.migration")

OVERRIDE = clipboard.OVERRIDE
SCHEMAS = clipboard.SCHEMAS
THEME_SCRIPT = Path("/usr/bin/caramos-theme-apply")
SCHEMA = "org.nemo.desktop"
KEY = "trash-icon-visible"

XFCE_DESKTOP = Path("/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml")
USER_DESKTOP = Path(".config/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml")
CHANNEL = "xfce4-desktop"
PROPERTY = "/desktop-icons/file-icons/show-trash"

_OVERRIDE_LINE = re.compile(r"^(\s*)trash-icon-visible\s*=\s*false\s*$")
_THEME_LINE = "gsettings set org.nemo.desktop trash-icon-visible false"
_XFCE_LINE = re.compile(r'^(\s*)<property name="show-trash" type="bool" value="false"/>\s*$')


def override_updated(text: str) -> str:
    """CaramOS's gschema override with trash-icon-visible=true in [org.nemo.desktop]; "" when there is nothing to
    change."""

    lines = text.splitlines(keepends=True)
    section = ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped
            continue
        if section == f"[{SCHEMA}]" and _OVERRIDE_LINE.match(line):
            lines[index] = _OVERRIDE_LINE.sub(r"\1trash-icon-visible=true", line.rstrip("\n")) + "\n"
            return "".join(lines)
    return ""


def theme_script_updated(text: str) -> str:
    """The first-login script setting the Trash to show; "" when there is nothing to change."""

    if _THEME_LINE not in text:
        return ""
    return text.replace(_THEME_LINE, "gsettings set org.nemo.desktop trash-icon-visible true")


def xfce_defaults_updated(text: str) -> str:
    """CaramOS's xfdesktop defaults with show-trash true; "" when there is nothing to change."""

    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        match = _XFCE_LINE.match(line)
        if match:
            lines[index] = f'{match.group(1)}<property name="show-trash" type="bool" value="true"/>\n'
            return "".join(lines)
    return ""


def own_value(text: str) -> bool | None:
    """The user's own show-trash, from their xfce4-desktop.xml: None when they have none (no property, or xfconf's
    blank placeholder of type "empty")."""

    root = ElementTree.fromstring(text.encode("utf-8"))
    node = root.find("property[@name='desktop-icons']/property[@name='file-icons']/property[@name='show-trash']")
    if node is None or node.get("type") != "bool":
        return None
    return node.get("value") == "true"


def _update_file(context: MigrationContext, path: Path, updated) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        context.log(f"no {path}")
        return False
    except (OSError, UnicodeDecodeError) as exc:
        context.log(f"warning: could not read {path}: {exc}")
        return False
    new = updated(text)
    if not new:
        context.log(f"{path}: the Trash shows already, or the file is not CaramOS's; left alone")
        return False
    context.write_file_if_changed(path, new)
    return True


# Cinnamon -------------------------------------------------------------------------------------------------------

def show_trash(gsettings, log, username: str) -> None:
    """trash-icon-visible true where it is false; gsettings(args) runs gsettings as the user."""

    current = gsettings(["get", SCHEMA, KEY])
    if current.returncode != 0:
        log(f"warning: could not read the desktop icons of {username}: {current.stderr.strip()[:200]}")
        return
    if current.stdout.strip() == "true":
        log(f"the Trash is on the desktop of {username} already")
        return
    result = gsettings(["set", SCHEMA, KEY, "true"])
    if result.returncode == 0:
        log(f"the Trash is on the desktop of {username}")
    else:
        log(f"warning: could not show the Trash for {username}: {result.stderr.strip()[:200]}")


def cinnamon_user(context: MigrationContext, username: str, uid: int, home: Path) -> None:
    env = help_applet._user_environment(username, uid, home)
    show_trash(lambda args: help_applet._gsettings(username, env, args), context.log, username)


def trash_at_login(session: deferred.Session) -> None:
    """At the next login of a user who was logged in during an automatic update, before nemo-desktop starts."""

    if session.desktop == CINNAMON:
        show_trash(lambda args: session.gsettings(*args), session.log, session.username)


LOGIN_ACTIONS = {LOGIN_STEP: trash_at_login}


def run_cinnamon(context: MigrationContext) -> None:
    if _update_file(context, OVERRIDE, override_updated) and not context.dry_run:
        result = context.run_command(["glib-compile-schemas", str(SCHEMAS)], allow_fail=True)
        if result is None or result.returncode != 0:
            context.log(f"warning: glib-compile-schemas failed: {result.stderr.strip() if result is not None else ''}")
    _update_file(context, THEME_SCRIPT, theme_script_updated)
    if context.dry_run:
        context.log("show the Trash on the desktop of every Cinnamon user")
        return
    for username, uid, home in help_applet._desktop_users():
        if deferred.wait_for_login(context, MIGRATION, LOGIN_STEP, username, uid):
            continue
        cinnamon_user(context, username, uid, home)


# Xfce -----------------------------------------------------------------------------------------------------------

def xfce_user(context: MigrationContext, username: str, uid: int, home: Path,
              runtime_root: Path = clipboard.RUNTIME_ROOT) -> None:
    try:
        own = own_value((home / USER_DESKTOP).read_text(encoding="utf-8"))
    except FileNotFoundError:
        own = None
    except (OSError, UnicodeDecodeError, ElementTree.ParseError) as exc:
        context.log(f"desktop icons of {username} could not be read ({exc}); left alone")
        return
    if own is not None:
        context.log(f"{username} chose {'to show' if own else 'not to show'} the Trash; left as it is")
        return
    if not clipboard._logged_in(uid, runtime_root) or context.unattended:
        # An automatic update leaves the open desktop as it is: the new default shows from the next login.
        context.log(f"the Trash shows on the desktop of {username} from the next login")
        return
    runtime = runtime_root / str(uid)
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "XDG_CONFIG_DIRS": clipboard.XFCE_CONFIG_DIRS,
           "XDG_RUNTIME_DIR": str(runtime), "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus"}
    result = context.run_command(["runuser", "-u", username, "--", "xfconf-query", "-c", CHANNEL, "-p", PROPERTY,
                                  "-n", "-t", "bool", "-s", "true"], allow_fail=True, env=env)
    if result is not None and result.returncode == 0:
        context.log(f"the Trash is on the desktop of {username}")
    else:
        context.log(f"warning: could not show the Trash for {username}: "
                    f"{result.stderr.strip()[:200] if result is not None else 'not run'}; it shows from the next login")


def run_xfce(context: MigrationContext) -> None:
    _update_file(context, XFCE_DESKTOP, xfce_defaults_updated)
    if context.dry_run:
        context.log("show the Trash on the desktop of every logged-in Xfce user without a choice of their own")
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
        context.log(f"desktop {desktop}: no desktop icons to change")

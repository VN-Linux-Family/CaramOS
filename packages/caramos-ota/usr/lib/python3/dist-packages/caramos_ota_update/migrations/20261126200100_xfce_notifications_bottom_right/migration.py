"""CaramOS Xfce: notifications at the bottom right of the screen, where Windows shows them (ticket H-1219).

xfce4-notifyd showed them at the top right. Its setting, the xfce4-notifyd channel's /notify-location, becomes
"bottom-right":
- in CaramOS's system default (/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-notifyd.xml, which the
  Xfce session reads before Xfce's own), for accounts that never had it;
- for each account where it is "top-right": xfce4-notifyd 0.9 writes the stock "top-right" into every account's own
  settings the first time it runs, so that value is the old default, not a choice. Any other place stays.
A logged-in user gets it at once, through the xfconfd of the session (the next notification shows at the bottom
right); another user through a D-Bus session of its own, as migration 20261120100500 does. xfce4-notifyd keeps the
notifications inside the screen's work area, above the taskbar.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Xfce: notifications at the bottom right of the screen"

DEFAULTS = Path("/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-notifyd.xml")
USER_SETTINGS = Path(".config/xfce4/xfconf/xfce-perchannel-xml/xfce4-notifyd.xml")
PROPERTY = "/notify-location"
OLD = "top-right"
NEW = "bottom-right"
DEFAULTS_XML = f"""<?xml version="1.0" encoding="UTF-8"?>

<!-- CaramOS Xfce: notifications at the bottom right, where Windows shows them (ticket H-1219). -->
<channel name="xfce4-notifyd" version="1.0">
  <property name="notify-location" type="string" value="{NEW}"/>
</channel>
"""
_LOCATION = re.compile(r'<property name="notify-location" type="string" value="([^"]*)"\s*/>')

clipboard = importlib.import_module("caramos_ota_update.migrations.20261120100000_clipboard_history.migration")


def defaults_updated(text: str | None) -> str:
    """CaramOS's notifyd defaults with the bottom right; "" when there is nothing to change. A place other than the
    old default stays; a file without a place gets one; no file gets CaramOS's."""

    if text is None:
        return DEFAULTS_XML
    match = _LOCATION.search(text)
    if match is not None:
        if match.group(1) != OLD:
            return ""
        return text[:match.start(1)] + NEW + text[match.end(1):]
    if "notify-location" in text or "</channel>" not in text:
        return ""  # not as expected (another type, another layout): someone else's file
    line = f'  <property name="notify-location" type="string" value="{NEW}"/>\n'
    return text.replace("</channel>", line + "</channel>", 1)


def xfce_defaults(context: MigrationContext, path: Path = DEFAULTS) -> None:
    try:
        text: str | None = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = None
    except (OSError, UnicodeDecodeError) as exc:
        context.log(f"warning: {path} could not be read ({exc}); left alone")
        return
    new = defaults_updated(text)
    if new:
        context.write_file_if_changed(path, new)
    else:
        context.log(f"{path}: another place for notifications, kept")


def xfce_user(context: MigrationContext, username: str, uid: int, home: Path,
              runtime_root: Path = clipboard.RUNTIME_ROOT) -> None:
    logged_in = clipboard._logged_in(uid, runtime_root)
    if not logged_in and not (home / USER_SETTINGS).is_file():
        context.log(f"notifications of {username}: the system default, at the bottom right")
        return
    runtime = runtime_root / str(uid)
    env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "XDG_CONFIG_DIRS": clipboard.XFCE_CONFIG_DIRS}
    prefix = ["runuser", "-u", username, "--"]
    if logged_in:
        env.update(XDG_RUNTIME_DIR=str(runtime), DBUS_SESSION_BUS_ADDRESS=f"unix:path={runtime}/bus")
    else:
        prefix += ["dbus-run-session", "--"]
    query = [*prefix, "xfconf-query", "-c", "xfce4-notifyd", "-p", PROPERTY]
    current = context.run_command(query, allow_fail=True, env=env)
    value = current.stdout.strip() if current is not None and current.returncode == 0 else ""
    if value != OLD:
        context.log(f"notifications of {username}: " + (f"{value} of their own, kept" if value
                                                         else "the system default, at the bottom right"))
        return
    result = context.run_command([*query, "-n", "-t", "string", "-s", NEW], allow_fail=True, env=env)
    if result is None or result.returncode != 0:
        context.log(f"warning: notifications of {username} stay at the top right: "
                    f"{result.stderr.strip() if result is not None else 'not run'}")
    else:
        context.log(f"notifications of {username}: at the bottom right" + (" from now on" if logged_in else ""))


def run(context: MigrationContext) -> None:
    xfce_defaults(context)
    if context.dry_run:
        context.log("move the notifications of every Xfce user still at the old top right to the bottom right")
        return
    for username, uid, home in clipboard._desktop_users():
        xfce_user(context, username, uid, home)

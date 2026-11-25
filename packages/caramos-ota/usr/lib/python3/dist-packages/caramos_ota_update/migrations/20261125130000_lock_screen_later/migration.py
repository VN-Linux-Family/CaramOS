"""The screen locks later: about half an hour without use instead of 15 to 20 minutes.

People took the lock for a logout: on the Xfce edition light-locker shows LightDM's login screen, and on both the
password came back after a short coffee break. The screen still goes dark after 15 minutes without use, as before;
the lock now comes 10 to 15 minutes later. "Lock the computer when put to sleep" stays as it is: a computer that goes
to sleep is locked when it wakes up.

Cinnamon (cinnamon-screensaver): the screensaver starts after org.cinnamon.desktop.session idle-delay, 900 s
(Cinnamon's own default), and locks org.cinnamon.desktop.screensaver lock-delay later. CaramOS's default for that
was 300 s (/usr/share/glib-2.0/schemas/99_caramos.gschema.override, the ISO's file); it is 600 s now: locked after
25 minutes. Cinnamon's Screensaver settings only offer 5, 10 or 30 minutes there: 15 would show as an empty choice.

Xfce (xfce4-power-manager and light-locker): the power manager blanks the screen after blank-on-ac or
blank-on-battery minutes (its default: 10, and 5 on battery), and light-locker locks apps.light-locker
lock-after-screensaver seconds after that (its default: 5). CaramOS's defaults are now 15 minutes
(/etc/xdg/caramos-xfce/.../xfce4-power-manager.xml, the ISO's file; the settings allow up to 60) and 900 s (the gschema
override; light-locker allows up to 3600): locked after 30 minutes, on battery too.

Only the system's defaults change: an account whose own setting is there (Cinnamon's Screensaver settings, Xfce's
Power Manager, a value set with gsettings) keeps it. One exception: on Xfce each account usually has light-locker's
keys stored as its own, the stock 5 seconds among them, though nobody chose them (the test computers had all five
keys). An own lock-after-screensaver of exactly 5 is the old default, so it is reset and the new default applies; any
other value stays. A file that is not as CaramOS wrote it is left as it is. The new defaults apply from each user's
next login, when the screensaver and the power manager start again: nothing changes on an open desktop, so an
automatic update runs it while people work.
"""

from __future__ import annotations

import importlib
import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from caramos_ota_update.context import MigrationContext
from caramos_ota_update.desktop import XFCE, current_desktop

DESCRIPTION = "The screen locks after about half an hour without use, on both editions"

SCHEMAS = Path("/usr/share/glib-2.0/schemas")
OVERRIDE = SCHEMAS / "99_caramos.gschema.override"
SCREENSAVER = "org.cinnamon.desktop.screensaver"
OLD_LOCK_DELAY = 300
LOCK_DELAY = 600
LIGHT_LOCKER = "apps.light-locker"
LIGHT_LOCKER_DELAY = 900
OLD_LIGHT_LOCKER_DELAY = 5
LIGHT_LOCKER_KEY = "/apps/light-locker/lock-after-screensaver"
POWER_MANAGER = Path("/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-power-manager.xml")
BLANK_MINUTES = 15
BLANK_KEYS = ("blank-on-ac", "blank-on-battery")

_LOCK_DELAY_LINE = re.compile(rf"^(\s*)lock-delay\s*=\s*(?:uint32\s+)?{OLD_LOCK_DELAY}\s*$")
LIGHT_LOCKER_BLOCK = f"""
# The Xfce edition: light-locker locks the screen 15 minutes after the power manager blanks it (after 15 minutes, in
# /etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-power-manager.xml): after half an hour without use.
# Its own 5 seconds made people think CaramOS logged them out. Locking when the computer goes to sleep stays as it is.
[{LIGHT_LOCKER}]
lock-after-screensaver=uint32 {LIGHT_LOCKER_DELAY}
"""


def override_updated(text: str) -> str:
    """CaramOS's gschema override with the later lock: lock-delay 600 where it is still CaramOS's 300, and
    light-locker's delay where the file has none; "" when there is nothing to change."""

    lines = text.splitlines(keepends=True)
    section = ""
    changed = False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            continue
        match = _LOCK_DELAY_LINE.match(line.rstrip("\n"))
        if section == SCREENSAVER and match:
            lines[index] = f"{match.group(1)}lock-delay=uint32 {LOCK_DELAY}\n"
            changed = True
    new = "".join(lines)
    if not re.search(rf"^\[{re.escape(LIGHT_LOCKER)}\]\s*$", new, re.M):
        new = new.rstrip("\n") + "\n" + LIGHT_LOCKER_BLOCK
        changed = True
    return new if changed else ""


def power_manager_updated(text: str) -> str:
    """CaramOS's Xfce power manager defaults with the screen blanked after 15 minutes, on mains power and on battery;
    "" when the file already says how long (someone chose), or is not as expected. The comments and the rest stay."""

    try:
        root = ElementTree.fromstring(text.encode("utf-8"))
    except ElementTree.ParseError:
        return ""
    group = root.find("property[@name='xfce4-power-manager']")
    if root.tag != "channel" or root.get("name") != "xfce4-power-manager" or group is None:
        return ""
    if any(group.find(f"property[@name='{key}']") is not None for key in BLANK_KEYS):
        return ""
    match = re.search(r'\n([ \t]*)</property>\s*</channel>\s*$', text)
    first = re.search(r'<property name="xfce4-power-manager" type="empty">\n([ \t]*)<', text)
    if match is None or first is None:
        return ""
    indent = first.group(1)
    added = "".join(f'\n{indent}<property name="{key}" type="int" value="{BLANK_MINUTES}"/>' for key in BLANK_KEYS)
    new = text[:match.start()] + added + text[match.start():]
    try:
        group = ElementTree.fromstring(new.encode("utf-8")).find("property[@name='xfce4-power-manager']")
    except ElementTree.ParseError:
        return ""
    if group is None or any(group.find(f"property[@name='{key}']") is None for key in BLANK_KEYS):
        return ""
    return new


def _update(context: MigrationContext, path: Path, updated) -> bool:
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
        context.log(f"{path}: the later lock is there already, or the file is not CaramOS's; left alone")
        return False
    context.write_file_if_changed(path, new)
    return True


def light_locker_user(context: MigrationContext, username: str, uid: int, home: Path) -> None:
    """An account's own lock-after-screensaver of exactly 5 (the old default, stored without anyone choosing it) goes,
    so the new default applies; any other value of its own stays. Invisible on an open desktop: light-locker keeps
    what it read until the next login."""

    help_applet = importlib.import_module("caramos_ota_update.migrations.20261012180000_add_help_applet.migration")
    env = help_applet._user_environment(username, uid, home)
    own = context.run_command(["runuser", "-u", username, "--", "dconf", "read", LIGHT_LOCKER_KEY], allow_fail=True,
                              env=env)
    value = own.stdout.strip() if own is not None and own.returncode == 0 else ""
    if value not in (f"uint32 {OLD_LIGHT_LOCKER_DELAY}", str(OLD_LIGHT_LOCKER_DELAY)):
        context.log(f"light-locker of {username}: " + (f"{value} of their own; left as it is" if value
                                                       else "the system's default"))
        return
    result = help_applet._gsettings(username, env, ["reset", LIGHT_LOCKER, "lock-after-screensaver"])
    if result.returncode == 0:
        context.log(f"light-locker of {username}: the old 5 seconds go; the new default applies from the next login")
    else:
        context.log(f"warning: could not reset light-locker's delay for {username}: {result.stderr.strip()[:200]}")


def run(context: MigrationContext, desktop: str | None = None) -> None:
    desktop = current_desktop() if desktop is None else desktop
    # Both editions have the override; each desktop reads only its own part of it.
    if _update(context, OVERRIDE, override_updated) and not context.dry_run:
        result = context.run_command(["glib-compile-schemas", str(SCHEMAS)], allow_fail=True)
        if result is None or result.returncode != 0:
            context.log(f"warning: glib-compile-schemas failed: {result.stderr.strip() if result is not None else ''}")
    if POWER_MANAGER.parent.is_dir():
        _update(context, POWER_MANAGER, power_manager_updated)
    if desktop == XFCE:
        if context.dry_run:
            context.log("reset light-locker's delay where an account still has the old 5 seconds of its own")
        else:
            help_applet = importlib.import_module(
                "caramos_ota_update.migrations.20261012180000_add_help_applet.migration")
            for username, uid, home in help_applet._desktop_users():
                light_locker_user(context, username, uid, home)
    context.log(f"the screen locks {LOCK_DELAY // 60} minutes after Cinnamon's screensaver starts and "
                f"{LIGHT_LOCKER_DELAY // 60} minutes after Xfce blanks it, from each user's next login; "
                "accounts with a setting of their own keep it")

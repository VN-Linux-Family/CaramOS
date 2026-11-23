"""The Update Center's side of automatic updates; caramos_ota.auto_update is the system's side.

The switch
    enabled() reads the setting (no file: on). change() runs caramos-auto-update-helper through pkexec, which asks for
    an administrator's password, and returns the setting as it is afterwards: unchanged when the window was closed.

The end of an automatic update, for the user of this session
    caramos-ota-auto-update-notify.path, a systemd user unit, runs `caramos-ota-notifier --auto-update-result` when the
    result file changes (notify_result()), and the login autostart looks as well (at_login()):
    - after an update, a notification "CaramOS updated to 1.4.1" whose button See what's new opens the Update Center on
      the changes it installed; once;
    - after a failure, a notification whose button opens the Update Center's failure page, with Ask for help; and at the
      next login that page itself, while the user has not opened it and the update still waits.
    What the user saw is kept in seen_file() (~/.local/state/caramos/auto-update.json). Results older than MAX_AGE_DAYS
    are not shown.

Why an update waited
    The last automatic try is in state.json: waiting_reason() tells the update page why this update did not install by
    itself.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from caramos_ota import auto_update
from caramos_ota.i18n import _

from .constants import PKEXEC_COMMAND, STATE_FILE

NOTIFIER = "/usr/bin/caramos-ota-notifier"
ICON = "caramos-logo"
LOGO_FILE = Path("/usr/share/pixmaps/caramos-logo.png")
IMAGE_SIZE = 64
DESKTOP_ENTRY = "caramos-update-center"
MAX_AGE_DAYS = 14
# How long a notification can still open the Update Center from Cinnamon's notification list.
WAIT_SECONDS = 1800
# How long the pop-up stays on the screen.
POPUP_MS = 20000
CLOSED_EXPIRED = 1
HELPER_TIMEOUT = 300

DONE_NOTIFICATION = "notify-done"
FAILED_NOTIFICATION = "notify-failed"
FAILED_PAGE = "page-failed"


# The switch --------------------------------------------------------------------------------------


def enabled() -> bool:
    return auto_update.is_enabled()


def change(wanted: bool) -> bool:
    """Turn automatic updates on or off through pkexec; the setting afterwards."""

    try:
        subprocess.run([PKEXEC_COMMAND, auto_update.HELPER, "on" if wanted else "off"], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=HELPER_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        pass
    return auto_update.is_enabled()


def read_state(path: Path = STATE_FILE) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return state if isinstance(state, dict) else {}


def waiting_reason(update_info: dict[str, Any] | None, state: dict[str, Any] | None = None) -> str:
    """Why automatic updates did not install this update (auto_update.REASONS); "" when they are off or did not try."""

    if not update_info or not enabled():
        return ""
    last = (read_state() if state is None else state).get(auto_update.STATUS_KEY)
    if not isinstance(last, dict) or last.get("update") != auto_update.update_key(update_info):
        return ""
    if last.get("outcome") == auto_update.FAILED:
        return auto_update.FAILED_BEFORE
    reason = str(last.get("reason") or "")
    return reason if last.get("outcome") == auto_update.SKIPPED and reason in auto_update.REASONS else ""


def service_running(run=subprocess.run) -> bool:
    """caramos-ota-auto-update.service is installing an update now (not waiting 15 minutes to try again)."""

    try:
        result = run(["systemctl", "show", "--property=ActiveState,SubState", auto_update.UNIT],
                     capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    props = dict(line.split("=", 1) for line in (result.stdout or "").splitlines() if "=" in line)
    return props.get("ActiveState") in ("activating", "active", "deactivating") and props.get("SubState") != "auto-restart"


# What this user has seen -------------------------------------------------------------------------


def seen_file(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    state_home = env.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(state_home) / "caramos" / "auto-update.json"


def load_seen(path: Path | None = None) -> dict[str, str]:
    try:
        seen = json.loads((path or seen_file()).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return {key: str(value) for key, value in seen.items()} if isinstance(seen, dict) else {}


def mark(result: dict[str, Any], *keys: str, path: Path | None = None) -> bool:
    """Record that this user was shown the result ("notified", "opened"); False when another notifier did it first."""

    path = path or seen_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path.with_name(path.name + ".lock"), "w", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            seen = load_seen(path)
            identifier = str(result.get("id", ""))
            if all(seen.get(key) == identifier for key in keys):
                return False
            seen.update({key: identifier for key in keys})
            staging = path.with_name(f".{path.name}.{os.getpid()}")
            staging.write_text(json.dumps(seen, indent=2) + "\n", encoding="utf-8")
            os.replace(staging, path)
    except OSError:
        return True   # could not write it down: show it rather than never
    return True


def _age_days(result: dict[str, Any], now: datetime | None = None) -> float:
    try:
        finished = datetime.fromisoformat(str(result.get("finished_at")))
    except (TypeError, ValueError):
        return float("inf")
    now = now or datetime.now().astimezone()
    if finished.tzinfo is None:
        finished = finished.astimezone()
    return (now - finished).total_seconds() / 86400


def relevant(result: dict[str, Any] | None, state: dict[str, Any], now: datetime | None = None) -> bool:
    """A result worth telling: recent, and for a failure, the update it was for still waits."""

    if not result or _age_days(result, now) > MAX_AGE_DAYS:
        return False
    if result.get("outcome") == auto_update.FAILED:
        waiting = state.get("available_update")
        return isinstance(waiting, dict) and auto_update.update_key(waiting) == result.get("update_key")
    return result.get("outcome") == auto_update.DONE


def pending(result: dict[str, Any] | None, state: dict[str, Any], seen: dict[str, str], *, at_login: bool,
            now: datetime | None = None) -> str | None:
    """What this user is shown now: DONE_NOTIFICATION, FAILED_NOTIFICATION, FAILED_PAGE (at login only) or None."""

    if not relevant(result, state, now):
        return None
    identifier = str(result.get("id", ""))
    if result.get("outcome") == auto_update.FAILED:
        if at_login and seen.get("opened") != identifier:
            return FAILED_PAGE
        return FAILED_NOTIFICATION if not at_login and seen.get("notified") != identifier else None
    return DONE_NOTIFICATION if seen.get("notified") != identifier else None


# The notification --------------------------------------------------------------------------------


def notification_texts(result: dict[str, Any]) -> tuple[str, str, str]:
    """(title, body, button) of the notification for a result."""

    if result.get("outcome") == auto_update.FAILED:
        return (_("CaramOS could not update itself"),
                _("Open the Update Center to see what went wrong and to ask for help."), _("View details"))
    target, current = str(result.get("to_version") or ""), str(result.get("from_version") or "")
    title = _("CaramOS updated to %s") % target if target and target != current else _("CaramOS was updated")
    body = _("Restart to finish.") if result.get("restart") else _("Some changes show after you log in again.")
    return title, body, _("See what's new")


def draws_default_action(Notify) -> bool:
    """Whether the notification server shows the "default" action as a button (xfce4-notifyd) instead of opening it
    on a click on the notification (Cinnamon, GNOME)."""

    try:
        info = Notify.get_server_info()
    except Exception:   # noqa: BLE001 - an old libnotify or no server: the Cinnamon way
        return False
    name = info[1] if isinstance(info, tuple) and len(info) > 1 else ""
    return "xfce" in str(name).lower()


def open_update_center() -> None:
    """The Update Center on the last automatic update: what it installed, or the failure page."""

    argv = [NOTIFIER, "--show-auto-update"]
    if os.environ.get("INVOCATION_ID"):
        # Started by systemd (caramos-ota-auto-update-notify.service): the window gets its own scope, or systemd
        # stops it together with the service as soon as this notification exits.
        argv = ["systemd-run", "--user", "--scope", "--quiet", "--collect", "--", *argv]
    subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL)


def logo_image(size: int = IMAGE_SIZE):
    """The CaramOS flower as a picture of the size notifications show: the icon theme has it at 512 px only, which
    xfce4-notifyd draws as it is, over half the screen. None when it cannot be read."""

    try:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf, GLib
    except (ImportError, ValueError):
        return None
    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_size(str(LOGO_FILE), size, size)
    except GLib.Error:
        return None


def show_notification(title: str, body: str, button: str, on_open: Callable[[], Any],
                      wait_seconds: int = WAIT_SECONDS) -> bool:
    """A notification whose button runs on_open, as Driver Check's; False when none could be shown."""

    try:
        import gi

        gi.require_version("Notify", "0.7")
        from gi.repository import GLib, Notify
    except (ImportError, ValueError):
        return False
    if not Notify.init(_("Update Center")):
        return False
    loop = GLib.MainLoop()
    image = logo_image()
    note = Notify.Notification.new(title, body, None if image is not None else ICON)
    if image is not None:
        note.set_image_from_pixbuf(image)
    note.set_hint("desktop-entry", GLib.Variant("s", DESKTOP_ENTRY))
    # Time to read a sentence and press its button: xfce4-notifyd's own 5 seconds are too short, and its list of
    # past notifications has no buttons.
    note.set_timeout(POPUP_MS)

    def opened(_note, _action) -> None:
        on_open()
        loop.quit()

    if "actions" in (Notify.get_server_caps() or []):
        # Cinnamon opens the "default" action on a click on the notification and shows the others as buttons;
        # xfce4-notifyd shows every action as a button, so there it would be the same button twice.
        if not draws_default_action(Notify):
            note.add_action("default", button, opened)
        note.add_action("open", button, opened)

    def closed(closed_note) -> None:
        # Expired popups stay in Cinnamon's notification list, where the button still works.
        if closed_note.get_closed_reason() != CLOSED_EXPIRED:
            loop.quit()

    note.connect("closed", closed)
    try:
        note.show()
    except GLib.Error:
        return False
    GLib.timeout_add_seconds(wait_seconds, loop.quit)
    loop.run()
    Notify.uninit()
    return True


def notify_result(*, at_login: bool = False) -> int:
    """`caramos-ota-notifier --auto-update-result`: the notification for the last automatic update, once."""

    result = auto_update.read_result()
    decision = pending(result, read_state(), load_seen(), at_login=at_login)
    if decision not in (DONE_NOTIFICATION, FAILED_NOTIFICATION) or not mark(result, "notified"):
        return 0
    title, body, button = notification_texts(result)
    show_notification(title, body, button, open_update_center)
    return 0


def at_login() -> dict[str, Any] | None:
    """The login autostart: the failure page's result when it opens now (marked as seen); a notification to show is
    started on its own, so the rest of the login check goes on."""

    result = auto_update.read_result()
    decision = pending(result, read_state(), load_seen(), at_login=True)
    if decision == FAILED_PAGE:
        mark(result, "notified", "opened")
        return result
    if decision == DONE_NOTIFICATION:
        try:
            subprocess.Popen([NOTIFIER, "--auto-update-result"], start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    return None


def failure_detail(result: dict[str, Any]) -> str:
    """What the failure page shows under Details and sends with a help request: when it ran, then its output."""

    header = f"Automatic update (caramos-ota --auto-upgrade), {result.get('started_at', '?')} to " \
             f"{result.get('finished_at', '?')}, exit code {result.get('exit_code', '?')}"
    return f"{header}\n\n{str(result.get('output') or '').strip()}"

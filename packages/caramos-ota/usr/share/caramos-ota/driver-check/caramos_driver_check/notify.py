"""Notifications: Driver Check at login or when a device that needs a driver is plugged in, and VNLF's answers
to the user's requests (caramos-help --refresh).

Only GLib and libnotify are loaded: GTK starts only if the user opens the app."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

from caramos_ota.i18n import _, ngettext

from . import actions
from . import state as user_state
from .analysis import Report
from .helpdesk import News

COMMAND = "/usr/bin/caramos-driver-check"
ICON = "hardinfo"   # a green circuit board in CaramOS's Tela icons
HELP_COMMAND = "/usr/bin/caramos-help"
HELP_ICON = "help-browser"   # Feedback & Help in the menu
# How long a notification can still open the app from Cinnamon's notification list.
WAIT_SECONDS = {
    user_state.NOTIFY_PROBLEMS: 900,
    user_state.NOTIFY_RESOLVED: 120,
}
REPLY_WAIT_SECONDS = 900
CLOSED_EXPIRED = 1


def text_for(decision: user_state.Decision, report: Report) -> tuple[str, str]:
    if decision.action == user_state.NOTIFY_PROBLEMS:
        first = decision.new[0]
        if len(decision.new) == 1:
            return first.title, _("Open Driver Check to see how to fix it.")
        return first.title, _("Driver Check found %d things to fix. Open it to see how.") % len(decision.new)
    return _("Hardware problem solved"), _("The driver problem Driver Check told you about is gone.")


def show(title: str, body: str, wait_seconds: int) -> int:
    """A notification whose button opens the app."""

    return _show(_("Driver Check"), "caramos-driver-check", ICON, title, body, wait_seconds, _("View details"),
                 lambda: _start([COMMAND]))


def news_text(news: Sequence[News]) -> tuple[str, str]:
    if len(news) == 1:
        request = news[0].request
        if news[0].reply:
            title = _("VNLF answered your request %s") % request.get("id", "")
        else:
            title = _("The community answered your request %s") % request.get("id", "")
        return title, str(request.get("message", ""))
    count = len(news)
    return (ngettext("New answers to %d of your requests", "New answers to %d of your requests", count) % count,
            ", ".join(str(item.request.get("id", "")) for item in news))


def show_news(news: Sequence[News]) -> int:
    """VNLF or the community answered: the button opens the request's page, or the list when there are several."""

    title, body = news_text(news)
    if len(news) == 1:
        url = str(news[0].request["url"])
        return _show(_("Feedback & Help"), "caramos-help", HELP_ICON, title, body, REPLY_WAIT_SECONDS,
                     _("See the answer"), lambda: actions.open_url(url))
    return _show(_("Feedback & Help"), "caramos-help", HELP_ICON, title, body, REPLY_WAIT_SECONDS,
                 _("See your requests"), lambda: _start([HELP_COMMAND, "--requests"]))


def _start(argv: list[str]) -> None:
    if os.environ.get("INVOCATION_ID"):
        # Started by systemd (caramos-driver-check-hotplug.service): the app gets its own scope, or systemd
        # stops it together with the service as soon as this notification exits.
        argv = ["systemd-run", "--user", "--scope", "--quiet", "--collect", "--", *argv]
    subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL)


def _show(app: str, desktop_entry: str, icon: str, title: str, body: str, wait_seconds: int, button: str,
          on_open: Callable[[], Any]) -> int:
    try:
        import gi

        gi.require_version("Notify", "0.7")
        from gi.repository import GLib, Notify
    except (ImportError, ValueError):
        return 0
    if not Notify.init(app):
        return 0
    loop = GLib.MainLoop()
    note = Notify.Notification.new(title, body, icon)
    note.set_hint("desktop-entry", GLib.Variant("s", desktop_entry))

    def open_app(_note, _action) -> None:
        on_open()
        loop.quit()

    if "actions" in (Notify.get_server_caps() or []):
        note.add_action("default", button, open_app)
        note.add_action("open", button, open_app)

    def closed(closed_note) -> None:
        # Expired popups stay in Cinnamon's notification list, where the button still works.
        if closed_note.get_closed_reason() != CLOSED_EXPIRED:
            loop.quit()

    note.connect("closed", closed)
    try:
        note.show()
    except GLib.Error:
        return 0
    GLib.timeout_add_seconds(wait_seconds, loop.quit)
    loop.run()
    Notify.uninit()
    return 0

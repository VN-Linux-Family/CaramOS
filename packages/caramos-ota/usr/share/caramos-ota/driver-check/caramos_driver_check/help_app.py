"""Entry point of Feedback & Help: ask the VNLF community for help, report a bug or send feedback.

    caramos-help                  open the window, with "Ask for help" chosen
    caramos-help --type bug       open it with a bug report chosen (also: os, feedback)
    caramos-help --type bug --message TEXT --log FILE
                                  an app that failed (App Center, Update Center): the form starts with TEXT
                                  and attaches FILE (several --log for several files), see logs.py
    caramos-help --requests       open it on the list of the requests sent from this computer
    caramos-help --refresh        no window: ask VNLF how the requests are doing, notify new answers

The panel applet caramos-help@caramos and the menu start it; the applet runs --refresh now and then. The
form and the way it is sent belong to Driver Check (ui/help.py), so both apps ask the same way and share the
list of sent requests. Starting it again while it is open brings the open window forward with the kind or the
list asked for; what the user wrote stays.
"""

from __future__ import annotations

import argparse
import os
import sys

from caramos_ota.i18n import _

from .app import has_display, make_scanner

APP_ID = "net.vietnamlinuxfamily.CaramOSHelp"
KINDS = ("os", "bug", "feedback")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="caramos-help",
                                     description="Ask the VNLF community for help, report a bug or send feedback.")
    parser.add_argument("--type", dest="kind", choices=KINDS, default="os",
                        help="the kind of request chosen when the window opens (default: os)")
    parser.add_argument("--message", default="", help="the text the form starts with")
    parser.add_argument("--log", dest="logs", action="append", default=[], metavar="FILE",
                        help="a log to attach (only the VNLF team sees it); can be given several times")
    parser.add_argument("--requests", action="store_true", help="open the list of the requests sent from here")
    parser.add_argument("--refresh", action="store_true",
                        help="no window: ask VNLF how the requests are doing and notify new answers")
    return parser.parse_args(argv)


def refresh() -> int:
    """What VNLF says goes into the list of requests, where the panel applet shows it; new answers, VNLF's or the
    community's, are notified."""

    from . import helpdesk, notify

    news = helpdesk.refresh().news
    return notify.show_news(news) if news else 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if parse_args(argv).refresh:   # wrong arguments end here, before a running window gets them
        return refresh()
    if not has_display():
        print("caramos-help: no desktop session", file=sys.stderr)
        return 1

    from caramos_ota import gtk_renderer

    gtk_renderer.apply()  # cairo where OpenGL would run on the CPU
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib

    from .ui.common import load_css
    from .ui.help_window import HelpWindow

    GLib.set_prgname("caramos-help")
    GLib.set_application_name(_("Feedback & Help"))
    application = Adw.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)

    def command_line(app, command_line) -> int:
        from .logs import read_logs

        args = parse_args(command_line.get_arguments()[1:])
        # A second caramos-help hands its arguments to the open window: its paths are relative to its folder.
        logs = read_logs(os.path.join(command_line.get_cwd() or "/", path) for path in args.logs)
        window = app.get_active_window()
        if window is None:
            load_css()
            window = HelpWindow(app, make_scanner(), args.kind, args.message, logs)
        elif not args.requests:
            window.select(args.kind, args.message, logs)
        if args.requests:
            window.show_requests()
        window.present()
        return 0

    application.connect("command-line", command_line)
    return application.run(["caramos-help", *argv])

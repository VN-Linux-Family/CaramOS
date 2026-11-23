"""caramos-business: the window of CaramOS Doanh nghiệp, and the small windows the agent opens on employee machines.

    caramos-business                    the window
    caramos-business --connect URL      sign in to the company's shared folder (the agent's session part asks for it)
    caramos-business --prompt KIND ...  a message, countdown, consent, banner or notice (see ui/prompts.py)
    caramos-business --help-request     "Nhờ IT hỗ trợ": a note for IT, written to the outbox
"""

from __future__ import annotations

import sys

APP_ID = "net.vietnamlinuxfamily.caramos.Business"


def use_renderer() -> None:
    try:  # cairo where OpenGL would run on the CPU, as CaramOS's other GTK 4 programs (caramos-ota)
        from caramos_ota import gtk_renderer

        gtk_renderer.apply()
    except ImportError:
        pass


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--prompt"]:
        from .prompts import DEFAULT_ANSWER, answer_line, run

        if len(argv) < 2:
            print(answer_line(DEFAULT_ANSWER["message"]))
            return 0
        use_renderer()
        return run(argv[1], argv[2:])
    if argv == ["--help-request"]:
        from .prompts import run_help_request

        use_renderer()
        return run_help_request()
    import argparse

    parser = argparse.ArgumentParser(prog="caramos-business")
    parser.add_argument("--connect", metavar="URL", help="sign in to the shared folder at URL")
    args = parser.parse_args(argv)
    use_renderer()

    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib

    from ..i18n import _
    from . import common

    GLib.set_prgname("caramos-business")
    GLib.set_application_name(_("CaramOS Business"))
    if args.connect:
        from .connect import connect_share

        application = Adw.Application(application_id=f"{APP_ID}.Connect", flags=Gio.ApplicationFlags.NON_UNIQUE)
        application.connect("activate", lambda app: (common.load_css(), connect_share(app, args.connect)))
        return application.run([sys.argv[0]])
    application = Adw.Application(application_id=APP_ID)

    def activate(app: Adw.Application) -> None:
        from .window import Window

        common.load_css()
        window = app.get_active_window() or Window(app)
        window.present()

    application.connect("activate", activate)
    return application.run([sys.argv[0]])

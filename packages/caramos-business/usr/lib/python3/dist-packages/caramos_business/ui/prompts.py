"""The employee's side of PROTOCOL.md part 2's UI contract: small windows that stay above the others.

    caramos-business --prompt message --title T --body B --admin NAME [--ack]          read | closed
    caramos-business --prompt countdown --action shutdown|restart|logout|suspend --seconds N
                     [--postpones-left K --postpone-minutes M]                           now | postpone | timeout
    caramos-business --prompt consent --admin NAME --mode view|control                  view | control | refuse
    caramos-business --prompt banner --admin NAME --mode view|control                   stop
    caramos-business --prompt notice                                                    ok
    caramos-business --prompt frozen                                                    ok
    caramos-business --help-request                  writes $XDG_RUNTIME_DIR/caramos-business/outbox/help-<unix>.json

A prompt prints one JSON line {"answer": "..."} and exits 0. Ended by the agent (SIGTERM) it prints nothing."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

KINDS = ("message", "countdown", "consent", "banner", "notice", "frozen")
ACTIONS = ("shutdown", "restart", "logout", "suspend")
MODES = ("view", "control")
CONSENT_SECONDS = 60
MAX_NOTE = 300
DEFAULT_ANSWER = {"message": "closed", "countdown": "timeout", "consent": "refuse", "banner": "stop", "notice": "ok",
                  "frozen": "ok"}
# A prompt never grows past this: longer text scrolls, so that the buttons stay on a 1024×768 screen.
MAX_TEXT_HEIGHT = 360


class PromptError(Exception):
    """Options that do not follow the contract."""


class Parser(argparse.ArgumentParser):
    """Options that do not follow the contract raise PromptError instead of printing usage and exiting."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise PromptError(f"{self.prog}: {message}")


def parse(kind: str, argv: list[str]) -> dict[str, Any]:
    """The options of one kind of prompt, checked as the contract says."""

    if kind not in KINDS:
        raise PromptError(f"unknown prompt: {kind}")
    parser = Parser(prog=f"caramos-business --prompt {kind}", add_help=False)
    if kind == "message":
        parser.add_argument("--title", required=True)
        parser.add_argument("--body", default="")
        parser.add_argument("--admin", default="")
        parser.add_argument("--ack", action="store_true")
    elif kind == "countdown":
        parser.add_argument("--action", required=True, choices=ACTIONS)
        parser.add_argument("--seconds", required=True, type=int)
        parser.add_argument("--postpones-left", type=int, default=0)
        parser.add_argument("--postpone-minutes", type=int, default=0)
    elif kind in ("consent", "banner"):
        parser.add_argument("--admin", default="")
        parser.add_argument("--mode", required=True, choices=MODES)
    options = vars(parser.parse_args(argv))
    if kind == "countdown":
        if not 0 <= options["seconds"] <= 24 * 3600:
            raise PromptError("--seconds is 0 to 86400")
        if options["postpones_left"] < 0 or options["postpone_minutes"] < 0:
            raise PromptError("postpones cannot be negative")
    for key in ("title", "admin"):
        if key in options:
            options[key] = options[key][:200]
    if "body" in options:
        options["body"] = options["body"][:2000]
    return options


def fit_window(window: Any, root: Any, width: int) -> None:
    """Sizes a prompt that cannot be resized to what its content needs at its width: every wrapping label is kept
    within the width (about 7.5 px a character at the system's 10 pt font, less the 24 px margins), and the window's
    height is measured at that width. Left to GTK, the height was worked out for text on fewer lines than it takes,
    and the last row, buttons included, was cut off at the bottom."""

    from gi.repository import Gtk

    chars = max(20, int((width - 48) / 7.5))
    stack = [root]
    while stack:
        widget = stack.pop()
        if isinstance(widget, Gtk.Label) and widget.get_wrap() and widget.get_max_width_chars() < 0:
            widget.set_max_width_chars(chars)
        child = widget.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    _minimum, natural, _baseline, _natural_baseline = root.measure(Gtk.Orientation.VERTICAL, width)
    window.set_default_size(width, natural)


def answer_line(value: str) -> str:
    return json.dumps({"answer": value})


def remaining_text(seconds: int) -> str:
    """'9:05', or '1:02:03' over an hour."""

    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def outbox(environ: dict[str, str] | None = None) -> Path:
    environ = os.environ if environ is None else environ
    runtime = environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(runtime) / "caramos-business" / "outbox"


def write_help_request(note: str, folder: Path | None = None, now: float | None = None) -> Path:
    """{"note"} into the outbox, whole (written beside, then renamed), for the agent to send to /help."""

    folder = folder or outbox()
    folder.mkdir(parents=True, exist_ok=True)
    stamp = int(now if now is not None else time.time())
    path = folder / f"help-{stamp}.json"
    number = 1
    while path.exists():
        path = folder / f"help-{stamp}-{number}.json"
        number += 1
    staging = folder / f".{path.name}.tmp"
    staging.write_text(json.dumps({"note": note.strip()[:MAX_NOTE]}, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(staging, path)
    return path


# -- the windows -------------------------------------------------------------------------------------------------------

def _gtk() -> tuple[Any, Any, Any]:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib, Gtk

    return Adw, GLib, Gtk


def build(kind: str, options: dict[str, Any], application: Any, done: Callable[[str], None]) -> Any:
    """The window of a prompt; done(answer) when the employee answers or the time runs out."""

    Adw, GLib, Gtk = _gtk()
    from ..i18n import _, ngettext
    from . import common, x11

    window = Adw.ApplicationWindow(application=application, resizable=False, default_width=440)
    window.set_title(_("CaramOS Business"))
    x11.stay_above(window)
    view = Adw.ToolbarView()
    header = Adw.HeaderBar(show_title=False)
    view.add_top_bar(header)
    body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    body.add_css_class("prompt-body")
    buttons = Gtk.Box(spacing=12, halign=Gtk.Align.END, margin_top=12)
    content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    content.append(body)
    view.set_content(content)
    window.set_content(view)
    state = {"answered": False, "timer": 0}

    def answer(value: str) -> None:
        if state["answered"]:
            return
        state["answered"] = True
        if state["timer"]:
            GLib.source_remove(state["timer"])
            state["timer"] = 0
        done(value)

    def add_button(text: str, value: str, *classes: str) -> Gtk.Button:
        widget = Gtk.Button(label=text)
        for css_class in classes:
            widget.add_css_class(css_class)
        widget.connect("clicked", lambda _button: answer(value))
        buttons.append(widget)
        return widget

    def every_second(tick: Callable[[], bool]) -> None:
        state["timer"] = GLib.timeout_add_seconds(1, tick)

    def close_request(_window: Any) -> bool:
        if kind == "countdown":
            return True  # closing it does not stop the countdown, and must not end it early
        answer(DEFAULT_ANSWER[kind])
        return False

    window.connect("close-request", close_request)

    if kind == "message":
        window.set_title(_("Message from the company"))
        body.append(common.label(options["title"], "title-2"))
        if options["body"]:
            scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                          max_content_height=MAX_TEXT_HEIGHT)
            scroller.set_child(common.label(options["body"], "paragraph"))
            body.append(scroller)
        if options["admin"]:
            body.append(common.secondary(_("From %s") % options["admin"]))
        if options["ack"]:
            add_button(_("I have read it"), "read", "suggested-action").grab_focus()
        else:
            add_button(_("Close"), "closed", "suggested-action").grab_focus()
    elif kind == "countdown":
        action = options["action"]
        window.set_deletable(False)
        heading = {"shutdown": _("This machine will shut down in"), "restart": _("This machine will restart in"),
                   "logout": _("You will be logged out in"), "suspend": _("This machine will go to sleep in")}[action]
        now_label = {"shutdown": _("Shut down now"), "restart": _("Restart now"), "logout": _("Log out now"),
                     "suspend": _("Sleep now")}[action]
        body.append(common.label(heading, "title-3"))
        clock = common.label(remaining_text(options["seconds"]), "prompt-time")
        body.append(clock)
        body.append(common.label(_("Save your work now."), "paragraph"))
        left, minutes = options["postpones_left"], options["postpone_minutes"]
        if left > 0 and minutes > 0:
            body.append(common.secondary(ngettext("You can postpone it %d more time.",
                                                  "You can postpone it %d more times.", left) % left))
        add_button(now_label, "now")
        if left > 0 and minutes > 0:
            add_button(ngettext("Postpone %d minute", "Postpone %d minutes", minutes) % minutes, "postpone",
                       "suggested-action").grab_focus()
        deadline = time.monotonic() + options["seconds"]

        def tick() -> bool:
            left_seconds = deadline - time.monotonic()
            if left_seconds <= 0:
                state["timer"] = 0
                answer("timeout")
                return False
            clock.set_label(remaining_text(round(left_seconds)))
            return True

        every_second(tick)
    elif kind == "consent":
        admin = options["admin"] or _("The company's IT")
        window.set_title(_("Remote help"))
        body.append(common.label(_("%s wants to help you on this machine") % admin, "title-2"))
        body.append(common.label(_("They will see your screen but cannot use it.") if options["mode"] == "view" else
                                 _("They will see your screen and can use the mouse and keyboard."), "paragraph"))
        body.append(common.label(_("While they help, a small window shows it, with a button to stop."), "paragraph"))
        countdown = common.secondary("")
        body.append(countdown)
        add_button(_("Refuse"), "refuse")
        if options["mode"] == "control":
            add_button(_("Let them only see"), "view")
            add_button(_("Allow"), "control", "suggested-action")
        else:
            add_button(_("Allow"), "view", "suggested-action")
        deadline = time.monotonic() + CONSENT_SECONDS

        def tick() -> bool:
            left_seconds = round(deadline - time.monotonic())
            if left_seconds <= 0:
                state["timer"] = 0
                answer("refuse")
                return False
            countdown.set_label(ngettext("Refused by itself in %d second.", "Refused by itself in %d seconds.",
                                         left_seconds) % left_seconds)
            return True

        tick()
        every_second(tick)
    elif kind == "banner":
        admin = options["admin"] or _("the company's IT")
        window.set_deletable(False)
        window.set_default_size(360, -1)
        header.set_visible(False)
        body.remove_css_class("prompt-body")
        body.add_css_class("banner-window")
        line = Gtk.Box(spacing=12)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True, valign=Gtk.Align.CENTER)
        texts.append(common.label(_("Remote help by %s") % admin, "heading"))
        texts.append(common.secondary(_("They can see your screen.") if options["mode"] == "view" else
                                      _("They can see and use your screen.")))
        line.append(texts)
        stop = Gtk.Button(label=_("Stop"), valign=Gtk.Align.CENTER)
        stop.add_css_class("destructive-action")
        stop.connect("clicked", lambda _button: answer("stop"))
        line.append(stop)
        body.append(line)
        window.set_title(_("Remote help"))
    elif kind == "notice":
        from .. import transparency

        settings, admin_name = transparency.stored_settings()
        window.set_title(_("This machine is managed by the company"))
        window.set_default_size(520, -1)
        body.append(common.label(_("This machine is managed by the company"), "title-2"))
        body.append(common.label(_("Your company manages this machine with CaramOS Business, from the machine %s. "
                                   "This is what it does:") % (admin_name or "?"), "paragraph"))
        lists = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_end=6)
        listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listing.add_css_class("boxed-list")
        for title, sentence in transparency.always_items() + transparency.managed_items(settings):
            listing.append(common.row(title, sentence))
        lists.append(listing)
        lists.append(common.label(_("The company cannot see:"), "heading"))
        never = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        never.add_css_class("boxed-list")
        for item in transparency.never_items():
            never.append(common.row(item))
        lists.append(never)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                      max_content_height=420)
        scroller.set_child(lists)
        body.append(scroller)
        add_button(_("I understand"), "ok", "suggested-action").grab_focus()
    elif kind == "frozen":
        window.set_title(_("This machine is frozen"))
        body.append(common.label(_("This machine is frozen"), "title-2"))
        body.append(common.label(_("This machine undoes every change when it restarts. Save your files on the shared "
                                   "drive or on a USB drive."), "paragraph"))
        add_button(_("I understand"), "ok", "suggested-action").grab_focus()
    if kind != "banner":
        body.append(buttons)
    fit_window(window, view, window.get_default_size()[0])
    window.present()
    return window


def run(kind: str, argv: list[str]) -> int:
    """caramos-business --prompt KIND ...: shows the prompt and prints its answer."""

    try:
        options = parse(kind, argv)
    except PromptError as exc:
        print(exc, file=sys.stderr)
        print(answer_line(DEFAULT_ANSWER.get(kind, "closed")))
        return 0
    Adw, GLib, Gtk = _gtk()
    from gi.repository import Gio

    from . import common

    application = Adw.Application(application_id=f"{common.APP_ID}.Prompt", flags=Gio.ApplicationFlags.NON_UNIQUE)
    result: dict[str, Any] = {"answer": None, "terminated": False}

    def done(value: str) -> None:
        result["answer"] = value
        application.quit()

    def terminated() -> bool:
        result["terminated"] = True
        application.quit()
        return False

    def activate(app: Any) -> None:
        common.load_css()
        app.hold()
        build(kind, options, app, done)

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, terminated)
    application.connect("activate", activate)
    application.run([sys.argv[0]])
    if not result["terminated"]:
        print(answer_line(result["answer"] or DEFAULT_ANSWER[kind]), flush=True)
    return 0


class HelpRequest:
    """"Nhờ IT hỗ trợ": a short note for IT, written to the outbox; the agent sends it."""

    def __init__(self, application: Any, parent: Any = None, finished: Callable[[bool], None] | None = None) -> None:
        Adw, GLib, Gtk = _gtk()
        from ..i18n import _
        from . import common, x11

        self.finished = finished
        self.window = Adw.ApplicationWindow(application=application, resizable=False, default_width=460)
        self.window.set_title(_("Ask IT for help"))
        if parent is not None:
            self.window.set_transient_for(parent)
            self.window.set_modal(True)
        else:
            x11.stay_above(self.window)
        self.stack = Gtk.Stack()
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar(show_title=False))
        view.set_content(self.stack)
        self.window.set_content(view)
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.add_css_class("prompt-body")
        body.append(common.label(_("Ask IT for help"), "title-2"))
        body.append(common.label(_("Write what is wrong in a few words. IT sees it with this machine's name and your "
                                   "login name, and contacts you."), "paragraph"))
        self.text = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8, left_margin=10,
                                 right_margin=10, accepts_tab=False)
        self.text.update_property([Gtk.AccessibleProperty.LABEL], [_("What is wrong")])
        frame = Gtk.Frame()
        frame.set_child(self.text)
        frame.set_size_request(-1, 110)
        body.append(frame)
        self.counter = common.secondary(f"0/{MAX_NOTE}", xalign=1.0)
        body.append(self.counter)
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.END)
        cancel = Gtk.Button(label=_("Cancel"))
        cancel.connect("clicked", lambda _button: self.close(False))
        self.send = Gtk.Button(label=_("Send"), sensitive=False)
        self.send.add_css_class("suggested-action")
        self.send.connect("clicked", lambda _button: self.submit())
        buttons.append(cancel)
        buttons.append(self.send)
        body.append(buttons)
        self.stack.add_named(body, "form")
        # The page after Send is in the stack from the start: the window (which cannot be resized) takes the size of
        # the taller page when it opens. Added later, the page was cut off at the bottom: its "Đóng" button with it.
        self.stack.add_named(self.sent_page(), "sent")
        self.text.get_buffer().connect("changed", self.changed)
        self.window.connect("close-request", lambda _window: self.close(False, closing=True))
        fit_window(self.window, view, 460)
        self.window.present()
        self.text.grab_focus()

    def sent_page(self) -> Any:
        Adw, GLib, Gtk = _gtk()
        from ..i18n import _
        from . import common

        # At the top, as the form: centred, it was pushed down past the bottom edge.
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, valign=Gtk.Align.START)
        page.add_css_class("prompt-body")
        icon = Gtk.Image.new_from_icon_name("mail-send-symbolic")
        icon.set_pixel_size(48)
        icon.add_css_class("dim-label")
        icon.set_halign(Gtk.Align.START)
        page.append(icon)
        page.append(common.label(_("Sent to IT"), "title-2"))
        page.append(common.label(_("IT will contact you. Keep working, or wait near the machine. Their answers show in "
                                   "CaramOS Business, under Your requests."), "paragraph"))
        self.close_button = Gtk.Button(label=_("Close"), halign=Gtk.Align.END, margin_top=12)
        self.close_button.add_css_class("suggested-action")
        self.close_button.connect("clicked", lambda _button: self.close(True))
        page.append(self.close_button)
        return page

    def changed(self, buffer: Any) -> None:
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        if len(text) > MAX_NOTE:
            buffer.set_text(text[:MAX_NOTE])
            return
        self.counter.set_label(f"{len(text)}/{MAX_NOTE}")
        self.send.set_sensitive(bool(text.strip()))

    def submit(self) -> None:
        from ..i18n import _

        buffer = self.text.get_buffer()
        note = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        try:
            write_help_request(note)
        except OSError as exc:
            self.counter.set_label(_("Could not send: %s") % exc.strerror)
            self.counter.add_css_class("problem")
            return
        self.stack.set_visible_child_name("sent")
        self.close_button.grab_focus()
        self.sent = True

    def close(self, sent: bool, closing: bool = False) -> bool:
        sent = sent or getattr(self, "sent", False)
        if self.finished is not None:
            finished, self.finished = self.finished, None
            finished(sent)
        if not closing:
            self.window.close()
        return False


def run_help_request() -> int:
    Adw, GLib, Gtk = _gtk()
    from gi.repository import Gio

    from . import common

    application = Adw.Application(application_id=f"{common.APP_ID}.Help", flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(app: Any) -> None:
        common.load_css()
        HelpRequest(app)

    application.connect("activate", activate)
    application.run([sys.argv[0]])
    return 0

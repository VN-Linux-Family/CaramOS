"""caramos-ota-notices: show this computer's notices from the CaramOS team (caramos_ota.notices), one window at a time.

Run by caramos-ota-notices.timer in each desktop session. Each notice shows once to each user: "Got it" or closing the
window marks it seen (~/.local/state/caramos-ota/notices.json). The text can be selected, so a command in it can be
copied; the link opens in the browser. Nothing happens without a desktop, without the network or without a notice:
the next run tries again. `caramos-ota-notices --list` prints what would show, without a window.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import notices
from .i18n import _, prefers_vietnamese

ICONS = {"info": "dialog-information-symbolic", "warning": "dialog-warning-symbolic",
         "critical": "dialog-error-symbolic"}
APP_ID = "net.vietnamlinuxfamily.caramos.Notices"


def _log(message: str) -> None:
    print(f"caramos-ota-notices: {message}", file=sys.stderr, flush=True)


def to_show(now: datetime | None = None) -> tuple[list[notices.Notice], Path]:
    now = now or datetime.now(timezone.utc)
    path = notices.seen_file()
    found = notices.fetch()
    computer = notices.this_computer(now)
    return notices.pending(found, computer, notices.read_seen(path), now), path


def show(todo: list[notices.Notice], seen_path: Path) -> int:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, Gtk

    from . import adw_style

    english = not prefers_vietnamese()
    queue = list(todo)
    total = len(queue)

    def build(window: Adw.ApplicationWindow) -> None:
        notice = queue[0]
        title, body = notice.text(english)
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=_("A notice from CaramOS"),
                                                subtitle=f"{total - len(queue) + 1}/{total}" if total > 1 else ""))
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18, margin_bottom=24,
                          margin_start=24, margin_end=24)
        top = Gtk.Box(spacing=14)
        icon = Gtk.Image.new_from_icon_name(ICONS.get(notice.level, ICONS["info"]))
        icon.set_pixel_size(32)
        icon.set_valign(Gtk.Align.START)
        if notice.level != "info":
            icon.add_css_class("warning" if notice.level == "warning" else "error")
        # Labels that wrap need a width of their own, or the window is as high as for one long line and cuts the
        # buttons off; only the text can be selected (a command in it copied), and the focus starts on "Got it".
        heading = Gtk.Label(label=title, wrap=True, xalign=0, hexpand=True, max_width_chars=40)
        heading.add_css_class("title-3")
        top.append(icon)
        top.append(heading)
        text = Gtk.Label(label=body, wrap=True, xalign=0, yalign=0, selectable=True, max_width_chars=56, width_chars=56)
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                      max_content_height=360)
        scroller.set_child(text)
        buttons = Gtk.Box(spacing=8, halign=Gtk.Align.END, margin_top=6)
        if notice.link is not None:
            link = Gtk.Button(label=notice.link_label(english))
            link.connect("clicked", lambda *_a, url=notice.link.url: Gio.AppInfo.launch_default_for_uri(url, None))
            buttons.append(link)
        done = Gtk.Button(label=_("Got it"))
        done.add_css_class("suggested-action")
        done.connect("clicked", lambda *_a: next_notice(window))
        buttons.append(done)
        content.append(top)
        content.append(scroller)
        content.append(buttons)
        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(content)
        window.set_content(view)
        window.set_default_widget(done)
        window.set_focus(done)

    def seen_and_next(window: Adw.ApplicationWindow) -> None:
        """The notice on the screen is seen; the next one gets a window of its own, sized for it, before this one
        goes (the application ends with its last window)."""

        try:
            notices.mark_seen(seen_path, queue[0].id)
        except OSError as exc:
            _log(f"could not remember notice {queue[0].id}: {exc}")
        queue.pop(0)
        if queue:
            present(window.get_application())

    def next_notice(window: Adw.ApplicationWindow) -> None:
        seen_and_next(window)
        window.destroy()

    def on_close(window: Adw.ApplicationWindow) -> bool:
        # Closing is dismissing: the notice was on the screen. The others follow.
        seen_and_next(window)
        return False

    def present(app: Adw.Application) -> None:
        window = Adw.ApplicationWindow(application=app, default_width=520, resizable=True)
        window.set_title(_("A notice from CaramOS"))
        window.connect("close-request", on_close)
        build(window)
        window.present()

    def activate(app: Adw.Application) -> None:
        adw_style.apply()
        present(app)

    app = Adw.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
    app.connect("activate", activate)
    return app.run([sys.argv[0]])


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        todo, path = to_show()
    except (OSError, ValueError) as exc:
        _log(f"no notices this time ({exc.__class__.__name__}: {exc})")
        return 0
    if "--list" in args:
        english = not prefers_vietnamese()
        for notice in todo:
            title, _body = notice.text(english)
            print(f"#{notice.id} [{notice.level}] {title}")
        return 0
    if not todo:
        return 0
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        _log(f"{len(todo)} notice(s) wait for a desktop session")
        return 0
    return show(todo, path)

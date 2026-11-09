"""Driver install pages: progress fed by the helper's events, then the result with a restart button."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from gi.repository import Adw, GLib, Gtk

from caramos_ota.i18n import _, ngettext

from ..analysis import Action
from ..install import HelperRun, space_text
from .common import append_log, bottom_bar, clamp, header, icon_bubble, label, log_view, page_box, pill, scrolled

STAGES = {
    "update": lambda: _("Downloading the package list…"),
    "media": lambda: _("Reading the driver from the CaramOS USB stick…"),
    "install": lambda: _("Downloading and installing the driver…"),
    "finish": lambda: _("Finishing…"),
}


def error_text(code: str) -> str:
    return {
        "offline": _("This computer is not online. Get online (see the ways on the previous page) and try again."),
        "no-media": _("The CaramOS USB stick was not found. Plug it into this computer and try again."),
        "refused": _("This driver is not for this computer's hardware, so it was not installed."),
        "busy": _("Another driver installation is running. Wait for it to finish and try again."),
        "apt": _("Installing the packages failed. The details below show why; you can also send a hardware "
                 "report to ask the community."),
        "space": _("There is not enough free disk space for this driver. Free up some space and try again."),
    }.get(code, _("Something went wrong. The details below show what happened."))


class InstallView(Gtk.Box):
    """Runs the helper for the given installs and reports through on_done(ok, restart, error, log, space)."""

    def __init__(self, installs: list[Action], *,
                 on_done: Callable[[bool, bool, str, str, list[dict[str, Any]]], None],
                 on_cancelled: Callable[[], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.installs = installs
        self.on_done = on_done
        self.on_cancelled = on_cancelled
        self.result: dict[str, Any] | None = None
        self.lines: list[str] = []
        self.space: list[dict[str, Any]] = []
        self.run: HelperRun | None = None

        view = Adw.ToolbarView()
        view.add_top_bar(header(_("Installing drivers")))
        content = page_box(16)
        card = Gtk.Box(spacing=22)
        card.add_css_class("hero-card")
        card.append(icon_bubble("folder-download-symbolic", 36, "status-bubble", "status-ok"))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, hexpand=True)
        if len(installs) == 1:
            title = installs[0].label
        else:
            title = ngettext("Installing %d driver", "Installing %d drivers", len(installs)) % len(installs)
        texts.append(label(title, "hero-title"))
        texts.append(label(_("Please keep the computer on. Depending on the network this takes a few minutes."),
                           "hero-subtitle"))
        self.stage = label(_("Waiting for your password…"), "stage-label")
        self.stage.set_margin_top(10)
        texts.append(self.stage)
        self.progress = Gtk.ProgressBar()
        self.progress.add_css_class("overall")
        texts.append(self.progress)
        card.append(texts)
        content.append(card)
        details, self.log = log_view()
        content.append(details)
        page = scrolled(clamp(content, 820))
        page.add_css_class("welcome")
        view.set_content(page)
        view.set_vexpand(True)
        self.append(view)

    @property
    def running(self) -> bool:
        return self.run is not None

    def start(self) -> None:
        self.result = None
        self.lines = []
        self.space = []
        self.progress.set_fraction(0)
        self.run = HelperRun([action.target for action in self.installs], self._on_event, self._on_exit)

    def _on_event(self, event: dict[str, Any]) -> None:
        kind = event["event"]
        if kind == "stage":
            text = STAGES.get(str(event.get("stage")))
            if text is not None:
                self.stage.set_label(text())
        elif kind == "progress":
            self.progress.set_fraction(event["percent"] / 100)
        elif kind == "log":
            line = str(event.get("line", ""))
            self.lines.append(line)
            append_log(self.log, line)
        elif kind == "space":
            self.space.append(event)
        elif kind == "done":
            self.result = event

    def _on_exit(self, code: int, auth_cancelled: bool) -> None:
        self.run = None
        if auth_cancelled and self.result is None:
            self.on_cancelled()
            return
        result = self.result or {"ok": False, "restart": False, "error": "internal"}
        self.on_done(bool(result.get("ok")), bool(result.get("restart")), str(result.get("error") or ""),
                     "\n".join(self.lines), list(self.space))


def done_page(ok: bool, restart: bool, error: str, log: str, *, on_restart: Callable[[], None],
              on_back: Callable[[], None], on_retry: Callable[[], None],
              space: list[dict[str, Any]] | None = None,
              on_help: Callable[[], None] | None = None) -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    view = Adw.ToolbarView()
    view.add_top_bar(header(_("Installing drivers")))
    content = page_box(16)
    content.set_valign(Gtk.Align.CENTER)
    if ok:
        content.append(icon_bubble("emblem-ok-symbolic", 44, "status-bubble", "status-ok"))
        content.append(label(_("The driver is installed"), "hero-title", xalign=0.5))
        content.append(label(_("Restart the computer to start using it.") if restart
                             else _("It is working already; no restart needed."), "hero-subtitle", xalign=0.5))
    else:
        content.append(icon_bubble("dialog-warning-symbolic", 44, "status-bubble", "status-warning"))
        content.append(label(_("The driver was not installed"), "hero-title", xalign=0.5))
        text = space_text(space, GLib.format_size) if error == "space" and space else error_text(error)
        content.append(label(text, "hero-subtitle", xalign=0.5))
        details, _view = log_view(log)
        details.set_expanded(bool(log))
        content.append(details)
    page = scrolled(clamp(content, 760))
    page.add_css_class("welcome")
    view.set_content(page)
    view.set_vexpand(True)
    box.append(view)
    if ok and restart:
        buttons = [pill(_("Later"), on_back), pill(_("Restart now"), on_restart, suggested=True)]
        bar = bottom_bar(_("Restart to finish"), _("Save your work first."), buttons)
    elif ok:
        bar = bottom_bar(_("Done"), "", [pill(_("Back to the results"), on_back, suggested=True)])
    else:
        buttons = [pill(_("Back"), on_back), pill(_("Try again"), on_retry, suggested=True)]
        if on_help is not None:
            # As on the App Center's and the Update Center's failure pages: the request carries the helper's output.
            buttons.insert(1, pill(_("Ask for help"), on_help, icon_name="help-browser-symbolic"))
        bar = bottom_bar(_("Not installed"), "", buttons)
    box.append(bar)
    return box

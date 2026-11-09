"""Main window: scan, results, driver installs and help requests (HelpPages) in one stack of pages.

While the computer is offline because of a missing network driver, the window watches the connection
and checks again once the user plugged in a cable or a phone. It also checks again quietly when it gets
the focus back, e.g. after Driver Manager installed a driver.
"""

from __future__ import annotations

import threading
from time import monotonic
from typing import Any

from gi.repository import Adw, Gio, GLib, Gtk

from caramos_ota.i18n import _

from .. import actions
from ..analysis import INSTALL, REBOOT, REPORT, WIFI_ON, Action, Finding, Report
from ..logs import Log, install_failure_log, system_logs
from .help import HelpPages
from .install import InstallView, done_page
from .results import ResultsView
from .scan import ScanView

POLL_SECONDS = 3
FOCUS_RECHECK_SECONDS = 3


class MainWindow(HelpPages, Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application, scanner) -> None:
        super().__init__(application=application, title=_("Driver Check"), default_width=1000, default_height=780)
        self.set_size_request(360, 480)
        self.scanner = scanner
        self.report: Report | None = None
        self.pending: Report | None = None
        self.scanning = False
        self.busy = False            # a driver install, a hardware report or a help request is running
        self.came_online = False
        self.last_scan = 0.0
        self.poll_id: int | None = None

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=220,
                               vexpand=True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        demo = getattr(scanner, "demo", "")
        if demo:
            # Made-up hardware must never pass for a check of this computer.
            banner = Adw.Banner(title=_("Demo: made-up hardware (%s) to show the app. This is NOT a check of this "
                                        "computer.") % demo, revealed=True)
            banner.add_css_class("demo-banner")
            content.append(banner)
            self.set_title(_("Driver Check (demo)"))
        content.append(self.stack)
        self.toasts = Adw.ToastOverlay(child=content)
        self.set_content(self.toasts)
        self.connect("close-request", self._on_close_request)
        self.connect("notify::is-active", self._on_active)
        Gio.NetworkMonitor.get_default().connect("network-changed", self._on_network_changed)
        self.start_scan()

    def _set_page(self, name: str, widget: Gtk.Widget) -> None:
        old = self.stack.get_child_by_name(name)
        if old is not None:
            self.stack.remove(old)
        self.stack.add_named(widget, name)
        self.stack.set_visible_child_name(name)

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=text))

    # Scanning --------------------------------------------------------------------------------

    def start_scan(self) -> None:
        if self.scanning or self.busy:
            return
        self.scanning = True
        view = ScanView()
        self._set_page("scan", view)

        def work() -> None:
            snapshot = self.scanner.snapshot()
            basic = self.scanner.analyze(snapshot, ())
            GLib.idle_add(lambda: (view.reveal(basic, lambda: self._scan_finished()), False)[1])
            full = self.scanner.analyze(snapshot, self.scanner.proposals(snapshot))
            GLib.idle_add(self._proposals_ready, view, full)

        threading.Thread(target=work, daemon=True).start()

    def _proposals_ready(self, view: ScanView, report: Report) -> bool:
        self.pending = report
        view.drivers_found(len(report.installs))
        return False

    def _scan_finished(self) -> None:
        self.scanning = False
        self.last_scan = monotonic()
        if self.pending is not None:
            self.show_results(self.pending)

    def quiet_rescan(self) -> None:
        """Check again without the scan page; the results change only when something changed."""

        if self.scanning or self.busy:
            return
        self.scanning = True

        def work() -> None:
            snapshot = self.scanner.snapshot()
            report = self.scanner.analyze(snapshot, self.scanner.proposals(snapshot))
            GLib.idle_add(self._quiet_done, report)

        threading.Thread(target=work, daemon=True).start()

    def _quiet_done(self, report: Report) -> bool:
        self.scanning = False
        self.last_scan = monotonic()
        if self.report is not None and report != self.report and self.stack.get_visible_child_name() == "results":
            if self.report.needs_connection and not report.needs_connection and report.connected:
                self.came_online = True
            self.show_results(report)
        return False

    def show_results(self, report: Report) -> None:
        self.report = report
        view = ResultsView(report, came_online=self.came_online, on_action=self._on_action,
                           on_install_all=self.install, on_report=lambda: self.show_help("driver"),
                           on_recheck=self.start_scan, on_close=self.close)
        self._set_page("results", view)
        if report.needs_connection and self.poll_id is None:
            self.poll_id = GLib.timeout_add_seconds(POLL_SECONDS, self._poll)

    def _poll(self) -> bool:
        if self.report is None or not self.report.needs_connection:
            self.poll_id = None
            return False
        if self.scanner.connected():
            self.quiet_rescan()
        return True

    def _on_network_changed(self, _monitor, _available) -> None:
        if self.report is not None and self.report.needs_connection:
            GLib.timeout_add_seconds(2, lambda: (self.quiet_rescan(), False)[1])

    def _on_active(self, *_args) -> None:
        if self.is_active() and self.stack.get_visible_child_name() == "results" \
                and monotonic() - self.last_scan > FOCUS_RECHECK_SECONDS:
            self.quiet_rescan()

    # Actions ---------------------------------------------------------------------------------

    def _on_action(self, action: Action, _finding: Finding | None) -> None:
        if action.kind == INSTALL:
            self.install([action])
            return
        if action.kind == REPORT:
            self.show_help("driver")
            return
        if not actions.run(action.kind):
            self.toast(_("This tool is not installed on this computer."))
            return
        if action.kind == WIFI_ON:
            GLib.timeout_add_seconds(2, lambda: (self.quiet_rescan(), False)[1])

    def install(self, installs: list[Action]) -> None:
        if self.busy or not installs:
            return
        self.busy = True
        view = InstallView(installs, on_done=lambda ok, restart, error, log, space: self._install_done(
            installs, ok, restart, error, log, space), on_cancelled=self._install_cancelled)
        self._set_page("install", view)
        view.start()

    def _install_cancelled(self) -> None:
        self.busy = False
        if self.report is not None:
            self.show_results(self.report)
        self.toast(_("Not installed: the password was not entered."))

    def _install_done(self, installs: list[Action], ok: bool, restart: bool, error: str, log: str,
                      space: list[dict[str, Any]]) -> None:
        self.busy = False
        page = done_page(ok, restart, error, log, on_restart=lambda: actions.run(REBOOT),
                         on_back=self.start_scan, on_retry=lambda: self.install(installs), space=space,
                         on_help=lambda: self._install_help(installs, error, log))
        self._set_page("done", page)

    def _install_help(self, installs: list[Action], error: str, log: str) -> None:
        """Like the App Center's and the Update Center's failure pages: the request starts with what failed and
        carries what the helper printed."""

        targets = [action.target for action in installs]
        self.show_help("driver", _("Driver Check could not install %s.") % ", ".join(targets),
                       (install_failure_log(targets, error, log),))

    # Asking for help (HelpPages) -------------------------------------------------------------

    def show_help(self, kind: str, message: str = "", logs: tuple[Log, ...] = ()) -> None:
        if self.report is None:
            return
        self.help_message, self.help_logs = message, logs
        super().show_help(kind)
        form = self.help_form

        def work() -> None:
            # What the scans logged and this boot's warnings: a freeze or a slow scan shows there.
            try:
                found = system_logs()
            except Exception:   # noqa: BLE001 - a log that cannot be read must not keep the user from asking
                found = ()
            GLib.idle_add(attach, found)

        def attach(found) -> bool:
            if found and form is not None and self.help_form is form:
                self.help_logs = logs + found
                form.set_context("", self.help_logs)
            return False

        threading.Thread(target=work, daemon=True).start()

    def help_report(self) -> Report | None:
        return self.report

    def help_online(self) -> bool:
        return self.scanner.connected()

    def leave_help(self) -> None:
        self._back_to_results()

    def _back_to_results(self) -> None:
        if self.stack.get_child_by_name("results") is not None:
            self.stack.set_visible_child_name("results")
        else:
            self.start_scan()

    def _on_close_request(self, _window) -> bool:
        if self.busy:
            self.toast(_("Please wait until it finishes."))
            return True
        self.help_cleanup()
        if self.poll_id is not None:
            GLib.source_remove(self.poll_id)
            self.poll_id = None
        return False

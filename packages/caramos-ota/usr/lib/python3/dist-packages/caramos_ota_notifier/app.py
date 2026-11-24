"""Desktop notifier orchestration for CaramOS OTA."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Any

from caramos_ota.i18n import _

from caramos_ota import auto_update as system_auto_update

from . import auto_update as auto_update_ui
from . import problem
from .constants import (
    BUSY,
    CANCELLED,
    CHECK_HELPER,
    CHECK_TIMEOUT_SECONDS,
    CHECKED,
    DONE,
    FAILED,
    OFFLINE,
    OTA_BUSY,
    OTA_COMMAND,
    PKEXEC_COMMAND,
    PKEXEC_REFUSED,
    UPGRADE_TIMEOUT_SECONDS,
)
from .state import read_available_update, read_no_update_status, resolve_available_update_now
from .ui import (
    AutoUpdateSwitch,
    build_auto_updated_page,
    build_check_failed_page,
    build_checking_page,
    build_no_update_page,
    build_progress_page,
    build_result_page,
    build_update_page,
    build_update_window,
    import_gtk,
)

LOG_VIEW_LINES = 2000   # the progress view keeps the end of the output; the result page gets all of it
LOG_FLUSH_MS = 100      # queued output lines reach the progress view in one batch at most this often
NOTIFIER = "/usr/bin/caramos-ota-notifier"
AFTER_CHECK = "--after-check"
# The check could not reach the CaramOS PPA: caramos-ota's own message (from 1.5.1), or what apt-get says.
UNREACHABLE = (
    "could not reach the caramos update server",
    "temporary failure resolving",
    "could not resolve",
    "could not connect to",
    "network is unreachable",
    "connection timed out",
    "no route to host",
)


def has_display() -> bool:
    """Return True when a graphical display is available."""

    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def stage_for_line(line: str) -> str:
    """Map updater output to a progress stage in plain words."""

    text = line.lower()
    if "updating package index" in text or "apt-get update" in text:
        return _("Downloading the list of software…")
    if "repository:" in text:
        return _("Checking the update source…")
    if "migration path" in text:
        return _("Preparing the changes…")
    if "run:" in text or "starting migration" in text:
        return _("Applying the changes…")
    if "updated version metadata" in text or "set caramos system version" in text:
        return _("Saving the new version number…")
    if "update complete" in text or "finished migration" in text:
        return _("Finishing…")
    if "error" in text or "failed" in text:
        return _("The update ran into an error.")
    return _("Updating…")


def upgrade_outcome(return_code: int) -> str:
    """DONE, CANCELLED (no password given), BUSY (another update holds the OTA lock) or FAILED.

    Up to 1.3.9 a closed password window and an update already running elsewhere showed "Update failed" and
    offered to send the log to VNLF, though nothing went wrong.
    """

    if return_code == 0:
        return DONE
    if return_code in PKEXEC_REFUSED:
        return CANCELLED
    if return_code == OTA_BUSY:
        return BUSY
    return FAILED


def run_upgrade_stream(on_line) -> tuple[str, str]:
    """Run the OTA upgrade via pkexec and stream output lines to the UI: (upgrade_outcome, output)."""

    output: list[str] = []
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            [PKEXEC_COMMAND, OTA_COMMAND, "--upgrade", "--yes"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert process.stdout is not None

        def kill_process() -> None:
            if process and process.poll() is None:
                process.kill()

        timer = threading.Timer(UPGRADE_TIMEOUT_SECONDS, kill_process)
        timer.start()
        try:
            for raw_line in process.stdout:
                line = raw_line.rstrip("\n")
                output.append(line)
                on_line(line)
            return_code = process.wait(timeout=5)
        finally:
            timer.cancel()
        detail = "\n".join(output).strip()
        if return_code < 0:
            return FAILED, _("The update timed out (10 minutes).")
        return upgrade_outcome(return_code), detail
    except subprocess.TimeoutExpired:
        if process and process.poll() is None:
            process.kill()
        return FAILED, _("The update timed out (10 minutes).")
    except FileNotFoundError:
        return FAILED, _("The pkexec command was not found.")
    except Exception as exc:
        return FAILED, str(exc)


def check_outcome(return_code: int, output: str) -> str:
    """CHECKED, CANCELLED (pkexec refused), BUSY (another update holds the OTA lock), OFFLINE (the CaramOS update
    server could not be reached) or FAILED."""

    if return_code == 0:
        return CHECKED
    if return_code in PKEXEC_REFUSED:
        return CANCELLED
    if return_code == OTA_BUSY:
        return BUSY
    text = output.lower()
    if any(marker in text for marker in UNREACHABLE):
        return OFFLINE
    return FAILED


def run_check() -> tuple[str, str]:
    """Run the daily check now, through pkexec without a password: (check_outcome, output).

    A check that takes too long is left to finish on its own: it runs as root, so this window could not stop it, and
    stopping it halfway could leave a package half installed.
    """

    try:
        process = subprocess.Popen([PKEXEC_COMMAND, CHECK_HELPER], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, errors="replace")
        output, _unused = process.communicate(timeout=CHECK_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return FAILED, _("Checking for updates took too long.")
    except FileNotFoundError:
        return FAILED, _("The pkexec command was not found.")
    except Exception as exc:
        return FAILED, str(exc)
    output = (output or "").strip()
    return check_outcome(process.returncode, output), output


def check_first() -> bool:
    """Whether the Update Center, opened by hand, checks for new versions before it says anything: not on a live USB
    or a frozen system drive, where an update cannot stay."""

    try:
        return not (system_auto_update.live_session() or system_auto_update.overlay_root())
    except Exception:
        return True


def engine_version() -> str:
    """The installed caramos-ota, which a check may have just updated."""

    try:
        result = subprocess.run(["dpkg-query", "-W", "-f=${Version}", "caramos-ota"], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=30, check=False)
    except Exception:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


class UpdateWindowController:
    """Drive every OTA state inside one top-level GTK window.

    auto_result: the result of the last automatic update (caramos_ota.auto_update), shown instead: what it installed,
    or the failure page with Ask for help.
    """

    def __init__(self, Gtk, GLib, update_info: dict[str, Any] | None, no_update_status: dict[str, str] | None,
                 auto_result: dict[str, Any] | None = None, check: bool = False):
        self.Gtk = Gtk
        self.GLib = GLib
        self.update_info = update_info
        self.window, self.stack = build_update_window()
        self.upgrade_running = False
        self.checking = False
        self.shown = False
        self.progress_bar = None
        self.stage_label = None
        self.log_view = None
        self.pulse_source_id: int | None = None
        self.thread: threading.Thread | None = None
        # Lines from the updater thread wait here until the GTK thread shows them, see queue_log_line.
        self._log_lock = threading.Lock()
        self._log_queue: list[str] = []
        self._log_flush_queued = False
        self._log_end_queued = False

        self.window.connect("delete-event", self._on_delete_event)

        if auto_result is not None:
            self._show_auto_result(auto_result)
        elif update_info is None and check:
            # Opened by hand with nothing waiting: ask the CaramOS PPA before saying CaramOS is up to date.
            self.start_check()
        elif update_info is None:
            self._show_no_update(no_update_status)
        else:
            self._show_update(update_info)

    def _show_page(self, name: str, page) -> None:
        """Show a page, in place of an older one of the same name (after Try again)."""

        old = self.stack.get_child_by_name(name)
        if old is not None:
            self.stack.remove(old)
        self.stack.add_named(page, name)
        if self.shown:   # the window's show_all showed the pages added before it
            page.show_all()
        self.stack.set_visible_child_name(name)

    def _show_no_update(self, status: dict[str, str] | None) -> None:
        self._show_page("no-update", build_no_update_page(status, self.close, auto_update=self.auto_update_switch()))

    def _show_update(self, update_info: dict[str, Any]) -> None:
        self.update_info = update_info
        note = auto_update_ui.waiting_reason(update_info)
        info_page = build_update_page(update_info, self.start_upgrade, self.close,
                                      auto_update=self.auto_update_switch(note))
        progress_page, self.progress_bar, self.stage_label, self.log_view = build_progress_page(update_info)
        self.log_view.get_vadjustment().connect("changed", self._log_resized)
        old = self.stack.get_child_by_name("progress")
        if old is not None:
            self.stack.remove(old)
        self.stack.add_named(progress_page, "progress")
        if self.shown:
            progress_page.show_all()
        self._show_page("info", info_page)

    def start_check(self) -> None:
        """Check for new versions (again after Try again): the daily check, now, through pkexec without a password.

        Up to 1.5.0 the window only read the updater already installed. Where the daily check kept failing (a
        software source that no longer worked, a firewall), it said CaramOS was up to date for weeks: CaramOS 1.3.3
        computers were still told so when 1.5.0 was out.
        """

        if self.checking:
            return
        self.checking = True
        self._show_page("checking", build_checking_page(self.close))
        self.thread = threading.Thread(target=self._do_check, daemon=True)
        self.thread.start()

    def _do_check(self) -> None:
        before = engine_version()
        outcome, output = run_check()
        self.GLib.idle_add(self.on_check_done, outcome, output, engine_version() != before)

    def on_check_done(self, outcome: str, output: str, engine_updated: bool = False) -> bool:
        """Show what the check found: the update, CaramOS up to date, or why it could not check."""

        self.checking = False
        if outcome == CHECKED:
            if engine_updated:
                self.restart_after_check()
            update_info, status = resolve_available_update_now()
            if update_info is None:
                self._show_no_update(status)
            else:
                self._show_update(update_info)
            return False
        on_help = None
        if outcome in (FAILED, OFFLINE) and problem.help_available():
            on_help = lambda: problem.ask_for_help(output, None, checking=True)   # noqa: E731
        self._show_page("check-failed", build_check_failed_page(outcome, output, self.close, on_help, self.start_check))
        return False

    def restart_after_check(self) -> None:
        """The check installed a newer updater: open the Update Center again with that updater's code, which knows
        its own changes. Returns only if that did not work."""

        try:
            sys.stdout.flush()
            sys.stderr.flush()
            os.execv(NOTIFIER, [NOTIFIER, AFTER_CHECK])
        except OSError:
            pass

    def auto_update_switch(self, note: str = "") -> AutoUpdateSwitch:
        return AutoUpdateSwitch(enabled=auto_update_ui.enabled(), on_toggle=self.toggle_auto_update, note=note)

    def toggle_auto_update(self, wanted: bool, finish) -> None:
        """The person flipped Automatic updates: pkexec asks for an administrator's password in a thread of its own,
        then the switch goes where the setting is."""

        def work() -> None:
            self.GLib.idle_add(finish, auto_update_ui.change(wanted))

        threading.Thread(target=work, daemon=True).start()

    def _show_auto_result(self, result: dict[str, Any]) -> None:
        if result.get("outcome") == auto_update_ui.auto_update.FAILED:
            # The page a failed update shows in the Update Center, with this run's output under Details.
            self.update_info = result.get("update") or None
            detail = auto_update_ui.failure_detail(result)
            on_help = None
            if problem.help_available():
                on_help = lambda: problem.ask_for_help(detail, self.update_info)   # noqa: E731
            page = build_result_page(FAILED, detail, self.close, on_help, None, update_info=self.update_info)
            self.stack.add_named(page, "result")
            self.stack.set_visible_child_name("result")
            return
        page = build_auto_updated_page(result, self.close, auto_update=self.auto_update_switch())
        self.stack.add_named(page, "auto-updated")
        self.stack.set_visible_child_name("auto-updated")

    def show(self) -> None:
        """Show the update center and start its single GTK loop."""

        self.window.show_all()
        self.shown = True

    def close(self) -> bool:
        """Close the window unless an upgrade is active."""

        if self.upgrade_running:
            return True
        self.window.destroy()
        self.Gtk.main_quit()
        return False

    def _on_delete_event(self, _window, _event) -> bool:
        if self.upgrade_running:
            return True
        self.Gtk.main_quit()
        return False

    def start_upgrade(self) -> None:
        """Switch to progress and launch the privileged updater (again after Try again)."""

        if self.upgrade_running or self.progress_bar is None:
            return

        self.upgrade_running = True
        self.window.set_deletable(False)
        if self.log_view is not None and self.stage_label is not None:
            # Try again: the progress shows this run only.
            self.log_view.get_buffer().set_text("")
            self.stage_label.set_text(_("Getting ready…"))
            self.progress_bar.set_fraction(0.0)
        self.stack.set_visible_child_name("progress")
        self.pulse_source_id = self.GLib.timeout_add(100, self.pulse)

        self.thread = threading.Thread(target=self._do_upgrade, daemon=True)
        self.thread.start()

    def _do_upgrade(self) -> None:
        outcome, detail = run_upgrade_stream(self.queue_log_line)
        self.GLib.idle_add(self.on_upgrade_done, outcome, detail)

    def queue_log_line(self, line: str) -> None:
        """Queue one updater line (updater thread); the GTK thread shows the queue every LOG_FLUSH_MS.

        Up to 1.3.5 every line had its own GLib callback and its own text mark, never deleted, so each
        line cost more than the one before. The update that finished an NVIDIA install left unfinished by
        Driver Check printed 49,000 lines; the window then froze for a quarter of an hour.
        """

        with self._log_lock:
            self._log_queue.append(line)
            if self._log_flush_queued:
                return
            self._log_flush_queued = True
        self.GLib.timeout_add(LOG_FLUSH_MS, self.flush_log_lines)

    def flush_log_lines(self) -> bool:
        """Show the queued lines (GTK thread): one insert, at most LOG_VIEW_LINES lines kept."""

        with self._log_lock:
            lines, self._log_queue = self._log_queue[-LOG_VIEW_LINES:], []
            self._log_flush_queued = False
        if not lines or self.log_view is None or self.stage_label is None:
            return False
        buffer = self.log_view.get_buffer()
        buffer.insert(buffer.get_end_iter(), "\n".join(lines) + "\n")
        extra = buffer.get_line_count() - 1 - LOG_VIEW_LINES   # the text ends with "\n": one empty line
        if extra > 0:
            buffer.delete(buffer.get_start_iter(), buffer.get_iter_at_line(extra))
        self.stage_label.set_text(stage_for_line(lines[-1]))
        self._queue_log_end()
        return False

    def _log_resized(self, _adjustment) -> None:
        """The log's height changed: lines were laid out, or the reader opened the log or resized the window."""

        self._queue_log_end()

    def _queue_log_end(self) -> None:
        """Show the end of the log once GTK has laid out its lines, which it does at a higher priority.

        scroll_to_mark, which 1.3.5 used, does not do it once many lines come at once: GTK scrolls by the
        height it estimates for the lines not yet laid out, and the view stayed at the top of the log.
        """

        if self._log_end_queued:
            return
        self._log_end_queued = True
        self.GLib.idle_add(self._show_log_end, priority=self.GLib.PRIORITY_LOW)

    def _show_log_end(self) -> bool:
        self._log_end_queued = False
        if self.log_view is not None:
            adjustment = self.log_view.get_vadjustment()
            adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        return False

    def pulse(self) -> bool:
        """Pulse while the updater has no numeric progress value."""

        if not self.upgrade_running or self.progress_bar is None:
            return False
        self.progress_bar.pulse()
        return True

    def on_upgrade_done(self, outcome: str, detail: str) -> bool:
        """Replace progress with the result inside the same window (outcome: see upgrade_outcome)."""

        self.flush_log_lines()
        self.upgrade_running = False
        if self.pulse_source_id is not None:
            self.GLib.source_remove(self.pulse_source_id)
            self.pulse_source_id = None
        if self.progress_bar is not None:
            self.progress_bar.set_fraction(1.0)
        if self.stage_label is not None:
            stages = {DONE: _("Updated."), CANCELLED: _("Not updated."), BUSY: _("Another update is running.")}
            self.stage_label.set_text(stages.get(outcome, _("Could not update.")))

        # Only a real failure goes to VNLF; no password or a busy updater only needs another try.
        on_help = None
        if outcome == FAILED and problem.help_available():
            on_help = lambda: problem.ask_for_help(detail, self.update_info)   # noqa: E731
        on_retry = self.start_upgrade if outcome in (CANCELLED, BUSY) else None
        result_page = build_result_page(outcome, detail, self.close, on_help, on_retry, update_info=self.update_info)
        old_result = self.stack.get_child_by_name("result")
        if old_result is not None:
            self.stack.remove(old_result)
        self.stack.add_named(result_page, "result")
        result_page.show_all()
        self.stack.set_visible_child_name("result")
        # The title stays the app's name, "Update Center": the page says how the update went.
        self.window.set_deletable(True)
        return False


def main(argv: list[str] | None = None) -> int:
    """Run the desktop notifier."""

    import argparse

    parser = argparse.ArgumentParser(prog="caramos-ota-notifier")
    parser.add_argument(
        "--autostart",
        action="store_true",
        help="Run from desktop autostart and stay silent when no update is available.",
    )
    parser.add_argument(
        "--auto-update-result",
        action="store_true",
        help="Tell this user how the last automatic update went, once (caramos-ota-auto-update-notify.service).",
    )
    parser.add_argument(
        "--show-auto-update",
        action="store_true",
        help="Show what the last automatic update installed, or why it failed.",
    )
    parser.add_argument(
        AFTER_CHECK,
        action="store_true",
        help="Opened again by the Update Center after its check installed a newer updater: do not check again.",
    )
    args = parser.parse_args(argv)

    if args.auto_update_result:
        # A notification only: GTK starts if the person clicks its button (--show-auto-update).
        return auto_update_ui.notify_result()

    if not has_display():
        return 0

    try:
        Gtk, _gdk, GLib = import_gtk()
    except Exception:
        return 0

    auto_result = None
    if args.show_auto_update:
        auto_result = auto_update_ui.auto_update.read_result()
        if auto_result is not None:
            auto_update_ui.mark(auto_result, "notified", "opened")
    elif args.autostart:
        # A failed automatic update the user has not seen opens its failure page; a finished one has its
        # notification, started on its own.
        auto_result = auto_update_ui.at_login()

    update_info = read_available_update() if args.autostart else None
    no_update_status = read_no_update_status()
    if not args.autostart and auto_result is None:
        update_info, no_update_status = resolve_available_update_now()

    if args.autostart and auto_result is None:
        if update_info is None:
            return 0
        if auto_update_ui.enabled() and auto_update_ui.service_running():
            return 0   # an automatic update is installing it; its notification comes when it is done

    check = not args.autostart and auto_result is None and not args.after_check and check_first()
    controller = UpdateWindowController(Gtk, GLib, update_info, no_update_status, auto_result=auto_result, check=check)
    controller.show()
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

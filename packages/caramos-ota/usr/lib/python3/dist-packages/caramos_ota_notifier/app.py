"""Desktop notifier orchestration for CaramOS OTA."""

from __future__ import annotations

import os
import subprocess
import threading
from typing import Any

from caramos_ota.i18n import _

from . import problem
from .constants import OTA_COMMAND, PKEXEC_COMMAND, UPGRADE_TIMEOUT_SECONDS
from .state import read_available_update, read_no_update_status, resolve_available_update_now
from .ui import (
    build_no_update_page,
    build_progress_page,
    build_result_page,
    build_update_page,
    build_update_window,
    import_gtk,
)

LOG_VIEW_LINES = 2000   # the progress view keeps the end of the output; the result page gets all of it
LOG_FLUSH_MS = 100      # queued output lines reach the progress view in one batch at most this often


def has_display() -> bool:
    """Return True when a graphical display is available."""

    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def stage_for_line(line: str) -> str:
    """Map updater output to a user-friendly progress stage."""

    text = line.lower()
    if "updating package index" in text or "apt-get update" in text:
        return _("Downloading the package list…")
    if "repository:" in text:
        return _("Checking the update repository…")
    if "migration path" in text:
        return _("Preparing migrations…")
    if "run:" in text or "starting migration" in text:
        return _("Running system migrations…")
    if "updated version metadata" in text or "set caramos system version" in text:
        return _("Updating version information…")
    if "update complete" in text or "finished migration" in text:
        return _("Finishing the update…")
    if "error" in text or "failed" in text:
        return _("The update ran into an error.")
    return _("Updating CaramOS…")


def run_upgrade_stream(on_line) -> tuple[bool, str]:
    """Run the OTA upgrade via pkexec and stream output lines to the UI."""

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
            return False, _("The update timed out (10 minutes).")
        return return_code == 0, detail
    except subprocess.TimeoutExpired:
        if process and process.poll() is None:
            process.kill()
        return False, _("The update timed out (10 minutes).")
    except FileNotFoundError:
        return False, _("The pkexec command was not found.")
    except Exception as exc:
        return False, str(exc)


class UpdateWindowController:
    """Drive every OTA state inside one top-level GTK window."""

    def __init__(self, Gtk, GLib, update_info: dict[str, Any] | None, no_update_status: dict[str, str] | None):
        self.Gtk = Gtk
        self.GLib = GLib
        self.update_info = update_info
        self.window, self.stack = build_update_window()
        self.upgrade_running = False
        self.pulse_source_id: int | None = None
        self.thread: threading.Thread | None = None
        # Lines from the updater thread wait here until the GTK thread shows them, see queue_log_line.
        self._log_lock = threading.Lock()
        self._log_queue: list[str] = []
        self._log_flush_queued = False
        self._log_end_queued = False

        self.window.connect("delete-event", self._on_delete_event)

        if update_info is None:
            page = build_no_update_page(no_update_status, self.close)
            self.stack.add_named(page, "no-update")
            self.stack.set_visible_child_name("no-update")
            self.progress_bar = None
            self.stage_label = None
            self.log_view = None
        else:
            info_page = build_update_page(update_info, self.start_upgrade, self.close)
            progress_page, self.progress_bar, self.stage_label, self.log_view = build_progress_page()
            self.log_view.get_vadjustment().connect("changed", self._log_resized)
            self.stack.add_named(info_page, "info")
            self.stack.add_named(progress_page, "progress")
            self.stack.set_visible_child_name("info")

    def show(self) -> None:
        """Show the update center and start its single GTK loop."""

        self.window.show_all()

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
        """Switch to progress and launch the privileged updater once."""

        if self.upgrade_running or self.progress_bar is None:
            return

        self.upgrade_running = True
        self.window.set_deletable(False)
        self.window.set_title(_("CaramOS - Updating…"))
        self.stack.set_visible_child_name("progress")
        self.pulse_source_id = self.GLib.timeout_add(100, self.pulse)

        self.thread = threading.Thread(target=self._do_upgrade, daemon=True)
        self.thread.start()

    def _do_upgrade(self) -> None:
        success, detail = run_upgrade_stream(self.queue_log_line)
        self.GLib.idle_add(self.on_upgrade_done, success, detail)

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

    def on_upgrade_done(self, success: bool, detail: str) -> bool:
        """Replace progress with the result inside the same window."""

        self.flush_log_lines()
        self.upgrade_running = False
        if self.pulse_source_id is not None:
            self.GLib.source_remove(self.pulse_source_id)
            self.pulse_source_id = None
        if self.progress_bar is not None:
            self.progress_bar.set_fraction(1.0)
        if self.stage_label is not None:
            self.stage_label.set_text(_("Update complete.") if success else _("Update failed."))

        on_help = None
        if not success and problem.help_available():
            on_help = lambda: problem.ask_for_help(detail, self.update_info)   # noqa: E731
        result_page = build_result_page(success, detail, self.close, on_help)
        old_result = self.stack.get_child_by_name("result")
        if old_result is not None:
            self.stack.remove(old_result)
        self.stack.add_named(result_page, "result")
        result_page.show_all()
        self.stack.set_visible_child_name("result")
        self.window.set_title(_("CaramOS - Update complete!") if success else _("CaramOS - Update failed"))
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
    args = parser.parse_args(argv)

    if not has_display():
        return 0

    try:
        Gtk, _gdk, GLib = import_gtk()
    except Exception:
        return 0

    update_info = read_available_update() if args.autostart else None
    no_update_status = read_no_update_status()
    if not args.autostart:
        update_info, no_update_status = resolve_available_update_now()

    if args.autostart and update_info is None:
        return 0

    controller = UpdateWindowController(Gtk, GLib, update_info, no_update_status)
    controller.show()
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

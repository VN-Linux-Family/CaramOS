"""Desktop notifier orchestration for CaramOS OTA."""

from __future__ import annotations

import os
import subprocess
import threading
from typing import Any

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


def has_display() -> bool:
    """Return True when a graphical display is available."""

    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def stage_for_line(line: str) -> str:
    """Map updater output to a user-friendly progress stage."""

    text = line.lower()
    if "updating package index" in text or "apt-get update" in text:
        return "Đang tải danh sách gói..."
    if "repository:" in text:
        return "Đang kiểm tra kho cập nhật..."
    if "migration path" in text:
        return "Đang chuẩn bị migration..."
    if "run:" in text or "starting migration" in text:
        return "Đang chạy migration hệ thống..."
    if "updated version metadata" in text or "set caramos system version" in text:
        return "Đang cập nhật thông tin phiên bản..."
    if "update complete" in text or "finished migration" in text:
        return "Đang hoàn tất cập nhật..."
    if "error" in text or "failed" in text:
        return "Đã gặp lỗi khi cập nhật."
    return "Đang cập nhật CaramOS..."


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
            return False, "Quá thời gian chờ cập nhật (10 phút)."
        return return_code == 0, detail
    except subprocess.TimeoutExpired:
        if process and process.poll() is None:
            process.kill()
        return False, "Quá thời gian chờ cập nhật (10 phút)."
    except FileNotFoundError:
        return False, "Không tìm thấy lệnh pkexec."
    except Exception as exc:
        return False, str(exc)


class UpdateWindowController:
    """Drive every OTA state inside one top-level GTK window."""

    def __init__(self, Gtk, GLib, update_info: dict[str, Any] | None, no_update_status: dict[str, str] | None):
        self.Gtk = Gtk
        self.GLib = GLib
        self.window, self.stack = build_update_window()
        self.upgrade_running = False
        self.pulse_source_id: int | None = None
        self.thread: threading.Thread | None = None

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
        self.window.set_title("CaramOS - Đang cập nhật...")
        self.stack.set_visible_child_name("progress")
        self.pulse_source_id = self.GLib.timeout_add(100, self.pulse)

        self.thread = threading.Thread(target=self._do_upgrade, daemon=True)
        self.thread.start()

    def _do_upgrade(self) -> None:
        def on_line(line: str) -> None:
            self.GLib.idle_add(self.append_log_line, line)

        success, detail = run_upgrade_stream(on_line)
        self.GLib.idle_add(self.on_upgrade_done, success, detail)

    def append_log_line(self, line: str) -> bool:
        """Append one updater line from the GTK main thread."""

        if self.log_view is None or self.stage_label is None:
            return False
        buffer = self.log_view.get_buffer()
        end_iter = buffer.get_end_iter()
        buffer.insert(end_iter, line + "\n")
        mark = buffer.create_mark(None, buffer.get_end_iter(), False)
        self.log_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)
        self.stage_label.set_text(stage_for_line(line))
        return False

    def pulse(self) -> bool:
        """Pulse while the updater has no numeric progress value."""

        if not self.upgrade_running or self.progress_bar is None:
            return False
        self.progress_bar.pulse()
        return True

    def on_upgrade_done(self, success: bool, detail: str) -> bool:
        """Replace progress with the result inside the same window."""

        self.upgrade_running = False
        if self.pulse_source_id is not None:
            self.GLib.source_remove(self.pulse_source_id)
            self.pulse_source_id = None
        if self.progress_bar is not None:
            self.progress_bar.set_fraction(1.0)
        if self.stage_label is not None:
            self.stage_label.set_text("Cập nhật hoàn tất." if success else "Cập nhật thất bại.")

        result_page = build_result_page(success, detail, self.close)
        old_result = self.stack.get_child_by_name("result")
        if old_result is not None:
            self.stack.remove(old_result)
        self.stack.add_named(result_page, "result")
        result_page.show_all()
        self.stack.set_visible_child_name("result")
        self.window.set_title("CaramOS - Cập nhật thành công!" if success else "CaramOS - Cập nhật thất bại")
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
        Gtk, _, GLib = import_gtk()
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

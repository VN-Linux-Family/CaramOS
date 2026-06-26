"""Desktop notifier orchestration for CaramOS OTA."""

from __future__ import annotations

import os
import subprocess
import threading

from .constants import OTA_COMMAND, PKEXEC_COMMAND, UPGRADE_TIMEOUT_SECONDS
from .state import read_available_update, read_no_update_status, resolve_available_update_now
from .ui import (
    build_no_update_dialog,
    build_progress_dialog,
    build_result_dialog,
    build_update_dialog,
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

    if update_info is None:
        if args.autostart:
            return 0
        dialog = build_no_update_dialog(no_update_status)
        dialog.run()
        dialog.destroy()
        return 0

    dialog = build_update_dialog(update_info)
    response = dialog.run()
    dialog.destroy()

    if response != Gtk.ResponseType.ACCEPT:
        return 0

    progress_dialog, progress_bar, stage_label, log_view = build_progress_dialog()
    pulse_running = True

    def append_log_line(line: str) -> None:
        buffer = log_view.get_buffer()
        end_iter = buffer.get_end_iter()
        buffer.insert(end_iter, line + "\n")
        mark = buffer.create_mark(None, buffer.get_end_iter(), False)
        log_view.scroll_to_mark(mark, 0.0, True, 0.0, 1.0)
        stage_label.set_text(stage_for_line(line))

    def pulse() -> bool:
        if pulse_running:
            progress_bar.pulse()
            return True
        return False

    GLib.timeout_add(100, pulse)
    upgrade_result: list[object] = [False, ""]

    def do_upgrade() -> None:
        def on_line(line: str) -> None:
            GLib.idle_add(append_log_line, line)

        success, detail = run_upgrade_stream(on_line)
        upgrade_result[0] = success
        upgrade_result[1] = detail
        GLib.idle_add(on_upgrade_done)

    def on_upgrade_done() -> None:
        nonlocal pulse_running
        pulse_running = False
        progress_bar.set_fraction(1.0)
        stage_label.set_text("Cập nhật hoàn tất." if upgrade_result[0] else "Cập nhật thất bại.")
        progress_dialog.destroy()

        result_dialog = build_result_dialog(bool(upgrade_result[0]), str(upgrade_result[1]))
        result_dialog.run()
        result_dialog.destroy()
        Gtk.main_quit()

    thread = threading.Thread(target=do_upgrade, daemon=True)
    thread.start()
    Gtk.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

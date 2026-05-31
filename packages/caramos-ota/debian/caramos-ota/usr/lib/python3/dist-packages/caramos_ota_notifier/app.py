"""Desktop notifier orchestration for CaramOS OTA."""

from __future__ import annotations

import os
import subprocess
import threading

from .constants import OTA_COMMAND, PKEXEC_COMMAND, UPGRADE_TIMEOUT_SECONDS
from .state import read_available_update
from .ui import build_progress_dialog, build_result_dialog, build_update_dialog, import_gtk


def has_display() -> bool:
    """Return True when a graphical display is available."""

    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def run_upgrade() -> tuple[bool, str]:
    """Run the OTA upgrade via pkexec. Returns (success, detail_msg)."""

    try:
        result = subprocess.run(
            [PKEXEC_COMMAND, OTA_COMMAND, "--upgrade", "--yes"],
            capture_output=True,
            text=True,
            timeout=UPGRADE_TIMEOUT_SECONDS,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        stderr = result.stderr.strip() or result.stdout.strip()
        return False, stderr
    except subprocess.TimeoutExpired:
        return False, "Quá thời gian chờ cập nhật (10 phút)."
    except FileNotFoundError:
        return False, "Không tìm thấy lệnh pkexec."
    except Exception as exc:
        return False, str(exc)


def main() -> int:
    """Run the desktop notifier."""

    if not has_display():
        return 0

    update_info = read_available_update()
    if update_info is None:
        return 0

    try:
        Gtk, _, GLib = import_gtk()
    except Exception:
        return 0

    dialog = build_update_dialog(update_info)
    response = dialog.run()
    dialog.destroy()

    if response != Gtk.ResponseType.ACCEPT:
        return 0

    progress_dialog, progress_bar = build_progress_dialog()
    pulse_running = True

    def pulse() -> bool:
        if pulse_running:
            progress_bar.pulse()
            return True
        return False

    GLib.timeout_add(100, pulse)
    upgrade_result: list[object] = [False, ""]

    def do_upgrade() -> None:
        success, detail = run_upgrade()
        upgrade_result[0] = success
        upgrade_result[1] = detail
        GLib.idle_add(on_upgrade_done)

    def on_upgrade_done() -> None:
        nonlocal pulse_running
        pulse_running = False
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

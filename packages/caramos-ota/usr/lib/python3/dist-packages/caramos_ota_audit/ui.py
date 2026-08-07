"""One-click GTK UI for CaramOS audit collection."""

from __future__ import annotations

import subprocess
import threading
from pathlib import Path

from caramos_ota_notifier.ui import apply_theme, import_gtk, set_caramos_icon

from .cli import AuditReport, create_audit_bundle

DEFAULT_OUTPUT_DIR = str(Path.home() / "Desktop")
AREAS = (
    ("Tự động nhận diện", "automatic"),
    ("Wi-Fi / Mạng", "network"),
    ("Bluetooth", "bluetooth"),
    ("Âm thanh", "audio"),
    ("Màn hình", "display"),
    ("Nguồn / Pin", "power"),
    ("Control Center", "control-center"),
    ("Cập nhật OTA", "ota"),
    ("Khác", "other"),
)


def _open_folder(path: Path) -> None:
    subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_gui(*, summary: str = "", steps: str = "", expected: str = "", actual: str = "", area: str = "", output_dir: str = DEFAULT_OUTPUT_DIR) -> int:
    """Show one-click collector; optional note only helps identify symptom."""

    Gtk, Gdk, GLib = import_gtk()
    apply_theme(Gtk, Gdk)

    dialog = Gtk.Dialog(title="CaramOS Audit")
    dialog.set_default_size(620, 430)
    dialog.set_position(Gtk.WindowPosition.CENTER)
    set_caramos_icon(dialog, Gtk)

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    outer.set_margin_top(16)
    outer.set_margin_bottom(16)
    outer.set_margin_start(18)
    outer.set_margin_end(18)
    dialog.get_content_area().pack_start(outer, True, True, 0)

    hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    hero.get_style_context().add_class("hero")
    title = Gtk.Label()
    title.set_markup("<span foreground='#ffffff' size='large' weight='bold'>Thu thập báo cáo lỗi</span>")
    title.set_xalign(0)
    hero.pack_start(title, False, False, 0)
    intro = Gtk.Label(label="Sau khi lỗi xảy ra, bấm nút bên dưới. CaramOS tự lấy trạng thái và log cần thiết.")
    intro.set_xalign(0)
    intro.set_line_wrap(True)
    hero.pack_start(intro, False, False, 0)
    outer.pack_start(hero, False, False, 0)

    privacy = Gtk.Label(label="Không cần nhập các bước. Không upload. Không lấy mật khẩu, cookie, clipboard, SSH/GPG hoặc lịch sử trình duyệt.")
    privacy.set_xalign(0)
    privacy.set_line_wrap(True)
    privacy.get_style_context().add_class("warning")
    outer.pack_start(privacy, False, False, 0)

    area_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    area_label = Gtk.Label(label="Lỗi liên quan:")
    area_label.set_xalign(0)
    area_box.pack_start(area_label, False, False, 0)
    area_combo = Gtk.ComboBoxText()
    for label, value in AREAS:
        area_combo.append(value, label)
    area_combo.set_active_id(area if any(value == area for _, value in AREAS) else "automatic")
    area_box.pack_start(area_combo, True, True, 0)
    outer.pack_start(area_box, False, False, 0)

    note = Gtk.Entry()
    note.set_placeholder_text("Ghi chú ngắn nếu muốn, ví dụ: bấm kết nối Wi-Fi nhưng không vào được")
    note.set_text(summary)
    outer.pack_start(note, False, False, 0)

    status = Gtk.Label(label="Sẵn sàng. Hãy bấm Thu thập ngay sau khi lỗi xảy ra.")
    status.set_xalign(0)
    status.set_line_wrap(True)
    outer.pack_start(status, False, False, 0)

    progress = Gtk.ProgressBar()
    progress.set_show_text(True)
    progress.set_text("Chưa thu thập")
    outer.pack_start(progress, False, False, 0)

    buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
    close_button = Gtk.Button(label="Đóng")
    collect_button = Gtk.Button(label="Thu thập ngay")
    collect_button.get_style_context().add_class("suggested-action")
    buttons.pack_end(close_button, False, False, 0)
    buttons.pack_end(collect_button, False, False, 0)
    outer.pack_start(buttons, False, False, 0)

    def finish(result) -> bool:
        progress.set_fraction(1.0)
        progress.set_text("Đã xong")
        status.set_text(f"Đã tạo: {result.bundle_path}")
        collect_button.set_sensitive(True)
        open_button = Gtk.Button(label="Mở thư mục chứa file")
        open_button.connect("clicked", lambda _: _open_folder(result.output_dir))
        buttons.pack_start(open_button, False, False, 0)
        open_button.show()
        return False

    def fail(message: str) -> bool:
        progress.set_fraction(0.0)
        progress.set_text("Lỗi")
        status.set_text(f"Không tạo được báo cáo: {message}")
        collect_button.set_sensitive(True)
        return False

    def start(_: object) -> None:
        selected_area = area_combo.get_active_id() or "automatic"
        user_note = note.get_text().strip()
        report = AuditReport(
            summary=user_note or "Báo cáo tự động sau khi lỗi xảy ra",
            steps=["Người dùng tái hiện lỗi rồi mở CaramOS Audit"],
            expected="Tính năng hoạt động bình thường",
            actual=user_note or "Xem trạng thái và log được thu thập tự động",
            area=selected_area,
            created_at=None,
        )
        target_dir = output_dir or DEFAULT_OUTPUT_DIR
        collect_button.set_sensitive(False)
        progress.set_text("Đang thu thập")
        progress.pulse()
        status.set_text("Đang lấy trạng thái phần cứng, mạng, âm thanh và log gần nhất...")

        def progress_callback(message: str) -> None:
            GLib.idle_add(status.set_text, str(message))
            GLib.idle_add(progress.pulse)

        def worker() -> None:
            try:
                result = create_audit_bundle(report, target_dir, progress_callback)
                GLib.idle_add(finish, result)
            except Exception as exc:  # pragma: no cover - GUI boundary
                GLib.idle_add(fail, str(exc))

        threading.Thread(target=worker, daemon=True).start()

    collect_button.connect("clicked", start)
    close_button.connect("clicked", lambda _: dialog.response(Gtk.ResponseType.CLOSE))
    dialog.show_all()
    dialog.run()
    dialog.destroy()
    return 0

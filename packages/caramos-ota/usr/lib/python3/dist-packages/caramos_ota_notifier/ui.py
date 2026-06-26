"""GTK dialog builders for the CaramOS OTA desktop notifier."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from .state import format_value, normalize_package

CARAMOS_ICON = Path("/usr/share/pixmaps/caramos-logo.png")


def import_gtk():
    """Import GTK3 lazily so non-GUI sessions can exit quietly."""

    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    return Gtk, Gdk, GLib


def set_caramos_icon(dialog, Gtk) -> None:
    """Use the CaramOS brand icon for OTA dialogs when available."""

    if CARAMOS_ICON.exists():
        dialog.set_icon_from_file(str(CARAMOS_ICON))
    else:
        dialog.set_icon_name("caramos-logo")


def apply_theme(Gtk, Gdk) -> None:
    """Apply CaramOS/VNLF GTK styling."""

    css = b"""
    * {
      font-family: "Be Vietnam Pro", "Inter", "Noto Sans", sans-serif;
    }
    dialog, box {
      background: #f7f3e9;
      color: #1f2a22;
    }
    .hero {
      background: linear-gradient(135deg, #1f4f32, #2f7048);
      border-radius: 18px;
      color: #fffaf0;
      padding: 16px;
      box-shadow: 0 18px 48px rgba(31, 79, 50, 0.18);
    }
    .card {
      background: #fffdf7;
      border: 1px solid #e3dfd1;
      border-radius: 14px;
      padding: 10px;
      box-shadow: 0 10px 26px rgba(31, 79, 50, 0.06);
    }
    .muted { color: #657064; }
    .version-old { color: #657064; font-size: 18px; font-weight: 800; }
    .version-new { color: #2f7048; font-size: 18px; font-weight: 900; }
    .warning {
      background: #fff8df;
      border: 1px solid #ead5a3;
      border-radius: 12px;
      color: #7a5514;
      padding: 8px;
      font-weight: 700;
    }
    textview.notes-view,
    textview.notes-view text {
      background: #fffdf7;
      color: #1f2a22;
    }
    button {
      border-radius: 12px;
      padding: 8px 16px;
      font-weight: 800;
    }
    """
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def add_info_row(Gtk, grid, row: int, label: str, value: object) -> None:
    """Add a label/value row to a GTK grid."""

    key = Gtk.Label()
    key.set_markup(f"<span foreground='#6b7280'>{label}</span>")
    key.set_xalign(0)
    key.set_valign(Gtk.Align.START)
    grid.attach(key, 0, row, 1, 1)

    val = Gtk.Label()
    val.set_text(format_value(value))
    val.set_xalign(0)
    val.set_selectable(True)
    val.set_line_wrap(True)
    grid.attach(val, 1, row, 1, 1)


def build_update_dialog(update_info: dict[str, Any]):
    """Build and show the GTK3 update dialog."""

    Gtk, Gdk, _ = import_gtk()
    apply_theme(Gtk, Gdk)

    current_version = format_value(update_info.get("current_version") or update_info.get("from_version"))
    new_release = format_value(update_info.get("release") or update_info.get("to_version"))
    channel = format_value(update_info.get("channel"), "stable")
    severity = format_value(update_info.get("severity"), "normal")
    size = format_value(update_info.get("size"), "Chưa rõ")
    title = format_value(update_info.get("title"), "CaramOS có bản cập nhật mới")
    summary = format_value(
        update_info.get("summary"),
        "Bản cập nhật này sẽ chạy migration CaramOS cần thiết cho phiên bản mới.",
    )
    packages = [normalize_package(pkg) for pkg in update_info.get("packages", [])]
    release_notes = update_info.get("release_notes_vi") or update_info.get("release_notes") or []
    visible_notes = release_notes
    hidden_notes = 0

    dialog = Gtk.Dialog()
    dialog.set_title("CaramOS - Trung tâm cập nhật")
    screen = Gdk.Screen.get_default()
    screen_width = screen.get_width() if screen is not None else 1024
    screen_height = screen.get_height() if screen is not None else 768
    dialog_width = min(760, max(620, int(screen_width * 0.74)))
    dialog_height = min(max(520, int(screen_height * 0.72)), screen_height - 140)
    dialog.set_default_size(dialog_width, dialog_height)
    dialog.set_size_request(620, 500)
    dialog.set_resizable(True)
    dialog.set_position(Gtk.WindowPosition.CENTER)
    set_caramos_icon(dialog, Gtk)

    content = dialog.get_content_area()
    content.set_spacing(0)
    content.set_margin_top(0)
    content.set_margin_bottom(0)
    content.set_margin_start(0)
    content.set_margin_end(0)

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    outer.set_margin_top(12)
    outer.set_margin_bottom(10)
    outer.set_margin_start(14)
    outer.set_margin_end(14)
    content.pack_start(outer, True, True, 0)

    hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    hero.get_style_context().add_class("hero")
    outer.pack_start(hero, False, False, 0)

    eyebrow = Gtk.Label()
    eyebrow.set_markup("<span foreground='#fffaf0' weight='bold'>CARAMOS OTA • VIETNAM LINUX FAMILY</span>")
    eyebrow.set_xalign(0)
    hero.pack_start(eyebrow, False, False, 0)

    heading = Gtk.Label()
    heading.set_markup(f"<span foreground='#ffffff' size='large' weight='bold'>{html.escape(title)}</span>")
    heading.set_xalign(0)
    heading.set_line_wrap(True)
    hero.pack_start(heading, False, False, 0)

    subtitle = Gtk.Label()
    subtitle.set_markup(f"<span foreground='#fffaf0'>{html.escape(summary)}</span>")
    subtitle.set_xalign(0)
    subtitle.set_line_wrap(True)
    hero.pack_start(subtitle, False, False, 0)

    version_grid = Gtk.Grid()
    version_grid.set_column_spacing(12)
    version_grid.set_row_spacing(8)
    outer.pack_start(version_grid, False, False, 0)

    old_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    old_card.get_style_context().add_class("card")
    old_lbl = Gtk.Label(label="Phiên bản hiện tại")
    old_lbl.get_style_context().add_class("muted")
    old_lbl.set_xalign(0)
    old_val = Gtk.Label(label=current_version)
    old_val.get_style_context().add_class("version-old")
    old_val.set_xalign(0)
    old_card.pack_start(old_lbl, False, False, 0)
    old_card.pack_start(old_val, False, False, 0)
    version_grid.attach(old_card, 0, 0, 1, 1)

    new_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    new_card.get_style_context().add_class("card")
    new_lbl = Gtk.Label(label="Phiên bản khả dụng")
    new_lbl.get_style_context().add_class("muted")
    new_lbl.set_xalign(0)
    new_val = Gtk.Label(label=new_release)
    new_val.get_style_context().add_class("version-new")
    new_val.set_xalign(0)
    new_card.pack_start(new_lbl, False, False, 0)
    new_card.pack_start(new_val, False, False, 0)
    version_grid.attach(new_card, 1, 0, 1, 1)

    meta_card = Gtk.Grid()
    meta_card.get_style_context().add_class("card")
    meta_card.set_column_spacing(16)
    meta_card.set_row_spacing(7)
    outer.pack_start(meta_card, False, False, 0)
    add_info_row(Gtk, meta_card, 0, "Kênh cập nhật", channel)
    add_info_row(Gtk, meta_card, 1, "Mức độ", severity)
    add_info_row(Gtk, meta_card, 2, "Dung lượng", size)

    body = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
    outer.pack_start(body, True, True, 0)

    notes_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    notes_panel.get_style_context().add_class("card")
    body.pack1(notes_panel, resize=True, shrink=False)

    notes_title = Gtk.Label()
    notes_title.set_markup("<span weight='bold'>Nội dung cập nhật</span>")
    notes_title.set_xalign(0)
    notes_panel.pack_start(notes_title, False, False, 0)

    notes_scroll = Gtk.ScrolledWindow()
    notes_scroll.set_min_content_height(95)
    notes_scroll.set_max_content_height(170)
    notes_panel.pack_start(notes_scroll, True, True, 0)

    if visible_notes:
        notes_text = "\n\n".join(f"• {format_value(note)}" for note in visible_notes)
        if hidden_notes:
            notes_text += f"\n\n• Và {hidden_notes} thay đổi khác..."
    else:
        notes_text = "• Chạy migration CaramOS theo manifest OTA."

    notes_view = Gtk.TextView()
    notes_view.get_style_context().add_class("notes-view")
    notes_view.set_editable(False)
    notes_view.set_cursor_visible(False)
    notes_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    notes_view.set_left_margin(0)
    notes_view.set_right_margin(6)
    notes_view.set_top_margin(0)
    notes_view.set_bottom_margin(0)
    notes_view.get_buffer().set_text(notes_text)
    notes_scroll.add(notes_view)

    pkg_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    pkg_panel.get_style_context().add_class("card")
    body.pack2(pkg_panel, resize=True, shrink=False)

    pkg_title = Gtk.Label()
    pkg_title.set_markup(f"<span weight='bold'>Migration sẽ chạy ({len(packages)})</span>")
    pkg_title.set_xalign(0)
    pkg_panel.pack_start(pkg_title, False, False, 0)

    scroll = Gtk.ScrolledWindow()
    scroll.set_min_content_height(80)
    scroll.set_max_content_height(150)
    pkg_panel.pack_start(scroll, True, True, 0)

    pkg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    for pkg in packages:
        item = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        name_lbl = Gtk.Label()
        badge = "bắt buộc" if pkg["required"] is True else "tùy chọn" if pkg["required"] is False else "gói"
        name_lbl.set_markup(
            f"<span weight='bold'>{html.escape(str(pkg['name']))}</span>  "
            f"<span foreground='#657064'>({html.escape(badge)})</span>"
        )
        name_lbl.set_xalign(0)
        item.pack_start(name_lbl, False, False, 0)

        ver_lbl = Gtk.Label()
        ver_lbl.set_text(f"{pkg['current']}  →  {pkg['available']}")
        ver_lbl.set_xalign(0)
        ver_lbl.set_selectable(True)
        item.pack_start(ver_lbl, False, False, 0)

        if pkg["description"]:
            item.set_tooltip_text(str(pkg["description"]))

        pkg_box.pack_start(item, False, False, 0)

    scroll.add(pkg_box)

    warning = Gtk.Label()
    warning.get_style_context().add_class("warning")
    warning.set_text(
        "Khuyến nghị: cắm sạc, giữ kết nối mạng ổn định và không tắt máy trong lúc cập nhật. "
        "Bạn có thể đóng cửa sổ này và cập nhật sau."
    )
    warning.set_xalign(0)
    warning.set_line_wrap(True)
    outer.pack_start(warning, False, False, 0)

    dialog.add_button("Để sau", Gtk.ResponseType.CLOSE)
    dialog.add_button("Cập nhật ngay", Gtk.ResponseType.ACCEPT)

    dialog.show_all()
    return dialog


def _screen_dialog_size(Gdk, *, width_ratio: float = 0.78, height_ratio: float = 0.80) -> tuple[int, int]:
    """Return a premium responsive dialog size bounded by the current screen."""

    screen = Gdk.Screen.get_default()
    screen_width = screen.get_width() if screen is not None else 1024
    screen_height = screen.get_height() if screen is not None else 768
    width = min(760, max(640, int(screen_width * width_ratio)))
    height = min(max(560, int(screen_height * height_ratio)), screen_height - 48)
    return width, height


def build_progress_dialog():
    """Build the progress dialog shown during update."""

    Gtk, Gdk, _ = import_gtk()
    apply_theme(Gtk, Gdk)
    dialog = Gtk.Dialog()
    dialog.set_title("CaramOS - Đang cập nhật...")
    dialog.set_default_size(*_screen_dialog_size(Gdk))
    dialog.set_resizable(True)
    dialog.set_position(Gtk.WindowPosition.CENTER)
    dialog.set_deletable(False)
    set_caramos_icon(dialog, Gtk)

    content = dialog.get_content_area()
    content.set_spacing(0)
    content.set_margin_top(0)
    content.set_margin_bottom(0)
    content.set_margin_start(0)
    content.set_margin_end(0)

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    outer.set_margin_top(12)
    outer.set_margin_bottom(10)
    outer.set_margin_start(14)
    outer.set_margin_end(14)
    content.pack_start(outer, True, True, 0)

    hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    hero.get_style_context().add_class("hero")
    outer.pack_start(hero, False, False, 0)

    eyebrow = Gtk.Label()
    eyebrow.set_markup("<span foreground='#fffaf0' weight='bold'>CARAMOS OTA • ĐANG CẬP NHẬT</span>")
    eyebrow.set_xalign(0)
    hero.pack_start(eyebrow, False, False, 0)

    header = Gtk.Label()
    header.set_markup("<span foreground='#ffffff' size='large' weight='bold'>Đang cập nhật CaramOS...</span>")
    header.set_xalign(0)
    hero.pack_start(header, False, False, 0)

    stage_lbl = Gtk.Label(label="Đang chuẩn bị cập nhật...")
    stage_lbl.set_xalign(0)
    stage_lbl.set_line_wrap(True)
    hero.pack_start(stage_lbl, False, False, 0)

    progress = Gtk.ProgressBar()
    progress.set_pulse_step(0.05)
    outer.pack_start(progress, False, False, 0)

    log_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    log_card.get_style_context().add_class("card")
    outer.pack_start(log_card, True, True, 0)

    log_title = Gtk.Label()
    log_title.set_markup("<span weight='bold'>Tiến trình cập nhật</span>")
    log_title.set_xalign(0)
    log_card.pack_start(log_title, False, False, 0)

    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroll.set_min_content_height(260)
    log_card.pack_start(scroll, True, True, 0)

    log_view = Gtk.TextView()
    log_view.set_editable(False)
    log_view.set_cursor_visible(False)
    log_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    scroll.add(log_view)

    warning = Gtk.Label()
    warning.get_style_context().add_class("warning")
    warning.set_text("Vui lòng không tắt máy hoặc đóng tiến trình cập nhật.")
    warning.set_xalign(0)
    warning.set_line_wrap(True)
    outer.pack_start(warning, False, False, 0)

    dialog.show_all()
    return dialog, progress, stage_lbl, log_view


def build_result_dialog(success: bool, detail: str = ""):
    """Build the result dialog after update."""

    Gtk, Gdk, _ = import_gtk()
    apply_theme(Gtk, Gdk)
    dialog = Gtk.Dialog()
    dialog.set_default_size(*_screen_dialog_size(Gdk))
    dialog.set_resizable(True)
    dialog.set_position(Gtk.WindowPosition.CENTER)
    set_caramos_icon(dialog, Gtk)

    content = dialog.get_content_area()
    content.set_spacing(0)
    content.set_margin_top(0)
    content.set_margin_bottom(0)
    content.set_margin_start(0)
    content.set_margin_end(0)

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    outer.set_margin_top(12)
    outer.set_margin_bottom(10)
    outer.set_margin_start(14)
    outer.set_margin_end(14)
    content.pack_start(outer, True, True, 0)

    hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    hero.get_style_context().add_class("hero")
    outer.pack_start(hero, False, False, 0)

    if success:
        dialog.set_title("CaramOS - Cập nhật thành công!")
        title = "Cập nhật thành công!"
        summary = "CaramOS đã được cập nhật thành công."
    else:
        dialog.set_title("CaramOS - Cập nhật thất bại")
        title = "Cập nhật thất bại"
        summary = "Đã xảy ra lỗi khi cập nhật. Vui lòng thử lại hoặc chạy sudo caramos-ota --repair."

    header = Gtk.Label()
    header.set_markup(f"<span foreground='#ffffff' size='large' weight='bold'>{html.escape(title)}</span>")
    header.set_xalign(0)
    hero.pack_start(header, False, False, 0)

    summary_lbl = Gtk.Label(label=summary)
    summary_lbl.set_xalign(0)
    summary_lbl.set_line_wrap(True)
    hero.pack_start(summary_lbl, False, False, 0)

    detail_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    detail_card.get_style_context().add_class("card")
    outer.pack_start(detail_card, True, True, 0)

    detail_title = Gtk.Label()
    detail_title.set_markup("<span weight='bold'>Chi tiết cập nhật</span>")
    detail_title.set_xalign(0)
    detail_card.pack_start(detail_title, False, False, 0)

    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroll.set_min_content_height(340)
    detail_card.pack_start(scroll, True, True, 0)

    detail_view = Gtk.TextView()
    detail_view.set_editable(False)
    detail_view.set_cursor_visible(False)
    detail_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    detail_view.get_buffer().set_text(detail or summary)
    scroll.add(detail_view)

    dialog.add_button("Đóng", Gtk.ResponseType.CLOSE)
    dialog.show_all()
    return dialog


def build_no_update_dialog(status: dict[str, str] | None = None):
    """Build a visible dialog for manual launches when no update is available."""

    Gtk, Gdk, _ = import_gtk()
    apply_theme(Gtk, Gdk)
    status = status or {}
    current_version = format_value(status.get("current_version"))
    latest_version = format_value(status.get("latest_version"))
    channel = format_value(status.get("channel"), "stable")

    dialog = Gtk.Dialog()
    dialog.set_title("CaramOS - Trung tâm cập nhật")
    dialog.set_default_size(*_screen_dialog_size(Gdk))
    dialog.set_resizable(True)
    dialog.set_position(Gtk.WindowPosition.CENTER)
    set_caramos_icon(dialog, Gtk)

    content = dialog.get_content_area()
    content.set_spacing(0)
    content.set_margin_top(0)
    content.set_margin_bottom(0)
    content.set_margin_start(0)
    content.set_margin_end(0)

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    outer.set_margin_top(12)
    outer.set_margin_bottom(10)
    outer.set_margin_start(14)
    outer.set_margin_end(14)
    content.pack_start(outer, True, True, 0)

    hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    hero.get_style_context().add_class("hero")
    outer.pack_start(hero, False, False, 0)

    eyebrow = Gtk.Label()
    eyebrow.set_markup("<span foreground='#fffaf0' weight='bold'>CARAMOS OTA • VIETNAM LINUX FAMILY</span>")
    eyebrow.set_xalign(0)
    hero.pack_start(eyebrow, False, False, 0)

    header = Gtk.Label()
    header.set_markup("<span foreground='#ffffff' size='large' weight='bold'>CaramOS đã được cập nhật</span>")
    header.set_xalign(0)
    hero.pack_start(header, False, False, 0)

    summary = Gtk.Label(label="Hệ thống đang dùng phiên bản mới nhất trong kênh cập nhật stable.")
    summary.set_xalign(0)
    summary.set_line_wrap(True)
    hero.pack_start(summary, False, False, 0)

    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    card.get_style_context().add_class("card")
    outer.pack_start(card, True, True, 0)

    title = Gtk.Label()
    title.set_markup("<span weight='bold'>Trạng thái cập nhật</span>")
    title.set_xalign(0)
    card.pack_start(title, False, False, 0)

    version_grid = Gtk.Grid()
    version_grid.set_column_spacing(12)
    version_grid.set_row_spacing(8)
    card.pack_start(version_grid, False, False, 0)
    add_info_row(Gtk, version_grid, 0, "Phiên bản hiện tại", current_version)
    add_info_row(Gtk, version_grid, 1, "Phiên bản mới nhất", latest_version)
    add_info_row(Gtk, version_grid, 2, "Kênh cập nhật", channel)

    body = Gtk.Label()
    body.set_xalign(0)
    body.set_line_wrap(True)
    body.set_text(
        "Không có migration mới trong danh sách cập nhật.\n\n"
        "Bạn có thể đóng cửa sổ này. CaramOS OTA sẽ tiếp tục kiểm tra định kỳ bằng systemd timer."
    )
    card.pack_start(body, False, False, 0)

    dialog.add_button("Đóng", Gtk.ResponseType.CLOSE)
    dialog.show_all()
    return dialog

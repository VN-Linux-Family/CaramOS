"""GTK dialog builders for the CaramOS OTA desktop notifier."""

from __future__ import annotations

import html
from typing import Any

from .state import format_value, normalize_package


def import_gtk():
    """Import GTK3 lazily so non-GUI sessions can exit quietly."""

    import gi

    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, GLib, Gtk

    return Gtk, Gdk, GLib


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
        "Bản cập nhật này sẽ cài các gói hệ thống cần thiết cho CaramOS.",
    )
    packages = [normalize_package(pkg) for pkg in update_info.get("packages", [])]
    release_notes = update_info.get("release_notes_vi") or update_info.get("release_notes") or []
    visible_notes = release_notes[:3]
    hidden_notes = max(0, len(release_notes) - len(visible_notes))

    dialog = Gtk.Dialog()
    dialog.set_title("CaramOS - Trung tâm cập nhật")
    dialog.set_default_size(640, 520)
    dialog.set_resizable(True)
    dialog.set_position(Gtk.WindowPosition.CENTER)
    dialog.set_icon_name("system-software-update")

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

    notes_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    notes_box.get_style_context().add_class("card")
    body.pack1(notes_box, resize=True, shrink=False)

    notes_title = Gtk.Label()
    notes_title.set_markup("<span weight='bold'>Nội dung cập nhật</span>")
    notes_title.set_xalign(0)
    notes_box.pack_start(notes_title, False, False, 0)

    if visible_notes:
        for note in visible_notes:
            note_lbl = Gtk.Label()
            note_lbl.set_text(f"• {format_value(note)}")
            note_lbl.set_xalign(0)
            note_lbl.set_line_wrap(True)
            notes_box.pack_start(note_lbl, False, False, 0)
        if hidden_notes:
            more_lbl = Gtk.Label()
            more_lbl.set_text(f"• Và {hidden_notes} thay đổi khác...")
            more_lbl.set_xalign(0)
            more_lbl.get_style_context().add_class("muted")
            notes_box.pack_start(more_lbl, False, False, 0)
    else:
        note_lbl = Gtk.Label()
        note_lbl.set_text("• Cập nhật các thành phần hệ thống theo manifest OTA.")
        note_lbl.set_xalign(0)
        note_lbl.set_line_wrap(True)
        notes_box.pack_start(note_lbl, False, False, 0)

    pkg_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    pkg_panel.get_style_context().add_class("card")
    body.pack2(pkg_panel, resize=True, shrink=False)

    pkg_title = Gtk.Label()
    pkg_title.set_markup(f"<span weight='bold'>Gói sẽ cập nhật ({len(packages)})</span>")
    pkg_title.set_xalign(0)
    pkg_panel.pack_start(pkg_title, False, False, 0)

    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_min_content_height(150)
    scroll.set_max_content_height(190)
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


def build_progress_dialog():
    """Build the progress dialog shown during update."""

    Gtk, _, _ = import_gtk()
    dialog = Gtk.Dialog()
    dialog.set_title("CaramOS - Đang cập nhật...")
    dialog.set_default_size(400, 150)
    dialog.set_resizable(False)
    dialog.set_position(Gtk.WindowPosition.CENTER)
    dialog.set_deletable(False)
    dialog.set_icon_name("system-software-update")

    content = dialog.get_content_area()
    content.set_spacing(15)
    content.set_margin_top(20)
    content.set_margin_bottom(20)
    content.set_margin_start(30)
    content.set_margin_end(30)

    header = Gtk.Label()
    header.set_markup("<span size='large' weight='bold'>🔄 Đang cập nhật CaramOS...</span>")
    content.pack_start(header, False, False, 0)

    progress = Gtk.ProgressBar()
    progress.set_pulse_step(0.05)
    content.pack_start(progress, False, False, 5)

    warn_lbl = Gtk.Label()
    warn_lbl.set_text("Vui lòng không tắt máy hoặc đóng tiến trình cập nhật.")
    warn_lbl.set_line_wrap(True)
    content.pack_start(warn_lbl, False, False, 0)

    dialog.show_all()
    return dialog, progress


def build_result_dialog(success: bool, detail: str = ""):
    """Build the result dialog after update."""

    Gtk, _, _ = import_gtk()
    dialog = Gtk.Dialog()
    dialog.set_default_size(400, 180)
    dialog.set_resizable(False)
    dialog.set_position(Gtk.WindowPosition.CENTER)
    dialog.set_icon_name("system-software-update")

    content = dialog.get_content_area()
    content.set_spacing(10)
    content.set_margin_top(20)
    content.set_margin_bottom(15)
    content.set_margin_start(25)
    content.set_margin_end(25)

    if success:
        dialog.set_title("CaramOS - Cập nhật thành công!")
        header = Gtk.Label()
        header.set_markup("<span size='large' weight='bold'>✅ Cập nhật thành công!</span>")
        content.pack_start(header, False, False, 5)

        msg = Gtk.Label()
        msg.set_text(detail or "Đã cập nhật CaramOS thành công.")
        msg.set_line_wrap(True)
        msg.set_xalign(0)
        content.pack_start(msg, False, False, 5)
    else:
        dialog.set_title("CaramOS - Cập nhật thất bại")
        header = Gtk.Label()
        header.set_markup("<span size='large' weight='bold'>❌ Cập nhật thất bại</span>")
        content.pack_start(header, False, False, 5)

        msg = Gtk.Label()
        msg.set_text("Đã xảy ra lỗi khi cập nhật.")
        msg.set_xalign(0)
        content.pack_start(msg, False, False, 2)

        repair = Gtk.Label()
        repair.set_text("Vui lòng thử lại hoặc chạy:\n  sudo caramos-ota --repair")
        repair.set_xalign(0)
        content.pack_start(repair, False, False, 2)

        if detail:
            detail_lbl = Gtk.Label()
            detail_lbl.set_text(detail)
            detail_lbl.set_xalign(0)
            detail_lbl.set_line_wrap(True)
            content.pack_start(detail_lbl, False, False, 2)

    dialog.add_button("Đóng", Gtk.ResponseType.CLOSE)
    dialog.show_all()
    return dialog

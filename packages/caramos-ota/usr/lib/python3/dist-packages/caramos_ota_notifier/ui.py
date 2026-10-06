"""GTK dialog builders for the CaramOS OTA desktop notifier."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from caramos_ota.i18n import _, localized, ngettext

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


def severity_label(severity: str) -> str:
    """Translate the manifest severity token (feature/important/normal/none)."""

    labels = {
        "feature": _("New features"),
        "important": _("Important"),
        "normal": _("Normal"),
        "none": _("None"),
    }
    return labels.get(severity, severity)


def add_info_row(Gtk, grid, row: int, label: str, value: object) -> None:
    """Add a label/value row to a GTK grid."""

    key = Gtk.Label()
    key.set_markup(f"<span foreground='#6b7280'>{html.escape(label)}</span>")
    key.set_xalign(0)
    key.set_valign(Gtk.Align.START)
    grid.attach(key, 0, row, 1, 1)

    val = Gtk.Label()
    val.set_text(format_value(value))
    val.set_xalign(0)
    val.set_selectable(True)
    val.set_line_wrap(True)
    grid.attach(val, 1, row, 1, 1)


def _add_action_buttons(Gtk, outer, buttons: list[tuple[str, Any]]) -> None:
    """Add right-aligned page actions."""

    actions = Gtk.ButtonBox(orientation=Gtk.Orientation.HORIZONTAL)
    actions.set_layout(Gtk.ButtonBoxStyle.END)
    actions.set_spacing(8)
    for label, callback in buttons:
        button = Gtk.Button(label=label)
        button.connect("clicked", callback)
        actions.add(button)
    outer.pack_start(actions, False, False, 0)


def build_update_window():
    """Build the single top-level window used by every notifier state."""

    Gtk, Gdk, _glib = import_gtk()
    apply_theme(Gtk, Gdk)

    window = Gtk.Window()
    window.set_title(_("CaramOS - Update Center"))
    window.set_default_size(*_screen_dialog_size(Gdk))
    window.set_resizable(True)
    window.set_position(Gtk.WindowPosition.CENTER)
    set_caramos_icon(window, Gtk)

    stack = Gtk.Stack()
    stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
    stack.set_transition_duration(180)
    window.add(stack)
    return window, stack


def build_update_page(update_info: dict[str, Any], on_accept, on_close):
    """Build the available-update page."""

    Gtk, _gdk, _glib = import_gtk()

    current_version = format_value(update_info.get("current_version") or update_info.get("from_version"))
    new_release = format_value(update_info.get("release") or update_info.get("to_version"))
    channel = format_value(update_info.get("channel"), "stable")
    severity = severity_label(format_value(update_info.get("severity"), "normal"))
    size = format_value(update_info.get("size"))
    title = format_value(localized(update_info, "title"), _("A new CaramOS update is available"))
    summary = format_value(
        localized(update_info, "summary"),
        _("This update runs the CaramOS migrations the new version needs."),
    )
    packages = [normalize_package(pkg) for pkg in update_info.get("packages", [])]

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    outer.set_margin_top(12)
    outer.set_margin_bottom(10)
    outer.set_margin_start(14)
    outer.set_margin_end(14)

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
    old_lbl = Gtk.Label(label=_("Current version"))
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
    new_lbl = Gtk.Label(label=_("Available version"))
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
    add_info_row(Gtk, meta_card, 0, _("Update channel"), channel)
    add_info_row(Gtk, meta_card, 1, _("Severity"), severity)
    add_info_row(Gtk, meta_card, 2, _("Size"), size)

    pkg_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    pkg_panel.get_style_context().add_class("card")
    outer.pack_start(pkg_panel, True, True, 0)

    pkg_title = Gtk.Label()
    pkg_title.set_markup(
        "<span weight='bold'>{}</span>".format(
            html.escape(ngettext("%d change in this update", "%d changes in this update", len(packages)) % len(packages))
        )
    )
    pkg_title.set_xalign(0)
    pkg_panel.pack_start(pkg_title, False, False, 0)

    scroll = Gtk.ScrolledWindow()
    scroll.set_min_content_height(80)
    scroll.set_max_content_height(150)
    pkg_panel.pack_start(scroll, True, True, 0)

    pkg_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    for pkg in packages:
        item = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        description = format_value(pkg.get("description") or pkg.get("name"), _("CaramOS update"))
        description_lbl = Gtk.Label(label=description)
        description_lbl.set_xalign(0)
        description_lbl.set_line_wrap(True)
        item.pack_start(description_lbl, False, False, 0)
        pkg_box.pack_start(item, False, False, 0)

    scroll.add(pkg_box)

    warning = Gtk.Label()
    warning.get_style_context().add_class("warning")
    warning.set_text(
        _(
            "Recommended: plug in the charger, keep a stable network connection and do not turn off the "
            "computer during the update. You can close this window and update later."
        )
    )
    warning.set_xalign(0)
    warning.set_line_wrap(True)
    outer.pack_start(warning, False, False, 0)

    _add_action_buttons(
        Gtk,
        outer,
        [
            (_("Later"), lambda _button: on_close()),
            (_("Update now"), lambda _button: on_accept()),
        ],
    )
    return outer


def _screen_dialog_size(Gdk, *, width_ratio: float = 0.78, height_ratio: float = 0.80) -> tuple[int, int]:
    """Return a premium responsive dialog size bounded by the current screen."""

    screen = Gdk.Screen.get_default()
    screen_width = screen.get_width() if screen is not None else 1024
    screen_height = screen.get_height() if screen is not None else 768
    width = min(760, max(640, int(screen_width * width_ratio)))
    height = min(max(560, int(screen_height * height_ratio)), screen_height - 48)
    return width, height


def build_progress_page():
    """Build the progress page shown during update."""

    Gtk, _gdk, _glib = import_gtk()
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    outer.set_margin_top(12)
    outer.set_margin_bottom(10)
    outer.set_margin_start(14)
    outer.set_margin_end(14)

    hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    hero.get_style_context().add_class("hero")
    outer.pack_start(hero, False, False, 0)

    eyebrow = Gtk.Label()
    eyebrow.set_markup(
        "<span foreground='#fffaf0' weight='bold'>{}</span>".format(html.escape(_("CARAMOS OTA • UPDATING")))
    )
    eyebrow.set_xalign(0)
    hero.pack_start(eyebrow, False, False, 0)

    header = Gtk.Label()
    header.set_markup(
        "<span foreground='#ffffff' size='large' weight='bold'>{}</span>".format(html.escape(_("Updating CaramOS…")))
    )
    header.set_xalign(0)
    hero.pack_start(header, False, False, 0)

    stage_lbl = Gtk.Label(label=_("Preparing the update…"))
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
    log_title.set_markup("<span weight='bold'>{}</span>".format(html.escape(_("Update progress"))))
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
    warning.set_text(_("Please do not turn off the computer or close the update."))
    warning.set_xalign(0)
    warning.set_line_wrap(True)
    outer.pack_start(warning, False, False, 0)

    return outer, progress, stage_lbl, log_view


def build_result_page(success: bool, detail: str, on_close):
    """Build the result page shown after update."""

    Gtk, _gdk, _glib = import_gtk()
    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    outer.set_margin_top(12)
    outer.set_margin_bottom(10)
    outer.set_margin_start(14)
    outer.set_margin_end(14)

    hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    hero.get_style_context().add_class("hero")
    outer.pack_start(hero, False, False, 0)

    if success:
        title = _("Update complete!")
        summary = _("CaramOS was updated successfully.")
    else:
        title = _("Update failed")
        summary = _("Something went wrong during the update. Try again or run sudo caramos-ota --repair.")

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
    detail_title.set_markup("<span weight='bold'>{}</span>".format(html.escape(_("Update details"))))
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

    _add_action_buttons(Gtk, outer, [(_("Close"), lambda _button: on_close())])
    return outer


def build_no_update_page(status: dict[str, str] | None, on_close):
    """Build the page shown after a manual check finds no update."""

    Gtk, _gdk, _glib = import_gtk()
    status = status or {}
    current_version = format_value(status.get("current_version"))
    latest_version = format_value(status.get("latest_version"))
    channel = format_value(status.get("channel"), "stable")

    outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
    outer.set_margin_top(12)
    outer.set_margin_bottom(10)
    outer.set_margin_start(14)
    outer.set_margin_end(14)

    hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    hero.get_style_context().add_class("hero")
    outer.pack_start(hero, False, False, 0)

    eyebrow = Gtk.Label()
    eyebrow.set_markup("<span foreground='#fffaf0' weight='bold'>CARAMOS OTA • VIETNAM LINUX FAMILY</span>")
    eyebrow.set_xalign(0)
    hero.pack_start(eyebrow, False, False, 0)

    header = Gtk.Label()
    header.set_markup(
        "<span foreground='#ffffff' size='large' weight='bold'>{}</span>".format(html.escape(_("CaramOS is up to date")))
    )
    header.set_xalign(0)
    hero.pack_start(header, False, False, 0)

    summary = Gtk.Label(label=_("The system runs the latest version in the stable update channel."))
    summary.set_xalign(0)
    summary.set_line_wrap(True)
    hero.pack_start(summary, False, False, 0)

    card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    card.get_style_context().add_class("card")
    outer.pack_start(card, True, True, 0)

    title = Gtk.Label()
    title.set_markup("<span weight='bold'>{}</span>".format(html.escape(_("Update status"))))
    title.set_xalign(0)
    card.pack_start(title, False, False, 0)

    version_grid = Gtk.Grid()
    version_grid.set_column_spacing(12)
    version_grid.set_row_spacing(8)
    card.pack_start(version_grid, False, False, 0)
    add_info_row(Gtk, version_grid, 0, _("Current version"), current_version)
    add_info_row(Gtk, version_grid, 1, _("Latest version"), latest_version)
    add_info_row(Gtk, version_grid, 2, _("Update channel"), channel)

    body = Gtk.Label()
    body.set_xalign(0)
    body.set_line_wrap(True)
    body.set_text(
        _(
            "There are no new migrations to install.\n\n"
            "You can close this window. CaramOS OTA keeps checking periodically with a systemd timer."
        )
    )
    card.pack_start(body, False, False, 0)

    _add_action_buttons(Gtk, outer, [(_("Close"), lambda _button: on_close())])
    return outer

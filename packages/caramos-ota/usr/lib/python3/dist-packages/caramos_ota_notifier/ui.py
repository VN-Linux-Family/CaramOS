"""GTK dialog builders for the CaramOS OTA desktop notifier.

Every page is a scrolled body above a fixed action bar, so the buttons stay on screen however small the
window or long the list of changes (issue #77). Colours follow the Vietnam Linux Family palette, with a
dark variant when the desktop uses a dark GTK theme.
"""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from caramos_ota.i18n import _, localized, ngettext

from .constants import BUSY, CANCELLED, DONE, FAILED
from .state import format_value, normalize_package

CARAMOS_ICON = Path("/usr/share/pixmaps/caramos-logo.png")

LIGHT = {
    "green_900": "#1f4f32", "green_800": "#285f3d", "green_700": "#2f7048", "on_green": "#fffaf0",
    "bg": "#f7f3e9", "card": "#fffdf7", "ink": "#1f2a22", "muted": "#657064", "line": "#e3dfd1",
    "accent": "#2f7048", "tint": "rgba(47, 112, 72, 0.08)", "warn_bg": "#fff8df", "warn_line": "#ead5a3",
    "warn_ink": "#7a5514", "error_900": "#7a2e1d", "error_700": "#a5432a",
}
DARK = {
    "green_900": "#0f2a1a", "green_800": "#16331f", "green_700": "#3d8a5a", "on_green": "#fffaf0",
    "bg": "#141d17", "card": "#1c2820", "ink": "#eef2ea", "muted": "#a3b0a2", "line": "#2d3b31",
    "accent": "#8fd1a6", "tint": "rgba(143, 209, 166, 0.10)", "warn_bg": "#2e2715", "warn_line": "#5a4a22",
    "warn_ink": "#ffd08a", "error_900": "#4a1d14", "error_700": "#7a3424",
}

CSS = """
window.caramos-ota { background-color: %(bg)s; color: %(ink)s; }
window.caramos-ota * { font-family: "Be Vietnam Pro", "Inter", "Noto Sans", sans-serif; }
window.caramos-ota label { color: %(ink)s; }

window.caramos-ota headerbar.caramos-header {
  background-image: linear-gradient(135deg, %(green_900)s, %(green_800)s);
  background-color: %(green_900)s;
  border: none;
  box-shadow: inset 0 -1px rgba(0, 0, 0, 0.12);
  padding: 4px 8px;
}
window.caramos-ota headerbar.caramos-header label { color: %(on_green)s; }
window.caramos-ota headerbar.caramos-header .title { font-weight: 800; }
window.caramos-ota headerbar.caramos-header .subtitle { opacity: 0.75; }
window.caramos-ota headerbar.caramos-header button.titlebutton {
  color: %(on_green)s; background-image: none; background-color: transparent; border: none; box-shadow: none;
}
window.caramos-ota headerbar.caramos-header button.titlebutton:hover { background-color: rgba(255, 255, 255, 0.14); }

window.caramos-ota .hero {
  background-image: linear-gradient(135deg, %(green_900)s, %(green_700)s);
  border-radius: 20px;
  padding: 20px 22px;
}
window.caramos-ota .hero.error { background-image: linear-gradient(135deg, %(error_900)s, %(error_700)s); }
window.caramos-ota .hero label { color: %(on_green)s; }
window.caramos-ota .hero label.eyebrow {
  font-size: 11px; font-weight: 800;
  background-color: rgba(255, 250, 240, 0.16); border-radius: 999px; padding: 3px 10px;
}
window.caramos-ota .hero label.hero-title { font-size: 22px; font-weight: 800; }
window.caramos-ota .hero .version-box {
  background-color: rgba(255, 250, 240, 0.12); border-radius: 14px; padding: 10px 14px;
}
window.caramos-ota .hero label.version-caption { font-size: 12px; }
window.caramos-ota .hero label.version-value { font-size: 20px; font-weight: 800; }
window.caramos-ota .hero label.version-arrow { font-size: 20px; }

window.caramos-ota label.chip {
  font-size: 12px; font-weight: 700;
  background-color: %(card)s; border: 1px solid %(line)s; border-radius: 999px; padding: 4px 12px;
}
window.caramos-ota .card {
  background-color: %(card)s; border: 1px solid %(line)s; border-radius: 16px; padding: 16px 18px;
}
window.caramos-ota label.card-title { font-size: 15px; font-weight: 800; }
window.caramos-ota label.muted { color: %(muted)s; }
window.caramos-ota label.status-value { font-weight: 800; }
window.caramos-ota .change-row { padding: 4px 0; }
window.caramos-ota .change-row image { color: %(accent)s; }

window.caramos-ota .callout {
  background-color: %(warn_bg)s; border: 1px solid %(warn_line)s; border-radius: 14px; padding: 12px 14px;
}
window.caramos-ota .callout label, window.caramos-ota .callout image { color: %(warn_ink)s; font-weight: 600; }

window.caramos-ota .action-bar {
  background-color: %(card)s; border-top: 1px solid %(line)s; padding: 12px 18px;
}
window.caramos-ota .action-bar label.muted { font-size: 12px; }

window.caramos-ota button.primary, window.caramos-ota button.secondary {
  background-image: none; box-shadow: none; text-shadow: none;
  border-radius: 999px; padding: 9px 22px;
}
window.caramos-ota button.primary { background-color: %(green_700)s; border: 1px solid %(green_700)s; }
window.caramos-ota button.primary:hover { background-color: %(green_800)s; }
window.caramos-ota button.primary label { color: #ffffff; font-weight: 800; }
window.caramos-ota button.secondary { background-color: %(card)s; border: 1px solid %(line)s; }
window.caramos-ota button.secondary:hover { border-color: %(accent)s; }
window.caramos-ota button.secondary label { color: %(ink)s; font-weight: 800; }

window.caramos-ota progressbar.ota-progress trough {
  min-height: 10px; border-radius: 999px; border: none; background-image: none;
  background-color: rgba(255, 250, 240, 0.22);
}
window.caramos-ota progressbar.ota-progress progress {
  min-height: 10px; border-radius: 999px; border: none; background-image: none; background-color: %(on_green)s;
}

window.caramos-ota expander title label { font-weight: 700; }
window.caramos-ota textview.log-view, window.caramos-ota textview.log-view text {
  background-color: %(card)s; color: %(ink)s; font-family: "Ubuntu Mono", "DejaVu Sans Mono", monospace;
  font-size: 12px;
}
window.caramos-ota scrolledwindow.log-scroll { border: 1px solid %(line)s; border-radius: 12px; }
"""


def import_gtk():
    """Import GTK3 lazily so non-GUI sessions can exit quietly."""

    import gi

    # Pin Gdk and Pango too: with GTK 4 typelibs installed (the App Center needs them), an unpinned Gdk
    # loads 4.0 and GTK 3 then fails to import, so the Update Center never opened.
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Pango", "1.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Gdk, GLib, Gtk

    return Gtk, Gdk, GLib


def set_caramos_icon(dialog, Gtk) -> None:
    """Use the CaramOS brand icon for OTA dialogs.

    The 512 px pixmap is too large for GTK 3 to publish as _NET_WM_ICON, which left the taskbar entry
    blank; the themed icon (or the pixmap scaled down) is published.
    """

    theme = Gtk.IconTheme.get_default()
    if theme is not None and theme.has_icon("caramos-logo"):
        dialog.set_icon_name("caramos-logo")
    elif CARAMOS_ICON.exists():
        from gi.repository import GdkPixbuf

        dialog.set_icon(GdkPixbuf.Pixbuf.new_from_file_at_size(str(CARAMOS_ICON), 128, 128))


def prefers_dark(Gtk) -> bool:
    """True when the desktop uses a dark GTK theme (CaramOS dark mode switches to a -Dark theme)."""

    settings = Gtk.Settings.get_default()
    if settings is None:
        return False
    theme = (settings.get_property("gtk-theme-name") or "").lower()
    return bool(settings.get_property("gtk-application-prefer-dark-theme")) or "dark" in theme


def apply_theme(Gtk, Gdk) -> None:
    """Apply the CaramOS/VNLF styling to the Update Center window."""

    provider = Gtk.CssProvider()
    provider.load_from_data((CSS % (DARK if prefers_dark(Gtk) else LIGHT)).encode("utf-8"))
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


# Small widget helpers --------------------------------------------------------------------------


def _label(Gtk, text: str, *classes: str, wrap: bool = True, xalign: float = 0.0):
    from gi.repository import Pango

    widget = Gtk.Label(label=text)
    widget.set_xalign(xalign)
    widget.set_line_wrap(wrap)
    if wrap:
        widget.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
    for css_class in classes:
        widget.get_style_context().add_class(css_class)
    return widget


def _box(Gtk, vertical: bool = True, spacing: int = 0, *classes: str):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL if vertical else Gtk.Orientation.HORIZONTAL, spacing=spacing)
    for css_class in classes:
        box.get_style_context().add_class(css_class)
    return box


def _hero(Gtk, eyebrow: str, title: str, summary: str, *, error: bool = False):
    hero = _box(Gtk, True, 8, "hero")
    if error:
        hero.get_style_context().add_class("error")
    if eyebrow:
        tag = _label(Gtk, eyebrow, "eyebrow", wrap=False)
        tag.set_halign(Gtk.Align.START)
        hero.pack_start(tag, False, False, 0)
    hero.pack_start(_label(Gtk, title, "hero-title"), False, False, 0)
    if summary:
        hero.pack_start(_label(Gtk, summary, "hero-summary"), False, False, 0)
    return hero


def _callout(Gtk, icon_name: str, text: str):
    row = _box(Gtk, False, 10, "callout")
    image = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.LARGE_TOOLBAR)
    image.set_valign(Gtk.Align.START)
    row.pack_start(image, False, False, 0)
    row.pack_start(_label(Gtk, text), True, True, 0)
    return row


def _button(Gtk, text: str, style: str, callback):
    button = Gtk.Button(label=text)
    button.get_style_context().add_class(style)
    button.connect("clicked", callback)
    return button


def _page(Gtk, body_children: list, buttons: list, hint: str = ""):
    """A scrolled body over a fixed action bar that is always visible."""

    page = _box(Gtk, True, 0)
    scroll = Gtk.ScrolledWindow()
    scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
    scroll.set_min_content_height(120)
    body = _box(Gtk, True, 14)
    body.set_margin_top(18)
    body.set_margin_bottom(18)
    body.set_margin_start(20)
    body.set_margin_end(20)
    for child in body_children:
        body.pack_start(child, False, False, 0)
    scroll.add(body)
    page.pack_start(scroll, True, True, 0)

    if buttons or hint:
        bar = _box(Gtk, False, 10, "action-bar")
        if hint:
            note = _label(Gtk, hint, "muted")
            note.set_valign(Gtk.Align.CENTER)
            bar.pack_start(note, True, True, 0)
        for button in buttons:
            button.set_valign(Gtk.Align.CENTER)
            bar.pack_end(button, False, False, 0)
        page.pack_end(bar, False, False, 0)
    return page


def _info_card(Gtk, title: str, rows: list[tuple[str, str]]):
    card = _box(Gtk, True, 10, "card")
    card.pack_start(_label(Gtk, title, "card-title"), False, False, 0)
    grid = Gtk.Grid()
    grid.set_column_spacing(18)
    grid.set_row_spacing(8)
    for index, (key, value) in enumerate(rows):
        grid.attach(_label(Gtk, key, "muted", wrap=False), 0, index, 1, 1)
        grid.attach(_label(Gtk, value, "status-value"), 1, index, 1, 1)
    card.pack_start(grid, False, False, 0)
    return card


def _details(Gtk, title: str, text: str, *, expanded: bool):
    """A collapsible read-only log; returns (expander, text view)."""

    expander = Gtk.Expander(label=title)
    expander.set_expanded(expanded)
    scroll = Gtk.ScrolledWindow()
    scroll.get_style_context().add_class("log-scroll")
    scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scroll.set_min_content_height(180)
    scroll.set_margin_top(8)
    view = Gtk.TextView()
    view.get_style_context().add_class("log-view")
    view.set_editable(False)
    view.set_cursor_visible(False)
    view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
    view.set_left_margin(10)
    view.set_right_margin(10)
    view.set_top_margin(8)
    view.set_bottom_margin(8)
    view.get_buffer().set_text(text)
    scroll.add(view)
    expander.add(scroll)
    return expander, view


# Window and pages ------------------------------------------------------------------------------


def build_update_window():
    """Build the single top-level window used by every notifier state."""

    Gtk, Gdk, _glib = import_gtk()
    apply_theme(Gtk, Gdk)

    window = Gtk.Window()
    window.get_style_context().add_class("caramos-ota")
    header = Gtk.HeaderBar()
    header.set_show_close_button(True)
    header.set_subtitle("Vietnam Linux Family")
    header.get_style_context().add_class("caramos-header")
    window.set_titlebar(header)
    window.set_title(_("CaramOS - Update Center"))
    window.set_default_size(*_screen_dialog_size(Gdk))
    # Small enough for any laptop screen; the page bodies scroll and the action bar stays visible.
    window.set_size_request(380, 360)
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
    size = format_value(localized(update_info, "size"))
    title = format_value(localized(update_info, "title"), _("A new CaramOS update is available"))
    summary = format_value(
        localized(update_info, "summary"),
        _("This update runs the CaramOS migrations the new version needs."),
    )
    packages = [normalize_package(pkg) for pkg in update_info.get("packages", [])]

    hero = _hero(Gtk, _("New update"), title, summary)
    versions = _box(Gtk, False, 10)
    versions.set_margin_top(6)
    for caption, value in ((_("Current version"), current_version), (_("Available version"), new_release)):
        block = _box(Gtk, True, 2, "version-box")
        block.pack_start(_label(Gtk, caption, "version-caption", wrap=False), False, False, 0)
        block.pack_start(_label(Gtk, value, "version-value", wrap=False), False, False, 0)
        versions.pack_start(block, False, False, 0)
        if caption == _("Current version"):
            arrow = _label(Gtk, "→", "version-arrow", wrap=False)
            arrow.set_valign(Gtk.Align.CENTER)
            versions.pack_start(arrow, False, False, 0)
    hero.pack_start(versions, False, False, 0)

    chips = Gtk.FlowBox()
    chips.set_selection_mode(Gtk.SelectionMode.NONE)
    chips.set_column_spacing(8)
    chips.set_row_spacing(8)
    chips.set_max_children_per_line(4)
    for caption, value in ((_("Update channel"), channel), (_("Severity"), severity), (_("Size"), size)):
        chip = _label(Gtk, "%s: %s" % (caption, value), "chip")
        chip.set_halign(Gtk.Align.START)
        chips.add(chip)

    changes = _box(Gtk, True, 6, "card")
    changes.pack_start(
        _label(Gtk, ngettext("%d change in this update", "%d changes in this update", len(packages)) % len(packages),
               "card-title"),
        False, False, 0,
    )
    for pkg in packages:
        row = _box(Gtk, False, 10, "change-row")
        mark = Gtk.Image.new_from_icon_name("object-select-symbolic", Gtk.IconSize.MENU)
        mark.set_valign(Gtk.Align.START)
        mark.set_margin_top(3)
        row.pack_start(mark, False, False, 0)
        description = format_value(pkg.get("description") or pkg.get("name"), _("CaramOS update"))
        row.pack_start(_label(Gtk, description), True, True, 0)
        changes.pack_start(row, False, False, 0)

    warning = _callout(
        Gtk,
        "battery-good-charging-symbolic",
        _(
            "Recommended: plug in the charger, keep a stable network connection and do not turn off the "
            "computer during the update. You can close this window and update later."
        ),
    )
    buttons = [
        _button(Gtk, _("Update now"), "primary", lambda _button: on_accept()),
        _button(Gtk, _("Later"), "secondary", lambda _button: on_close()),
    ]
    return _page(Gtk, [hero, chips, changes, warning], buttons)


def _screen_dialog_size(Gdk, *, max_width: int = 720, max_height: int = 680) -> tuple[int, int]:
    """Default window size: comfortable on large screens, never larger than the monitor's work area."""

    width, height = 1024, 728
    display = Gdk.Display.get_default()
    monitor = None
    if display is not None:
        monitor = display.get_primary_monitor() or display.get_monitor(0)
    if monitor is not None:
        area = monitor.get_workarea()
        width, height = area.width, area.height
    return max(380, min(max_width, width - 64)), max(360, min(max_height, height - 64))


def build_progress_page():
    """Build the progress page shown during update."""

    Gtk, _gdk, _glib = import_gtk()
    hero = _hero(Gtk, _("Updating"), _("Updating CaramOS…"), "")
    stage_lbl = _label(Gtk, _("Preparing the update…"), "hero-summary")
    hero.pack_start(stage_lbl, False, False, 0)
    progress = Gtk.ProgressBar()
    progress.get_style_context().add_class("ota-progress")
    progress.set_pulse_step(0.05)
    progress.set_margin_top(8)
    hero.pack_start(progress, False, False, 0)

    details, log_view = _details(Gtk, _("Update progress"), "", expanded=False)
    page = _page(Gtk, [hero, details], [], hint=_("Please do not turn off the computer or close the update."))
    return page, progress, stage_lbl, log_view


def build_result_page(outcome: str, detail: str, on_close, on_help=None, on_retry=None):
    """Build the result page shown after an update run (outcome: DONE, FAILED, CANCELLED or BUSY).

    on_help: after a failure, ask VNLF for help with the log. on_retry: run the update again, offered when
    no password was given or another update was running.
    """

    Gtk, _gdk, _glib = import_gtk()
    if outcome == DONE:
        hero = _hero(Gtk, "", _("Update complete!"), _("CaramOS was updated successfully."))
    elif outcome == CANCELLED:
        hero = _hero(Gtk, "", _("Not updated yet"),
                     _("Updating CaramOS needs the password of an administrator account, and the password "
                       "window was closed. Click Try again and type the password when it is asked for."))
    elif outcome == BUSY:
        hero = _hero(Gtk, "", _("Another update is running"),
                     _("CaramOS is already updating, in another Update Center window or in the background. "
                       "Wait until it finishes (on a slow connection it can take a while), then click Try "
                       "again."))
    else:
        hero = _hero(
            Gtk, "", _("Update failed"),
            _("Something went wrong during the update. Try again or run sudo caramos-ota --repair."),
            error=True,
        )
    details, _view = _details(Gtk, _("Update details"), detail or "", expanded=outcome == FAILED)
    if on_retry is not None:
        # The bar packs from the end: Try again stays at the right edge.
        buttons = [_button(Gtk, _("Try again"), "primary", lambda _button: on_retry()),
                   _button(Gtk, _("Close"), "secondary", lambda _button: on_close())]
    else:
        buttons = [_button(Gtk, _("Close"), "primary", lambda _button: on_close())]
    hint = ""
    if outcome == FAILED and on_help is not None:
        # The bar packs from the end: Close stays at the right edge.
        buttons.append(_button(Gtk, _("Ask for help"), "secondary", lambda _button: on_help()))
        hint = _("Ask for help sends VNLF what the update logged, for its team only.")
    return _page(Gtk, [hero, details], buttons, hint=hint)


def build_no_update_page(status: dict[str, str] | None, on_close):
    """Build the page shown after a manual check finds no update."""

    Gtk, _gdk, _glib = import_gtk()
    status = status or {}
    current_version = format_value(status.get("current_version"))
    latest_version = format_value(status.get("latest_version"))
    channel = format_value(status.get("channel"), "stable")

    hero = _hero(Gtk, "", _("CaramOS is up to date"),
                 _("The system runs the latest version in the stable update channel."))
    card = _info_card(Gtk, _("Update status"), [
        (_("Current version"), current_version),
        (_("Latest version"), latest_version),
        (_("Update channel"), channel),
    ])
    note = _label(
        Gtk,
        _(
            "There are no new migrations to install.\n\n"
            "You can close this window. CaramOS OTA keeps checking periodically with a systemd timer."
        ),
        "muted",
    )
    return _page(Gtk, [hero, card, note], [_button(Gtk, _("Close"), "primary", lambda _button: on_close())])

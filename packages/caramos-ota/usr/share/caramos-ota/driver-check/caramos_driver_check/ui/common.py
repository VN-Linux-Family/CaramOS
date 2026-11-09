"""Widget helpers shared by the Driver Check pages; the look follows the CaramOS App Center."""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gtk, Pango  # noqa: E402

from caramos_ota.i18n import _  # noqa: E402

from ..analysis import ABSENT, CRITICAL, INFO, OK, TIP, WARNING  # noqa: E402

APP_DIR = Path(__file__).resolve().parents[2]
SYSTEM_LOGO = Path("/usr/share/pixmaps/caramos-logo.png")

AREA_ICONS = {
    "wifi": "network-wireless-symbolic",
    "ethernet": "network-wired-symbolic",
    "graphics": "video-display-symbolic",
    "audio": "audio-speakers-symbolic",
    "bluetooth": "bluetooth-active-symbolic",
    "camera": "camera-web-symbolic",
    "fingerprint": "auth-fingerprint-symbolic",
    "printer": "printer-symbolic",
    "other": "preferences-system-symbolic",
    "drivers": "system-software-install-symbolic",
}
LEVEL_ICONS = {
    OK: "emblem-ok-symbolic",
    TIP: "emblem-ok-symbolic",
    INFO: "dialog-information-symbolic",
    WARNING: "dialog-warning-symbolic",
    CRITICAL: "dialog-error-symbolic",
    ABSENT: "list-remove-symbolic",
}


def level_text(level: str) -> str:
    return {
        OK: _("Works"),
        TIP: _("Works"),
        INFO: _("Limited"),
        WARNING: _("Needs attention"),
        CRITICAL: _("Not working"),
        ABSENT: _("Not present"),
    }.get(level, level)


def load_css() -> None:
    display = Gdk.Display.get_default()
    # Icons the icon theme does not have: the bug of bug reports.
    Gtk.IconTheme.get_for_display(display).add_search_path(str(APP_DIR / "icons"))
    base = Gtk.CssProvider()
    base.load_from_path(str(APP_DIR / "style.css"))
    Gtk.StyleContext.add_provider_for_display(display, base, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    dark = Gtk.CssProvider()
    dark.load_from_path(str(APP_DIR / "style-dark.css"))
    manager = Adw.StyleManager.get_default()

    def apply(*_args) -> None:
        if manager.get_dark():
            Gtk.StyleContext.add_provider_for_display(display, dark, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        else:
            Gtk.StyleContext.remove_provider_for_display(display, dark)

    manager.connect("notify::dark", apply)
    apply()


def label(text: str, *classes: str, wrap: bool = True, xalign: float = 0.0, lines: int = 0,
          selectable: bool = False) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=xalign)
    widget.set_wrap(wrap)
    widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    if lines:
        widget.set_lines(lines)
        widget.set_ellipsize(Pango.EllipsizeMode.END)
    if selectable:
        widget.set_selectable(True)
        widget.set_can_focus(False)
    for css_class in classes:
        widget.add_css_class(css_class)
    return widget


def icon(name: str, size: int = 16, *classes: str) -> Gtk.Image:
    display = Gdk.Display.get_default()
    theme = Gtk.IconTheme.get_for_display(display) if display is not None else None
    if theme is not None and not theme.has_icon(name):
        name = "dialog-information-symbolic"
    image = Gtk.Image.new_from_icon_name(name)
    image.set_pixel_size(size)
    for css_class in classes:
        image.add_css_class(css_class)
    return image


def icon_bubble(name: str, size: int, *classes: str) -> Gtk.Widget:
    """An icon on a round tinted background (area icons of the cards, the status of the hero).

    The image itself carries the background; GTK draws the icon centred in it, and the size comes from
    the min-width/min-height of the bubble's CSS class.
    """

    image = icon(name, size, "bubble", *classes)
    image.set_halign(Gtk.Align.CENTER)
    image.set_valign(Gtk.Align.START)
    return image


def logo(size: int) -> Gtk.Widget:
    if SYSTEM_LOGO.is_file():
        image = Gtk.Image.new_from_file(str(SYSTEM_LOGO))
    else:
        image = Gtk.Image.new_from_icon_name("hardinfo")
    image.set_pixel_size(size)
    return image


def badge(text: str, *classes: str) -> Gtk.Label:
    widget = label(text, "badge", *classes, wrap=False)
    widget.set_valign(Gtk.Align.CENTER)
    return widget


def pill(text: str, callback, *, suggested: bool = False, icon_name: str = "") -> Gtk.Button:
    button = Gtk.Button()
    if icon_name:
        content = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        content.append(Gtk.Image.new_from_icon_name(icon_name))
        content.append(Gtk.Label(label=text))
        button.set_child(content)
    else:
        button.set_label(text)
    button.add_css_class("pill")
    if suggested:
        button.add_css_class("suggested-action")
    button.connect("clicked", lambda _button: callback())
    return button


def link_button(text: str, url: str) -> Gtk.Button:
    button = Gtk.Button()
    button.add_css_class("flat")
    button.add_css_class("see-more")
    content = Gtk.Box(spacing=6)
    content.append(Gtk.Label(label=text))
    content.append(Gtk.Image.new_from_icon_name("web-browser-symbolic"))
    button.set_child(content)
    button.set_tooltip_text(url)
    button.connect("clicked", lambda widget: open_uri(widget, url))
    return button


def open_uri(widget: Gtk.Widget, uri: str) -> None:
    root = widget.get_root()
    Gtk.UriLauncher.new(uri).launch(root if isinstance(root, Gtk.Window) else None, None, None, None)


def notes_box(notes, spacing: int = 6) -> Gtk.Box:
    """Facts as ✓ (good) and – (caveat) lines, like the pros and cons of the App Center cards."""

    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    for text, good in notes:
        row = Gtk.Box(spacing=8)
        image = Gtk.Image.new_from_icon_name("object-select-symbolic" if good else "list-remove-symbolic")
        image.add_css_class("pro-icon" if good else "con-icon")
        image.set_valign(Gtk.Align.START)
        image.set_margin_top(2)
        row.append(image)
        text_label = label(text, "pro-text" if good else "con-text")
        text_label.set_hexpand(True)
        row.append(text_label)
        box.append(row)
    return box


def section(number: int, title: str, hint: str = "") -> Gtk.Box:
    heading = Gtk.Box(spacing=12)
    heading.append(label(str(number), "section-number", wrap=False, xalign=0.5))
    title_label = label(title, "section-title")
    title_label.set_valign(Gtk.Align.CENTER)
    heading.append(title_label)
    if hint:
        hint_label = label(hint, "section-hint", wrap=False)
        hint_label.set_valign(Gtk.Align.CENTER)
        heading.append(hint_label)
    return heading


def clamp(child: Gtk.Widget, width: int = 980) -> Adw.Clamp:
    widget = Adw.Clamp(maximum_size=width, tightening_threshold=width - 200)
    widget.set_child(child)
    return widget


def scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    window = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    window.set_child(child)
    return window


def page_box(spacing: int = 30) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=spacing)
    box.set_margin_top(24)
    box.set_margin_bottom(32)
    box.set_margin_start(24)
    box.set_margin_end(24)
    return box


def header(title: str, subtitle: str = "") -> Adw.HeaderBar:
    bar = Adw.HeaderBar()
    bar.set_title_widget(Adw.WindowTitle(title=title, subtitle=subtitle or _("CaramOS")))
    return bar


def bottom_bar(title: str, detail: str, buttons: list[Gtk.Widget]) -> Gtk.Box:
    """The sticky bar under every page, like the App Center's install bar."""

    bar = Gtk.Box(spacing=12)
    bar.add_css_class("install-bar")
    totals = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, hexpand=True, valign=Gtk.Align.CENTER)
    totals.append(label(title, "bar-total"))
    if detail:
        totals.append(label(detail, "dim-label", "bar-detail"))
    bar.append(totals)
    for button in buttons:
        button.set_valign(Gtk.Align.CENTER)
        bar.append(button)
    return bar


def log_view(text: str = "") -> tuple[Gtk.Expander, Gtk.TextView]:
    expander = Gtk.Expander(label=_("Details"))
    view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
    view.add_css_class("log-view")
    view.set_left_margin(10)
    view.set_right_margin(10)
    view.set_top_margin(8)
    view.set_bottom_margin(8)
    view.get_buffer().set_text(text)
    window = Gtk.ScrolledWindow(min_content_height=180, hscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
    window.add_css_class("log-scroll")
    window.set_child(view)
    window.set_margin_top(8)
    expander.set_child(window)
    return expander, view


def append_log(view: Gtk.TextView, line: str) -> None:
    buffer = view.get_buffer()
    buffer.insert(buffer.get_end_iter(), line + "\n")

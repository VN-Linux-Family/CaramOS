"""The look of CaramOS's GTK 4 + libadwaita tools, after DESIGN.md in the CaramOS repository.

libadwaita's own header bars, surfaces, boxed lists and status pages; the forest green accent as the only colour of
CaramOS's own; the system font (Be Vietnam Pro), of which this only sets sizes and the two weights, 400 and 600. The
dark values are loaded on top while the system uses a dark style. Used by Chuyển mã sang Unicode and Chuyển dữ liệu
từ Windows; the App Center has the same rules in its own package.
"""

from __future__ import annotations

LIGHT = """
@define-color accent_bg_color #2b6a44;
@define-color accent_fg_color #ffffff;
@define-color accent_color #276140;
@define-color caramos_line_color rgba(0, 0, 0, 0.09);

/* Two weights: libadwaita's titles are 700 to 800 and its buttons bold. */
.title-1, .title-2, .title-3, .title-4, .heading, headerbar .title, windowtitle .title, button {
  font-weight: 600;
}
button.flat.link { font-weight: inherit; }

.page-title { font-size: 1.8em; font-weight: 600; }
.section-title { font-size: 1.15em; font-weight: 600; }
.row-title { font-weight: 600; }
.secondary { font-size: 0.92em; }

/* Boxed lists: a thin line around and between the rows, no shadow; each row's name in 600. */
list.boxed-list { box-shadow: 0 0 0 1px @caramos_line_color; }
list.boxed-list > row { border-color: @caramos_line_color; }
list.boxed-list > row:not(.entry) box.title > label.title { font-weight: 600; }

/* Status pages: a 64px icon and the page title size (only the page's own, not those of rows inside it). */
statuspage > scrolledwindow > viewport > box > clamp > box > .icon { -gtk-icon-size: 64px; }
statuspage > scrolledwindow > viewport > box > clamp > box > .title { font-size: 1.8em; font-weight: 600; }

/* The bar at the bottom: a hint at the left, the buttons at the right. */
.action-bar { padding: 12px 24px; }
.caramos-log { font-family: monospace; font-size: 0.92em; }
"""

DARK = """
@define-color accent_bg_color #3a855a;
@define-color accent_fg_color #ffffff;
@define-color accent_color #8ccfa5;
@define-color caramos_line_color rgba(255, 255, 255, 0.08);
"""


def apply() -> None:
    """Load the style for the default display, and follow the system between light and dark."""

    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    display = Gdk.Display.get_default()
    if display is None:
        return
    light = Gtk.CssProvider()
    light.load_from_string(LIGHT)
    Gtk.StyleContext.add_provider_for_display(display, light, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    dark = Gtk.CssProvider()
    dark.load_from_string(DARK)
    manager = Adw.StyleManager.get_default()

    def follow(*_args) -> None:
        if manager.get_dark():
            Gtk.StyleContext.add_provider_for_display(display, dark, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        else:
            Gtk.StyleContext.remove_provider_for_display(display, dark)

    manager.connect("notify::dark", follow)
    follow()

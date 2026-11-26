"""The sound level shown for a moment when a sound key is pressed: a slim bar at the bottom of the screen, above the
dock, with the speaker (or microphone), the level and its percentage. It lets clicks through and hides by itself.

It was Cinnamon's square until ticket H-1216: the square took much room, showed no number, and the theme's 32 px
minimum for a level bar's block (Cinnamon-Delight's gtk.css) drew every level under about a third the same, so the
first presses of the keys showed no change. The block has no minimum now (style.css).

The keys change the sound themselves (caramos-volume, an Xfce keyboard shortcut), then ask the running Control Center
for this window (its "osd" action)."""

from __future__ import annotations

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import widgets as w  # noqa: E402

try:
    gi.require_foreign("cairo")
    import cairo
except (ImportError, ValueError):  # without python3-gi-cairo the window only takes the clicks on it
    cairo = None

SHOW_MS = 1500
ICON_SIZE = 20
ABOVE_DOCK = 48 + 24  # the bar's bottom edge: 24 px above the 48 px dock


def percent_text(fraction: float) -> str:
    """The level as people read it on Windows: "45%"."""

    return f"{round(max(0.0, min(fraction, 1.0)) * 100)}%"


class Osd(Gtk.Window):
    def __init__(self) -> None:
        super().__init__(type=Gtk.WindowType.POPUP)
        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.set_accept_focus(False)
        w.styled(self, "caramos-cc")
        self.card = w.styled(Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14), "caramos-cc-osd")
        self.image = w.icon("audio-volume-high-symbolic", ICON_SIZE, "caramos-cc-osd-icon")
        self.level = w.styled(Gtk.LevelBar.new_for_interval(0, 1), "caramos-cc-osd-level")
        for offset in (Gtk.LEVEL_BAR_OFFSET_LOW, Gtk.LEVEL_BAR_OFFSET_HIGH, Gtk.LEVEL_BAR_OFFSET_FULL):
            self.level.remove_offset_value(offset)
        self.level.set_valign(Gtk.Align.CENTER)
        # "100%" fits, so the bar does not move as the number changes.
        self.percent = w.styled(Gtk.Label(xalign=1.0, width_chars=4), "caramos-cc-osd-percent")
        self.card.pack_start(self.image, False, False, 0)
        self.card.pack_start(self.level, True, True, 0)
        self.card.pack_start(self.percent, False, False, 0)
        self.add(self.card)
        self.connect("realize", self._click_through)
        self._timeout = 0

    @staticmethod
    def _click_through(window: Gtk.Window) -> None:
        if cairo is not None:
            window.get_window().input_shape_combine_region(cairo.Region(), 0, 0)

    def show_level(self, icon_name: str, fraction: float, muted: bool, dark: bool) -> None:
        w.set_icon(self.image, icon_name)
        self.level.set_value(0 if muted else max(0.0, min(fraction, 1.0)))
        # Muted: the bar is empty, the number stays (greyed), the level the key brings back.
        self.percent.set_text(percent_text(fraction))
        w.set_class(self.percent, "muted", muted)
        w.set_class(self, "dark", dark)
        self.card.show_all()
        natural = self.get_preferred_size()[1]
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        area = monitor.get_geometry()
        self.move(area.x + (area.width - natural.width) // 2, area.y + area.height - ABOVE_DOCK - natural.height)
        self.show()
        if self._timeout:
            GLib.source_remove(self._timeout)
        self._timeout = GLib.timeout_add(SHOW_MS, self._done)

    def _done(self) -> bool:
        self._timeout = 0
        self.hide()
        return False

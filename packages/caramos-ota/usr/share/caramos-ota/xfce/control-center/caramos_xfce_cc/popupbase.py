"""A card that opens above the taskbar's right island, as the Cinnamon applets' menus do: the Control Center's popup
and the clock's calendar."""

from __future__ import annotations

import time

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import widgets as w  # noqa: E402
from .util import SOUND_KEYS, spawn  # noqa: E402

EDGE = 4  # the right island also stops 4 px before the screen edge
GAP = 0   # as on Cinnamon, the card sits on the panel: the island's own margin is the gap
SOUND_KEY_ARGS = {Gdk.KEY_AudioRaiseVolume: "up", Gdk.KEY_AudioLowerVolume: "down", Gdk.KEY_AudioMute: "mute",
                  Gdk.KEY_AudioMicMute: "mic-mute"}


class CardPopup(Gtk.Window):
    def __init__(self, title: str, *card_classes: str) -> None:
        # A popup window, as GTK's menus are: the window manager does not move it or draw a square shadow around
        # it, and it takes the pointer and keyboard while open (a click outside or Esc closes it).
        super().__init__(type=Gtk.WindowType.POPUP)
        self.hidden_at = 0.0
        self._anchor: tuple[int, int] | None = None
        self._grabbed = False
        self.set_title(title)
        visual = self.get_screen().get_rgba_visual()
        if visual is not None:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.set_type_hint(Gdk.WindowTypeHint.POPUP_MENU)
        self.set_resizable(False)
        w.styled(self, "caramos-cc")
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("button-press-event", self._on_button)
        self.connect("key-press-event", self._on_key)
        self.connect("map-event", lambda *_: self._grab())
        self.connect("grab-broken-event", lambda *_: self.hide_popup() or False)
        self.connect("size-allocate", lambda *_: self._place())

        # The card fills the window, which is transparent outside the card's round corners.
        self.card = w.styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8), "caramos-cc-card",
                             *card_classes)
        self.add(self.card)

    def toggle(self, anchor: tuple[int, int] | None, event_time: int = Gdk.CURRENT_TIME) -> None:
        if self.get_visible():
            self.hide_popup()
            return
        if time.monotonic() - self.hidden_at < 0.3:  # the click that took the focus away is this one
            return
        self.show_popup(anchor, event_time)

    def show_popup(self, anchor: tuple[int, int] | None, event_time: int = Gdk.CURRENT_TIME) -> None:
        self._anchor = anchor
        self.show_all()
        self._place()

    def left(self, area: Gdk.Rectangle, width: int) -> int:
        """The card's left edge on the screen: its right edge 4 px from the screen's, as the right island's."""

        return area.x + area.width - EDGE - width

    def _place(self) -> bool:
        """The card's bottom just above the right island."""

        display = Gdk.Display.get_default()
        monitor = display.get_monitor_at_point(*self._anchor) if self._anchor else display.get_primary_monitor()
        if monitor is None:
            monitor = display.get_monitor(0)
        area = monitor.get_geometry()
        top = self._anchor[1] if self._anchor else area.y + area.height - 48 + EDGE
        width, height = self.get_size()
        self.move(self.left(area, width), top - GAP - height)
        return False

    def _grab(self) -> None:
        window = self.get_window()
        seat = Gdk.Display.get_default().get_default_seat()
        if window is None or seat is None:
            return
        status = seat.grab(window, Gdk.SeatCapabilities.ALL, True, None, None, None)
        self._grabbed = status == Gdk.GrabStatus.SUCCESS
        if not self._grabbed:  # someone else holds the pointer (a menu): try once more in a moment
            GLib.timeout_add(100, self._retry_grab)

    def _retry_grab(self) -> bool:
        if self.get_visible() and not self._grabbed:
            self._grab()
        return False

    def hide_popup(self) -> None:
        if self._grabbed:
            Gdk.Display.get_default().get_default_seat().ungrab()
            self._grabbed = False
        if self.get_visible():
            self.hide()
            self.hidden_at = time.monotonic()

    def _on_button(self, _widget: Gtk.Widget, event: Gdk.EventButton) -> bool:
        """With the grab, a click anywhere reaches this window: outside the card it closes the popup."""

        window = self.get_window()
        if window is None:
            return False
        _ok, origin_x, origin_y = window.get_origin()
        card = self.card.get_allocation()
        x, y = event.x_root - origin_x, event.y_root - origin_y
        if card.x <= x < card.x + card.width and card.y <= y < card.y + card.height:
            return False
        self.hide_popup()
        return True

    def _on_key(self, _widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide_popup()
            return True
        # The popup holds the keyboard, so the session's shortcut for the sound keys does not see them: run it here.
        sound_key = SOUND_KEY_ARGS.get(event.keyval)
        if sound_key:
            spawn((SOUND_KEYS, sound_key))
            return True
        return False

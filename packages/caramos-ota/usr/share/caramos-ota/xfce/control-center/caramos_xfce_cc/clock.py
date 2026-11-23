"""The taskbar's clock on CaramOS Xfce, which the Control Center draws beside its button: Xfce's clock plugin opens
GTK's calendar, which cannot show lunar dates, so the clock is this one (ticket H-1178). Clicking it opens the
calendar with lunar dates (calendar_popup.py), as on Cinnamon; its tooltip has today's lunar date.

It looks like Xfce's clock in CaramOS 1.4.0: the button has that clock's name, so panel-islands.css draws it the
same piece of the right island, and it keeps that clock's font and format, without the double space that %e puts
before the 1st to the 9th of a month. It is hidden while a panel holds Xfce's clock (backends/panelclock.py)."""

from __future__ import annotations

import datetime
from collections.abc import Callable

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, Gtk  # noqa: E402

from . import lunar  # noqa: E402
from . import widgets as w  # noqa: E402

FORMAT = "%A %H:%M, %-d %B"  # Xfce's clock in CaramOS 1.4.0 had "%A %H:%M, %e %B"


def today(now: GLib.DateTime) -> datetime.date:
    return datetime.date(now.get_year(), now.get_month(), now.get_day_of_month())


def long_date(now: GLib.DateTime, language: str) -> str:
    """The weekday and the date: in Vietnamese the Vietnamese way (lunar.vietnamese_date), else "Friday 20 November
    2026"."""

    if lunar.is_vietnamese(language):
        return f"{now.format('%A')}, {lunar.vietnamese_date(today(now))}"
    return now.format("%A %-d %B %Y") or ""


class Clock(Gtk.Button):
    def __init__(self, panel_clock: object, on_click: Callable[["Clock", int], None]) -> None:
        super().__init__()
        self.panel_clock = panel_clock
        self.language = GLib.get_language_names()[0]
        self.set_name("clock-button")
        self.set_relief(Gtk.ReliefStyle.NONE)
        self.label = w.styled(Gtk.Label(), "caramos-cc-clock-label")
        self.add(self.label)
        self.label.show()
        self.set_no_show_all(True)  # shown or hidden by _show_or_hide only
        self.connect("button-release-event", lambda _b, event: on_click(self, event.time) or False)
        self._timer = 0
        self.update()
        panel_clock.connect("changed", lambda *_: self._show_or_hide())
        self._show_or_hide()
        self._watch_sleep()

    def _show_or_hide(self) -> None:
        self.set_visible(not self.panel_clock.xfce_clock)

    def update(self) -> None:
        now = GLib.DateTime.new_now_local()
        self.label.set_text(now.format(FORMAT) or "")
        text = f"{long_date(now, self.language)}\n{lunar.lunar_text(today(now), self.language)}"
        self.set_tooltip_text(text)
        self.get_accessible().set_name(text)
        # The next minute, a little after it starts.
        if self._timer:
            GLib.source_remove(self._timer)
        delay = (60 - now.get_second()) * 1000 - now.get_microsecond() // 1000 + 50
        self._timer = GLib.timeout_add(max(delay, 50), self._tick)

    def _tick(self) -> bool:
        self._timer = 0
        self.update()
        return False

    def _watch_sleep(self) -> None:
        """A timer does not count the time the computer slept: after waking up, the clock is set again at once."""

        try:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        except GLib.Error:
            return
        bus.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager", "PrepareForSleep",
                             "/org/freedesktop/login1", None, Gio.DBusSignalFlags.NONE, self._on_sleep)

    def _on_sleep(self, _bus: object, _sender: str, _path: str, _interface: str, _signal: str,
                  parameters: GLib.Variant) -> None:
        going_to_sleep = parameters.unpack()[0]
        if not going_to_sleep:
            self.update()

    def set_open(self, open_: bool) -> None:
        """While the calendar is open the clock keeps its round patch (#clock-button:checked in panel-islands.css),
        as Xfce's clock did."""

        if open_:
            self.set_state_flags(Gtk.StateFlags.CHECKED, False)
        else:
            self.unset_state_flags(Gtk.StateFlags.CHECKED)

    def anchor(self) -> tuple[int, int]:
        """(middle, top) of this button on the screen, for the calendar."""

        window = self.get_window()
        if window is None:
            return (0, 0)
        _ok, x, y = window.get_origin()
        allocation = self.get_allocation()
        return (x + allocation.x + allocation.width // 2, y + allocation.y)


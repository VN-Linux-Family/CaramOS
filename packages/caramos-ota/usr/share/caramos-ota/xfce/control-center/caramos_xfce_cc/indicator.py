"""The Control Center's button in the taskbar's right island, as on Cinnamon: the network, a VPN while one is
connected, the microphone while an application records, the volume, the battery with its percentage when the
computer has one, and a crossed bell while Do not disturb is on. It draws its own piece of the island
(panel-islands.css, #caramos-cc-indicator). Scrolling over it changes the volume by the volume step (ticket H-1180),
through caramos-volume, which also shows the level."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from . import widgets as w  # noqa: E402
from .backends.audio import volume_icon  # noqa: E402
from .backends.power import battery_text  # noqa: E402
from .i18n import _  # noqa: E402


# The sound keys' command: it changes the volume by the volume step and shows the level.
VOLUME_COMMAND = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                              "caramos-volume")


class Indicator(Gtk.Button):
    def __init__(self, backends: object, on_click: Callable[["Indicator", int], None]) -> None:
        super().__init__()
        self.b = backends
        self.set_name("caramos-cc-indicator")
        self.set_relief(Gtk.ReliefStyle.NONE)
        self.set_tooltip_text(_("CaramOS Control Center"))
        self.get_accessible().set_name(_("CaramOS Control Center"))
        box = Gtk.Box(spacing=8)
        self.network = w.icon("network-offline-symbolic", 16, "caramos-cc-panel-icon")
        self.vpn = w.icon("network-vpn-symbolic", 16, "caramos-cc-panel-icon")
        self.mic = w.icon("microphone-sensitivity-high-symbolic", 16, "caramos-cc-panel-icon")
        self.volume = w.icon("audio-volume-high-symbolic", 16, "caramos-cc-panel-icon")
        self.quiet = w.icon(["notifications-disabled-symbolic", "preferences-system-notifications-symbolic"], 16,
                            "caramos-cc-panel-icon")
        self.battery = Gtk.Box(spacing=3)
        self.battery_icon = w.icon("battery-full-symbolic", 16, "caramos-cc-panel-icon")
        self.battery_label = w.label("", "caramos-cc-panel-battery", ellipsize=False)
        self.battery.pack_start(self.battery_icon, False, False, 0)
        self.battery.pack_start(self.battery_label, False, False, 0)
        for child in (self.quiet, self.network, self.vpn, self.mic, self.volume, self.battery):
            box.pack_start(child, False, False, 0)
        self.add(box)
        self.show_all()
        self.connect("button-release-event", lambda _b, event: on_click(self, event.time) or False)
        # Notches only: with the smooth-scroll mask, GTK on X11 reports a wheel click as a smooth scroll whose delta
        # is 0 after the pointer enters the window, so the first clicks would do nothing.
        self.add_events(Gdk.EventMask.SCROLL_MASK)
        self.connect("scroll-event", self._on_scroll)
        for source in (self.b.audio, self.b.network, self.b.vpn, self.b.battery, self.b.notifications):
            source.connect("changed", lambda *_: self.update())
        self.update()

    def _on_scroll(self, _button: Gtk.Button, event: Gdk.EventScroll) -> bool:
        direction = {Gdk.ScrollDirection.UP: "up", Gdk.ScrollDirection.DOWN: "down"}.get(event.direction)
        if direction:
            subprocess.Popen([VOLUME_COMMAND, direction], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        return True

    def update(self) -> None:
        network = self.b.network.state
        kind = network.primary_type
        w.set_icon(self.network, "network-offline-symbolic" if not kind else "network-wired-symbolic"
                   if kind == "ethernet" else "network-wireless-symbolic" if kind == "wifi"
                   else "network-transmit-receive-symbolic")
        self.vpn.set_visible(any(profile.active for profile in self.b.vpn.profiles))
        self.mic.set_visible(self.b.audio.recording)
        output = self.b.audio.state.device("output")
        w.set_icon(self.volume, volume_icon(output.volume, output.muted) if output else "audio-volume-muted-symbolic")
        self.quiet.set_visible(self.b.notifications.quiet)
        battery = self.b.battery.battery
        self.battery.set_visible(battery.present)
        if battery.present:
            w.set_icon(self.battery_icon, battery.icon)
            self.battery_label.set_text(f"{round(battery.percentage)}%")
            self.set_tooltip_text(f"{_('CaramOS Control Center')}\n{_('Battery')}: {battery_text(battery)}")

    def anchor(self) -> tuple[int, int]:
        """(right edge, top) of this button on the screen, for the popup."""

        window = self.get_window()
        if window is None:
            return (0, 0)
        _ok, x, y = window.get_origin()
        allocation = self.get_allocation()
        return (x + allocation.x + allocation.width, y + allocation.y)

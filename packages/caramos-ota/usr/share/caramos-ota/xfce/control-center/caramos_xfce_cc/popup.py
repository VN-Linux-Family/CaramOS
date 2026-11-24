"""The Control Center popup: the layout and behaviour of the Cinnamon applet's menu (applet.js _buildMenu)."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from . import widgets as w  # noqa: E402
from .backends import session  # noqa: E402
from .backends.appearance import ACCENTS, Appearance  # noqa: E402
from .backends.audio import AudioBackend, volume_icon  # noqa: E402
from .backends.bluetooth import BluetoothBackend  # noqa: E402
from .backends.brightness import Brightness  # noqa: E402
from .backends.ddc import Ddc  # noqa: E402
from .backends.drives import DrivesBackend  # noqa: E402
from .backends.network import (NetworkBackend, VpnBackend, connectivity_text, device_state_text,  # noqa: E402
                               wifi_signal_icon)
from .backends.nightlight import NightLight  # noqa: E402
from .backends.notifications import Notifications  # noqa: E402
from .backends.panelclock import PanelClock  # noqa: E402
from .backends.power import PROFILE_ICONS, BatteryBackend, ProfilesBackend, battery_text, profile_label  # noqa: E402
from .backends.taskbar import CENTER, LEFT, Taskbar  # noqa: E402
from .i18n import _, ngettext  # noqa: E402
from .popupbase import CardPopup  # noqa: E402
from .util import notify, spawn, spawn_named  # noqa: E402

LOG = logging.getLogger("caramos-control-center")

WIFI_LIST_LIMIT = 7
VPN_LIST_LIMIT = 7
CARD_WIDTH = 362  # the Cinnamon applet's card, border included


class Popup(CardPopup):
    def __init__(self, backends: "Backends") -> None:
        # The window and its card: popupbase.CardPopup, as the clock's calendar.
        super().__init__(_("CaramOS Control Center"))
        self.b = backends
        self.card.set_size_request(CARD_WIDTH, -1)
        self.inline = w.InlineCard(self.close_inline)
        self.inline_fill: Callable[[], None] | None = None
        self.confirming = ""

        # Header: battery, then screenshot, settings, lock and the power menu.
        self.header = w.styled(Gtk.Box(spacing=8), "caramos-cc-header")
        self.pill = w.Pill(lambda: self._run("powerSettings"))
        self.header.pack_start(self.pill, False, False, 0)
        buttons = Gtk.Box(spacing=8)
        for icon_name, tooltip, action in (
                ("camera-photo-symbolic", _("Take a screenshot"), self._screenshot),
                ("preferences-system-symbolic", _("Open system settings"), lambda: self._run("settings")),
                ("system-lock-screen-symbolic", _("Lock screen"), lambda: self._run("lock")),
                ("system-shutdown-symbolic", _("Open power menu"),
                 lambda: self.toggle_inline("power", "system-shutdown-symbolic", _("Power"), self.fill_power,
                                            self.header))):
            buttons.pack_start(w.round_button(icon_name, tooltip, action), False, False, 0)
        self.header.pack_end(buttons, False, False, 0)
        self.card.pack_start(self.header, False, False, 0)

        # USB drives and memory cards, while one is plugged in (ticket H-1195): open it, or remove it safely.
        self.drives = w.styled(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2), "caramos-cc-inline-card",
                               "caramos-cc-drives")
        drives_head = Gtk.Box(spacing=8)
        drives_head.pack_start(w.icon("drive-removable-media-symbolic", 16, "caramos-cc-inline-head-icon"),
                               False, False, 0)
        drives_head.pack_start(w.label(_("USB drives and memory cards"), "caramos-cc-inline-title"), True, True, 0)
        self.drives.pack_start(drives_head, False, False, 0)
        self.drive_rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.drives.pack_start(self.drive_rows, False, False, 0)
        self.drive_keys: list[tuple[str, str, bool]] = []
        self.card.pack_start(self.drives, False, False, 0)

        # Sliders.
        self.volume = w.SliderRow("audio-volume-high-symbolic", _("Volume"),
                                  lambda v: self.b.audio.set_volume("output", v),
                                  lambda: self.b.audio.toggle_mute("output"),
                                  lambda: self.toggle_inline("output", "audio-speakers-symbolic", _("Output device"),
                                                             lambda: self.fill_audio("output"), self.volume))
        self.mic = w.SliderRow("microphone-sensitivity-high-symbolic", _("Microphone"),
                               lambda v: self.b.audio.set_volume("input", v),
                               lambda: self.b.audio.toggle_mute("input"),
                               lambda: self.toggle_inline("input", "audio-input-microphone-symbolic",
                                                          _("Input device"), lambda: self.fill_audio("input"),
                                                          self.mic))
        self.brightness = w.SliderRow("display-brightness-symbolic", _("Brightness"), self.b.brightness.set)
        for row in (self.volume, self.mic, self.brightness):
            self.card.pack_start(row, False, False, 0)
        # External monitors' brightness (ticket H-1183): a slider for each monitor that answers DDC/CI.
        self.ddc_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.ddc_rows: dict[int, w.SliderRow] = {}
        self.card.pack_start(self.ddc_box, False, False, 0)

        # Tiles, two per row.
        self.wired = w.Tile("network-wired-symbolic", _("Wired network"), _("Checking…"),
                            lambda: self._run("networkSettings"),
                            lambda: self.toggle_inline("wired", "network-wired-symbolic", _("Wired network"),
                                                       self.fill_wired, self.network_row))
        self.wifi = w.Tile("network-wireless-symbolic", _("Wi‑Fi"), _("Checking…"), self.toggle_wifi,
                           lambda: self.toggle_inline("wifi", "network-wireless-symbolic", _("Wi‑Fi"),
                                                      self.fill_wifi, self.network_row, self.b.network.request_scan))
        self.vpn = w.Tile("network-vpn-symbolic", _("VPN"), _("Not connected"), self.toggle_vpn,
                          lambda: self.toggle_inline("vpn", "network-vpn-symbolic", _("VPN"), self.fill_vpn,
                                                     self.connections_row, self.b.vpn.refresh))
        self.bluetooth = w.Tile("bluetooth-symbolic", _("Bluetooth"), _("Checking…"), self.toggle_bluetooth,
                                lambda: self.toggle_inline("bluetooth", "bluetooth-symbolic", _("Bluetooth"),
                                                           self.fill_bluetooth, self.connections_row))
        self.dark = w.Tile(["dark-mode-symbolic", "weather-clear-night-symbolic"], _("Dark mode"), _("Disabled"),
                           self.toggle_dark)
        self.night = w.Tile(["night-light-symbolic", "weather-clear-night-symbolic"], _("Night Light"),
                            _("Disabled"), self.toggle_night)
        self.power_mode = w.Tile("preferences-system-power-symbolic", _("Power mode"), _("Loading…"),
                                 self.open_power_mode, self.open_power_mode)
        self.accent = w.Tile(["preferences-color-symbolic", "color-select-symbolic", "applications-graphics-symbolic"],
                             _("Accent colour"), "",
                             lambda: self.toggle_inline("accent", "applications-graphics-symbolic",
                                                        _("Accent colour"), self.fill_accent, self.power_row))
        # Do not disturb (ticket H-1179): xfce4-notifyd keeps notifications without showing them.
        self.dnd = w.Tile(["notifications-disabled-symbolic", "preferences-system-notifications-symbolic"],
                          _("Do not disturb"), _("Disabled"), self.toggle_dnd)
        # The taskbar's middle island in the middle or next to the menu (ticket H-1181).
        self.taskbar = w.Tile("format-justify-center-symbolic", _("Taskbar"), "", self.open_taskbar)
        self.network_row = self._row(self.wired, self.wifi)
        self.connections_row = self._row(self.vpn, self.bluetooth)
        self.display_row = self._row(self.dark, self.night)
        self.power_row = self._row(self.power_mode, self.accent)
        self.notifications_row = self._row(self.dnd, self.taskbar)

        self.card.show_all()
        self.brightness.hide()
        self.pill.hide()
        for signal_source in (self.b.audio, self.b.network, self.b.vpn, self.b.bluetooth, self.b.battery,
                              self.b.profiles, self.b.appearance, self.b.notifications, self.b.taskbar,
                              self.b.drives):
            signal_source.connect("changed", lambda *_: self.refresh())
        self.b.drives.connect("removed", self._drive_removed)
        self.b.drives.connect("writing", self._drive_writing)
        self.refresh()

    def _row(self, left: Gtk.Widget, right: Gtk.Widget) -> Gtk.Box:
        row = Gtk.Box(spacing=10, homogeneous=True)
        row.pack_start(left, True, True, 0)
        row.pack_start(right, True, True, 0)
        self.card.pack_start(row, False, False, 0)
        return row

    # -- showing ---------------------------------------------------------------------------------------------------

    def show_popup(self, anchor: tuple[int, int] | None, event_time: int = Gdk.CURRENT_TIME) -> None:
        """anchor: (right edge, top) of the panel button in screen coordinates."""

        self._anchor = anchor
        self.close_inline()
        self.b.vpn.refresh()
        self._read_brightness()
        self.b.ddc.read(self._show_ddc)
        self.refresh()
        self.show_all()
        self._apply_visibility()
        self._place()

    def hide_popup(self) -> None:
        super().hide_popup()
        if self.b.bluetooth.state.discovering:
            self.b.bluetooth.set_discovering(False)

    def _on_key(self, widget: Gtk.Widget, event: Gdk.EventKey) -> bool:
        if event.keyval == Gdk.KEY_Escape and self.inline.get_parent() is not None:
            self.close_inline()
            return True
        return super()._on_key(widget, event)

    def _run(self, command: str) -> None:
        self.hide_popup()
        spawn_named(command)

    def _screenshot(self) -> None:
        self.hide_popup()
        GLib.timeout_add(350, lambda: spawn_named("screenshot") and False)

    # -- the inline card ---------------------------------------------------------------------------------------------

    def toggle_inline(self, kind: str, icon_name: str, title: str, fill: Callable[[], None], anchor: Gtk.Widget,
                      on_open: Callable[[], object] | None = None) -> None:
        if self.inline.kind == kind and self.inline.get_parent() is not None:
            self.close_inline()
            return
        self.close_inline()
        self.inline.kind = kind
        self.inline.set_heading(icon_name, title)
        self.inline_fill = fill
        self.confirming = ""
        children = self.card.get_children()
        self.card.pack_start(self.inline, False, False, 0)
        self.card.reorder_child(self.inline, children.index(anchor) + 1)
        fill()
        self.inline.show_all()
        if on_open is not None:
            on_open()

    def close_inline(self) -> None:
        if self.inline.kind == "bluetooth" and self.b.bluetooth.state.discovering:
            self.b.bluetooth.set_discovering(False)
        if self.inline.get_parent() is not None:
            self.card.remove(self.inline)
        self.inline.clear()  # the next card starts empty
        self.inline.kind = ""
        self.inline_fill = None
        self.confirming = ""
        self.resize(1, 1)

    def _refill(self, kind: str | None = None) -> None:
        if self.inline_fill is not None and self.inline.get_parent() is not None \
                and (kind is None or self.inline.kind == kind):
            self.inline.clear()
            self.inline_fill()
            self.inline.show_all()

    # -- state -------------------------------------------------------------------------------------------------------

    def refresh(self) -> None:
        self._refresh_drives()
        self._refresh_audio()
        self._refresh_network()
        self._refresh_vpn()
        self._refresh_bluetooth()
        self._refresh_power()
        self._refresh_appearance()
        if self.inline.kind in ("output", "input", "wired", "wifi", "vpn", "bluetooth", "power-mode", "accent"):
            self._refill()

    def _apply_visibility(self) -> None:
        self.pill.set_visible(self.b.battery.battery.present)
        self.brightness.set_visible(self.b.brightness.available)
        self.drives.set_visible(bool(self.drive_keys))

    def _refresh_drives(self) -> None:
        drives = self.b.drives.drives
        keys = [(drive.key, drive.name, drive.busy) for drive in drives]
        if keys != self.drive_keys:
            self.drive_keys = keys
            for child in self.drive_rows.get_children():
                child.destroy()
            for drive in drives:
                self.drive_rows.pack_start(self._drive_row(drive), False, False, 0)
            self.drive_rows.show_all()
        self.drives.set_visible(bool(drives) and self.get_visible())

    def _drive_row(self, drive: object) -> Gtk.Box:
        """The drive's name, which opens it in Files, and the eject button, which removes it safely."""

        row = Gtk.Box(spacing=4)
        text = _("Safely removing %s…") % drive.name if drive.busy else drive.name
        opener = w.list_row(drive.icon, text, None, lambda d=drive: self._open_drive(d))
        opener.set_tooltip_text(_("Open %s in Files") % drive.name)
        opener.set_sensitive(not drive.busy)
        row.pack_start(opener, True, True, 0)
        eject = w.round_button("media-eject-symbolic", _("Safely remove %s") % drive.name,
                               lambda d=drive: self._remove_drive(d))
        eject.set_valign(Gtk.Align.CENTER)
        eject.set_sensitive(not drive.busy)
        row.pack_end(eject, False, False, 0)
        return row

    def _open_drive(self, drive: object) -> None:
        self.hide_popup()
        self.b.drives.open(drive.key, lambda uri: spawn(("xdg-open", uri)))

    def _remove_drive(self, drive: object) -> None:
        # As the menu of Windows' Safely Remove: it closes, and a notification tells when to unplug. Closed, the
        # popup lets go of the keyboard and pointer, which the dialog naming the programs that still use the drive
        # needs.
        self.hide_popup()
        self.b.drives.remove(drive.key)

    def _drive_writing(self, _backend: object, name: str) -> None:
        notify(_("CaramOS Control Center"), _("Writing the last files to %s") % name, _("Do not unplug it yet."),
               "drive-removable-media", transient=True)

    def _drive_removed(self, _backend: object, name: str, removed: bool, error: str) -> None:
        if removed:
            notify(_("CaramOS Control Center"), _("You can unplug %s now") % name, _("It was removed safely."),
                   "drive-removable-media")
        else:
            notify(_("CaramOS Control Center"), _("%s was not removed") % name,
                   _("Close the files and windows that use it, then try again.") + (f"\n{error}" if error else ""),
                   "drive-removable-media")

    def _refresh_audio(self) -> None:
        state = self.b.audio.state
        for kind, row in (("output", self.volume), ("input", self.mic)):
            device = state.device(kind)
            row.set_enabled(state.available and device is not None)
            if device is not None:
                row.set_value(device.volume)
                row.set_icon_name(volume_icon(device.volume, device.muted, microphone=kind == "input"))

    def _refresh_network(self) -> None:
        state = self.b.network.state
        wired = state.wired[0] if state.wired else None
        wired_connected = wired is not None and wired.state == 100
        self.wired.set_enabled(state.available and wired is not None)
        if not state.available:
            text = _("Unavailable")
        elif wired is None:
            text = _("No device")
        elif wired_connected and state.primary_iface == wired.iface:
            text = _("In use for Internet") if state.connectivity in (0, 4) else connectivity_text(state.connectivity)
        else:
            text = device_state_text(wired.state)
        self.wired.set_subtitle(text)
        self.wired.set_active(wired_connected)

        self.wifi.set_enabled(state.available and state.wifi_available and state.wifi_hardware_enabled)
        active = next((network for network in state.wifi_networks if network.active), None)
        if not state.available:
            text = _("Unavailable")
        elif not state.wifi_available:
            text = _("No device")
        elif not state.wifi_hardware_enabled:
            text = _("Blocked by hardware")
        elif not state.wifi_enabled:
            text = _("Off")
        else:
            text = active.ssid if active else _("On")
        self.wifi.set_subtitle(text)
        self.wifi.set_active(state.available and state.wifi_available and state.wifi_enabled
                             and state.wifi_hardware_enabled)
        self.wifi.set_loading(state.wifi_scanning)

    def _refresh_vpn(self) -> None:
        vpn = self.b.vpn
        active = [profile for profile in vpn.profiles if profile.active]
        if not vpn.loaded:
            text = _("Not connected")
        elif vpn.error:
            text = vpn.error
        elif len(active) == 1:
            text = active[0].name
        elif active:
            text = ngettext("%d active connection", "%d active connections", len(active)) % len(active)
        elif not vpn.profiles:
            text = _("No profiles")
        else:
            text = _("Not connected")
        self.vpn.set_subtitle(text)
        self.vpn.set_active(bool(active))

    def _refresh_bluetooth(self) -> None:
        state = self.b.bluetooth.state
        self.bluetooth.set_enabled(state.available)
        self.bluetooth.set_subtitle(_("On") if state.powered else _("Off") if state.available else _("Unavailable"))
        self.bluetooth.set_active(state.available and state.powered)

    def _refresh_power(self) -> None:
        battery = self.b.battery.battery
        self.pill.set_visible(battery.present and self.get_visible())
        if battery.present:
            text = battery_text(battery)
            self.pill.text.set_text(text)
            w.set_icon(self.pill.image, battery.icon)
            source = _("UPS") if battery.ups else _("Battery")
            self.pill.get_accessible().set_name(_("%s: %s") % (source, text))
        profiles = self.b.profiles.state
        if profiles.pending:
            text = _("Changing…")
        elif profiles.error and profiles.available:
            text = _("Change failed")
        elif profiles.loading:
            text = _("Loading…")
        elif profiles.available:
            text = profile_label(profiles.active)
            if profiles.degraded and profiles.active == "performance":
                text = _("%s · limited") % text
        else:
            text = _("Unavailable")
        self.power_mode.set_subtitle(text)
        self.power_mode.set_enabled(profiles.available or profiles.loading)
        self.power_mode.set_active(bool(profiles.available and profiles.active))
        self.power_mode.set_loading(bool(profiles.pending) or profiles.loading)

    def _refresh_appearance(self) -> None:
        appearance = self.b.appearance
        self.dark.set_enabled(appearance.available)
        dark = appearance.is_dark()
        self.dark.set_subtitle(_("Enabled") if dark else _("Disabled") if appearance.available else _("Unavailable"))
        self.dark.set_active(dark)
        w.set_class(self, "dark", dark)
        night = self.b.night_light.enabled
        self.night.set_subtitle(_("Enabled") if night else _("Disabled"))
        self.night.set_active(night)
        self.accent.set_subtitle(self._accent_name())
        notifications = self.b.notifications
        self.dnd.set_enabled(notifications.available)
        quiet = notifications.quiet
        self.dnd.set_subtitle(_("Notifications hidden") if quiet else _("Disabled") if notifications.available
                              else _("Unavailable"))
        self.dnd.set_active(quiet)
        place = self.b.taskbar.alignment
        self.taskbar.set_enabled(place is not None)
        self.taskbar.set_subtitle(_("Left") if place == LEFT else _("Centre") if place == CENTER else _("Unavailable"))
        self.taskbar.set_icon_name("format-justify-left-symbolic" if place == LEFT else "format-justify-center-symbolic")

    def _read_brightness(self) -> None:
        def got(fraction: float | None) -> None:
            self.brightness.set_visible(fraction is not None and self.get_visible())
            if fraction is not None:
                self.brightness.set_value(fraction)

        self.b.brightness.read(got)

    def _show_ddc(self, displays: list[dict[str, object]]) -> None:
        if [display["bus"] for display in displays] != list(self.ddc_rows):
            for row in self.ddc_rows.values():
                row.destroy()
            self.ddc_rows = {}
            for display in displays:
                # Translators: accessible name of the brightness slider of an external monitor; %s is its model.
                name = _("Brightness of %s") % display["name"] if display["name"] else _("Monitor brightness")
                row = w.SliderRow("video-display-symbolic", name, lambda value, d=display: self.b.ddc.set(d, value))
                self.ddc_rows[int(display["bus"])] = row
                self.ddc_box.pack_start(row, False, False, 0)
            self.ddc_box.show_all()
        for display in displays:
            row = self.ddc_rows.get(int(display["bus"]))
            if row is not None and not row.dragging and not self.b.ddc.busy(int(display["bus"])):
                row.set_value(float(display["fraction"]))

    # -- tiles -------------------------------------------------------------------------------------------------------

    def toggle_wifi(self) -> None:
        state = self.b.network.state
        if not (state.available and state.wifi_available and state.wifi_hardware_enabled):
            self._run("networkSettings")
            return
        self.wifi.set_subtitle(_("Off") if state.wifi_enabled else _("On"))
        self.wifi.set_loading(True)
        self.b.network.set_wifi_enabled(not state.wifi_enabled)

    def toggle_vpn(self) -> None:
        vpn = self.b.vpn
        if not vpn.available:
            self._run("networkSettings")
            return
        active = [profile for profile in vpn.profiles if profile.active]
        if len(active) == 1:
            self.vpn.set_loading(True)
            vpn.set_active(active[0], False)
            return
        self.toggle_inline("vpn", "network-vpn-symbolic", _("VPN"), self.fill_vpn, self.connections_row, vpn.refresh)

    def toggle_bluetooth(self) -> None:
        state = self.b.bluetooth.state
        if not state.available:
            self._run("bluetoothSettings")
            return
        self.bluetooth.set_subtitle(_("Off") if state.powered else _("On"))
        self.bluetooth.set_loading(True)
        self.b.bluetooth.set_powered(not state.powered)
        GLib.timeout_add(1500, lambda: self.bluetooth.set_loading(False) or False)

    def toggle_dark(self) -> None:
        appearance = self.b.appearance
        dark = not appearance.is_dark()
        self.dark.set_subtitle(_("Enabled") if dark else _("Disabled"))
        self.dark.set_active(dark)
        self.dark.set_loading(True)
        appearance.set_dark(dark)
        GLib.timeout_add(1500, self._appearance_settled)

    def _appearance_settled(self) -> bool:
        self.dark.set_loading(False)
        self.refresh()
        return False

    def toggle_night(self) -> None:
        self.b.night_light.set_enabled(not self.b.night_light.enabled)
        self.refresh()

    def toggle_dnd(self) -> None:
        self.b.notifications.set_quiet(not self.b.notifications.quiet)
        self.refresh()

    def open_taskbar(self) -> None:
        self.toggle_inline("taskbar", "format-justify-center-symbolic", _("Taskbar"), self.fill_taskbar,
                           self.notifications_row)

    def set_taskbar(self, place: str) -> None:
        if place == self.b.taskbar.alignment:
            return
        # xfce4-panel restarts to move the dock, and takes this popup with it.
        self.hide_popup()
        self.b.taskbar.set_alignment(place)

    def open_power_mode(self) -> None:
        self.toggle_inline("power-mode", "preferences-system-power-symbolic", _("Power mode"), self.fill_power_mode,
                           self.power_row)

    # -- inline lists ------------------------------------------------------------------------------------------------

    def fill_audio(self, kind: str) -> None:
        state = self.b.audio.state
        devices = state.outputs if kind == "output" else state.inputs
        if not devices:
            self.inline.append(w.empty_text(_("No sound devices")))
        for device in devices:
            self.inline.append(w.list_row("audio-speakers-symbolic" if kind == "output"
                                          else "audio-input-microphone-symbolic", device.description,
                                          "object-select-symbolic" if device.default else None,
                                          lambda d=device: self.b.audio.set_default(kind, d.name)))
        appearance = self.b.appearance
        if kind == "output" and appearance.has_volume_step:
            def pick(step: int) -> None:
                appearance.set_volume_step(step)
                self._refill("output")

            self.inline.append(w.separator())
            self.inline.append(w.step_chooser(_("Volume step"), appearance.VOLUME_STEPS, appearance.volume_step(), pick))
        self.inline.append(w.separator())
        self.inline.append(w.list_row("preferences-system-symbolic", _("Open sound settings"), None,
                                      lambda: self._run("soundSettings")))

    def fill_wired(self) -> None:
        state = self.b.network.state
        if not state.wired:
            self.inline.append(w.empty_text(_("No wired network devices")))
        for device in state.wired:
            status = device_state_text(device.state)
            if device.state == 100 and device.iface == state.primary_iface:
                status = _("%s · default route") % status
            rows = [(_("Status"), status), (_("Profile"), device.connection),
                    (_("Link"), _("Signal detected") if device.carrier else _("No signal")),
                    (_("Speed"), f"{device.speed} Mb/s" if device.speed else ""), (_("Address"), device.address),
                    (_("Gateway"), device.gateway), (_("DNS"), ", ".join(device.dns))]
            grid = Gtk.Grid(column_spacing=10, row_spacing=3)
            grid.set_margin_start(6)
            grid.set_margin_end(6)
            for line, (key, value) in enumerate((k, v) for k, v in rows if v):
                grid.attach(w.label(key, "caramos-cc-detail-key", ellipsize=False), 0, line, 1, 1)
                value_label = w.label(value, "caramos-cc-detail-value")
                value_label.set_selectable(True)
                value_label.set_hexpand(True)
                grid.attach(value_label, 1, line, 1, 1)
            self.inline.append(grid)
        if state.connectivity == 3:
            self.inline.append(w.list_row("web-browser-symbolic", _("Open network sign-in page"), None,
                                          lambda: self._open_portal()))
        self.inline.append(w.separator())
        self.inline.append(w.list_row("preferences-system-symbolic", _("Open network settings"), None,
                                      lambda: self._run("networkSettings")))

    def _open_portal(self) -> None:
        self.hide_popup()
        Gtk.show_uri_on_window(None, "http://nmcheck.gnome.org/", Gdk.CURRENT_TIME)

    def fill_wifi(self) -> None:
        state = self.b.network.state
        if not state.wifi_available:
            self.inline.append(w.empty_text(_("No Wi‑Fi device")))
        elif not state.wifi_hardware_enabled:
            self.inline.append(w.empty_text(_("Wi‑Fi is blocked by hardware")))
        elif not state.wifi_enabled:
            self.inline.append(w.empty_text(_("Wi‑Fi is off")))
        elif not state.wifi_networks:
            self.inline.append(w.empty_text(_("Searching for Wi‑Fi networks…") if state.wifi_scanning
                                            else _("No Wi‑Fi networks found")))
        else:
            for network in state.wifi_networks[:WIFI_LIST_LIMIT]:
                self.inline.append(w.list_row(wifi_signal_icon(network.strength, network.secure), network.ssid,
                                              "object-select-symbolic" if network.active else None,
                                              lambda n=network: self._join_wifi(n)))
        self.inline.append(w.separator())
        if state.wifi_available and state.wifi_enabled:
            self.inline.append(w.list_row("view-refresh-symbolic", _("Scan for Wi‑Fi networks again"), None,
                                          self.b.network.request_scan))
        self.inline.append(w.list_row("preferences-system-symbolic", _("Open network settings"), None,
                                      lambda: self._run("networkSettings")))

    def _join_wifi(self, network: object) -> None:
        self.wifi.set_loading(True)
        if not self.b.network.activate_wifi(network):
            self._run("networkSettings")
        elif not network.active and not network.saved and network.secure:
            # NetworkManager asks for the password in its own window: get out of its way.
            self.hide_popup()

    def fill_vpn(self) -> None:
        vpn = self.b.vpn
        if not vpn.loaded:
            self.inline.append(w.empty_text(_("Reading VPN profiles…")))
        elif not vpn.available:
            self.inline.append(w.empty_text(vpn.error or _("NetworkManager unavailable")))
            self.inline.append(w.list_row("view-refresh-symbolic", _("Try again"), None, vpn.refresh))
        elif not vpn.profiles:
            self.inline.append(w.empty_text(_("No VPN profiles")))
        else:
            if vpn.error:
                self.inline.append(w.empty_text(vpn.error))
            for profile in vpn.profiles[:VPN_LIST_LIMIT]:
                name = profile.name if profile.kind != "wireguard" else f"{profile.name} · {_('WireGuard')}"
                self.inline.append(w.list_row("network-vpn-symbolic", name,
                                              "object-select-symbolic" if profile.active else None,
                                              lambda p=profile: vpn.set_active(p, not p.active)))
        self.inline.append(w.separator())
        self.inline.append(w.list_row("preferences-system-symbolic", _("Open VPN settings"), None,
                                      lambda: self._run("networkSettings")))

    def fill_bluetooth(self) -> None:
        state = self.b.bluetooth.state
        if state.discovering:
            self.inline.append(w.empty_text(_("Searching for Bluetooth devices…")))
        if state.devices:
            for device in state.devices:
                text = device.name if device.battery is None else f"{device.name} · {device.battery}%"
                self.inline.append(w.list_row("bluetooth-symbolic", text,
                                              "object-select-symbolic" if device.connected else None,
                                              lambda d=device: self.b.bluetooth.toggle_device(d)))
        elif not state.discovering:
            self.inline.append(w.empty_text(_("No available or connected devices") if state.available
                                            else _("BlueZ unavailable; open Bluetooth settings")))
        self.inline.append(w.separator())
        if state.available:
            self.inline.append(w.list_row("media-playback-stop-symbolic" if state.discovering
                                          else "view-refresh-symbolic",
                                          _("Stop searching") if state.discovering else _("Search for new devices"),
                                          None, lambda: self.b.bluetooth.set_discovering(not state.discovering)))
        self.inline.append(w.list_row("preferences-system-symbolic", _("Bluetooth settings"), None,
                                      lambda: self._run("bluetoothSettings")))

    def fill_power_mode(self) -> None:
        state = self.b.profiles.state
        if state.loading:
            self.inline.append(w.empty_text(_("Loading power modes…")))
        elif not state.available:
            self.inline.append(w.empty_text(_("Power mode service unavailable")))
        elif not state.profiles:
            self.inline.append(w.empty_text(_("No power modes")))
        if state.error:
            self.inline.append(w.empty_text(_("Could not change the power mode")))
        for profile in state.profiles:
            self.inline.append(w.list_row(PROFILE_ICONS.get(profile, "preferences-system-power-symbolic"),
                                          profile_label(profile),
                                          "object-select-symbolic" if profile == (state.pending or state.active)
                                          else None, lambda p=profile: self.b.profiles.set_profile(p)))
        self.inline.append(w.separator())
        self.inline.append(w.list_row("preferences-system-symbolic", _("Power settings"), None,
                                      lambda: self._run("powerSettings")))

    def fill_taskbar(self) -> None:
        place = self.b.taskbar.alignment
        if place is None:
            # Translators: the taskbar's panels were changed, so the Taskbar choices cannot move the apps' island.
            self.inline.append(w.empty_text(_("The taskbar was changed in the panel settings")))
            return
        for choice, icon_name, text in ((CENTER, "format-justify-center-symbolic", _("Centre")),
                                         (LEFT, "format-justify-left-symbolic", _("Left"))):
            self.inline.append(w.list_row(icon_name, text, "object-select-symbolic" if choice == place else None,
                                          lambda c=choice: self.set_taskbar(c)))
        self.inline.append(w.empty_text(_("The taskbar reloads for a second or two.")))

    def fill_power(self) -> None:
        if self.confirming:
            self._fill_confirm(self.confirming)
            return
        state = self.b.session_state
        if not state.available:
            self.inline.append(w.empty_text(_("Session service unavailable")))
            return
        for action, icon_name, text, capable in (
                ("suspend", "media-playback-pause-symbolic", _("Suspend"), state.can_suspend),
                ("hibernate", "weather-clear-night-symbolic", _("Hibernate"), state.can_hibernate),
                ("restart", "view-refresh-symbolic", _("Restart…"), state.can_restart),
                ("shutdown", "system-shutdown-symbolic", _("Shut down…"), state.can_shutdown)):
            if capable:
                self.inline.append(w.list_row(icon_name, text, None, lambda a=action: self._session(a)))
        self.inline.append(w.separator())
        for action, icon_name, text, capable in (
                ("logout", "system-log-out-symbolic", _("Log out…"), state.can_logout),
                ("switchUser", "system-users-symbolic", _("Switch user…"), state.can_switch_user)):
            if capable:
                self.inline.append(w.list_row(icon_name, text, None, lambda a=action: self._session(a)))

    def _session(self, action: str) -> None:
        if action in session.CONFIRM:
            self.confirming = action
            self._refill("power")
            return
        self.hide_popup()
        session.run(action)

    def _fill_confirm(self, action: str) -> None:
        question, verb = {
            "restart": (_("Restart the computer?"), _("Restart")),
            "shutdown": (_("Shut down the computer?"), _("Shut down")),
            "logout": (_("Log out of CaramOS?"), _("Log out")),
        }[action]
        self.inline.append(w.label(question, "caramos-cc-dialog-question", ellipsize=False))
        buttons = Gtk.Box(spacing=10, homogeneous=True)
        cancel = w.styled(Gtk.Button(label=_("Cancel")), "caramos-cc-dialog-btn")
        cancel.connect("clicked", lambda *_: self._cancel_confirm())
        go = w.styled(Gtk.Button(label=verb), "caramos-cc-dialog-btn", "caramos-cc-dialog-btn-primary")
        go.connect("clicked", lambda *_: self._confirmed(action))
        buttons.pack_start(cancel, True, True, 0)
        buttons.pack_start(go, True, True, 0)
        self.inline.append(buttons)
        GLib.idle_add(go.grab_focus)

    def _cancel_confirm(self) -> None:
        self.confirming = ""
        self._refill("power")

    def _confirmed(self, action: str) -> None:
        self.hide_popup()
        session.run(action)

    def fill_accent(self) -> None:
        appearance = self.b.appearance
        choice = appearance.accent_choice()
        themed = appearance.accent_for_mode()
        auto = choice not in dict(ACCENTS) and choice != "custom"
        self.inline.append(self._accent_row(themed, _("Follow the theme"), auto, lambda: appearance.set_accent("auto")))
        swatches = Gtk.Box(spacing=6, homogeneous=True)
        swatches.set_margin_top(4)
        swatches.set_margin_bottom(4)
        for key, color in ACCENTS:
            button = w.styled(Gtk.Button(), "caramos-cc-accent-swatch")
            if key == choice:
                w.styled(button, "selected")
            button.set_tooltip_text(ACCENT_NAMES()[key])
            button.get_accessible().set_name(ACCENT_NAMES()[key])
            self._paint(button, color)
            button.connect("clicked", lambda _b, k=key: appearance.set_accent(k))
            swatches.pack_start(button, True, False, 0)
        self.inline.append(swatches)
        custom = appearance.accent_settings.get_string("custom-accent") if appearance.accent_settings else ""
        self.inline.append(self._accent_row(custom if len(custom) == 7 else "#888888", _("Other colour…"),
                                            choice == "custom", lambda: self._run("accentPicker")))

    def _accent_row(self, color: str, text: str, selected: bool, on_click: Callable[[], None]) -> Gtk.Button:
        button = w.styled(Gtk.Button(), "caramos-cc-list-row")
        box = Gtk.Box(spacing=8)
        dot = w.styled(Gtk.Box(), "caramos-cc-accent-dot")
        dot.set_size_request(14, 14)
        dot.set_valign(Gtk.Align.CENTER)
        self._paint(dot, color, radius=True)
        box.pack_start(dot, False, False, 4)
        box.pack_start(w.label(text, "caramos-cc-list-label"), True, True, 0)
        if selected:
            box.pack_end(w.icon("object-select-symbolic", 12, "caramos-cc-row-trail-icon"), False, False, 0)
        button.add(box)
        button.connect("clicked", lambda *_: on_click())
        return button

    @staticmethod
    def _paint(widget: Gtk.Widget, color: str, radius: bool = False) -> None:
        provider = Gtk.CssProvider()
        css = f"* {{ background-color: {color};{' border-radius: 999px;' if radius else ''} }}"
        provider.load_from_data(css.encode())
        widget.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)

    def _accent_name(self) -> str:
        appearance = self.b.appearance
        choice = appearance.accent_choice()
        names = ACCENT_NAMES()
        if choice == "custom":
            return _("Custom colour")
        if choice in names:
            return names[choice]
        themed_key = next((key for key, color in ACCENTS if color == appearance.accent_for_mode()), "orange")
        return _("%s · from the theme") % names[themed_key]


def ACCENT_NAMES() -> dict[str, str]:  # noqa: N802 - a table, translated when asked for
    return {"orange": _("Orange"), "blue": _("Blue"), "teal": _("Teal"), "green": _("Green"),
            "purple": _("Purple"), "pink": _("Pink"), "red": _("Red"), "graphite": _("Graphite")}


class Backends:
    def __init__(self) -> None:
        self.audio = AudioBackend()
        self.network = NetworkBackend()
        self.vpn = VpnBackend()
        self.bluetooth = BluetoothBackend()
        self.battery = BatteryBackend()
        self.profiles = ProfilesBackend()
        self.appearance = Appearance()
        self.night_light = NightLight()
        self.notifications = Notifications()
        self.taskbar = Taskbar()
        self.panel_clock = PanelClock()
        self.brightness = Brightness()
        self.ddc = Ddc()
        self.drives = DrivesBackend()
        self.session_state = session.read_state()

"""Battery (UPower's display device) and power modes (power-profiles-daemon), as in the Cinnamon applet."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from gi.repository import Gio, GLib, GObject

from ..i18n import _


def upower():
    import gi

    gi.require_version("UPowerGlib", "1.0")
    from gi.repository import UPowerGlib

    return UPowerGlib

LOG = logging.getLogger("caramos-control-center")

PROFILE_ORDER = ("performance", "balanced", "power-saver")
PROFILE_ICONS = {"performance": "power-profile-performance-symbolic",
                 "balanced": "power-profile-balanced-symbolic",
                 "power-saver": "power-profile-power-saver-symbolic"}
PROFILE_SERVICES = (
    ("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles",
     "org.freedesktop.UPower.PowerProfiles"),
    ("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles", "net.hadess.PowerProfiles"),
)
ERROR_SECONDS = 4


def profile_label(profile: str) -> str:
    return {"performance": _("Performance"), "balanced": _("Balanced"),
            "power-saver": _("Power saver")}.get(profile, profile)


@dataclass
class Battery:
    present: bool = False
    percentage: float = 0.0
    charging: bool = False
    seconds: int = 0  # to full while charging, to empty otherwise
    icon: str = "battery-full-symbolic"
    ups: bool = False


def estimate_text(seconds: int) -> str:
    if not seconds or seconds < 60:
        return ""
    minutes = round(seconds / 60)
    hours = minutes // 60
    return _("%dh %dm") % (hours, minutes % 60) if hours else _("%dm") % minutes


def battery_text(battery: Battery) -> str:
    estimate = estimate_text(battery.seconds)
    percent = f"{round(battery.percentage)}%"
    return f"{percent} · {estimate}" if estimate else percent


class BatteryBackend(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self) -> None:
        super().__init__()
        self.battery = Battery()
        self._device = None
        try:
            self._up = upower()
            self._device = self._up.Client.new().get_display_device()
        except (GLib.Error, ImportError, ValueError) as exc:
            LOG.info("UPower: %s", exc)
        if self._device is not None:
            self._device.connect("notify", lambda *_: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        device = self._device
        if device is None:
            self.battery = Battery()
        else:
            up = self._up
            kind = device.props.kind
            state = device.props.state
            charging = state in (up.DeviceState.CHARGING, up.DeviceState.PENDING_CHARGE)
            self.battery = Battery(
                present=bool(device.props.is_present) and kind in (up.DeviceKind.BATTERY, up.DeviceKind.UPS),
                percentage=float(device.props.percentage),
                charging=charging,
                seconds=int(device.props.time_to_full if charging else device.props.time_to_empty),
                icon=device.props.icon_name or "battery-full-symbolic",
                ups=kind == up.DeviceKind.UPS,
            )
        self.emit("changed")


@dataclass
class ProfilesState:
    available: bool = False
    loading: bool = True
    active: str = ""
    profiles: list[str] = field(default_factory=list)
    degraded: str = ""
    pending: str = ""
    error: bool = False


class ProfilesBackend(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self) -> None:
        super().__init__()
        self.state = ProfilesState()
        self._proxy: Gio.DBusProxy | None = None
        self._try(0)

    def _try(self, index: int) -> None:
        if index >= len(PROFILE_SERVICES):
            self.state = ProfilesState(available=False, loading=False)
            self.emit("changed")
            return
        name, path, interface = PROFILE_SERVICES[index]

        def ready(_source: object, result: Gio.AsyncResult) -> None:
            try:
                proxy = Gio.DBusProxy.new_for_bus_finish(result)
            except GLib.Error:
                self._try(index + 1)
                return
            if proxy.get_name_owner() is None:
                self._try(index + 1)
                return
            self._proxy = proxy
            proxy.connect("g-properties-changed", lambda *_: self.refresh())
            self.refresh()

        Gio.DBusProxy.new_for_bus(Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None, name, path, interface, None,
                                  ready)

    def refresh(self) -> None:
        proxy = self._proxy
        if proxy is None:
            return
        active = proxy.get_cached_property("ActiveProfile")
        profiles = proxy.get_cached_property("Profiles")
        degraded = proxy.get_cached_property("PerformanceDegraded")
        names = [entry.get("Profile") for entry in (profiles.unpack() if profiles is not None else [])]
        self.state = ProfilesState(available=active is not None, loading=False,
                                   active=active.unpack() if active is not None else "",
                                   profiles=[name for name in PROFILE_ORDER if name in names],
                                   degraded=degraded.unpack() if degraded is not None else "",
                                   pending="", error=self.state.error)
        self.emit("changed")

    def set_profile(self, profile: str) -> None:
        proxy = self._proxy
        if proxy is None or profile == self.state.active:
            return
        self.state.pending = profile
        self.state.error = False
        self.emit("changed")

        def done(connection: Gio.DBusConnection, result: Gio.AsyncResult) -> None:
            try:
                connection.call_finish(result)
                self.state.error = False
            except GLib.Error as exc:
                LOG.info("power profile: %s", exc.message)
                self.state.error = True
                GLib.timeout_add_seconds(ERROR_SECONDS, self._clear_error)
            self.state.pending = ""
            self.refresh()

        proxy.get_connection().call(proxy.get_name(), proxy.get_object_path(), "org.freedesktop.DBus.Properties",
                                    "Set", GLib.Variant("(ssv)", (proxy.get_interface_name(), "ActiveProfile",
                                                                  GLib.Variant("s", profile))),
                                    None, Gio.DBusCallFlags.NONE, 10000, None, done)

    def _clear_error(self) -> bool:
        self.state.error = False
        self.emit("changed")
        return False

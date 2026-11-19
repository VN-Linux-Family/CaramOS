"""Wired network, Wi-Fi and VPN through NetworkManager, as the Cinnamon applet does.

One difference: a protected Wi-Fi network that was never used is joined here directly, and NetworkManager asks for its
password through nm-applet's dialog. Cinnamon opens its network settings for that; Xfce has no such page, and
nm-applet keeps running on CaramOS Xfce for exactly this (only its tray icon is hidden).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from gi.repository import GLib, GObject

from ..i18n import _
from ..util import run_async


def nm():
    """NetworkManager's GObject library, loaded when first needed (the tests of the parsers do without it)."""

    import gi

    gi.require_version("NM", "1.0")
    from gi.repository import NM

    return NM

LOG = logging.getLogger("caramos-control-center")
CHANGE_DELAY_MS = 150

def device_state_text(state: int) -> str:
    """NetworkManager's NMDeviceState, in the Cinnamon applet's words."""

    texts = {
        0: _("Unknown"), 10: _("Unmanaged"), 20: _("Unavailable"), 30: _("Disconnected"), 40: _("Preparing"),
        50: _("Configuring"), 60: _("Authentication required"), 70: _("Getting network address"),
        80: _("Checking connection"), 90: _("Finishing"), 100: _("Connected"), 110: _("Disconnecting"),
        120: _("Connection failed"),
    }
    return texts.get(int(state), _("Unknown"))


def connectivity_text(connectivity: int) -> str:
    """NetworkManager's NMConnectivityState."""

    texts = {0: _("Unknown"), 1: _("No network"), 2: _("Local network only"), 3: _("Network sign-in required"),
             4: _("Internet access")}
    return texts.get(int(connectivity), _("Unknown"))


def wifi_signal_icon(strength: int, secure: bool) -> str:
    level = "excellent" if strength >= 75 else "good" if strength >= 55 else "ok" if strength >= 35 else "weak"
    return f"network-wireless-signal-{level}{'-secure' if secure else ''}-symbolic"


@dataclass
class WiredDevice:
    iface: str
    state: int
    connection: str = ""
    carrier: bool = False
    speed: int = 0  # Mb/s
    address: str = ""
    gateway: str = ""
    dns: list[str] = field(default_factory=list)


@dataclass
class WifiNetwork:
    ssid: str
    strength: int
    secure: bool
    enterprise: bool
    active: bool
    saved: bool
    best_ap: object = None
    connections: list = field(default_factory=list)


@dataclass
class NetworkState:
    available: bool = False
    connectivity: int = 0
    primary_type: str = ""  # "ethernet", "wifi", another NetworkManager type, or "" when offline
    primary_iface: str = ""
    wired: list[WiredDevice] = field(default_factory=list)
    wifi_available: bool = False
    wifi_hardware_enabled: bool = True
    wifi_enabled: bool = False
    wifi_scanning: bool = False
    wifi_networks: list[WifiNetwork] = field(default_factory=list)


KEY_MGMT_802_1X = 0x200  # NM80211ApSecurityFlags.KEY_MGMT_802_1X
PRIVACY = 0x1  # NM80211ApFlags.PRIVACY


def ap_security(ap: object) -> tuple[bool, bool]:
    """(secure, enterprise) of an access point."""

    wpa, rsn = int(ap.get_wpa_flags()), int(ap.get_rsn_flags())
    if (wpa | rsn) & KEY_MGMT_802_1X:
        return True, True
    if rsn or wpa or int(ap.get_flags()) & PRIVACY:
        return True, False
    return False, False


def ssid_text(ap: object) -> str:
    ssid = ap.get_ssid()
    if ssid is None:
        return ""
    try:
        return nm().utils_ssid_to_utf8(ssid.get_data()) or ""
    except (TypeError, ValueError):
        return ""


class NetworkBackend(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self) -> None:
        super().__init__()
        self.state = NetworkState()
        self.client = None
        self._watched: list[tuple[GObject.Object, int]] = []
        self._change_id = 0
        try:
            self.client = nm().Client.new(None)
        except (GLib.Error, ImportError, ValueError) as exc:
            LOG.warning("NetworkManager: %s", exc)
            return
        for signal in ("notify::state", "notify::connectivity", "notify::wireless-enabled",
                       "notify::wireless-hardware-enabled", "notify::primary-connection", "device-added",
                       "device-removed", "active-connection-added", "active-connection-removed",
                       "connection-added", "connection-removed", "notify::nm-running"):
            self.client.connect(signal, self._on_change)
        self.refresh()

    def _on_change(self, *_args: object) -> None:
        if not self._change_id:
            self._change_id = GLib.timeout_add(CHANGE_DELAY_MS, self._changed_now)

    def _changed_now(self) -> bool:
        self._change_id = 0
        self.refresh()
        return False

    def _watch_devices(self, devices: list) -> None:
        for obj, handler in self._watched:
            try:
                obj.disconnect(handler)
            except TypeError:
                pass
        self._watched = []
        for device in devices:
            self._watched.append((device, device.connect("state-changed", self._on_change)))
            if isinstance(device, nm().DeviceWifi):
                for signal in ("access-point-added", "access-point-removed", "notify::active-access-point",
                               "notify::last-scan"):
                    self._watched.append((device, device.connect(signal, self._on_change)))

    # -- state -----------------------------------------------------------------------------------------------------

    def refresh(self) -> None:
        client = self.client
        if client is None or not client.get_nm_running():
            self.state = NetworkState(available=False)
            self.emit("changed")
            return
        devices = [device for device in client.get_devices() or [] if device.get_managed()]
        self._watch_devices(devices)
        NM = nm()
        primary = client.get_primary_connection()
        primary_type, primary_iface = "", ""
        if primary is not None and primary.get_state() == NM.ActiveConnectionState.ACTIVATED:
            kind = primary.get_connection_type() or ""
            primary_type = {"802-3-ethernet": "ethernet", "802-11-wireless": "wifi"}.get(kind, kind)
            primary_devices = primary.get_devices() or []
            primary_iface = primary_devices[0].get_iface() if primary_devices else ""
        wifi_device = next((device for device in devices if isinstance(device, NM.DeviceWifi)), None)
        old_scanning = self.state.wifi_scanning
        self.state = NetworkState(
            available=True,
            connectivity=int(client.get_connectivity()),
            primary_type=primary_type,
            primary_iface=primary_iface,
            wired=[self._wired(device) for device in devices if isinstance(device, NM.DeviceEthernet)],
            wifi_available=wifi_device is not None,
            wifi_hardware_enabled=client.wireless_hardware_get_enabled(),
            wifi_enabled=client.wireless_get_enabled(),
            wifi_scanning=old_scanning,
            wifi_networks=self._networks(wifi_device) if wifi_device is not None else [],
        )
        self.emit("changed")

    @staticmethod
    def _wired(device: object) -> WiredDevice:
        active = device.get_active_connection()
        ip4 = device.get_ip4_config()
        address = gateway = ""
        dns: list[str] = []
        if ip4 is not None:
            addresses = ip4.get_addresses() or []
            if addresses:
                address = f"{addresses[0].get_address()}/{addresses[0].get_prefix()}"
            gateway = ip4.get_gateway() or ""
            dns = list(ip4.get_nameservers() or [])
        return WiredDevice(iface=device.get_iface() or "", state=int(device.get_state()),
                           connection=active.get_id() if active is not None else "",
                           carrier=bool(device.get_carrier()), speed=int(device.get_speed() or 0),
                           address=address, gateway=gateway, dns=dns)

    def _networks(self, device: object) -> list[WifiNetwork]:
        active_ap = device.get_active_access_point()
        connections = self.client.get_connections() or []
        grouped: dict[tuple[str, bool], WifiNetwork] = {}
        for ap in device.get_access_points() or []:
            ssid = ssid_text(ap)
            if not ssid:
                continue
            secure, enterprise = ap_security(ap)
            key = (ssid, secure)
            network = grouped.get(key)
            if network is None:
                network = grouped[key] = WifiNetwork(ssid=ssid, strength=0, secure=secure, enterprise=enterprise,
                                                     active=False, saved=False)
            if ap == active_ap:
                network.active = True
            strength = int(ap.get_strength())
            if network.best_ap is None or ap == active_ap or (strength > network.strength and not network.active):
                network.best_ap, network.strength = ap, strength
            for connection in connections:
                if connection not in network.connections and ap.connection_valid(connection):
                    network.connections.append(connection)
        networks = list(grouped.values())
        for network in networks:
            network.saved = bool(network.connections)
        networks.sort(key=lambda n: (not n.active, not n.saved, -n.strength, n.ssid.lower()))
        return networks

    # -- actions ---------------------------------------------------------------------------------------------------

    def set_wifi_enabled(self, enabled: bool) -> bool:
        if self.client is None or not self.state.wifi_hardware_enabled:
            return False
        NM = nm()
        self.client.dbus_set_property(NM.DBUS_PATH, NM.DBUS_INTERFACE, "WirelessEnabled",
                                      GLib.Variant("b", enabled), -1, None, None, None)
        return True

    def _wifi_device(self) -> object | None:
        if self.client is None:
            return None
        wifi = nm().DeviceWifi
        return next((d for d in self.client.get_devices() or [] if isinstance(d, wifi) and d.get_managed()), None)

    def request_scan(self) -> bool:
        device = self._wifi_device()
        if device is None or not self.state.wifi_enabled:
            return False
        self.state.wifi_scanning = True
        self.emit("changed")

        def done(dev: object, result: object) -> None:
            try:
                dev.request_scan_finish(result)
            except GLib.Error:
                pass
            GLib.timeout_add_seconds(4, self._scan_over)

        device.request_scan_async(None, done)
        return True

    def _scan_over(self) -> bool:
        self.state.wifi_scanning = False
        self.refresh()
        return False

    def activate_wifi(self, network: WifiNetwork) -> bool:
        """Join a network (a saved profile first; else a new one, whose password NetworkManager asks for), or leave
        the active one."""

        device = self._wifi_device()
        if device is None or network.best_ap is None:
            return False
        if network.active:
            active = device.get_active_connection()
            if active is None:
                return False
            self.client.deactivate_connection_async(active, None, lambda c, r: self._finish(c.deactivate_connection_finish, r))
            return True
        if network.connections:
            self.client.activate_connection_async(network.connections[0], device, network.best_ap.get_path(), None,
                                                  lambda c, r: self._finish(c.activate_connection_finish, r))
            return True
        self.client.add_and_activate_connection_async(None, device, network.best_ap.get_path(), None,
                                                      lambda c, r: self._finish(c.add_and_activate_connection_finish, r))
        return True

    def _finish(self, finish, result: object) -> None:
        try:
            finish(result)
        except GLib.Error as exc:
            LOG.info("NetworkManager: %s", exc.message)
        self.refresh()


@dataclass
class VpnProfile:
    uuid: str
    name: str
    kind: str  # "vpn" or "wireguard"
    active: bool


def split_nmcli(line: str) -> list[str]:
    """The fields of one `nmcli -t --escape yes` line (':' separates, '\\:' and '\\\\' are escapes)."""

    fields, current, escaped = [], [], False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields


def parse_vpn_profiles(saved: str, active: str) -> list[VpnProfile]:
    def kind_of(value: str) -> str:
        value = value.lower()
        return value if value in ("vpn", "wireguard") else ""

    active_uuids = {fields[0] for fields in map(split_nmcli, active.splitlines())
                    if len(fields) >= 3 and kind_of(fields[2])}
    profiles = []
    for fields in map(split_nmcli, saved.splitlines()):
        if len(fields) >= 3 and fields[0] and kind_of(fields[2]):
            profiles.append(VpnProfile(uuid=fields[0], name=fields[1] or _("VPN"), kind=kind_of(fields[2]),
                                       active=fields[0] in active_uuids))
    return profiles


class VpnBackend(GObject.Object):
    """VPN profiles through nmcli, as the Cinnamon applet reads them."""

    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self) -> None:
        super().__init__()
        self.available = True
        self.loaded = False
        self.error = ""
        self.profiles: list[VpnProfile] = []
        self._busy = False

    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True
        fields = ["nmcli", "-t", "--escape", "yes", "-f", "UUID,NAME,TYPE", "connection", "show"]

        def got_active(ok: bool, active: str, _err: str) -> None:
            def got_saved(ok2: bool, saved: str, _err2: str) -> None:
                self._busy = False
                self.loaded = True
                self.available = ok and ok2
                self.error = "" if self.available else _("Could not read the VPN status")
                self.profiles = parse_vpn_profiles(saved, active) if self.available else []
                self.emit("changed")

            run_async(fields, got_saved)

        run_async(fields + ["--active"], got_active)

    def set_active(self, profile: VpnProfile, active: bool) -> None:
        def done(ok: bool, _out: str, err: str) -> None:
            self.error = "" if ok else (err.strip() or _("Could not change the VPN connection"))
            GLib.timeout_add_seconds(1, lambda: self.refresh() or False)
            self.refresh()

        run_async(["nmcli", "connection", "up" if active else "down", "uuid", profile.uuid], done)

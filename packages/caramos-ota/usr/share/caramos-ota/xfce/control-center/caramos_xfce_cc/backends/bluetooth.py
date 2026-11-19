"""Bluetooth through BlueZ on the system bus, as the Cinnamon applet does: the first adapter's power and search, and
the devices it knows. Pairing a new device stays in Blueman (Bluetooth settings), whose applet is the pairing agent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from gi.repository import Gio, GLib, GObject

LOG = logging.getLogger("caramos-control-center")

BLUEZ = "org.bluez"
ADAPTER = "org.bluez.Adapter1"
DEVICE = "org.bluez.Device1"
BATTERY = "org.bluez.Battery1"
CHANGE_DELAY_MS = 250
LIST_LIMIT = 5


@dataclass
class BluetoothDevice:
    path: str
    name: str
    connected: bool
    paired: bool
    battery: int | None = None


@dataclass
class BluetoothState:
    available: bool = False  # BlueZ runs and has an adapter
    powered: bool = False
    discovering: bool = False
    devices: list[BluetoothDevice] = field(default_factory=list)


def visible_devices(devices: list[BluetoothDevice], discovering: bool) -> list[BluetoothDevice]:
    """Connected, then paired devices; while searching, new devices too."""

    shown = [device for device in devices if device.connected or device.paired or discovering]
    shown.sort(key=lambda d: (not d.connected, not d.paired, d.name.lower()))
    return shown[:LIST_LIMIT]


class BluetoothBackend(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self) -> None:
        super().__init__()
        self.state = BluetoothState()
        self.manager: Gio.DBusObjectManagerClient | None = None
        self._adapter_path = ""
        self._change_id = 0
        Gio.bus_watch_name(Gio.BusType.SYSTEM, BLUEZ, Gio.BusNameWatcherFlags.NONE,
                           self._on_appeared, self._on_vanished)

    def _on_appeared(self, _connection: Gio.DBusConnection, _name: str, _owner: str) -> None:
        Gio.DBusObjectManagerClient.new_for_bus(Gio.BusType.SYSTEM, Gio.DBusObjectManagerClientFlags.NONE, BLUEZ,
                                                "/", None, None, None, None, self._on_manager)

    def _on_vanished(self, _connection: Gio.DBusConnection, _name: str) -> None:
        self.manager = None
        self.state = BluetoothState()
        self.emit("changed")

    def _on_manager(self, _source: object, result: Gio.AsyncResult) -> None:
        try:
            self.manager = Gio.DBusObjectManagerClient.new_for_bus_finish(result)
        except GLib.Error as exc:
            LOG.info("BlueZ: %s", exc.message)
            return
        for signal in ("object-added", "object-removed", "interface-added", "interface-removed",
                       "interface-proxy-properties-changed"):
            self.manager.connect(signal, self._on_change)
        self.refresh()

    def _on_change(self, *_args: object) -> None:
        if not self._change_id:
            self._change_id = GLib.timeout_add(CHANGE_DELAY_MS, self._changed_now)

    def _changed_now(self) -> bool:
        self._change_id = 0
        self.refresh()
        return False

    @staticmethod
    def _prop(proxy: Gio.DBusProxy | None, name: str, default: object = None) -> object:
        value = proxy.get_cached_property(name) if proxy is not None else None
        return value.unpack() if value is not None else default

    def refresh(self) -> None:
        if self.manager is None:
            return
        adapter = None
        devices = []
        for obj in self.manager.get_objects():
            adapter_proxy = obj.get_interface(ADAPTER)
            if adapter_proxy is not None and adapter is None:
                adapter = adapter_proxy
            device = obj.get_interface(DEVICE)
            if device is not None:
                name = self._prop(device, "Alias") or self._prop(device, "Name")
                if not name:
                    continue
                battery = obj.get_interface(BATTERY)
                devices.append(BluetoothDevice(path=obj.get_object_path(), name=str(name),
                                               connected=bool(self._prop(device, "Connected", False)),
                                               paired=bool(self._prop(device, "Paired", False)),
                                               battery=self._prop(battery, "Percentage") if battery else None))
        self._adapter_path = adapter.get_object_path() if adapter is not None else ""
        discovering = bool(self._prop(adapter, "Discovering", False))
        self.state = BluetoothState(available=adapter is not None, powered=bool(self._prop(adapter, "Powered", False)),
                                    discovering=discovering, devices=visible_devices(devices, discovering))
        self.emit("changed")

    # -- actions ---------------------------------------------------------------------------------------------------

    def _call(self, path: str, interface: str, method: str, parameters: GLib.Variant | None = None) -> None:
        def done(connection: Gio.DBusConnection, result: Gio.AsyncResult) -> None:
            try:
                connection.call_finish(result)
            except GLib.Error as exc:
                LOG.info("BlueZ %s: %s", method, exc.message)
            self.refresh()

        Gio.bus_get_sync(Gio.BusType.SYSTEM, None).call(BLUEZ, path, interface, method, parameters, None,
                                                         Gio.DBusCallFlags.NONE, 30000, None, done)

    def set_powered(self, powered: bool) -> bool:
        if not self._adapter_path:
            return False
        self._call(self._adapter_path, "org.freedesktop.DBus.Properties", "Set",
                   GLib.Variant("(ssv)", (ADAPTER, "Powered", GLib.Variant("b", powered))))
        return True

    def set_discovering(self, discovering: bool) -> None:
        if self._adapter_path:
            self._call(self._adapter_path, ADAPTER, "StartDiscovery" if discovering else "StopDiscovery")

    def toggle_device(self, device: BluetoothDevice) -> None:
        self._call(device.path, DEVICE, "Disconnect" if device.connected else "Connect")

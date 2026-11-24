"""USB drives and memory cards for the Control Center (ticket H-1195): what is plugged in, and Safely remove.

Safely remove does what Files' "Safely Remove Drive" does: it finishes writing, unmounts every partition of the drive
and powers it off (else ejects it), through GIO and udisks2; a notification then says it can be unplugged. A drive
something still uses is not removed: GTK's own dialog names the programs, and offers to remove it anyway.

Listed: the drives the user can unplug (GIO's removable drives that can be powered off or ejected), with at least one
partition. Disk drives inside the computer, and CD/DVD drives, which eject from Files, are not.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gio, GLib, GObject, Gtk  # noqa: E402

LOG = logging.getLogger("caramos-control-center")


@dataclass
class Removable:
    key: str  # the same for as long as the drive is plugged in
    name: str  # what Files calls it: the partition's name, else the drive's
    icon: str
    mounts: list[str]  # the URIs of its mounted partitions
    busy: bool


def listed(drive: Gio.Drive) -> bool:
    """Whether the user can unplug this drive: removable, with partitions, and it can be powered off or ejected; not
    a CD/DVD drive."""

    device = drive.get_identifier(Gio.DRIVE_IDENTIFIER_KIND_UNIX_DEVICE) or ""
    return (drive.is_removable() and drive.has_volumes() and (drive.can_stop() or drive.can_eject())
            and not device.startswith("/dev/sr"))


def drive_name(drive_label: str, volume_names: list[str]) -> str:
    """One partition: its name (KINGSTON, or "16 GB Volume" without a label), as in Files; else the drive's name."""

    names = [name for name in volume_names if name]
    return names[0] if len(names) == 1 else drive_label or (names[0] if names else "")


def symbolic(gicon: Gio.Icon | None) -> str:
    names = gicon.get_names() if isinstance(gicon, Gio.ThemedIcon) else []
    return next((name for name in names if name.endswith("-symbolic")), "drive-removable-media-symbolic")


class DrivesBackend(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # A drive was removed (name, True) or could not be (name, False, why).
        "removed": (GObject.SignalFlags.RUN_FIRST, None, (str, bool, str)),
        # Writing the rest of the files takes a while (name): do not unplug it yet.
        "writing": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self) -> None:
        super().__init__()
        self.busy: set[str] = set()
        self.monitor = Gio.VolumeMonitor.get()
        for signal in ("drive-connected", "drive-disconnected", "drive-changed", "volume-added", "volume-removed",
                       "volume-changed", "mount-added", "mount-removed", "mount-changed"):
            self.monitor.connect(signal, lambda *_args: self.emit("changed"))

    def _drives(self) -> list[Gio.Drive]:
        return [drive for drive in self.monitor.get_connected_drives() if listed(drive)]

    @staticmethod
    def _key(drive: Gio.Drive) -> str:
        return drive.get_identifier(Gio.DRIVE_IDENTIFIER_KIND_UNIX_DEVICE) or drive.get_name()

    @property
    def drives(self) -> list[Removable]:
        result = []
        for drive in self._drives():
            volumes = drive.get_volumes()
            mounts = [mount for mount in (volume.get_mount() for volume in volumes) if mount is not None]
            key = self._key(drive)
            result.append(Removable(key=key, name=drive_name(drive.get_name(), [v.get_name() for v in volumes]),
                                    icon=symbolic(drive.get_symbolic_icon()),
                                    mounts=[mount.get_root().get_uri() for mount in mounts], busy=key in self.busy))
        return result

    def open(self, key: str, opened: Callable[[str], None], parent: Gtk.Window | None = None) -> None:
        """Hand the URI of the drive's first partition to opened(), mounting it first when it is not mounted (CaramOS
        Xfce does not mount drives by itself: Files does, when it is open)."""

        drive = next((drive for drive in self._drives() if self._key(drive) == key), None)
        if drive is None:
            return
        volumes = drive.get_volumes()
        mount = next((volume.get_mount() for volume in volumes if volume.get_mount() is not None), None)
        if mount is not None:
            opened(mount.get_root().get_uri())
            return
        volume = next((volume for volume in volumes if volume.can_mount()), None)
        if volume is None:
            return

        def mounted(source: Gio.Volume, result: Gio.AsyncResult) -> None:
            try:
                source.mount_finish(result)
            except GLib.Error as exc:
                LOG.info("could not mount %s: %s", source.get_name(), exc.message)
                return
            done = source.get_mount()
            if done is not None:
                opened(done.get_root().get_uri())

        volume.mount(Gio.MountMountFlags.NONE, Gtk.MountOperation(parent=parent), None, mounted)

    def remove(self, key: str, parent: Gtk.Window | None = None) -> None:
        """Safely remove the drive: unmount its partitions, then power it off (or eject it)."""

        drive = next((drive for drive in self._drives() if self._key(drive) == key), None)
        if drive is None or key in self.busy:
            return
        name = next((item.name for item in self.drives if item.key == key), drive.get_name())
        operation = Gtk.MountOperation(parent=parent)
        operation.connect("show-unmount-progress", self._on_progress, name)
        self.busy.add(key)
        self.emit("changed")
        done = self._finisher(key, name, drive.stop_finish if drive.can_stop() else drive.eject_with_operation_finish)
        if drive.can_stop():
            drive.stop(Gio.MountUnmountFlags.NONE, operation, None, done)
        else:
            drive.eject_with_operation(Gio.MountUnmountFlags.NONE, operation, None, done)

    def _on_progress(self, _operation: Gio.MountOperation, message: str, _time_left: int, bytes_left: int,
                     name: str) -> None:
        # GIO says so when the last files take longer than a moment to write, and again (0 bytes left) when done.
        if bytes_left > 0:
            self.emit("writing", name)

    def _finisher(self, key: str, name: str, finish: Callable[[Gio.AsyncResult], bool]
                  ) -> Callable[[GObject.Object, Gio.AsyncResult], None]:
        def done(_drive: GObject.Object, result: Gio.AsyncResult) -> None:
            self.busy.discard(key)
            try:
                finish(result)
            except GLib.Error as exc:
                LOG.info("could not remove %s: %s", name, exc.message)
                if not exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.FAILED_HANDLED):
                    self.emit("removed", name, False, exc.message)
            else:
                self.emit("removed", name, True, "")
            self.emit("changed")

        return done

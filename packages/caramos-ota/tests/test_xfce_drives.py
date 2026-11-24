"""USB drives and memory cards in the Xfce Control Center (ticket H-1195): a drive icon in the right island while one is
plugged in, a card at the top of the popup with Safely remove, and a notification when it can be unplugged
(backends/drives.py). Also the network in words when pointing at the Control Center's button (ticket H-1205)."""

from __future__ import annotations

import importlib
import importlib.util
import os
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
CC = ROOT / "usr/share/caramos-ota/xfce/control-center"
PACKAGE = CC / "caramos_xfce_cc"

try:
    import gi

    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gio, GLib, Gtk  # noqa: F401

    HAVE_GTK = True
except (ImportError, ValueError):
    HAVE_GTK = False

if HAVE_GTK:
    os.environ.setdefault("CARAMOS_CC_LOCALEDIR", "/nonexistent")
    sys.path.insert(0, str(CC))


class FakeDrive:
    def __init__(self, device: str = "/dev/sdb", removable: bool = True, volumes: int = 1, stop: bool = True,
                 eject: bool = False) -> None:
        self.device, self.removable, self.volumes, self.stop, self.eject = device, removable, volumes, stop, eject

    def get_identifier(self, _kind: str) -> str:
        return self.device

    def is_removable(self) -> bool:
        return self.removable

    def has_volumes(self) -> bool:
        return self.volumes > 0

    def can_stop(self) -> bool:
        return self.stop

    def can_eject(self) -> bool:
        return self.eject


@unittest.skipUnless(HAVE_GTK, "PyGObject with GTK 3 is unavailable")
class DrivesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.drives = importlib.import_module("caramos_xfce_cc.backends.drives")

    def test_which_drives(self) -> None:
        listed = self.drives.listed
        self.assertTrue(listed(FakeDrive()), "a USB stick: powered off when removed")
        self.assertTrue(listed(FakeDrive(stop=False, eject=True)), "a card reader: ejected")
        self.assertFalse(listed(FakeDrive(removable=False)), "a disk inside the computer")
        self.assertFalse(listed(FakeDrive(volumes=0)), "nothing to open")
        self.assertFalse(listed(FakeDrive(device="/dev/sr0", stop=False, eject=True)), "CDs eject from Files")
        self.assertFalse(listed(FakeDrive(stop=False, eject=False)))

    def test_names_as_in_files(self) -> None:
        self.assertEqual("KINGSTON", self.drives.drive_name("Kingston DataTraveler 3.0", ["KINGSTON"]))
        self.assertEqual("16 GB Volume", self.drives.drive_name("SanDisk Cruzer", ["16 GB Volume"]))
        self.assertEqual("WD Elements", self.drives.drive_name("WD Elements", ["Data", "Backup"]))
        self.assertEqual("", self.drives.drive_name("", []))

    def test_symbolic_icons(self) -> None:
        icon = Gio.ThemedIcon.new_from_names(["drive-removable-media-usb", "drive-removable-media-usb-symbolic"])
        self.assertEqual("drive-removable-media-usb-symbolic", self.drives.symbolic(icon))
        self.assertEqual("drive-removable-media-symbolic", self.drives.symbolic(None))

    def test_what_a_removal_says(self) -> None:
        with mock.patch.object(self.drives.Gio.VolumeMonitor, "get",
                               return_value=SimpleNamespace(connect=lambda *_args: 0)):
            backend = self.drives.DrivesBackend()
        backend.busy = {"/dev/sdb"}
        heard = []
        backend.connect("removed", lambda _b, name, ok, why: heard.append((name, ok, why)))
        backend.connect("changed", lambda _b: heard.append("changed"))

        def finish_ok(_result: object) -> bool:
            return True

        backend._finisher("/dev/sdb", "KINGSTON", finish_ok)(None, None)
        self.assertEqual([("KINGSTON", True, ""), "changed"], heard)
        self.assertEqual(set(), backend.busy)
        heard.clear()

        def finish_busy(_result: object) -> bool:
            raise GLib.Error.new_literal(Gio.io_error_quark(), "Target is busy", Gio.IOErrorEnum.BUSY)

        backend._finisher("/dev/sdb", "KINGSTON", finish_busy)(None, None)
        self.assertEqual([("KINGSTON", False, "Target is busy"), "changed"], heard)
        heard.clear()

        def finish_cancelled(_result: object) -> bool:
            raise GLib.Error.new_literal(Gio.io_error_quark(), "aborted", Gio.IOErrorEnum.FAILED_HANDLED)

        backend._finisher("/dev/sdb", "KINGSTON", finish_cancelled)(None, None)
        self.assertEqual(["changed"], heard, "Cancel in GTK's dialog says nothing more")

    def test_network_in_words(self) -> None:
        indicator = importlib.import_module("caramos_xfce_cc.indicator")
        wired = SimpleNamespace(primary_type="ethernet", connectivity=4, wifi_networks=[])
        self.assertEqual("Wired network: Internet access", indicator.network_text(wired))
        wifi = SimpleNamespace(primary_type="wifi", connectivity=4,
                               wifi_networks=[SimpleNamespace(active=False, ssid="Hang xom"),
                                              SimpleNamespace(active=True, ssid="Phong may 1")])
        self.assertEqual("Wi‑Fi: Phong may 1", indicator.network_text(wifi))
        self.assertEqual("No network", indicator.network_text(SimpleNamespace(primary_type="", connectivity=1,
                                                                              wifi_networks=[])))


class SourceTests(unittest.TestCase):
    def test_the_popup(self) -> None:
        popup = (PACKAGE / "popup.py").read_text(encoding="utf-8")
        self.assertIn('"caramos-cc-drives"', popup)
        self.assertIn('_("USB drives and memory cards")', popup)
        remove = re.search(r"def _remove_drive\(.*?\n\n", popup, re.S).group(0)
        # GTK's dialog naming the programs that still use the drive needs the keyboard, which the open popup holds.
        self.assertLess(remove.index("self.hide_popup()"), remove.index("self.b.drives.remove("))
        self.assertIn('w.round_button("media-eject-symbolic"', popup)
        self.assertIn("self.drives.set_visible(bool(self.drive_keys))", popup, "show_all must not show an empty card")

    def test_the_island_icon(self) -> None:
        indicator = (PACKAGE / "indicator.py").read_text(encoding="utf-8")
        self.assertIn('self.usb = w.icon("drive-removable-media-symbolic", 16, "caramos-cc-panel-icon")', indicator)
        self.assertIn("(self.quiet, self.usb, self.network,", indicator, "left of the network, as on Windows")
        self.assertIn("self.usb.set_visible(bool(self.b.drives.drives))", indicator)


if __name__ == "__main__":
    unittest.main()

"""Static packaging checks for OTA launcher branding."""

from __future__ import annotations

import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
ICON = ROOT / "usr/share/pixmaps/caramos-logo.png"


class NotifierPackagingTests(unittest.TestCase):
    def test_launchers_use_caramos_icon(self) -> None:
        for path in (
            ROOT / "usr/share/applications/caramos-update-center.desktop",
            ROOT / "etc/xdg/autostart/caramos-ota-notifier.desktop",
        ):
            with self.subTest(path=path):
                source = path.read_text(encoding="utf-8")
                self.assertIn("\nIcon=caramos-logo\n", f"\n{source}")
                self.assertNotIn("Icon=system-software-update", source)

    def test_package_installs_icon_for_pixmaps_and_hicolor(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        self.assertIn("usr/share/pixmaps/caramos-logo.png usr/share/pixmaps/", install)
        self.assertIn("usr/share/pixmaps/caramos-logo.png usr/share/icons/hicolor/512x512/apps/", install)

    def test_icon_is_512_pixel_png(self) -> None:
        data = ICON.read_bytes()
        self.assertEqual(b"\x89PNG\r\n\x1a\n", data[:8])
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((512, 512), (width, height))


if __name__ == "__main__":
    unittest.main()

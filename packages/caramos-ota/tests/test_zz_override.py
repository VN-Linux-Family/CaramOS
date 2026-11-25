"""zz_caramos-ota.gschema.override: the CaramOS defaults that must win over Linux Mint's mint-artwork override."""

from __future__ import annotations

import configparser
import unittest
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
OVERRIDE = PACKAGE / "usr/share/glib-2.0/schemas/zz_caramos-ota.gschema.override"
# The ISO's own override, in the repository; absent in the package-only build (Launchpad), where those tests skip.
ISO_OVERRIDE = PACKAGE.parents[1] / "config/includes.chroot/usr/share/glib-2.0/schemas/99_caramos.gschema.override"


def read(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


class ZzOverrideTests(unittest.TestCase):
    def test_it_sorts_after_mints_override(self) -> None:
        # glib-compile-schemas reads override files in name order; the last value of a key wins.
        self.assertGreater(OVERRIDE.name, "mint-artwork.gschema.override")
        self.assertGreater(OVERRIDE.name, "99_caramos.gschema.override")

    def test_the_lock_and_login_screens_use_be_vietnam_pro(self) -> None:
        override = read(OVERRIDE)
        self.assertEqual({"font-date": "'Be Vietnam Pro 24'", "font-message": "'Be Vietnam Pro 14'",
                          "font-time": "'Be Vietnam Pro 64'"}, dict(override["org.cinnamon.desktop.screensaver"]))
        self.assertEqual({"font-name": "'Be Vietnam Pro 11'"}, dict(override["x.dm.slick-greeter"]))

    def test_it_is_installed(self) -> None:
        install = (PACKAGE / "debian/install").read_text(encoding="utf-8")
        self.assertIn(f"usr/share/glib-2.0/schemas/{OVERRIDE.name} usr/share/glib-2.0/schemas/", install)

    @unittest.skipUnless(ISO_OVERRIDE.is_file(), "the repository's config/ is not here (package-only build)")
    def test_it_repeats_the_isos_values(self) -> None:
        # Only a copy of what 99_caramos says: change both together.
        override, iso = read(OVERRIDE), read(ISO_OVERRIDE)
        for section in override.sections():
            for key, value in override[section].items():
                self.assertEqual(iso[section][key], value, f"[{section}] {key}")


if __name__ == "__main__":
    unittest.main()

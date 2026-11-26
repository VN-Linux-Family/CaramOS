"""Linux Mint's Update Manager (mintupdate 7.1.4) keeps its updates back until someone presses OK on its welcome page;
its first automatic refresh, 10 minutes after login, then opens its window on that page, over whatever is open (Veyon
Master in a computer lab, 2026-11-26). The owner asked for it to be off on every CaramOS computer: the package's
gschema override makes com.linuxmint.updates show-welcome-page false by default."""

from __future__ import annotations

import configparser
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
OVERRIDE = ROOT / "usr/share/glib-2.0/schemas/60_caramos-ota.gschema.override"
ISO_OVERRIDE = REPO / "config/includes.chroot/usr/share/glib-2.0/schemas/99_caramos.gschema.override"
SCHEMA = "com.linuxmint.updates"

# mintupdate's schema for the key: its default shows the page.
SCHEMA_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="{SCHEMA}" path="/com/linuxmint/updates/">
    <key type="b" name="show-welcome-page"><default>true</default><summary></summary></key>
  </schema>
</schemalist>
"""


def parser(path: Path) -> configparser.ConfigParser:
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.read(path, encoding="utf-8")
    return config


class MintUpdateWelcomePageTests(unittest.TestCase):
    def test_the_package_turns_the_welcome_page_off(self) -> None:
        self.assertEqual("false", parser(OVERRIDE)[SCHEMA]["show-welcome-page"])
        self.assertIn(f"{OVERRIDE.relative_to(ROOT)} usr/share/glib-2.0/schemas/",
                      (ROOT / "debian/install").read_text(encoding="utf-8"))

    @unittest.skipUnless(ISO_OVERRIDE.exists(), "the source package has no config/")
    def test_the_iso_does_not_take_it_back(self) -> None:
        # 99_caramos sorts after 60_caramos-ota, so a value there would win.
        self.assertNotIn(SCHEMA, parser(ISO_OVERRIDE))

    @unittest.skipUnless(shutil.which("glib-compile-schemas") and shutil.which("gsettings"), "GLib tools unavailable")
    def test_glib_reads_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / f"{SCHEMA}.gschema.xml").write_text(SCHEMA_XML, encoding="utf-8")
            groups = OVERRIDE.read_text(encoding="utf-8").split("\n[")
            ours = "[" + next(group for group in groups if group.startswith(SCHEMA + "]"))
            (directory / "60_caramos-ota.gschema.override").write_text(ours, encoding="utf-8")
            subprocess.run(["glib-compile-schemas", "--strict", str(directory)], check=True, capture_output=True)
            env = dict(os.environ, GSETTINGS_SCHEMA_DIR=str(directory), GSETTINGS_BACKEND="memory")
            value = subprocess.run(["gsettings", "get", SCHEMA, "show-welcome-page"], env=env, check=True, text=True,
                                   capture_output=True).stdout.strip()
            self.assertEqual("false", value)


if __name__ == "__main__":
    unittest.main()

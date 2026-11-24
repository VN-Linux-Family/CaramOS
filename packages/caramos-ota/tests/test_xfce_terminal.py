"""Files (Nemo) > Open in Terminal on the Xfce edition, ticket H-1185: Nemo starts the terminal named in
org.cinnamon.desktop.default-applications.terminal, which the ISO sets to GNOME Terminal for both editions; the Xfce
edition has xfce4-terminal only. The package's override gives Xfce sessions xfce4-terminal."""

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
SCHEMA = "org.cinnamon.desktop.default-applications.terminal"
XFCE_GROUP = f"{SCHEMA}:XFCE"

# cinnamon-desktop's schema for the key (its default is GNOME Terminal).
SCHEMA_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema id="{SCHEMA}" path="/org/cinnamon/desktop/applications/terminal/">
    <key name="exec" type="s"><default>'gnome-terminal'</default><summary>Terminal</summary></key>
    <key name="exec-arg" type="s"><default>'--'</default><summary>Argument</summary></key>
  </schema>
</schemalist>
"""


def parser(path: Path) -> configparser.ConfigParser:
    config = configparser.ConfigParser(interpolation=None, strict=False)
    config.read(path, encoding="utf-8")
    return config


class XfceTerminalTests(unittest.TestCase):
    def test_xfce_sessions_get_xfce4_terminal(self) -> None:
        config = parser(OVERRIDE)
        self.assertEqual("'xfce4-terminal'", config[XFCE_GROUP]["exec"])
        self.assertEqual("'-x'", config[XFCE_GROUP]["exec-arg"])
        self.assertNotIn(SCHEMA, config)  # Cinnamon keeps the ISO's GNOME Terminal

    @unittest.skipUnless(ISO_OVERRIDE.exists(), "the source package has no config/")
    def test_the_iso_does_not_take_it_back(self) -> None:
        config = parser(ISO_OVERRIDE)
        self.assertEqual("'gnome-terminal'", config[SCHEMA]["exec"])
        self.assertFalse([group for group in config.sections() if group.startswith(f"{SCHEMA}:")])

    @unittest.skipUnless(shutil.which("glib-compile-schemas") and shutil.which("gsettings"), "GLib tools unavailable")
    def test_glib_picks_it_for_xfce_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / f"{SCHEMA}.gschema.xml").write_text(SCHEMA_XML, encoding="utf-8")
            # The ISO's general default comes after the package's file, as on a computer (99_ after 60_).
            groups = OVERRIDE.read_text(encoding="utf-8").split("\n[")
            ours = "[" + next(group for group in groups if group.startswith(XFCE_GROUP + "]"))
            (directory / "60_caramos-ota.gschema.override").write_text(ours, encoding="utf-8")
            (directory / "99_caramos.gschema.override").write_text(f"[{SCHEMA}]\nexec='gnome-terminal'\n",
                                                                     encoding="utf-8")
            subprocess.run(["glib-compile-schemas", "--strict", str(directory)], check=True, capture_output=True)

            def value(desktop: str, key: str) -> str:
                env = dict(os.environ, GSETTINGS_SCHEMA_DIR=str(directory), GSETTINGS_BACKEND="memory",
                           XDG_CURRENT_DESKTOP=desktop)
                return subprocess.run(["gsettings", "get", SCHEMA, key], env=env, check=True, text=True,
                                      capture_output=True).stdout.strip()

            self.assertEqual("'xfce4-terminal'", value("XFCE", "exec"))
            self.assertEqual("'-x'", value("XFCE", "exec-arg"))
            self.assertEqual("'gnome-terminal'", value("X-Cinnamon", "exec"))
            self.assertEqual("'--'", value("X-Cinnamon", "exec-arg"))


if __name__ == "__main__":
    unittest.main()

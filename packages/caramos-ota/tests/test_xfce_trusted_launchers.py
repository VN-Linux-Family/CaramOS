"""CaramOS Xfce: the launchers CaramOS puts on the Desktop (Files, CaramOS App Center, Install CaramOS in the live
session) open without Thunar's "Untrusted application launcher" question, which also made xfdesktop report "Failed to
run …: Timeout was reached". Launchers that are not root's own copies still ask."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "usr/share/caramos-ota/xfce/caramos-trust-desktop-launchers"
AUTOSTART = ROOT / "etc/xdg/autostart/caramos-xfce-trusted-launchers.desktop"

# gio stand-in: the metadata of FILE lives in FILE.meta; every "gio set" is logged.
FAKE_GIO = """#!/bin/sh
if [ "$1" = info ]; then
    [ -f "$4.meta" ] && printf 'attributes:\\n  metadata::xfce-exe-checksum: %s\\n' "$(cat "$4.meta")"
    exit 0
fi
if [ "$1" = set ]; then
    printf '%s' "$4" > "$2.meta"
    echo "$2" >> "$GIO_LOG"
fi
"""
LAUNCHER = "[Desktop Entry]\nType=Application\nName=Files\nExec=nemo %U\n"


class TrustedLaunchersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        self.home = self.root / "home"
        self.desktop = self.home / "Desktop"
        self.skel = self.root / "skel/Desktop"
        self.applications = self.root / "applications"
        self.bin = self.root / "bin"
        for folder in (self.desktop, self.skel, self.applications, self.bin):
            folder.mkdir(parents=True)
        self.tool("gio", FAKE_GIO)
        self.tool("xdg-user-dir", f'#!/bin/sh\necho "{self.desktop}"\n')
        self.log = self.root / "gio.log"

    def tool(self, name: str, text: str) -> None:
        path = self.bin / name
        path.write_text(text, encoding="utf-8")
        path.chmod(0o755)

    def put(self, folder: Path, name: str, text: str = LAUNCHER, mode: int = 0o755) -> Path:
        path = folder / name
        path.write_text(text, encoding="utf-8")
        path.chmod(mode)
        return path

    def run_script(self) -> list[str]:
        self.log.unlink(missing_ok=True)
        environment = {"PATH": f"{self.bin}:/usr/bin:/bin", "HOME": str(self.home), "GIO_LOG": str(self.log),
                       "CARAMOS_SKEL_DESKTOP": str(self.skel), "CARAMOS_APPLICATIONS": str(self.applications)}
        result = subprocess.run(["/bin/sh", str(SCRIPT)], env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    @staticmethod
    def checksum(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def stored(self, path: Path) -> str | None:
        meta = Path(f"{path}.meta")
        return meta.read_text(encoding="utf-8") if meta.exists() else None

    def test_the_isos_launchers_are_trusted_once(self) -> None:
        self.put(self.skel, "nemo.desktop")
        files = self.put(self.desktop, "nemo.desktop")
        installer_text = "[Desktop Entry]\nName=Install CaramOS\nExec=ubiquity gtk_ui\n"
        self.put(self.applications, "ubiquity.desktop", installer_text, 0o644)
        installer = self.put(self.desktop, "ubiquity.desktop", installer_text)  # casper's copy in the live session
        self.assertEqual(sorted([str(files), str(installer)]), sorted(self.run_script()))
        self.assertEqual(self.checksum(files), self.stored(files))
        self.assertEqual(self.checksum(installer), self.stored(installer))
        self.assertEqual([], self.run_script(), "nothing to do at the next login")

    def test_other_launchers_still_ask(self) -> None:
        self.put(self.skel, "nemo.desktop")
        changed = self.put(self.desktop, "nemo.desktop", LAUNCHER + "Exec=evil\n")
        downloaded = self.put(self.desktop, "game.desktop", "[Desktop Entry]\nExec=evil\n")
        linked = self.desktop / "caramos-app-center.desktop"
        self.put(self.skel, "caramos-app-center.desktop")
        linked.symlink_to(self.skel / "caramos-app-center.desktop")
        self.assertEqual([], self.run_script())
        for path in (changed, downloaded, linked):
            self.assertIsNone(self.stored(path), path)

    def test_a_stale_checksum_is_replaced_and_the_execute_bit_set(self) -> None:
        self.put(self.skel, "nemo.desktop")
        files = self.put(self.desktop, "nemo.desktop", mode=0o644)
        Path(f"{files}.meta").write_text("old", encoding="utf-8")
        self.assertEqual([str(files)], self.run_script())
        self.assertEqual(self.checksum(files), self.stored(files))
        self.assertTrue(os.access(files, os.X_OK))

    def test_without_a_desktop_folder_nothing_happens(self) -> None:
        self.tool("xdg-user-dir", f'#!/bin/sh\necho "{self.home}"\n')  # before xdg-user-dirs made the folders
        self.put(self.skel, "nemo.desktop")
        self.put(self.desktop, "nemo.desktop")
        self.assertEqual([], self.run_script())

    def test_only_xfce_runs_it_at_login(self) -> None:
        text = AUTOSTART.read_text(encoding="utf-8")
        self.assertIn("OnlyShowIn=XFCE;\n", text)
        self.assertIn(f"Exec=/{SCRIPT.relative_to(ROOT)}\n", text)
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        install = (ROOT / "debian/install").read_text(encoding="utf-8").splitlines()
        self.assertIn("etc/xdg/autostart/caramos-xfce-trusted-launchers.desktop etc/xdg/autostart/", install)
        self.assertIn("usr/share/caramos-ota/xfce usr/share/caramos-ota/", install)


if __name__ == "__main__":
    unittest.main()

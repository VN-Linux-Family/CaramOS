"""CopyQ leaves CaramOS: new installs do not get it, and migration 20261014120000_stop_copyq_autostart stops it
from starting at login on installed systems, keeping the app and its history."""

from __future__ import annotations

import configparser
import importlib.util
import json
import os
import pwd
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).parents[1]
REPO = ROOT.parents[1]
MIGRATION_PATH = (
    ROOT
    / "usr/lib/python3/dist-packages/caramos_ota_update/migrations"
    / "20261014120000_stop_copyq_autostart/migration.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("stop_copyq_autostart_test", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = load_migration()


class StopCopyqAutostartTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.users: list[pwd.struct_passwd] = []
        for name, value in {
            "SKEL": self.root / "etc/skel",
            "PASSWD_HOME_ROOT": self.root / "home",
            "_desktop_users": lambda: self.users,
        }.items():
            patcher = patch.object(migration, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def entry(self, base: Path, content: str = migration.SHIPPED) -> Path:
        path = base / ".config/autostart/copyq.desktop"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o775)   # as /etc/skel had it
        return path

    def add_user(self, name: str) -> Path:
        home = self.root / "home" / name
        home.mkdir(parents=True)
        self.users.append(pwd.struct_passwd((name, "x", os.getuid(), os.getgid(), name, str(home), "/bin/bash")))
        return home

    def run_migration(self, *, dry_run: bool = False) -> list[list[str]]:
        context = MigrationContext(dry_run=dry_run)
        calls: list[list[str]] = []

        def fake_run(args, **_kwargs):
            calls.append(list(args))
            return subprocess.CompletedProcess(list(args), 0, "", "")

        with patch.object(context, "run_command", side_effect=fake_run):
            migration.run(context)
        return calls

    def test_copyq_stays_but_no_longer_starts_at_login(self) -> None:
        skel = self.entry(self.root / "etc/skel")
        an = self.entry(self.add_user("an"))
        changed = migration.SHIPPED.replace("X-GNOME-Autostart-Delay=3", "X-GNOME-Autostart-Delay=10")
        binh = self.entry(self.add_user("binh"), changed)
        self.add_user("chi")   # no autostart entry

        self.assertEqual([], self.run_migration())   # nothing is uninstalled

        self.assertFalse(skel.exists())
        self.assertEqual(migration.SHIPPED.replace("X-GNOME-Autostart-enabled=true", "X-GNOME-Autostart-enabled=false"),
                         an.read_text(encoding="utf-8"))
        self.assertEqual(0o775, an.stat().st_mode & 0o777)
        self.assertEqual([], list(an.parent.glob(".copyq.desktop.*")))
        self.assertEqual(changed, binh.read_text(encoding="utf-8"))
        self.assertFalse((self.root / "home/chi/.config").exists())

        written = an.stat().st_mtime_ns
        self.run_migration()
        self.assertEqual(written, an.stat().st_mtime_ns)

    def test_it_is_turned_off_the_way_startup_applications_does_it(self) -> None:
        an = self.entry(self.add_user("an"))
        self.run_migration()
        entry = configparser.ConfigParser(interpolation=None, strict=False)
        entry.optionxform = str
        entry.read(an, encoding="utf-8")
        section = entry["Desktop Entry"]
        # cinnamon-session skips it; Startup Applications still lists it (it hides Hidden=true), switched off.
        self.assertEqual("false", section["X-GNOME-Autostart-enabled"])
        self.assertEqual("false", section["Hidden"])
        self.assertEqual('"/usr/bin/copyq"', section["Exec"])

    def test_dry_run_changes_nothing(self) -> None:
        skel = self.entry(self.root / "etc/skel")
        an = self.entry(self.add_user("an"))
        self.run_migration(dry_run=True)
        self.assertTrue(skel.exists())
        self.assertEqual(migration.SHIPPED, an.read_text(encoding="utf-8"))

    def test_an_entry_behind_a_symlink_is_left_alone(self) -> None:
        home = self.add_user("an")
        target = self.entry(self.root / "elsewhere")
        (home / ".config").mkdir()
        (home / ".config/autostart").symlink_to(target.parent, target_is_directory=True)
        linked_skel = self.root / "etc/skel/.config/autostart/copyq.desktop"
        linked_skel.parent.mkdir(parents=True)
        linked_skel.symlink_to(target)

        self.run_migration()

        self.assertEqual(migration.SHIPPED, target.read_text(encoding="utf-8"))
        self.assertTrue(linked_skel.is_symlink())

    def test_manifest(self) -> None:
        manifest = json.loads(MIGRATION_PATH.with_name("manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(2, manifest["schema"])
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertIn("Ứng dụng Khởi chạy", " ".join(manifest["release_notes_vi"]))   # Cinnamon's Vietnamese name


@unittest.skipUnless((REPO / "config").is_dir(), "ISO tree is not in the source package")
class NewInstallTests(unittest.TestCase):
    def test_the_iso_has_no_copyq(self) -> None:
        for name in ("config/packages.txt", "config/package-lists/caramos.list.chroot"):
            packages = [line.strip() for line in (REPO / name).read_text(encoding="utf-8").splitlines()]
            self.assertNotIn("copyq", packages, name)
        self.assertFalse((REPO / "config/includes.chroot/etc/skel/.config/autostart/copyq.desktop").exists())

    def test_every_listed_shortcut_is_defined(self) -> None:
        # custom2 was CopyQ's Super+V, whose definition went in May 2026. The others are defined in dconf, as
        # overrides cannot reach the relocatable custom shortcuts (20261112100000_screenshot_shortcuts).
        override = (REPO / "config/includes.chroot/usr/share/glib-2.0/schemas/99_caramos.gschema.override").read_text(
            encoding="utf-8")
        defaults = (REPO / "config/includes.chroot/etc/dconf/db/local.d/02-caramos-screenshot-keys").read_text(
            encoding="utf-8")
        listed = re.search(r"^custom-list=\[(.*)\]$", override, re.MULTILINE).group(1)
        for name in re.findall(r"'([^']+)'", listed):
            self.assertIn(f"\n[org/cinnamon/desktop/keybindings/custom-keybindings/{name}]\n", defaults)
        self.assertNotIn("'custom2'", listed)


if __name__ == "__main__":
    unittest.main()

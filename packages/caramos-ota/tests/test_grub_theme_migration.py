"""Tests for the CaramOS GRUB theme migration."""

from __future__ import annotations

import importlib.util
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from caramos_ota_update.context import MigrationContext

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "usr/lib/python3/dist-packages/caramos_ota_update/migrations"
    / "20261005190000_install_grub_theme/migration.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("install_grub_theme_test", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = load_migration()


def png_header(path: Path) -> tuple[int, int, int, int]:
    """Return (width, height, bit depth, interlace) from the IHDR chunk."""

    data = path.read_bytes()[:33]
    if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise AssertionError(f"not a PNG file: {path}")
    width, height, depth, _color, _compression, _filter, interlace = struct.unpack(">IIBBBBB", data[16:29])
    return width, height, depth, interlace


def sourced_grub_theme(defaults_file: Path, preset: str | None) -> str:
    """Source the drop-in like grub-mkconfig does and print the resulting GRUB_THEME."""

    script = f'. "{defaults_file}"; printf %s "$GRUB_THEME"'
    if preset is not None:
        script = f"GRUB_THEME={preset}; {script}"
    return subprocess.run(["sh", "-c", script], check=True, capture_output=True, text=True).stdout


class GrubThemePayloadTests(unittest.TestCase):
    def test_background_is_a_png_grub_can_decode(self) -> None:
        # GRUB's PNG reader rejects interlaced images; the file must also be a real PNG, not a
        # JPEG with a .png name like the old ISO splash.
        width, height, depth, interlace = png_header(migration.PAYLOAD_DIR / "background.png")
        self.assertEqual((1920, 1080, 8, 0), (width, height, depth, interlace))

    def test_theme_only_references_bundled_images(self) -> None:
        theme = (migration.PAYLOAD_DIR / "theme.txt").read_text(encoding="utf-8")
        self.assertIn('desktop-image: "background.png"', theme)
        for name in migration.THEME_FILES:
            self.assertTrue((migration.PAYLOAD_DIR / name).is_file(), name)

    def test_defaults_drop_in_keeps_a_user_theme(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            defaults = Path(tmp) / "60_caramos-theme.cfg"
            defaults.write_text(migration.DEFAULTS_CONTENT, encoding="utf-8")
            theme = str(migration.THEME_DIR / "theme.txt")

            self.assertEqual(theme, sourced_grub_theme(defaults, None))
            self.assertEqual("/boot/grub/themes/other/theme.txt", sourced_grub_theme(defaults, "/boot/grub/themes/other/theme.txt"))
            self.assertEqual("", sourced_grub_theme(defaults, '""'))


class InstallGrubThemeMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.theme_dir = root / "boot/grub/themes/caramos"
        self.defaults = root / "etc/default/grub.d/60_caramos-theme.cfg"
        self.grub_cfg = root / "boot/grub/grub.cfg"
        for name, value in (
            ("THEME_DIR", self.theme_dir),
            ("DEFAULTS_FILE", self.defaults),
            ("GRUB_CFG", self.grub_cfg),
        ):
            patcher = patch.object(migration, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        which = patch.object(migration.shutil, "which", return_value="/usr/sbin/update-grub")
        which.start()
        self.addCleanup(which.stop)

    def run_migration(self, *, dry_run: bool = False, returncode: int = 0) -> list[list[str]]:
        context = MigrationContext(dry_run=dry_run)
        calls: list[list[str]] = []

        def fake_run(args, **_kwargs):
            calls.append(list(args))
            return subprocess.CompletedProcess(list(args), returncode, "", "error: syntax error\n")

        with patch.object(context, "run_command", side_effect=fake_run):
            migration.run(context)
        return calls

    def assert_installed(self) -> None:
        for name in migration.THEME_FILES:
            self.assertEqual((migration.PAYLOAD_DIR / name).read_bytes(), (self.theme_dir / name).read_bytes())
            self.assertEqual(0o644, (self.theme_dir / name).stat().st_mode & 0o777)
        self.assertEqual(migration.DEFAULTS_CONTENT, self.defaults.read_text(encoding="utf-8"))

    def test_installed_system_gets_theme_and_update_grub(self) -> None:
        self.grub_cfg.parent.mkdir(parents=True)
        self.grub_cfg.write_text("# generated\n", encoding="utf-8")

        calls = self.run_migration()

        self.assert_installed()
        self.assertEqual([["update-grub"]], calls)

    def test_iso_build_installs_files_without_update_grub(self) -> None:
        # The ISO rootfs has no /boot/grub/grub.cfg; the installer runs update-grub on the target.
        calls = self.run_migration()

        self.assert_installed()
        self.assertEqual([], calls)

    def test_update_grub_failure_does_not_fail_the_migration(self) -> None:
        self.grub_cfg.parent.mkdir(parents=True)
        self.grub_cfg.write_text("# generated\n", encoding="utf-8")

        calls = self.run_migration(returncode=1)

        self.assert_installed()
        self.assertEqual([["update-grub"]], calls)

    def test_second_run_changes_nothing(self) -> None:
        self.grub_cfg.parent.mkdir(parents=True)
        self.grub_cfg.write_text("# generated\n", encoding="utf-8")
        self.run_migration()

        calls = self.run_migration()

        self.assertEqual([], calls)
        self.assert_installed()

    def test_dry_run_writes_nothing(self) -> None:
        self.grub_cfg.parent.mkdir(parents=True)
        self.grub_cfg.write_text("# generated\n", encoding="utf-8")

        with patch("caramos_ota_update.context.subprocess.run") as run:
            migration.run(MigrationContext(dry_run=True))

        run.assert_not_called()
        self.assertFalse(self.theme_dir.exists())
        self.assertFalse(self.defaults.exists())


if __name__ == "__main__":
    unittest.main()

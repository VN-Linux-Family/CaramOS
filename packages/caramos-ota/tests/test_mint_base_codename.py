"""Tests for writing the real Linux Mint base codename (zena) instead of wilma."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from caramos_ota_update.context import MigrationContext
from caramos_ota_update.version_metadata import MINT_BASE_CODENAME, MINT_BASE_NAME, version_metadata_files

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "usr/lib/python3/dist-packages/caramos_ota_update/migrations"
    / "20261004120000_fix_mint_base_codename/migration.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("fix_mint_base_codename_test", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = load_migration()

# What CaramOS 1.0.12-1.0.16 installs actually carry.
ISO_INFO = (
    "RELEASE=1.0.16\nCODENAME=wilma\nEDITION=\"Cinnamon\"\n"
    "DESCRIPTION=\"CaramOS 1.0.16 Cinnamon\"\nGRUB_TITLE=CaramOS 1.0.16 Cinnamon\n"
)
ISO_OS_RELEASE = 'NAME="CaramOS"\nVERSION_ID="1.0.16"\nVERSION_CODENAME=wilma\nUBUNTU_CODENAME=noble\n'
ISO_LSB = 'DISTRIB_ID=CaramOS\nDISTRIB_RELEASE=1.0.16\nDISTRIB_CODENAME=wilma\nDISTRIB_DESCRIPTION="CaramOS 1.0.16"\n'


class VersionMetadataCodenameTests(unittest.TestCase):
    def test_base_is_mint_22_3_zena(self) -> None:
        # Every CaramOS ISO so far uses the packages.linuxmint.com "zena" suite (Mint 22.3).
        self.assertEqual(("Linux Mint 22.3", "zena"), (MINT_BASE_NAME, MINT_BASE_CODENAME))

    def test_all_release_files_use_the_base_codename(self) -> None:
        files = {str(path): content for path, content in version_metadata_files("1.0.16.1").items()}
        self.assertIn("CODENAME=zena\n", files["/etc/linuxmint/info"])
        self.assertIn("VERSION_CODENAME=zena\n", files["/etc/os-release"])
        self.assertIn("UBUNTU_CODENAME=noble\n", files["/etc/os-release"])
        self.assertIn('CARAMOS_BASE="Linux Mint 22.3"\n', files["/etc/os-release"])
        self.assertIn("DISTRIB_CODENAME=zena\n", files["/etc/lsb-release"])
        self.assertFalse(any("wilma" in content for content in files.values()))
        # CaramOS keeps its own version and branding in the Mint release file.
        self.assertIn("RELEASE=1.0.16.1\n", files["/etc/linuxmint/info"])


class FixMintBaseCodenameMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.info = root / "info"
        self.os_release = root / "os-release"
        self.lsb = root / "lsb-release"
        self.info.write_text(ISO_INFO, encoding="utf-8")
        self.os_release.write_text(ISO_OS_RELEASE, encoding="utf-8")
        self.lsb.write_text(ISO_LSB, encoding="utf-8")
        keys = ((self.info, "CODENAME"), (self.os_release, "VERSION_CODENAME"), (self.lsb, "DISTRIB_CODENAME"))
        patcher = patch.object(migration, "CODENAME_KEYS", keys)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_rewrites_only_the_codename_lines(self) -> None:
        migration.run(MagicMock(spec=MigrationContext, dry_run=False))

        self.assertEqual(ISO_INFO.replace("CODENAME=wilma", "CODENAME=zena"), self.info.read_text(encoding="utf-8"))
        self.assertEqual(ISO_OS_RELEASE.replace("VERSION_CODENAME=wilma", "VERSION_CODENAME=zena"), self.os_release.read_text(encoding="utf-8"))
        self.assertEqual(ISO_LSB.replace("DISTRIB_CODENAME=wilma", "DISTRIB_CODENAME=zena"), self.lsb.read_text(encoding="utf-8"))
        self.assertIn("UBUNTU_CODENAME=noble", self.os_release.read_text(encoding="utf-8"))

    def test_is_idempotent(self) -> None:
        migration.run(MagicMock(spec=MigrationContext, dry_run=False))
        context = MagicMock(spec=MigrationContext, dry_run=False)
        migration.run(context)
        messages = [entry.args[0] for entry in context.log.call_args_list]
        self.assertEqual(3, sum("already zena" in message for message in messages))

    def test_dry_run_changes_nothing(self) -> None:
        migration.run(MagicMock(spec=MigrationContext, dry_run=True))
        self.assertEqual(ISO_INFO, self.info.read_text(encoding="utf-8"))
        self.assertEqual(ISO_LSB, self.lsb.read_text(encoding="utf-8"))

    def test_missing_file_is_skipped(self) -> None:
        self.lsb.unlink()
        context = MagicMock(spec=MigrationContext, dry_run=False)
        migration.run(context)
        self.assertIn(f"skip missing {self.lsb}", [entry.args[0] for entry in context.log.call_args_list])
        self.assertIn("CODENAME=zena", self.info.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

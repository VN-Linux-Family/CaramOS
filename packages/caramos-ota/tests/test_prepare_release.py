"""Tests for explicit release version stamping."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "tools/prepare-release.py"
SPEC = importlib.util.spec_from_file_location("prepare_release", SCRIPT)
assert SPEC and SPEC.loader
prepare_release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prepare_release)


class PrepareReleaseTests(unittest.TestCase):
    def test_rejects_invalid_version_before_writes(self) -> None:
        with mock.patch.object(prepare_release, "atomic_write") as atomic_write:
            with self.assertRaisesRegex(ValueError, "invalid CaramOS release version"):
                prepare_release.prepare("release-next", check=False)
        atomic_write.assert_not_called()

    def test_stamps_only_release_metadata_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "scripts/config.sh"
            changelog = root / "packages/caramos-ota/debian/changelog"
            release_metadata = root / "packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota/release_metadata.py"
            constants = root / "packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota/constants.py"
            migration = root / "packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/migrations/20260101000000_test/manifest.json"
            for path in (config, changelog, release_metadata, constants, migration):
                path.parent.mkdir(parents=True, exist_ok=True)
            config.write_text('CARAMOS_VERSION="1.0.16"\n', encoding="utf-8")
            changelog.write_text(
                "caramos-ota (1.0.16-0caramos1) noble; urgency=medium\n\n"
                "  * Existing release.\n\n"
                " -- Test <test@example.com>  Wed, 05 Aug 2026 00:00:00 +0700\n",
                encoding="utf-8",
            )
            release_metadata.write_text('PRODUCT_VERSION = "1.0.16"\n', encoding="utf-8")
            constants.write_text('TOOL_VERSION = "1.0.16-0caramos1"\n', encoding="utf-8")
            migration.write_text('{"schema": 2}\n', encoding="utf-8")
            migration_before = migration.read_bytes()

            with (
                mock.patch.object(prepare_release, "ROOT", root),
                mock.patch.object(prepare_release, "CONFIG", config),
                mock.patch.object(prepare_release, "CHANGELOG", changelog),
                mock.patch.object(prepare_release, "RELEASE_METADATA", release_metadata),
                mock.patch.object(prepare_release, "CONSTANTS", constants),
            ):
                prepare_release.prepare("1.0.17", check=False)
                prepare_release.prepare("1.0.17", check=True)

            self.assertIn('CARAMOS_VERSION="1.0.17"', config.read_text(encoding="utf-8"))
            self.assertIn('PRODUCT_VERSION = "1.0.17"', release_metadata.read_text(encoding="utf-8"))
            self.assertIn('TOOL_VERSION = "1.0.17-0caramos1"', constants.read_text(encoding="utf-8"))
            self.assertTrue(changelog.read_text(encoding="utf-8").startswith("caramos-ota (1.0.17-0caramos1)"))
            self.assertEqual(migration_before, migration.read_bytes())

    def test_check_fails_when_metadata_is_not_stamped(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "config.sh"
            changelog = root / "changelog"
            release_metadata = root / "release_metadata.py"
            constants = root / "constants.py"
            config.write_text('CARAMOS_VERSION="1.0.16"\n', encoding="utf-8")
            changelog.write_text("caramos-ota (1.0.16-0caramos1) noble; urgency=medium\n", encoding="utf-8")
            release_metadata.write_text('PRODUCT_VERSION = "1.0.16"\n', encoding="utf-8")
            constants.write_text('TOOL_VERSION = "1.0.16-0caramos1"\n', encoding="utf-8")

            with (
                mock.patch.object(prepare_release, "ROOT", root),
                mock.patch.object(prepare_release, "CONFIG", config),
                mock.patch.object(prepare_release, "CHANGELOG", changelog),
                mock.patch.object(prepare_release, "RELEASE_METADATA", release_metadata),
                mock.patch.object(prepare_release, "CONSTANTS", constants),
            ):
                with self.assertRaisesRegex(RuntimeError, "release metadata is not stamped"):
                    prepare_release.prepare("1.0.17", check=True)


if __name__ == "__main__":
    unittest.main()

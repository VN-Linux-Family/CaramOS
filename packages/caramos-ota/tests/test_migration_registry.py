"""Tests for timestamp migration auto-discovery and planning."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from caramos_ota_update.ledger import applied_ids, bootstrap_ledger, mark_applied
from caramos_ota_update.registry import (
    MigrationRegistryError,
    discover_migrations,
    latest_legacy_release,
    resolve_plan,
)


class MigrationRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_legacy(self, folder: str, from_version: str, to_version: str) -> None:
        directory = self.root / folder
        directory.mkdir()
        (directory / "manifest.json").write_text(
            json.dumps(
                {
                    "schema": 1,
                    "version": to_version,
                    "from_version": from_version,
                    "codename": "noble",
                    "channel": "stable",
                    "summary": f"Legacy {to_version}",
                }
            ),
            encoding="utf-8",
        )
        (directory / "migration.py").write_text(
            f'FROM_VERSION = "{from_version}"\n'
            f'TO_VERSION = "{to_version}"\n'
            f'DESCRIPTION = "Legacy {to_version}"\n'
            "def run(context):\n    context.log('legacy')\n",
            encoding="utf-8",
        )

    def write_timestamp(self, migration_id: str, release: str) -> None:
        directory = self.root / migration_id
        directory.mkdir()
        (directory / "manifest.json").write_text(
            json.dumps(
                {
                    "schema": 2,
                    "release": release,
                    "codename": "noble",
                    "channel": "stable",
                    "summary": migration_id,
                }
            ),
            encoding="utf-8",
        )
        (directory / "migration.py").write_text(
            f'DESCRIPTION = "{migration_id}"\n'
            "def run(context):\n    context.log('timestamp')\n",
            encoding="utf-8",
        )

    def test_bundled_catalog_starts_timestamp_migrations_at_1_0_13(self) -> None:
        catalog = discover_migrations()
        descriptors = {item.migration_id: item for item in catalog}

        self.assertEqual(12, len(catalog))
        self.assertNotIn("v1_0_13", descriptors)
        self.assertEqual("1.0.12", latest_legacy_release(catalog))

        migration = descriptors["20260715090258_install_control_center"]
        self.assertEqual(2, migration.schema)
        self.assertEqual("1.0.13", migration.release)
        self.assertFalse(migration.legacy)

        plan = resolve_plan(
            "1.0.12",
            target_version="1.0.13",
            applied_ids={item.migration_id for item in catalog if item.legacy},
            descriptors=catalog,
        )
        self.assertEqual(
            ["20260715090258_install_control_center"],
            [item.migration_id for item in plan.migrations],
        )

        applied_plan = resolve_plan(
            "1.0.12",
            target_version="1.0.13",
            applied_ids={item.migration_id for item in catalog},
            descriptors=catalog,
        )
        self.assertEqual([], applied_plan.migrations)

    def test_bundled_ledger_bootstrap_at_1_0_12_does_not_infer_timestamp_ids(self) -> None:
        catalog = discover_migrations()
        ledger_path = self.root / "bundled-ledger.json"

        ledger = bootstrap_ledger("1.0.12", catalog, path=ledger_path)

        self.assertEqual(
            {f"v1_0_{version}" for version in range(2, 13)},
            applied_ids(ledger),
        )
        self.assertNotIn("20260715090258_install_control_center", applied_ids(ledger))

    def test_auto_discovers_two_migrations_for_same_release(self) -> None:
        self.write_legacy("v1_0_2", "1.0.1", "1.0.2")
        self.write_timestamp("20260714090000_first_change", "1.0.3")
        self.write_timestamp("20260714090100_second_change", "1.0.3")

        catalog = discover_migrations(self.root)
        plan = resolve_plan("1.0.2", applied_ids={"v1_0_2"}, descriptors=catalog)

        self.assertEqual("1.0.3", plan.target_version)
        self.assertEqual(
            ["20260714090000_first_change", "20260714090100_second_change"],
            [item.migration_id for item in plan.migrations],
        )

    def test_applied_timestamp_migration_does_not_run_again(self) -> None:
        self.write_legacy("v1_0_2", "1.0.1", "1.0.2")
        self.write_timestamp("20260714090000_first_change", "1.0.3")
        self.write_timestamp("20260714090100_second_change", "1.0.3")
        catalog = discover_migrations(self.root)

        plan = resolve_plan(
            "1.0.3",
            applied_ids={"v1_0_2", "20260714090000_first_change"},
            descriptors=catalog,
        )

        self.assertEqual(["20260714090100_second_change"], [item.migration_id for item in plan.migrations])

    def test_applied_timestamp_migrations_still_cover_target_release(self) -> None:
        self.write_legacy("v1_0_2", "1.0.1", "1.0.2")
        self.write_timestamp("20260714090000_first_change", "1.0.3")
        self.write_timestamp("20260714090100_second_change", "1.0.3")
        catalog = discover_migrations(self.root)

        plan = resolve_plan(
            "1.0.2",
            target_version="1.0.3",
            applied_ids={
                "v1_0_2",
                "20260714090000_first_change",
                "20260714090100_second_change",
            },
            descriptors=catalog,
        )

        self.assertEqual("1.0.3", plan.target_version)
        self.assertEqual([], plan.migrations)

    def test_late_migration_for_current_release_is_pending(self) -> None:
        self.write_legacy("v1_0_2", "1.0.1", "1.0.2")
        self.write_timestamp("20260714090000_late_fix", "1.0.2")
        catalog = discover_migrations(self.root)

        plan = resolve_plan("1.0.2", applied_ids={"v1_0_2"}, descriptors=catalog)

        self.assertEqual("1.0.2", plan.target_version)
        self.assertEqual(["20260714090000_late_fix"], [item.migration_id for item in plan.migrations])

    def test_bootstrap_marks_only_legacy_migrations(self) -> None:
        self.write_legacy("v1_0_2", "1.0.1", "1.0.2")
        self.write_timestamp("20260714090000_late_fix", "1.0.2")
        catalog = discover_migrations(self.root)
        ledger_path = self.root / "ledger.json"

        ledger = bootstrap_ledger("1.0.2", catalog, path=ledger_path)

        self.assertEqual({"v1_0_2"}, applied_ids(ledger))
        timestamp = next(item for item in catalog if not item.legacy)
        mark_applied(ledger, timestamp, path=ledger_path)
        self.assertEqual(
            {"v1_0_2", "20260714090000_late_fix"},
            applied_ids(ledger),
        )

    def test_invalid_directory_fails_closed(self) -> None:
        self.write_legacy("v1_0_2", "1.0.1", "1.0.2")
        invalid = self.root / "random_folder"
        invalid.mkdir()
        (invalid / "manifest.json").write_text("{}", encoding="utf-8")

        with self.assertRaisesRegex(MigrationRegistryError, "invalid directory"):
            discover_migrations(self.root)

    def test_missing_timestamp_entrypoint_fails_closed(self) -> None:
        directory = self.root / "20260714090000_missing_entrypoint"
        directory.mkdir()
        (directory / "manifest.json").write_text(
            json.dumps(
                {
                    "schema": 2,
                    "release": "1.0.3",
                    "codename": "noble",
                    "channel": "stable",
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(MigrationRegistryError, "missing migration.py"):
            discover_migrations(self.root)

    def test_legacy_manifest_and_module_must_match(self) -> None:
        self.write_legacy("v1_0_2", "1.0.1", "1.0.2")
        module = self.root / "v1_0_2" / "migration.py"
        module.write_text(
            'FROM_VERSION = "1.0.0"\n'
            'TO_VERSION = "1.0.2"\n'
            'DESCRIPTION = "bad"\n'
            "def run(context):\n    pass\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(MigrationRegistryError, "FROM_VERSION mismatch"):
            discover_migrations(self.root)


if __name__ == "__main__":
    unittest.main()

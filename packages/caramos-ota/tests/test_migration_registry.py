"""Tests for timestamp migration auto-discovery and planning."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from caramos_ota_update.ledger import applied_ids, bootstrap_ledger, load_ledger, mark_applied
from caramos_ota_update.registry import (
    MigrationRegistryError,
    discover_migrations,
    latest_legacy_release,
    resolve_plan,
    version_le,
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

    def write_timestamp(
        self,
        migration_id: str,
        extra_manifest: dict[str, object] | None = None,
        *,
        root: Path | None = None,
    ) -> None:
        directory = (root or self.root) / migration_id
        directory.mkdir()
        manifest = {
            "schema": 2,
            "codename": "noble",
            "channel": "stable",
            "summary": migration_id,
        }
        if extra_manifest:
            manifest.update(extra_manifest)
        (directory / "manifest.json").write_text(
            json.dumps(manifest),
            encoding="utf-8",
        )
        (directory / "migration.py").write_text(
            f'DESCRIPTION = "{migration_id}"\n'
            "def run(context):\n    context.log('timestamp')\n",
            encoding="utf-8",
        )

    def test_bundled_catalog_uses_schema2_timestamps_without_release(self) -> None:
        catalog = discover_migrations()
        descriptors = {item.migration_id: item for item in catalog}

        self.assertEqual(15, len(catalog))
        self.assertNotIn("v1_0_13", descriptors)
        self.assertNotIn("v1_0_14", descriptors)
        self.assertEqual("1.0.12", latest_legacy_release(catalog))

        timestamp_ids = [item.migration_id for item in catalog if not item.legacy]
        self.assertEqual(
            [
                "20260715090258_install_control_center",
                "20260803120000_apply_three_dock_taskbar",
                "20260804223346_change_default_wallpaper",
                "20260805111120_update_taskbar_pins_cleanup_desktop",
            ],
            timestamp_ids,
        )
        for migration_id in timestamp_ids:
            descriptor = descriptors[migration_id]
            self.assertEqual(2, descriptor.schema)
            self.assertIsNone(descriptor.release)
            self.assertFalse(descriptor.legacy)

    def test_unapplied_timestamps_run_lexically_independent_of_target(self) -> None:
        catalog = discover_migrations()
        legacy_ids = {item.migration_id for item in catalog if item.legacy}

        plan = resolve_plan(
            "1.0.12",
            target_version="1.0.13",
            applied_ids=legacy_ids,
            descriptors=catalog,
        )

        self.assertEqual("1.0.13", plan.target_version)
        self.assertEqual(
            [
                "20260715090258_install_control_center",
                "20260803120000_apply_three_dock_taskbar",
                "20260804223346_change_default_wallpaper",
                "20260805111120_update_taskbar_pins_cleanup_desktop",
            ],
            [item.migration_id for item in plan.migrations],
        )

    def test_applied_timestamps_do_not_run_again_even_when_target_is_newer(self) -> None:
        catalog = discover_migrations()
        legacy_ids = {item.migration_id for item in catalog if item.legacy}

        plan = resolve_plan(
            "1.0.15",
            target_version="1.0.16",
            applied_ids=legacy_ids
            | {
                "20260715090258_install_control_center",
                "20260803120000_apply_three_dock_taskbar",
                "20260804223346_change_default_wallpaper",
            },
            descriptors=catalog,
        )

        self.assertEqual(
            ["20260805111120_update_taskbar_pins_cleanup_desktop"],
            [item.migration_id for item in plan.migrations],
        )

    def test_bundled_ledger_bootstrap_at_1_0_12_does_not_infer_timestamp_ids(self) -> None:
        catalog = discover_migrations()
        ledger_path = self.root / "bundled-ledger.json"

        ledger = bootstrap_ledger("1.0.12", catalog, path=ledger_path)

        self.assertEqual(
            {f"v1_0_{version}" for version in range(2, 13)},
            applied_ids(ledger),
        )
        self.assertNotIn("20260715090258_install_control_center", applied_ids(ledger))

    def test_vm_ledger_seed_filters_out_versionless_timestamps(self) -> None:
        catalog = discover_migrations()
        selected = [
            item
            for item in catalog
            if item.legacy and item.release is not None and version_le(item.release, "1.0.12")
        ]

        self.assertEqual(
            {f"v1_0_{version}" for version in range(2, 13)},
            {item.migration_id for item in selected},
        )
        self.assertTrue(all(item.legacy for item in selected))

    def test_auto_discovers_two_timestamps_without_release(self) -> None:
        self.write_legacy("v1_0_2", "1.0.1", "1.0.2")
        self.write_timestamp("20260714090000_first_change")
        self.write_timestamp("20260714090100_second_change")

        catalog = discover_migrations(self.root)
        plan = resolve_plan(
            "1.0.2",
            target_version="1.0.2",
            applied_ids={"v1_0_2"},
            descriptors=catalog,
        )

        self.assertEqual("1.0.2", plan.target_version)
        self.assertEqual(
            ["20260714090000_first_change", "20260714090100_second_change"],
            [item.migration_id for item in plan.migrations],
        )
        self.assertTrue(all(item.release is None for item in plan.migrations))

    def test_applied_timestamp_migration_does_not_run_again(self) -> None:
        self.write_legacy("v1_0_2", "1.0.1", "1.0.2")
        self.write_timestamp("20260714090000_first_change")
        self.write_timestamp("20260714090100_second_change")
        catalog = discover_migrations(self.root)

        plan = resolve_plan(
            "1.0.3",
            target_version="1.0.3",
            applied_ids={"v1_0_2", "20260714090000_first_change"},
            descriptors=catalog,
        )

        self.assertEqual(["20260714090100_second_change"], [item.migration_id for item in plan.migrations])

    def test_applied_timestamp_migrations_keep_target_for_finalization(self) -> None:
        self.write_legacy("v1_0_2", "1.0.1", "1.0.2")
        self.write_timestamp("20260714090000_first_change")
        self.write_timestamp("20260714090100_second_change")
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

    def test_downgrade_target_fails_even_when_timestamps_are_pending(self) -> None:
        self.write_legacy("v1_0_2", "1.0.1", "1.0.2")
        self.write_timestamp("20260714090000_pending_fix")
        catalog = discover_migrations(self.root)

        with self.assertRaisesRegex(MigrationRegistryError, "older than installed version"):
            resolve_plan(
                "1.0.2",
                target_version="1.0.1",
                applied_ids={"v1_0_2"},
                descriptors=catalog,
            )

    def test_bootstrap_marks_only_legacy_migrations_and_timestamp_record_omits_release(self) -> None:
        self.write_legacy("v1_0_2", "1.0.1", "1.0.2")
        self.write_timestamp("20260714090000_late_fix")
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
        timestamp_record = ledger["applied_migrations"][-1]
        self.assertEqual("20260714090000_late_fix", timestamp_record["id"])
        self.assertNotIn("release", timestamp_record)

    def test_old_ledger_records_with_release_remain_readable(self) -> None:
        ledger_path = self.root / "old-ledger.json"
        ledger_path.write_text(
            json.dumps(
                {
                    "schema": 1,
                    "applied_migrations": [
                        {
                            "id": "20260714090000_old_timestamp",
                            "release": "1.0.13",
                            "applied_at": "2026-07-14T09:00:00+00:00",
                            "source": "old",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        ledger = load_ledger(ledger_path)

        self.assertIsNotNone(ledger)
        self.assertEqual({"20260714090000_old_timestamp"}, applied_ids(ledger or {}))

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
                    "codename": "noble",
                    "channel": "stable",
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(MigrationRegistryError, "missing migration.py"):
            discover_migrations(self.root)

    def test_timestamp_manifest_must_not_contain_version_fields(self) -> None:
        for field in ("release", "version", "from_version", "to_version"):
            with self.subTest(field=field):
                root = self.root / field
                root.mkdir()
                self.write_timestamp(
                    "20260714090000_bad_timestamp",
                    {field: "1.0.3"},
                    root=root,
                )

                with self.assertRaisesRegex(MigrationRegistryError, f"must not contain: {field}"):
                    discover_migrations(root)

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

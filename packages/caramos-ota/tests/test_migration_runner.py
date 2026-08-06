"""Tests for migration execution and release metadata recovery."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from caramos_ota_update.registry import MigrationDescriptor
from caramos_ota_update.runner import MigrationRunner


class MigrationRunnerTests(unittest.TestCase):
    def test_runs_bundled_timestamp_migration_and_finalizes_release(self) -> None:
        context = MagicMock()
        context.dry_run = False
        runner = MigrationRunner(context=context)
        legacy_ids = {f"v1_0_{version}" for version in range(2, 13)}
        ledger = {
            "schema": 1,
            "applied_migrations": [
                {"id": migration_id, "release": "1.0.12"}
                for migration_id in sorted(legacy_ids)
            ]
            + [
                {
                    "id": "20260715090258_install_control_center",
                    "release": "1.0.13",
                },
                {
                    "id": "20260803120000_apply_three_dock_taskbar",
                    "release": "1.0.14",
                },
                {
                    "id": "20260804223346_change_default_wallpaper",
                    "release": "1.0.15",
                },
            ],
        }

        with (
            patch("caramos_ota_update.runner.bootstrap_ledger", return_value=ledger),
            patch("caramos_ota_update.runner.start_transaction", return_value="timestamp-batch") as start,
            patch("caramos_ota_update.runner.mark_transaction_success") as success,
            patch("caramos_ota_update.runner.mark_migration_running"),
            patch("caramos_ota_update.runner.mark_migration_complete"),
            patch("caramos_ota_update.runner.mark_applied"),
            patch.object(runner, "_run_one") as run_one,
        ):
            runner.run(current_version="1.0.15", target_version="1.0.16")

        start.assert_called_once_with(
            target_version="1.0.16",
            migration_ids=["20260805111120_update_taskbar_pins_cleanup_desktop"],
        )
        run_one.assert_called_once()
        self.assertEqual(
            "20260805111120_update_taskbar_pins_cleanup_desktop",
            run_one.call_args.args[0].migration_id,
        )
        context.update_release_file.assert_called_once_with("1.0.16")
        success.assert_called_once_with(
            transaction_id="timestamp-batch",
            installed_version="1.0.16",
        )

    def test_finalizes_release_when_target_migrations_are_already_applied(self) -> None:
        migration = MigrationDescriptor(
            migration_id="20260714090000_first_change",
            release="1.0.3",
            description="First change",
            source="test",
            directory=Path("/tmp/20260714090000_first_change"),
            module_path=Path("/tmp/20260714090000_first_change/migration.py"),
            schema=2,
            codename="noble",
            channel="stable",
            severity="normal",
            size="migration update",
            title="Update",
            summary="First change",
            release_notes_vi=[],
            release_notes_en=[],
        )
        ledger = {
            "schema": 1,
            "applied_migrations": [
                {"id": migration.migration_id, "release": migration.release},
            ],
        }
        context = MagicMock()
        context.dry_run = False
        runner = MigrationRunner(context=context)
        runner.discover = MagicMock(return_value=[migration])

        with (
            patch("caramos_ota_update.runner.bootstrap_ledger", return_value=ledger),
            patch("caramos_ota_update.runner.start_transaction", return_value="recovery") as start,
            patch("caramos_ota_update.runner.mark_transaction_success") as success,
        ):
            runner.run(current_version="1.0.2", target_version="1.0.3")

        start.assert_called_once_with(target_version="1.0.3", migration_ids=[])
        context.update_release_file.assert_called_once_with("1.0.3")
        success.assert_called_once_with(
            transaction_id="recovery",
            installed_version="1.0.3",
        )


if __name__ == "__main__":
    unittest.main()

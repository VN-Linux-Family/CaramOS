"""Tests for restoring power-profiles-daemon through OTA."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

from caramos_ota_update.context import MigrationContext

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "usr/lib/python3/dist-packages/caramos_ota_update/migrations"
    / "20260808090000_restore_power_profiles_daemon/migration.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("power_profiles_migration_test", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load migration module: {MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = load_migration()


class PowerProfilesMigrationTests(unittest.TestCase):
    def test_uses_safe_helpers_in_transaction_order(self) -> None:
        context = MagicMock(spec=MigrationContext)

        migration.run(context)

        self.assertTrue(migration.DESCRIPTION)
        self.assertEqual(
            [
                call.apt_update(),
                call.apt_replace(
                    install=["power-profiles-daemon"],
                    remove=["tlp", "tlp-rdw"],
                ),
                call.ensure_service_enabled("power-profiles-daemon.service"),
            ],
            context.method_calls,
        )
        context.apt_install.assert_not_called()
        context.apt_remove.assert_not_called()

    def test_apt_replace_uses_one_atomic_transaction(self) -> None:
        context = MigrationContext()

        with patch.object(context, "run_command") as run_command:
            context.apt_replace(
                install=["power-profiles-daemon"],
                remove=["tlp", "tlp-rdw"],
            )

        run_command.assert_called_once_with(
            [
                "apt-get",
                "install",
                "--yes",
                "--",
                "power-profiles-daemon",
                "tlp-",
                "tlp-rdw-",
            ]
        )

    def test_dry_run_does_not_execute_subprocesses(self) -> None:
        context = MigrationContext(dry_run=True)

        with patch("caramos_ota_update.context.subprocess.run") as run:
            migration.run(context)

        run.assert_not_called()

    def test_migration_can_be_retried(self) -> None:
        context = MagicMock(spec=MigrationContext)

        migration.run(context)
        migration.run(context)

        self.assertEqual(2, context.apt_update.call_count)
        self.assertEqual(2, context.apt_replace.call_count)
        self.assertEqual(2, context.ensure_service_enabled.call_count)


if __name__ == "__main__":
    unittest.main()

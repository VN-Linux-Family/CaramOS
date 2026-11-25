"""Migration 20261012120000_add_driver_check installs hw-probe without its recommends."""

from __future__ import annotations

import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext, MigrationContextError

MIGRATION_ID = "20261012120000_add_driver_check"
migration = importlib.import_module(f"caramos_ota_update.migrations.{MIGRATION_ID}.migration")
MANIFEST = Path(migration.__file__).with_name("manifest.json")


class DriverCheckMigrationTests(unittest.TestCase):
    def test_installs_hw_probe_without_recommends(self) -> None:
        context = MigrationContext()
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(migration, "COMMAND", Path(temp) / "hw-probe"), \
                mock.patch.object(context, "run_command") as run:
            migration.run(context)
        run.assert_called_once_with(["apt-get", "-o", "Dpkg::Options::=--force-confdef",
                                     "-o", "Dpkg::Options::=--force-confold", "-o", "DPkg::Lock::Timeout=120", "install", "--yes",
                                     "--no-install-recommends", "--", "hw-probe"], env=mock.ANY)

    def test_nothing_to_do_when_hw_probe_is_installed(self) -> None:
        context = MigrationContext()
        with tempfile.NamedTemporaryFile() as command, \
                mock.patch.object(migration, "COMMAND", Path(command.name)), \
                mock.patch.object(context, "run_command") as run:
            migration.run(context)
        run.assert_not_called()

    def test_a_failed_install_does_not_fail_the_update(self) -> None:
        context = MigrationContext()
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(migration, "COMMAND", Path(temp) / "hw-probe"), \
                mock.patch.object(context, "run_command", side_effect=MigrationContextError("exit code 100")), \
                mock.patch.object(context, "log") as log:
            migration.run(context)
        self.assertIn("could not install hw-probe", log.call_args.args[0])

    def test_dry_run_changes_nothing(self) -> None:
        context = MigrationContext(dry_run=True)
        with tempfile.TemporaryDirectory() as temp, \
                mock.patch.object(migration, "COMMAND", Path(temp) / "hw-probe"), \
                mock.patch("subprocess.run") as run:
            migration.run(context)
        run.assert_not_called()

    def test_apt_install_keeps_recommends_by_default(self) -> None:
        context = MigrationContext()
        with mock.patch.object(context, "run_command") as run:
            context.apt_install(["earlyoom"])
        run.assert_called_once_with(["apt-get", "-o", "Dpkg::Options::=--force-confdef",
                                     "-o", "Dpkg::Options::=--force-confold", "-o", "DPkg::Lock::Timeout=120", "install", "--yes", "--",
                                     "earlyoom"], env=mock.ANY)
        env = run.call_args.kwargs["env"]
        self.assertEqual(("noninteractive", "1"), (env["DEBIAN_FRONTEND"], env["UCF_FORCE_CONFFOLD"]))
        self.assertEqual(os.environ["PATH"], env["PATH"])

    def test_manifest_announces_driver_check_in_both_languages(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual("feature", manifest["severity"])
        self.assertIn("Kiểm tra driver", manifest["title"])
        self.assertIn("Driver Check", manifest["title_en"])
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))


if __name__ == "__main__":
    unittest.main()

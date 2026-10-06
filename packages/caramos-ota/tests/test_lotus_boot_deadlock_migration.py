"""Tests for the Lotus enable service boot deadlock fix."""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from caramos_ota_update.context import MigrationContext

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "usr/lib/python3/dist-packages/caramos_ota_update/migrations"
    / "20261006090100_fix_lotus_boot_deadlock/migration.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("fix_lotus_boot_deadlock_test", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = load_migration()
TEMPLATE = "/usr/lib/systemd/system/fcitx5-lotus-server@.service"


class LotusBootDeadlockTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.helper = root / "usr/local/sbin/caramos-fcitx5-lotus-system-enable"
        self.service = root / "etc/systemd/system/caramos-fcitx5-lotus-system-enable.service"
        self.wants = root / "etc/systemd/system/multi-user.target.wants"
        self.runtime = root / "run/systemd/system"
        self.wants.mkdir(parents=True)
        for user in ("caram", "dungleviet", "runner"):
            (self.wants / f"fcitx5-lotus-server@{user}.service").symlink_to(TEMPLATE)
        patches = {
            "SYSTEM_ENABLE_HELPER": self.helper,
            "SYSTEM_ENABLE_SERVICE": self.service,
            "WANTS_DIR": self.wants,
            "SYSTEMD_RUNTIME": self.runtime,
            "_user_exists": lambda name: name == "caram",
        }
        for name, value in patches.items():
            patcher = patch.object(migration, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_migration(self, *, dry_run: bool = False, state: str = "active") -> list[list[str]]:
        context = MigrationContext(dry_run=dry_run)
        calls: list[list[str]] = []

        def fake_run(args, **_kwargs):
            calls.append(list(args))
            stdout = f"{state}\n" if args[:2] == ["systemctl", "show"] else ""
            return subprocess.CompletedProcess(list(args), 0, stdout, "")

        with patch.object(context, "run_command", side_effect=fake_run):
            migration.run(context)
        return calls

    def test_helper_no_longer_waits_for_the_server_start_job(self) -> None:
        script = migration.SYSTEM_ENABLE_HELPER_SCRIPT
        self.assertIn('systemctl enable --now --no-block "fcitx5-lotus-server@${user}.service"', script)
        self.assertNotRegex(script.replace("--now --no-block", ""), r"systemctl enable --now ")
        self.assertIn("TimeoutStartSec=", migration.SYSTEM_ENABLE_SERVICE_CONFIG)

    def test_iso_build_writes_files_and_drops_build_machine_users(self) -> None:
        calls = self.run_migration()  # no /run/systemd/system: ISO build chroot

        self.assertEqual(migration.SYSTEM_ENABLE_HELPER_SCRIPT, self.helper.read_text(encoding="utf-8"))
        self.assertEqual(0o755, self.helper.stat().st_mode & 0o777)
        self.assertEqual(migration.SYSTEM_ENABLE_SERVICE_CONFIG, self.service.read_text(encoding="utf-8"))
        self.assertEqual(["fcitx5-lotus-server@caram.service"], sorted(p.name for p in self.wants.iterdir()))
        self.assertEqual([], calls)

    def test_running_system_stops_the_stuck_oneshot_and_reruns_the_helper(self) -> None:
        self.runtime.mkdir(parents=True)

        calls = self.run_migration(state="activating")

        self.assertIn(["systemctl", "daemon-reload"], calls)
        self.assertIn(["systemctl", "kill", migration.SERVICE_NAME], calls)
        self.assertIn(["systemctl", "reset-failed", migration.SERVICE_NAME], calls)
        for user in ("dungleviet", "runner"):
            self.assertIn(["systemctl", "stop", "--no-block", f"fcitx5-lotus-server@{user}.service"], calls)
            self.assertIn(["systemctl", "reset-failed", f"fcitx5-lotus-server@{user}.service"], calls)
        self.assertNotIn(["systemctl", "stop", "--no-block", "fcitx5-lotus-server@caram.service"], calls)
        self.assertEqual([str(self.helper)], calls[-1])

    def test_oneshot_stopped_by_the_new_timeout_is_reset(self) -> None:
        # daemon-reload applies TimeoutStartSec to the job stuck since boot, which fails it.
        self.runtime.mkdir(parents=True)

        calls = self.run_migration(state="failed")

        self.assertNotIn(["systemctl", "kill", migration.SERVICE_NAME], calls)
        self.assertIn(["systemctl", "reset-failed", migration.SERVICE_NAME], calls)
        self.assertEqual([str(self.helper)], calls[-1])

    def test_running_system_that_already_booted_is_not_killed(self) -> None:
        self.runtime.mkdir(parents=True)

        calls = self.run_migration(state="inactive")

        self.assertNotIn(["systemctl", "kill", migration.SERVICE_NAME], calls)
        self.assertEqual([str(self.helper)], calls[-1])

    def test_dry_run_changes_nothing(self) -> None:
        self.runtime.mkdir(parents=True)
        with patch("caramos_ota_update.context.subprocess.run") as run:
            migration.run(MigrationContext(dry_run=True))
        run.assert_not_called()
        self.assertFalse(self.helper.exists())
        self.assertEqual(3, len(list(self.wants.iterdir())))

    def test_second_run_writes_nothing(self) -> None:
        self.run_migration()
        before = self.helper.stat().st_mtime_ns
        self.run_migration()
        self.assertEqual(before, self.helper.stat().st_mtime_ns)


if __name__ == "__main__":
    unittest.main()

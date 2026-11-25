"""Migration 20261125120000_computer_lab_stays_connected: on a Phòng máy computer, Veyon Server comes back by itself
(caramos-lab-veyon-check.timer) and a student's accounts stop locking and sleeping (caramos-lab --session); a computer
that left the lab with an older Phòng máy stops starting Veyon Server at boot."""

from __future__ import annotations

import importlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from caramos_ota_update.context import MigrationContext

migration = importlib.import_module(
    "caramos_ota_update.migrations.20261125120000_computer_lab_stays_connected.migration")


class FakeContext(MigrationContext):
    def __init__(self, dry_run: bool = False, fail: tuple[str, ...] = (), enabled: str = "enabled",
                 method: str = "0") -> None:
        super().__init__(dry_run=dry_run)
        self.fail = fail
        self.enabled = enabled
        self.method = method
        self.commands: list[tuple[list[str], dict | None]] = []
        self.logs: list[str] = []

    def log(self, message: str) -> None:
        self.logs.append(message)

    def run_command(self, args, *, allow_fail=False, env=None):  # noqa: ANN001, ANN201 - the context's signature
        args = [str(part) for part in args]
        if self.dry_run:
            return None
        self.commands.append((args, env))
        code = 1 if any(word in args for word in self.fail) else 0
        out = "awake: gsettings org.cinnamon.desktop.session idle-delay" if args[-1] == "--session" else ""
        if args[:2] == ["systemctl", "is-enabled"]:
            out = self.enabled + "\n"
        elif args[:3] == ["veyon-cli", "config", "get"]:
            out = self.method + "\n"
        return subprocess.CompletedProcess(args, code, out, "failed" if code else "")


class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state = self.root / "lab/state.json"
        self.keys = self.root / "keys"
        self.runtime = self.root / "run-user"
        self.users = [("hocsinh", 1000, self.root / "home/hocsinh"), ("giaovien", 1001, self.root / "home/giaovien")]
        (self.runtime / "1000").mkdir(parents=True)
        (self.runtime / "1000/bus").touch()  # hocsinh is logged in, giaovien is not

    def lab(self, **state) -> None:
        self.state.parent.mkdir(parents=True, exist_ok=True)
        self.state.write_text(json.dumps(state), encoding="utf-8")

    def left_lab(self) -> None:
        """What leaving with Phòng máy up to 1.5.1 left: its folder, no state, no key, logon authentication."""

        self.state.parent.mkdir(parents=True, exist_ok=True)

    def run_migration(self, context: FakeContext) -> list[list[str]]:
        migration.run(context, state_path=self.state, users=self.users, runtime_root=self.runtime, keys=self.keys)
        return [command for command, _env in context.commands]

    def test_not_a_lab_computer(self) -> None:
        context = FakeContext()
        self.assertEqual([], self.run_migration(context))
        self.assertIn("not a computer of a Phòng máy lab", context.logs[-1])

    def test_a_computer_that_left_the_lab_stops_starting_veyon(self) -> None:
        self.left_lab()
        context = FakeContext()
        commands = self.run_migration(context)
        self.assertEqual(["systemctl", "disable", "--now", "veyon.service"], commands[-1])
        self.assertIn("no longer starts at boot", context.logs[-1])

    def test_veyon_someone_else_set_up_is_left_alone(self) -> None:
        self.left_lab()
        for context in (FakeContext(enabled="disabled"), FakeContext(method="1")):
            self.assertNotIn(["systemctl", "disable", "--now", "veyon.service"], self.run_migration(context))
        key = self.keys / "public/giaovien/key"
        key.parent.mkdir(parents=True)
        key.write_text("-----BEGIN PUBLIC KEY-----\n", encoding="utf-8")
        context = FakeContext()
        self.assertNotIn(["systemctl", "disable", "--now", "veyon.service"], self.run_migration(context))
        self.assertIn("key is still here", context.logs[-1])

    def test_veyon_student(self) -> None:
        self.lab(role="student", backend="veyon", room="Phòng máy 1")
        context = FakeContext()
        commands = self.run_migration(context)
        self.assertEqual(["systemctl", "enable", "--now", "caramos-lab-veyon-check.timer"], commands[0])
        self.assertEqual([["runuser", "-u", "hocsinh", "--", "/usr/bin/caramos-lab", "--session"]], commands[1:],
                         "only the logged-in account now; the others at their next login")
        env = context.commands[1][1]
        self.assertEqual("unix:path=" + str(self.runtime / "1000/bus"), env["DBUS_SESSION_BUS_ADDRESS"])
        self.assertEqual(str(self.root / "home/hocsinh"), env["HOME"])
        self.assertTrue(any("giaovien is not logged in" in line for line in context.logs))

    def test_veyon_teacher_keeps_its_screen_lock(self) -> None:
        self.lab(role="teacher", backend="veyon")
        commands = self.run_migration(FakeContext())
        self.assertEqual([["systemctl", "enable", "--now", "caramos-lab-veyon-check.timer"]], commands)

    def test_epoptes_student_has_no_veyon_check(self) -> None:
        self.lab(role="student", backend="epoptes")
        commands = self.run_migration(FakeContext())
        self.assertEqual([["runuser", "-u", "hocsinh", "--", "/usr/bin/caramos-lab", "--session"]], commands)

    def test_failures_are_warnings(self) -> None:
        self.lab(role="student", backend="veyon")
        context = FakeContext(fail=("--now", "--session"))
        self.run_migration(context)  # does not raise: the rest of the update goes on
        self.assertEqual(2, sum(line.startswith("warning:") for line in context.logs))

    def test_a_dry_run_changes_nothing(self) -> None:
        self.lab(role="student", backend="veyon")
        context = FakeContext(dry_run=True)
        self.assertEqual([], self.run_migration(context))
        self.assertTrue(any("would" in line for line in context.logs))

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("desktops", manifest, "Phòng máy is on both editions")
        self.assertEqual("anytime", manifest["unattended"])  # nothing changes on the screen
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertIn("màu cam", manifest["release_notes_vi"][0])


if __name__ == "__main__":
    unittest.main()

"""What a migration leaves for later (caramos_ota_update.deferred): the visible part of a migration that an automatic
update runs while someone works waits for that user's next login, and `dconf update` for the next start."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from caramos_ota_update import deferred
from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).resolve().parents[1]
TRASH = "20261124140000_show_trash_on_desktop"
SHOW_DESKTOP = "20261124100000_show_desktop_button"


def context(unattended: bool = True, dry_run: bool = False) -> MigrationContext:
    made = MigrationContext(dry_run=dry_run, unattended=unattended)
    made.log = mock.Mock()   # type: ignore[method-assign]
    return made


class Folder(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.queue = self.root / "var/lib/caramos-ota/login-actions"
        self.runtime = self.root / "run/user"

    def log_in(self, uid: int) -> None:
        (self.runtime / str(uid)).mkdir(parents=True, exist_ok=True)
        (self.runtime / str(uid) / "bus").touch()


class QueueTests(Folder):
    def test_an_automatic_update_queues_the_step_of_a_logged_in_user(self) -> None:
        self.log_in(1000)
        made = context()
        self.assertTrue(deferred.wait_for_login(made, TRASH, "trash-icon", "minh", 1000, runtime_root=self.runtime,
                                                queue_dir=self.queue))
        path = self.queue / "1000.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual({"schema": 1, "user": "minh"}, {key: data[key] for key in ("schema", "user")})
        self.assertEqual([(TRASH, "trash-icon")], [(entry["migration"], entry["action"]) for entry in data["actions"]])
        self.assertEqual(0o644, path.stat().st_mode & 0o777, "the user's login reads it")
        self.assertIn("waits for their next login", made.log.call_args.args[0])

    def test_otherwise_the_migration_changes_it_now(self) -> None:
        self.log_in(1000)
        for made, uid in ((context(unattended=False), 1000), (context(), 1001)):
            with self.subTest(unattended=made.unattended, uid=uid):
                self.assertFalse(deferred.wait_for_login(made, TRASH, "trash-icon", "minh", uid,
                                                         runtime_root=self.runtime, queue_dir=self.queue))
        self.assertFalse(self.queue.exists())

    def test_a_dry_run_only_says_so(self) -> None:
        self.log_in(1000)
        made = context(dry_run=True)
        self.assertTrue(deferred.wait_for_login(made, TRASH, "trash-icon", "minh", 1000, runtime_root=self.runtime,
                                                queue_dir=self.queue))
        self.assertFalse(self.queue.exists())

    def test_a_step_is_queued_once_and_steps_add_up(self) -> None:
        made = context()
        for migration, action in ((TRASH, "trash-icon"), (TRASH, "trash-icon"), (SHOW_DESKTOP, "corner-bar")):
            deferred.queue_for_login(made, migration, action, "minh", 1000, queue_dir=self.queue)
        data = json.loads((self.queue / "1000.json").read_text(encoding="utf-8"))
        self.assertEqual([TRASH, SHOW_DESKTOP], [entry["migration"] for entry in data["actions"]])

    def test_another_account_with_the_same_uid_starts_afresh(self) -> None:
        made = context()
        deferred.queue_for_login(made, TRASH, "trash-icon", "old", 1000, queue_dir=self.queue)
        deferred.queue_for_login(made, SHOW_DESKTOP, "corner-bar", "minh", 1000, queue_dir=self.queue)
        data = json.loads((self.queue / "1000.json").read_text(encoding="utf-8"))
        self.assertEqual("minh", data["user"])
        self.assertEqual([SHOW_DESKTOP], [entry["migration"] for entry in data["actions"]])

    def test_dconf_update_waits_for_the_next_start(self) -> None:
        flag = self.root / "dconf-update-pending"
        deferred.dconf_update_at_next_start(context(dry_run=True), flag)
        self.assertFalse(flag.exists())
        deferred.dconf_update_at_next_start(context(), flag)
        self.assertTrue(flag.is_file())


class Session(deferred.Session):
    """A login that records its commands and answers them from a table."""

    def __init__(self, answers: dict[tuple[str, ...], str] | None = None, desktop: str = "cinnamon",
                 home: Path = Path("/home/minh")) -> None:
        super().__init__("minh", 1000, home, desktop, environ={})
        self.answers = answers or {}
        self.commands: list[list[str]] = []

    def run(self, args, timeout=deferred.COMMAND_TIMEOUT):  # noqa: ANN001
        self.commands.append(list(args))
        for prefix, out in self.answers.items():
            if tuple(args[:len(prefix)]) == prefix:
                return subprocess.CompletedProcess(args, 0, out, "")
        return subprocess.CompletedProcess(args, 0, "", "")

    def log(self, message: str) -> None:
        self.messages.append(message)


class LoginTests(Folder):
    def setUp(self) -> None:
        super().setUp()
        self.state = self.root / "home/minh/.local/state/caramos/login-actions.json"

    def queue_steps(self, *steps: tuple[str, str], user: str = "minh") -> None:
        for migration, action in steps:
            deferred.queue_for_login(context(), migration, action, user, 1000, queue_dir=self.queue)

    def login(self, session: Session) -> int:
        return deferred.run_pending(session, queue_dir=self.queue, state_path=self.state)

    def test_the_next_login_runs_each_step_once(self) -> None:
        self.queue_steps((TRASH, "trash-icon"))
        session = Session({("gsettings", "get"): "false\n"})
        self.assertEqual(1, self.login(session))
        self.assertEqual(["gsettings", "set", "org.nemo.desktop", "trash-icon-visible", "true"], session.commands[-1])
        self.assertEqual(0o600, self.state.stat().st_mode & 0o777)
        again = Session({("gsettings", "get"): "false\n"})
        self.assertEqual(0, self.login(again))
        self.assertEqual([], again.commands, "a user who hides the Trash later keeps it hidden")

    def test_both_migrations_at_one_login(self) -> None:
        self.queue_steps((SHOW_DESKTOP, "corner-bar"), (TRASH, "trash-icon"))
        applets = ("['panel1:right:0:systray@cinnamon.org:2', 'panel1:right:1:caramos-control-center@caramos:0', "
                   "'panel1:right:2:caramos-help@caramos:8']")
        session = Session({("gsettings", "get", "org.cinnamon"): applets + "\n",
                           ("gsettings", "get", "org.nemo.desktop"): "false\n"})
        self.assertEqual(2, self.login(session))
        sets = [command for command in session.commands if command[1] == "set"]
        self.assertIn("cornerbar@cinnamon.org", sets[0][-1])
        self.assertEqual("true", sets[1][-1])

    def test_a_failing_step_is_tried_at_the_next_logins_then_given_up(self) -> None:
        self.queue_steps((TRASH, "trash-icon"))
        broken = mock.Mock(side_effect=RuntimeError("no D-Bus"))
        with mock.patch.object(deferred, "find_action", return_value=broken):
            for _login in range(deferred.MAX_TRIES + 1):
                self.assertEqual(0, self.login(Session()))
        self.assertEqual(deferred.MAX_TRIES, broken.call_count)
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertTrue(state["done"][f"{TRASH}/trash-icon"].endswith("failed"))

    def test_a_step_this_version_does_not_have_is_skipped(self) -> None:
        self.queue_steps(("20991231000000_gone", "something"), (TRASH, "no-such-step"))
        session = Session()
        self.assertEqual(0, self.login(session))
        self.assertEqual([], session.commands)
        self.assertEqual(2, len(json.loads(self.state.read_text(encoding="utf-8"))["done"]))

    def test_steps_of_another_account_with_this_uid_are_not_run(self) -> None:
        self.queue_steps((TRASH, "trash-icon"), user="old")
        session = Session({("gsettings", "get"): "false\n"})
        self.assertEqual(0, self.login(session))
        self.assertEqual([], session.commands)

    def test_old_steps_expire(self) -> None:
        self.queue_steps((TRASH, "trash-icon"))
        later = deferred._now() + deferred.MAX_AGE + timedelta(days=1)
        self.assertEqual([], deferred.pending("minh", 1000, queue_dir=self.queue, now=later))
        self.assertEqual(1, len(deferred.pending("minh", 1000, queue_dir=self.queue)))

    def test_only_steps_a_migration_names(self) -> None:
        self.assertIsNone(deferred.find_action("../../etc", "x"))
        self.assertIsNone(deferred.find_action(TRASH, "../x"))
        self.assertIsNone(deferred.find_action(TRASH, "run"))
        self.assertIsNotNone(deferred.find_action(TRASH, "trash-icon"))

    def test_the_login_command(self) -> None:
        with mock.patch.object(os, "getuid", return_value=0), mock.patch.object(deferred, "run_pending") as run:
            self.assertEqual(0, deferred.main([], queue_dir=self.queue))
        run.assert_not_called()
        user = SimpleNamespace(pw_name="minh", pw_dir=str(self.root / "home/minh"))
        with mock.patch.object(os, "getuid", return_value=1000), mock.patch.object(deferred.pwd, "getpwuid",
                                                                                 return_value=user), \
                mock.patch.object(deferred, "run_pending") as run:
            self.assertEqual(0, deferred.main([], queue_dir=self.queue))
            run.assert_not_called()   # nothing queued for this user
            self.queue_steps((TRASH, "trash-icon"))
            run.side_effect = RuntimeError("bug")
            with mock.patch("sys.stderr"):
                self.assertEqual(0, deferred.main([], queue_dir=self.queue), "the login goes on")
            self.assertEqual("minh", run.call_args.args[0].username)
        with mock.patch("sys.stderr"):
            self.assertEqual(2, deferred.main(["--now"], queue_dir=self.queue))

    def test_the_session_desktop(self) -> None:
        self.assertEqual("cinnamon", deferred.session_desktop({"XDG_CURRENT_DESKTOP": "X-Cinnamon"}))
        self.assertEqual("xfce", deferred.session_desktop({"XDG_CURRENT_DESKTOP": "XFCE", "DESKTOP_SESSION": "xfce"}))
        with mock.patch.object(deferred, "current_desktop", return_value="other"):
            self.assertEqual("other", deferred.session_desktop({}))

    def test_a_command_that_cannot_run_fails_without_an_exception(self) -> None:
        session = deferred.Session("minh", 1000, Path("/home/minh"), "cinnamon", environ={"PATH": "/nonexistent"})
        self.assertEqual(127, session.run(["caramos-no-such-command"]).returncode)


class PackagingTests(unittest.TestCase):
    def test_the_xsession_hook_runs_before_the_desktop_only_when_something_waits(self) -> None:
        hook = ROOT / "etc/X11/Xsession.d/96caramos-login-actions"
        text = hook.read_text(encoding="utf-8")
        # After 95dbus_update-activation-env (xfconfd started through D-Bus gets the session's XDG_CONFIG_DIRS),
        # before 99x11-common_start starts the desktop.
        self.assertTrue("95dbus_update-activation-env" < hook.name < "99mint" < "99x11-common_start")
        self.assertIn('[ -e "/var/lib/caramos-ota/login-actions/$(id -u).json" ]', text)
        # Xsession runs with set -e: nothing here may fail the login, nor hang it.
        self.assertIn("timeout 60 /usr/share/caramos-ota/login/caramos-login-actions </dev/null || true", text)
        self.assertEqual(0, subprocess.run(["sh", "-n", str(hook)], check=False).returncode)
        command = ROOT / "usr/share/caramos-ota/login/caramos-login-actions"
        self.assertTrue(command.stat().st_mode & 0o111)
        self.assertIn("from caramos_ota_update.deferred import main", command.read_text(encoding="utf-8"))
        self.assertEqual(deferred.LOGIN_COMMAND, "/" + str(command.relative_to(ROOT)))

    def test_dconf_update_runs_at_a_start_before_anyone_logs_in(self) -> None:
        unit = (ROOT / "usr/lib/systemd/system/caramos-ota-dconf-update.service").read_text(encoding="utf-8")
        self.assertIn(f"ConditionPathExists={deferred.DCONF_FLAG}\n", unit)
        self.assertIn("Before=systemd-user-sessions.service display-manager.service\n", unit)
        self.assertIn("ExecStart=/usr/bin/dconf update\n", unit)
        self.assertIn(f"ExecStartPost=/usr/bin/rm -f {deferred.DCONF_FLAG}\n", unit)
        rules = (ROOT / "debian/rules").read_text(encoding="utf-8")
        # Enabled, and never started by the package: Cinnamon dies under `dconf update`.
        self.assertIn("\tdh_installsystemd --no-start --no-stop-on-upgrade caramos-ota-dconf-update.service\n", rules)

    def test_debian_install_ships_them(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        for line in ("etc/X11/Xsession.d/96caramos-login-actions etc/X11/Xsession.d/",
                     "usr/share/caramos-ota/login usr/share/caramos-ota/",
                     "usr/lib/systemd/system/caramos-ota-dconf-update.service usr/lib/systemd/system/"):
            self.assertIn(line + "\n", install)

    def test_every_queued_step_is_a_login_action_of_its_migration(self) -> None:
        # The migrations name their steps in constants; each one must be in LOGIN_ACTIONS.
        migrations = ROOT / "usr/lib/python3/dist-packages/caramos_ota_update/migrations"
        for source in sorted(migrations.glob("2*/migration.py")):
            text = source.read_text(encoding="utf-8")
            if "deferred.wait_for_login(" not in text:
                continue
            with self.subTest(migration=source.parent.name):
                self.assertIsNotNone(re.search(r"^LOGIN_ACTIONS = \{", text, re.M))
                steps = re.findall(r'^[A-Z_]*STEP = "([a-z0-9-]+)"', text, re.M)
                self.assertTrue(steps)
                for step in steps:
                    self.assertIsNotNone(deferred.find_action(source.parent.name, step), step)


if __name__ == "__main__":
    unittest.main()

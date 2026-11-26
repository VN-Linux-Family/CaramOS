"""CaramOS Xfce: notifications at the bottom right (ticket H-1219). The system default, and each account still at the
stock top right that xfce4-notifyd 0.9 wrote into it."""

from __future__ import annotations

import importlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext

migration = importlib.import_module(
    "caramos_ota_update.migrations.20261126200100_xfce_notifications_bottom_right.migration")
FOLDER = Path(migration.__file__).parent

# What xfce4-notifyd 0.9.4 wrote into a CaramOS 1.5.2 Xfce account (caramxfce1.5.2, 2026-11-26).
USER_1_5_2 = """<?xml version="1.0" encoding="UTF-8"?>

<channel name="xfce4-notifyd" version="1.0">
  <property name="notify-location" type="string" value="top-right"/>
  <property name="theme" type="empty"/>
  <property name="show-notifications-on" type="string" value="active-monitor"/>
</channel>
"""


class DefaultsTests(unittest.TestCase):
    def test_a_new_file(self) -> None:
        text = migration.defaults_updated(None)
        self.assertIn('<property name="notify-location" type="string" value="bottom-right"/>', text)
        self.assertIn('<channel name="xfce4-notifyd" version="1.0">', text)

    def test_the_old_default_moves(self) -> None:
        self.assertEqual(USER_1_5_2.replace('value="top-right"', 'value="bottom-right"'),
                         migration.defaults_updated(USER_1_5_2))

    def test_another_place_stays(self) -> None:
        self.assertEqual("", migration.defaults_updated(USER_1_5_2.replace("top-right", "bottom-left")))

    def test_a_file_without_a_place_gets_one(self) -> None:
        text = '<?xml version="1.0" encoding="UTF-8"?>\n<channel name="xfce4-notifyd" version="1.0">\n</channel>\n'
        self.assertIn('value="bottom-right"/>\n</channel>', migration.defaults_updated(text))

    def test_written_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "xfce-perchannel-xml" / "xfce4-notifyd.xml"
            with mock.patch.object(MigrationContext, "log"):
                migration.xfce_defaults(MigrationContext(), path)
                first = path.read_text(encoding="utf-8")
                migration.xfce_defaults(MigrationContext(), path)
            self.assertEqual(migration.DEFAULTS_XML, first)
            self.assertEqual(first, path.read_text(encoding="utf-8"))


class UserTests(unittest.TestCase):
    def run_user(self, logged_in: bool, value: str | None, own_file: bool = True,
                 write_fails: bool = False) -> tuple[list, list]:
        commands: list[list[str]] = []
        logged: list[str] = []

        def run_command(argv, allow_fail=False, env=None):  # noqa: ANN001
            commands.append(list(argv))
            if "-s" not in argv:
                if value is None:
                    return subprocess.CompletedProcess(argv, 1, "", "Property does not exist")
                return subprocess.CompletedProcess(argv, 0, value + "\n", "")
            return subprocess.CompletedProcess(argv, 1 if write_fails else 0, "", "no" if write_fails else "")

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            runtime = Path(tmp) / "run"
            if own_file:
                (home / migration.USER_SETTINGS).parent.mkdir(parents=True)
                (home / migration.USER_SETTINGS).write_text(USER_1_5_2, encoding="utf-8")
            if logged_in:
                (runtime / "1000").mkdir(parents=True)
                (runtime / "1000" / "bus").touch()
            context = MigrationContext()
            with mock.patch.object(context, "run_command", side_effect=run_command), \
                    mock.patch.object(context, "log", side_effect=logged.append):
                migration.xfce_user(context, "minh", 1000, home, runtime_root=runtime)
        return commands, logged

    def test_a_running_session_moves_at_once(self) -> None:
        commands, logged = self.run_user(logged_in=True, value="top-right")
        self.assertTrue(all("dbus-run-session" not in command for command in commands))
        self.assertEqual(["runuser", "-u", "minh", "--", "xfconf-query", "-c", "xfce4-notifyd", "-p",
                          "/notify-location", "-n", "-t", "string", "-s", "bottom-right"], commands[-1])
        self.assertIn("at the bottom right from now on", logged[-1])

    def test_not_logged_in_through_a_session_of_its_own(self) -> None:
        commands, _logged = self.run_user(logged_in=False, value="top-right")
        self.assertTrue(all(command[4:6] == ["dbus-run-session", "--"] for command in commands))
        self.assertEqual(["-s", "bottom-right"], commands[-1][-2:])

    def test_a_place_chosen_stays(self) -> None:
        for value in ("bottom-left", "top-left", "bottom-right"):
            with self.subTest(value=value):
                commands, logged = self.run_user(logged_in=True, value=value)
                self.assertEqual(1, len(commands), "only read")
                self.assertIn("kept", logged[-1])

    def test_nothing_to_read(self) -> None:
        commands, logged = self.run_user(logged_in=False, value=None, own_file=False)
        self.assertEqual([], commands)
        self.assertIn("system default", logged[0])

    def test_a_failed_write_is_logged(self) -> None:
        _commands, logged = self.run_user(logged_in=True, value="top-right", write_fails=True)
        self.assertTrue(logged[-1].startswith("warning:"))

    def test_run(self) -> None:
        users = [("minh", 1000, Path("/home/minh")), ("lan", 1001, Path("/home/lan"))]
        with mock.patch.object(migration.clipboard, "_desktop_users", return_value=users), \
                mock.patch.object(migration, "xfce_defaults") as defaults, \
                mock.patch.object(migration, "xfce_user") as user, \
                mock.patch.object(MigrationContext, "log"):
            migration.run(MigrationContext())
            defaults.assert_called_once()
            self.assertEqual(["minh", "lan"], [call.args[1] for call in user.call_args_list])
            user.reset_mock()
            migration.run(MigrationContext(dry_run=True))
            user.assert_not_called()

    def test_manifest(self) -> None:
        manifest = json.loads((FOLDER / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(["xfce"], manifest["desktops"])
        self.assertEqual("anytime", manifest["unattended"])


if __name__ == "__main__":
    unittest.main()

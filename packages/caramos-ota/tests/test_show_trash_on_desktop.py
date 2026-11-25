"""The Trash on the desktop on both editions, as on Windows (ticket H-1210, migration 20261124140000).

Up to 1.5.0 CaramOS hid it: the gschema override and the first-login script caramos-theme-apply on Cinnamon (which set
false in every account), xfce4-desktop.xml on Xfce (where users' own files only have a blank placeholder)."""

from __future__ import annotations

import importlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update import deferred
from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
MIGRATION_DIR = ROOT / "usr/lib/python3/dist-packages/caramos_ota_update/migrations/20261124140000_show_trash_on_desktop"
ISO_OVERRIDE = REPO / "config/includes.chroot/usr/share/glib-2.0/schemas/99_caramos.gschema.override"
ISO_THEME_SCRIPT = REPO / "config/includes.chroot/usr/bin/caramos-theme-apply"
ISO_XFCE = REPO / "config/includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml"
migration = importlib.import_module("caramos_ota_update.migrations.20261124140000_show_trash_on_desktop.migration")

OVERRIDE_1_5_0 = """[org.cinnamon.desktop.background]
picture-uri='file:///usr/share/backgrounds/caramos/default.png'

[org.nemo.desktop]
computer-icon-visible=false
home-icon-visible=false
trash-icon-visible=false
network-icon-visible=false
volumes-visible=true
"""
THEME_SCRIPT_1_5_0 = """#!/bin/bash
gsettings set org.nemo.desktop home-icon-visible false 2>/dev/null || true
gsettings set org.nemo.desktop trash-icon-visible false 2>/dev/null || true
"""
XFCE_DEFAULTS_1_5_0 = """<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-desktop" version="1.0">
  <property name="desktop-icons" type="empty">
    <property name="style" type="int" value="2"/>
    <property name="file-icons" type="empty">
      <property name="show-filesystem" type="bool" value="false"/>
      <property name="show-home" type="bool" value="false"/>
      <property name="show-trash" type="bool" value="false"/>
      <property name="show-removable" type="bool" value="false"/>
    </property>
  </property>
</channel>
"""
# What a 1.5.0 user's own file has there: a blank placeholder, not a value.
USER_FILE_PLACEHOLDER = """<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-desktop" version="1.0">
  <property name="desktop-icons" type="empty">
    <property name="file-icons" type="empty">
      <property name="show-home" type="empty"/>
      <property name="show-trash" type="empty"/>
    </property>
  </property>
</channel>
"""


def done(code: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


class FileTests(unittest.TestCase):
    def test_the_cinnamon_default_shows_the_trash_once(self) -> None:
        new = migration.override_updated(OVERRIDE_1_5_0)
        self.assertIn("trash-icon-visible=true\n", new)
        self.assertNotIn("trash-icon-visible=false", new)
        self.assertEqual(OVERRIDE_1_5_0.replace("trash-icon-visible=false", "trash-icon-visible=true"), new)
        self.assertEqual("", migration.override_updated(new))

    def test_another_section_is_not_touched(self) -> None:
        text = "[org.other]\ntrash-icon-visible=false\n"
        self.assertEqual("", migration.override_updated(text))

    def test_the_first_login_script_shows_it_for_accounts_made_later(self) -> None:
        new = migration.theme_script_updated(THEME_SCRIPT_1_5_0)
        self.assertIn("gsettings set org.nemo.desktop trash-icon-visible true", new)
        self.assertIn("home-icon-visible false", new)
        self.assertEqual("", migration.theme_script_updated(new))

    def test_the_xfce_default_shows_the_trash_once(self) -> None:
        new = migration.xfce_defaults_updated(XFCE_DEFAULTS_1_5_0)
        self.assertIn('<property name="show-trash" type="bool" value="true"/>', new)
        self.assertIn('<property name="show-home" type="bool" value="false"/>', new)
        self.assertEqual(XFCE_DEFAULTS_1_5_0.count("\n"), new.count("\n"))
        self.assertEqual("", migration.xfce_defaults_updated(new))

    def test_a_users_own_value(self) -> None:
        self.assertIsNone(migration.own_value(USER_FILE_PLACEHOLDER))
        self.assertIsNone(migration.own_value('<channel name="xfce4-desktop" version="1.0"/>'))
        chose = USER_FILE_PLACEHOLDER.replace('name="show-trash" type="empty"/>',
                                              'name="show-trash" type="bool" value="false"/>')
        self.assertIs(False, migration.own_value(chose))
        self.assertIs(True, migration.own_value(chose.replace('value="false"', 'value="true"')))

    @unittest.skipUnless(ISO_OVERRIDE.is_file() and ISO_XFCE.is_file(), "the source package has no config/")
    def test_new_installs_show_the_trash(self) -> None:
        self.assertEqual("", migration.override_updated(ISO_OVERRIDE.read_text(encoding="utf-8")))
        self.assertIn("trash-icon-visible=true", ISO_OVERRIDE.read_text(encoding="utf-8"))
        self.assertEqual("", migration.theme_script_updated(ISO_THEME_SCRIPT.read_text(encoding="utf-8")))
        self.assertIn("trash-icon-visible true", ISO_THEME_SCRIPT.read_text(encoding="utf-8"))
        self.assertEqual("", migration.xfce_defaults_updated(ISO_XFCE.read_text(encoding="utf-8")))
        self.assertIn('<property name="show-trash" type="bool" value="true"/>', ISO_XFCE.read_text(encoding="utf-8"))

    def test_manifest(self) -> None:
        manifest = json.loads((MIGRATION_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("anytime", manifest["unattended"], "a logged-in desktop gets the icon at its next login")
        self.assertIn("lần đăng nhập sau", manifest["release_notes_vi"][-1])
        self.assertNotIn("desktops", manifest, "both editions")
        for key in ("title", "summary", "title_en", "summary_en", "size", "size_en"):
            self.assertTrue(manifest[key].strip(), key)
        self.assertIn("Sọt rác", " ".join(manifest["release_notes_vi"]), "Cinnamon's own name of the setting")


class CinnamonTests(unittest.TestCase):
    def test_false_from_the_first_login_script_becomes_true(self) -> None:
        calls = []

        def gsettings(username, env, args):  # noqa: ANN001
            calls.append(args)
            return done(0, "false\n") if args[0] == "get" else done()

        context = MigrationContext()
        with mock.patch.object(migration.help_applet, "_user_environment", return_value={}), \
                mock.patch.object(migration.help_applet, "_gsettings", side_effect=gsettings), \
                mock.patch.object(context, "log") as log:
            migration.cinnamon_user(context, "minh", 1000, Path("/home/minh"))
        self.assertEqual([["get", "org.nemo.desktop", "trash-icon-visible"],
                          ["set", "org.nemo.desktop", "trash-icon-visible", "true"]], calls)
        self.assertIn("the Trash is on the desktop of minh", log.call_args.args[0])

    def test_shown_already_is_left_alone(self) -> None:
        context = MigrationContext()
        with mock.patch.object(migration.help_applet, "_user_environment", return_value={}), \
                mock.patch.object(migration.help_applet, "_gsettings", return_value=done(0, "true\n")) as gsettings, \
                mock.patch.object(context, "log"):
            migration.cinnamon_user(context, "minh", 1000, Path("/home/minh"))
        self.assertEqual(1, gsettings.call_count)

    def test_run_updates_the_defaults_then_each_account(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            override = Path(folder, "99_caramos.gschema.override")
            override.write_text(OVERRIDE_1_5_0, encoding="utf-8")
            script = Path(folder, "caramos-theme-apply")
            script.write_text(THEME_SCRIPT_1_5_0, encoding="utf-8")
            context = MigrationContext()
            users = [("minh", 1000, Path("/home/minh")), ("lan", 1001, Path("/home/lan"))]
            with mock.patch.object(migration, "OVERRIDE", override), mock.patch.object(migration, "SCHEMAS", Path(folder)), \
                    mock.patch.object(migration, "THEME_SCRIPT", script), \
                    mock.patch.object(context, "run_command", return_value=done()) as run_command, \
                    mock.patch.object(migration.help_applet, "_desktop_users", return_value=users), \
                    mock.patch.object(migration, "cinnamon_user") as user, mock.patch.object(context, "log"):
                migration.run(context, "cinnamon")
            self.assertIn("trash-icon-visible=true", override.read_text(encoding="utf-8"))
            self.assertIn("trash-icon-visible true", script.read_text(encoding="utf-8"))
        self.assertEqual(["glib-compile-schemas", folder], run_command.call_args.args[0])
        self.assertEqual(["minh", "lan"], [call.args[1] for call in user.call_args_list])


class AutomaticUpdateTests(unittest.TestCase):
    """Cinnamon shows a changed setting at once: a logged-in account gets the Trash at its next login."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        runtime = self.root / "run/user"
        (runtime / "1000").mkdir(parents=True)
        (runtime / "1000/bus").touch()   # minh is logged in, lan is not
        for name, value in (("QUEUE_DIR", self.root / "login-actions"), ("RUNTIME_ROOT", runtime)):
            patcher = mock.patch.object(deferred, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_cinnamon(self, unattended: bool) -> list[str]:
        context = MigrationContext(unattended=unattended)
        users = [("minh", 1000, Path("/home/minh")), ("lan", 1001, Path("/home/lan"))]
        with mock.patch.object(migration, "_update_file", return_value=False), \
                mock.patch.object(migration.help_applet, "_desktop_users", return_value=users), \
                mock.patch.object(migration, "cinnamon_user") as user, mock.patch.object(context, "log"):
            migration.run(context, "cinnamon")
        return [call.args[1] for call in user.call_args_list]

    def test_a_logged_in_account_waits_for_its_next_login(self) -> None:
        self.assertEqual(["lan"], self.run_cinnamon(unattended=True))
        queued = json.loads(deferred.queue_file(1000).read_text(encoding="utf-8"))
        self.assertEqual("minh", queued["user"])
        self.assertEqual([(migration.MIGRATION, "trash-icon")],
                         [(entry["migration"], entry["action"]) for entry in queued["actions"]])

    def test_the_update_center_shows_it_at_once(self) -> None:
        self.assertEqual(["minh", "lan"], self.run_cinnamon(unattended=False))
        self.assertFalse(deferred.queue_file(1000).exists())

    def test_the_next_login_shows_it_before_nemo_desktop_starts(self) -> None:
        commands = []

        class Session(deferred.Session):
            def run(self, args, timeout=deferred.COMMAND_TIMEOUT):  # noqa: ANN001
                commands.append(list(args))
                return done(0, "false\n") if args[1] == "get" else done()

            def log(self, message: str) -> None:
                self.messages.append(message)

        session = Session("minh", 1000, Path("/home/minh"), "cinnamon", environ={})
        migration.LOGIN_ACTIONS["trash-icon"](session)
        self.assertEqual([["gsettings", "get", "org.nemo.desktop", "trash-icon-visible"],
                          ["gsettings", "set", "org.nemo.desktop", "trash-icon-visible", "true"]], commands)
        self.assertEqual("the Trash is on the desktop of minh", session.messages[-1])
        commands.clear()
        session.desktop = "xfce"   # xfdesktop takes the new default by itself
        migration.LOGIN_ACTIONS["trash-icon"](session)
        self.assertEqual([], commands)


class XfceTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.home = self.root / "home/minh"
        (self.home / migration.USER_DESKTOP).parent.mkdir(parents=True)
        self.runtime = self.root / "run/user"

    def user(self, text: str | None, logged_in: bool):
        if text is not None:
            (self.home / migration.USER_DESKTOP).write_text(text, encoding="utf-8")
        if logged_in:
            (self.runtime / "1000").mkdir(parents=True)
            (self.runtime / "1000/bus").touch()
        context = MigrationContext()
        with mock.patch.object(context, "run_command", return_value=done()) as run_command, \
                mock.patch.object(context, "log") as log:
            migration.xfce_user(context, "minh", 1000, self.home, runtime_root=self.runtime)
        return run_command, log

    def test_logged_in_without_a_choice_shows_it_at_once(self) -> None:
        run_command, _log = self.user(USER_FILE_PLACEHOLDER, logged_in=True)
        argv = run_command.call_args.args[0]
        self.assertEqual(["runuser", "-u", "minh", "--", "xfconf-query", "-c", "xfce4-desktop", "-p",
                          "/desktop-icons/file-icons/show-trash", "-n", "-t", "bool", "-s", "true"], argv)
        env = run_command.call_args.kwargs["env"]
        self.assertEqual(f"unix:path={self.runtime}/1000/bus", env["DBUS_SESSION_BUS_ADDRESS"])

    def test_an_automatic_update_leaves_an_open_desktop_to_the_new_default(self) -> None:
        context = MigrationContext(unattended=True)
        (self.runtime / "1000").mkdir(parents=True)
        (self.runtime / "1000/bus").touch()
        with mock.patch.object(context, "run_command") as run_command, mock.patch.object(context, "log") as log:
            migration.xfce_user(context, "minh", 1000, self.home, runtime_root=self.runtime)
        run_command.assert_not_called()
        self.assertIn("from the next login", log.call_args.args[0])

    def test_not_logged_in_gets_the_new_default_at_the_next_login(self) -> None:
        run_command, log = self.user(USER_FILE_PLACEHOLDER, logged_in=False)
        run_command.assert_not_called()
        self.assertIn("from the next login", log.call_args.args[0])

    def test_no_file_of_their_own_counts_as_no_choice(self) -> None:
        run_command, _log = self.user(None, logged_in=True)
        self.assertEqual("xfconf-query", run_command.call_args.args[0][4])

    def test_a_choice_of_their_own_stays(self) -> None:
        chose = USER_FILE_PLACEHOLDER.replace('name="show-trash" type="empty"/>',
                                              'name="show-trash" type="bool" value="false"/>')
        run_command, log = self.user(chose, logged_in=True)
        run_command.assert_not_called()
        self.assertIn("chose not to show", log.call_args.args[0])

    def test_run_updates_the_default_then_each_account(self) -> None:
        defaults = self.root / "xfce4-desktop.xml"
        defaults.write_text(XFCE_DEFAULTS_1_5_0, encoding="utf-8")
        context = MigrationContext()
        with mock.patch.object(migration, "XFCE_DESKTOP", defaults), \
                mock.patch.object(migration.clipboard, "_desktop_users", return_value=[("minh", 1000, self.home)]), \
                mock.patch.object(migration, "xfce_user") as user, mock.patch.object(context, "log"):
            migration.run(context, "xfce")
        self.assertIn('name="show-trash" type="bool" value="true"', defaults.read_text(encoding="utf-8"))
        user.assert_called_once()

    def test_other_desktops(self) -> None:
        context = MigrationContext()
        with mock.patch.object(migration, "run_cinnamon") as cinnamon, mock.patch.object(migration, "run_xfce") as xfce, \
                mock.patch.object(context, "log"):
            migration.run(context, "other")
        cinnamon.assert_not_called()
        xfce.assert_not_called()


if __name__ == "__main__":
    unittest.main()

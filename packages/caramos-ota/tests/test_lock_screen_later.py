"""The screen locks after about half an hour without use (migration 20261125130000): people took the lock for a logout.

Cinnamon: the screensaver after 15 minutes as before (idle-delay 900, Cinnamon's default), the lock 600 s after it
instead of CaramOS's 300. Xfce: the power manager blanks after 15 minutes instead of 10 (5 on battery), light-locker
locks 900 s after that instead of 5. Only the system's defaults change; an account's own setting stays."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
MIGRATION_DIR = ROOT / "usr/lib/python3/dist-packages/caramos_ota_update/migrations/20261125130000_lock_screen_later"
ISO_OVERRIDE = REPO / "config/includes.chroot/usr/share/glib-2.0/schemas/99_caramos.gschema.override"
ISO_POWER = REPO / "config/includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-power-manager.xml"
migration = importlib.import_module("caramos_ota_update.migrations.20261125130000_lock_screen_later.migration")
HELP_APPLET = importlib.import_module("caramos_ota_update.migrations.20261012180000_add_help_applet.migration")

OVERRIDE_1_5_0 = """[org.cinnamon.settings-daemon.plugins.power]
sleep-inactive-ac-timeout=0
sleep-inactive-battery-timeout=900

[org.cinnamon.desktop.screensaver]
lock-enabled=true
lock-delay=uint32 300
font-date='Be Vietnam Pro 24'

[org.example.other]
lock-delay=uint32 300
"""
POWER_1_5_0 = """<?xml version="1.0" encoding="UTF-8"?>
<!-- CaramOS Xfce: Mint's xfce4-power-manager.xml, with the power button asking what to do. -->

<channel name="xfce4-power-manager" version="1.0">
  <property name="xfce4-power-manager" type="empty">
    <property name="power-button-action" type="uint" value="3"/>
    <property name="lid-action-on-battery" type="uint" value="1"/>
    <property name="show-panel-label" type="int" value="0"/>
  </property>
</channel>
"""
# The choices of Cinnamon 6.6's Screensaver settings (cinnamon-settings modules/cs_screensaver.py): a value not
# among them shows as an empty choice. idle-delay: LOCK_INACTIVE_OPTIONS; lock-delay: LOCK_DELAY_OPTIONS.
CINNAMON_IDLE_CHOICES = (0, 60, 300, 600, 900, 1800, 2700, 3600)
CINNAMON_LOCK_CHOICES = (0, 2, 5, 10, 15, 30, 60, 120, 180, 300, 600, 1800, 3600)
LIGHT_LOCKER_RANGE = range(0, 3601)      # apps.light-locker lock-after-screensaver
XFPM_BLANK_RANGE = range(0, 61)          # xfce4-power-manager-settings: Display > Blank after (minutes)


def done(code: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, stdout, stderr)


def blank(text: str) -> dict[str, str]:
    group = ElementTree.fromstring(text.encode("utf-8")).find("property[@name='xfce4-power-manager']")
    return {node.get("name"): node.get("value") for node in group}


class ValueTests(unittest.TestCase):
    def test_about_half_an_hour_with_values_the_settings_can_show(self) -> None:
        self.assertIn(900, CINNAMON_IDLE_CHOICES)
        self.assertIn(migration.LOCK_DELAY, CINNAMON_LOCK_CHOICES)
        self.assertEqual(25 * 60, 900 + migration.LOCK_DELAY)
        self.assertIn(migration.LIGHT_LOCKER_DELAY, LIGHT_LOCKER_RANGE)
        self.assertIn(migration.BLANK_MINUTES, XFPM_BLANK_RANGE)
        self.assertEqual(30 * 60, migration.BLANK_MINUTES * 60 + migration.LIGHT_LOCKER_DELAY)


class OverrideTests(unittest.TestCase):
    def test_cinnamons_lock_waits_longer_and_light_locker_gets_its_delay(self) -> None:
        new = migration.override_updated(OVERRIDE_1_5_0)
        self.assertIn("[org.cinnamon.desktop.screensaver]\nlock-enabled=true\nlock-delay=uint32 600\n", new)
        self.assertIn("[org.example.other]\nlock-delay=uint32 300\n", new, "another schema's key stays")
        self.assertIn("[apps.light-locker]\nlock-after-screensaver=uint32 900\n", new)
        self.assertIn("sleep-inactive-battery-timeout=900", new, "sleep stays as it is")
        self.assertEqual("", migration.override_updated(new), "once")

    def test_a_delay_someone_changed_stays(self) -> None:
        changed = OVERRIDE_1_5_0.replace("lock-enabled=true\nlock-delay=uint32 300", "lock-enabled=true\nlock-delay=uint32 120")
        new = migration.override_updated(changed)
        self.assertIn("lock-delay=uint32 120", new)
        self.assertNotIn("lock-delay=uint32 600", new)
        with_light_locker = changed + "\n[apps.light-locker]\nlock-after-screensaver=uint32 60\n"
        self.assertEqual("", migration.override_updated(with_light_locker))

    @unittest.skipUnless(ISO_OVERRIDE.is_file(), "the source package has no config/")
    def test_new_installs_have_it(self) -> None:
        text = ISO_OVERRIDE.read_text(encoding="utf-8")
        self.assertEqual("", migration.override_updated(text))
        self.assertIn("lock-enabled=true\nlock-delay=uint32 600\n", text)
        self.assertIn("[apps.light-locker]\nlock-after-screensaver=uint32 900\n", text)

    @unittest.skipUnless(ISO_OVERRIDE.is_file() and shutil.which("glib-compile-schemas") and shutil.which("gsettings"),
                         "needs the ISO tree and GLib's tools")
    def test_the_override_compiles_to_these_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            schemas = Path(folder)
            (schemas / "test.gschema.xml").write_text("""<schemalist>
  <schema id="org.cinnamon.desktop.screensaver" path="/org/cinnamon/desktop/screensaver/">
    <key name="lock-enabled" type="b"><default>true</default></key>
    <key name="lock-delay" type="u"><default>0</default></key>
    <key name="font-date" type="s"><default>''</default></key>
    <key name="font-message" type="s"><default>''</default></key>
    <key name="font-time" type="s"><default>''</default></key>
  </schema>
  <schema id="apps.light-locker" path="/apps/light-locker/">
    <key name="lock-after-screensaver" type="u"><range min="0" max="3600"/><default>5</default></key>
    <key name="lock-on-suspend" type="b"><default>true</default></key>
  </schema>
</schemalist>
""", encoding="utf-8")
            shutil.copy(ISO_OVERRIDE, schemas / ISO_OVERRIDE.name)
            # Schemas the override names but this folder lacks are left out by glib-compile-schemas.
            subprocess.run(["glib-compile-schemas", "--strict", folder], check=True, capture_output=True)
            env = {**os.environ, "GSETTINGS_SCHEMA_DIR": folder, "GSETTINGS_BACKEND": "memory"}

            def get(schema: str, key: str) -> str:
                return subprocess.run(["gsettings", "get", schema, key], check=True, capture_output=True, text=True,
                                      env=env).stdout.strip()

            self.assertEqual("uint32 600", get("org.cinnamon.desktop.screensaver", "lock-delay"))
            self.assertEqual("true", get("org.cinnamon.desktop.screensaver", "lock-enabled"))
            self.assertEqual("uint32 900", get("apps.light-locker", "lock-after-screensaver"))
            self.assertEqual("true", get("apps.light-locker", "lock-on-suspend"), "locking at sleep stays")


class PowerManagerTests(unittest.TestCase):
    def test_xfce_blanks_after_15_minutes_on_mains_and_battery(self) -> None:
        new = migration.power_manager_updated(POWER_1_5_0)
        values = blank(new)
        self.assertEqual("15", values["blank-on-ac"])
        self.assertEqual("15", values["blank-on-battery"])
        self.assertEqual("3", values["power-button-action"])
        self.assertIn("<!-- CaramOS Xfce", new, "the comment stays")
        self.assertIn('    <property name="blank-on-ac" type="int" value="15"/>\n', new)
        self.assertEqual("", migration.power_manager_updated(new), "once")

    def test_a_blank_time_someone_chose_stays(self) -> None:
        chosen = POWER_1_5_0.replace('    <property name="show-panel-label" type="int" value="0"/>\n',
                                     '    <property name="show-panel-label" type="int" value="0"/>\n'
                                     '    <property name="blank-on-ac" type="int" value="5"/>\n')
        self.assertEqual("", migration.power_manager_updated(chosen))

    def test_files_it_does_not_know_stay(self) -> None:
        self.assertEqual("", migration.power_manager_updated("not xml"))
        self.assertEqual("", migration.power_manager_updated('<channel name="xfwm4" version="1.0"/>'))
        self.assertEqual("", migration.power_manager_updated('<channel name="xfce4-power-manager" version="1.0"/>'))

    @unittest.skipUnless(ISO_POWER.is_file(), "the source package has no config/")
    def test_new_installs_have_it(self) -> None:
        text = ISO_POWER.read_text(encoding="utf-8")
        self.assertEqual({"blank-on-ac": "15", "blank-on-battery": "15"},
                         {key: value for key, value in blank(text).items() if key.startswith("blank-")})
        self.assertNotIn("lock-screen-suspend-hibernate", text, "locking at sleep keeps Xfce's own default")


class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.override = self.root / "schemas/99_caramos.gschema.override"
        self.override.parent.mkdir()
        self.override.write_text(OVERRIDE_1_5_0, encoding="utf-8")
        self.power = self.root / "caramos-xfce/xfce4-power-manager.xml"

    def run_migration(self, context: MigrationContext, xfce: bool):
        if xfce:
            self.power.parent.mkdir(exist_ok=True)
            self.power.write_text(POWER_1_5_0, encoding="utf-8")
        with mock.patch.object(migration, "OVERRIDE", self.override), \
                mock.patch.object(migration, "SCHEMAS", self.override.parent), \
                mock.patch.object(migration, "POWER_MANAGER", self.power), \
                mock.patch.object(migration, "light_locker_user") as user, \
                mock.patch.object(HELP_APPLET, "_desktop_users", return_value=[("minh", 1000, Path("/home/minh"))]), \
                mock.patch.object(context, "run_command", return_value=done()) as run_command, \
                mock.patch.object(context, "log"):
            migration.run(context, "xfce" if xfce else "cinnamon")
        self.light_locker_users = [call.args[1] for call in user.call_args_list]
        return run_command

    def test_both_editions(self) -> None:
        for xfce in (False, True):
            with self.subTest(xfce=xfce):
                self.override.write_text(OVERRIDE_1_5_0, encoding="utf-8")
                run_command = self.run_migration(MigrationContext(unattended=True), xfce)
                self.assertIn("lock-delay=uint32 600", self.override.read_text(encoding="utf-8"))
                run_command.assert_called_once_with(["glib-compile-schemas", str(self.override.parent)], allow_fail=True)
                self.assertEqual(xfce, self.power.is_file() and "blank-on-ac" in self.power.read_text(encoding="utf-8"))
                self.assertEqual(["minh"] if xfce else [], self.light_locker_users)

    def test_nothing_asks_a_session(self) -> None:
        # No gsettings, xfconf-query or reload: nothing changes on an open desktop, and no account's own value.
        run_command = self.run_migration(MigrationContext(unattended=True), True)
        self.assertEqual([["glib-compile-schemas", str(self.override.parent)]],
                         [call.args[0] for call in run_command.call_args_list])

    def test_a_dry_run_changes_nothing(self) -> None:
        run_command = self.run_migration(MigrationContext(dry_run=True), True)
        self.assertEqual(OVERRIDE_1_5_0, self.override.read_text(encoding="utf-8"))
        self.assertEqual(POWER_1_5_0, self.power.read_text(encoding="utf-8"))
        run_command.assert_not_called()
        self.assertEqual([], self.light_locker_users)


class LightLockerUserTests(unittest.TestCase):
    """Xfce accounts usually have all of light-locker's keys stored as their own, the stock 5 seconds among them."""

    def user(self, own: str, logged_in: bool = False):
        context = MigrationContext(unattended=True)
        env = {"HOME": "/home/minh"}
        if logged_in:
            env["DBUS_SESSION_BUS_ADDRESS"] = "unix:path=/run/user/1000/bus"
        with mock.patch.object(HELP_APPLET, "_user_environment", return_value=env), \
                mock.patch.object(HELP_APPLET, "_gsettings", return_value=done()) as gsettings, \
                mock.patch.object(context, "run_command", return_value=done(0, own)) as run_command, \
                mock.patch.object(context, "log") as log:
            migration.light_locker_user(context, "minh", 1000, Path("/home/minh"))
        self.assertEqual(["runuser", "-u", "minh", "--", "dconf", "read", "/apps/light-locker/lock-after-screensaver"],
                         run_command.call_args.args[0])
        return gsettings, log

    def test_the_old_five_seconds_go(self) -> None:
        for logged_in in (False, True):
            with self.subTest(logged_in=logged_in):
                gsettings, log = self.user("uint32 5\n", logged_in)
                self.assertEqual(["reset", "apps.light-locker", "lock-after-screensaver"], gsettings.call_args.args[2])
                self.assertIn("the new default applies from the next login", log.call_args.args[0])

    def test_a_value_of_their_own_or_none_stays(self) -> None:
        for own in ("uint32 60\n", "uint32 0\n", ""):
            with self.subTest(own=own):
                gsettings, _log = self.user(own)
                gsettings.assert_not_called()


class ManifestTests(unittest.TestCase):
    def test_manifest(self) -> None:
        manifest = json.loads((MIGRATION_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("anytime", manifest["unattended"], "only defaults change; they apply from the next login")
        self.assertNotIn("desktops", manifest, "both editions")
        for key in ("title", "summary", "title_en", "summary_en", "size", "size_en"):
            self.assertTrue(manifest[key].strip(), key)
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        notes = " ".join(manifest["release_notes_vi"])
        self.assertIn("25 phút", notes)
        self.assertIn("30 phút", notes)
        self.assertIn("Trình bảo vệ màn hình", notes, "Cinnamon's own name of the settings page")


if __name__ == "__main__":
    unittest.main()

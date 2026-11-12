"""Migration 20261112100000_screenshot_shortcuts: Print Screen and Super+Shift+S start Flameshot's capture."""

from __future__ import annotations

import ast
import configparser
import importlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).parents[1]
REPO = ROOT.parents[1]
ISO_DEFAULTS = REPO / "config/includes.chroot/etc/dconf/db/local.d/02-caramos-screenshot-keys"
OVERRIDE = REPO / "config/includes.chroot/usr/share/glib-2.0/schemas/99_caramos.gschema.override"

migration = importlib.import_module("caramos_ota_update.migrations.20261112100000_screenshot_shortcuts.migration")

KEYBINDINGS = "org.cinnamon.desktop.keybindings"
MEDIA_KEYS = "org.cinnamon.desktop.keybindings.media-keys"
SLOT = "org.cinnamon.desktop.keybindings.custom-keybinding:/org/cinnamon/desktop/keybindings/custom-keybindings/{}/"


class FakeSettings:
    """gsettings for one user: values as gsettings prints them, the defaults of a CaramOS install."""

    def __init__(self, values: dict[tuple[str, str], str] | None = None, fail_set: bool = False) -> None:
        self.values = {(KEYBINDINGS, "custom-list"): "['custom0', 'custom1']",
                       (MEDIA_KEYS, "screenshot"): "@as []", (MEDIA_KEYS, "home"): "['<Super>e']"}
        self.values.update(values or {})
        self.writes: list[tuple[str, str, str]] = []
        self.fail_set = fail_set

    def __call__(self, username: str, env: dict[str, str], args: list[str]) -> subprocess.CompletedProcess[str]:
        command, schema = args[0], args[1]
        if command == "get":
            key = args[2]
            default = {"name": "''", "command": "''", "binding": "@as []"}.get(key, "")
            return subprocess.CompletedProcess(args, 0, self.values.get((schema, key), default) + "\n", "")
        if command == "list-recursively":
            lines = [f"{schema} {key} {value}" for (owner, key), value in self.values.items() if owner == schema]
            return subprocess.CompletedProcess(args, 0, "\n".join(lines) + "\n", "")
        if command == "set":
            if self.fail_set:
                return subprocess.CompletedProcess(args, 1, "", "no session")
            self.values[(schema, args[2])] = args[3]
            self.writes.append((schema, args[2], args[3]))
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(args)

    def get(self, schema: str, key: str) -> object:
        return migration.parse(self.values.get((schema, key), "@as []"))


def fix(settings: FakeSettings) -> list[str]:
    context = MigrationContext()
    logged: list[str] = []
    with mock.patch.object(migration, "_gsettings", settings), \
            mock.patch.object(context, "log", side_effect=logged.append):
        migration._fix_for_user(context, "caram", 1000, Path("/home/caram"))
    return logged


class DefaultsTests(unittest.TestCase):
    def test_the_dconf_defaults(self) -> None:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(migration.dconf_defaults())
        self.assertEqual(
            {"org/cinnamon/desktop/keybindings/custom-keybindings/custom0":
                 {"name": "'Flameshot'", "command": "'flameshot gui'", "binding": "['<Super><Shift>s']"},
             "org/cinnamon/desktop/keybindings/custom-keybindings/custom1":
                 {"name": "'Flameshot Print'", "command": "'flameshot gui'", "binding": "['Print']"}},
            {section: dict(parser[section]) for section in parser.sections()})

    @unittest.skipUnless((REPO / "config").is_dir(), "ISO tree is not in the source package")
    def test_new_installs_get_the_same_defaults(self) -> None:
        self.assertEqual(migration.dconf_defaults(), ISO_DEFAULTS.read_text(encoding="utf-8"))

    @unittest.skipUnless((REPO / "config").is_dir(), "ISO tree is not in the source package")
    def test_the_override_keeps_cinnamons_screenshots_off_and_sets_no_path(self) -> None:
        text = OVERRIDE.read_text(encoding="utf-8")
        # GLib reads [schema:X] as an override for the desktop X: a path there never applies.
        self.assertEqual([], [group for group in re.findall(r"^\[([^\]]*)\]", text, re.M) if ":" in group])
        groups = re.split(r"^\[", text, flags=re.M)
        media_keys = next(group for group in groups if group.startswith("org.cinnamon.desktop.keybindings.media-keys]"))
        for key in ("screenshot", "window-screenshot", "area-screenshot"):
            self.assertIn(f"\n{key}=@as []\n", media_keys)
        self.assertIn("\ncustom-list=['custom0', 'custom1']\n", text)

    def test_values_as_gsettings_prints_them(self) -> None:
        self.assertEqual([], migration.parse("@as []"))
        self.assertEqual(["custom0", "custom1"], migration.parse("['custom0', 'custom1']\n"))
        self.assertEqual("it's", migration.parse("\"it's\""))
        self.assertEqual("flameshot gui", migration.parse("'flameshot gui'"))
        self.assertIsNone(migration.parse("uint32 300"))
        self.assertIsNone(migration.parse("true"))
        self.assertEqual("['a\\\\b', 'it\\'s']", migration.gvariant_strv(["a\\b", "it's"]))
        self.assertEqual(["a\\b", "it's"], ast.literal_eval(migration.gvariant_strv(["a\\b", "it's"])))
        self.assertEqual("@as []", migration.gvariant_strv([]))

    def test_the_same_key_written_differently(self) -> None:
        self.assertEqual(migration.accelerator("<Super><Shift>s"), migration.accelerator("<Shift><Mod4>S"))
        self.assertEqual(migration.accelerator("<Primary>Print"), migration.accelerator("<Control>Print"))
        self.assertNotEqual(migration.accelerator("Print"), migration.accelerator("<Shift>Print"))
        self.assertIsNone(migration.accelerator(""))
        self.assertEqual({migration.accelerator("Print")}, migration.accelerators(["Print", "", 3]))
        self.assertEqual(set(), migration.accelerators(None))

    def test_the_list_is_written_so_cinnamon_reads_it_again(self) -> None:
        self.assertEqual([["custom1", "custom0"], ["custom0", "custom1"]],
                         migration.list_writes(["custom0", "custom1"], ["custom0", "custom1"]))
        self.assertEqual([["custom2", "custom1"]], migration.list_writes(["custom2"], ["custom2", "custom1"]))
        self.assertEqual([[], ["custom1"]], migration.list_writes(["custom1"], ["custom1"]))


class UserTests(unittest.TestCase):
    def test_a_user_who_never_set_them(self) -> None:
        settings = FakeSettings()
        logged = fix(settings)

        self.assertEqual("['<Super><Shift>s']", settings.values[(SLOT.format("custom0"), "binding")])
        self.assertEqual("['Print']", settings.values[(SLOT.format("custom1"), "binding")])
        self.assertEqual("'flameshot gui'", settings.values[(SLOT.format("custom1"), "command")])
        self.assertEqual("'Flameshot Print'", settings.values[(SLOT.format("custom1"), "name")])
        # Cinnamon binds them at once: custom-list changes, and ends as it was.
        lists = [value for schema, key, value in settings.writes if key == "custom-list"]
        self.assertEqual(["['custom1', 'custom0']", "['custom0', 'custom1']"], lists)
        self.assertEqual("custom-list", settings.writes[-1][1])
        self.assertIn("<Super><Shift>s and Print start Flameshot for caram", logged[-1])

    def test_a_shortcut_the_user_set_stays(self) -> None:
        settings = FakeSettings({(SLOT.format("custom1"), "command"): "'gnome-screenshot -i'",
                                 (SLOT.format("custom1"), "binding"): "['Print']"})
        fix(settings)

        self.assertEqual("'gnome-screenshot -i'", settings.values[(SLOT.format("custom1"), "command")])
        self.assertEqual("['<Super><Shift>s']", settings.values[(SLOT.format("custom0"), "binding")])
        self.assertNotIn((SLOT.format("custom1"), "command", "'flameshot gui'"), settings.writes)

    def test_a_key_the_user_gave_to_something_else_stays_theirs(self) -> None:
        settings = FakeSettings({(KEYBINDINGS, "custom-list"): "['custom0', 'custom1', 'custom2']",
                                 (SLOT.format("custom2"), "command"): "'xfce4-screenshooter'",
                                 (SLOT.format("custom2"), "binding"): "['Print']"})
        logged = fix(settings)

        self.assertEqual("@as []", settings.values.get((SLOT.format("custom1"), "binding"), "@as []"))
        self.assertEqual("['<Super><Shift>s']", settings.values[(SLOT.format("custom0"), "binding")])
        self.assertIn("Print does something else for caram: leave custom1 empty", logged)
        self.assertEqual(["custom0", "custom1", "custom2"], settings.get(KEYBINDINGS, "custom-list"))

    def test_cinnamons_own_screenshot_key_turned_on_again(self) -> None:
        settings = FakeSettings({(MEDIA_KEYS, "screenshot"): "['Print']"})
        fix(settings)
        self.assertNotIn((SLOT.format("custom1"), "binding"), settings.values)
        self.assertEqual("['<Super><Shift>s']", settings.values[(SLOT.format("custom0"), "binding")])

    def test_slots_the_user_took_out_of_the_list_come_back_with_the_keys(self) -> None:
        settings = FakeSettings({(KEYBINDINGS, "custom-list"): "['custom5']"})
        fix(settings)
        self.assertEqual([(KEYBINDINGS, "custom-list", "['custom5', 'custom0', 'custom1']")],
                         [write for write in settings.writes if write[1] == "custom-list"])

    def test_nothing_to_do_when_the_defaults_apply(self) -> None:
        settings = FakeSettings({(SLOT.format(slot), key): value
                                 for slot, binding in (("custom0", "['<Super><Shift>s']"), ("custom1", "['Print']"))
                                 for key, value in (("command", "'flameshot gui'"), ("binding", binding))})
        fix(settings)
        self.assertEqual([], settings.writes)

    def test_unreadable_settings_are_left_alone(self) -> None:
        settings = FakeSettings({(KEYBINDINGS, "custom-list"): "not a list"})
        logged = fix(settings)
        self.assertEqual([], settings.writes)
        self.assertIn("warning: could not read the custom shortcuts of caram; leave them as they are", logged)

    def test_a_write_that_fails_changes_no_list(self) -> None:
        settings = FakeSettings(fail_set=True)
        logged = fix(settings)
        self.assertEqual([], settings.writes)
        self.assertTrue(any(line.startswith("warning: could not set custom0 of caram") for line in logged))

    def test_gsettings_runs_as_the_user_in_their_session_or_a_new_bus(self) -> None:
        with mock.patch.object(migration.subprocess, "run") as run:
            migration._gsettings("caram", {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"},
                                 ["get", KEYBINDINGS, "custom-list"])
            migration._gsettings("caram", {}, ["get", KEYBINDINGS, "custom-list"])
        self.assertEqual(["runuser", "-u", "caram", "--", "gsettings", "get", KEYBINDINGS, "custom-list"],
                         run.call_args_list[0].args[0])
        self.assertEqual(["runuser", "-u", "caram", "--", "dbus-run-session", "--", "gsettings"],
                         run.call_args_list[1].args[0][:7])


class RunTests(unittest.TestCase):
    def run_migration(self, *, dry_run: bool = False, logged_in: bool = False, flameshot: bool = True,
                      existing: str | None = None) -> tuple[Path, mock.Mock, mock.Mock]:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        tool = base / "flameshot"
        if flameshot:
            tool.touch()
        defaults = base / "local.d/02-caramos-screenshot-keys"
        if existing is not None:
            defaults.parent.mkdir()
            defaults.write_text(existing, encoding="utf-8")
        bus = base / "bus"
        if logged_in:
            bus.touch()
        context = MigrationContext(dry_run=dry_run)
        with mock.patch.object(migration, "FLAMESHOT", tool), mock.patch.object(migration, "DCONF_FILE", defaults), \
                mock.patch.object(migration, "_desktop_users", return_value=[("caram", 1000, base)]), \
                mock.patch.object(migration, "_session_bus", return_value=bus), \
                mock.patch.object(migration, "_fix_for_user") as fix_for_user, \
                mock.patch.object(context, "run_command") as run_command, \
                mock.patch.object(context, "log"):
            migration.run(context)
        return defaults, run_command, fix_for_user

    def test_defaults_then_every_user(self) -> None:
        defaults, run_command, fix_for_user = self.run_migration()
        self.assertEqual(migration.dconf_defaults(), defaults.read_text(encoding="utf-8"))
        run_command.assert_called_once_with(["dconf", "update"], allow_fail=True)
        self.assertEqual("caram", fix_for_user.call_args.args[1])

    def test_no_dconf_update_under_a_running_session(self) -> None:
        defaults, run_command, fix_for_user = self.run_migration(logged_in=True)
        self.assertTrue(defaults.is_file())
        run_command.assert_not_called()
        fix_for_user.assert_called_once()

    def test_defaults_in_place_need_no_dconf_update(self) -> None:
        _defaults, run_command, fix_for_user = self.run_migration(existing=migration.dconf_defaults())
        run_command.assert_not_called()
        fix_for_user.assert_called_once()

    def test_dry_run_changes_nothing(self) -> None:
        defaults, run_command, fix_for_user = self.run_migration(dry_run=True)
        self.assertFalse(defaults.exists())
        run_command.assert_not_called()
        fix_for_user.assert_not_called()

    def test_without_flameshot_the_keys_stay_as_they_are(self) -> None:
        defaults, run_command, fix_for_user = self.run_migration(flameshot=False)
        self.assertFalse(defaults.exists())
        fix_for_user.assert_not_called()

    def test_manifest(self) -> None:
        manifest = json.loads(Path(migration.__file__).with_name("manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((2, "important"), (manifest["schema"], manifest["severity"]))
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))


if __name__ == "__main__":
    unittest.main()

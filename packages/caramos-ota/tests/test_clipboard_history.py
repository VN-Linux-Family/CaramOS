"""Super+V shows the clipboard history (ticket H-1182): caramos-clipboard, migration 20261120100000, and the Xfce
edition's Super key (caramos-super-key, xcape)."""

from __future__ import annotations

import ast
import configparser
import importlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext, MigrationContextError

ROOT = Path(__file__).parents[1]
REPO = ROOT.parents[1]
MIGRATION_DIR = ROOT / "usr/lib/python3/dist-packages/caramos_ota_update/migrations/20261120100000_clipboard_history"
ISO_DCONF = REPO / "config/includes.chroot/etc/dconf/db/local.d/03-caramos-clipboard-key"
ISO_OVERRIDE = REPO / "config/includes.chroot/usr/share/glib-2.0/schemas/99_caramos.gschema.override"
ISO_XFCE_SHORTCUTS = (REPO / "config/includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml"
                      / "xfce4-keyboard-shortcuts.xml")
CLIPBOARD = ROOT / "usr/bin/caramos-clipboard"
SUPER_KEY = ROOT / "usr/share/caramos-ota/xfce/caramos-super-key"
SUPER_KEY_AUTOSTART = ROOT / "etc/xdg/autostart/caramos-xfce-super-key.desktop"

migration = importlib.import_module("caramos_ota_update.migrations.20261120100000_clipboard_history.migration")

KEYBINDINGS = "org.cinnamon.desktop.keybindings"
MEDIA_KEYS = "org.cinnamon.desktop.keybindings.media-keys"
SLOT = "org.cinnamon.desktop.keybindings.custom-keybinding:/org/cinnamon/desktop/keybindings/custom-keybindings/{}/"

# The 1.4.0 ISO's Xfce shortcuts, as far as this migration looks at them.
XFCE_1_4_0 = """<?xml version="1.0" encoding="UTF-8"?>
<!-- CaramOS Xfce -->

<channel name="xfce4-keyboard-shortcuts" version="1.0">
  <property name="commands" type="empty">
    <property name="default" type="empty">
      <property name="&lt;Alt&gt;F1" type="string" value="xfce4-popup-applicationsmenu"/>
      <property name="&lt;Shift&gt;&lt;Super&gt;s" type="string" value="flameshot gui"/>
      <property name="Super_L" type="string" value="xfce4-popup-whiskermenu"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;t" type="string" value="x-terminal-emulator"/>
    </property>
  </property>
  <property name="xfwm4" type="empty">
    <property name="default" type="empty">
      <property name="&lt;Super&gt;Tab" type="string" value="switch_window_key"/>
    </property>
  </property>
</channel>
"""


def commands_default(text: str) -> dict[str, str]:
    default = ElementTree.fromstring(text.encode("utf-8")).find("property[@name='commands']/property[@name='default']")
    return {item.get("name", ""): item.get("value", "") for item in default}


class FakeSettings:
    """gsettings for one user, values as gsettings prints them: a CaramOS 1.4.0 Cinnamon user by default."""

    def __init__(self, values: dict[tuple[str, str], str] | None = None, fail_set: bool = False) -> None:
        self.values = {(KEYBINDINGS, "custom-list"): "['custom0', 'custom1']",
                       (SLOT.format("custom0"), "command"): "'flameshot gui'",
                       (SLOT.format("custom0"), "binding"): "['<Super><Shift>s']",
                       (SLOT.format("custom1"), "command"): "'flameshot gui'",
                       (SLOT.format("custom1"), "binding"): "['Print']",
                       (MEDIA_KEYS, "home"): "['<Super>e']"}
        self.values.update(values or {})
        self.writes: list[tuple[str, str, str]] = []
        self.fail_set = fail_set

    def __call__(self, username: str, env: dict[str, str], args: list[str]) -> subprocess.CompletedProcess[str]:
        command, schema = args[0], args[1]
        if command == "get":
            default = {"name": "''", "command": "''", "binding": "@as []"}.get(args[2], "")
            return subprocess.CompletedProcess(args, 0, self.values.get((schema, args[2]), default) + "\n", "")
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
        return migration.screenshot.parse(self.values.get((schema, key), "@as []"))


def give_cinnamon_key(settings: FakeSettings) -> list[str]:
    context = MigrationContext()
    logged: list[str] = []
    with mock.patch.object(migration.screenshot, "_gsettings", settings), \
            mock.patch.object(context, "log", side_effect=logged.append):
        migration.cinnamon_user(context, "caram", 1000, Path("/home/caram"))
    return logged


class CinnamonDefaultsTests(unittest.TestCase):
    @unittest.skipUnless((REPO / "config").is_dir(), "ISO tree is not in the source package")
    def test_new_installs_get_the_migrations_defaults(self) -> None:
        self.assertEqual(migration.dconf_defaults(), ISO_DCONF.read_text(encoding="utf-8"))
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(migration.dconf_defaults())
        self.assertEqual({"org/cinnamon/desktop/keybindings/custom-keybindings/custom2":
                          {"name": "'CopyQ'", "command": "'caramos-clipboard'", "binding": "['<Super>v']"}},
                         {section: dict(parser[section]) for section in parser.sections()})

    @unittest.skipUnless((REPO / "config").is_dir(), "ISO tree is not in the source package")
    def test_the_iso_lists_custom2(self) -> None:
        self.assertIn(f"\n{migration.LIST_AFTER}\n", ISO_OVERRIDE.read_text(encoding="utf-8"))

    def test_the_override_of_1_4_0_gets_custom2(self) -> None:
        old = "[org.cinnamon.desktop.keybindings]\ncustom-list=['custom0', 'custom1']\n"
        self.assertEqual("[org.cinnamon.desktop.keybindings]\ncustom-list=['custom0', 'custom1', 'custom2']\n",
                         migration.override_with_slot(old))

    def test_an_override_changed_since_stays(self) -> None:
        for text in ("custom-list=['custom0']\n", "custom-list=['custom0', 'custom1', 'custom2']\n", "",
                     "custom-list=['custom0', 'custom1']\ncustom-list=['custom0', 'custom1']\n"):
            with self.subTest(text):
                self.assertEqual("", migration.override_with_slot(text))

    def test_defaults_written_and_schemas_compiled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "schemas/99_caramos.gschema.override"
            override.parent.mkdir()
            override.write_text("[org.cinnamon.desktop.keybindings]\ncustom-list=['custom0', 'custom1']\n",
                                encoding="utf-8")
            dconf_file = Path(tmp) / "dconf/03-caramos-clipboard-key"
            context = MigrationContext()
            with mock.patch.object(context, "run_command") as run, mock.patch.object(context, "log"):
                migration.cinnamon_defaults(context, [("caram", 1000, Path("/home/caram"))], override, dconf_file,
                                            Path(tmp) / "run")
            self.assertEqual(migration.dconf_defaults(), dconf_file.read_text(encoding="utf-8"))
            self.assertIn(migration.LIST_AFTER, override.read_text(encoding="utf-8"))
            commands = [call.args[0] for call in run.call_args_list]
            self.assertIn(["dconf", "update"], commands)
            self.assertIn(["glib-compile-schemas", str(override.parent)], commands)

    def test_no_dconf_update_under_a_running_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "run/1000").mkdir(parents=True)
            (Path(tmp) / "run/1000/bus").touch()
            context = MigrationContext()
            with mock.patch.object(context, "run_command") as run, mock.patch.object(context, "log"):
                migration.cinnamon_defaults(context, [("caram", 1000, Path("/home/caram"))],
                                            Path(tmp) / "missing.override", Path(tmp) / "dconf/03",
                                            Path(tmp) / "run")
            self.assertNotIn(["dconf", "update"], [call.args[0] for call in run.call_args_list])


class CinnamonUserTests(unittest.TestCase):
    def test_a_user_of_1_4_0_gets_custom2(self) -> None:
        settings = FakeSettings()
        give_cinnamon_key(settings)
        self.assertEqual("caramos-clipboard", settings.get(SLOT.format("custom2"), "command"))
        self.assertEqual(["<Super>v"], settings.get(SLOT.format("custom2"), "binding"))
        self.assertEqual("CopyQ", settings.get(SLOT.format("custom2"), "name"))
        self.assertEqual(["custom0", "custom1", "custom2"], settings.get(KEYBINDINGS, "custom-list"))
        self.assertEqual("custom-list", settings.writes[-1][1], "the list last, so Cinnamon binds the slot at once")

    def test_the_users_own_custom2_stays(self) -> None:
        settings = FakeSettings({(KEYBINDINGS, "custom-list"): "['custom0', 'custom1', 'custom2']",
                                 (SLOT.format("custom2"), "command"): "'gnome-calculator'",
                                 (SLOT.format("custom2"), "binding"): "['<Super>c']"})
        give_cinnamon_key(settings)
        self.assertEqual("gnome-calculator", settings.get(SLOT.format("custom2"), "command"))
        self.assertEqual("caramos-clipboard", settings.get(SLOT.format("custom3"), "command"))
        self.assertEqual(["custom0", "custom1", "custom2", "custom3"], settings.get(KEYBINDINGS, "custom-list"))

    def test_a_slot_with_the_system_defaults_is_used(self) -> None:
        # dconf update ran: custom2 reads CaramOS's values although this user's list never had it.
        settings = FakeSettings({(SLOT.format("custom2"), "command"): "'caramos-clipboard'",
                                 (SLOT.format("custom2"), "binding"): "['<Super>v']"})
        give_cinnamon_key(settings)
        self.assertEqual(["custom0", "custom1", "custom2"], settings.get(KEYBINDINGS, "custom-list"))

    def test_custom2_listed_by_the_new_default_but_still_empty(self) -> None:
        # The new override is compiled, dconf update has not run yet: custom2 is in the list without values.
        settings = FakeSettings({(KEYBINDINGS, "custom-list"): "['custom0', 'custom1', 'custom2']"})
        give_cinnamon_key(settings)
        self.assertEqual("caramos-clipboard", settings.get(SLOT.format("custom2"), "command"))
        self.assertEqual("''", settings.values.get((SLOT.format("custom3"), "command"), "''"), "no second slot")
        lists = [value for _schema, key, value in settings.writes if key == "custom-list"]
        self.assertEqual(["['custom2', 'custom1', 'custom0']", "['custom0', 'custom1', 'custom2']"], lists,
                         "the same list, written twice so Cinnamon binds custom2 at once")

    def test_users_before_the_system_defaults(self) -> None:
        order: list[str] = []
        with mock.patch.object(migration, "install_packages"), \
                mock.patch.object(migration, "_desktop_users", return_value=[("caram", 1000, Path("/home/caram"))]), \
                mock.patch.object(migration, "cinnamon_user", side_effect=lambda *_args: order.append("user")), \
                mock.patch.object(migration, "cinnamon_defaults", side_effect=lambda *_args: order.append("defaults")):
            migration.run(MigrationContext(), desktop="cinnamon")
        self.assertEqual(["user", "defaults"], order)

    def test_super_v_of_the_user_stays(self) -> None:
        settings = FakeSettings({(KEYBINDINGS, "custom-list"): "['custom0', 'custom1', 'custom5']",
                                 (SLOT.format("custom5"), "command"): "'diodon'",
                                 (SLOT.format("custom5"), "binding"): "['<Mod4>V']"})
        logged = give_cinnamon_key(settings)
        self.assertEqual([], settings.writes)
        self.assertTrue(any("does something else" in line for line in logged), logged)

    def test_super_v_of_cinnamon_stays(self) -> None:
        settings = FakeSettings({(MEDIA_KEYS, "screensaver"): "['<Super>v']"})
        give_cinnamon_key(settings)
        self.assertEqual([], settings.writes)

    def test_nothing_to_do_twice(self) -> None:
        settings = FakeSettings({(KEYBINDINGS, "custom-list"): "['custom0', 'custom1', 'custom2']",
                                 (SLOT.format("custom2"), "command"): "'caramos-clipboard'",
                                 (SLOT.format("custom2"), "binding"): "['<Super>v']"})
        logged = give_cinnamon_key(settings)
        self.assertEqual([], settings.writes)
        self.assertTrue(any("already" in line for line in logged), logged)

    def test_unreadable_settings_are_left_alone(self) -> None:
        settings = FakeSettings({(KEYBINDINGS, "custom-list"): "not a list"})
        give_cinnamon_key(settings)
        self.assertEqual([], settings.writes)

    def test_a_write_that_fails_changes_no_list(self) -> None:
        settings = FakeSettings(fail_set=True)
        logged = give_cinnamon_key(settings)
        self.assertEqual(["custom0", "custom1"], settings.get(KEYBINDINGS, "custom-list"))
        self.assertTrue(any(line.startswith("warning:") for line in logged), logged)


class XfceDefaultsTests(unittest.TestCase):
    def test_1_4_0_defaults(self) -> None:
        new = commands_default(migration.xfce_defaults_updated(XFCE_1_4_0))
        self.assertEqual("xfce4-popup-whiskermenu", new["<Alt>F1"])
        self.assertNotIn("Super_L", new)
        self.assertEqual("caramos-clipboard", new["<Super>v"])
        self.assertEqual("flameshot gui", new["<Shift><Super>s"])

    def test_indentation_and_order_kept(self) -> None:
        new = migration.xfce_defaults_updated(XFCE_1_4_0)
        self.assertIn('\n      <property name="&lt;Alt&gt;F1" type="string" value="xfce4-popup-whiskermenu"/>\n', new)
        self.assertIn('x-terminal-emulator"/>\n      <property name="&lt;Super&gt;v" type="string" '
                      'value="caramos-clipboard"/>\n    </property>\n', new)

    def test_once(self) -> None:
        self.assertEqual("", migration.xfce_defaults_updated(migration.xfce_defaults_updated(XFCE_1_4_0)))

    @unittest.skipUnless((REPO / "config").is_dir(), "ISO tree is not in the source package")
    def test_the_iso_has_them(self) -> None:
        iso = ISO_XFCE_SHORTCUTS.read_text(encoding="utf-8")
        self.assertEqual("", migration.xfce_defaults_updated(iso))
        defaults = commands_default(iso)
        self.assertEqual(("xfce4-popup-whiskermenu", "caramos-clipboard"), (defaults["<Alt>F1"], defaults["<Super>v"]))
        self.assertNotIn("Super_L", defaults)

    def test_an_alt_f1_of_someone_else_keeps_super_l(self) -> None:
        text = XFCE_1_4_0.replace("xfce4-popup-applicationsmenu", "xfce4-appfinder")
        new = commands_default(migration.xfce_defaults_updated(text))
        self.assertEqual(("xfce4-appfinder", "xfce4-popup-whiskermenu"), (new["<Alt>F1"], new["Super_L"]))
        self.assertEqual("caramos-clipboard", new["<Super>v"])

    def test_a_super_v_there_stays(self) -> None:
        text = XFCE_1_4_0.replace('"&lt;Primary&gt;&lt;Alt&gt;t" type="string" value="x-terminal-emulator"',
                                  '"&lt;Super&gt;v" type="string" value="diodon"')
        self.assertEqual("diodon", commands_default(migration.xfce_defaults_updated(text))["<Super>v"])

    def test_not_as_expected(self) -> None:
        for text in ("", "<channel/>", "not xml", XFCE_1_4_0.replace('<property name="commands"', "<x")):
            with self.subTest(text[:20]):
                self.assertEqual("", migration.xfce_defaults_updated(text))


class XfceUserTests(unittest.TestCase):
    LISTING = """/commands/custom/<Alt>F1                    xfce4-popup-applicationsmenu
/commands/custom/<Super>e                   thunar
/commands/custom/<Super>r                   xfce4-appfinder -c
/commands/custom/<Super>r/startup-notify    true
/commands/custom/override                   true
/commands/default/<Super>e                  thunar
/xfwm4/custom/<Super>Tab                    switch_window_key
"""

    def test_plans(self) -> None:
        cases = {
            "set": self.LISTING,
            "already shows the clipboard history": self.LISTING + "/commands/custom/<Super>v  caramos-clipboard\n",
            "<Super>v does something else: leave it": self.LISTING + "/commands/custom/<Mod4>V  diodon\n",
            "<Super>v does something else: leave it ": self.LISTING + "/xfwm4/custom/<Super>v  tile_up_key\n",
            "no shortcuts of their own yet: the defaults apply at their first login":
                "/commands/default/<Super>e   thunar\n",
        }
        for expected, listing in cases.items():
            with self.subTest(expected):
                self.assertEqual(expected.strip(), migration.xfce_plan(migration.xfce_properties(listing)))

    def run_user(self, listing: str, logged_in: bool) -> list[list[str]]:
        context = MigrationContext()
        calls: list[list[str]] = []

        def run_command(args, allow_fail=False, env=None):  # noqa: ANN001, ANN202
            calls.append(list(args))
            return subprocess.CompletedProcess(args, 0, listing if "-l" in args else "", "")

        with tempfile.TemporaryDirectory() as tmp:
            if logged_in:
                (Path(tmp) / "1000").mkdir()
                (Path(tmp) / "1000/bus").touch()
            with mock.patch.object(context, "run_command", side_effect=run_command), \
                    mock.patch.object(context, "log"):
                migration.xfce_user(context, "caram", 1000, Path(tmp))
        return calls

    def test_set_through_the_session_or_a_bus_of_its_own(self) -> None:
        set_call = ["xfconf-query", "-c", "xfce4-keyboard-shortcuts", "-p", "/commands/custom/<Super>v", "-n",
                    "-t", "string", "-s", "caramos-clipboard"]
        calls = self.run_user(self.LISTING, logged_in=True)
        self.assertEqual(["runuser", "-u", "caram", "--", *set_call], calls[-1])
        calls = self.run_user(self.LISTING, logged_in=False)
        self.assertEqual(["runuser", "-u", "caram", "--", "dbus-run-session", "--", *set_call], calls[-1])

    def test_nothing_set_when_not_needed(self) -> None:
        calls = self.run_user(self.LISTING + "/commands/custom/<Super>v  caramos-clipboard\n", logged_in=True)
        self.assertEqual(1, len(calls))


class PackagesAndRunTests(unittest.TestCase):
    def install(self, desktop: str, installed: set[str], fails: bool = False) -> tuple[list, list[str]]:
        context = MigrationContext()
        logged: list[str] = []
        apt = mock.Mock(side_effect=MigrationContextError("no network") if fails else None)
        with mock.patch.object(migration, "_installed", side_effect=lambda _c, package: package in installed), \
                mock.patch.object(context, "apt_install", apt), \
                mock.patch.object(context, "log", side_effect=logged.append):
            migration.install_packages(context, desktop)
        return apt.call_args_list, logged

    def test_cinnamon_gets_copyq_with_its_plugins(self) -> None:
        calls, _logged = self.install("cinnamon", set())
        self.assertEqual([mock.call(["copyq", "copyq-plugins"], recommends=False)], calls)

    def test_xfce_gets_xcape_too(self) -> None:
        calls, _logged = self.install("xfce", {"copyq"})
        self.assertEqual([mock.call(["copyq-plugins", "xcape"], recommends=False)], calls)

    def test_nothing_installed_twice(self) -> None:
        calls, _logged = self.install("xfce", {"copyq", "copyq-plugins", "xcape"})
        self.assertEqual([], calls)

    def test_no_network_is_no_failure(self) -> None:
        _calls, logged = self.install("cinnamon", set(), fails=True)
        self.assertTrue(any("could not install" in line for line in logged), logged)

    def test_each_edition_its_keys(self) -> None:
        for desktop, called, not_called in (("cinnamon", "cinnamon_defaults", "xfce_defaults"),
                                            ("xfce", "xfce_defaults", "cinnamon_defaults")):
            with self.subTest(desktop):
                context = MigrationContext()
                with mock.patch.object(migration, "install_packages"), \
                        mock.patch.object(migration, "_desktop_users", return_value=[]), \
                        mock.patch.object(migration, called) as wanted, \
                        mock.patch.object(migration, not_called) as other:
                    migration.run(context, desktop=desktop)
                wanted.assert_called_once()
                other.assert_not_called()

    def test_dry_run_changes_no_user(self) -> None:
        context = MigrationContext(dry_run=True)
        with mock.patch.object(migration, "install_packages"), \
                mock.patch.object(migration, "_desktop_users", return_value=[("caram", 1000, Path("/home/caram"))]), \
                mock.patch.object(migration, "cinnamon_defaults"), \
                mock.patch.object(migration, "cinnamon_user") as user, mock.patch.object(context, "log"):
            migration.run(context, desktop="cinnamon")
        user.assert_not_called()

    def test_manifest(self) -> None:
        manifest = json.loads((MIGRATION_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("desktops", manifest, "both editions")
        for key in ("title", "summary", "size", "title_en", "summary_en", "size_en"):
            self.assertTrue(manifest[key].strip(), key)
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))

    @unittest.skipUnless((REPO / "config").is_dir(), "ISO tree is not in the source package")
    def test_iso_package_lists(self) -> None:
        def packages(name: str) -> list[str]:
            lines = (REPO / "config" / name).read_text(encoding="utf-8").splitlines()
            return [line.strip() for line in lines if line.strip() and not line.startswith("#")]

        self.assertIn("copyq", packages("packages.txt"), "both editions: packages-xfce.txt adds to packages.txt")
        self.assertIn("xcape", packages("packages-xfce.txt"))


def load_clipboard() -> object:
    loader = importlib.machinery.SourceFileLoader("caramos_clipboard", str(CLIPBOARD))
    spec = importlib.util.spec_from_loader("caramos_clipboard", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class ClipboardCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clipboard = load_clipboard()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        self.menu = ["copyq", "eval", "--", self.clipboard.MENU]

    def press(self, *, installed: bool = True, running: bool = True, printed: str = "",
              results: dict[str, int] | None = None) -> tuple[list, list]:
        runs: list[list[str]] = []
        notes: list[list[str]] = []
        results = results or {}

        def run(args, **kwargs):  # noqa: ANN001, ANN202
            runs.append(list(args))
            if args[0] == "pgrep":
                return subprocess.CompletedProcess(args, 0 if running else 1)
            # Only the menu's command may read CopyQ's output: a command that starts CopyQ must not.
            reads = kwargs.get("stdout") == subprocess.PIPE
            self.assertEqual(reads, list(args) == self.menu, args)
            command = next(arg for arg in args[1:] if not arg.startswith("--"))
            return subprocess.CompletedProcess(args, results.get(command, 0), printed if reads else None)

        def popen(args, **_kwargs):  # noqa: ANN001, ANN202
            notes.append(list(args))
            return mock.Mock()

        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": str(self.state)}), \
                mock.patch.object(self.clipboard.shutil, "which", return_value="/usr/bin/copyq" if installed else None), \
                mock.patch.object(self.clipboard.subprocess, "run", side_effect=run), \
                mock.patch.object(self.clipboard.subprocess, "Popen", side_effect=popen):
            self.status = self.clipboard.main()
        return runs, notes

    def titles(self, notes: list[list[str]]) -> list[str]:
        return [note[-2] for note in notes]

    def test_first_press_turns_the_history_on(self) -> None:
        runs, notes = self.press()
        self.assertEqual(["pgrep", "-u", str(os.getuid()), "-x", "copyq"], runs[0])
        self.assertEqual([self.menu, ["copyq", "--start-server", "config", "autostart", "true"]], runs[1:])
        self.assertEqual([self.clipboard._("Clipboard history is on")], self.titles(notes))
        self.assertTrue((self.state / "caramos/clipboard-history").exists())
        self.assertEqual(0, self.status)

    def test_copyq_started_quietly_first(self) -> None:
        runs, _notes = self.press(running=False)
        self.assertEqual(["copyq", "--start-server", "eval", "--", self.clipboard.STORE], runs[1],
                         "with the text copied before CopyQ started")
        self.assertEqual(self.menu, runs[2])

    def test_later_presses_only_show_the_list(self) -> None:
        self.press()
        runs, notes = self.press()
        self.assertEqual(self.menu, runs[-1])
        self.assertEqual([], notes, "start at login turned off by the user stays off, without a word")

    def test_an_empty_history_says_so(self) -> None:
        self.press()
        _runs, notes = self.press(printed="empty\n")
        self.assertEqual([self.clipboard._("Nothing copied yet")], self.titles(notes))
        self.assertEqual("--icon=edit-paste", notes[0][2])

    def test_the_first_press_says_it_once(self) -> None:
        _runs, notes = self.press(printed="empty\n")
        self.assertEqual([self.clipboard._("Clipboard history is on")], self.titles(notes))

    def test_copyqs_own_menu_when_the_script_fails(self) -> None:
        runs, _notes = self.press(results={"eval": 4})
        self.assertEqual(["copyq", "--start-server", "menu"], runs[2])

    def test_nothing_turned_on_when_copyq_does_not_answer(self) -> None:
        runs, notes = self.press(results={"eval": 1, "menu": 1})
        self.assertEqual(3, len(runs))
        self.assertEqual([], notes)
        self.assertFalse((self.state / "caramos/clipboard-history").exists())
        self.assertEqual(1, self.status)

    def test_without_copyq(self) -> None:
        runs, notes = self.press(installed=False)
        self.assertEqual([], runs)
        self.assertIn("sudo apt install copyq", notes[0][-1])
        self.assertEqual(1, self.status)

    def test_the_menu_script(self) -> None:
        # The newest items of the clipboard's tab, CopyQ's own menu when no tab keeps the clipboard, and a word back
        # when the tab is empty (CopyQ shows no menu then).
        self.assertIn('config("clipboard_tab")', self.clipboard.MENU)
        self.assertIn(f"if (size() > 0) menu(name, {self.clipboard.ITEMS}); else print(\"empty\");",
                      self.clipboard.MENU)
        self.assertEqual(self.clipboard.MENU.count("{"), self.clipboard.MENU.count("}"))

    def test_the_store_script(self) -> None:
        # The clipboard's text into the clipboard's tab, unless it is its newest item already.
        self.assertIn("var text = str(clipboard());", self.clipboard.STORE)
        self.assertIn("if (size() == 0 || str(read(0)) != text) add(text);", self.clipboard.STORE)
        self.assertEqual(self.clipboard.STORE.count("{"), self.clipboard.STORE.count("}"))

    def test_copyq_never_keeps_the_callers_pipes(self) -> None:
        tree = ast.parse(CLIPBOARD.read_text(encoding="utf-8"))
        quiet = next(node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                     and getattr(node.targets[0], "id", "") == "QUIET")
        self.assertEqual({"stdin", "stdout", "stderr"}, {key.value for key in quiet.value.keys})

    def test_executable_and_shipped(self) -> None:
        self.assertTrue(os.access(CLIPBOARD, os.X_OK))
        self.assertIn("usr/bin/caramos-clipboard usr/bin/", (ROOT / "debian/install").read_text(encoding="utf-8"))


class SuperKeyTests(unittest.TestCase):
    """caramos-super-key with xfconf-query, pkill and xcape replaced by fakes."""

    def run_script(self, values: dict[str, str], xcape: bool = True) -> tuple[dict[str, str], list[list[str]]]:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            store = Path(tmp) / "xfconf.json"
            store.write_text(json.dumps(values), encoding="utf-8")
            calls = Path(tmp) / "calls.jsonl"
            (bin_dir / "xfconf-query").write_text("""#!/usr/bin/env python3
import json, os, sys
store = os.environ["STORE"]
values = json.load(open(store))
args = sys.argv[1:]
prop = args[args.index("-p") + 1]
if "-r" in args:
    values.pop(prop, None)
elif "-s" in args:
    values[prop] = args[args.index("-s") + 1]
elif prop in values:
    print(values[prop])
else:
    sys.exit(1)
json.dump(values, open(store, "w"))
""", encoding="utf-8")
            record = ("#!/usr/bin/env python3\nimport json, os, sys\n"
                      "open(os.environ['CALLS'], 'a').write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:])"
                      " + '\\n')\n")
            tools = ("pkill", "xcape") if xcape else ("pkill",)
            for tool in tools:
                (bin_dir / tool).write_text(record, encoding="utf-8")
            for tool in ("xfconf-query", *tools):
                (bin_dir / tool).chmod(0o755)
            # Only the fakes and the shell's basics: no real xcape from the host.
            path = f"{bin_dir}:/usr/bin:/bin" if xcape else f"{bin_dir}"
            env = {"PATH": path, "STORE": str(store), "CALLS": str(calls), "HOME": tmp}
            shell = "/bin/sh"
            result = subprocess.run([shell, str(SUPER_KEY)], env=env, text=True, capture_output=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stderr)
            lines = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
            return json.loads(store.read_text(encoding="utf-8")), [json.loads(line) for line in lines]

    XCAPE = ["xcape", "-d", "-e", "Super_L=Alt_L|F1;Super_R=Alt_L|F1"]

    def test_a_user_of_1_4_0(self) -> None:
        values, calls = self.run_script({"/commands/custom/override": "true",
                                         "/commands/custom/<Alt>F1": "xfce4-popup-applicationsmenu",
                                         "/commands/custom/Super_L": "xfce4-popup-whiskermenu",
                                         "/commands/custom/<Super>e": "thunar"})
        self.assertEqual({"/commands/custom/override": "true", "/commands/custom/<Alt>F1": "xfce4-popup-whiskermenu",
                          "/commands/custom/<Super>e": "thunar"}, values)
        self.assertEqual("pkill", calls[0][0])
        self.assertEqual(self.XCAPE, calls[-1])

    def test_an_alt_f1_of_the_users_own(self) -> None:
        before = {"/commands/custom/override": "true", "/commands/custom/<Alt>F1": "xfce4-appfinder",
                  "/commands/custom/Super_L": "xfce4-popup-whiskermenu"}
        values, calls = self.run_script(dict(before))
        self.assertEqual(before, values)
        self.assertEqual([], calls, "no xcape: the Super_L shortcut stays the way to the menu")

    def test_system_defaults_in_use(self) -> None:
        new = {"/commands/default/<Alt>F1": "xfce4-popup-whiskermenu"}
        values, calls = self.run_script(dict(new))
        self.assertEqual(new, values, "the user's own shortcuts are not started by a write")
        self.assertEqual(self.XCAPE, calls[-1])
        old = {"/commands/default/<Alt>F1": "xfce4-popup-applicationsmenu",
               "/commands/default/Super_L": "xfce4-popup-whiskermenu"}
        _values, calls = self.run_script(dict(old))
        self.assertEqual([], calls)

    def test_without_xcape_nothing_changes(self) -> None:
        before = {"/commands/custom/override": "true", "/commands/custom/<Alt>F1": "xfce4-popup-applicationsmenu",
                  "/commands/custom/Super_L": "xfce4-popup-whiskermenu"}
        values, calls = self.run_script(dict(before), xcape=False)
        self.assertEqual(before, values)
        self.assertEqual([], calls)

    def test_autostart_entry(self) -> None:
        entry = configparser.ConfigParser(interpolation=None)
        entry.optionxform = str
        entry.read_string(SUPER_KEY_AUTOSTART.read_text(encoding="utf-8"))
        group = entry["Desktop Entry"]
        self.assertEqual(("/usr/share/caramos-ota/xfce/caramos-super-key", "XFCE;"),
                         (group["Exec"], group["OnlyShowIn"]))
        self.assertIn("etc/xdg/autostart/caramos-xfce-super-key.desktop etc/xdg/autostart/",
                      (ROOT / "debian/install").read_text(encoding="utf-8"))
        self.assertTrue(os.access(SUPER_KEY, os.X_OK))

    def test_xcape_output_goes_nowhere(self) -> None:
        # In -d mode xcape prints every key event: never into ~/.xsession-errors.
        line = next(line for line in SUPER_KEY.read_text(encoding="utf-8").splitlines() if line.startswith("exec xcape"))
        self.assertTrue(line.endswith(">/dev/null 2>&1"), line)


if __name__ == "__main__":
    unittest.main()

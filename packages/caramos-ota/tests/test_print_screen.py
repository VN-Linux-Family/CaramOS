"""Print Screen copies the whole screen to the clipboard, with a short notification, on both editions (tickets H-1188
and H-1193): caramos-print-screen, and migration 20261124100200, which gives Print to it where it still runs
Flameshot's capture. Super+Shift+S keeps Flameshot."""

from __future__ import annotations

import ast
import configparser
import importlib
import json
import py_compile
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
HELPER = ROOT / "usr/bin/caramos-print-screen"
SHORTCUTS_1_5_0 = (ROOT / "tests/data/xfce4-keyboard-shortcuts.xml-1.5.0").read_text(encoding="utf-8")
ISO_XFCE = REPO / "config/includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml"
ISO_DCONF = REPO / "config/includes.chroot/etc/dconf/db/local.d/02-caramos-screenshot-keys"
migration = importlib.import_module("caramos_ota_update.migrations.20261124100200_print_screen_to_clipboard.migration")
screenshot = importlib.import_module("caramos_ota_update.migrations.20261112100000_screenshot_shortcuts.migration")


def msgids(path: Path) -> set[str]:
    ids, current = set(), None
    for line in path.read_text(encoding="utf-8").splitlines() + [""]:
        if line.startswith("msgid "):
            current = [line[6:]]
        elif current is not None and line.startswith('"'):
            current.append(line)
        else:
            if current is not None:
                ids.add("".join(ast.literal_eval(part) for part in current))
            current = None
    return ids


class HelperTests(unittest.TestCase):
    def test_it_compiles_and_is_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            py_compile.compile(str(HELPER), cfile=str(Path(tmp) / "x.pyc"), doraise=True)
        self.assertTrue(HELPER.stat().st_mode & 0o111)
        self.assertIn("usr/bin/caramos-print-screen usr/bin/", (ROOT / "debian/install").read_text(encoding="utf-8"))

    def test_the_clipboard_manager_keeps_one_png(self) -> None:
        source = HELPER.read_text(encoding="utf-8")
        # PNG only to the clipboard manager, then the program ends: nothing stays running for a paste to wait on.
        self.assertIn('PNG = "image/png"', source)
        self.assertIn("clipboard.set_can_store([Gtk.TargetEntry.new(PNG, 0, 0)])", source)
        self.assertIn("clipboard.store()", source)
        self.assertIn("supports_clipboard_persistence()", source, "without a manager it keeps the clipboard itself")
        self.assertIn('"transient"', source, "the notification does not pile up in the list")

    def test_every_word_is_translated(self) -> None:
        used = set()
        for node in ast.walk(ast.parse(HELPER.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_" and node.args:
                used.add(node.args[0].value)
        self.assertIn("Screenshot copied to the clipboard", used)
        self.assertEqual(set(), used - msgids(ROOT / "po/caramos-ota/caramos-ota.pot"))
        vi = (ROOT / "po/caramos-ota/vi.po").read_text(encoding="utf-8")
        self.assertIn('msgid "Screenshot copied to the clipboard"\nmsgstr "Đã chụp màn hình và chép vào bộ nhớ tạm"', vi)


class CinnamonTests(unittest.TestCase):
    def test_the_defaults(self) -> None:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(migration.dconf_defaults())
        custom0 = parser["org/cinnamon/desktop/keybindings/custom-keybindings/custom0"]
        custom1 = parser["org/cinnamon/desktop/keybindings/custom-keybindings/custom1"]
        self.assertEqual(("'flameshot gui'", "['<Super><Shift>s']"), (custom0["command"], custom0["binding"]))
        self.assertEqual(("'caramos-print-screen'", "['Print']"), (custom1["command"], custom1["binding"]))

    @unittest.skipUnless(ISO_DCONF.is_file(), "the source package has no config/")
    def test_new_installs_get_them(self) -> None:
        self.assertEqual(migration.dconf_defaults(), ISO_DCONF.read_text(encoding="utf-8"))

    def test_the_defaults_change_only_where_they_are_caramos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "02-caramos-screenshot-keys"
            context = MigrationContext()
            with mock.patch.object(context, "run_command") as run, mock.patch.object(context, "log"):
                path.write_text(screenshot.dconf_defaults(), encoding="utf-8")
                migration.cinnamon_defaults(context, [], path)
                self.assertEqual(migration.dconf_defaults(), path.read_text(encoding="utf-8"))
                run.assert_called_once_with(["dconf", "update"], allow_fail=True)
                run.reset_mock()
                migration.cinnamon_defaults(context, [], path)
                run.assert_not_called()
                path.write_text("# mine\n", encoding="utf-8")
                migration.cinnamon_defaults(context, [], path)
                self.assertEqual("# mine\n", path.read_text(encoding="utf-8"))

    def user(self, values: dict[str, str]) -> list[list[str]]:
        sets: list[list[str]] = []

        def gsettings(_user, _env, args):  # noqa: ANN001
            if args[0] == "set":
                sets.append(args)
                return subprocess.CompletedProcess(args, 0, "", "")
            key = f"{args[1]} {args[2]}"
            return subprocess.CompletedProcess(args, 0, values.get(key, "''") + "\n", "")

        with mock.patch.object(migration.screenshot, "_user_environment", return_value={}), \
                mock.patch.object(migration.screenshot, "_gsettings", side_effect=gsettings), \
                mock.patch.object(MigrationContext, "log"):
            migration.cinnamon_user(MigrationContext(), "minh", 1000, Path("/home/minh"))
        return sets

    def test_a_user_whose_print_runs_flameshot(self) -> None:
        slot = screenshot._slot_schema("custom1")
        sets = self.user({"org.cinnamon.desktop.keybindings custom-list": "['custom0', 'custom1', 'custom2']",
                          f"{slot} command": "'flameshot gui'", f"{slot} binding": "['Print']"})
        self.assertIn(["set", slot, "command", "'caramos-print-screen'"], sets)
        self.assertIn(["set", slot, "name", "'Screenshot to clipboard'"], sets)
        # Cinnamon binds custom shortcuts again when their list changes: written in another order, then as it was.
        lists = [entry[3] for entry in sets if entry[2] == "custom-list"]
        self.assertEqual(["['custom2', 'custom1', 'custom0']", "['custom0', 'custom1', 'custom2']"], lists)

    def test_a_user_with_their_own_print_keeps_it(self) -> None:
        slot = screenshot._slot_schema("custom1")
        sets = self.user({"org.cinnamon.desktop.keybindings custom-list": "['custom0', 'custom1']",
                          f"{slot} command": "'gnome-screenshot'", f"{slot} binding": "['Print']"})
        self.assertEqual([], sets)


class XfceTests(unittest.TestCase):
    def test_1_5_0(self) -> None:
        new = migration.xfce_defaults_updated(SHORTCUTS_1_5_0)
        self.assertIn('<property name="Print" type="string" value="caramos-print-screen"/>', new)
        self.assertIn('<property name="&lt;Shift&gt;&lt;Super&gt;s" type="string" value="flameshot gui"/>', new)
        self.assertEqual("", migration.xfce_defaults_updated(new), "once")
        self.assertEqual(len(SHORTCUTS_1_5_0), len(new) - len("caramos-print-screen") + len("flameshot gui"))

    @unittest.skipUnless(ISO_XFCE.is_file(), "the source package has no config/")
    def test_new_installs(self) -> None:
        text = ISO_XFCE.read_text(encoding="utf-8")
        self.assertIn('<property name="Print" type="string" value="caramos-print-screen"/>', text)
        self.assertEqual("", migration.xfce_defaults_updated(text))

    def test_user(self) -> None:
        for listing, expected in (("/commands/custom/override   true\n/commands/custom/Print   flameshot gui\n", 1),
                                  ("/commands/custom/override   true\n/commands/custom/Print   xfce4-screenshooter\n", 0),
                                  ("", 0)):
            commands: list[list[str]] = []

            def run_command(argv, allow_fail=False, env=None, listing=listing):  # noqa: ANN001
                commands.append(list(argv))
                return subprocess.CompletedProcess(argv, 0, listing if argv[-2:] == ["-l", "-v"] else "", "")

            context = MigrationContext()
            with tempfile.TemporaryDirectory() as tmp, \
                    mock.patch.object(context, "run_command", side_effect=run_command), \
                    mock.patch.object(context, "log"):
                migration.xfce_user(context, "minh", 1000, runtime_root=Path(tmp))
            writes = [command for command in commands if "-s" in command]
            self.assertEqual(expected, len(writes), listing)
            if writes:
                self.assertEqual(["-p", "/commands/custom/Print", "-t", "string", "-s", "caramos-print-screen"],
                                 writes[0][-6:])

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("desktops", manifest, "both editions")
        self.assertEqual("anytime", manifest["unattended"])
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))


if __name__ == "__main__":
    unittest.main()

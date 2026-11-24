"""Migration 20261124100100: on Xfce, Super+D shows the desktop (tickets H-1201, H-1202) and Super+E opens Files, not
Thunar (H-1185), as on Windows and on the Cinnamon edition."""

from __future__ import annotations

import importlib
import json
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
SHORTCUTS_1_5_0 = (ROOT / "tests/data/xfce4-keyboard-shortcuts.xml-1.5.0").read_text(encoding="utf-8")
ISO = REPO / "config/includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml"
migration = importlib.import_module("caramos_ota_update.migrations.20261124100100_xfce_super_d_super_e.migration")


def defaults(text: str, provider: str) -> dict[str, str]:
    node = ElementTree.fromstring(text.encode("utf-8")).find(f"property[@name='{provider}']/property[@name='default']")
    return {item.get("name"): item.get("value") for item in node}


class DefaultsTests(unittest.TestCase):
    def test_1_5_0_gets_both_keys(self) -> None:
        new = migration.defaults_updated(SHORTCUTS_1_5_0)
        self.assertEqual("exo-open --launch FileManager", defaults(new, "commands")["<Super>e"])
        self.assertEqual("show_desktop_key", defaults(new, "xfwm4")["<Super>d"])
        self.assertEqual("show_desktop_key", defaults(new, "xfwm4")["<Control><Alt>d"], "Ctrl+Alt+D stays")
        self.assertEqual("", migration.defaults_updated(new), "once")
        old = SHORTCUTS_1_5_0.splitlines()
        self.assertEqual(len(old) + 2, len(new.splitlines()), "two lines more, nothing else")

    def test_thunar_is_replaced_something_else_stays(self) -> None:
        with_thunar = SHORTCUTS_1_5_0.replace(
            '<property name="&lt;Super&gt;v"',
            '<property name="&lt;Super&gt;e" type="string" value="thunar"/>\n      <property name="&lt;Super&gt;v"')
        self.assertEqual("exo-open --launch FileManager",
                         defaults(migration.defaults_updated(with_thunar), "commands")["<Super>e"])
        with_own = with_thunar.replace('value="thunar"', 'value="xfce4-taskmanager"')
        self.assertEqual("xfce4-taskmanager", defaults(migration.defaults_updated(with_own), "commands")["<Super>e"])

    def test_a_key_taken_by_the_other_provider_stays(self) -> None:
        taken = SHORTCUTS_1_5_0.replace(
            '<property name="&lt;Super&gt;v"',
            '<property name="&lt;Super&gt;d" type="string" value="xfce4-dict"/>\n      <property name="&lt;Super&gt;v"')
        new = migration.defaults_updated(taken)
        self.assertNotIn("<Super>d", defaults(new, "xfwm4"))
        self.assertEqual("xfce4-dict", defaults(new, "commands")["<Super>d"])

    def test_not_as_expected(self) -> None:
        self.assertEqual("", migration.defaults_updated("not xml"))
        self.assertEqual("", migration.defaults_updated('<channel name="xfce4-keyboard-shortcuts" version="1.0"/>'))

    @unittest.skipUnless(ISO.is_file(), "the source package has no config/")
    def test_new_installs_have_them(self) -> None:
        text = ISO.read_text(encoding="utf-8")
        self.assertEqual("", migration.defaults_updated(text))
        self.assertEqual("exo-open --launch FileManager", defaults(text, "commands")["<Super>e"])
        self.assertEqual("show_desktop_key", defaults(text, "xfwm4")["<Super>d"])


class UserTests(unittest.TestCase):
    def test_plan(self) -> None:
        self.assertIsInstance(migration.user_plan({"/commands/default/<Super>e": "thunar"}), str)
        own = {"/commands/custom/override": "true", "/commands/custom/<Super>e": "thunar",
               "/commands/custom/<Super>r/startup-notify": "true", "/xfwm4/custom/<Control><Alt>d": "show_desktop_key"}
        self.assertEqual([("/commands/custom/<Super>e", "exo-open --launch FileManager"),
                          ("/xfwm4/custom/<Super>d", "show_desktop_key")], migration.user_plan(own))
        mine = {"/commands/custom/<Super>e": "geany", "/commands/custom/<Super>d": "xfce4-dict"}
        self.assertIsInstance(migration.user_plan(mine), str, "keys given to something else stay")
        done = {"/commands/custom/<Super>e": "exo-open --launch FileManager", "/xfwm4/custom/<Super>d": "show_desktop_key"}
        self.assertIsInstance(migration.user_plan(done), str)

    def test_user(self) -> None:
        listing = ("/commands/custom/override   true\n/commands/custom/<Super>e   thunar\n"
                   "/xfwm4/custom/override   true\n/xfwm4/custom/<Primary><Alt>d   show_desktop_key\n")
        commands: list[list[str]] = []

        def run_command(argv, allow_fail=False, env=None):  # noqa: ANN001
            commands.append(list(argv))
            output = listing if argv[-2:] == ["-l", "-v"] else ""
            return subprocess.CompletedProcess(argv, 0, output, "")

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "1000").mkdir()
            (Path(tmp) / "1000" / "bus").touch()
            context = MigrationContext()
            with mock.patch.object(context, "run_command", side_effect=run_command), mock.patch.object(context, "log"):
                migration.xfce_user(context, "minh", 1000, runtime_root=Path(tmp))
        writes = [command for command in commands if "-s" in command]
        self.assertEqual(2, len(writes))
        self.assertTrue(all("dbus-run-session" not in command for command in commands), "the session's xfconfd")
        self.assertIn(["runuser", "-u", "minh", "--", "xfconf-query", "-c", "xfce4-keyboard-shortcuts", "-p",
                       "/xfwm4/custom/<Super>d", "-n", "-t", "string", "-s", "show_desktop_key"], writes)

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(["xfce"], manifest["desktops"])
        self.assertEqual("anytime", manifest["unattended"], "keys: nothing on the screen changes")
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))


if __name__ == "__main__":
    unittest.main()

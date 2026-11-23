"""Migration 20261120100700_windows_shortcuts: Super+L locks, Ctrl+Alt+Delete and Ctrl+Alt+End log out and shut down,
the same on both editions."""

from __future__ import annotations

import importlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).parents[1]
CONFIG = ROOT.parents[1] / "config"
ISO_OVERRIDE = CONFIG / "includes.chroot/usr/share/glib-2.0/schemas/99_caramos.gschema.override"
ISO_XFCE = CONFIG / "includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml"
migration = importlib.import_module("caramos_ota_update.migrations.20261120100700_windows_shortcuts.migration")

OVERRIDE_BEFORE = """[org.cinnamon.desktop.keybindings.media-keys]
screenshot=@as []
area-screenshot-clip=@as []

# custom2: Super+V
[org.cinnamon.desktop.keybindings]
custom-list=['custom0', 'custom1', 'custom2']
"""
XFCE_BEFORE = """<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-keyboard-shortcuts" version="1.0">
  <property name="commands" type="empty">
    <property name="default" type="empty">
      <property name="&lt;Alt&gt;F1" type="string" value="xfce4-popup-whiskermenu"/>
      <property name="&lt;Primary&gt;&lt;Alt&gt;Delete" type="string" value="xflock4"/>
      <property name="&lt;Super&gt;v" type="string" value="caramos-clipboard"/>
    </property>
  </property>
</channel>
"""


class CinnamonTests(unittest.TestCase):
    def test_keys_after_their_section(self) -> None:
        new = migration.override_with_keys(OVERRIDE_BEFORE)
        lines = new.splitlines()
        lock = lines.index("screensaver=['<Control><Alt>l', '<Super>l', 'XF86ScreenSaver']")
        self.assertLess(lines.index("area-screenshot-clip=@as []"), lock)
        self.assertLess(lock, lines.index("# custom2: Super+V"), "the next section's comment stays with it")
        self.assertGreater(lines.index("looking-glass-keybinding=@as []"), lines.index("[org.cinnamon.desktop.keybindings]"))
        self.assertEqual(new, migration.override_with_keys(new))

    def test_missing_sections_are_added(self) -> None:
        new = migration.override_with_keys("[org.cinnamon]\nfoo=1")
        self.assertIn("[org.cinnamon.desktop.keybindings.media-keys]\n", new)
        self.assertIn("[org.cinnamon.desktop.keybindings]\n", new)
        self.assertTrue(new.startswith("[org.cinnamon]\nfoo=1\n"))

    def test_the_iso_has_them(self) -> None:
        if not ISO_OVERRIDE.is_file():
            self.skipTest("the source package has no config/")
        text = ISO_OVERRIDE.read_text(encoding="utf-8")
        self.assertEqual(text, migration.override_with_keys(text))

    def test_defaults_written_then_compiled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            override = Path(tmp) / "99_caramos.gschema.override"
            override.write_text(OVERRIDE_BEFORE, encoding="utf-8")
            context = MigrationContext()
            with mock.patch.object(context, "run_command",
                                   return_value=subprocess.CompletedProcess([], 0, "", "")) as run, \
                    mock.patch.object(context, "log"):
                migration.cinnamon_defaults(context, override, Path(tmp))
                run.assert_called_once_with(["glib-compile-schemas", tmp], allow_fail=True)
                run.reset_mock()
                migration.cinnamon_defaults(context, override, Path(tmp))
                run.assert_not_called()


class XfceDefaultsTests(unittest.TestCase):
    def test_keys_added_and_ctrl_alt_delete_changed(self) -> None:
        new = migration.xfce_defaults_updated(XFCE_BEFORE)
        for line in ('<property name="&lt;Super&gt;l" type="string" value="xflock4"/>',
                     '<property name="&lt;Primary&gt;&lt;Alt&gt;l" type="string" value="xflock4"/>',
                     '<property name="&lt;Primary&gt;&lt;Alt&gt;Delete" type="string" value="xfce4-session-logout"/>'):
            self.assertIn(f"      {line}\n", new)
        self.assertNotIn('value="xflock4"/>\n      <property name="&lt;Super&gt;v"', new)
        self.assertEqual("", migration.xfce_defaults_updated(new), "once")

    def test_no_key_of_the_window_manager(self) -> None:
        with_wm = XFCE_BEFORE.replace("</channel>", """  <property name="xfwm4" type="empty">
    <property name="default" type="empty">
      <property name="&lt;Control&gt;&lt;Alt&gt;l" type="string" value="maximize_window_key"/>
    </property>
  </property>
</channel>""")
        new = migration.xfce_defaults_updated(with_wm)
        self.assertNotIn('&lt;Primary&gt;&lt;Alt&gt;l" type="string" value="xflock4"', new)
        self.assertNotIn("End", new)

    def test_a_key_given_to_something_else_stays(self) -> None:
        mine = XFCE_BEFORE.replace('Delete" type="string" value="xflock4"', 'Delete" type="string" value="htop"')
        new = migration.xfce_defaults_updated(mine)
        self.assertIn('Delete" type="string" value="htop"', new)

    def test_not_as_expected(self) -> None:
        self.assertEqual("", migration.xfce_defaults_updated("not xml"))
        self.assertEqual("", migration.xfce_defaults_updated('<channel name="x" version="1.0"/>'))

    def test_the_iso_has_them(self) -> None:
        if not ISO_XFCE.is_file():
            self.skipTest("the source package has no config/")
        self.assertEqual("", migration.xfce_defaults_updated(ISO_XFCE.read_text(encoding="utf-8")))


class XfceUserTests(unittest.TestCase):
    def test_plan(self) -> None:
        self.assertIsInstance(migration.xfce_user_plan({"/commands/default/<Alt>F1": "x"}), str)
        own = {"/commands/custom/override": "true", "/commands/custom/<Primary><Alt>Delete": "xflock4",
               "/commands/custom/<Super>l": "firefox", "/xfwm4/custom/<Primary><Alt>End": "close_window_key"}
        self.assertEqual([("/commands/custom/<Primary><Alt>l", "xflock4"),
                          ("/commands/custom/<Primary><Alt>Delete", "xfce4-session-logout")],
                         migration.xfce_user_plan(own))
        done = {"/commands/custom/<Super>l": "xflock4", "/commands/custom/<Primary><Alt>l": "xflock4",
                "/commands/custom/<Primary><Alt>Delete": "xfce4-session-logout"}
        self.assertIsInstance(migration.xfce_user_plan(done), str)

    def test_user(self) -> None:
        listing = "/commands/custom/override   true\n/commands/custom/<Primary><Alt>Delete   xflock4\n"
        commands: list[list[str]] = []

        def run_command(argv, allow_fail=False, env=None):  # noqa: ANN001
            commands.append(list(argv))
            if argv[-2:] == ["-l", "-v"]:
                return subprocess.CompletedProcess(argv, 0, listing, "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            (runtime / "1000").mkdir()
            (runtime / "1000" / "bus").touch()
            context = MigrationContext()
            with mock.patch.object(context, "run_command", side_effect=run_command), \
                    mock.patch.object(context, "log"):
                migration.xfce_user(context, "minh", 1000, runtime_root=runtime)
        writes = [command for command in commands if "-s" in command]
        self.assertEqual(3, len(writes))
        self.assertTrue(all("dbus-run-session" not in command for command in commands))
        self.assertIn(["runuser", "-u", "minh", "--", "xfconf-query", "-c", "xfce4-keyboard-shortcuts", "-p",
                       "/commands/custom/<Primary><Alt>Delete", "-n", "-t", "string", "-s", "xfce4-session-logout"],
                      writes)

    def test_run(self) -> None:
        with mock.patch.object(migration, "cinnamon_defaults") as cinnamon, \
                mock.patch.object(migration, "xfce_defaults") as xfce, \
                mock.patch.object(migration, "xfce_user") as user, \
                mock.patch.object(migration.clipboard, "_desktop_users", return_value=[("minh", 1000, Path("/h"))]), \
                mock.patch.object(MigrationContext, "log"):
            with mock.patch.object(migration, "XFCE_SHORTCUTS", Path("/nonexistent")):
                migration.run(MigrationContext())
                user.assert_not_called()
            with tempfile.NamedTemporaryFile() as shortcuts, \
                    mock.patch.object(migration, "XFCE_SHORTCUTS", Path(shortcuts.name)):
                migration.run(MigrationContext())
                user.assert_called_once_with(mock.ANY, "minh", 1000)
            self.assertEqual(2, cinnamon.call_count)
            self.assertEqual(2, xfce.call_count)

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("desktops", manifest)
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))


if __name__ == "__main__":
    unittest.main()

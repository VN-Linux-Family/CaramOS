"""Migration 20261105120100_search_menu_while_composing: the Cinnamenu Start Menu searches the word Lotus is
still composing (preedit), so it finds apps while Vietnamese typing is on (ticket H-1098)."""

from __future__ import annotations

import importlib
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from caramos_ota_update.context import MigrationContext

migration = importlib.import_module("caramos_ota_update.migrations.20261105120100_search_menu_while_composing.migration")
start_fcitx = importlib.import_module("caramos_ota_update.migrations.20261022120000_start_fcitx_at_login.migration")

# The parts of Cinnamenu (5.8/applet.js and 5.8/display.js) the change goes into, as the 1.3.1 ISO has them.
APPLET = """const Meta = imports.gi.Meta;
const Main = imports.ui.main;

class CinnamenuApplet extends TextIconApplet {
//==============search==============
    _onSearchTextChanged() {
        const searchText = this.display.searchView.searchEntryText.get_text();

        if (searchText.length === 0) {//search text deleted, cancel search mode
            return;
        }
    }
}
"""
DISPLAY = """class Display {
    constructor (appThis) {
        this.searchView = new SearchView(this.appThis);
        this.displaySignals.connect(this.searchView.searchEntryText, 'text-changed',
                                        (...args) => this.appThis._onSearchTextChanged(...args));
        this.displaySignals.connect(this.searchView.searchEntryText, 'key-press-event',
                                                (...args) => this.appThis._onMenuKeyPress(...args));
    }
}
"""
# display.js of the Cinnamenu (metadata version 5.7) the 1.3.3 ISO carries in 5.8: the same connection over
# four lines, through this.applet.
DISPLAY_133 = """class Display {
    constructor (applet) {
        this.searchView = new SearchView(this.applet);
        this.displaySignals.connect(
            this.searchView.searchEntryText,
            'text-changed',
            (...args) => this.applet._onSearchTextChanged(...args)
        );
        this.displaySignals.connect(
            this.searchView.searchEntryText,
            'key-press-event',
            (...args) => this.applet._onMenuKeyPress(...args)
        );
    }
}
"""


class PatchTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "Cinnamenu@json"
        self.current = self.root / "5.8"
        self.old = self.root / "3.2"
        for version, applet, display in ((self.current, APPLET, DISPLAY), (self.old, "const x = 1;\n", "// old\n")):
            version.mkdir(parents=True)
            (version / "applet.js").write_text(applet, encoding="utf-8")
            (version / "display.js").write_text(display, encoding="utf-8")
        (self.root / "icons").mkdir()
        patcher = mock.patch.object(migration, "CINNAMENU", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(migration, "SYSTEMD_RUNTIME", Path(folder.name) / "no-systemd")
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self, folder: Path, name: str) -> str:
        return (folder / name).read_text(encoding="utf-8")

    def test_the_search_takes_the_composition_and_follows_it(self) -> None:
        migration.run(MigrationContext())
        applet, display = self.read(self.current, "applet.js"), self.read(self.current, "display.js")
        self.assertIn("this._withPreedit(this.display.searchView.searchEntryText.get_text())", applet)
        self.assertIn("Main.inputMethod._preeditStr", applet)
        self.assertIn("'cursor-changed'", display)
        self.assertIn("'text-changed'", display)
        self.assertIn("this.appThis._onSearchTextChanged();", display)
        # The other version and the rest of the files stay as they were.
        self.assertEqual("const x = 1;\n", self.read(self.old, "applet.js"))
        self.assertIn("if (searchText.length === 0)", applet)

    def test_the_cinnamenu_of_the_1_3_3_iso_too(self) -> None:
        (self.current / "display.js").write_text(DISPLAY_133, encoding="utf-8")
        migration.run(MigrationContext())
        applet, display = self.read(self.current, "applet.js"), self.read(self.current, "display.js")
        self.assertIn("this._withPreedit(", applet)
        self.assertIn("this.applet._onSearchTextChanged();", display)
        self.assertNotIn("appThis", display)
        # The addition comes after the whole text-changed connection, at its indentation.
        self.assertIn("""            (...args) => this.applet._onSearchTextChanged(...args)
        );
        // CaramOS: an input method changes its preedit""", display)
        self.assertLess(display.index("'cursor-changed'"), display.index("'key-press-event'"))

    def test_twice_changes_nothing_more(self) -> None:
        migration.run(MigrationContext())
        first = self.read(self.current, "applet.js"), self.read(self.current, "display.js")
        migration.run(MigrationContext())
        self.assertEqual(first, (self.read(self.current, "applet.js"), self.read(self.current, "display.js")))

    def test_another_cinnamenu_stays_as_it_is(self) -> None:
        (self.current / "display.js").write_text(DISPLAY.replace("'text-changed'", "'changed'"), encoding="utf-8")
        migration.run(MigrationContext())
        self.assertEqual(APPLET, self.read(self.current, "applet.js"))

    def test_dry_run(self) -> None:
        migration.run(MigrationContext(dry_run=True))
        self.assertEqual(APPLET, self.read(self.current, "applet.js"))
        self.assertEqual(DISPLAY, self.read(self.current, "display.js"))

    def test_running_sessions_reload_the_menu(self) -> None:
        user = SimpleNamespace(pw_name="minh", pw_uid=1000, pw_gid=1000, pw_dir="/home/minh")
        session = {"DISPLAY": ":0", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}
        with mock.patch.object(migration, "SYSTEMD_RUNTIME", self.root), \
                mock.patch.object(start_fcitx, "_desktop_users", return_value=[user]), \
                mock.patch.object(start_fcitx, "session_environment", return_value=session), \
                mock.patch.object(migration.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            migration.run(MigrationContext())
        command = run.call_args.args[0]
        self.assertEqual(["runuser", "-u", "minh", "--", "env", "-i"], command[:6])
        self.assertEqual(["org.Cinnamon.ReloadXlet", "Cinnamenu@json", "APPLET"], command[-3:])

    def test_without_cinnamenu_nothing_happens(self) -> None:
        with mock.patch.object(migration, "CINNAMENU", self.root.parent / "missing"):
            migration.run(MigrationContext())


if __name__ == "__main__":
    unittest.main()

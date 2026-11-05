"""Migration 20261105120200_start_menu_file_search_without_freeze: the Start Menu's home folder search no longer
waits for the disk or the network on Cinnamon's main loop, and stays out of drives mounted in the home folder.
A user reported the menu freezing; on a slow disk the search stalled Cinnamon for 11 seconds."""

from __future__ import annotations

import importlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from caramos_ota_update.context import MigrationContext

migration = importlib.import_module(
    "caramos_ota_update.migrations.20261105120200_start_menu_file_search_without_freeze.migration")
composing = importlib.import_module("caramos_ota_update.migrations.20261105120100_search_menu_while_composing.migration")
start_fcitx = importlib.import_module("caramos_ota_update.migrations.20261022120000_start_fcitx_at_login.migration")

# The lines of the home folder search the change goes into, as Cinnamenu 5.4.14 has them (the CaramOS 1.3.0
# to 1.3.3 ISOs): every file's icon and content type, read with the blocking next_file().
OLD_APPLET = """const Gio = imports.gi.Gio;
const GLib = imports.gi.GLib;

class CinnamenuApplet {
    _doSearch(pattern) {
        //----home folder search--------
        Meta.later_add(Meta.LaterType.IDLE, () => {
            const foldersToDo = [];
            foldersToDo.push(this.settings.searchStartFolder);//start search in (default value) home directory
            let currentFolderIndex = 0;
            const searchNextDir = (thisSearchId) => {
                dir.enumerate_children_async(
                            'standard::name,standard::type,standard::icon,standard::content-type,' +
                            'standard::is-hidden,standard::is-symlink',
                            Gio.FileQueryInfoFlags.NONE, GLib.PRIORITY_DEFAULT, null, (source, result) => {
                    let next = enumerator.next_file(null);
                    while (next && Date.now() < searchTimeLimit) {
                        const foundFile = {
                                        gicon: next.get_icon(),
                                        uri: file.get_uri(),
                                        mimeType: next.get_content_type(),
                                        description: filePath };
                        if (isDirectory && !next.get_is_symlink() &&
                                                            foldersToDo.length < MAX_FOLDERS_TODO) {
                            foldersToDo.push(filePath);
                        }
                        next = enumerator.next_file(null);
                    }
                });//end of enumerate_children_async
            };
        });

        ///----search providers--------
        Meta.later_add(Meta.LaterType.IDLE, () => {
            const info = dir.enumerate_children(
                'standard::name,standard::type,standard::icon,standard::content-type,standard::is-hidden',
                Gio.FileQueryInfoFlags.NONE, null);
        });
    }
}
"""
# Cinnamenu 5.7 (ISOs built after 2026-10-30): the folders are read in the background, each match's icon and
# content type with a blocking query_info().
NEW_APPLET = """const Gio = imports.gi.Gio;

class CinnamenuApplet {
    _doSearch(pattern) {
        //----home folder search--------
        Meta.later_add(Meta.LaterType.IDLE, () => {
            const foldersToDo = [];
            foldersToDo.push(this.settings.searchStartFolder); // Start search in (default value) home directory
            const searchNextDir = (thisSearchId) => {
                dir.enumerate_children_async('standard::name,standard::type,standard::is-symlink',
                            Gio.FileQueryInfoFlags.NONE, GLib.PRIORITY_DEFAULT, null, (source, result) => {
                    fileInfos.forEach((fileInfo) => {
                        if (matchScore > 1) {
                            const file = Gio.file_new_for_path(filePath);
                            const extraFileInfo = file.query_info('standard::icon,standard::content-type',
                                                                Gio.FileQueryInfoFlags.NONE, null);
                            const foundFile = {
                                gicon: extraFileInfo.get_icon(),
                                mimeType: extraFileInfo.get_content_type(),
                            };
                        }
                        if (isDirectory && (!fileInfo.get_is_symlink() || FOLLOW_SYMLINKS) &&
                                                    foldersSearched < MAX_FOLDERS_TO_SEARCH) {
                            foldersToDo.push(filePath);
                        }
                    });
                }); // end of enumerate_children_async
            };
        });

        ///----search providers--------
    }
}
"""


def search_block(applet: str) -> str:
    return applet[applet.index(migration.BLOCK_START):applet.index(migration.BLOCK_END)]


class PatchTests(unittest.TestCase):
    def test_the_search_of_the_1_3_x_isos_reads_no_file_and_stays_on_its_disk(self) -> None:
        result = migration.patched(OLD_APPLET)
        block = search_block(result)
        self.assertIn("'standard::name,standard::type,standard::fast-content-type,unix::device,'", block)
        self.assertNotIn("standard::icon", block)
        self.assertIn("gicon: Gio.content_type_get_icon(caramosType(next)),", block)
        self.assertIn("mimeType: caramosType(next),", block)
        self.assertIn("if (isDirectory && !next.get_is_symlink() && caramosOnStartDevice(next) &&", block)
        # The helpers come after the start folder, where `this` is the applet.
        self.assertLess(block.index("foldersToDo.push(this.settings.searchStartFolder)"),
                        block.index("const caramosDevice"))
        # The folder view after the search keeps its own query.
        self.assertIn("'standard::name,standard::type,standard::icon,standard::content-type,standard::is-hidden'",
                      result[result.index(migration.BLOCK_END):])

    def test_the_search_of_cinnamenu_5_7_too(self) -> None:
        block = search_block(migration.patched(NEW_APPLET))
        self.assertNotIn("query_info('standard::icon", block)
        self.assertIn("'standard::name,standard::type,standard::is-symlink,standard::fast-content-type,unix::device'",
                      block)
        self.assertIn("get_icon: () => Gio.content_type_get_icon(caramosType(fileInfo))", block)
        self.assertIn("caramosOnStartDevice(fileInfo) &&", block)

    def test_another_cinnamenu_stays_as_it_is(self) -> None:
        self.assertIsNone(migration.patched(OLD_APPLET.replace("gicon: next.get_icon(),", "gicon: icon,")))
        self.assertIsNone(migration.patched(NEW_APPLET.replace(migration.BLOCK_END, "// providers")))
        self.assertIsNone(migration.patched("const x = 1;\n"))


class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "Cinnamenu@json"
        for version, applet in (("5.8", NEW_APPLET), ("4.0", OLD_APPLET), ("3.2", "const x = 1;\n")):
            (self.root / version).mkdir(parents=True)
            (self.root / version / "applet.js").write_text(applet, encoding="utf-8")
        for name, value in (("CINNAMENU", self.root), ("SYSTEMD_RUNTIME", Path(folder.name) / "no-systemd")):
            patcher = mock.patch.object(migration, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def read(self, version: str) -> str:
        return (self.root / version / "applet.js").read_text(encoding="utf-8")

    def test_each_known_version_is_patched_once(self) -> None:
        migration.run(MigrationContext())
        first = self.read("5.8"), self.read("4.0")
        self.assertIn(migration.MARKER, first[0])
        self.assertIn(migration.MARKER, first[1])
        self.assertEqual("const x = 1;\n", self.read("3.2"))
        migration.run(MigrationContext())
        self.assertEqual(first, (self.read("5.8"), self.read("4.0")))

    def test_dry_run(self) -> None:
        migration.run(MigrationContext(dry_run=True))
        self.assertEqual(NEW_APPLET, self.read("5.8"))

    def test_running_sessions_reload_the_menu(self) -> None:
        user = SimpleNamespace(pw_name="minh", pw_uid=1000, pw_gid=1000, pw_dir="/home/minh")
        session = {"DISPLAY": ":0", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}
        with mock.patch.object(migration, "SYSTEMD_RUNTIME", self.root), \
                mock.patch.object(start_fcitx, "_desktop_users", return_value=[user]), \
                mock.patch.object(start_fcitx, "session_environment", return_value=session), \
                mock.patch.object(composing.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run:
            migration.run(MigrationContext())
        self.assertEqual(["org.Cinnamon.ReloadXlet", "Cinnamenu@json", "APPLET"], run.call_args.args[0][-3:])

    def test_without_cinnamenu_nothing_happens(self) -> None:
        with mock.patch.object(migration, "CINNAMENU", self.root.parent / "missing"):
            migration.run(MigrationContext())


if __name__ == "__main__":
    unittest.main()

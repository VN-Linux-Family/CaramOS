"""Migration 20261124180000_tray_icons_keep_their_place: the icons of Cinnamon's system tray keep a fixed order,
so they no longer swap places when Dark mode is turned on or off (a follow-up to ticket H-1211)."""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update import cinnamon_patches
from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).parents[1]
migration = importlib.import_module("caramos_ota_update.migrations.20261124180000_tray_icons_keep_their_place.migration")

# The part of Cinnamon 6.6.4's systray@cinnamon.org/applet.js that the block goes into, as CaramOS 1.5.0 has it
# (with the full-height hover of migration 20260803120000).
SYSTRAY_JS = """const Clutter = imports.gi.Clutter;
const St = imports.gi.St;
const GLib = imports.gi.GLib;
const Main = imports.ui.main;

class CinnamonSystrayApplet {
    _onTrayIconAdded(o, icon, role) {
        try {
            let hiddenIcons = Main.systrayManager.getRoles();

            if (hiddenIcons.indexOf(role.toLowerCase()) != -1 ) {
                // We've got an applet for that
                global.log("Hiding systray: " + role);
                return;
            }

            global.log("Adding systray: " + role + " (" + icon.get_width() + "x" + icon.get_height() + "px)");

            let button = new St.Bin(
            {
                style_class: "applet-box",
                child: icon
            })

            icon.set_x_align(Clutter.ActorAlign.CENTER);
            icon.set_y_align(Clutter.ActorAlign.CENTER);
            // CaramOS right-dock tray hover 20260803120000
            button.set_y_align(Clutter.ActorAlign.FILL);

            icon.visible = false;
            icon.opacity = 0;
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, 1000, () => {
                return GLib.SOURCE_REMOVE;
            });

            this.button_box.insert_child_at_index(button, 0);
        } catch (e) {
            global.logError(e);
        }
    }
}
"""

# Runs the patched applet in node with stand-ins for St, Clutter, GLib, Main and the tray's box: a login where the
# programs make their icons in any order (one of them has an applet of its own and stays hidden), then a theme change
# where Update Manager, System Information and Flameshot make theirs again. Prints the order after each.
NODE_HARNESS = """
const Clutter = { ActorAlign: { CENTER: 0, FILL: 1 } };
class Bin { constructor(props) { Object.assign(this, props); } set_y_align() {} }
const St = { Bin };
const GLib = { PRIORITY_DEFAULT: 0, SOURCE_REMOVE: false, timeout_add() { return 1; } };
const Main = { systrayManager: { getRoles: () => ["nm-applet"] } };
const global = { log() {}, logError(error) { throw error; } };
%s
class Box {
    constructor() { this.children = []; }
    get_children() { return this.children.slice(); }
    insert_child_at_index(child, index) { this.children.splice(index, 0, child); }
    remove(role) { this.children = this.children.filter((child) => child._caramosRole !== role); }
}
const icon = () => ({ set_x_align() {}, set_y_align() {}, get_width: () => 16, get_height: () => 16 });
const applet = new CinnamonSystrayApplet();
applet.button_box = new Box();
const add = (role) => applet._onTrayIconAdded(null, icon(), role);
const order = () => applet.button_box.children.map((child) => child._caramosRole);
const seen = [];
for (const role of ["flameshot", "fcitx", "mintupdate.py", "Telegram", "tray.py", "nm-applet", "copyq", "zalo"])
    add(role);
seen.push(order());
for (const role of ["mintupdate.py", "tray.py", "flameshot"]) applet.button_box.remove(role);
for (const role of ["flameshot", "tray.py", "mintupdate.py"]) add(role);
seen.push(order());
console.log(JSON.stringify(seen));
"""


class PatchTests(unittest.TestCase):
    def test_the_block_replaces_the_line_that_put_icons_first(self) -> None:
        new = migration.patched(SYSTRAY_JS)
        self.assertEqual(1, new.count(migration.START))
        self.assertNotIn(migration.ANCHOR, new)
        self.assertEqual(SYSTRAY_JS, new.replace(migration.BLOCK, migration.ANCHOR))
        self.assertEqual(new, migration.patched(new))

    def test_lines_stay_readable(self) -> None:
        for line in migration.BLOCK.splitlines():
            self.assertLessEqual(len(line), 120, line)

    def test_other_cinnamon_code_stays(self) -> None:
        changed = SYSTRAY_JS.replace(migration.ANCHOR, "            this.button_box.add_child(button);\n")
        self.assertEqual("", migration.patched(changed))
        twice = SYSTRAY_JS + migration.ANCHOR
        self.assertEqual("", migration.patched(twice))
        half = migration.patched(SYSTRAY_JS).replace(migration.END, "", 1)
        self.assertEqual("", migration.patched(half))

    def test_valid_javascript(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        subprocess.run([node, "--check", "-"], input=migration.patched(SYSTRAY_JS), text=True, check=True,
                       capture_output=True)

    def test_icons_keep_a_fixed_order(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        source = migration.patched(SYSTRAY_JS).split("\n", 5)[5]  # without the imports
        result = subprocess.run([node, "-"], input=NODE_HARNESS % source, text=True, check=True,
                                capture_output=True)
        # Other programs first, by name, then the CaramOS ones as a login shows them; the same after a theme change.
        expected = ["telegram", "zalo", "tray.py", "mintupdate.py", "copyq", "fcitx", "flameshot"]
        self.assertEqual([expected, expected], json.loads(result.stdout))


class RestoreTests(unittest.TestCase):
    def systray(self, text: str = SYSTRAY_JS) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "applet.js"
        path.write_text(text, encoding="utf-8")
        path.chmod(0o644)
        return path

    def test_restore(self) -> None:
        path = self.systray()
        with mock.patch.object(MigrationContext, "log"):
            migration.restore(MigrationContext(), path)
            migration.restore(MigrationContext(), path)
        self.assertEqual(migration.patched(SYSTRAY_JS), path.read_text(encoding="utf-8"))
        self.assertEqual(0o644, path.stat().st_mode & 0o777)

    def test_dry_run(self) -> None:
        path = self.systray()
        with mock.patch.object(MigrationContext, "log"):
            migration.restore(MigrationContext(dry_run=True), path)
        self.assertEqual(SYSTRAY_JS, path.read_text(encoding="utf-8"))

    def test_a_file_it_does_not_know_stays(self) -> None:
        path = self.systray("// another Cinnamon\n")
        logged: list[str] = []
        with mock.patch.object(MigrationContext, "log", side_effect=logged.append):
            migration.restore(MigrationContext(), path)
        self.assertEqual("// another Cinnamon\n", path.read_text(encoding="utf-8"))
        self.assertTrue(logged[0].startswith("warning:"), logged)

    def test_without_cinnamon(self) -> None:
        logged: list[str] = []
        with mock.patch.object(MigrationContext, "log", side_effect=logged.append):
            migration.restore(MigrationContext(), Path("/nonexistent/applets/systray@cinnamon.org/applet.js"))
        self.assertIn("nothing to change", logged[0])

    def test_after_a_cinnamon_update(self) -> None:
        with mock.patch.object(migration, "restore") as restore:
            cinnamon_patches.restore(MigrationContext(), {migration_id()})
            restore.assert_called_once()
            restore.reset_mock()
            cinnamon_patches.restore(MigrationContext(), set())
            restore.assert_not_called()
        self.assertEqual(migration_id(), cinnamon_patches.TRAY_ORDER_MIGRATION)
        triggers = (ROOT / "debian/triggers").read_text(encoding="utf-8")
        self.assertIn(f"interest-noawait {migration.SYSTRAY_JS.parent}\n", triggers)

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(["cinnamon"], manifest["desktops"])
        self.assertEqual("anytime", manifest["unattended"])  # nothing on the screen changes before the next login
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertIn("đăng nhập sau", manifest["release_notes_vi"][-1])


def migration_id() -> str:
    return Path(migration.__file__).parent.name


if __name__ == "__main__":
    unittest.main()

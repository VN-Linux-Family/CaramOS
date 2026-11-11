"""Migration 20261111090000_start_menu_ctrl_scroll_icon_size: Ctrl + mouse wheel over the apps of the Start Menu
makes their icons bigger or smaller, as on Windows (asked for by the owner on 2026-11-10)."""

from __future__ import annotations

import importlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from caramos_ota_update.context import MigrationContext

migration = importlib.import_module(
    "caramos_ota_update.migrations.20261111090000_start_menu_ctrl_scroll_icon_size.migration")
composing = importlib.import_module("caramos_ota_update.migrations.20261105120100_search_menu_while_composing.migration")
start_fcitx = importlib.import_module("caramos_ota_update.migrations.20261022120000_start_fcitx_at_login.migration")

# The apps view of Cinnamenu 5.7 (ISOs built after 2026-10-30), cut down to the lines the change uses.
NEW_APPSVIEW = """const GLib = imports.gi.GLib;
const Clutter = imports.gi.Clutter;
const St = imports.gi.St;
const ApplicationsViewMode = Object.freeze({LIST: 0, GRID: 1});

class AppButton {
    constructor(applet, app) {
        if (app.emoji) {
            this.icon = new St.Label({ style: 'color: white; font-size: ' +
                                            (Math.round(this.applet.getAppIconSize() * 0.85)) + 'px;'});
        }
    }

    destroy() {
        this.signals.disconnectAllSignals();
    }
}

class AppsView {
    constructor(applet) {
        this.applet = applet;
        this.buttonStore = [];
        this.appsViewSignals = new SignalManager(null);
        this.applicationsScrollBox = new St.ScrollView({ style_class: 'vfade menu-applications-scrollbox' });
        this.applicationsScrollBox.set_mouse_scrolling(true);
        this.appsViewSignals.connect(this.applicationsScrollBox, 'button-release-event', () => {});
    }

    resizeGrid() {
        this.currentGridViewColumnCount = this.getGridValues().columns;
    }

    populate_init() {
        this.clearAppsView();
        this.applicationsScrollBox.vscroll.adjustment.set_value(0);//scroll to top
    }

    getGridValues() {
        const gridBoxUsableWidth = this.applet.display.currentGridBoxUsableWidth;
        const minColumnWidth = Math.max(140, this.applet.settings.appsGridIconSize * 1.2);
        const columns = Math.floor(gridBoxUsableWidth / (minColumnWidth * global.ui_scale));
        return {columnWidth: Math.floor(gridBoxUsableWidth / columns), columns: columns};
    }

    clearAppsView() {
        this.getActiveContainer().remove_all_children();
    }

    destroy() {
        this.appsViewSignals.disconnectAllSignals();
        this.applicationsScrollBox.destroy();
    }
}
"""
# Cinnamenu 5.4.14 (the CaramOS 1.0.x to 1.3.3 ISOs): the same view through `this.appThis`, cleared by clearApps(),
# and without GLib or Meta imported.
OLD_APPSVIEW = (NEW_APPSVIEW.replace("const GLib = imports.gi.GLib;\n", "")
                .replace("constructor(applet) {\n        this.applet = applet;",
                         "constructor(appThis) {\n        this.appThis = appThis;")
                .replace("clearAppsView()", "clearApps()")
                .replace("this.applet.display.currentGridBoxUsableWidth", "this.currentGridBoxWidth")
                .replace("this.applet.settings.appsGridIconSize", "this.appThis.settings.appsGridIconSize")
                .replace("this.applet.getAppIconSize()", "this.appThis.getAppIconSize()"))
APPLET = """class CinnamenuApplet {
    constructor() {
        this.currentCategory = 'all';
        [
        { key: 'applications-view-mode',    value: 'applicationsViewMode',  cb: refreshDisplay },
        { key: 'apps-list-icon-size',       value: 'appsListIconSize',      cb: refreshDisplay },
        { key: 'apps-grid-icon-size',       value: 'appsGridIconSize',      cb: refreshDisplay },
        ].forEach(setting => this.appletSettings.bind(setting.key, setting.value, setting.cb));
    }

    setActiveCategory(categoryId) {
        this.currentCategory = categoryId;
    }

    _onSearchTextChanged() {
        this.searchActive = true;
    }

    _endSearchMode() {
        this.searchActive = false;
        this.previousSearchPattern = '';
    }
}
"""


def added(result: str) -> str:
    """The methods the change puts before getGridValues()."""
    return result[result.index("\n    // CaramOS: Ctrl + mouse wheel") + 1:result.index(migration.GRID_VALUES)]


class PatchTests(unittest.TestCase):
    def test_cinnamenu_5_7_resizes_through_this_applet(self) -> None:
        result = migration.patched(NEW_APPSVIEW, APPLET)
        methods = added(result)
        self.assertIn("this.applet.settings[isList ? 'appsListIconSize' : 'appsGridIconSize'] = size;", methods)
        self.assertIn("this.clearAppsView();", methods)
        self.assertIn("this.applet.setActiveCategory(this.applet.currentCategory);", methods)
        self.assertNotIn("appThis", result)

    def test_cinnamenu_5_4_14_through_this_appthis(self) -> None:
        result = migration.patched(OLD_APPSVIEW, APPLET)
        methods = added(result)
        self.assertIn("this.appThis.settings[isList ? 'appsListIconSize' : 'appsGridIconSize'] = size;", methods)
        self.assertIn("this.clearApps();", methods)
        self.assertIn("this.appThis._onSearchTextChanged();", methods)
        self.assertNotIn("this.applet.", result)
        # GLib and Meta are not imported there, so the change reaches them through imports.gi.
        self.assertIn("imports.gi.Meta.later_add(imports.gi.Meta.LaterType.BEFORE_REDRAW,", methods)
        self.assertIn("imports.gi.Meta.later_add(imports.gi.Meta.LaterType.IDLE,", methods)

    def test_the_wheel_is_caught_over_the_apps_and_released_with_the_view(self) -> None:
        result = migration.patched(NEW_APPSVIEW, APPLET)
        connect = result.index("this.appsViewSignals.connect(this.applicationsScrollBox, 'scroll-event',")
        self.assertLess(result.index(migration.SCROLL_BOX), connect)
        self.assertLess(connect, result.index("'button-release-event'"))
        destroy = result[result.index(migration.DESTROY):]
        self.assertLess(destroy.index("imports.gi.Meta.later_remove(this._caramosResizeLater);"),
                        destroy.index("this.applicationsScrollBox.destroy();"))
        # AppButton's own destroy() is left alone.
        self.assertIn("    destroy() {\n        this.signals.disconnectAllSignals();\n    }\n", result)

    def test_notches_come_from_up_and_down_events_only(self) -> None:
        methods = added(migration.patched(NEW_APPSVIEW, APPLET))
        self.assertIn("} else if (direction === Clutter.ScrollDirection.SMOOTH) {\n            return Clutter.EVENT_STOP;",
                      methods)
        self.assertNotIn("get_scroll_delta", methods)
        self.assertIn("if ((event.get_state() & Clutter.ModifierType.CONTROL_MASK) === 0) {\n"
                      "            return Clutter.EVENT_PROPAGATE;", methods)
        # About 10 % a notch, so the icons grow and shrink gradually.
        self.assertIn("const sizes = isList ? [16, 20, 24, 28, 32, 40, 48, 56, 64]\n"
                      "                             : [24, 28, 32, 36, 40, 44, 48, 54, 60, 64, 72, 80, 88, 96, 108, 120, 128];",
                      methods)

    def test_every_notch_resizes_the_icons_in_place_once_a_frame(self) -> None:
        methods = added(migration.patched(NEW_APPSVIEW, APPLET))
        handler = methods[methods.index("_caramosCtrlScroll(event) {"):methods.index("_caramosResizeIcons(size, isList) {")]
        # No waiting for the wheel to rest, no buttons created again for a notch.
        self.assertIn("if (!this._caramosResizeLater) {", handler)
        self.assertIn("this._caramosResizeIcons(size, isList);", handler)
        self.assertNotIn("timeout_add", methods)
        self.assertNotIn("_caramosRecreateButtons", handler)
        resize = methods[methods.index("_caramosResizeIcons(size, isList) {"):methods.index("_caramosRecreateButtons() {")]
        self.assertIn("if (icon instanceof St.Icon) {\n                icon.set_icon_size(size);", resize)
        self.assertIn("icon.set_style('color: white; font-size: ' + Math.round(size * 0.85) + 'px;');", resize)
        self.assertIn("if (!isList) {\n            this.resizeGrid();", resize)
        # Only an icon of another kind makes the buttons be created again.
        self.assertIn("if (other) {\n            this._caramosRecreateButtons();", resize)

    def test_the_columns_follow_the_icon_size(self) -> None:
        for appsview, app in ((NEW_APPSVIEW, "applet"), (OLD_APPSVIEW, "appThis")):
            result = migration.patched(appsview, APPLET)
            self.assertNotIn("Math.max(140,", result)
            self.assertIn("const minColumnWidth = Math.round(140 * (Math.max(24, "
                          f"this.{app}.settings.appsGridIconSize) + 32) / 96);", result)

    def test_the_default_size_keeps_cinnamenus_columns(self) -> None:
        # The formula in the patch: the default 64 px keeps the 140 px columns of Cinnamenu.
        sizes = (24, 28, 32, 36, 40, 44, 48, 54, 60, 64, 72, 80, 88, 96, 108, 120, 128)
        width = {size: round(140 * (max(24, size) + 32) / 96) for size in (16,) + sizes}
        self.assertEqual((82, 82, 140, 233), (width[16], width[24], width[64], width[128]))
        # The grid of the CaramOS 1.3.7 menu is 593 px wide (measured in the VM): from 7 apps in a row at 24 px
        # down to 2 at 128 px, with 4 at the default 64 px as before.
        self.assertEqual([7, 6, 6, 5, 5, 5, 5, 4, 4, 4, 3, 3, 3, 3, 2, 2, 2], [593 // width[size] for size in sizes])

    def test_the_menu_is_not_rebuilt(self) -> None:
        # The settings callback, refreshDisplay(), rebuilds the whole menu and closes it.
        self.assertNotIn("refreshDisplay", migration.patched(NEW_APPSVIEW, APPLET))

    def test_another_cinnamenu_stays_as_it_is(self) -> None:
        self.assertIsNone(migration.patched(NEW_APPSVIEW.replace(migration.SCROLL_BOX, ""), APPLET))
        self.assertIsNone(migration.patched(NEW_APPSVIEW.replace("clearAppsView()", "clearView()"), APPLET))
        self.assertIsNone(migration.patched(OLD_APPSVIEW.replace("const Clutter = imports.gi.Clutter;\n", ""), APPLET))
        self.assertIsNone(migration.patched(NEW_APPSVIEW + OLD_APPSVIEW, APPLET))
        self.assertIsNone(migration.patched(NEW_APPSVIEW, APPLET.replace("setActiveCategory(categoryId)", "show(id)")))
        self.assertIsNone(migration.patched(NEW_APPSVIEW, APPLET.replace("'apps-grid-icon-size'", "'grid-size'")))
        self.assertIsNone(migration.patched(NEW_APPSVIEW.replace("Math.max(140, ", "Math.max(160, "), APPLET))
        self.assertIsNone(migration.patched("const x = 1;\n", APPLET))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_both_forms_are_valid_javascript(self) -> None:
        for appsview in (NEW_APPSVIEW, OLD_APPSVIEW):
            with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as handle:
                handle.write(migration.patched(appsview, APPLET))
                handle.flush()
                checked = subprocess.run(["node", "--check", handle.name], capture_output=True, text=True,
                                         check=False)
            self.assertEqual(0, checked.returncode, checked.stderr)


class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "Cinnamenu@json"
        for version, appsview in (("5.8", NEW_APPSVIEW), ("4.0", OLD_APPSVIEW), ("3.2", "const x = 1;\n")):
            (self.root / version).mkdir(parents=True)
            (self.root / version / "appsview.js").write_text(appsview, encoding="utf-8")
            (self.root / version / "applet.js").write_text(APPLET, encoding="utf-8")
        for name, value in (("CINNAMENU", self.root), ("SYSTEMD_RUNTIME", Path(folder.name) / "no-systemd")):
            patcher = mock.patch.object(migration, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def read(self, version: str) -> str:
        return (self.root / version / "appsview.js").read_text(encoding="utf-8")

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
        self.assertEqual(NEW_APPSVIEW, self.read("5.8"))

    def test_running_sessions_reload_the_menu(self) -> None:
        user = SimpleNamespace(pw_name="minh", pw_uid=1000, pw_gid=1000, pw_dir="/home/minh")
        session = {"DISPLAY": ":0", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}
        with mock.patch.object(migration, "SYSTEMD_RUNTIME", self.root), \
                mock.patch.object(start_fcitx, "_desktop_users", return_value=[user]), \
                mock.patch.object(start_fcitx, "session_environment", return_value=session), \
                mock.patch.object(composing.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run, \
                mock.patch.object(composing.time, "sleep"):
            migration.run(MigrationContext())
        self.assertEqual(["org.Cinnamon.ReloadXlet", "Cinnamenu@json", "APPLET"], run.call_args.args[0][-3:])

    def test_nothing_to_patch_reloads_nothing(self) -> None:
        migration.run(MigrationContext())
        with mock.patch.object(migration, "SYSTEMD_RUNTIME", self.root), \
                mock.patch.object(composing, "_reload_in_sessions") as reload:
            migration.run(MigrationContext())
        reload.assert_not_called()

    def test_without_cinnamenu_nothing_happens(self) -> None:
        with mock.patch.object(migration, "CINNAMENU", self.root.parent / "missing"):
            migration.run(MigrationContext())


if __name__ == "__main__":
    unittest.main()

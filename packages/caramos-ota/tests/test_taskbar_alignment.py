"""The taskbar's middle island in the middle of the screen or next to the menu (ticket H-1181): the Cinnamon applet's
Taskbar tile, the Xfce Control Center's, and migration 20261120100100, which paints Cinnamon's island on the window
list."""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).parents[1]
APPLET_JS = ROOT / "usr/share/caramos-ota/applets/caramos-control-center@caramos/applet.js"
XFCE_CC = ROOT / "usr/share/caramos-ota/xfce/control-center"
DARK_THEME_CSS = ROOT / "usr/share/themes/Cinnamon-Delight-Dark/cinnamon/cinnamon.css"

migration = importlib.import_module("caramos_ota_update.migrations.20261120100100_taskbar_alignment.migration")
three_docks = importlib.import_module("caramos_ota_update.migrations.20260803120000_apply_three_dock_taskbar.migration")

sys.path.insert(0, str(XFCE_CC))
# The Xfce Control Center imports PyGObject, which Launchpad's builders do not have.
HAVE_GI = importlib.util.find_spec("gi") is not None
taskbar = importlib.import_module("caramos_xfce_cc.backends.taskbar") if HAVE_GI else None

# Cinnamon's enabled-applets on CaramOS 1.4.0.
CARAMOS_APPLETS = [
    "panel1:left:0:Cinnamenu@json:0",
    "panel1:center:0:grouped-window-list@cinnamon.org:1",
    "panel1:right:0:systray@cinnamon.org:2",
    "panel1:right:3:notifications@cinnamon.org:5",
    "panel1:right:5:calendar@cinnamon.org:7",
    "panel1:right:6:caramos-control-center@caramos:0",
    "panel1:right:7:caramos-help@caramos:8",
]


def extract_function(source: str, name: str) -> str:
    match = re.search(rf"^function {name}\(.*?^\}}\n", source, re.S | re.M)
    if not match:
        raise AssertionError(f"function {name} not found in applet.js")
    return match.group(0)


class CinnamonAppletLogicTests(unittest.TestCase):
    """The applet's pure functions under node."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        source = APPLET_JS.read_text(encoding="utf-8")
        constants = [re.search(rf"^const {name} = .*?;\n", source, re.S | re.M).group(0)
                     for name in ("TASKBAR_APPLET", "TASKBAR_ALIGNMENTS")]
        cls.program = "".join(constants) + "".join(extract_function(source, name)
                                                   for name in ("taskbarAlignment", "withTaskbarAlignment"))

    def js(self, expression: str) -> object:
        if not self.node:
            self.skipTest("node is unavailable")
        script = self.program + f"process.stdout.write(JSON.stringify({expression}));\n"
        return json.loads(subprocess.run([self.node, "-e", script], check=True, capture_output=True,
                                         text=True).stdout)

    def test_where_the_window_list_is(self) -> None:
        self.assertEqual("center", self.js(f"taskbarAlignment({json.dumps(CARAMOS_APPLETS)})"))
        left = [entry.replace("panel1:center:0:grouped", "panel1:left:1:grouped") for entry in CARAMOS_APPLETS]
        self.assertEqual("left", self.js(f"taskbarAlignment({json.dumps(left)})"))
        right = [entry.replace("panel1:center:0:grouped", "panel1:right:9:grouped") for entry in CARAMOS_APPLETS]
        self.assertIsNone(self.js(f"taskbarAlignment({json.dumps(right)})"))
        without = [entry for entry in CARAMOS_APPLETS if "grouped-window-list" not in entry]
        self.assertIsNone(self.js(f"taskbarAlignment({json.dumps(without)})"))
        other_panel = [entry.replace("panel1:center", "panel2:center") for entry in CARAMOS_APPLETS]
        self.assertIsNone(self.js(f"taskbarAlignment({json.dumps(other_panel)})"))

    def test_left_after_the_menu_and_back(self) -> None:
        left = self.js(f"withTaskbarAlignment({json.dumps(CARAMOS_APPLETS)}, 'left')")
        self.assertEqual("panel1:left:1:grouped-window-list@cinnamon.org:1", left[1])
        self.assertEqual(CARAMOS_APPLETS[:1] + CARAMOS_APPLETS[2:], left[:1] + left[2:], "the others stay as they are")
        self.assertEqual(CARAMOS_APPLETS, self.js(f"withTaskbarAlignment({json.dumps(left)}, 'center')"))

    def test_after_every_applet_of_the_left_zone(self) -> None:
        applets = CARAMOS_APPLETS + ["panel1:left:4:show-desktop@cinnamon.org:9"]
        left = self.js(f"withTaskbarAlignment({json.dumps(applets)}, 'left')")
        self.assertIn("panel1:left:5:grouped-window-list@cinnamon.org:1", left)

    def test_nothing_to_move(self) -> None:
        self.assertEqual(CARAMOS_APPLETS, self.js(f"withTaskbarAlignment({json.dumps(CARAMOS_APPLETS)}, 'center')"))
        self.assertIsNone(self.js(f"withTaskbarAlignment({json.dumps(CARAMOS_APPLETS)}, 'right')"))
        without = [entry for entry in CARAMOS_APPLETS if "grouped-window-list" not in entry]
        self.assertIsNone(self.js(f"withTaskbarAlignment({json.dumps(without)}, 'left')"))


class CinnamonAppletContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APPLET_JS.read_text(encoding="utf-8")

    def method(self, name: str) -> str:
        match = re.search(rf"\n    {name}\([^)]*\) \{{([\s\S]*?)\n    \}}\n", self.source)
        self.assertIsNotNone(match, name)
        return match.group(1)

    def test_the_tile_is_next_to_do_not_disturb(self) -> None:
        self.assertIn("this._notificationsRow.add_child(this._dndTile.actor);\n"
                      "        this._notificationsRow.add_child(this._taskbarTile.actor);", self.source)

    def test_the_theme_loads_again_once_through_the_theme_manager(self) -> None:
        body = self.method("_setTaskbarAlignment")
        # Main.loadTheme() alone leaves the applets' stylesheets out: Cinnamon adds them back on 'theme-set'.
        self.assertIn("Main.themeManager._changeTheme();", body)
        self.assertNotIn("Main.loadTheme", body)
        self.assertIn("if (this._taskbarThemeReloaded) return;", body)

    def test_the_tile_follows_the_panel(self) -> None:
        self.assertIn("global.settings.connect('changed::enabled-applets', () => this._refreshTaskbarTile())", self.source)
        self.assertIn("global.settings.disconnect(this._taskbarSignalId)", self.source)


@unittest.skipUnless(HAVE_GI, "PyGObject is unavailable")
class XfcePlanTests(unittest.TestCase):
    NAMES = {1: "whiskermenu", 2: "docklike", 3: "systray", 4: "clock", 7: "caramos-control-center"}

    def test_caramos_panels(self) -> None:
        centre = ([1, 2, 3], {1: [1], 2: [2]})
        self.assertEqual("center", taskbar.alignment(*centre, self.NAMES))
        self.assertEqual({"/panels": [1, 3], "/panels/panel-1/plugin-ids": [1, 2]},
                         taskbar.plan(*centre, self.NAMES, "left"))
        left = ([1, 3], {1: [1, 2], 2: [2]})
        self.assertEqual("left", taskbar.alignment(*left, self.NAMES))
        self.assertEqual({"/panels": [1, 2, 3], "/panels/panel-1/plugin-ids": [1],
                          "/panels/panel-2/plugin-ids": [2]}, taskbar.plan(*left, self.NAMES, "center"))

    def test_left_when_panel_2_settings_are_gone(self) -> None:
        # xfce4-panel may drop the settings of a panel that is not in its list; Centre writes them again.
        left = ([1, 3], {1: [1, 2], 2: []})
        self.assertEqual("left", taskbar.alignment(*left, self.NAMES))
        self.assertEqual([2], taskbar.plan(*left, self.NAMES, "center")["/panels/panel-2/plugin-ids"])

    def test_nothing_to_do(self) -> None:
        self.assertEqual({}, taskbar.plan([1, 2, 3], {1: [1], 2: [2]}, self.NAMES, "center"))

    def test_panels_changed_by_the_user(self) -> None:
        for panels, ids in (([1, 2, 3], {1: [4], 2: [2]}),          # no menu in panel-1
                            ([1, 2, 3], {1: [1], 2: [3]}),          # no dock
                            ([1, 2, 3], {1: [1, 2], 2: [2]}),       # the dock twice
                            ([2, 3], {1: [1], 2: [2]})):            # no panel-1
            with self.subTest(panels=panels, ids=ids):
                self.assertIsNone(taskbar.alignment(panels, ids, self.NAMES))
                self.assertIsNone(taskbar.plan(panels, ids, self.NAMES, "left"))

    def test_the_popup_has_the_tile(self) -> None:
        popup = (XFCE_CC / "caramos_xfce_cc/popup.py").read_text(encoding="utf-8")
        self.assertIn("self.notifications_row = self._row(self.dnd, self.taskbar)", popup)
        self.assertIn("self.hide_popup()\n        self.b.taskbar.set_alignment(place)", popup)

    def test_the_panel_restarts_without_the_callers_pipes(self) -> None:
        source = (XFCE_CC / "caramos_xfce_cc/backends/taskbar.py").read_text(encoding="utf-8")
        self.assertIn('subprocess.Popen(["xfce4-panel", "--restart"], stdin=subprocess.DEVNULL, '
                      'stdout=subprocess.DEVNULL,', source)
        self.assertIn("start_new_session=True", source)


class IslandCssTests(unittest.TestCase):
    def test_the_light_block(self) -> None:
        block = migration.island_on_window_list(three_docks.DOCK_CSS)
        rules = dict(re.findall(r"\n([.#][^{}\n]+) \{\n([^{}]*)\}", block))
        self.assertIn("background-color: transparent;", rules[".panelCenter"])
        self.assertIn("box-shadow: none;", rules[".panelCenter"])
        island = rules[".grouped-window-list-box"]
        self.assertIn("background-color: rgba(247, 243, 233, 0.82);", island)
        self.assertIn("border-radius: 999px;", island)
        self.assertIn("box-shadow: inset 0 0 0 1px rgba(31, 79, 50, 0.14);", island)
        self.assertNotIn(".panelCenter .grouped-window-list", block)
        for token in three_docks.FORBIDDEN_DOCK_CSS:
            self.assertNotIn(token, block)

    def test_once(self) -> None:
        self.assertEqual("", migration.island_on_window_list(migration.island_on_window_list(three_docks.DOCK_CSS)))

    def test_the_dark_theme_has_it(self) -> None:
        css = DARK_THEME_CSS.read_text(encoding="utf-8")
        self.assertEqual("", migration.theme_with_island_on_window_list(css), "already moved onto the window list")
        block = css[css.index(migration.START):css.index(migration.END)]
        rules = dict(re.findall(r"\n([.#][^{}\n]+) \{\n([^{}]*)\}", block))
        # The same colour as the left island (build-delight-dark-theme.py tints the tool's colours for the theme).
        fill = re.search(r"background-color: ([^;]+);", rules[".panelLeft .applet-box"]).group(1)
        self.assertIn(f"background-color: {fill};", rules[".grouped-window-list-box"])
        self.assertIn("background-color: transparent;", rules[".panelCenter"])
        tool = (ROOT / "tools/delight-dark-dock.css").read_text(encoding="utf-8")
        self.assertEqual("", migration.theme_with_island_on_window_list(tool), "the generator's input too")
        self.assertIn(".grouped-window-list-box {", tool)

    def test_a_theme_without_the_block(self) -> None:
        for css in ("", "#panel {}\n", migration.START + "\n" + migration.START + "\n" + migration.END):
            with self.subTest(css=css[:30]):
                self.assertEqual("", migration.theme_with_island_on_window_list(css))


class MigrationTests(unittest.TestCase):
    def run_on(self, css: str, dry_run: bool = False) -> tuple[str, list[str]]:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cinnamon.css"
            path.write_text(css, encoding="utf-8")
            path.chmod(0o644)
            context = MigrationContext(dry_run=dry_run)
            logged: list[str] = []
            with mock.patch.object(context, "log", side_effect=logged.append):
                migration.run(context, path)
            self.assertEqual(0o644, path.stat().st_mode & 0o777)
            return path.read_text(encoding="utf-8"), logged

    def test_the_theme_of_1_4_0(self) -> None:
        theme = "/* Cinnamon-Delight */\n#panel { color: red; }\n\n" + three_docks.DOCK_CSS + "\n"
        new, _logged = self.run_on(theme)
        self.assertEqual(theme.replace(three_docks.DOCK_CSS, ""), new.replace(
            new[new.index(migration.START):new.index(migration.END) + len(migration.END)], ""))
        self.assertIn(".grouped-window-list-box {", new)
        again, logged = self.run_on(new)
        self.assertEqual(new, again)
        self.assertTrue(any("left alone" in line for line in logged), logged)

    def test_dry_run(self) -> None:
        theme = three_docks.DOCK_CSS + "\n"
        new, logged = self.run_on(theme, dry_run=True)
        self.assertEqual(theme, new)
        self.assertTrue(any("paint the middle island" in line for line in logged), logged)

    def test_no_theme(self) -> None:
        context = MigrationContext()
        with mock.patch.object(context, "log") as log:
            migration.run(context, Path("/nonexistent/cinnamon.css"))
        self.assertIn("nothing to change", log.call_args.args[0])

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("desktops", manifest)
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertIn("Thanh tác vụ", manifest["release_notes_vi"][0])


if __name__ == "__main__":
    unittest.main()

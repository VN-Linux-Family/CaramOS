"""The Xfce edition's clock and calendar with lunar dates (ticket H-1178): the Control Center's clock and calendar
(caramos_xfce_cc: lunar.py, month.py, clock.py, calendar_popup.py), and migration 20261120100400, which takes Xfce's
clock out of the panel of installed systems. The lunar dates must be those of the Cinnamon edition's calendar
(migration 20261120100200's LUNAR_JS), day for day."""

from __future__ import annotations

import datetime
import importlib
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_lunar_calendar import KNOWN_DATES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
XFCE_CC = ROOT / "usr/share/caramos-ota/xfce/control-center"
PACKAGE = XFCE_CC / "caramos_xfce_cc"
PANEL_XML = REPO / "config/includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml"

sys.path.insert(0, str(XFCE_CC))
lunar = importlib.import_module("caramos_xfce_cc.lunar")
month = importlib.import_module("caramos_xfce_cc.month")
migration = importlib.import_module("caramos_ota_update.migrations.20261120100400_xfce_lunar_clock.migration")
cinnamon = importlib.import_module("caramos_ota_update.migrations.20261120100200_lunar_calendar.migration")

# CaramOS 1.4.0's system defaults for the panels (the ISO's xfce4-panel.xml), with Xfce's clock as plugin-4.
PANEL_1_4_0 = """<?xml version="1.0" encoding="UTF-8"?>
<!-- CaramOS Xfce: the three islands of CaramOS Cinnamon, one panel each, at the bottom of the screen.
     Left: the CaramOS menu (Whisker). Middle: pinned and open apps (Docklike, its pins in panel/docklike.rc).
     Right: the tray, the clock, the Control Center (network, volume, battery; its popup has the rest) and Feedback
     & Help (the question mark), in the order of CaramOS Cinnamon.
     The island look is caramos-ota's /usr/share/caramos-ota/xfce/panel-islands.css, imported by the theme. It needs
     this layout: three clear panels (background style 1, alpha 0) 48 px high, and the plugin ids below, which the CSS
     names (tests/test_xfce_panel_islands.py checks both).
     The Control Center is caramos-ota's /usr/share/caramos-ota/xfce/caramos-control-center; the plugin that gives it
     its place here is CaramOS's xfce4-caramos-plugin (packages/xfce4-caramos-plugin). With it, the panel has no
     sound or battery plugin, and nm-applet shows no icon (its dconf default), as on Cinnamon.
     Mint's xapp-status plugin is left out: Mint's icons then show in the tray, as small as the other tray icons. -->
<channel name="xfce4-panel" version="1.0">
  <property name="configver" type="int" value="2"/>
  <property name="panels" type="array">
    <value type="int" value="1"/>
    <value type="int" value="2"/>
    <value type="int" value="3"/>
    <property name="dark-mode" type="bool" value="false"/>
    <property name="panel-1" type="empty">
      <property name="position" type="string" value="p=8;x=0;y=0"/>
      <property name="length" type="uint" value="1"/>
      <property name="length-adjust" type="bool" value="true"/>
      <property name="position-locked" type="bool" value="true"/>
      <property name="size" type="uint" value="48"/>
      <property name="icon-size" type="uint" value="32"/>
      <property name="background-style" type="uint" value="1"/>
      <property name="background-rgba" type="array">
        <value type="double" value="0.000000"/>
        <value type="double" value="0.000000"/>
        <value type="double" value="0.000000"/>
        <value type="double" value="0.000000"/>
      </property>
      <property name="plugin-ids" type="array">
        <value type="int" value="1"/>
      </property>
    </property>
    <property name="panel-2" type="empty">
      <property name="position" type="string" value="p=10;x=0;y=0"/>
      <property name="length" type="uint" value="1"/>
      <property name="length-adjust" type="bool" value="true"/>
      <property name="position-locked" type="bool" value="true"/>
      <property name="size" type="uint" value="48"/>
      <property name="icon-size" type="uint" value="32"/>
      <property name="background-style" type="uint" value="1"/>
      <property name="background-rgba" type="array">
        <value type="double" value="0.000000"/>
        <value type="double" value="0.000000"/>
        <value type="double" value="0.000000"/>
        <value type="double" value="0.000000"/>
      </property>
      <property name="plugin-ids" type="array">
        <value type="int" value="2"/>
      </property>
    </property>
    <property name="panel-3" type="empty">
      <property name="position" type="string" value="p=4;x=0;y=0"/>
      <property name="length" type="uint" value="1"/>
      <property name="length-adjust" type="bool" value="true"/>
      <property name="position-locked" type="bool" value="true"/>
      <property name="size" type="uint" value="48"/>
      <property name="icon-size" type="uint" value="16"/>
      <property name="background-style" type="uint" value="1"/>
      <property name="background-rgba" type="array">
        <value type="double" value="0.000000"/>
        <value type="double" value="0.000000"/>
        <value type="double" value="0.000000"/>
        <value type="double" value="0.000000"/>
      </property>
      <property name="plugin-ids" type="array">
        <value type="int" value="3"/>
        <value type="int" value="4"/>
        <value type="int" value="5"/>
        <value type="int" value="6"/>
      </property>
    </property>
  </property>
  <property name="plugins" type="empty">
    <property name="plugin-1" type="string" value="whiskermenu"/>
    <property name="plugin-2" type="string" value="docklike"/>
    <!-- 20 px cells: the XEmbed icons (Mint's, the network) draw 16 px icons in them, 22 px apart. -->
    <property name="plugin-3" type="string" value="systray">
      <property name="icon-size" type="int" value="20"/>
      <property name="symbolic-icons" type="bool" value="true"/>
      <property name="square-icons" type="bool" value="false"/>
      <property name="single-row" type="bool" value="true"/>
      <property name="names-visible" type="array">
        <value type="string" value="networkmanager applet"/>
      </property>
      <property name="show-frame" type="bool" value="false"/>
    </property>
    <property name="plugin-4" type="string" value="clock">
      <property name="mode" type="uint" value="2"/>
      <property name="digital-layout" type="uint" value="3"/>
      <property name="digital-time-format" type="string" value="%A %H:%M, %e %B"/>
      <property name="digital-time-font" type="string" value="Be Vietnam Pro Bold 10"/>
    </property>
    <property name="plugin-5" type="string" value="caramos-control-center"/>
    <property name="plugin-6" type="string" value="launcher">
      <property name="items" type="array">
        <value type="string" value="/usr/share/caramos-ota/xfce/caramos-help-panel.desktop"/>
      </property>
    </property>
  </property>
</channel>
"""

NAMES = {1: "whiskermenu", 2: "docklike", 3: "systray", 4: "clock", 5: "caramos-control-center", 6: "launcher"}


def without_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->\n?", "", text, flags=re.S)


class LunarTests(unittest.TestCase):
    def test_known_dates(self) -> None:
        for (day, month_number, year), (lunar_day, lunar_month, lunar_year, leap) in KNOWN_DATES:
            with self.subTest(date=(day, month_number, year)):
                self.assertEqual((lunar_day, lunar_month, lunar_year, leap), tuple(lunar.lunar_date(day, month_number, year)))

    def test_every_day_as_on_cinnamon(self) -> None:
        # The Cinnamon calendar's JavaScript, run by node, for every day of 1900-2100.
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        script = cinnamon.LUNAR_JS + """
const out = [];
for (let t = Date.UTC(1900, 0, 1); t <= Date.UTC(2100, 11, 31); t += 86400000) {
    const d = new Date(t);
    const l = caramosLunar(d.getUTCDate(), d.getUTCMonth() + 1, d.getUTCFullYear());
    out.push([l.day, l.month, l.year, l.leap]);
}
process.stdout.write(JSON.stringify(out));
"""
        expected = json.loads(subprocess.run([node, "-e", script], check=True, capture_output=True, text=True,
                                             timeout=120).stdout)
        day = datetime.date(1900, 1, 1)
        found = []
        for _entry in expected:
            found.append(list(lunar.of(day)))
            day += datetime.timedelta(days=1)
        self.assertEqual(datetime.date(2101, 1, 1), day)
        differ = [(index, want, got) for index, (want, got) in enumerate(zip(expected, found)) if want != got]
        self.assertEqual([], differ[:5])

    def test_words_as_on_cinnamon(self) -> None:
        cases = {
            (datetime.date(2026, 2, 21), "vi_VN.UTF-8"): "Âm lịch: mùng 5 tháng Giêng năm Bính Ngọ",
            (datetime.date(2026, 11, 20), "vi_VN.UTF-8"): "Âm lịch: 12 tháng 10 năm Bính Ngọ",
            (datetime.date(2026, 2, 16), "vi"): "Âm lịch: 29 tháng Chạp năm Ất Tỵ",
            (datetime.date(2025, 7, 25), "vi_VN"): "Âm lịch: mùng 1 tháng 6 nhuận năm Ất Tỵ",
            (datetime.date(2026, 11, 20), "en_US.UTF-8"): "Lunar calendar: day 12 of month 10, Bính Ngọ year",
            (datetime.date(2025, 7, 25), "C"): "Lunar calendar: day 1 of month 6 (leap), Ất Tỵ year",
            (datetime.date(2026, 11, 20), None): "Lunar calendar: day 12 of month 10, Bính Ngọ year",
        }
        for (date, language), expected in cases.items():
            with self.subTest(date=date, language=language):
                self.assertEqual(expected, lunar.lunar_text(date, language))
        self.assertEqual(["Bính Ngọ", "Ất Tỵ", "Giáp Thìn", "Canh Tý", "Đinh Mùi"],
                         [lunar.year_name(year) for year in (2026, 2025, 2024, 2020, 2027)])
        self.assertEqual("20 tháng 11 năm 2026", lunar.vietnamese_date(datetime.date(2026, 11, 20)))

    def test_the_grid_marks(self) -> None:
        # 9 November 2026 is mùng 1 tháng 10, 23 November rằm.
        self.assertEqual("1/10", lunar.cell_text(lunar.of(datetime.date(2026, 11, 9))))
        self.assertEqual("12", lunar.cell_text(lunar.of(datetime.date(2026, 11, 20))))
        self.assertTrue(lunar.marked(lunar.of(datetime.date(2026, 11, 9))))
        self.assertTrue(lunar.marked(lunar.of(datetime.date(2026, 11, 23))))
        self.assertFalse(lunar.marked(lunar.of(datetime.date(2026, 11, 20))))


class MonthTests(unittest.TestCase):
    def test_first_day_of_the_week_as_gtk_calendar(self) -> None:
        # glibc: en_US starts on Sunday, en_GB and vi_VN on Monday.
        self.assertEqual(month.SUNDAY, month.week_start("first_weekday=1\nweek-1stday=19971130\n"))
        self.assertEqual(month.MONDAY, month.week_start("first_weekday=2\nweek-1stday=19971130\n"))
        self.assertEqual(month.MONDAY, month.week_start("first_weekday=1\nweek-1stday=19971201\n"))
        self.assertEqual(6, month.week_start("first_weekday=7\nweek-1stday=19971130\n"))
        for broken in ("", "first_weekday=9\nweek-1stday=19971130\n", "first_weekday=1\nweek-1stday=20000101\n"):
            self.assertIsNone(month.week_start(broken))

    def test_six_weeks_from_the_week_of_the_first(self) -> None:
        sunday = month.days(2026, 11, month.SUNDAY)  # 1 November 2026 is a Sunday
        self.assertEqual(42, len(sunday))
        self.assertEqual(datetime.date(2026, 11, 1), sunday[0])
        self.assertEqual(datetime.date(2026, 12, 12), sunday[-1])
        monday = month.days(2026, 11, month.MONDAY)
        self.assertEqual(datetime.date(2026, 10, 26), monday[0])
        self.assertEqual([1] * 41, [(b - a).days for a, b in zip(monday, monday[1:])])
        self.assertTrue(all(month.weekday(day) == month.MONDAY for day in monday[::7]))

    def test_months_before_and_after(self) -> None:
        self.assertEqual((2025, 12), month.shifted(2026, 1, -1))
        self.assertEqual((2027, 1), month.shifted(2026, 12, 1))
        self.assertEqual((2027, 11), month.shifted(2026, 11, 12))
        self.assertEqual((2025, 11), month.shifted(2026, 11, -12))

    def test_the_weekend(self) -> None:
        self.assertEqual([True, False, False, False, False, False, True], [month.weekend(day) for day in range(7)])


class ControlCenterTests(unittest.TestCase):
    def source(self, name: str) -> str:
        return (PACKAGE / name).read_text(encoding="utf-8")

    def test_the_clock_beside_the_button(self) -> None:
        app = self.source("app.py")
        self.assertIn("box.pack_start(self.clock, False, False, 0)\n        box.pack_start(self.indicator, False, False, 0)",
                      app)
        # Never the calendar and the Control Center's popup together.
        self.assertIn("    def on_indicator(self, indicator: object, event_time: int) -> None:\n        self._hide_calendar()",
                      app)
        self.assertIn("        self.popup.hide_popup()\n        if self.calendar is None:", app)

    def test_the_clock_of_caramos_1_4_0(self) -> None:
        clock = self.source("clock.py")
        self.assertIn('FORMAT = "%A %H:%M, %-d %B"', clock)
        self.assertIn('self.set_name("clock-button")', clock)
        self.assertIn('"PrepareForSleep"', clock)
        css = self.source("style.css")
        rule = css[css.index(".caramos-cc-clock-label {"):]
        rule = rule[:rule.index("}")]
        old = re.search(r'name="digital-time-font" type="string" value="([^"]+)"', PANEL_1_4_0).group(1)
        self.assertEqual("Be Vietnam Pro Bold 10", old)
        for declaration in ('font-family: "Be Vietnam Pro";', "font-weight: bold;", "font-size: 10pt;"):
            self.assertIn(declaration, rule)

    def test_the_popups_share_their_mechanics(self) -> None:
        for name in ("popup.py", "calendar_popup.py"):
            self.assertRegex(self.source(name), r"class \w+\(CardPopup\):")
        base = self.source("popupbase.py")
        self.assertIn("seat.grab(window, Gdk.SeatCapabilities.ALL, True, None, None, None)", base)
        self.assertIn("if event.keyval == Gdk.KEY_Escape:", base)
        # Gtk.Window.move places the card: a method of that name in the calendar would hide it.
        self.assertNotRegex(self.source("calendar_popup.py"), r"\n    def move\(")

    def test_the_clock_waits_for_the_panel(self) -> None:
        # A clock taken out of the settings is on the taskbar until the panel starts again: the Control Center's
        # shows only once that happened, never beside it.
        source = self.source("backends/panelclock.py")
        self.assertIn("if self.xfce_clock or not WATCHED.fullmatch(prop):\n            return", source)


class PanelClockTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            self.panelclock = importlib.import_module("caramos_xfce_cc.backends.panelclock")
        except ImportError:
            self.skipTest("PyGObject is unavailable")

    def test_any_panel_in_use(self) -> None:
        shown = self.panelclock.xfce_clock_shown
        self.assertTrue(shown([1, 2, 3], {3: [3, 4, 5, 6]}, NAMES))
        self.assertFalse(shown([1, 2, 3], {3: [3, 5, 6]}, NAMES))
        self.assertTrue(shown([1, 4], {4: [4]}, NAMES), "on a panel of its own")
        self.assertFalse(shown([1, 2], {3: [4]}, NAMES), "a panel that is not in /panels is not shown")
        for prop in ("/panels", "/panels/panel-3/plugin-ids", "/plugins/plugin-4"):
            self.assertTrue(self.panelclock.WATCHED.fullmatch(prop), prop)
        self.assertFalse(self.panelclock.WATCHED.fullmatch("/plugins/plugin-4/digital-time-format"))


class PlanTests(unittest.TestCase):
    def test_the_clock_beside_the_control_center(self) -> None:
        self.assertEqual((3, [3, 5, 6]), migration.plan([1, 2, 3], {1: [1], 2: [2], 3: [3, 4, 5, 6]}, NAMES))
        # caramxfce, a panel changed by hand: other numbers.
        names = {3: "systray", 4: "clock", 5: "pulseaudio", 6: "launcher", 7: "caramos-control-center"}
        self.assertEqual((3, [3, 7, 6]), migration.plan([1, 2, 3], {3: [3, 4, 7, 6]}, names))

    def test_nothing_to_take_out(self) -> None:
        self.assertIsNone(migration.plan([1, 2, 3], {3: [3, 5, 6]}, NAMES))
        self.assertIsNone(migration.plan([1, 2], {1: [1, 4], 2: [2, 5]}, NAMES), "a clock on another panel stays")
        self.assertIsNone(migration.plan([1], {1: [1, 4]}, NAMES), "no Control Center")

    def test_xfconf_query_arrays(self) -> None:
        self.assertEqual([3, 4, 7, 6], migration.array("Value is an array with 4 items:\n\n3\n4\n7\n6\n"))
        self.assertEqual([5], migration.array("Value is an array with 1 items:\n\n5\n"))
        self.assertIsNone(migration.array("1\n"))
        self.assertIsNone(migration.array(""))
        self.assertIsNone(migration.array("Value is an array with 1 items:\n\nfive\n"))


class DefaultsTests(unittest.TestCase):
    def test_1_4_0_becomes_the_iso_of_now(self) -> None:
        new = migration.defaults_without_clock(PANEL_1_4_0)
        self.assertTrue(new)
        self.assertNotIn('value="clock"', new)
        self.assertEqual("", migration.defaults_without_clock(new), "once")
        if PANEL_XML.is_file():  # the source package has no config/
            # Then migration 20261124100000 puts Show desktop at the end of the right island.
            show_desktop = importlib.import_module(
                "caramos_ota_update.migrations.20261124100000_show_desktop_button.migration")
            self.assertEqual(without_comments(PANEL_XML.read_text(encoding="utf-8")),
                             without_comments(show_desktop.defaults_with_strip(new)))
        self.assertEqual(PANEL_1_4_0.count("<!--"), new.count("<!--"), "the comments stay")

    def test_files_not_as_expected_stay(self) -> None:
        self.assertEqual("", migration.defaults_without_clock("not xml"))
        self.assertEqual("", migration.defaults_without_clock('<channel name="xfce4-panel" version="1.0"/>'))
        moved = PANEL_1_4_0.replace('<value type="int" value="4"/>\n', "").replace(
            '<value type="int" value="2"/>\n      </property>', '<value type="int" value="2"/>\n        <value type="int" value="4"/>\n      </property>')
        self.assertEqual("", migration.defaults_without_clock(moved), "a clock in another panel stays")

    def test_written_only_when_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "xfce4-panel.xml"
            path.write_text(PANEL_1_4_0, encoding="utf-8")
            with mock.patch.object(MigrationContext, "log"):
                migration.xfce_defaults(MigrationContext(), path)
                first = path.read_text(encoding="utf-8")
                migration.xfce_defaults(MigrationContext(), path)
                migration.xfce_defaults(MigrationContext(), Path(tmp) / "missing.xml")
            self.assertEqual(migration.defaults_without_clock(PANEL_1_4_0), first)
            self.assertEqual(first, path.read_text(encoding="utf-8"))


class UserTests(unittest.TestCase):
    LISTING = ("/panels                    <<UNSUPPORTED>>\n/panels/panel-3/plugin-ids <<UNSUPPORTED>>\n"
               "/plugins/plugin-1          whiskermenu\n/plugins/plugin-2          docklike\n"
               "/plugins/plugin-3          systray\n/plugins/plugin-4          clock\n"
               "/plugins/plugin-4/mode     2\n/plugins/plugin-5          pulseaudio\n"
               "/plugins/plugin-6          launcher\n/plugins/plugin-7          caramos-control-center\n")
    ARRAYS = {"/panels": [1, 2, 3], "/panels/panel-1/plugin-ids": [1], "/panels/panel-2/plugin-ids": [2],
              "/panels/panel-3/plugin-ids": [3, 4, 7, 6]}

    def run_user(self, logged_in: bool, own_panels: bool = True, write_fails: bool = False) -> tuple[list, list]:
        commands: list[list[str]] = []
        logged: list[str] = []

        def run_command(argv, allow_fail=False, env=None):  # noqa: ANN001
            commands.append(list(argv))
            query = argv[argv.index("xfconf-query"):]
            if query[3:] == ["-l", "-v"]:
                return subprocess.CompletedProcess(argv, 0, self.LISTING, "")
            if "-s" in query:
                return subprocess.CompletedProcess(argv, 1 if write_fails else 0, "", "no" if write_fails else "")
            values = self.ARRAYS[query[4]]
            text = f"Value is an array with {len(values)} items:\n\n" + "".join(f"{v}\n" for v in values)
            return subprocess.CompletedProcess(argv, 0, text, "")

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            runtime = Path(tmp) / "run"
            if own_panels:
                (home / migration.USER_PANELS).parent.mkdir(parents=True)
                (home / migration.USER_PANELS).write_text("<channel/>", encoding="utf-8")
            if logged_in:
                (runtime / "1000").mkdir(parents=True)
                (runtime / "1000" / "bus").touch()
            context = MigrationContext()
            with mock.patch.object(context, "run_command", side_effect=run_command), \
                    mock.patch.object(context, "log", side_effect=logged.append):
                migration.xfce_user(context, "minh", 1000, home, runtime_root=runtime)
        return commands, logged

    def test_logged_in_through_their_session(self) -> None:
        commands, logged = self.run_user(logged_in=True)
        self.assertTrue(all(command[:4] == ["runuser", "-u", "minh", "--"] for command in commands))
        self.assertTrue(all("dbus-run-session" not in command for command in commands))
        self.assertEqual(["runuser", "-u", "minh", "--", "xfconf-query", "-c", "xfce4-panel", "-p",
                          "/panels/panel-3/plugin-ids", "--force-array", "-t", "int", "-s", "3", "-t", "int", "-s", "7",
                          "-t", "int", "-s", "6"], commands[-1])
        self.assertIn("from the next login", logged[-1])

    def test_not_logged_in_through_a_session_of_its_own(self) -> None:
        commands, _logged = self.run_user(logged_in=False)
        self.assertTrue(all(command[4:6] == ["dbus-run-session", "--"] for command in commands))
        self.assertEqual(["-s", "6"], commands[-1][-2:])

    def test_panels_still_the_defaults(self) -> None:
        commands, logged = self.run_user(logged_in=True, own_panels=False)
        self.assertEqual([], commands)
        self.assertIn("still the defaults", logged[0])

    def test_a_failed_write_is_logged(self) -> None:
        _commands, logged = self.run_user(logged_in=True, write_fails=True)
        self.assertTrue(logged[-1].startswith("warning:"))

    def test_run(self) -> None:
        users = [("minh", 1000, Path("/home/minh")), ("lan", 1001, Path("/home/lan"))]
        with mock.patch.object(migration.clipboard, "_desktop_users", return_value=users), \
                mock.patch.object(migration, "xfce_defaults") as defaults, \
                mock.patch.object(migration, "xfce_user") as user, \
                mock.patch.object(MigrationContext, "log"):
            migration.run(MigrationContext())
            defaults.assert_called_once()
            self.assertEqual(["minh", "lan"], [call.args[1] for call in user.call_args_list])
            user.reset_mock()
            migration.run(MigrationContext(dry_run=True))
            user.assert_not_called()

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(["xfce"], manifest["desktops"])
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertIn("lần đăng nhập sau", manifest["release_notes_vi"][-1])


if __name__ == "__main__":
    unittest.main()

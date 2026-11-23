"""Migration 20261120100200_lunar_calendar: lunar dates in Cinnamon's calendar applet (ticket H-1178)."""

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
migration = importlib.import_module("caramos_ota_update.migrations.20261120100200_lunar_calendar.migration")

# The lines of Cinnamon 6.6.4's calendar@cinnamon.org that the blocks go after, with their neighbours.
CALENDAR_JS = """const St = imports.gi.St;
const Clutter = imports.gi.Clutter;

const MSECS_IN_DAY = 24 * 60 * 60 * 1000;
const WEEKDATE_HEADER_WIDTH_DIGITS = 3;

class Calendar {
    _update(forceReload) {
        let iter = new Date();
        while (true) {
            let group = new Cinnamon.Stack();
            let button = new St.Button({ label: iter.getDate().toString() });
            group.add_actor(button);

            let dot_box = new Cinnamon.GenericContainer({ style_class: "calendar-day-event-dot-box" });
            group.add_actor(dot_box);

            let iterStr = iter.toUTCString();
        }
    }
}
"""
APPLET_JS = """const GLib = imports.gi.GLib;
const Calendar = require('./calendar');

class CinnamonCalendarApplet extends Applet.TextApplet {
    constructor() {
            this._date = new St.Label({ style_class: "calendar-today-date-label" });
            this.go_home_button.add_actor(this._date);

            this._calendar = new Calendar.Calendar(this.settings, this.events_manager);
    }

    _updateClockAndDate() {
        let dateFormattedTooltip = this.clock.get_clock_for_format(DATE_FORMAT_FULL).capitalize();
        this._day.set_text(dayFormatted);
        this._date.set_text(dateFormattedShort);
        this.set_applet_tooltip(dateFormattedTooltip);
    }
}
"""

# (Gregorian date, lunar day, month, year, leap): Tết, leap months, Mid-Autumn, and the years when Vietnam's
# calendar (UTC+7) and China's (UTC+8) disagree.
KNOWN_DATES = (
    ((17, 2, 2026), (1, 1, 2026, False)),     # Tết Bính Ngọ
    ((16, 2, 2026), (29, 12, 2025, False)),   # giao thừa: no 30th in tháng Chạp of Ất Tỵ
    ((29, 1, 2025), (1, 1, 2025, False)),
    ((10, 2, 2024), (1, 1, 2024, False)),
    ((22, 1, 2023), (1, 1, 2023, False)),
    ((22, 3, 2023), (1, 2, 2023, True)),      # tháng 2 nhuận
    ((25, 7, 2025), (1, 6, 2025, True)),      # tháng 6 nhuận
    ((23, 5, 2020), (1, 4, 2020, True)),      # tháng 4 nhuận
    ((25, 9, 2026), (15, 8, 2026, False)),    # Trung thu
    ((17, 2, 2007), (1, 1, 2007, False)),     # China: 18 February
    ((21, 1, 1985), (1, 1, 1985, False)),     # China: 20 February
    ((6, 2, 2027), (1, 1, 2027, False)),
    ((20, 11, 2026), (12, 10, 2026, False)),
)


class LunarAlgorithmTests(unittest.TestCase):
    def js(self, expression: str) -> object:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        script = migration.LUNAR_JS + f"\nprocess.stdout.write(JSON.stringify({expression}));\n"
        return json.loads(subprocess.run([node, "-e", script], check=True, capture_output=True, text=True).stdout)

    def test_known_dates(self) -> None:
        dates = [list(date) for date, _lunar in KNOWN_DATES]
        found = self.js(f"{json.dumps(dates)}.map(([d, m, y]) => caramosLunar(d, m, y))")
        for (date, (day, month, year, leap)), lunar in zip(KNOWN_DATES, found):
            with self.subTest(date=date):
                self.assertEqual({"day": day, "month": month, "year": year, "leap": leap}, lunar)

    def test_a_month_is_29_or_30_days(self) -> None:
        # Every lunar month of 2000-2030 ends on day 29 or 30.
        lengths = self.js("""(() => {
            const out = new Set();
            let previous = null;
            for (let t = Date.UTC(2000, 0, 1); t <= Date.UTC(2030, 11, 31); t += 86400000) {
                const d = new Date(t);
                const lunar = caramosLunar(d.getUTCDate(), d.getUTCMonth() + 1, d.getUTCFullYear());
                if (lunar.day === 1 && previous) out.add(previous.day);
                previous = lunar;
            }
            return [...out].sort();
        })()""")
        self.assertEqual([29, 30], lengths)

    def test_year_names(self) -> None:
        self.assertEqual(["Bính Ngọ", "Ất Tỵ", "Giáp Thìn", "Canh Tý", "Đinh Mùi"],
                         self.js("[2026, 2025, 2024, 2020, 2027].map(caramosLunarYearName)"))

    def test_vietnamese_date(self) -> None:
        self.assertEqual(["20 tháng 11 năm 2026", "1 tháng 1 năm 2027"],
                         self.js("[new Date(2026, 10, 20), new Date(2027, 0, 1)].map(caramosVietnameseDate)"))

    def test_words(self) -> None:
        cases = {
            "new Date(2026, 1, 21), 'vi_VN.UTF-8'": "Âm lịch: mùng 5 tháng Giêng năm Bính Ngọ",
            "new Date(2026, 10, 20), 'vi_VN.UTF-8'": "Âm lịch: 12 tháng 10 năm Bính Ngọ",
            "new Date(2026, 1, 16), 'vi'": "Âm lịch: 29 tháng Chạp năm Ất Tỵ",
            "new Date(2025, 6, 25), 'vi_VN'": "Âm lịch: mùng 1 tháng 6 nhuận năm Ất Tỵ",
            "new Date(2026, 10, 20), 'en_US.UTF-8'": "Lunar calendar: day 12 of month 10, Bính Ngọ year",
            "new Date(2025, 6, 25), 'C'": "Lunar calendar: day 1 of month 6 (leap), Ất Tỵ year",
        }
        for arguments, expected in cases.items():
            with self.subTest(arguments):
                self.assertEqual(expected, self.js(f"caramosLunarText({arguments})"))


class PatchTests(unittest.TestCase):
    def test_calendar(self) -> None:
        new = migration.patched("calendar.js", CALENDAR_JS)
        self.assertEqual(2, new.count(migration.START))
        functions = new.index("function caramosLunar(")
        self.assertLess(new.index("const MSECS_IN_DAY"), functions)
        self.assertLess(functions, new.index("class Calendar"))
        # The day's button shows the day of the month with the lunar day under it.
        cell = new.index("button.set_child(caramosDay);")
        self.assertLess(new.index("group.add_actor(dot_box);"), cell)
        self.assertLess(cell, new.index("let iterStr"))
        self.assertEqual(new, migration.patched("calendar.js", new))

    def test_applet(self) -> None:
        new = migration.patched("applet.js", APPLET_JS)
        self.assertEqual(2, new.count(migration.START))
        self.assertLess(new.index("this.go_home_button.add_actor(this._caramosLunar);"),
                        new.index("this._calendar = new Calendar.Calendar"))
        self.assertLess(new.index('dateFormattedTooltip += "\\n" + caramosLunarToday;'),
                        new.index("this.set_applet_tooltip(dateFormattedTooltip);"))
        self.assertLess(new.index("this._date.set_text(dateFormattedShort);"),
                        new.index("this._date.set_text(Calendar.caramosVietnameseDate(new Date()));"))
        self.assertEqual(new, migration.patched("applet.js", new))

    def test_valid_javascript(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        for name, source in (("calendar.js", CALENDAR_JS), ("applet.js", APPLET_JS)):
            with self.subTest(name):
                code = migration.patched(name, source).replace("imports.gi.", "({}).").replace("require(", "(")
                subprocess.run([node, "--check", "-"], input=code, text=True, check=True, capture_output=True)

    def test_other_cinnamon_code_stays(self) -> None:
        changed = CALENDAR_JS.replace("            group.add_actor(dot_box);\n", "            group.add(dot_box);\n")
        self.assertEqual("", migration.patched("calendar.js", changed))
        half = migration.patched("calendar.js", CALENDAR_JS).replace(migration.END, "", 1)
        self.assertEqual("", migration.patched("calendar.js", half))


class RestoreTests(unittest.TestCase):
    def applet(self, calendar: str = CALENDAR_JS, applet: str = APPLET_JS) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        directory = Path(tmp.name)
        (directory / "calendar.js").write_text(calendar, encoding="utf-8")
        (directory / "applet.js").write_text(applet, encoding="utf-8")
        for name in ("calendar.js", "applet.js"):
            (directory / name).chmod(0o644)
        return directory

    def test_both_files(self) -> None:
        directory = self.applet()
        with mock.patch.object(MigrationContext, "log"):
            migration.restore(MigrationContext(), directory)
        self.assertIn(migration.START, (directory / "calendar.js").read_text(encoding="utf-8"))
        self.assertIn(migration.START, (directory / "applet.js").read_text(encoding="utf-8"))
        self.assertEqual(0o644, (directory / "applet.js").stat().st_mode & 0o777)

    def test_both_or_neither(self) -> None:
        # The applet calls the calendar's function: one file alone would break it.
        directory = self.applet(applet=APPLET_JS.replace("this._date.set_text(dateFormattedShort);", "x();"))
        logged: list[str] = []
        with mock.patch.object(MigrationContext, "log", side_effect=logged.append):
            migration.restore(MigrationContext(), directory)
        self.assertEqual(CALENDAR_JS, (directory / "calendar.js").read_text(encoding="utf-8"))
        self.assertTrue(any(line.startswith("warning:") for line in logged), logged)

    def test_dry_run(self) -> None:
        directory = self.applet()
        with mock.patch.object(MigrationContext, "log"):
            migration.restore(MigrationContext(dry_run=True), directory)
        self.assertEqual(CALENDAR_JS, (directory / "calendar.js").read_text(encoding="utf-8"))

    def test_without_the_applet(self) -> None:
        logged: list[str] = []
        with mock.patch.object(MigrationContext, "log", side_effect=logged.append):
            migration.restore(MigrationContext(), Path("/nonexistent/calendar@cinnamon.org"))
        self.assertIn("nothing to change", logged[0])

    def test_after_a_cinnamon_update(self) -> None:
        with mock.patch.object(cinnamon_patches, "restore_taskbar"), \
                mock.patch.object(cinnamon_patches, "restore_wallpaper_collection_name"), \
                mock.patch.object(migration, "restore") as restore:
            cinnamon_patches.restore(MigrationContext(), {"20261120100200_lunar_calendar"})
            restore.assert_called_once()
            restore.reset_mock()
            cinnamon_patches.restore(MigrationContext(), set())
            restore.assert_not_called()
        triggers = (ROOT / "debian/triggers").read_text(encoding="utf-8")
        self.assertIn("interest-noawait /usr/share/cinnamon/applets/calendar@cinnamon.org\n", triggers)

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(["cinnamon"], manifest["desktops"])
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))


if __name__ == "__main__":
    unittest.main()

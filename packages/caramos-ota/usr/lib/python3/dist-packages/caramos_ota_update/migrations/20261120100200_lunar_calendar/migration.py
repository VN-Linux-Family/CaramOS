"""Lunar dates in the calendar of the Cinnamon panel (ticket H-1178: "thêm phần Âm lịch vào lịch mặc định").

Cinnamon's calendar applet (calendar@cinnamon.org, in Linux Mint's cinnamon-common) gets:
- the lunar day under each day of the month, centred, smaller and lighter, as calendars that show lunar dates put it;
  "1/10" on the first day of a lunar month, and the first and the fifteenth (mùng 1, rằm) in red, as Vietnamese wall
  calendars mark them;
- today's lunar date under today's date at the top ("Âm lịch: 12 tháng 10 năm Bính Ngọ"), and in the clock's
  tooltip; in English when the session is not in Vietnamese. In Vietnamese, today's date at the top reads the
  Vietnamese way too ("20 tháng 11 năm 2026"; Cinnamon's own is "Tháng 11 20, 2026").

The dates are computed in the applet (new moons and the sun's longitude for Vietnam's time zone, see LUNAR_JS), so
nothing is downloaded and the calendar works offline for any year. The changes are marked blocks after lines of the
applet that are checked first; an applet whose lines changed is left as it is. A Cinnamon update puts the original
files back: caramos_ota_update.cinnamon_patches makes the changes again after each one (debian/triggers). They show
when Cinnamon loads the applet again: at the next login.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Show lunar dates in Cinnamon's calendar"

CALENDAR_DIR = Path("/usr/share/cinnamon/applets/calendar@cinnamon.org")
START = "// CARAMOS_LUNAR_START"
END = "// CARAMOS_LUNAR_END"

LUNAR_JS = r"""// CaramOS: the Vietnamese lunar calendar (ticket H-1178). New moons and the sun's longitude after Jean Meeus,
// "Astronomical Algorithms", computed for Vietnam's time zone (UTC+7): the method of Hồ Ngọc Đức's
// "Lịch Việt Nam", which puts the month that holds the winter solstice as the 11th and makes the first month
// without a major solar term of a 13-month year its leap month.
function caramosJulianDay(day, month, year) {
    const a = Math.floor((14 - month) / 12);
    const y = year + 4800 - a;
    const m = month + 12 * a - 3;
    let jd = day + Math.floor((153 * m + 2) / 5) + 365 * y + Math.floor(y / 4) - Math.floor(y / 100)
        + Math.floor(y / 400) - 32045;
    if (jd < 2299161)
        jd = day + Math.floor((153 * m + 2) / 5) + 365 * y + Math.floor(y / 4) - 32083;
    return jd;
}

function caramosNewMoon(k) {
    const T = k / 1236.85, T2 = T * T, T3 = T2 * T, dr = Math.PI / 180;
    let jd1 = 2415020.75933 + 29.53058868 * k + 0.0001178 * T2 - 0.000000155 * T3;
    jd1 += 0.00033 * Math.sin((166.56 + 132.87 * T - 0.009173 * T2) * dr);
    const M = 359.2242 + 29.10535608 * k - 0.0000333 * T2 - 0.00000347 * T3;
    const Mpr = 306.0253 + 385.81691806 * k + 0.0107306 * T2 + 0.00001236 * T3;
    const F = 21.2964 + 390.67050646 * k - 0.0016528 * T2 - 0.00000239 * T3;
    let c1 = (0.1734 - 0.000393 * T) * Math.sin(M * dr) + 0.0021 * Math.sin(2 * dr * M);
    c1 = c1 - 0.4068 * Math.sin(Mpr * dr) + 0.0161 * Math.sin(dr * 2 * Mpr);
    c1 = c1 - 0.0004 * Math.sin(dr * 3 * Mpr);
    c1 = c1 + 0.0104 * Math.sin(dr * 2 * F) - 0.0051 * Math.sin(dr * (M + Mpr));
    c1 = c1 - 0.0074 * Math.sin(dr * (M - Mpr)) + 0.0004 * Math.sin(dr * (2 * F + M));
    c1 = c1 - 0.0004 * Math.sin(dr * (2 * F - M)) - 0.0006 * Math.sin(dr * (2 * F + Mpr));
    c1 = c1 + 0.0010 * Math.sin(dr * (2 * F - Mpr)) + 0.0005 * Math.sin(dr * (2 * Mpr + M));
    const deltat = T < -11
        ? 0.001 + 0.000839 * T + 0.0002261 * T2 - 0.00000845 * T3 - 0.000000081 * T * T3
        : -0.000278 + 0.000265 * T + 0.000262 * T2;
    return jd1 + c1 - deltat;
}

function caramosSunLongitude(jdn) {
    const T = (jdn - 2451545.0) / 36525, T2 = T * T, dr = Math.PI / 180;
    const M = 357.52910 + 35999.05030 * T - 0.0001559 * T2 - 0.00000048 * T * T2;
    const L0 = 280.46645 + 36000.76983 * T + 0.0003032 * T2;
    let dl = (1.914600 - 0.004817 * T - 0.000014 * T2) * Math.sin(dr * M);
    dl += (0.019993 - 0.000101 * T) * Math.sin(dr * 2 * M) + 0.000290 * Math.sin(dr * 3 * M);
    let L = (L0 + dl) * dr;
    L -= Math.PI * 2 * Math.floor(L / (Math.PI * 2));
    return L;
}

// The major solar term (0-11) of the day; the new moon's day; both in Vietnam's time zone.
function caramosSolarTerm(dayNumber) {
    return Math.floor(caramosSunLongitude(dayNumber - 0.5 - 7 / 24) / Math.PI * 6);
}

function caramosNewMoonDay(k) {
    return Math.floor(caramosNewMoon(k) + 0.5 + 7 / 24);
}

function caramosLunarMonth11(year) {
    const k = Math.floor((caramosJulianDay(31, 12, year) - 2415021) / 29.530588853);
    const day = caramosNewMoonDay(k);
    return caramosSolarTerm(day) >= 9 ? caramosNewMoonDay(k - 1) : day;
}

function caramosLeapMonthOffset(a11) {
    const k = Math.floor((a11 - 2415021.076998695) / 29.530588853 + 0.5);
    let i = 1, arc = caramosSolarTerm(caramosNewMoonDay(k + i)), last;
    do {
        last = arc;
        i++;
        arc = caramosSolarTerm(caramosNewMoonDay(k + i));
    } while (arc !== last && i < 14);
    return i - 1;
}

// {day, month, year, leap} of the lunar date of a day of the Gregorian calendar (month 1-12).
function caramosLunar(day, month, year) {
    const dayNumber = caramosJulianDay(day, month, year);
    const k = Math.floor((dayNumber - 2415021.076998695) / 29.530588853);
    let monthStart = caramosNewMoonDay(k + 1);
    if (monthStart > dayNumber)
        monthStart = caramosNewMoonDay(k);
    let a11 = caramosLunarMonth11(year), b11 = a11, lunarYear;
    if (a11 >= monthStart) {
        lunarYear = year;
        a11 = caramosLunarMonth11(year - 1);
    } else {
        lunarYear = year + 1;
        b11 = caramosLunarMonth11(year + 1);
    }
    const diff = Math.floor((monthStart - a11) / 29);
    let lunarMonth = diff + 11, leap = false;
    if (b11 - a11 > 365) {
        const leapDiff = caramosLeapMonthOffset(a11);
        if (diff >= leapDiff) {
            lunarMonth = diff + 10;
            leap = diff === leapDiff;
        }
    }
    if (lunarMonth > 12)
        lunarMonth -= 12;
    if (lunarMonth >= 11 && diff < 4)
        lunarYear -= 1;
    return { day: dayNumber - monthStart + 1, month: lunarMonth, year: lunarYear, leap };
}

const CARAMOS_CAN = ['Giáp', 'Ất', 'Bính', 'Đinh', 'Mậu', 'Kỷ', 'Canh', 'Tân', 'Nhâm', 'Quý'];
const CARAMOS_CHI = ['Tý', 'Sửu', 'Dần', 'Mão', 'Thìn', 'Tỵ', 'Ngọ', 'Mùi', 'Thân', 'Dậu', 'Tuất', 'Hợi'];

// The year's name in the sixty-year cycle, such as "Bính Ngọ" for 2026.
function caramosLunarYearName(year) {
    return `${CARAMOS_CAN[(year + 6) % 10]} ${CARAMOS_CHI[(year + 8) % 12]}`;
}
// The lunar date of `date` in words: "Âm lịch: mùng 5 tháng Giêng năm Bính Ngọ" when `language` (the first of
// GLib.get_language_names()) is Vietnamese, else "Lunar calendar: day 5 of month 1, Bính Ngọ year".
function caramosLunarText(date, language) {
    const lunar = caramosLunar(date.getDate(), date.getMonth() + 1, date.getFullYear());
    const year = caramosLunarYearName(lunar.year);
    if (String(language || '').startsWith('vi')) {
        const day = lunar.day <= 10 ? `mùng ${lunar.day}` : String(lunar.day);
        const month = lunar.month === 1 ? 'Giêng' : lunar.month === 12 ? 'Chạp' : String(lunar.month);
        return `Âm lịch: ${day} tháng ${month}${lunar.leap ? ' nhuận' : ''} năm ${year}`;
    }
    return `Lunar calendar: day ${lunar.day} of month ${lunar.month}${lunar.leap ? ' (leap)' : ''}, ${year} year`;
}
// A date the Vietnamese way, "20 tháng 11 năm 2026": Cinnamon's own short date reads "Tháng 11 20, 2026".
function caramosVietnameseDate(date) {
    return `${date.getDate()} tháng ${date.getMonth() + 1} năm ${date.getFullYear()}`;
}
// The lunar day in a cell of the month grid: smaller than the day of the month, and not bold on weekends.
const CARAMOS_LUNAR_DAY_STYLE = 'font-size: 0.72em; font-weight: normal;';"""

# (file, the line that the block goes after, the block)
PATCHES = (
    ("calendar.js", "const MSECS_IN_DAY = 24 * 60 * 60 * 1000;\n",
     f"\n{START} (ticket H-1178): the Vietnamese lunar calendar, for the month grid and the applet.\n{LUNAR_JS}\n{END}\n"),
    ("calendar.js", "            group.add_actor(dot_box);\n",
     f"""            {START} (ticket H-1178): the lunar day under the day of the month, centred, smaller and lighter,
            // as calendars with lunar dates show it; "1/10" on the first day of a lunar month.
            let caramosLunarDay = caramosLunar(iter.getDate(), iter.getMonth() + 1, iter.getFullYear());
            let caramosLunarLabel = new St.Label({{
                text: caramosLunarDay.day === 1 ? `1/${{caramosLunarDay.month}}` : String(caramosLunarDay.day),
                style: CARAMOS_LUNAR_DAY_STYLE,
                x_align: Clutter.ActorAlign.CENTER,
            }});
            let caramosDay = new St.BoxLayout({{ vertical: true }});
            caramosDay.add_actor(new St.Label({{ text: iter.getDate().toString(), x_align: Clutter.ActorAlign.CENTER }}));
            caramosDay.add_actor(caramosLunarLabel);
            button.set_child(caramosDay);
            button.style = 'height: 2.75em;';
            dot_box.style = 'margin-top: 2.35em;';
            if ((caramosLunarDay.day === 1 || caramosLunarDay.day === 15) && iter.getMonth() == this._selectedDate.getMonth()) {{
                // Mùng 1 and rằm in red, as wall calendars mark them; white under the pointer, like the day.
                let caramosRed = () => caramosLunarLabel.style = CARAMOS_LUNAR_DAY_STYLE + (button.hover ? '' : ' color: #d1493f;');
                button.connect('notify::hover', caramosRed);
                caramosRed();
            }} else {{
                caramosLunarLabel.opacity = 150;
            }}
            {END}
"""),
    ("applet.js", "            this.go_home_button.add_actor(this._date);\n",
     f"""            {START} (ticket H-1178): today's lunar date, under today's date and lighter.
            this._caramosLunar = new St.Label({{ style_class: "calendar-today-date-label",
                                                 style: "font-size: 1em; font-weight: normal; padding-top: 0.2em;" }});
            this._caramosLunar.opacity = 200;
            this.go_home_button.add_actor(this._caramosLunar);
            {END}
"""),
    ("applet.js", "        this._date.set_text(dateFormattedShort);\n",
     f"""        {START} (ticket H-1178): today's lunar date, at the top of the calendar and in the tooltip; in
        // Vietnamese, today's date in the Vietnamese order above it.
        let caramosLanguage = GLib.get_language_names()[0];
        let caramosLunarToday = Calendar.caramosLunarText(new Date(), caramosLanguage);
        if (String(caramosLanguage).startsWith('vi')) this._date.set_text(Calendar.caramosVietnameseDate(new Date()));
        if (this._caramosLunar) this._caramosLunar.set_text(caramosLunarToday);
        dateFormattedTooltip += "\\n" + caramosLunarToday;
        {END}
"""),
)


def patched(name: str, source: str) -> str:
    """The applet file with its lunar blocks; the same text when they are there already, "" when its lines are not
    the ones the blocks go after."""

    patches = [(anchor, block) for file, anchor, block in PATCHES if file == name]
    if source.count(START) == len(patches) and source.count(END) == len(patches):
        return source
    if START in source or END in source:
        return ""
    if any(source.count(anchor) != 1 for anchor, _block in patches):
        return ""
    for anchor, block in patches:
        source = source.replace(anchor, anchor + block, 1)
    return source


def _write(path: Path, content: str) -> None:
    fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(staging, path.stat().st_mode & 0o777)
        os.replace(staging, path)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise


def restore(context: MigrationContext, directory: Path = CALENDAR_DIR) -> None:
    """Puts the lunar blocks into both files of the applet, or into neither."""

    files = {name: directory / name for name in ("calendar.js", "applet.js")}
    if any(path.is_symlink() or not path.is_file() for path in files.values()):
        context.log(f"no Cinnamon calendar applet in {directory}; nothing to change")
        return
    new = {name: patched(name, path.read_text(encoding="utf-8")) for name, path in files.items()}
    if not all(new.values()):
        context.log(f"warning: the calendar applet in {directory} is not as expected; it stays without lunar dates")
        return
    changed = [name for name, path in files.items() if new[name] != path.read_text(encoding="utf-8")]
    if not changed:
        context.log("the calendar shows lunar dates already")
        return
    context.log(f"show lunar dates in the calendar: {', '.join(changed)}")
    if context.dry_run:
        return
    for name in changed:
        _write(files[name], new[name])


def run(context: MigrationContext) -> None:
    restore(context)

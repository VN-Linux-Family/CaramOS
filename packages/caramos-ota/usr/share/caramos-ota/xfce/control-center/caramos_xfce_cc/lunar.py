"""The Vietnamese lunar calendar, for the clock and its calendar (ticket H-1178): the computation of the Cinnamon
edition's calendar (LUNAR_JS of migration 20261120100200_lunar_calendar), in Python, step for step, so the two
editions show the same dates (tests/test_xfce_lunar_clock.py compares them day by day).

New moons and the sun's longitude after Jean Meeus, "Astronomical Algorithms", computed for Vietnam's time zone
(UTC+7): the method of Hồ Ngọc Đức's "Lịch Việt Nam", which puts the month that holds the winter solstice as the
11th and makes the first month without a major solar term of a 13-month year its leap month. Nothing is downloaded:
it works offline for any year.
"""

from __future__ import annotations

import datetime
import math
from functools import lru_cache
from typing import NamedTuple

TIME_ZONE = 7  # Vietnam, hours east of UTC

CAN = ("Giáp", "Ất", "Bính", "Đinh", "Mậu", "Kỷ", "Canh", "Tân", "Nhâm", "Quý")
CHI = ("Tý", "Sửu", "Dần", "Mão", "Thìn", "Tỵ", "Ngọ", "Mùi", "Thân", "Dậu", "Tuất", "Hợi")


class LunarDate(NamedTuple):
    day: int
    month: int
    year: int
    leap: bool


def julian_day(day: int, month: int, year: int) -> int:
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    jd = day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    if jd < 2299161:
        jd = day + (153 * m + 2) // 5 + 365 * y + y // 4 - 32083
    return jd


def new_moon(k: int) -> float:
    """The Julian day of the k-th new moon after 1 January 1900."""

    t = k / 1236.85
    t2 = t * t
    t3 = t2 * t
    dr = math.pi / 180
    jd1 = 2415020.75933 + 29.53058868 * k + 0.0001178 * t2 - 0.000000155 * t3
    jd1 += 0.00033 * math.sin((166.56 + 132.87 * t - 0.009173 * t2) * dr)
    m = 359.2242 + 29.10535608 * k - 0.0000333 * t2 - 0.00000347 * t3
    mpr = 306.0253 + 385.81691806 * k + 0.0107306 * t2 + 0.00001236 * t3
    f = 21.2964 + 390.67050646 * k - 0.0016528 * t2 - 0.00000239 * t3
    c1 = (0.1734 - 0.000393 * t) * math.sin(m * dr) + 0.0021 * math.sin(2 * dr * m)
    c1 = c1 - 0.4068 * math.sin(mpr * dr) + 0.0161 * math.sin(dr * 2 * mpr)
    c1 = c1 - 0.0004 * math.sin(dr * 3 * mpr)
    c1 = c1 + 0.0104 * math.sin(dr * 2 * f) - 0.0051 * math.sin(dr * (m + mpr))
    c1 = c1 - 0.0074 * math.sin(dr * (m - mpr)) + 0.0004 * math.sin(dr * (2 * f + m))
    c1 = c1 - 0.0004 * math.sin(dr * (2 * f - m)) - 0.0006 * math.sin(dr * (2 * f + mpr))
    c1 = c1 + 0.0010 * math.sin(dr * (2 * f - mpr)) + 0.0005 * math.sin(dr * (2 * mpr + m))
    if t < -11:
        deltat = 0.001 + 0.000839 * t + 0.0002261 * t2 - 0.00000845 * t3 - 0.000000081 * t * t3
    else:
        deltat = -0.000278 + 0.000265 * t + 0.000262 * t2
    return jd1 + c1 - deltat


def sun_longitude(jdn: float) -> float:
    """The sun's longitude in radians, 0 to 2π."""

    t = (jdn - 2451545.0) / 36525
    t2 = t * t
    dr = math.pi / 180
    m = 357.52910 + 35999.05030 * t - 0.0001559 * t2 - 0.00000048 * t * t2
    l0 = 280.46645 + 36000.76983 * t + 0.0003032 * t2
    dl = (1.914600 - 0.004817 * t - 0.000014 * t2) * math.sin(dr * m)
    dl += (0.019993 - 0.000101 * t) * math.sin(dr * 2 * m) + 0.000290 * math.sin(dr * 3 * m)
    longitude = (l0 + dl) * dr
    longitude -= math.pi * 2 * math.floor(longitude / (math.pi * 2))
    return longitude


def solar_term(day_number: int) -> int:
    """The major solar term (0-11) of the day, in Vietnam's time zone."""

    return math.floor(sun_longitude(day_number - 0.5 - TIME_ZONE / 24) / math.pi * 6)


@lru_cache(maxsize=4096)
def new_moon_day(k: int) -> int:
    """The day (Julian day number) of the k-th new moon, in Vietnam's time zone."""

    return math.floor(new_moon(k) + 0.5 + TIME_ZONE / 24)


@lru_cache(maxsize=512)
def lunar_month_11(year: int) -> int:
    """The first day of the 11th lunar month, the one with the winter solstice, around the end of `year`."""

    k = math.floor((julian_day(31, 12, year) - 2415021) / 29.530588853)
    day = new_moon_day(k)
    return new_moon_day(k - 1) if solar_term(day) >= 9 else day


@lru_cache(maxsize=512)
def leap_month_offset(a11: int) -> int:
    k = math.floor((a11 - 2415021.076998695) / 29.530588853 + 0.5)
    i = 1
    arc = solar_term(new_moon_day(k + i))
    while True:
        last = arc
        i += 1
        arc = solar_term(new_moon_day(k + i))
        if arc == last or i >= 14:
            return i - 1


def lunar_date(day: int, month: int, year: int) -> LunarDate:
    """The lunar date of a day of the Gregorian calendar (month 1-12)."""

    day_number = julian_day(day, month, year)
    k = math.floor((day_number - 2415021.076998695) / 29.530588853)
    month_start = new_moon_day(k + 1)
    if month_start > day_number:
        month_start = new_moon_day(k)
    a11 = lunar_month_11(year)
    b11 = a11
    if a11 >= month_start:
        lunar_year = year
        a11 = lunar_month_11(year - 1)
    else:
        lunar_year = year + 1
        b11 = lunar_month_11(year + 1)
    diff = math.floor((month_start - a11) / 29)
    lunar_month = diff + 11
    leap = False
    if b11 - a11 > 365:
        leap_diff = leap_month_offset(a11)
        if diff >= leap_diff:
            lunar_month = diff + 10
            leap = diff == leap_diff
    if lunar_month > 12:
        lunar_month -= 12
    if lunar_month >= 11 and diff < 4:
        lunar_year -= 1
    return LunarDate(day_number - month_start + 1, lunar_month, lunar_year, leap)


def of(date: datetime.date) -> LunarDate:
    return lunar_date(date.day, date.month, date.year)


def year_name(year: int) -> str:
    """The year's name in the sixty-year cycle, such as "Bính Ngọ" for 2026."""

    return f"{CAN[(year + 6) % 10]} {CHI[(year + 8) % 12]}"


def is_vietnamese(language: str | None) -> bool:
    """language: the first of GLib.get_language_names(), as the Cinnamon calendar decides."""

    return str(language or "").startswith("vi")


def lunar_text(date: datetime.date, language: str | None) -> str:
    """"Âm lịch: mùng 5 tháng Giêng năm Bính Ngọ" in Vietnamese, else "Lunar calendar: day 5 of month 1, Bính Ngọ
    year", as on Cinnamon."""

    lunar = of(date)
    year = year_name(lunar.year)
    if is_vietnamese(language):
        day = f"mùng {lunar.day}" if lunar.day <= 10 else str(lunar.day)
        month = "Giêng" if lunar.month == 1 else "Chạp" if lunar.month == 12 else str(lunar.month)
        return f"Âm lịch: {day} tháng {month}{' nhuận' if lunar.leap else ''} năm {year}"
    return f"Lunar calendar: day {lunar.day} of month {lunar.month}{' (leap)' if lunar.leap else ''}, {year} year"


def vietnamese_date(date: datetime.date) -> str:
    """"20 tháng 11 năm 2026": the date the Vietnamese way (glibc's vi_VN writes the month "Tháng 11")."""

    return f"{date.day} tháng {date.month} năm {date.year}"


def cell_text(lunar: LunarDate) -> str:
    """The lunar day in the month grid: "1/10" on the first day of a lunar month, as on Cinnamon."""

    return f"1/{lunar.month}" if lunar.day == 1 else str(lunar.day)


def marked(lunar: LunarDate) -> bool:
    """Mùng 1 and rằm, which Vietnamese wall calendars mark in red."""

    return lunar.day in (1, 15)

"""The month that the calendar shows: its six weeks, and the first day of the week of the locale, as GtkCalendar (the
calendar of Xfce's clock) takes it. Days of the week are numbered as GLib and JavaScript do: 0 Sunday to 6 Saturday."""

from __future__ import annotations

import datetime
import re
import subprocess

SUNDAY = 0
MONDAY = 1
WEEKS = 6  # always six rows, as GtkCalendar and Cinnamon's calendar
# _NL_TIME_WEEK_1STDAY: the date of a day that starts a week, 30 November 1997 a Sunday, 1 December a Monday.
WEEK_ORIGINS = {"19971130": SUNDAY, "19971201": MONDAY}


def week_start(locale_keywords: str) -> int | None:
    """The first day of the week from `locale -k first_weekday week-1stday`, as GtkCalendar computes it; None when
    the output does not say."""

    values = dict(re.findall(r"^([a-z0-9_-]+)=(\S+)$", locale_keywords, re.M))
    origin = WEEK_ORIGINS.get(values.get("week-1stday", ""))
    first = values.get("first_weekday", "")
    if origin is None or not first.isdigit() or not 1 <= int(first) <= 7:
        return None
    return (origin + int(first) - 1) % 7


def locale_week_start(vietnamese: bool) -> int:
    """The first day of the week of the program's locale (LC_TIME); Monday in Vietnamese and Sunday otherwise when
    `locale` cannot tell."""

    try:
        output = subprocess.run(["locale", "-k", "first_weekday", "week-1stday"], capture_output=True, text=True,
                                timeout=5, check=False, stdin=subprocess.DEVNULL).stdout
    except (OSError, subprocess.SubprocessError):
        output = ""
    found = week_start(output)
    if found is not None:
        return found
    return MONDAY if vietnamese else SUNDAY


def weekday(date: datetime.date) -> int:
    return date.isoweekday() % 7


def days(year: int, month: int, first_day: int) -> list[datetime.date]:
    """The 42 days of the grid: the weeks of the month, from the week of its 1st."""

    first = datetime.date(year, month, 1)
    start = first - datetime.timedelta(days=(weekday(first) - first_day) % 7)
    return [start + datetime.timedelta(days=offset) for offset in range(7 * WEEKS)]


def shifted(year: int, month: int, months: int) -> tuple[int, int]:
    """(year, month) `months` later (earlier when negative)."""

    index = year * 12 + (month - 1) + months
    return index // 12, index % 12 + 1


def weekend(day: int) -> bool:
    """Saturday and Sunday, which Cinnamon's calendar writes in bold."""

    return day in (SUNDAY, 6)

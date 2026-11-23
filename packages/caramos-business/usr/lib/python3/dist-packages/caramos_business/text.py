"""Small text helpers of the window, apart from GTK so that they can be tested without a display."""

from __future__ import annotations

import datetime
import re
from typing import Any

from . import protocol
from .i18n import _, ngettext

# The agent's detail for a lock, message, restart and the like issued before the machine's current boot (PROTOCOL.md
# part 2, "Signed commands").
BEFORE_THIS_BOOT = "trước lần khởi động này"
DAY_MONTH = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})\s*$")
DAY_MONTH_YEAR = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d{1,2})\s*/\s*(\d{4})\s*$")


def weekday_names() -> list[str]:
    """Short weekday names, Monday first (ISO weekday 1 to 7); in Vietnamese T2 to CN."""

    return [_("Mon"), _("Tue"), _("Wed"), _("Thu"), _("Fri"), _("Sat"), _("Sun")]


def month_day(text: str) -> str | None:
    """'25/1' or '25/01' (day/month, as Vietnamese write dates) as PROTOCOL.md's '01-25'; None if not a day."""

    match = DAY_MONTH.match(text)
    if not match:
        return None
    value = f"{int(match.group(2)):02d}-{int(match.group(1)):02d}"
    return value if protocol.valid_month_day(value) else None


def day_month(value: str) -> str:
    """'01-25' as '25/1'."""

    month, day = value.split("-")
    return f"{int(day)}/{int(month)}"


def iso_date(text: str) -> str | None:
    """'15/3/2024' as '2024-03-15'; '' for an empty text; None if not a date."""

    if not text.strip():
        return ""
    match = DAY_MONTH_YEAR.match(text)
    if not match:
        return None
    try:
        return datetime.date(int(match.group(3)), int(match.group(2)), int(match.group(1))).isoformat()
    except ValueError:
        return None


def vn_date(value: str) -> str:
    """'2024-03-15' as '15/3/2024'."""

    try:
        day = datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return ""
    return f"{day.day}/{day.month}/{day.year}"


def money(value: Any) -> str:
    """A price in đồng with dots between thousands, as Vietnamese write it: 15.000.000 đ."""

    if not isinstance(value, int) or isinstance(value, bool):
        return ""
    return f"{value:,}".replace(",", ".") + " đ"


def parse_money(text: str) -> int | None:
    """'15.000.000', '15,000,000 đ' or '15000000' as 15000000; None for an empty text; ValueError if not a number."""

    digits = re.sub(r"[\s.,đĐdVNDvnd]", "", text)
    if not digits:
        return None
    if not digits.isdigit():
        raise ValueError(text)
    return int(digits)


def ago(text: str, now: datetime.datetime | None = None) -> str:
    """How long ago an ISO 8601 time was, in words."""

    try:
        then = datetime.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return _("never")
    if then.tzinfo is None:
        then = then.astimezone()
    seconds = ((now or datetime.datetime.now().astimezone()) - then).total_seconds()
    if seconds < 90:
        return _("just now")
    if seconds < 3600:
        minutes = int(seconds // 60)
        return ngettext("%d minute ago", "%d minutes ago", minutes) % minutes
    if seconds < 86400:
        hours = int(seconds // 3600)
        return ngettext("%d hour ago", "%d hours ago", hours) % hours
    days = int(seconds // 86400)
    return ngettext("%d day ago", "%d days ago", days) % days


def clock(text: str) -> str:
    """An ISO 8601 time as '14:05' today, or '14:05, 20/11' another day."""

    try:
        then = datetime.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return ""
    then = then.astimezone() if then.tzinfo else then
    if then.date() == datetime.datetime.now().astimezone().date():
        return then.strftime("%H:%M")
    return f"{then:%H:%M}, {then.day}/{then.month}"


def days_text(days: list[int]) -> str:
    """[1, 2, 3, 4, 5, 6] as 'T2 to T7' (Vietnamese weekday names), [1, 3] as 'T2, T4'."""

    days = sorted(set(days))
    if not days:
        return ""
    if len(days) == 7:
        return _("every day")
    names = [weekday_names()[day - 1] for day in days]
    if len(days) >= 3 and days == list(range(days[0], days[-1] + 1)):
        return _("%(first)s to %(last)s") % {"first": names[0], "last": names[-1]}
    return ", ".join(names)


def join_sentence(parts: list[str]) -> str:
    """Parts of a sentence joined with commas, without the empty ones."""

    return ", ".join(part for part in parts if part)


def fold(value: str) -> str:
    """Lower case without accents, for searching: 'Kế Toán' gives 'ke toan'."""

    import unicodedata

    decomposed = unicodedata.normalize("NFKD", value.replace("đ", "d").replace("Đ", "D"))
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def sentence(parts: list[str]) -> str:
    """Parts joined with commas, as a sentence: the first letter upper case (only that one), a full stop."""

    joined = join_sentence(parts)
    return joined[:1].upper() + joined[1:] + "." if joined else ""


def size_gb(value: Any) -> str:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        return ""
    if value >= 1000:
        return f"{value / 1000:.1f} TB".replace(".0 ", " ").replace(".", ",")
    return f"{value:.0f} GB"


def cpu_text(inventory: dict[str, Any]) -> str:
    cpu = inventory.get("cpu") or {}
    model = re.sub(r"\s+", " ", cpu.get("model") or "").strip()
    cores, threads = cpu.get("cores"), cpu.get("threads")
    if cores and threads and threads != cores:
        return _("%(model)s, %(cores)d cores, %(threads)d threads") % {"model": model, "cores": cores,
                                                                         "threads": threads}
    if cores:
        return ngettext("%(model)s, %(cores)d core", "%(model)s, %(cores)d cores", cores) % {"model": model,
                                                                                          "cores": cores}
    return model


def memory_text(inventory: dict[str, Any]) -> str:
    memory = inventory.get("memory") or {}
    total = memory.get("total_mb")
    if not total:
        return ""
    gigabytes = round(total / 1024)
    text = f"{max(gigabytes, 1)} GB"
    kinds = sorted({module.get("type") for module in memory.get("modules") or [] if module.get("type")})
    return f"{text} {'/'.join(kinds)}" if kinds else text


def disk_kind(disk: dict[str, Any]) -> str:
    if disk.get("transport") == "nvme":
        return "SSD NVMe"
    if disk.get("rotational") is True:
        return "HDD"
    if disk.get("rotational") is False:
        return "SSD"
    return ""


def disks_text(inventory: dict[str, Any]) -> str:
    return ", ".join(" ".join(part for part in (size_gb(disk.get("size_gb")), disk_kind(disk)) if part)
                     for disk in inventory.get("disks") or [] if disk.get("size_gb"))


def model_text(inventory: dict[str, Any]) -> str:
    system = inventory.get("system") or {}
    return " ".join(part for part in (system.get("vendor") or "", system.get("product") or "") if part).strip()


def edition_text(edition: str) -> str:
    return {"cinnamon": "Cinnamon", "xfce": "Xfce"}.get(edition, "")

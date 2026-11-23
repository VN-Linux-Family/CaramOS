"""The problems the admin flags (PROTOCOL.md part 2, "Problems", and part 3, "Security report"), and when each was
first seen.

The server records, at each check-in, the clock skew, since when security updates and a restart have been waiting,
and the first time each problem showed (health.json). The window shows the problems from the same function, plus
"not seen for 3 days", which no check-in can report."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any

from . import protocol
from .i18n import _, ngettext

DISK_FREE_MIN = 10
BATTERY_MIN = 60
SECURITY_DAYS = 7
REBOOT_DAYS = 3
OFFLINE_DAYS = 3
ONLINE_MINUTES = 10
# Most urgent first: the overview lists problems in this order.
SEVERITY = ("clone", "disk_failing", "disk_space", "firewall", "applied", "security_updates", "maintenance_late",
            "snapshot_old", "freeze_pending", "clock", "capability", "reboot", "battery", "offline")
# A machine that changed network card this many times within CLONE_MINUTES is probably two machines with a cloned
# disk, checking in by turns. A laptop moving from cable to Wi-Fi and back changes card twice.
CLONE_SWITCHES = 3
CLONE_MINUTES = 30
# Part 3: a snapshot is late after twice its period; a frozen machine after 8 days without maintenance; a freeze that
# is on the disk but not running (or the other way round) after a day.
SNAPSHOT_LATE_DAYS = {"daily": 2, "weekly": 14, "monthly": 62}
MAINTENANCE_LATE_DAYS = 8
FREEZE_PENDING_DAYS = 1


@dataclass
class Problem:
    key: str
    text: str
    since: datetime.datetime | None

    @property
    def severity(self) -> int:
        kind = self.key.split(":", 1)[0]
        return SEVERITY.index(kind) if kind in SEVERITY else len(SEVERITY)


def _parse(text: Any) -> datetime.datetime | None:
    try:
        value = datetime.datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.astimezone()


def _iso(value: datetime.datetime) -> str:
    return value.isoformat(timespec="seconds")


def section_title(section: str) -> str:
    return {"wallpaper": _("Wallpaper"), "folders": _("Folders on the server"), "shares": _("Shared drives"),
            "browser": _("Browser"), "printers": _("Printers"), "power": _("Power schedule"), "apps": _("Apps"),
            "usb": _("USB storage"), "screen_lock": _("Screen lock"), "firewall": _("Firewall"),
            "inventory": _("Automatic inventory"), "wifi": _("Wi-Fi"), "shared": _("Shared machine"),
            "snapshots": _("System snapshots")}.get(section, section)


def duration(seconds: float) -> str:
    """A duration in words: "3 minutes", "2 hours", "5 days"."""

    seconds = abs(seconds)
    if seconds < 120:
        value = int(seconds)
        return ngettext("%d second", "%d seconds", value) % value
    if seconds < 7200:
        value = int(seconds // 60)
        return ngettext("%d minute", "%d minutes", value) % value
    if seconds < 2 * 86400:
        value = int(seconds // 3600)
        return ngettext("%d hour", "%d hours", value) % value
    value = int(seconds // 86400)
    return ngettext("%d day", "%d days", value) % value


def managed(effective: dict[str, Any]) -> list[str]:
    """The sections a machine's agent must apply: present and not null."""

    return [section for section in protocol.SECTIONS if effective.get(section) is not None]


def reported(entry: dict[str, Any], record: dict[str, Any], effective: dict[str, Any],
             now: datetime.datetime) -> dict[str, str]:
    """The problems a machine's last check-in shows: {key: text}. Not "offline": see problems()."""

    found: dict[str, str] = {}

    def lately(when: object) -> bool:
        seen = _parse(when)
        return seen is not None and now - seen <= datetime.timedelta(minutes=CLONE_MINUTES)

    if sum(1 for when in entry.get("mac_switches") or [] if lately(when)) >= CLONE_SWITCHES:
        cards = sorted(mac for mac, when in (entry.get("macs") or {}).items() if lately(when))
        found["clone"] = _("It may be a cloned disk: machines with the network cards %s report as this one. Remove it, "
                           "then pair each machine again.") % ", ".join(cards)
    health = entry.get("health") or {}
    if health:
        free = health.get("disk_free_pct")
        if free is not None and free < DISK_FREE_MIN:
            found["disk_space"] = _("The disk is almost full: %d%% free.") % int(free)
        if health.get("disk_health") == "failing":
            found["disk_failing"] = _("A disk is failing: copy the files to a safe place and replace it.")
        battery = health.get("battery_health_pct")
        if battery is not None and battery < BATTERY_MIN:
            found["battery"] = _("The battery is worn: it holds %d%% of its first charge.") % int(battery)
        security = (health.get("updates") or {}).get("security", 0)
        since = _parse(record.get("security_since"))
        if security and since and now - since > datetime.timedelta(days=SECURITY_DAYS):
            found["security_updates"] = ngettext(
                "%(count)d security update has waited for %(time)s.", "%(count)d security updates have waited for "
                "%(time)s.", security) % {"count": security, "time": duration((now - since).total_seconds())}
        since = _parse(record.get("reboot_since"))
        if health.get("reboot_required") and since and now - since > datetime.timedelta(days=REBOOT_DAYS):
            found["reboot"] = _("It has needed a restart for %s.") % duration((now - since).total_seconds())
        if effective.get("firewall") is not None and health.get("firewall") == "off":
            found["firewall"] = _("The firewall is off, though the company turns it on.")
        for section, state in sorted((health.get("applied") or {}).items()):
            if state != "ok":
                reason = state.split(":", 1)[1].strip() if ":" in state else state
                found[f"applied:{section}"] = _("%(section)s was not applied: %(reason)s") % {
                    "section": section_title(section), "reason": reason}
    found.update(shared_problems(health, record, effective, now))
    skew = record.get("skew")
    if isinstance(skew, (int, float)) and abs(skew) > protocol.SKEW_PROBLEM:
        found["clock"] = _("Its clock is %s off.") % duration(skew)
    capabilities = entry.get("capabilities")
    if isinstance(capabilities, list) and (capabilities or entry.get("health")):
        for section in managed(effective):
            if section not in capabilities:
                found[f"capability:{section}"] = _("Its CaramOS Doanh nghiệp cannot apply %s yet: update the "
                                                   "machine.") % section_title(section)
    return found


def freezing(effective: dict[str, Any]) -> bool:
    return bool((effective.get("shared") or {}).get("freeze"))


def shared_problems(health: dict[str, Any], record: dict[str, Any], effective: dict[str, Any],
                    now: datetime.datetime) -> dict[str, str]:
    """Part 3's problems: snapshot_old, maintenance_late and freeze_pending."""

    found: dict[str, str] = {}
    snapshots = effective.get("snapshots")
    if snapshots and health:
        late = datetime.timedelta(days=SNAPSHOT_LATE_DAYS.get(snapshots.get("schedule"), 14))
        last, since = _parse(health.get("last_snapshot")), _parse(record.get("snapshots_since"))
        if last and now - last > late:
            found["snapshot_old"] = _("The last system snapshot is %s old.") % duration((now - last).total_seconds())
        elif not last and since and now - since > late:
            found["snapshot_old"] = _("No system snapshot was taken in %s.") % duration((now - since).total_seconds())
    if freezing(effective) and health:
        late = datetime.timedelta(days=MAINTENANCE_LATE_DAYS)
        last, since = _parse(health.get("last_maintenance")), _parse(record.get("freeze_since"))
        if last and now - last > late:
            found["maintenance_late"] = _("This frozen machine has had no maintenance for %s, so it misses its "
                                          "updates.") % duration((now - last).total_seconds())
        elif not last and since and now - since > late:
            found["maintenance_late"] = _("This frozen machine has had no maintenance in the %s since it was "
                                          "frozen.") % duration((now - since).total_seconds())
    since = _parse(record.get("freeze_pending_since"))
    if since and now - since > datetime.timedelta(days=FREEZE_PENDING_DAYS):
        if health.get("freeze_configured"):
            found["freeze_pending"] = _("It needs a restart to start freezing.")
        else:
            found["freeze_pending"] = _("It needs a restart to stop freezing.")
    return found


def update_record(record: dict[str, Any] | None, entry: dict[str, Any], effective: dict[str, Any],
                  now: datetime.datetime, skew: float | None = None) -> dict[str, Any]:
    """health.json's entry for a machine after a check-in: the skew, since when security updates and a restart
    have waited, and when each current problem was first seen."""

    record = dict(record or {})
    if skew is not None:
        record["skew"] = int(skew)
    health = entry.get("health") or {}
    if health:
        waiting = (health.get("updates") or {}).get("security", 0) > 0
        record["security_since"] = (record.get("security_since") or _iso(now)) if waiting else None
        record["reboot_since"] = (record.get("reboot_since") or _iso(now)) if health.get("reboot_required") else None
        pending = bool(health.get("frozen")) != bool(health.get("freeze_configured"))
        record["freeze_pending_since"] = (record.get("freeze_pending_since") or _iso(now)) if pending else None
    # Since when snapshots and freezing have been on for this machine: "none yet" is late only after a while.
    record["snapshots_since"] = (record.get("snapshots_since") or _iso(now)) if effective.get("snapshots") else None
    record["freeze_since"] = (record.get("freeze_since") or _iso(now)) if freezing(effective) else None
    first_seen = dict(record.get("problems") or {})
    current = reported(entry, record, effective, now)
    record["problems"] = {key: first_seen.get(key) or _iso(now) for key in current}
    return record


def online(entry: dict[str, Any], now: datetime.datetime) -> bool:
    seen = _parse(entry.get("last_seen"))
    return bool(seen and now - seen <= datetime.timedelta(minutes=ONLINE_MINUTES))


def problems(entry: dict[str, Any], record: dict[str, Any] | None, effective: dict[str, Any],
             now: datetime.datetime) -> list[Problem]:
    """Everything to flag for a machine, most urgent first."""

    record = record or {}
    first_seen = record.get("problems") or {}
    found = [Problem(key, text, _parse(first_seen.get(key))) for key, text in
             reported(entry, record, effective, now).items()]
    seen = _parse(entry.get("last_seen"))
    if seen and now - seen > datetime.timedelta(days=OFFLINE_DAYS):
        found.append(Problem("offline", _("Not seen for %s.") % duration((now - seen).total_seconds()),
                             seen + datetime.timedelta(days=OFFLINE_DAYS)))
    return sorted(found, key=lambda problem: problem.severity)

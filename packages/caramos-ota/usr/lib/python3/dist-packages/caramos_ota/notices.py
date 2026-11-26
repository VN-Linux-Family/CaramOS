"""Notices from the CaramOS team to this computer (caramos-ota-notices).

The team writes them at https://caramos.vietnamlinuxfamily.net/quan-tri (CaramOSLanding: server/admin.js), and
URL lists the notices that are on. caramos-ota-notices.timer, a user timer of every desktop session, runs
caramos-ota-notices 3 minutes after login and every 4 hours: it fetches the list, keeps the notices meant for this
computer and shows each one once to each user (notices_window), in the session's language when the notice has it.

Meant for this computer: its CaramOS version (VERSION in /etc/caramos-release) within the notice's bounds, its edition
(Cinnamon or Xfce), and its state when the notice asks for one: an update waiting to be installed, or updates failing
(the last automatic update failed, or no successful daily check for 3 days on a computer up for 2 hours).

Why: on 2026-11-26 most computers counted by the daily count had a recent updater and an old CaramOS (1.0.x, 1.3.x,
1.4.0), and computers whose dpkg was interrupted could not update at all; nothing could tell their users. This goes
through no APT and no dpkg, and its request says nothing about the computer: it gets the whole list and chooses. A
notice is text and at most one https link to vietnamlinuxfamily.net; nothing in it is run.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from .constants import STATE_FILE

URL = "https://caramos.vietnamlinuxfamily.net/api/thong-bao"
TIMEOUT_SECONDS = 20
MAX_BYTES = 256 * 1024
USER_AGENT = "caramos-ota-notices/1"
RELEASE_FILE = Path("/etc/caramos-release")
AUTO_UPDATE_RESULT_KEY = "auto_update"   # caramos_ota.auto_update.STATUS_KEY, in state.json
FAILING_AFTER = timedelta(days=3)
UP_AT_LEAST = timedelta(hours=2)

LEVELS = ("info", "warning", "critical")
EDITIONS = ("all", "cinnamon", "xfce")
CONDITIONS = ("all", "update-waiting", "update-failing")
LIMITS = {"title": 120, "body": 2000, "label": 40, "url": 300}
_VERSION = re.compile(r"^\d{1,3}(\.\d{1,3}){1,3}$")


@dataclass(frozen=True)
class Link:
    url: str
    label_vi: str
    label_en: str


@dataclass(frozen=True)
class Notice:
    id: int
    level: str
    title_vi: str
    body_vi: str
    title_en: str
    body_en: str
    editions: str
    min_version: str
    max_version: str
    condition: str
    link: Link | None
    starts_at: datetime | None
    ends_at: datetime | None

    def text(self, english: bool) -> tuple[str, str]:
        """(title, body) in English when wanted and written, else Vietnamese."""

        if english and self.title_en and self.body_en:
            return self.title_en, self.body_en
        return self.title_vi, self.body_vi

    def link_label(self, english: bool) -> str:
        if self.link is None:
            return ""
        return self.link.label_en if english and self.link.label_en else self.link.label_vi


def link_allowed(value: str) -> bool:
    """https on vietnamlinuxfamily.net or one of its subdomains, without a user or a password: as the server checks."""

    try:
        parts = urlsplit(value)
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    return (parts.scheme == "https" and not parts.username and not parts.password
            and (host == "vietnamlinuxfamily.net" or host.endswith(".vietnamlinuxfamily.net")))


def version_key(version: str) -> tuple[int, ...] | None:
    return tuple(int(part) for part in version.split(".")) if _VERSION.match(version or "") else None


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _string(mapping: Any, key: str, limit: int) -> str | None:
    value = mapping.get(key, "") if isinstance(mapping, Mapping) else None
    if not isinstance(value, str) or len(value) > limit:
        return None
    return value.strip()


def parse_notice(item: Any) -> Notice | None:
    """One notice of the list, checked; None when anything is wrong with it (the others still count)."""

    if not isinstance(item, Mapping):
        return None
    ident = item.get("id")
    if not isinstance(ident, int) or isinstance(ident, bool) or ident <= 0:
        return None
    level = item.get("level")
    editions = item.get("editions", "all")
    condition = item.get("condition", "all")
    if level not in LEVELS or editions not in EDITIONS or condition not in CONDITIONS:
        return None
    title, body = item.get("title"), item.get("body")
    title_vi, title_en = _string(title, "vi", LIMITS["title"]), _string(title, "en", LIMITS["title"])
    body_vi, body_en = _string(body, "vi", LIMITS["body"]), _string(body, "en", LIMITS["body"])
    if not title_vi or not body_vi or title_en is None or body_en is None:
        return None
    bounds = []
    for key in ("min_version", "max_version"):
        value = item.get(key, "")
        if not isinstance(value, str) or (value and version_key(value) is None):
            return None
        bounds.append(value)
    link = None
    raw_link = item.get("link")
    if raw_link is not None:
        if not isinstance(raw_link, Mapping):
            return None
        url = raw_link.get("url")
        label = raw_link.get("label")
        label_vi, label_en = _string(label, "vi", LIMITS["label"]), _string(label, "en", LIMITS["label"])
        if (not isinstance(url, str) or len(url) > LIMITS["url"] or not link_allowed(url) or not label_vi
                or label_en is None):
            return None
        link = Link(url, label_vi, label_en)
    return Notice(ident, level, title_vi, body_vi, title_en or "", body_en or "", editions, bounds[0], bounds[1],
                  condition, link, _time(item.get("starts_at")), _time(item.get("ends_at")))


def parse(document: Any) -> list[Notice]:
    if not isinstance(document, Mapping) or document.get("schema") != 1 or not isinstance(document.get("notices"), list):
        return []
    notices = [parse_notice(item) for item in document["notices"]]
    return [notice for notice in notices if notice is not None]


Opener = Callable[..., Any]


def url() -> str:
    """The address; CARAMOS_OTA_NOTICES_URL replaces it on a test computer, as CARAMOS_OTA_STATS_URL does for the count."""

    return os.environ.get("CARAMOS_OTA_NOTICES_URL") or URL


def fetch(address: str | None = None, opener: Opener | None = None) -> list[Notice]:
    """The notices that are on; raises OSError (urllib's errors among them) or ValueError when they cannot be read."""

    request = urllib.request.Request(address or url(), headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with (opener or urllib.request.urlopen)(request, timeout=TIMEOUT_SECONDS) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("the list of notices is too large")
    return parse(json.loads(data.decode("utf-8")))


# ---------------------------------------------------------------------------------------------------------------------
# This computer


@dataclass(frozen=True)
class Computer:
    version: str
    edition: str
    update_waiting: bool
    update_failing: bool


def release_version(path: Path = RELEASE_FILE) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "VERSION":
                return value.strip().strip('"').strip("'")
    except (OSError, UnicodeDecodeError):
        pass
    return ""


def _uptime(path: Path = Path("/proc/uptime")) -> timedelta:
    try:
        return timedelta(seconds=float(path.read_text(encoding="utf-8").split()[0]))
    except (OSError, ValueError, IndexError):
        return timedelta(0)


def update_state(state: Mapping[str, Any], now: datetime, uptime: timedelta) -> tuple[bool, bool]:
    """(an update waiting, updates failing) from the OTA's state.json."""

    waiting = bool(state.get("available_update"))
    last_try = state.get(AUTO_UPDATE_RESULT_KEY)
    failing = isinstance(last_try, Mapping) and last_try.get("outcome") == "failed"
    if not failing and uptime >= UP_AT_LEAST:
        last_check = _time(state.get("last_check"))
        failing = last_check is None or now - last_check > FAILING_AFTER
    return waiting, failing


def this_computer(now: datetime | None = None, state_file: Path = STATE_FILE, release_file: Path = RELEASE_FILE,
                  uptime: timedelta | None = None) -> Computer:
    from caramos_ota_update.desktop import current_desktop

    now = now or datetime.now(timezone.utc)
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if not isinstance(state, Mapping):
        state = {}
    waiting, failing = update_state(state, now, _uptime() if uptime is None else uptime)
    return Computer(release_version(release_file), current_desktop(), waiting, failing)


def applies(notice: Notice, computer: Computer, now: datetime) -> bool:
    if notice.starts_at and now < notice.starts_at:
        return False
    if notice.ends_at and now >= notice.ends_at:
        return False
    if notice.editions != "all" and notice.editions != computer.edition:
        return False
    if notice.min_version or notice.max_version:
        mine = version_key(computer.version)
        if mine is None:
            return False
        if notice.min_version and mine < (version_key(notice.min_version) or ()):
            return False
        if notice.max_version and mine > (version_key(notice.max_version) or ()):
            return False
    if notice.condition == "update-waiting":
        return computer.update_waiting
    if notice.condition == "update-failing":
        return computer.update_failing
    return True


# ---------------------------------------------------------------------------------------------------------------------
# What each user has seen


def seen_file(environ: Mapping[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    base = env.get("XDG_STATE_HOME") or str(Path(env.get("HOME") or Path.home()) / ".local" / "state")
    return Path(base) / "caramos-ota" / "notices.json"


def read_seen(path: Path) -> set[int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    seen = data.get("seen") if isinstance(data, Mapping) else None
    return {item for item in seen if isinstance(item, int)} if isinstance(seen, list) else set()


def mark_seen(path: Path, notice_id: int) -> None:
    seen = read_seen(path) | {notice_id}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"seen": sorted(seen)}) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def pending(notices: list[Notice], computer: Computer, seen: set[int], now: datetime) -> list[Notice]:
    """The notices to show now: meant for this computer, not seen by this user; the most urgent first."""

    order = {level: index for index, level in enumerate(reversed(LEVELS))}
    chosen = [notice for notice in notices if notice.id not in seen and applies(notice, computer, now)]
    return sorted(chosen, key=lambda notice: (order[notice.level], notice.id))

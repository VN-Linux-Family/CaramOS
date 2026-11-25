"""How many CaramOS computers are in use each day: once a day, the daily check tells the CaramOS site that this
computer is on. The id it sends changes every day, so the days of one computer cannot be linked, and no computer can
be told apart from another.

What is sent
    POST URL with the JSON {"id": ..., "version": "1.5.2", "edition": "cinnamon" | "xfce"}: id is the hex SHA-256 of
    /etc/machine-id + ":" + the day (YYYY-MM-DD, UTC) + ":caramos-active", version the CaramOS version, edition the
    desktop. Nothing else: no host name, user, address or hardware. The site answers 204 (or 200).

When
    `caramos-ota --check`, which caramos-ota-check.service runs every day as root (and the Update Center when someone
    opens it), calls daily() first: at most once per UTC day (LAST_FILE keeps the last day that was counted), with a
    short timeout. A failure is only logged; the next check tries again. Not on the live USB, whose machine-id is new
    at every start.

The setting
    SETTINGS_FILE (/etc/caramos-ota/stats.conf) with STATS=no turns it off; `sudo caramos-ota --stats on|off` writes it,
    as `--auto-update on|off` writes /etc/caramos-ota/auto-update.conf. Without the file, or with a value it cannot
    read: on.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from .constants import STATE_DIR
from .logging_utils import log_info

URL = "https://caramos.vietnamlinuxfamily.net/api/active"
SETTINGS_FILE = Path("/etc/caramos-ota/stats.conf")
SETTING = "STATS"
SETTINGS_TEXT = """\
# CaramOS counts the computers in use each day: the daily check sends a number that changes every day, the CaramOS
# version and the edition, nothing else. no: send nothing. Change it with: sudo caramos-ota --stats on|off
{key}={value}
"""
LAST_FILE = STATE_DIR / "stats.json"
MACHINE_ID = Path("/etc/machine-id")
SALT = "caramos-active"
TIMEOUT_SECONDS = 5
EDITIONS = ("cinnamon", "xfce")
ACCEPTED = (200, 201, 202, 204)

# How daily() ended.
OFF = "off"
LIVE = "live"
ALREADY = "already"
SENT = "sent"
FAILED = "failed"
NO_ID = "no-machine-id"
OTHER_DESKTOP = "other-desktop"

Post = Callable[[str, bytes, float], int]


# The setting ------------------------------------------------------------------------------------------------------


def read_setting(path: Path | None = None) -> bool | None:
    """STATS of the settings file: True, False, or None without the file or a clear value."""

    try:
        text = (path or SETTINGS_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    value = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        if key.strip() != SETTING:
            continue
        word = raw.strip().strip("\"'").strip().lower()
        value = True if word in ("yes", "true", "on", "1") else False if word in ("no", "false", "off", "0") else None
    return value


def is_enabled(path: Path | None = None) -> bool:
    return read_setting(path) is not False


def set_enabled(enabled: bool, path: Path | None = None) -> None:
    """Write the setting (root): a new file renamed over the old one, readable by everyone."""

    path = path or SETTINGS_FILE
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(SETTINGS_TEXT.format(key=SETTING, value="yes" if enabled else "no"))
        os.replace(staging, path)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise


def change_setting(enabled: bool, by: str, path: Path | None = None) -> None:
    set_enabled(enabled, path)
    log_info(f"Daily count of computers in use turned {'on' if enabled else 'off'} by {by}")


# The count --------------------------------------------------------------------------------------------------------


def today(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%d")


def machine_id(path: Path | None = None) -> str:
    try:
        return (path or MACHINE_ID).read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def daily_id(machine: str, day: str) -> str:
    """The id of this computer for one day: the next day's cannot be told from another computer's."""

    return hashlib.sha256(f"{machine}:{day}:{SALT}".encode("utf-8")).hexdigest()


def body(machine: str, day: str, version: str, edition: str) -> bytes:
    return json.dumps({"id": daily_id(machine, day), "version": version, "edition": edition},
                      separators=(",", ":")).encode("utf-8")


def last_day(path: Path | None = None) -> str:
    try:
        data = json.loads((path or LAST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return ""
    return str(data.get("last_sent") or "") if isinstance(data, dict) else ""


def remember(day: str, path: Path | None = None) -> None:
    path = path or LAST_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o644)
            json.dump({"last_sent": day}, handle)
            handle.write("\n")
        os.replace(staging, path)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise


def url() -> str:
    """The address; CARAMOS_OTA_STATS_URL replaces it in tests on a test computer."""

    return os.environ.get("CARAMOS_OTA_STATS_URL") or URL


def post(address: str, data: bytes, timeout: float) -> int:
    """POST the JSON, without cookies or anything about the computer in the headers: the HTTP status."""

    request = urllib.request.Request(address, data=data, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "caramos-ota"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code


def daily(version: str, edition: str, *, now: datetime | None = None, sender: Post | None = None,
          settings: Path | None = None, last: Path | None = None, machine: Path | None = None,
          live: Callable[[], bool] | None = None) -> str:
    """Count this computer for today, once (the daily check): how it ended (SENT, ALREADY, OFF, FAILED...)."""

    if not is_enabled(settings):
        return OFF
    if live is None:
        from .auto_update import live_session as live
    if live():
        return LIVE
    day = today(now)
    if last_day(last) == day:
        return ALREADY
    if edition not in EDITIONS:
        return OTHER_DESKTOP
    identity = machine_id(machine)
    if not identity:
        return NO_ID
    try:
        status = (sender or post)(url(), body(identity, day, version, edition), TIMEOUT_SECONDS)
    except Exception as exc:   # noqa: BLE001 - no network, a timeout, a broken answer: the next check tries again
        log_info(f"Daily count: not sent ({exc.__class__.__name__}); the next check tries again")
        return FAILED
    if status not in ACCEPTED:
        log_info(f"Daily count: the site answered {status}; the next check tries again")
        return FAILED
    try:
        remember(day, last)
    except OSError:
        pass
    log_info(f"Daily count: this computer counted for {day}")
    return SENT


def run_from_check(version: str) -> None:
    """daily() for `caramos-ota --check`: never stops the check."""

    try:
        from caramos_ota_update.desktop import current_desktop

        daily(version, current_desktop())
    except Exception as exc:   # noqa: BLE001 - counting must never cost the check
        log_info(f"Daily count: skipped ({exc.__class__.__name__})")


def status_lines() -> list[str]:
    """For `caramos-ota --status`."""

    sent = last_day()
    return [f"Daily count:          {'on' if is_enabled() else 'off'}" + (f", last counted {sent}" if sent else "")]

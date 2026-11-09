"""What the user has already been told, so the check speaks up once per problem and not at every login.

The first check (first login after installing, every boot of the live USB because its home is in RAM,
and the first login after the OTA update that brings Driver Check) opens the window, also when everything
works: people trying CaramOS want to see that their hardware does. Later logins stay quiet unless a new
problem shows up (new hardware, a kernel update that broke a driver) or a known one is gone. A problem of a
device that is no longer plugged in (a printer, a Wi-Fi stick) is not gone, only away: it is neither told as
solved nor told again when the device comes back.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

from .analysis import CRITICAL, Finding, Report

STATE_NAME = "caramos-driver-check/state.json"

# What the autostart run does.
QUIET = "quiet"
SHOW_WINDOW = "window"
NOTIFY_PROBLEMS = "problems"
NOTIFY_RESOLVED = "resolved"


def state_path(environ: dict[str, str] | None = None) -> Path:
    env = os.environ if environ is None else environ
    config = env.get("XDG_CONFIG_HOME") or str(Path(env.get("HOME") or Path.home()) / ".config")
    return Path(config) / STATE_NAME


@dataclass
class UserState:
    first_check_done: bool = False
    seen: set[str] = field(default_factory=set)   # problems the user has been told about


def load(path: Path) -> UserState:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return UserState()
    if not isinstance(data, dict):
        return UserState()
    seen = data.get("seen")
    return UserState(
        first_check_done=data.get("first_check_done") is True,
        seen={key for key in seen if isinstance(key, str)} if isinstance(seen, list) else set(),
    )


def save(path: Path, state: UserState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"first_check_done": state.first_check_done, "seen": sorted(state.seen)}, indent=2)
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".json")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload + "\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class Decision:
    action: str
    new: tuple[Finding, ...] = ()      # problems the user has not been told about
    resolved: tuple[str, ...] = ()     # problems from earlier checks that are gone


def device_key(key: str) -> str:
    """The device a problem is about: "usb:04a9:2676" for "printer:capt:usb:04a9:2676", "" for "network:none"."""

    parts = key.split(":", 2)
    return parts[2] if len(parts) == 3 else ""


def away(key: str, present: Collection[str] | None) -> bool:
    """The problem's device is not in the computer now (Device.key not in present): unplugged, not fixed.

    present=None: the devices are not known, so every problem that is gone counts as solved."""

    device = device_key(key)
    return present is not None and bool(device) and device not in present


def decide(report: Report, state: UserState, present: Collection[str] | None = None) -> Decision:
    """What the autostart run shows for this report, given what the user was told before.

    present: the keys of the devices in the computer now (Snapshot.devices)."""

    problems = {finding.key: finding for finding in report.problems}
    if not state.first_check_done:
        return Decision(SHOW_WINDOW, new=tuple(problems.values()))
    new = tuple(finding for key, finding in problems.items() if key not in state.seen)
    resolved = tuple(sorted(key for key in state.seen if key not in problems and not away(key, present)))
    if any(finding.level == CRITICAL for finding in new):
        return Decision(SHOW_WINDOW, new=new, resolved=resolved)
    if new:
        return Decision(NOTIFY_PROBLEMS, new=new, resolved=resolved)
    if resolved:
        return Decision(NOTIFY_RESOLVED, resolved=resolved)
    return Decision(QUIET)


def remember(report: Report, state: UserState, present: Collection[str] | None = None) -> UserState:
    """The state after the user has been shown this report; problems of unplugged devices stay known."""

    kept = {key for key in state.seen if away(key, present)}
    return UserState(first_check_done=True, seen={finding.key for finding in report.problems} | kept)

"""Logging helpers for CaramOS OTA."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from .constants import LOG_DIR

_log_file: Path | None = None


def now_iso() -> str:
    """Return the current local time in ISO-8601 format."""

    return datetime.now().astimezone().isoformat()


def init_log() -> None:
    """Initialize the daily OTA log file."""

    global _log_file
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    _log_file = LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"


def current_log_file() -> Path | None:
    """Return the active log file path, if logging has been initialized."""

    return _log_file


def log(level: str, message: str) -> None:
    """Write one OTA log line and mirror warnings/errors to stderr."""

    line = f"{now_iso()} [{level}] {message}"
    if _log_file is not None:
        with _log_file.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    if level in {"ERROR", "WARN"}:
        print(line, file=sys.stderr)


def log_info(message: str) -> None:
    log("INFO", message)


def log_warn(message: str) -> None:
    log("WARN", message)


def log_error(message: str) -> None:
    log("ERROR", message)


def print_ok(message: str) -> None:
    print(f"[✓] {message}")


def print_fail(message: str) -> None:
    print(f"[✗] {message}")

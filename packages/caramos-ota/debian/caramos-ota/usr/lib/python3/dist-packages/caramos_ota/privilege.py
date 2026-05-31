"""Root privilege and process locking helpers."""

from __future__ import annotations

import fcntl
import os
from typing import TextIO

from .constants import EXIT_LOCK, EXIT_NOT_ROOT, LOCK_FILE, STATE_DIR, TOOL_NAME
from .logging_utils import log_error, log_info

_lock_handle: TextIO | None = None


def require_root() -> None:
    """Exit when the current process is not running as root."""

    if os.geteuid() != 0:
        print("Error: This command requires root privileges.")
        print(f"Please run: sudo {TOOL_NAME}")
        raise SystemExit(EXIT_NOT_ROOT)


def acquire_lock() -> None:
    """Acquire the global OTA lock or exit with EXIT_LOCK."""

    global _lock_handle
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _lock_handle = LOCK_FILE.open("w", encoding="utf-8")
    try:
        fcntl.flock(_lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Error: Another CaramOS OTA operation is already running.")
        print("Please wait for it to finish, then try again.")
        log_error(f"Could not acquire lock: {LOCK_FILE}")
        raise SystemExit(EXIT_LOCK)
    log_info(f"Lock acquired: {LOCK_FILE}")

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


def acquire_lock(inherited_fd: int | None = None) -> int:
    """Acquire the global OTA lock or reuse a lock inherited from the parent."""

    global _lock_handle
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if inherited_fd is None:
        handle = LOCK_FILE.open("w", encoding="utf-8")
    else:
        try:
            lock_stat = LOCK_FILE.stat()
            inherited_stat = os.fstat(inherited_fd)
        except (OSError, ValueError) as exc:
            log_error(f"Invalid inherited OTA lock descriptor: {exc}")
            raise SystemExit(EXIT_LOCK) from exc
        if (inherited_stat.st_dev, inherited_stat.st_ino) != (lock_stat.st_dev, lock_stat.st_ino):
            log_error("Inherited OTA lock descriptor does not match the global lock file")
            raise SystemExit(EXIT_LOCK)
        handle = os.fdopen(inherited_fd, "w", encoding="utf-8", closefd=False)

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        print("Error: Another CaramOS OTA operation is already running.")
        print("Please wait for it to finish, then try again.")
        log_error(f"Could not acquire lock: {LOCK_FILE}")
        raise SystemExit(EXIT_LOCK)
    _lock_handle = handle
    log_info(f"Lock acquired: {LOCK_FILE}")
    return handle.fileno()


def current_lock_fd() -> int:
    """Return the descriptor for the lock held by this process."""

    if _lock_handle is None:
        raise RuntimeError("CaramOS OTA lock has not been acquired")
    return _lock_handle.fileno()

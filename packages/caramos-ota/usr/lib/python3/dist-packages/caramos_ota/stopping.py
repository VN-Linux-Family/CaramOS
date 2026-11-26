"""An install finishes before the program stops.

At shutdown, systemd stops the daily check's unit (caramos-ota-check.service). With KillMode=mixed it sends SIGTERM
to caramos-ota alone, not to the apt-get and dpkg it runs, and waits up to the unit's TimeoutStopSec. caramos-ota then
waits until its install is done and only stops afterwards. With the default KillMode, systemd sent SIGTERM to dpkg too:
dpkg stopped half-way left its journal behind, and from then on APT refused every install ("dpkg was interrupted"),
so the computer got no update and the App Center installed nothing (tickets H-1218, H-1221).
"""

from __future__ import annotations

import signal
from collections.abc import Iterator
from contextlib import contextmanager

from .logging_utils import log_warn

# The exit status of a program that stopped on SIGTERM.
EXIT_STOPPED = 128 + signal.SIGTERM


@contextmanager
def finishing_before_stopping(what: str) -> Iterator[None]:
    """SIGTERM during the block waits until the block is done; the program then stops (SystemExit EXIT_STOPPED)."""

    asked: list[int] = []

    def wait(signum: int, _frame: object) -> None:
        if not asked:
            log_warn(f"Asked to stop while {what}; finishing first")
        asked.append(signum)

    try:
        previous = signal.signal(signal.SIGTERM, wait)
    except ValueError:
        # Not the main thread, where Python cannot take signals: the block runs as it would have.
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
    if asked:
        log_warn(f"Stopping now that {what} is done")
        raise SystemExit(EXIT_STOPPED)

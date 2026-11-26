"""Veyon Server back within half a minute when it is gone, on a Phòng máy computer with Veyon.

veyon-service runs one veyon-server, for the session on screen. Veyon 4.7.5 (Ubuntu 24.04) does not start it again
when it exits: after its X display went away, or when the lock screen's session closed before logind said so (checked
in a VM lab on 2026-11-25: 3 of 7 lock/unlock rounds of an Xfce student ended with no server). Veyon Master then shows
that computer as an orange screen ("Veyon Server unreachable or not running") until the student's computer
restarts, and a teacher's computer without its server cannot show its screen (Demo). Veyon 4.11.5, which the CaramOS
PPA has since November 2026, starts its server again by itself (checked in a VM lab on 2026-11-26: 6 lock/unlock rounds
of an Xfce student and a killed x11vnc, with this timer stopped); the timer stays as a backstop.

caramos-lab-veyon-check.timer runs this every 30 seconds where the lab helper set up Veyon (teacher's and students'
computers). When a graphical session is on screen and nothing listens on Veyon Server's port for SETTLE seconds, it
restarts veyon.service, which starts a server for that session. Switching sessions (lock screen, login) takes Veyon a
few seconds; that is why it looks again before restarting. Messages below notice level are not logged
(LogLevelMax=notice in the unit): the journal only gets the restarts.
"""

from __future__ import annotations

import subprocess
import sys
import time
from typing import Callable

from . import VEYON
from . import system

SERVICE = "veyon.service"
SERVER_PORT = 11100  # Network/VeyonServerPort, single-session mode
SETTLE = 9  # seconds a server may be missing while Veyon switches sessions
CHECK_INTERVAL = 3

Runner = Callable[[list[str]], subprocess.CompletedProcess]


def run_command(command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, capture_output=True, text=True, check=False, timeout=30)
    except (OSError, subprocess.SubprocessError) as error:
        return subprocess.CompletedProcess(command, 127, "", str(error))


def properties(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def session_on_screen(run: Runner, seat: str = "seat0") -> str | None:
    """The X11 session shown on the seat (the student's, or the login/lock screen's), if any."""

    seat_info = properties(run(["loginctl", "show-seat", seat, "-p", "ActiveSession"]).stdout)
    session = seat_info.get("ActiveSession", "").strip()
    if not session:
        return None
    info = properties(run(["loginctl", "show-session", session, "-p", "Type", "-p", "State"]).stdout)
    if info.get("Type") == "x11" and info.get("State") in ("active", "online"):
        return session
    return None


def server_listening(run: Runner, port: int = SERVER_PORT) -> bool:
    result = run(["ss", "-Hltn", "sport", "=", f":{port}"])
    return result.returncode == 0 and bool(result.stdout.strip())


def service_enabled(run: Runner) -> bool:
    return run(["systemctl", "is-enabled", SERVICE]).stdout.strip() == "enabled"


def check(state: dict, run: Runner = run_command, sleep: Callable[[float], None] = time.sleep) -> str:
    """Look once (and again for a while when the server is missing); restart veyon.service when it stays missing."""

    if state.get("backend") != VEYON:
        return "not a Veyon computer of the lab"
    if not service_enabled(run):
        return f"{SERVICE} is not enabled: left alone"
    waited = 0
    while True:
        session = session_on_screen(run)
        if session is None:
            return "no graphical session on screen"
        if server_listening(run):
            return f"Veyon Server is running for session {session}"
        if waited >= SETTLE:
            break
        sleep(CHECK_INTERVAL)
        waited += CHECK_INTERVAL
    run(["systemctl", "restart", SERVICE])
    return f"restarted {SERVICE}: no Veyon Server for session {session} for {SETTLE} seconds"


def main(argv: list[str] | None = None) -> int:
    message = check(system.read_state())
    # "<5>": notice for the journal (systemd's level prefix), so that LogLevelMax=notice keeps only the restarts.
    level = "<5>" if message.startswith("restarted") else "<6>"
    print(level + message, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

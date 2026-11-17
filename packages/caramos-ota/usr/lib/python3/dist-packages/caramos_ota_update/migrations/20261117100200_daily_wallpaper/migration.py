"""Start the daily photo of Vietnam in the sessions that are open now.

This package brings three things the Update Center would not list otherwise, so this migration's notes tell
them: the daily wallpaper (caramos-daily-wallpaper, a systemd user timer), the accent colour of the Control
Center (schema net.vietnamlinuxfamily.caramos.control-center) and the GRUB menu after a failed boot
(caramos-boot-success.timer).

The package enables the user timer for everyone (/etc/systemd/user/timers.target.wants), but a user service
manager that is already running only sees it after a reload: here each logged-in user's manager is reloaded and
the timer started, so the "Việt Nam mỗi ngày" folder shows up in System Settings > Backgrounds today, not after
the next login. A user without a running manager (logged out, the ISO build) gets it at their next login. A
failure is logged and does not stop the update.
"""

from __future__ import annotations

import os
import pwd
import subprocess
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Start the daily photo of Vietnam in the open sessions"

TIMER = "caramos-daily-wallpaper.timer"
TIMER_FILE = Path("/usr/lib/systemd/user") / TIMER
RUNTIME_ROOT = Path("/run/user")


def _desktop_users() -> list[tuple[str, int]]:
    users = []
    for entry in pwd.getpwall():
        if 1000 <= entry.pw_uid < 60000 and not entry.pw_shell.endswith(("/nologin", "/false")):
            users.append((entry.pw_name, entry.pw_uid))
    return sorted(users, key=lambda item: item[1])


def _user_manager_running(uid: int) -> bool:
    return (RUNTIME_ROOT / str(uid) / "systemd/private").exists()


def _systemctl(username: str, uid: int, *args: str) -> subprocess.CompletedProcess[str]:
    runtime = RUNTIME_ROOT / str(uid)
    env = {"PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"), "XDG_RUNTIME_DIR": str(runtime),
           "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus"}
    return subprocess.run(["runuser", "-u", username, "--", "systemctl", "--user", *args], check=False,
                          capture_output=True, text=True, env=env)


def run(context: MigrationContext) -> None:
    if not TIMER_FILE.exists():
        context.log(f"{TIMER_FILE} is missing; nothing to start")
        return
    for username, uid in _desktop_users():
        if not _user_manager_running(uid):
            continue
        if context.dry_run:
            context.log(f"start {TIMER} for {username}")
            continue
        reload = _systemctl(username, uid, "daemon-reload")
        start = _systemctl(username, uid, "start", TIMER) if reload.returncode == 0 else reload
        if start.returncode == 0:
            context.log(f"started {TIMER} for {username}")
        else:
            context.log(f"could not start {TIMER} for {username} ({start.stderr.strip()[:160]}); it starts at the next login")

"""Files (Nemo): right-click > "Mới" > "Thư mục", like Windows and the Tin học textbooks.

The package does the work: /usr/share/caramos-ota/nemo-menu/caramos-nemo-menu writes the changed menus (run by
postinst and again here, which also covers the ISO build), /etc/X11/Xsession.d/85caramos-nemo-menu points Nemo at
them from the next login, and caramos-templates.timer puts the Word, Excel and PowerPoint templates into each
user's Templates folder once. This migration starts that timer in the sessions that are open now, so the
templates are there before the next login, and its notes tell users about the menu. A failure is logged and does
not stop the update.
"""

from __future__ import annotations

import os
import pwd
import subprocess
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Files: right-click > New > Folder, and the document templates"

MENU = Path("/usr/share/caramos-ota/nemo-menu/caramos-nemo-menu")
TIMER = "caramos-templates.timer"
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
    if context.dry_run:
        context.log(f"run {MENU}; start {TIMER} in the open sessions")
        return
    if MENU.exists():
        result = subprocess.run([str(MENU)], check=False, capture_output=True, text=True)
        context.log((result.stdout or result.stderr).strip()[:300] or f"{MENU} exited {result.returncode}")
    else:
        context.log(f"{MENU} is missing; Nemo keeps its own menus")
    if not TIMER_FILE.exists():
        context.log(f"{TIMER_FILE} is missing; no templates")
        return
    for username, uid in _desktop_users():
        if not _user_manager_running(uid):
            continue
        reload = _systemctl(username, uid, "daemon-reload")
        start = _systemctl(username, uid, "start", TIMER) if reload.returncode == 0 else reload
        if start.returncode == 0:
            context.log(f"started {TIMER} for {username}")
        else:
            context.log(f"could not start {TIMER} for {username} ({start.stderr.strip()[:160]}); it starts at the next login")

"""Stop the Lotus enable service from deadlocking boot.

Migration v1_0_12 added caramos-fcitx5-lotus-system-enable.service, a oneshot pulled in by
multi-user.target that runs `systemctl enable --now fcitx5-lotus-server@USER.service` for each desktop
user. That unit is ordered After=multi-user.target, and `systemctl --now` waits for its start job, so
multi-user.target waits for the oneshot, the oneshot waits for the server and the server waits for
multi-user.target. Oneshots have no start timeout: the system stays "starting" forever, the Lotus
server never runs, and any later `systemctl start` of a unit ordered after multi-user.target (for
example a package postinst) hangs.

The helper now queues the start with --no-block. ISOs built with sudo also enabled the server for
the build machine's user (SUDO_USER, e.g. "dungleviet" or CI's "runner"), an account that does not
exist on installed systems; those links are removed. On a running system the stuck oneshot from
this boot is stopped so boot can finish and the queued Lotus servers start.
"""

from __future__ import annotations

import os
import pwd
import tempfile
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Fix the Lotus enable service that keeps boot from finishing"

SYSTEM_ENABLE_HELPER = Path("/usr/local/sbin/caramos-fcitx5-lotus-system-enable")
SYSTEM_ENABLE_SERVICE = Path("/etc/systemd/system/caramos-fcitx5-lotus-system-enable.service")
SERVICE_NAME = SYSTEM_ENABLE_SERVICE.name
WANTS_DIR = Path("/etc/systemd/system/multi-user.target.wants")
SERVER_PREFIX = "fcitx5-lotus-server@"
SYSTEMD_RUNTIME = Path("/run/systemd/system")

SYSTEM_ENABLE_HELPER_SCRIPT = r'''#!/bin/sh
set -eu

TEMPLATE_UNIT="/lib/systemd/system/fcitx5-lotus-server@.service"

[ -f "$TEMPLATE_UNIT" ] || [ -f "/etc/systemd/system/fcitx5-lotus-server@.service" ] || exit 0
command -v systemctl >/dev/null 2>&1 || exit 0

while IFS=: read -r user _ uid _ _ home shell; do
    [ "$uid" -ge 1000 ] 2>/dev/null || continue
    [ "$uid" -lt 60000 ] 2>/dev/null || continue
    [ -d "$home" ] || continue
    case "$home" in
        /home/*) ;;
        *) continue ;;
    esac
    case "$shell" in
        */nologin|*/false) continue ;;
    esac

    # --no-block: fcitx5-lotus-server@ is ordered After=multi-user.target, which waits for this
    # oneshot. Waiting for the start job here deadlocks boot.
    if ! systemctl enable --now --no-block "fcitx5-lotus-server@${user}.service" >/dev/null 2>&1; then
        echo "caramos-fcitx5-lotus-system-enable: failed to enable service for ${user}" >&2
    fi
done < /etc/passwd
'''

SYSTEM_ENABLE_SERVICE_CONFIG = """[Unit]
Description=Enable Fcitx5 Lotus server for CaramOS desktop users
After=systemd-user-sessions.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/caramos-fcitx5-lotus-system-enable
# Safety net: a oneshot has no start timeout by default and blocks multi-user.target.
TimeoutStartSec=90

[Install]
WantedBy=multi-user.target
"""


def _write_if_changed(context: MigrationContext, path: Path, content: str, mode: int) -> bool:
    if path.is_file() and path.read_text(encoding="utf-8") == content and path.stat().st_mode & 0o777 == mode:
        context.log(f"file unchanged: {path}")
        return False
    context.log(f"write {path}")
    if context.dry_run:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(staging, mode)
        os.replace(staging, path)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise
    return True


def _user_exists(name: str) -> bool:
    try:
        pwd.getpwnam(name)
    except KeyError:
        return False
    return True


def _remove_stale_server_links(context: MigrationContext) -> list[str]:
    removed: list[str] = []
    if not WANTS_DIR.is_dir():
        return removed
    for link in sorted(WANTS_DIR.glob(f"{SERVER_PREFIX}*.service")):
        user = link.name[len(SERVER_PREFIX):-len(".service")]
        if not link.is_symlink() or _user_exists(user):
            continue
        context.log(f"remove {link}: user {user!r} does not exist (leaked from the ISO build machine)")
        removed.append(link.name)
        if not context.dry_run:
            link.unlink()
    return removed


def _systemd_running() -> bool:
    return SYSTEMD_RUNTIME.is_dir()


def _unit_state(context: MigrationContext, unit: str) -> str:
    result = context.run_command(["systemctl", "show", "--property=ActiveState", "--value", unit], allow_fail=True)
    if result is None:
        return ""
    return (result.stdout or "").strip()


def run(context: MigrationContext) -> None:
    changed = _write_if_changed(context, SYSTEM_ENABLE_HELPER, SYSTEM_ENABLE_HELPER_SCRIPT, 0o755)
    changed = _write_if_changed(context, SYSTEM_ENABLE_SERVICE, SYSTEM_ENABLE_SERVICE_CONFIG, 0o644) or changed
    stale_units = _remove_stale_server_links(context)
    changed = changed or bool(stale_units)

    if not _systemd_running():
        context.log("systemd is not running (ISO build); the fixed service runs at first boot")
        return
    if changed:
        context.run_command(["systemctl", "daemon-reload"], allow_fail=True)

    # The oneshot started at this boot is still waiting on itself. Stopping it lets
    # multi-user.target finish; its queued fcitx5-lotus-server@ start jobs then run.
    # The daemon-reload above can already have stopped it: the new TimeoutStartSec applies to the
    # running job, which leaves the unit failed and the system "degraded" until reset.
    state = _unit_state(context, SERVICE_NAME)
    if state == "activating":
        context.log(f"stop {SERVICE_NAME}, stuck since boot")
        context.run_command(["systemctl", "kill", SERVICE_NAME], allow_fail=True)
    if state in {"activating", "failed"}:
        context.run_command(["systemctl", "reset-failed", SERVICE_NAME], allow_fail=True)

    # Their start jobs were queued at this boot and fail once boot can finish.
    for unit in stale_units:
        context.run_command(["systemctl", "stop", "--no-block", unit], allow_fail=True)
        context.run_command(["systemctl", "reset-failed", unit], allow_fail=True)

    context.run_command([str(SYSTEM_ENABLE_HELPER)], allow_fail=True)

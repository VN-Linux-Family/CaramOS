"""Start Fcitx 5 at every login, so Vietnamese typing works on new installs and on the live USB.

Two autostart entries declare X-GNOME-Provides=inputmethod: Fcitx's own org.fcitx.Fcitx5.desktop and
caramos-fcitx5-lotus-enable.desktop, the CaramOS Lotus login helper. Cinnamon's session runs only the first
of them it reads ("service 'inputmethod' is already provided") and reads /etc/xdg/autostart in directory
order: alphabetical on the live USB, where the helper always comes first, and on ext4 an order that changes
from one install to the next. Since migration 20261010120100 the helper restarts Fcitx only when one of the
CaramOS defaults differs from /etc/skel, trusting org.fcitx.Fcitx5.desktop to start it. Where the helper came
first and the user's files still matched /etc/skel, nothing started Fcitx: in every live session, and at
every login of a new install, whose Fcitx never ran and so never rewrote its profile. Lotus showed no "V" in
the tray and typing gave Telex letters without accents, from CaramOS 1.3.0 on.

The helper now also starts Fcitx when it is not running. The session still runs only one of the two entries,
so a computer whose org.fcitx.Fcitx5.desktop came first changes nothing. People logged in during the update
get Fcitx started in their session at once.
"""

from __future__ import annotations

import os
import pwd
import subprocess
import tempfile
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Start Fcitx 5 at every login so Vietnamese typing works"

SYSTEMD_RUNTIME = Path("/run/systemd/system")
PROC = Path("/proc")
LOGIN_HELPER = Path("/usr/local/bin/caramos-fcitx5-lotus-enable")
# Every CaramOS version of the helper (ISO hook 0150, migrations v1_0_12 and 20261010120100) copies these.
CARAMOS_HELPER_MARKER = "/etc/skel/.config/fcitx5"
LOGIN_HELPER_SCRIPT = r'''#!/bin/sh
set -eu

# Avoid competing input method daemons.
killall ibus-daemon >/dev/null 2>&1 || ibus exit >/dev/null 2>&1 || true

mkdir -p "${HOME}/.config/fcitx5/conf" "${HOME}/.config/environment.d"

# The CaramOS defaults apply at every login. This entry and org.fcitx.Fcitx5.desktop both provide
# "inputmethod", so the session runs only the one it reads first: Fcitx is started here when it is not
# running, and restarted when one of the defaults changed.
changed=0
install_default() {
    [ -f "$1" ] || return 0
    cmp -s "$1" "$2" 2>/dev/null && return 0
    cp -f "$1" "$2"
    changed=1
}
install_default /etc/skel/.config/fcitx5/config "${HOME}/.config/fcitx5/config"
install_default /etc/skel/.config/fcitx5/profile "${HOME}/.config/fcitx5/profile"
install_default /etc/skel/.config/fcitx5/conf/lotus.conf "${HOME}/.config/fcitx5/conf/lotus.conf"
install_default /etc/skel/.config/environment.d/90-fcitx5-lotus.conf "${HOME}/.config/environment.d/90-fcitx5-lotus.conf"

command -v fcitx5 >/dev/null 2>&1 || exit 0
if [ "$changed" = 1 ]; then
    fcitx5 -d --replace >/dev/null 2>&1 || true
elif ! pgrep -u "$(id -u)" -x fcitx5 >/dev/null 2>&1; then
    fcitx5 -d >/dev/null 2>&1 || true
fi
'''

# The process names (/proc/PID/comm, 15 characters) of a running Cinnamon session.
SESSION_PROCESSES = ("cinnamon", "cinnamon-sessio")
# What Fcitx needs from the session: the X display, the session bus, the language and the paths.
SESSION_VARIABLES = ("DISPLAY", "XAUTHORITY", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR", "HOME", "USER",
                     "LOGNAME", "PATH", "LANG", "LANGUAGE", "XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP",
                     "XDG_SESSION_DESKTOP", "XDG_DATA_DIRS", "XDG_CONFIG_DIRS", "XMODIFIERS")
START_TIMEOUT = 30


def _write_helper(context: MigrationContext, path: Path = LOGIN_HELPER) -> bool:
    return write_helper(context, path, LOGIN_HELPER_SCRIPT, "start Fcitx when it is not running")


def write_helper(context: MigrationContext, path: Path, script: str, change: str = "") -> bool:
    """Replace the CaramOS Lotus login helper at path with script; a script that is not CaramOS's stays."""

    if not path.is_file() or path.is_symlink():
        context.log(f"{path} is not installed")
        return False
    try:
        current = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        context.log(f"skip {path}: {exc}")
        return False
    if current == script:
        context.log(f"file unchanged: {path}")
        return False
    if CARAMOS_HELPER_MARKER not in current:
        context.log(f"skip {path}: not the CaramOS Lotus login helper")
        return False
    context.log(f"write {path}" + (f": {change}" if change else ""))
    if context.dry_run:
        return True
    fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(script)
        os.chmod(staging, 0o755)
        os.replace(staging, path)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise
    return True


def _desktop_users() -> list[pwd.struct_passwd]:
    """People who log in: not system users, nor the dynamic users of services such as earlyoom (uid 61184+)."""

    users = []
    for entry in pwd.getpwall():
        if not 1000 <= entry.pw_uid < 60000 or entry.pw_shell.endswith(("/nologin", "/false")):
            continue
        if entry.pw_dir not in ("", "/", "/nonexistent") and Path(entry.pw_dir).is_dir():
            users.append(entry)
    return sorted(users, key=lambda entry: entry.pw_uid)


def session_environment(uid: int, proc: Path = PROC) -> dict[str, str] | None:
    """The variables Fcitx needs, from the user's running Cinnamon session; None when they are not logged in."""

    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != uid or (entry / "comm").read_text(encoding="utf-8").strip() not in SESSION_PROCESSES:
                continue
            raw = (entry / "environ").read_bytes()
        except OSError:
            continue
        variables = dict(item.split("=", 1) for item in raw.decode("utf-8", errors="replace").split("\0") if "=" in item)
        if variables.get("DISPLAY") and variables.get("DBUS_SESSION_BUS_ADDRESS"):
            return {name: value for name, value in variables.items()
                    if name in SESSION_VARIABLES or name.startswith("LC_")}
    return None


def _fcitx_running(uid: int) -> bool:
    result = subprocess.run(["pgrep", "-u", str(uid), "-x", "fcitx5"], check=False, capture_output=True)
    return result.returncode == 0


def start_command(username: str, environment: dict[str, str]) -> list[str]:
    return ["runuser", "-u", username, "--", "env", "-i",
            *(f"{name}={value}" for name, value in sorted(environment.items())), "fcitx5", "-d"]


def start_in_session(context: MigrationContext, username: str, environment: dict[str, str]) -> bool:
    context.log(f"start Fcitx in the session of {username}")
    try:
        # No pipes: the daemon Fcitx forks would hold them open and this call would never return.
        result = subprocess.run(start_command(username, environment), check=False,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                start_new_session=True, timeout=START_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        context.log(f"warning: could not start Fcitx for {username}, it starts at the next login: {exc}")
        return False
    if result.returncode != 0:
        context.log(f"warning: Fcitx did not start for {username} (exit {result.returncode}), "
                    "it starts at the next login")
        return False
    return True


def _start_in_sessions(context: MigrationContext) -> None:
    for user in _desktop_users():
        environment = session_environment(user.pw_uid)
        if environment is None:
            continue
        if _fcitx_running(user.pw_uid):
            context.log(f"Fcitx is running for {user.pw_name}")
            continue
        start_in_session(context, user.pw_name, environment)


def run(context: MigrationContext) -> None:
    _write_helper(context)
    if context.dry_run:
        context.log("[dry-run] start Fcitx in the sessions of logged-in users that do not have it")
        return
    if not SYSTEMD_RUNTIME.is_dir():
        context.log("systemd is not running (ISO build); Fcitx starts at each login")
        return
    _start_in_sessions(context)

"""Keep the user's input method settings, and start every session typing Vietnamese.

Two faults of the CaramOS Lotus setup:

- The login helper caramos-fcitx5-lotus-enable copied the CaramOS defaults over ~/.config/fcitx5/config,
  profile and conf/lotus.conf whenever a file differed from /etc/skel. Fcitx and the Lotus settings window
  save every change in those files, so each login undid them: the typing method (VNI instead of Telex), the
  Lotus mode, spell checking, shortcuts (tickets H-1092, H-1093). The helper now copies a default only when
  the file is missing, as for a new account.
- The CaramOS profile listed Lotus before the keyboard layout. Fcitx uses the first input method of a group
  while it is inactive and the next one while active, and it starts active (ActiveByDefault in the CaramOS
  config), so every session started in English ("A" in the tray) and Ctrl+Shift turned Vietnamese on. People
  thought typing with accents was broken (ticket H-1104). The keyboard layout now comes first, as Fcitx
  expects: a session starts in Vietnamese ("V") and Ctrl+Shift switches to English.

The order changes in /etc/skel and in each profile that is still the CaramOS one (Lotus, then one keyboard
layout, no layout of their own); any other profile stays as it is. Fcitx writes its profile when it quits,
so for a logged-in user it is stopped first, the profile written, and Fcitx started again in their session.
"""

from __future__ import annotations

import importlib
import os
import pwd
import re
import signal
import tempfile
import time
from pathlib import Path

from caramos_ota_update.context import MigrationContext

start_fcitx = importlib.import_module("caramos_ota_update.migrations.20261022120000_start_fcitx_at_login.migration")

DESCRIPTION = "Keep input method settings and start every session typing Vietnamese"

SYSTEMD_RUNTIME = Path("/run/systemd/system")
LOGIN_HELPER = start_fcitx.LOGIN_HELPER
SKEL = Path("/etc/skel")
PROFILE = Path(".config/fcitx5/profile")
STOP_TIMEOUT = 10.0
LOGIN_HELPER_SCRIPT = r'''#!/bin/sh
set -eu

# Avoid competing input method daemons.
killall ibus-daemon >/dev/null 2>&1 || ibus exit >/dev/null 2>&1 || true

mkdir -p "${HOME}/.config/fcitx5/conf" "${HOME}/.config/environment.d"

# The CaramOS defaults, for a file that is missing (a new account). Fcitx and the Lotus settings window keep
# the user's own choices in these files, so a file that is there is never replaced.
added=0
install_default() {
    [ -f "$1" ] || return 0
    [ -e "$2" ] && return 0
    cp "$1" "$2"
    added=1
}
install_default /etc/skel/.config/fcitx5/config "${HOME}/.config/fcitx5/config"
install_default /etc/skel/.config/fcitx5/profile "${HOME}/.config/fcitx5/profile"
install_default /etc/skel/.config/fcitx5/conf/lotus.conf "${HOME}/.config/fcitx5/conf/lotus.conf"
install_default /etc/skel/.config/environment.d/90-fcitx5-lotus.conf "${HOME}/.config/environment.d/90-fcitx5-lotus.conf"

# This entry and org.fcitx.Fcitx5.desktop both provide "inputmethod", so the session runs only the one it
# reads first: Fcitx is started here when it is not running, and restarted when a default was added.
command -v fcitx5 >/dev/null 2>&1 || exit 0
if [ "$added" = 1 ]; then
    fcitx5 -d --replace >/dev/null 2>&1 || true
elif ! pgrep -u "$(id -u)" -x fcitx5 >/dev/null 2>&1; then
    fcitx5 -d >/dev/null 2>&1 || true
fi
'''

GROUP_RE = re.compile(r"Groups/\d+")
ITEM_RE = re.compile(r"Groups/0/Items/(\d+)")


def parse_profile(text: str) -> dict[str, dict[str, str]] | None:
    """The sections of a Fcitx profile (an INI file), None when it is not one."""

    sections: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
        elif current is not None and "=" in line:
            key, value = line.split("=", 1)
            current[key.strip()] = value.strip()
        else:
            return None
    return sections


def reordered_profile(text: str) -> str | None:
    """The CaramOS profile with the keyboard layout before Lotus; None for any other profile."""

    sections = parse_profile(text)
    if not sections:
        return None
    items = sorted((name for name in sections if ITEM_RE.fullmatch(name)), key=lambda name: int(ITEM_RE.fullmatch(name).group(1)))
    known = {"Groups/0", "GroupOrder", *items}
    if [name for name in sections if GROUP_RE.fullmatch(name)] != ["Groups/0"] or set(sections) != known:
        return None
    if items != ["Groups/0/Items/0", "Groups/0/Items/1"]:
        return None
    lotus, keyboard = sections["Groups/0/Items/0"], sections["Groups/0/Items/1"]
    if (lotus.get("Name") != "lotus" or not keyboard.get("Name", "").startswith("keyboard-")
            or lotus.get("Layout") or keyboard.get("Layout")):
        return None
    group = sections["Groups/0"]
    name = group.get("Name") or "Default"
    if sections["GroupOrder"] != {"0": name}:
        return None
    return (f"[Groups/0]\nName={name}\nDefault Layout={group.get('Default Layout', 'us')}\nDefaultIM=lotus\n\n"
            f"[Groups/0/Items/0]\nName={keyboard['Name']}\nLayout=\n\n"
            f"[Groups/0/Items/1]\nName=lotus\nLayout=\n\n"
            f"[GroupOrder]\n0={name}\n")


def _write_file(path: Path, content: str, owner: tuple[int, int] | None) -> None:
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(staging, mode)
        if owner is not None:
            os.chown(staging, *owner)
        # os.replace renames over the name without following it.
        os.replace(staging, path)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise


def _owned_file(base: Path, path: Path, uid: int) -> bool:
    """A regular file of the user, in their own folders: this runs as root in the user's home."""

    if path.is_symlink() or not path.is_file():
        return False
    folder = path.parent
    try:
        resolved = folder.resolve()
        return (not folder.is_symlink() and base.resolve() in resolved.parents and resolved.stat().st_uid == uid
                and path.stat().st_uid == uid)
    except OSError:
        return False


def new_profile(path: Path) -> str | None:
    try:
        return reordered_profile(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return None


def _fcitx_pids(uid: int, proc: Path = Path("/proc")) -> list[int]:
    pids = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid == uid and (entry / "comm").read_text(encoding="utf-8").strip() == "fcitx5":
                pids.append(int(entry.name))
        except OSError:
            continue
    return pids


def _stop(pids: list[int], timeout: float = STOP_TIMEOUT) -> bool:
    """Ask Fcitx to quit (it saves its profile then) and wait until it is gone."""

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not any(Path(f"/proc/{pid}").exists() for pid in pids):
            return True
        time.sleep(0.2)
    return False


def _update_user(context: MigrationContext, user: pwd.struct_passwd, systemd: bool) -> None:
    home = Path(user.pw_dir)
    path = home / PROFILE
    if not _owned_file(home, path, user.pw_uid):
        return
    if new_profile(path) is None:
        context.log(f"the input methods of {user.pw_name} are their own; leave them as they are")
        return
    environment = start_fcitx.session_environment(user.pw_uid) if systemd else None
    pids = _fcitx_pids(user.pw_uid) if systemd else []
    if context.dry_run:
        context.log(f"[dry-run] put the keyboard layout before Lotus in {path}")
        return
    if pids and not _stop(pids):
        context.log(f"warning: Fcitx of {user.pw_name} did not quit; their profile changes at the next login")
        return
    # Read again: Fcitx wrote its profile as it quit.
    content = new_profile(path) if _owned_file(home, path, user.pw_uid) else None
    if content is None:
        context.log(f"the input methods of {user.pw_name} are their own; leave them as they are")
    else:
        _write_file(path, content, (user.pw_uid, user.pw_gid))
        context.log(f"{user.pw_name} starts typing Vietnamese: keyboard layout before Lotus in {path}")
    if pids and environment is not None:
        start_fcitx.start_in_session(context, user.pw_name, environment)


def run(context: MigrationContext) -> None:
    start_fcitx.write_helper(context, LOGIN_HELPER, LOGIN_HELPER_SCRIPT)
    skel_profile = SKEL / PROFILE
    content = new_profile(skel_profile) if skel_profile.is_file() and not skel_profile.is_symlink() else None
    if content is not None:
        context.log(f"put the keyboard layout before Lotus in {skel_profile}")
        if not context.dry_run:
            _write_file(skel_profile, content, None)
    systemd = SYSTEMD_RUNTIME.is_dir()
    for user in start_fcitx._desktop_users():
        _update_user(context, user, systemd)

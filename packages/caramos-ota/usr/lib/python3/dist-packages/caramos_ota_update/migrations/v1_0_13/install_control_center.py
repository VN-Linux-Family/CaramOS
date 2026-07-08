"""Migration for 1.0.12: install CaramOS Control Center applet."""

from __future__ import annotations

import os
import pwd
import shutil
import subprocess
from pathlib import Path

from caramos_ota_update.context import MigrationContext

FROM_VERSION = "1.0.11"
TO_VERSION = "1.0.12"
DESCRIPTION = "Install CaramOS Control Center Cinnamon applet"

APPLET_UUID = "caramos-control-center@caramos"
SOURCE_APPLET_DIR = Path("/usr/share/caramos-ota/applets") / APPLET_UUID
TARGET_APPLET_DIR = Path("/usr/share/cinnamon/applets") / APPLET_UUID


def _install_applet(context: MigrationContext) -> None:
    if not SOURCE_APPLET_DIR.exists():
        context.log(f"warning: applet source not found: {SOURCE_APPLET_DIR}")
        return

    if TARGET_APPLET_DIR.exists():
        shutil.rmtree(TARGET_APPLET_DIR)
    shutil.copytree(SOURCE_APPLET_DIR, TARGET_APPLET_DIR)
    context.log(f"installed Cinnamon applet: {TARGET_APPLET_DIR}")


def _session_environment(uid: int) -> dict[str, str] | None:
    runtime_dir = Path(f"/run/user/{uid}")
    if not runtime_dir.exists():
        return None

    env = os.environ.copy()
    env.update(
        {
            "DISPLAY": os.environ.get("DISPLAY", ":0"),
            "XDG_RUNTIME_DIR": str(runtime_dir),
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime_dir}/bus",
        }
    )
    return env


def _live_desktop_users() -> list[tuple[str, int]]:
    users: list[tuple[str, int]] = []
    runtime_root = Path("/run/user")
    if not runtime_root.exists():
        return users

    for runtime_dir in runtime_root.iterdir():
        if not runtime_dir.is_dir() or not runtime_dir.name.isdigit():
            continue
        uid = int(runtime_dir.name)
        try:
            user_info = pwd.getpwuid(uid)
        except KeyError:
            continue
        if uid < 1000 or user_info.pw_dir in ("", "/nonexistent"):
            continue
        users.append((user_info.pw_name, uid))

    return users


def _run_gsettings(user: str, env: dict[str, str], args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["runuser", "-u", user, "--", "gsettings", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _append_applet(enabled_applets: str) -> str | None:
    """Insert Control Center immediately before calendar@cinnamon.org.

    Falls back to appending at the end when calendar is absent.
    Renumbers position field of all panel1:right entries in ascending order.
    """

    value = enabled_applets.strip()
    if APPLET_UUID in value:
        return value
    if not value.startswith("[") or not value.endswith("]"):
        return None

    inner = value[1:-1].strip()
    entries: list[str] = []
    if inner:
        for raw in inner.split(","):
            e = raw.strip().strip("'").strip('"')
            if e:
                entries.append(e)

    right_entries: list[str] = []
    other_entries: list[str] = []
    for e in entries:
        if e.startswith("panel1:right:"):
            right_entries.append(e)
        else:
            other_entries.append(e)

    calendar_idx = -1
    for i, e in enumerate(right_entries):
        parts = e.split(":", 4)
        if len(parts) >= 4 and parts[3] == "calendar@cinnamon.org":
            calendar_idx = i
            break

    new_uuid_entry_tail = f"{APPLET_UUID}:0"
    if calendar_idx == -1:
        right_entries.append(f"panel1:right:X:{new_uuid_entry_tail}")
    else:
        right_entries.insert(calendar_idx, f"panel1:right:X:{new_uuid_entry_tail}")

    renumbered: list[str] = []
    for i, e in enumerate(right_entries):
        parts = e.split(":", 4)
        if len(parts) < 5:
            renumbered.append(e)
            continue
        parts[2] = str(i)
        renumbered.append(":".join(parts))

    quoted = [f"'{e}'" for e in other_entries + renumbered]
    return f"[{', '.join(quoted)}]"


def _apply_to_live_user(context: MigrationContext, username: str, uid: int) -> None:
    env = _session_environment(uid)
    if env is None:
        return

    current = _run_gsettings(username, env, ["get", "org.cinnamon", "enabled-applets"])
    if current.returncode != 0:
        context.log(f"warning: could not read Cinnamon applets for {username}: {current.stderr.strip()}")
        return

    updated_applets = _append_applet(current.stdout)
    if updated_applets is None:
        context.log(f"warning: unexpected enabled-applets format for {username}; skip Control Center enable")
        return
    if updated_applets == current.stdout.strip():
        context.log(f"kept existing Control Center applet for user: {username}")
        return

    result = _run_gsettings(username, env, ["set", "org.cinnamon", "enabled-applets", updated_applets])
    if result.returncode == 0:
        context.log(f"enabled CaramOS Control Center for live user: {username}")
    else:
        context.log(f"warning: could not enable Control Center for {username}: {result.stderr.strip()}")


def run(context: MigrationContext) -> None:
    """Install and enable the CaramOS Control Center applet."""

    if context.dry_run:
        context.log(f"[dry-run] copy {SOURCE_APPLET_DIR} to {TARGET_APPLET_DIR}")
        context.log("[dry-run] append Control Center applet for live desktop users")
        return

    _install_applet(context)

    for username, uid in _live_desktop_users():
        _apply_to_live_user(context, username, uid)

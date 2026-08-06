"""Timestamp migration for 1.0.13: install CaramOS Control Center applet."""

from __future__ import annotations

import ast
import json
import os
import pwd
import shutil
import subprocess
import tempfile
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Install CaramOS Control Center Cinnamon applet"

APPLET_UUID = "caramos-control-center@caramos"
REPLACED_APPLET_UUIDS = frozenset(
    {
        "network@cinnamon.org",
        "sound@cinnamon.org",
        "power@cinnamon.org",
    }
)
SOURCE_APPLET_DIR = Path("/usr/share/caramos-ota/applets") / APPLET_UUID
TARGET_APPLET_DIR = Path("/usr/share/cinnamon/applets") / APPLET_UUID
REQUIRED_APPLET_FILES = ("applet.js", "metadata.json", "stylesheet.css")


def _validate_applet(directory: Path) -> None:
    if not directory.is_dir():
        raise RuntimeError(f"applet source directory not found: {directory}")
    if directory.is_symlink():
        raise RuntimeError(f"applet source must not be a symlink: {directory}")

    for name in REQUIRED_APPLET_FILES:
        path = directory / name
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"applet source requires regular file: {path}")

    try:
        metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    except Exception as exc:
        raise RuntimeError(f"cannot read applet metadata: {exc}") from exc
    if not isinstance(metadata, dict) or metadata.get("uuid") != APPLET_UUID:
        raise RuntimeError(f"applet metadata UUID must be {APPLET_UUID!r}")


def _clear_directory(directory: Path) -> None:
    for child in directory.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def _copy_directory_contents(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        destination = target / child.name
        if child.is_dir() and not child.is_symlink():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination, follow_symlinks=False)


def _install_applet(context: MigrationContext) -> None:
    _validate_applet(SOURCE_APPLET_DIR)
    TARGET_APPLET_DIR.parent.mkdir(parents=True, exist_ok=True)
    if TARGET_APPLET_DIR.is_symlink():
        raise RuntimeError(f"applet target must not be a symlink: {TARGET_APPLET_DIR}")
    if TARGET_APPLET_DIR.exists() and not TARGET_APPLET_DIR.is_dir():
        raise RuntimeError(f"applet target must be a directory: {TARGET_APPLET_DIR}")

    staging_root = Path(tempfile.mkdtemp(prefix=f".{APPLET_UUID}.", dir=TARGET_APPLET_DIR.parent))
    staging_dir = staging_root / APPLET_UUID
    backup_dir = staging_root / "previous"
    target_existed = TARGET_APPLET_DIR.exists()
    try:
        shutil.copytree(SOURCE_APPLET_DIR, staging_dir)
        _validate_applet(staging_dir)
        if target_existed:
            shutil.copytree(TARGET_APPLET_DIR, backup_dir, symlinks=True)

        TARGET_APPLET_DIR.mkdir(parents=True, exist_ok=True)
        try:
            _clear_directory(TARGET_APPLET_DIR)
            _copy_directory_contents(staging_dir, TARGET_APPLET_DIR)
            _validate_applet(TARGET_APPLET_DIR)
        except Exception:
            _clear_directory(TARGET_APPLET_DIR)
            if target_existed:
                _copy_directory_contents(backup_dir, TARGET_APPLET_DIR)
            else:
                TARGET_APPLET_DIR.rmdir()
            raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)

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


def _update_enabled_applets(enabled_applets: str) -> str | None:
    """Replace redundant stock indicators with Control Center atomically.

    Existing entries keep their text, order, and position fields. Both the
    four-field and five-field Cinnamon formats are accepted; unknown top-level
    list formats are rejected without changing user settings.
    """

    value = enabled_applets.strip()
    if not value.startswith("[") or not value.endswith("]"):
        return None

    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(parsed, list) or any(not isinstance(entry, str) for entry in parsed):
        return None

    inner = value[1:-1].strip()
    if inner and not parsed:
        return None

    entries: list[str] = []
    has_control_center = False
    for entry in parsed:
        parts = entry.split(":", 4)
        uuid = parts[3] if len(parts) >= 4 else None
        if uuid in REPLACED_APPLET_UUIDS:
            continue
        entries.append(entry)
        if uuid == APPLET_UUID:
            has_control_center = True

    if not has_control_center:
        positions = [
            int(parts[2])
            for entry in entries
            for parts in [entry.split(":", 4)]
            if len(parts) >= 4
            and parts[0] == "panel1"
            and parts[1] == "right"
            and parts[2].isdigit()
        ]
        next_position = max(positions, default=-1) + 1
        entries.append(f"panel1:right:{next_position}:{APPLET_UUID}:0")

    quoted = [repr(entry) for entry in entries]
    return f"[{', '.join(quoted)}]"


def _apply_to_live_user(context: MigrationContext, username: str, uid: int) -> None:
    env = _session_environment(uid)
    if env is None:
        return

    current = _run_gsettings(username, env, ["get", "org.cinnamon", "enabled-applets"])
    if current.returncode != 0:
        context.log(f"warning: could not read Cinnamon applets for {username}: {current.stderr.strip()}")
        return

    updated_applets = _update_enabled_applets(current.stdout)
    if updated_applets is None:
        context.log(f"warning: unexpected enabled-applets format for {username}; skip Control Center panel update")
        return
    if updated_applets == current.stdout.strip():
        context.log(f"kept existing Control Center panel layout for user: {username}")
        return

    result = _run_gsettings(username, env, ["set", "org.cinnamon", "enabled-applets", updated_applets])
    if result.returncode == 0:
        context.log(f"enabled Control Center and removed redundant network, sound, and power applets for: {username}")
    else:
        context.log(f"warning: could not update Control Center panel for {username}: {result.stderr.strip()}")


def run(context: MigrationContext) -> None:
    """Install and enable the CaramOS Control Center applet."""

    if context.dry_run:
        context.log(f"[dry-run] copy {SOURCE_APPLET_DIR} to {TARGET_APPLET_DIR}")
        context.log("[dry-run] enable Control Center and remove redundant network, sound, and power applets for live desktop users")
        return

    _install_applet(context)

    for username, uid in _live_desktop_users():
        _apply_to_live_user(context, username, uid)

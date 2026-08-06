"""Timestamp migration for CaramOS 1.0.15: change the default wallpaper."""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import NamedTuple

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Install and activate the new CaramOS default wallpaper"

MIGRATION_ID = "20260804223346_change_default_wallpaper"
SOURCE_WALLPAPER = Path(__file__).parent / "payload" / "wallpaper2.png"
WALLPAPER_DIR = Path("/usr/share/backgrounds/caramos")
TARGET_WALLPAPER = WALLPAPER_DIR / "wallpaper2.png"
DEFAULT_WALLPAPER = WALLPAPER_DIR / "default.png"
BACKUP_DIR = Path("/var/lib/caramos-ota/backups") / MIGRATION_ID
RUNTIME_ROOT = Path("/run/user")
DEFAULT_URI = "file:///usr/share/backgrounds/caramos/default.png"
TARGET_URI = "file:///usr/share/backgrounds/caramos/wallpaper2.png"
KNOWN_DEFAULT_URIS = {
    DEFAULT_URI,
    "file:///usr/share/backgrounds/caramos/wallpaper.jpg",
    "file:///usr/share/backgrounds/caramos/default.jpg",
    "file:///usr/share/backgrounds/caramos/caramos-wallpaper.png",
    TARGET_URI,
}
DESKTOP_SCHEMAS = (
    "org.cinnamon.desktop.background",
    "org.gnome.desktop.background",
)


class EntryState(NamedTuple):
    """Filesystem entry state captured before migration-owned replacement."""

    kind: str
    link_target: str | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _entry_state(path: Path, *, allow_symlink: bool) -> EntryState:
    if path.is_symlink():
        if not allow_symlink:
            raise RuntimeError(f"wallpaper target must not be a symbolic link: {path}")
        return EntryState("symlink", os.readlink(path))
    if not path.exists():
        return EntryState("absent")
    if path.is_file():
        return EntryState("file")
    raise RuntimeError(f"unsupported wallpaper destination type: {path}")


def _validate_payload() -> None:
    if SOURCE_WALLPAPER.is_symlink() or not SOURCE_WALLPAPER.is_file():
        raise RuntimeError(f"wallpaper payload requires a regular file: {SOURCE_WALLPAPER}")
    if SOURCE_WALLPAPER.stat().st_size <= 0:
        raise RuntimeError(f"wallpaper payload is empty: {SOURCE_WALLPAPER}")


def _same_content(left: Path, right: Path) -> bool:
    if right.is_symlink() or not right.is_file():
        return False
    if left.stat().st_size != right.stat().st_size:
        return False
    return _sha256(left) == _sha256(right)


def _default_link_is_current() -> bool:
    return DEFAULT_WALLPAPER.is_symlink() and os.readlink(DEFAULT_WALLPAPER) == TARGET_WALLPAPER.name


def _atomic_copy(source: Path, target: Path, mode: int) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    staging = Path(staging_name)
    try:
        shutil.copy2(source, staging)
        staging.chmod(mode)
        if not _same_content(source, staging):
            raise RuntimeError(f"staged wallpaper failed content validation: {target}")
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)


def _atomic_symlink(link_target: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.with_name(f".{destination.name}.{MIGRATION_ID}.tmp")
    staging.unlink(missing_ok=True)
    try:
        staging.symlink_to(link_target)
        os.replace(staging, destination)
    finally:
        staging.unlink(missing_ok=True)


def _backup_file(source: Path, destination: Path) -> None:
    _atomic_copy(source, destination, source.stat().st_mode & 0o777)


def _write_backup_metadata(states: dict[str, EntryState]) -> None:
    payload = {
        name: {"kind": state.kind, "link_target": state.link_target}
        for name, state in states.items()
    }
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(prefix=".state.", dir=BACKUP_DIR)
    os.close(descriptor)
    staging = Path(staging_name)
    try:
        staging.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        staging.chmod(0o600)
        os.replace(staging, BACKUP_DIR / "state.json")
    finally:
        staging.unlink(missing_ok=True)


def _backup_entries(target_state: EntryState, default_state: EntryState) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if target_state.kind == "file":
        _backup_file(TARGET_WALLPAPER, BACKUP_DIR / "wallpaper2.png.previous")
    if default_state.kind == "file":
        _backup_file(DEFAULT_WALLPAPER, BACKUP_DIR / "default.png.previous")
    _write_backup_metadata({"target": target_state, "default": default_state})


def _remove_entry(path: Path) -> None:
    if path.is_symlink() or path.exists():
        path.unlink()


def _restore_entry(path: Path, state: EntryState, backup: Path) -> None:
    if state.kind == "absent":
        _remove_entry(path)
    elif state.kind == "symlink":
        if state.link_target is None:
            raise RuntimeError(f"missing backup link target for {path}")
        _atomic_symlink(state.link_target, path)
    elif state.kind == "file":
        if not backup.is_file() or backup.is_symlink():
            raise RuntimeError(f"missing regular backup for {path}: {backup}")
        _atomic_copy(backup, path, backup.stat().st_mode & 0o777)
    else:
        raise RuntimeError(f"unknown backup state for {path}: {state.kind}")


def _install_filesystem(context: MigrationContext) -> bool:
    _validate_payload()
    target_state = _entry_state(TARGET_WALLPAPER, allow_symlink=False)
    default_state = _entry_state(DEFAULT_WALLPAPER, allow_symlink=True)
    install_image = not _same_content(SOURCE_WALLPAPER, TARGET_WALLPAPER)
    install_link = not _default_link_is_current()

    if not install_image and not install_link:
        context.log("default wallpaper files already active")
        return False

    if install_image:
        context.log(f"install wallpaper: {TARGET_WALLPAPER}")
    if install_link:
        context.log(f"activate default wallpaper: {DEFAULT_WALLPAPER} -> {TARGET_WALLPAPER.name}")
    if context.dry_run:
        return True

    _backup_entries(target_state, default_state)
    target_changed = False
    default_changed = False
    try:
        if install_image:
            _atomic_copy(SOURCE_WALLPAPER, TARGET_WALLPAPER, 0o644)
            target_changed = True
        if install_link:
            _atomic_symlink(TARGET_WALLPAPER.name, DEFAULT_WALLPAPER)
            default_changed = True
        if not _same_content(SOURCE_WALLPAPER, TARGET_WALLPAPER):
            raise RuntimeError("installed wallpaper failed final content validation")
        if not _default_link_is_current():
            raise RuntimeError("installed default wallpaper link failed validation")
    except Exception:
        if default_changed:
            _restore_entry(
                DEFAULT_WALLPAPER,
                default_state,
                BACKUP_DIR / "default.png.previous",
            )
        if target_changed:
            _restore_entry(
                TARGET_WALLPAPER,
                target_state,
                BACKUP_DIR / "wallpaper2.png.previous",
            )
        raise
    return True


def _session_environment(uid: int, home: Path) -> dict[str, str] | None:
    runtime_dir = RUNTIME_ROOT / str(uid)
    if not runtime_dir.is_dir() or not (runtime_dir / "bus").exists():
        return None
    env = os.environ.copy()
    env.update(
        {
            "DISPLAY": os.environ.get("DISPLAY", ":0"),
            "XAUTHORITY": str(home / ".Xauthority"),
            "XDG_RUNTIME_DIR": str(runtime_dir),
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime_dir}/bus",
        }
    )
    return env


def _live_desktop_users() -> list[tuple[str, int, Path]]:
    users: list[tuple[str, int, Path]] = []
    if not RUNTIME_ROOT.is_dir():
        return users
    for runtime_dir in sorted(RUNTIME_ROOT.iterdir(), key=lambda path: path.name):
        if not runtime_dir.is_dir() or not runtime_dir.name.isdigit():
            continue
        uid = int(runtime_dir.name)
        if uid < 1000:
            continue
        try:
            info = pwd.getpwuid(uid)
        except KeyError:
            continue
        if not info.pw_name or info.pw_dir in ("", "/nonexistent"):
            continue
        users.append((info.pw_name, uid, Path(info.pw_dir)))
    return users


def _run_as_user(user: str, env: dict[str, str], args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["runuser", "-u", user, "--", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _unquote_gsettings(value: str) -> str:
    normalized = value.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in ("'", '"'):
        return normalized[1:-1]
    return normalized


def _set_picture_uri(
    context: MigrationContext,
    user: str,
    env: dict[str, str],
    schema: str,
    uri: str,
) -> bool:
    result = _run_as_user(
        user,
        env,
        ["gsettings", "set", schema, "picture-uri", uri],
    )
    if result.returncode != 0:
        context.log(f"warning: could not set {schema} wallpaper for {user}: {result.stderr.strip()}")
        return False
    return True


def _apply_schema(context: MigrationContext, user: str, env: dict[str, str], schema: str) -> None:
    current = _run_as_user(user, env, ["gsettings", "get", schema, "picture-uri"])
    if current.returncode != 0:
        context.log(f"warning: could not read {schema} wallpaper for {user}: {current.stderr.strip()}")
        return
    current_uri = _unquote_gsettings(current.stdout)
    if current_uri not in KNOWN_DEFAULT_URIS:
        context.log(f"kept custom {schema} wallpaper for live user: {user}")
        return
    if current_uri != DEFAULT_URI:
        if _set_picture_uri(context, user, env, schema, DEFAULT_URI):
            context.log(f"updated {schema} default wallpaper for live user: {user}")
        return

    # Cinnamon/GNOME can cache a URI when only its symlink target changes.
    # Toggle between two migration-owned URIs so active sessions reload the image.
    if not _set_picture_uri(context, user, env, schema, TARGET_URI):
        return
    if not _set_picture_uri(context, user, env, schema, DEFAULT_URI):
        context.log(f"warning: {schema} wallpaper reload stopped at migration-owned URI for {user}")
        return
    context.log(f"reloaded {schema} default wallpaper for live user: {user}")


def _apply_to_live_user(context: MigrationContext, user: str, uid: int, home: Path) -> None:
    env = _session_environment(uid, home)
    if env is None:
        context.log(f"warning: desktop session bus unavailable for live user: {user}")
        return
    for schema in DESKTOP_SCHEMAS:
        _apply_schema(context, user, env, schema)


def run(context: MigrationContext) -> None:
    """Install wallpaper2 and preserve user-selected custom wallpaper settings."""
    _validate_payload()
    if context.dry_run:
        _install_filesystem(context)
        context.log("evaluate active Cinnamon and GNOME users still using a CaramOS default wallpaper")
        return

    changed = _install_filesystem(context)
    for user, uid, home in _live_desktop_users():
        _apply_to_live_user(context, user, uid, home)
    if changed:
        context.log("new default wallpaper is active for desktop and LightDM consumers")

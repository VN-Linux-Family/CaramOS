"""Install the CaramOS wallpaper collection and force Sage Mist as default."""

from __future__ import annotations

import hashlib
import json
import os
import pwd
import shutil
import struct
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import NamedTuple

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Install the CaramOS wallpaper collection and replace Mint sources in Cinnamon Backgrounds"

MIGRATION_ID = "20260804223346_change_default_wallpaper"
MIGRATION_DIR = Path(__file__).resolve().parent
PAYLOAD_DIR = MIGRATION_DIR / "payload"
WALLPAPER_DIR = Path("/usr/share/backgrounds/caramos")
DEFAULT_WALLPAPER = WALLPAPER_DIR / "default.png"
DEFAULT_WALLPAPER_NAME = "03-sage-mist-2k.jpg"
DEFAULT_URI = "file:///usr/share/backgrounds/caramos/default.png"
DIRECT_DEFAULT_URI = f"file:///usr/share/backgrounds/caramos/{DEFAULT_WALLPAPER_NAME}"
BACKGROUND_PROPERTIES_DIR = Path("/usr/share/cinnamon-background-properties")
CARAMOS_COLLECTION = BACKGROUND_PROPERTIES_DIR / "caramos.xml"
MINT_COLLECTIONS = (
    BACKGROUND_PROPERTIES_DIR / "linuxmint.xml",
)
WALLPAPERS_COLLECTION = BACKGROUND_PROPERTIES_DIR / "linuxmint-wallpapers.xml"
CINNAMON_BACKGROUNDS_MODULE = Path("/usr/share/cinnamon/cinnamon-settings/modules/cs_backgrounds.py")
BACKUP_DIR = Path("/var/lib/caramos-ota/backups") / MIGRATION_ID
ORIGINAL_STATE_FILE = BACKUP_DIR / "filesystem-state-v2.json"
RUNTIME_ROOT = Path("/run/user")
PATCH_MARKER = "# CaramOS OTA 20260804223346: branded wallpaper collection"
PATCH_ANCHOR = '''                    if display_name == "Linuxmint":
                        display_name = "Linux Mint"
                        icon = "linuxmint-logo-badge-symbolic"
                        order = 0
'''
PATCH_BLOCK = '''                    # CaramOS OTA 20260804223346: branded wallpaper collection
                    if display_name == "Caramos":
                        display_name = "CaramOS"
                        icon = "caramos-logo-symbolic"
                        order = 0
'''
WALLPAPERS = (
    ("01-paper-dawn-2k.jpg", "Paper Dawn"),
    ("02-indigo-night-2k.jpg", "Indigo Night"),
    ("03-sage-mist-2k.jpg", "Sage Mist"),
    ("04-terracotta-cutout-2k.jpg", "Terracotta Cutout"),
    ("05-glass-aurora-2k.jpg", "Glass Aurora"),
)
KNOWN_DEFAULT_URIS = {
    DEFAULT_URI,
    DIRECT_DEFAULT_URI,
    "file:///usr/share/backgrounds/caramos/wallpaper.jpg",
    "file:///usr/share/backgrounds/caramos/default.jpg",
    "file:///usr/share/backgrounds/caramos/caramos-wallpaper.png",
    "file:///usr/share/backgrounds/caramos/wallpaper2.png",
    "file:///usr/share/backgrounds/caramos/wallpaper22.png",
}
MINT_URI_PREFIXES = (
    "file:///usr/share/backgrounds/linuxmint/",
    "file:///usr/share/backgrounds/linuxmint-wallpapers/",
)
MINT_SLIDESHOW_SOURCES = {
    "xml:///usr/share/cinnamon-background-properties/linuxmint.xml",
    "xml:///usr/share/cinnamon-background-properties/linuxmint-wallpapers.xml",
}
CARAMOS_SLIDESHOW_SOURCE = "xml:///usr/share/cinnamon-background-properties/caramos.xml"
DESKTOP_SCHEMAS = (
    "org.cinnamon.desktop.background",
    "org.gnome.desktop.background",
)


class EntryState(NamedTuple):
    """State needed to restore one filesystem entry."""

    kind: str
    link_target: str | None = None
    mode: int | None = None
    backup_name: str | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _jpeg_dimensions(path: Path) -> tuple[int, int]:
    """Read JPEG dimensions without optional image libraries."""

    with path.open("rb") as handle:
        if handle.read(2) != b"\xff\xd8":
            raise RuntimeError(f"wallpaper payload is not a JPEG: {path}")
        while True:
            marker_start = handle.read(1)
            if not marker_start:
                break
            if marker_start != b"\xff":
                continue
            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if not marker or marker in (b"\xd8", b"\xd9"):
                continue
            if marker == b"\xda":
                break
            length_bytes = handle.read(2)
            if len(length_bytes) != 2:
                break
            length = struct.unpack(">H", length_bytes)[0]
            if length < 2:
                break
            if marker[0] in {
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            }:
                frame = handle.read(length - 2)
                if len(frame) < 5:
                    break
                height, width = struct.unpack(">HH", frame[1:5])
                return width, height
            handle.seek(length - 2, os.SEEK_CUR)
    raise RuntimeError(f"could not read JPEG dimensions: {path}")


def _payload_path(filename: str) -> Path:
    return PAYLOAD_DIR / filename


def _target_path(filename: str) -> Path:
    return WALLPAPER_DIR / filename


def _validate_payloads() -> None:
    filenames = [filename for filename, _name in WALLPAPERS]
    if len(filenames) != len(set(filenames)):
        raise RuntimeError("wallpaper payload filenames must be unique")
    if DEFAULT_WALLPAPER_NAME not in filenames:
        raise RuntimeError(f"default wallpaper payload is missing: {DEFAULT_WALLPAPER_NAME}")
    for filename in filenames:
        source = _payload_path(filename)
        if source.is_symlink() or not source.is_file():
            raise RuntimeError(f"wallpaper payload requires a regular file: {source}")
        if source.stat().st_size <= 0:
            raise RuntimeError(f"wallpaper payload is empty: {source}")
        if _jpeg_dimensions(source) != (2048, 1152):
            raise RuntimeError(f"wallpaper payload must be 2048x1152: {source}")


def _same_content(left: Path, right: Path) -> bool:
    if right.is_symlink() or not right.is_file():
        return False
    return left.stat().st_size == right.stat().st_size and _sha256(left) == _sha256(right)


def _atomic_copy(source: Path, target: Path, mode: int = 0o644) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    staging = Path(staging_name)
    try:
        shutil.copy2(source, staging)
        staging.chmod(mode)
        if not _same_content(source, staging):
            raise RuntimeError(f"staged file failed content validation: {target}")
        os.replace(staging, target)
    finally:
        staging.unlink(missing_ok=True)


def _atomic_write(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    staging = Path(staging_name)
    try:
        staging.write_text(content, encoding="utf-8")
        staging.chmod(mode)
        os.replace(staging, path)
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


def _remove_entry(path: Path) -> None:
    if path.is_symlink() or path.exists():
        path.unlink()


def _entry_state(path: Path, backup_root: Path, index: int) -> EntryState:
    if path.is_symlink():
        return EntryState("symlink", link_target=os.readlink(path))
    if not path.exists():
        return EntryState("absent")
    if not path.is_file():
        raise RuntimeError(f"unsupported migration destination type: {path}")
    backup_name = f"{index:02d}-{path.name}.backup"
    shutil.copy2(path, backup_root / backup_name)
    return EntryState("file", mode=path.stat().st_mode & 0o777, backup_name=backup_name)


def _capture_snapshot(paths: tuple[Path, ...], backup_root: Path) -> dict[Path, EntryState]:
    backup_root.mkdir(parents=True, exist_ok=True)
    states = {path: _entry_state(path, backup_root, index) for index, path in enumerate(paths)}
    payload = {str(path): state._asdict() for path, state in states.items()}
    _atomic_write(backup_root / "state.json", json.dumps(payload, indent=2, sort_keys=True) + "\n", 0o600)
    return states


def _restore_snapshot(states: dict[Path, EntryState], backup_root: Path) -> None:
    for path, state in reversed(tuple(states.items())):
        if state.kind == "absent":
            _remove_entry(path)
        elif state.kind == "symlink":
            if state.link_target is None:
                raise RuntimeError(f"missing symlink target in rollback state: {path}")
            _atomic_symlink(state.link_target, path)
        elif state.kind == "file":
            if state.backup_name is None:
                raise RuntimeError(f"missing backup name in rollback state: {path}")
            backup = backup_root / state.backup_name
            if backup.is_symlink() or not backup.is_file():
                raise RuntimeError(f"missing rollback file: {backup}")
            _atomic_copy(backup, path, state.mode or 0o644)
        else:
            raise RuntimeError(f"unknown rollback state for {path}: {state.kind}")


def _save_original_snapshot_once(paths: tuple[Path, ...]) -> None:
    if ORIGINAL_STATE_FILE.exists():
        return
    original_root = BACKUP_DIR / "original-v2"
    states = _capture_snapshot(paths, original_root)
    payload = {str(path): state._asdict() for path, state in states.items()}
    _atomic_write(ORIGINAL_STATE_FILE, json.dumps(payload, indent=2, sort_keys=True) + "\n", 0o600)


def _build_collection_xml() -> str:
    root = ET.Element("wallpapers")
    for filename, display_name in WALLPAPERS:
        wallpaper = ET.SubElement(root, "wallpaper", {"deleted": "false"})
        values = (
            ("name", display_name),
            ("filename", str(_target_path(filename))),
            ("options", "zoom"),
            ("pcolor", "#000000"),
            ("scolor", "#000000"),
            ("shade_type", "solid"),
            ("artist", "CaramOS"),
        )
        for tag, value in values:
            ET.SubElement(wallpaper, tag).text = value
    ET.indent(root, space="  ")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE wallpapers SYSTEM "cinnamon-wp-list.dtd">\n'
        + ET.tostring(root, encoding="unicode")
        + "\n"
    )


def _patched_cinnamon_source(source: str) -> str:
    if source.count(PATCH_MARKER) == 1:
        return source
    if PATCH_MARKER in source:
        raise RuntimeError("Cinnamon Backgrounds contains duplicate CaramOS patch markers")
    if source.count(PATCH_ANCHOR) != 1:
        raise RuntimeError("Cinnamon Backgrounds source does not match the supported patch anchor")
    return source.replace(PATCH_ANCHOR, PATCH_ANCHOR + PATCH_BLOCK, 1)


def _filesystem_paths() -> tuple[Path, ...]:
    return (
        *(_target_path(filename) for filename, _name in WALLPAPERS),
        DEFAULT_WALLPAPER,
        CARAMOS_COLLECTION,
        *MINT_COLLECTIONS,
        WALLPAPERS_COLLECTION,
        CINNAMON_BACKGROUNDS_MODULE,
    )


def _preflight_runtime() -> str:
    if CINNAMON_BACKGROUNDS_MODULE.is_symlink() or not CINNAMON_BACKGROUNDS_MODULE.is_file():
        raise RuntimeError(f"Cinnamon Backgrounds module is missing: {CINNAMON_BACKGROUNDS_MODULE}")
    source = CINNAMON_BACKGROUNDS_MODULE.read_text(encoding="utf-8")
    return _patched_cinnamon_source(source)


def _default_link_is_current() -> bool:
    return DEFAULT_WALLPAPER.is_symlink() and os.readlink(DEFAULT_WALLPAPER) == DEFAULT_WALLPAPER_NAME


def _restore_wallpapers_collection_if_missing() -> bool:
    """Restore stock Wallpapers metadata removed by an earlier migration run."""

    if WALLPAPERS_COLLECTION.is_symlink() or WALLPAPERS_COLLECTION.exists():
        return False
    original_root = BACKUP_DIR / "original-v2"
    candidates = sorted(original_root.glob("*-linuxmint-wallpapers.xml.backup"))
    gnome_copy = Path("/usr/share/gnome-background-properties/linuxmint-wallpapers.xml")
    if candidates:
        source = candidates[-1]
    elif gnome_copy.is_file() and not gnome_copy.is_symlink():
        source = gnome_copy
    else:
        raise RuntimeError(
            f"stock Wallpapers collection is missing and no restore source exists: {WALLPAPERS_COLLECTION}"
        )
    _atomic_copy(source, WALLPAPERS_COLLECTION, source.stat().st_mode & 0o777)
    return True


def _install_filesystem(context: MigrationContext) -> bool:
    _validate_payloads()
    patched_source = _preflight_runtime()
    collection_xml = _build_collection_xml()
    changed = any(not _same_content(_payload_path(name), _target_path(name)) for name, _title in WALLPAPERS)
    changed = changed or not _default_link_is_current()
    changed = changed or not CARAMOS_COLLECTION.is_file() or CARAMOS_COLLECTION.read_text(encoding="utf-8") != collection_xml
    changed = changed or any(path.is_symlink() or path.exists() for path in MINT_COLLECTIONS)
    changed = changed or not WALLPAPERS_COLLECTION.exists()
    changed = changed or CINNAMON_BACKGROUNDS_MODULE.read_text(encoding="utf-8") != patched_source

    for filename, _title in WALLPAPERS:
        context.log(f"install CaramOS wallpaper: {_target_path(filename)}")
    context.log(f"activate default wallpaper: {DEFAULT_WALLPAPER} -> {DEFAULT_WALLPAPER_NAME}")
    context.log(f"install CaramOS Cinnamon collection: {CARAMOS_COLLECTION}")
    context.log("remove the Linux Mint branded collection from Cinnamon Backgrounds")
    context.log("keep the stock Wallpapers collection in Cinnamon Backgrounds")
    context.log("brand Cinnamon Backgrounds collection as CaramOS")
    if context.dry_run:
        return changed
    if not changed:
        context.log("CaramOS wallpaper collection already active")
        return False

    paths = _filesystem_paths()
    _save_original_snapshot_once(paths)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".rollback-", dir=BACKUP_DIR) as rollback_name:
        rollback_root = Path(rollback_name)
        states = _capture_snapshot(paths, rollback_root)
        try:
            for filename, _title in WALLPAPERS:
                source = _payload_path(filename)
                target = _target_path(filename)
                if not _same_content(source, target):
                    _atomic_copy(source, target)
            if not CARAMOS_COLLECTION.is_file() or CARAMOS_COLLECTION.read_text(encoding="utf-8") != collection_xml:
                _atomic_write(CARAMOS_COLLECTION, collection_xml)
            if CINNAMON_BACKGROUNDS_MODULE.read_text(encoding="utf-8") != patched_source:
                _atomic_write(CINNAMON_BACKGROUNDS_MODULE, patched_source)
            if not _default_link_is_current():
                _atomic_symlink(DEFAULT_WALLPAPER_NAME, DEFAULT_WALLPAPER)
            for mint_collection in MINT_COLLECTIONS:
                _remove_entry(mint_collection)
            _restore_wallpapers_collection_if_missing()
            _validate_installed(collection_xml)
        except Exception:
            _restore_snapshot(states, rollback_root)
            raise
    return True


def _validate_installed(expected_xml: str) -> None:
    for filename, _title in WALLPAPERS:
        if not _same_content(_payload_path(filename), _target_path(filename)):
            raise RuntimeError(f"installed wallpaper failed validation: {_target_path(filename)}")
    if not _default_link_is_current():
        raise RuntimeError("installed default wallpaper link failed validation")
    if not CARAMOS_COLLECTION.is_file() or CARAMOS_COLLECTION.read_text(encoding="utf-8") != expected_xml:
        raise RuntimeError("installed CaramOS collection failed validation")
    root = ET.fromstring(expected_xml)
    if root.tag != "wallpapers":
        raise RuntimeError(f"CaramOS collection uses unsupported root element: {root.tag}")
    filenames = [node.text for node in root.findall("./wallpaper/filename")]
    if filenames != [str(_target_path(filename)) for filename, _title in WALLPAPERS]:
        raise RuntimeError("CaramOS collection contains unexpected wallpaper paths")
    if any(path.is_symlink() or path.exists() for path in MINT_COLLECTIONS):
        raise RuntimeError("Linux Mint collection metadata is still visible to Cinnamon Backgrounds")
    if WALLPAPERS_COLLECTION.is_symlink() or not WALLPAPERS_COLLECTION.is_file():
        raise RuntimeError("stock Wallpapers collection is missing from Cinnamon Backgrounds")
    source = CINNAMON_BACKGROUNDS_MODULE.read_text(encoding="utf-8")
    if source.count(PATCH_MARKER) != 1:
        raise RuntimeError("CaramOS Cinnamon Backgrounds patch failed validation")


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
        if info.pw_name and info.pw_dir not in ("", "/nonexistent"):
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


def _gsettings_get(user: str, env: dict[str, str], schema: str, key: str) -> tuple[bool, str]:
    result = _run_as_user(user, env, ["gsettings", "get", schema, key])
    return result.returncode == 0, _unquote_gsettings(result.stdout) if result.returncode == 0 else result.stderr.strip()


def _gsettings_set(
    context: MigrationContext,
    user: str,
    env: dict[str, str],
    schema: str,
    key: str,
    value: str,
) -> bool:
    result = _run_as_user(user, env, ["gsettings", "set", schema, key, value])
    if result.returncode != 0:
        context.log(f"warning: could not set {schema} {key} for {user}: {result.stderr.strip()}")
        return False
    return True


def _is_stock_wallpaper(uri: str) -> bool:
    return uri in KNOWN_DEFAULT_URIS or uri.startswith(MINT_URI_PREFIXES)


def _apply_schema(context: MigrationContext, user: str, env: dict[str, str], schema: str) -> None:
    success, current_uri = _gsettings_get(user, env, schema, "picture-uri")
    if not success:
        context.log(f"warning: could not read {schema} wallpaper for {user}: {current_uri}")
    # Force every live desktop session to reload Sage Mist, even when the user
    # previously selected another wallpaper.
    if not _gsettings_set(context, user, env, schema, "picture-uri", DIRECT_DEFAULT_URI):
        return
    if not _gsettings_set(context, user, env, schema, "picture-uri", DEFAULT_URI):
        return
    _gsettings_set(context, user, env, schema, "picture-options", "zoom")
    context.log(f"forced {schema} wallpaper to Sage Mist for live user: {user}")


def _apply_slideshow(context: MigrationContext, user: str, env: dict[str, str]) -> None:
    schema = "org.cinnamon.desktop.background.slideshow"
    success, source = _gsettings_get(user, env, schema, "image-source")
    if not success:
        context.log(f"warning: could not read Cinnamon slideshow source for {user}: {source}")
        return
    if source in MINT_SLIDESHOW_SOURCES:
        if _gsettings_set(context, user, env, schema, "image-source", CARAMOS_SLIDESHOW_SOURCE):
            context.log(f"updated Cinnamon slideshow source for live user: {user}")


def _apply_to_live_user(context: MigrationContext, user: str, uid: int, home: Path) -> None:
    env = _session_environment(uid, home)
    if env is None:
        context.log(f"warning: desktop session bus unavailable for live user: {user}")
        return
    for schema in DESKTOP_SCHEMAS:
        _apply_schema(context, user, env, schema)
    _apply_slideshow(context, user, env)


def run(context: MigrationContext) -> None:
    """Install five CaramOS wallpapers and force Sage Mist for live users."""

    _validate_payloads()
    changed = _install_filesystem(context)
    if context.dry_run:
        context.log("force Sage Mist for every active desktop user")
        return
    for user, uid, home in _live_desktop_users():
        _apply_to_live_user(context, user, uid, home)
    if changed:
        context.log("CaramOS wallpaper collection is active for desktop and login-screen consumers")

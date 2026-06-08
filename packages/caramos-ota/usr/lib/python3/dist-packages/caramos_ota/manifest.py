"""Migration metadata loading for CaramOS OTA."""

from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any

from .constants import EXIT_STATE, TOOL_VERSION
from .errors import OtaError
from .models import Manifest, ReleaseInfo

VALID_PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")

_VERSION_RE = re.compile(r"^\d+(?:\.\d+){1,4}(?:[-+~][A-Za-z0-9.+:~_-]+)?$")
_MIGRATIONS_PACKAGE = "caramos_ota_update.migrations"


def validate_package_name(package: str) -> bool:
    """Return True when a package name is safe to pass as an APT argument."""

    return bool(VALID_PACKAGE.fullmatch(package))


def _version_key(version: str) -> tuple[int | str, ...]:
    """Return a comparable key for dotted CaramOS versions."""

    parts: list[int | str] = []
    for item in re.split(r"[.+:~_-]", version):
        if item.isdigit():
            parts.append(int(item))
        elif item:
            parts.append(item)
    return tuple(parts)


def _migration_dir(version: str) -> str:
    """Return the migration directory name for a target version."""

    return "v" + version.replace(".", "_").replace("-", "_").replace("+", "_").replace("~", "_")


def _load_json_resource(relative_path: str) -> dict[str, Any]:
    """Load a bundled migration JSON resource."""

    try:
        root = resources.files(_MIGRATIONS_PACKAGE)
        raw = json.loads((root / relative_path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise OtaError(f"Error: Cannot read migration metadata {relative_path}: {exc}", EXIT_STATE) from exc
    if not isinstance(raw, dict):
        raise OtaError(f"Error: Migration metadata root must be an object: {relative_path}", EXIT_STATE)
    return raw


def load_migration_versions() -> list[str]:
    """Load ordered target versions from migrations/migration.json."""

    raw = _load_json_resource("migration.json")
    if raw.get("schema") != 1:
        raise OtaError("Error: Unsupported migration index schema", EXIT_STATE)
    versions = raw.get("versions")
    if not isinstance(versions, list) or not versions:
        raise OtaError("Error: migration.json must contain a non-empty versions list", EXIT_STATE)

    result: list[str] = []
    for version in versions:
        if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
            raise OtaError(f"Error: Invalid migration version in migration.json: {version!r}", EXIT_STATE)
        result.append(version)
    return result


def resolve_target_version(current_version: str) -> str | None:
    """Return the latest migration target newer than current_version, if any."""

    chain = resolve_migration_chain(current_version)
    return chain[-1] if chain else None


def resolve_migration_chain(current_version: str, target_version: str | None = None) -> list[str]:
    """Return ordered migration targets newer than current_version up to target_version."""

    current_key = _version_key(current_version)
    target_key = _version_key(target_version) if target_version is not None else None
    chain: list[str] = []
    for version in load_migration_versions():
        version_key = _version_key(version)
        if version_key <= current_key:
            continue
        if target_key is not None and version_key > target_key:
            continue
        chain.append(version)
    return chain

def load_migration_manifest(target_version: str, release_info: ReleaseInfo) -> Manifest:
    """Load the manifest.json stored inside the selected migration directory."""

    raw = _load_json_resource(f"{_migration_dir(target_version)}/manifest.json")
    return validate_manifest(raw, release_info, f"{_MIGRATIONS_PACKAGE}/{_migration_dir(target_version)}/manifest.json")


def parse_manifest(release_info: ReleaseInfo) -> Manifest:
    """Resolve the next migration and load its local manifest metadata."""

    target_version = resolve_target_version(release_info.version)
    if target_version is None:
        return Manifest(
            release=release_info.version,
            codename=release_info.codename,
            source="migration.json",
            min_client_version=None,
            channel=release_info.channel,
            severity="none",
            size="Không có cập nhật",
            title="CaramOS đã được cập nhật",
            summary="Không có migration mới.",
            release_notes_vi=[],
            release_notes_en=[],
        )
    return load_migration_manifest(target_version, release_info)


def validate_manifest(raw: dict[str, Any], release_info: ReleaseInfo, source: str) -> Manifest:
    """Validate one migration-local manifest object."""

    if raw.get("schema") != 1:
        raise OtaError(f"Error: Unsupported migration manifest schema from {source}", EXIT_STATE)
    version = raw.get("version")
    if not isinstance(version, str) or not _VERSION_RE.fullmatch(version):
        raise OtaError(f"Error: Invalid migration version from {source}: {version!r}", EXIT_STATE)
    if raw.get("codename") != release_info.codename:
        raise OtaError(
            f"Error: Migration codename mismatch from {source}: {raw.get('codename')} vs {release_info.codename}",
            EXIT_STATE,
        )
    min_client_version = raw.get("min_client_version", TOOL_VERSION)
    if min_client_version is not None and not isinstance(min_client_version, str):
        raise OtaError(f"Error: Invalid min_client_version in {source}", EXIT_STATE)

    return Manifest(
        release=version,
        codename=str(raw.get("codename", "")),
        source=source,
        min_client_version=min_client_version,
        channel=str(raw.get("channel") or release_info.channel),
        severity=str(raw.get("severity") or "normal"),
        size=str(raw.get("size") or "Migration update"),
        title=str(raw.get("title") or "CaramOS có bản cập nhật mới"),
        summary=str(raw.get("summary") or "Bản cập nhật này sẽ chạy migration CaramOS."),
        release_notes_vi=[str(note) for note in raw.get("release_notes_vi", []) if isinstance(note, str)],
        release_notes_en=[str(note) for note in raw.get("release_notes_en", []) if isinstance(note, str)],
    )

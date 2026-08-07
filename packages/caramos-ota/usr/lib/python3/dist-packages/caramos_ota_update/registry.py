"""Auto-discovery and validation for CaramOS OTA migrations."""

from __future__ import annotations

import ast
import json
import re
import subprocess
from dataclasses import dataclass
from functools import cmp_to_key
from importlib import resources
from pathlib import Path
from typing import Any

MIGRATIONS_PACKAGE = "caramos_ota_update.migrations"
TIMESTAMP_ID_RE = re.compile(r"^\d{14}_[a-z0-9][a-z0-9_]*$")
LEGACY_ID_RE = re.compile(r"^v\d+(?:_\d+)+(?:_[A-Za-z0-9_]+)?$")
VERSION_RE = re.compile(r"^\d+(?:\.\d+){1,3}(?:[-+~][A-Za-z0-9.+:~_-]+)?$")


class MigrationRegistryError(RuntimeError):
    """Raised when bundled migration metadata is invalid."""


@dataclass(frozen=True)
class MigrationDescriptor:
    """Validated metadata and entrypoint for one migration."""

    migration_id: str
    release: str | None
    description: str
    source: str
    directory: Path
    module_path: Path
    schema: int
    codename: str
    channel: str
    severity: str
    size: str
    title: str
    summary: str
    release_notes_vi: list[str]
    release_notes_en: list[str]
    from_version: str | None = None
    to_version: str | None = None

    @property
    def legacy(self) -> bool:
        return self.schema == 1


@dataclass(frozen=True)
class MigrationPlan:
    """Deterministic migration plan for one installed system."""

    current_version: str
    target_version: str
    migrations: list[MigrationDescriptor]


def compare_versions(left: str, right: str) -> int:
    """Compare CaramOS versions using Debian version semantics."""

    if left == right:
        return 0
    for operator, result in (("lt", -1), ("gt", 1)):
        completed = subprocess.run(
            ["dpkg", "--compare-versions", left, operator, right],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if completed.returncode == 0:
            return result
    raise MigrationRegistryError(f"cannot compare versions: {left!r} and {right!r}")


def version_le(left: str, right: str) -> bool:
    return compare_versions(left, right) <= 0


def version_lt(left: str, right: str) -> bool:
    return compare_versions(left, right) < 0


def max_version(versions: list[str]) -> str:
    if not versions:
        raise MigrationRegistryError("cannot select latest release from an empty migration registry")
    return sorted(versions, key=cmp_to_key(compare_versions))[-1]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MigrationRegistryError(f"cannot read migration metadata {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise MigrationRegistryError(f"migration metadata root must be an object: {path}")
    return raw


def _required_string(raw: dict[str, Any], key: str, source: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise MigrationRegistryError(f"migration metadata {source} requires string field {key!r}")
    return value.strip()


def _notes(raw: dict[str, Any], key: str) -> list[str]:
    value = raw.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise MigrationRegistryError(f"migration metadata field {key!r} must be a string list")
    return list(value)


def _legacy_module_path(directory: Path) -> Path:
    modules = sorted(
        path
        for path in directory.glob("*.py")
        if path.name != "__init__.py"
    )
    if len(modules) != 1:
        raise MigrationRegistryError(
            f"legacy migration {directory.name} must contain exactly one executable Python module"
        )
    return modules[0]


def _module_contract(module_path: Path, *, legacy: bool) -> dict[str, str]:
    """Validate migration entrypoint without importing executable code."""

    try:
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    except Exception as exc:
        raise MigrationRegistryError(f"cannot parse migration module {module_path}: {exc}") from exc

    values: dict[str, str] = {}
    has_run = False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
            has_run = True
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id not in {"DESCRIPTION", "FROM_VERSION", "TO_VERSION"}:
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            values[target.id] = node.value.value

    required = {"DESCRIPTION"}
    if legacy:
        required.update({"FROM_VERSION", "TO_VERSION"})
    missing = sorted(required.difference(values))
    if not has_run:
        missing.append("run")
    if missing:
        raise MigrationRegistryError(
            f"migration module {module_path} missing static contract: {', '.join(missing)}"
        )
    return values


def _descriptor(directory: Path) -> MigrationDescriptor:
    migration_id = directory.name
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file():
        raise MigrationRegistryError(f"migration {migration_id} is missing manifest.json")
    raw = _read_json(manifest_path)
    schema = raw.get("schema")

    if TIMESTAMP_ID_RE.fullmatch(migration_id):
        if schema != 2:
            raise MigrationRegistryError(f"timestamp migration {migration_id} requires manifest schema 2")
        forbidden = sorted({"release", "version", "from_version", "to_version"}.intersection(raw))
        if forbidden:
            raise MigrationRegistryError(
                f"timestamp migration {migration_id} manifest schema 2 must not contain: "
                f"{', '.join(forbidden)}"
            )
        release = None
        module_path = directory / "migration.py"
        if not module_path.is_file():
            raise MigrationRegistryError(f"timestamp migration {migration_id} is missing migration.py")
        from_version = None
        to_version = None
    elif LEGACY_ID_RE.fullmatch(migration_id):
        if schema != 1:
            raise MigrationRegistryError(f"legacy migration {migration_id} requires manifest schema 1")
        release = _required_string(raw, "version", manifest_path)
        from_version = _required_string(raw, "from_version", manifest_path)
        to_version = release
        module_path = _legacy_module_path(directory)
    else:
        raise MigrationRegistryError(
            f"invalid migration directory {migration_id!r}; expected vX_Y_Z or YYYYMMDDHHMMSS_name"
        )

    if release is not None and not VERSION_RE.fullmatch(release):
        raise MigrationRegistryError(f"invalid migration release {release!r} in {manifest_path}")
    if from_version is not None and not VERSION_RE.fullmatch(from_version):
        raise MigrationRegistryError(f"invalid from_version {from_version!r} in {manifest_path}")

    contract = _module_contract(module_path, legacy=schema == 1)
    if schema == 1:
        if contract["FROM_VERSION"] != from_version:
            raise MigrationRegistryError(
                f"legacy migration {migration_id} FROM_VERSION mismatch: "
                f"{contract['FROM_VERSION']!r} vs {from_version!r}"
            )
        if contract["TO_VERSION"] != release:
            raise MigrationRegistryError(
                f"legacy migration {migration_id} TO_VERSION mismatch: "
                f"{contract['TO_VERSION']!r} vs {release!r}"
            )

    changes = raw.get("changes", [])
    notes_vi = _notes(raw, "release_notes_vi")
    notes_en = _notes(raw, "release_notes_en")
    if not notes_vi and isinstance(changes, list) and all(isinstance(item, str) for item in changes):
        notes_vi = list(changes)

    summary = str(raw.get("summary") or "Bản cập nhật này sẽ chạy migration CaramOS.")
    return MigrationDescriptor(
        migration_id=migration_id,
        release=release,
        description=str(raw.get("description") or summary),
        source=str(manifest_path),
        directory=directory,
        module_path=module_path,
        schema=schema,
        codename=_required_string(raw, "codename", manifest_path),
        channel=str(raw.get("channel") or "stable"),
        severity=str(raw.get("severity") or "normal"),
        size=str(raw.get("size") or "Migration update"),
        title=str(raw.get("title") or "CaramOS có bản cập nhật mới"),
        summary=summary,
        release_notes_vi=notes_vi,
        release_notes_en=notes_en,
        from_version=from_version,
        to_version=to_version,
    )


def migration_root() -> Path:
    """Return installed bundled migration root."""

    return Path(str(resources.files(MIGRATIONS_PACKAGE)))


def discover_migrations(root: Path | None = None) -> list[MigrationDescriptor]:
    """Discover every migration directory without a central index."""

    selected_root = root or migration_root()
    if not selected_root.is_dir():
        raise MigrationRegistryError(f"migration root does not exist: {selected_root}")

    descriptors: list[MigrationDescriptor] = []
    for child in sorted(selected_root.iterdir(), key=lambda path: path.name):
        if not child.is_dir() or child.name == "__pycache__":
            continue
        entries = [entry for entry in child.iterdir() if entry.name != "__pycache__"]
        if not entries:
            continue
        if not (LEGACY_ID_RE.fullmatch(child.name) or TIMESTAMP_ID_RE.fullmatch(child.name)):
            raise MigrationRegistryError(
                f"invalid directory in migration root: {child.name!r}; "
                "only vX_Y_Z and YYYYMMDDHHMMSS_name are allowed"
            )
        descriptors.append(_descriptor(child))

    if not descriptors:
        raise MigrationRegistryError("no bundled migrations were discovered")
    _validate_registry(descriptors)
    return descriptors


def _validate_registry(descriptors: list[MigrationDescriptor]) -> None:
    seen_ids: set[str] = set()
    legacy_starts: dict[str, str] = {}
    for item in descriptors:
        if item.migration_id in seen_ids:
            raise MigrationRegistryError(f"duplicate migration ID: {item.migration_id}")
        seen_ids.add(item.migration_id)
        if not item.legacy:
            continue
        assert item.from_version is not None
        if item.from_version in legacy_starts:
            raise MigrationRegistryError(
                f"duplicate legacy migration start {item.from_version}: "
                f"{legacy_starts[item.from_version]} and {item.migration_id}"
            )
        legacy_starts[item.from_version] = item.migration_id

    for start in legacy_starts:
        cursor = start
        seen: set[str] = set()
        while cursor in legacy_starts:
            if cursor in seen:
                raise MigrationRegistryError(f"legacy migration cycle detected at {cursor}")
            seen.add(cursor)
            descriptor = next(item for item in descriptors if item.legacy and item.from_version == cursor)
            assert descriptor.release is not None
            cursor = descriptor.release


def latest_release(descriptors: list[MigrationDescriptor]) -> str:
    return max_version([item.release for item in descriptors if item.release is not None])


def latest_legacy_release(descriptors: list[MigrationDescriptor]) -> str:
    legacy = [item.release for item in descriptors if item.legacy and item.release is not None]
    return max_version(legacy)


def resolve_plan(
    current_version: str,
    *,
    applied_ids: set[str],
    target_version: str | None = None,
    descriptors: list[MigrationDescriptor] | None = None,
) -> MigrationPlan:
    """Resolve legacy bridge plus all pending timestamp migrations."""

    catalog = descriptors or discover_migrations()
    if target_version is None:
        raise MigrationRegistryError("target_version is required for migration plan finalization")
    target = target_version
    legacy_releases = [item.release for item in catalog if item.legacy and item.release is not None]
    latest_legacy = max_version(legacy_releases) if legacy_releases else current_version
    if version_lt(target, current_version):
        raise MigrationRegistryError(
            f"target version {target} is older than installed version {current_version}"
        )

    legacy_by_from = {
        item.from_version: item
        for item in catalog
        if item.legacy and item.from_version is not None
    }
    legacy_path: list[MigrationDescriptor] = []
    cursor = current_version
    seen: set[str] = set()
    while version_lt(cursor, target) and cursor in legacy_by_from:
        if cursor in seen:
            raise MigrationRegistryError(f"legacy migration cycle detected at {cursor}")
        seen.add(cursor)
        item = legacy_by_from[cursor]
        assert item.release is not None
        if not version_le(item.release, target):
            break
        legacy_path.append(item)
        cursor = item.release

    if legacy_releases and version_lt(cursor, target) and version_lt(cursor, latest_legacy):
        raise MigrationRegistryError(
            f"missing legacy migrations to target {target}; migration coverage stops at {cursor}"
        )

    timestamp_path = sorted(
        (
            item
            for item in catalog
            if not item.legacy and item.migration_id not in applied_ids
        ),
        key=lambda item: item.migration_id,
    )

    return MigrationPlan(
        current_version=current_version,
        target_version=target,
        migrations=legacy_path + timestamp_path,
    )

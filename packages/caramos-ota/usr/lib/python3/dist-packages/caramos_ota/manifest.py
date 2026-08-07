"""Auto-discovered migration metadata for CaramOS OTA."""

from __future__ import annotations

import re
from functools import cmp_to_key

from caramos_ota_update.ledger import applied_ids, bootstrap_ledger
from caramos_ota_update.registry import (
    MigrationDescriptor,
    MigrationPlan,
    MigrationRegistryError,
    compare_versions,
    discover_migrations,
    resolve_plan,
    version_lt,
)

from .constants import EXIT_STATE, TOOL_VERSION
from .release_metadata import PRODUCT_VERSION
from .errors import OtaError
from .models import Manifest, ReleaseInfo

VALID_PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")


def validate_package_name(package: str) -> bool:
    return bool(VALID_PACKAGE.fullmatch(package))


def _ota_error(exc: Exception) -> OtaError:
    return OtaError(f"Error: Invalid bundled migration registry: {exc}", EXIT_STATE)


def load_migration_catalog() -> list[MigrationDescriptor]:
    try:
        return discover_migrations()
    except MigrationRegistryError as exc:
        raise _ota_error(exc) from exc


def load_migration_versions() -> list[str]:
    """Return discovered releases for compatibility with older callers."""

    versions = {item.release for item in load_migration_catalog() if item.release is not None}
    versions.add(PRODUCT_VERSION)
    return sorted(versions, key=cmp_to_key(compare_versions))


def resolve_update_plan(release_info: ReleaseInfo, *, persist_ledger: bool = True) -> MigrationPlan:
    """Resolve pending migration IDs for one installed release."""

    catalog = load_migration_catalog()
    try:
        ledger = bootstrap_ledger(
            release_info.version,
            catalog,
            persist=persist_ledger,
        )
        return resolve_plan(
            release_info.version,
            applied_ids=applied_ids(ledger),
            target_version=PRODUCT_VERSION,
            descriptors=catalog,
        )
    except Exception as exc:
        raise _ota_error(exc) from exc


def resolve_target_version(current_version: str) -> str | None:
    """Return latest discovered release newer than current version."""

    try:
        return PRODUCT_VERSION if version_lt(current_version, PRODUCT_VERSION) else None
    except Exception as exc:
        raise _ota_error(exc) from exc


def resolve_migration_chain(current_version: str, target_version: str | None = None) -> list[str]:
    """Return discovered release boundaries for compatibility callers."""

    try:
        versions = load_migration_versions()
        target = target_version or PRODUCT_VERSION
        return [
            version
            for version in versions
            if version_lt(current_version, version) and not version_lt(target, version)
        ]
    except Exception as exc:
        if isinstance(exc, OtaError):
            raise
        raise _ota_error(exc) from exc


def _manifest_from_descriptors(
    descriptors: list[MigrationDescriptor],
    release_info: ReleaseInfo,
    target_version: str,
) -> Manifest:
    if not descriptors:
        target_newer = version_lt(release_info.version, target_version)
        return Manifest(
            release=target_version,
            codename=release_info.codename,
            source="packaged CaramOS release metadata",
            min_client_version=TOOL_VERSION if target_newer else None,
            channel=release_info.channel,
            severity="normal" if target_newer else "none",
            size="Release metadata" if target_newer else "Không có cập nhật",
            title="Cập nhật CaramOS" if target_newer else "CaramOS đã được cập nhật",
            summary=(
                f"Cập nhật thông tin hệ thống từ {release_info.version} lên {target_version}."
                if target_newer
                else "Không có migration mới."
            ),
            release_notes_vi=["Cập nhật thông tin phiên bản CaramOS."] if target_newer else [],
            release_notes_en=["Update CaramOS release metadata."] if target_newer else [],
        )

    for item in descriptors:
        if item.codename != release_info.codename:
            raise OtaError(
                f"Error: Migration codename mismatch from {item.source}: "
                f"{item.codename} vs {release_info.codename}",
                EXIT_STATE,
            )
        if item.channel != release_info.channel:
            raise OtaError(
                f"Error: Migration channel mismatch from {item.source}: "
                f"{item.channel} vs {release_info.channel}",
                EXIT_STATE,
            )

    target_items = [item for item in descriptors if item.release == target_version]
    display = target_items[-1] if target_items else descriptors[-1]
    notes_vi: list[str] = []
    notes_en: list[str] = []
    for item in descriptors:
        label = item.migration_id
        notes_vi.extend(f"{label}: {note}" for note in (item.release_notes_vi or [item.summary]))
        notes_en.extend(f"{label}: {note}" for note in (item.release_notes_en or [item.summary]))

    return Manifest(
        release=target_version,
        codename=display.codename,
        source=", ".join(item.source for item in descriptors),
        min_client_version=TOOL_VERSION,
        channel=display.channel,
        severity=display.severity,
        size=" + ".join(item.size for item in descriptors if item.size) or "Migration update",
        title=display.title,
        summary=display.summary,
        release_notes_vi=notes_vi,
        release_notes_en=notes_en,
    )


def manifest_for_plan(plan: MigrationPlan, release_info: ReleaseInfo) -> Manifest:
    return _manifest_from_descriptors(plan.migrations, release_info, plan.target_version)


def parse_manifest(release_info: ReleaseInfo) -> Manifest:
    plan = resolve_update_plan(release_info)
    return manifest_for_plan(plan, release_info)


def load_migration_manifest(target_version: str, release_info: ReleaseInfo) -> Manifest:
    """Aggregate pending migration metadata for compatibility callers."""

    if target_version != PRODUCT_VERSION:
        raise OtaError(
            f"Error: Requested target {target_version} does not match packaged target {PRODUCT_VERSION}",
            EXIT_STATE,
        )
    return parse_manifest(release_info)

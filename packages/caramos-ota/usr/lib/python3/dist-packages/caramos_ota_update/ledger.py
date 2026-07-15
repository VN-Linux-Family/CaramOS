"""Durable applied-migration ledger for CaramOS OTA."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from caramos_ota.constants import MIGRATION_LEDGER_FILE, STATE_DIR
from caramos_ota.logging_utils import now_iso

from .registry import MigrationDescriptor, MigrationRegistryError, max_version, version_le


class MigrationLedgerError(RuntimeError):
    """Raised when migration history cannot be loaded safely."""


def _default_ledger() -> dict[str, Any]:
    return {"schema": 1, "applied_migrations": []}


def load_ledger(path: Path = MIGRATION_LEDGER_FILE) -> dict[str, Any] | None:
    """Load an existing ledger; return None when no ledger exists yet."""

    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MigrationLedgerError(f"cannot read migration ledger {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != 1:
        raise MigrationLedgerError(f"unsupported migration ledger schema in {path}")
    records = raw.get("applied_migrations")
    if not isinstance(records, list):
        raise MigrationLedgerError(f"migration ledger {path} has invalid applied_migrations")
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str):
            raise MigrationLedgerError(f"migration ledger {path} contains an invalid record")
        if record["id"] in seen:
            raise MigrationLedgerError(f"migration ledger {path} contains duplicate ID {record['id']}")
        seen.add(record["id"])
    return raw


def save_ledger(ledger: dict[str, Any], path: Path = MIGRATION_LEDGER_FILE) -> None:
    """Atomically write migration history."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        json.dump(ledger, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(temp, path)
    os.chmod(path, 0o644)


def bootstrap_ledger(
    installed_version: str,
    descriptors: list[MigrationDescriptor],
    *,
    path: Path = MIGRATION_LEDGER_FILE,
    persist: bool = True,
) -> dict[str, Any]:
    """Create initial history from legacy version metadata only."""

    existing = load_ledger(path)
    if existing is not None:
        return existing

    legacy = [
        item
        for item in descriptors
        if item.legacy and version_le(item.release, installed_version)
    ]
    legacy_releases = [item.release for item in descriptors if item.legacy]
    latest_legacy = max_version(legacy_releases) if legacy_releases else None
    timestamp_releases = [item.release for item in descriptors if not item.legacy]
    if latest_legacy and timestamp_releases:
        try:
            beyond_legacy = not version_le(installed_version, latest_legacy)
        except MigrationRegistryError as exc:
            raise MigrationLedgerError(str(exc)) from exc
        if beyond_legacy:
            raise MigrationLedgerError(
                "migration ledger is missing on a post-legacy installation; "
                "restore /var/lib/caramos-ota/migrations.json before continuing"
            )

    ledger = _default_ledger()
    ledger["applied_migrations"] = [
        {
            "id": item.migration_id,
            "release": item.release,
            "applied_at": None,
            "source": "legacy-version-bootstrap",
        }
        for item in legacy
    ]
    if persist:
        save_ledger(ledger, path)
    return ledger


def applied_ids(ledger: dict[str, Any]) -> set[str]:
    return {
        str(record["id"])
        for record in ledger.get("applied_migrations", [])
        if isinstance(record, dict) and isinstance(record.get("id"), str)
    }


def mark_applied(
    ledger: dict[str, Any],
    descriptor: MigrationDescriptor,
    *,
    path: Path = MIGRATION_LEDGER_FILE,
) -> None:
    """Record one migration only after successful execution."""

    if descriptor.migration_id in applied_ids(ledger):
        return
    ledger.setdefault("applied_migrations", []).append(
        {
            "id": descriptor.migration_id,
            "release": descriptor.release,
            "applied_at": now_iso(),
            "source": descriptor.source,
        }
    )
    save_ledger(ledger, path)

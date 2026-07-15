"""State reading helpers for the desktop notifier."""

from __future__ import annotations

import json
from typing import Any

from caramos_ota.constants import RELEASE_FILE
from caramos_ota.manifest import manifest_for_plan, resolve_update_plan
from caramos_ota.models import ReleaseInfo

from .constants import STATE_FILE


def read_available_update() -> dict[str, Any] | None:
    try:
        if not STATE_FILE.exists():
            return None
        with STATE_FILE.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        if not isinstance(state, dict) or state.get("schema") not in (1, 2):
            return None
        available = state.get("available_update")
        if not isinstance(available, dict):
            return None
        packages = available.get("packages")
        if not isinstance(packages, list) or not packages:
            return None
        return available
    except Exception:
        return None


def format_value(value: object, fallback: str = "Chưa rõ") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def normalize_package(pkg: object) -> dict[str, object]:
    if isinstance(pkg, dict):
        name = format_value(pkg.get("name") or pkg.get("package"), "Không rõ migration")
        current = format_value(pkg.get("current_version") or pkg.get("installed_version"), "pending")
        available = format_value(
            pkg.get("available_version") or pkg.get("candidate_version") or pkg.get("min_version"),
            "Chưa rõ",
        )
        return {
            "name": name,
            "current": current,
            "available": available,
            "description": format_value(pkg.get("description"), ""),
            "required": pkg.get("required"),
        }
    return {
        "name": format_value(pkg, "Không rõ migration"),
        "current": "pending",
        "available": "Chưa rõ",
        "description": "",
        "required": None,
    }


def _read_release_info() -> ReleaseInfo | None:
    values: dict[str, str] = {}
    try:
        with RELEASE_FILE.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"')
    except Exception:
        return None
    if values.get("NAME") != "CaramOS":
        return None
    return ReleaseInfo(
        name="CaramOS",
        version=format_value(values.get("VERSION")),
        codename=format_value(values.get("UBUNTU_CODENAME"), "noble"),
        channel=format_value(values.get("CHANNEL"), "stable"),
    )


def _read_release_version() -> str:
    release_info = _read_release_info()
    return release_info.version if release_info else "Chưa rõ"


def read_no_update_status() -> dict[str, str]:
    release_info = _read_release_info()
    current_version = release_info.version if release_info else "Chưa rõ"
    latest_version = current_version
    if release_info:
        try:
            latest_version = resolve_update_plan(release_info, persist_ledger=False).target_version
        except Exception:
            pass
    return {
        "current_version": current_version,
        "latest_version": latest_version,
        "channel": release_info.channel if release_info else "stable",
    }


def resolve_available_update_now() -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Resolve pending migrations without executing migration modules."""

    release_info = _read_release_info()
    status = read_no_update_status()
    if release_info is None:
        return None, status
    try:
        plan = resolve_update_plan(release_info, persist_ledger=False)
        if not plan.migrations:
            return None, status
        manifest = manifest_for_plan(plan, release_info)
    except Exception:
        return None, status

    status["latest_version"] = plan.target_version
    packages = [
        {
            "name": item.migration_id,
            "current_version": "pending",
            "available_version": item.release,
            "description": item.summary,
            "required": True,
        }
        for item in plan.migrations
    ]
    update_info = {
        "detected_at": "manual",
        "release": manifest.release,
        "to_version": manifest.release,
        "manifest_source": manifest.source,
        "current_version": release_info.version,
        "from_version": release_info.version,
        "channel": manifest.channel,
        "severity": manifest.severity,
        "size": manifest.size,
        "title": manifest.title,
        "summary": manifest.summary,
        "release_notes_vi": manifest.release_notes_vi,
        "release_notes_en": manifest.release_notes_en,
        "migration_ids": [item.migration_id for item in plan.migrations],
        "packages": packages,
    }
    return update_info, status

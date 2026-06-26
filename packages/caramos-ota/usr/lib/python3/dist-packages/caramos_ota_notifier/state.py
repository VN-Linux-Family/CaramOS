"""State reading helpers for the desktop notifier."""

from __future__ import annotations

import json
from typing import Any

from caramos_ota.constants import RELEASE_FILE, TOOL_NAME
from caramos_ota.manifest import load_migration_manifest, load_migration_versions, resolve_migration_chain
from caramos_ota.models import ReleaseInfo

from .constants import STATE_FILE


def read_available_update() -> dict[str, Any] | None:
    """Read and validate state.json for a displayable available update."""

    try:
        if not STATE_FILE.exists():
            return None
        with STATE_FILE.open("r", encoding="utf-8") as handle:
            state = json.load(handle)
        if not isinstance(state, dict) or state.get("schema") != 1:
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
    """Return a safe, human-readable string for GTK labels."""

    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def normalize_package(pkg: object) -> dict[str, object]:
    """Normalize package entries from state into a predictable display dict."""

    if isinstance(pkg, dict):
        name = format_value(pkg.get("name") or pkg.get("package"), "Không rõ gói")
        current = format_value(
            pkg.get("current_version") or pkg.get("installed_version"),
            "Chưa cài",
        )
        available = format_value(
            pkg.get("available_version")
            or pkg.get("candidate_version")
            or pkg.get("min_version"),
            "Chưa rõ",
        )
        description = format_value(pkg.get("description"), "")
        return {
            "name": name,
            "current": current,
            "available": available,
            "description": description,
            "required": pkg.get("required"),
        }

    return {
        "name": format_value(pkg, "Không rõ gói"),
        "current": "Chưa rõ",
        "available": "Chưa rõ",
        "description": "",
        "required": None,
    }


def _read_release_info() -> ReleaseInfo | None:
    """Read installed CaramOS release metadata without invoking the CLI detector."""

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
    """Read the installed CaramOS version without invoking the CLI detector."""

    release_info = _read_release_info()
    return release_info.version if release_info else "Chưa rõ"


def read_no_update_status() -> dict[str, str]:
    """Return version metadata for the manual no-update dialog."""

    release_info = _read_release_info()
    current_version = release_info.version if release_info else "Chưa rõ"
    try:
        versions = load_migration_versions()
        latest_version = versions[-1] if versions else current_version
    except Exception:
        latest_version = current_version

    return {
        "current_version": current_version,
        "latest_version": latest_version,
        "channel": release_info.channel if release_info else "stable",
    }


def resolve_available_update_now() -> tuple[dict[str, Any] | None, dict[str, str]]:
    """Resolve migration availability directly for a manual notifier launch."""

    current_version = _read_release_version()
    status = read_no_update_status()
    if current_version == "Chưa rõ":
        return None, status

    try:
        chain = resolve_migration_chain(current_version)
        if not chain:
            return None, status

        release_info = _read_release_info()
        if release_info is None:
            return None, status
        manifests = [load_migration_manifest(version, release_info) for version in chain]
    except Exception:
        return None, status

    target = manifests[-1]
    notes_vi: list[str] = []
    notes_en: list[str] = []
    packages: list[dict[str, object]] = []
    previous_version = current_version
    for item in manifests:
        label = f"{previous_version} → {item.release}"
        notes_vi.extend(f"{label}: {note}" for note in (item.release_notes_vi or [item.summary]))
        notes_en.extend(f"{label}: {note}" for note in (item.release_notes_en or [item.summary]))
        packages.append(
            {
                "name": TOOL_NAME,
                "current_version": previous_version,
                "available_version": item.release,
                "description": item.summary,
                "required": True,
            }
        )
        previous_version = item.release

    status["latest_version"] = target.release
    manifest_sizes = [item.size for item in manifests if item.size]
    update_info = {
        "detected_at": "manual",
        "release": target.release,
        "to_version": target.release,
        "manifest_source": target.source,
        "current_version": current_version,
        "from_version": current_version,
        "channel": target.channel,
        "severity": target.severity,
        "size": " + ".join(manifest_sizes) if manifest_sizes else target.size,
        "title": target.title,
        "summary": target.summary,
        "release_notes_vi": notes_vi,
        "release_notes_en": notes_en,
        "packages": packages,
    }
    return update_info, status

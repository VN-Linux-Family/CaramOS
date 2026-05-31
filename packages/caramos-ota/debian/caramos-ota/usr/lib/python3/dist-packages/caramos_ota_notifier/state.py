"""State reading helpers for the desktop notifier."""

from __future__ import annotations

import json
from typing import Any

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

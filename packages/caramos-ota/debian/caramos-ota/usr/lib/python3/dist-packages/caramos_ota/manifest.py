"""OTA manifest parsing and validation."""

from __future__ import annotations

import json
import re

from .constants import EXIT_STATE, MANIFEST_FILE
from .errors import OtaError
from .models import Component, Manifest, ReleaseInfo

VALID_PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")


def validate_package_name(package: str) -> bool:
    """Return True when a package name is safe to pass as an APT argument."""

    return bool(VALID_PACKAGE.fullmatch(package))


def parse_manifest(release_info: ReleaseInfo) -> Manifest:
    """Load and validate the packaged OTA manifest."""

    try:
        with MANIFEST_FILE.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception as exc:
        raise OtaError(f"Error: Cannot read manifest: {exc}", EXIT_STATE) from exc

    if not isinstance(raw, dict) or raw.get("schema") != 1:
        schema = raw.get("schema") if isinstance(raw, dict) else "?"
        raise OtaError(f"Error: Unsupported manifest schema: {schema}", EXIT_STATE)
    if raw.get("codename") != release_info.codename:
        raise OtaError(
            f"Error: Manifest codename mismatch: {raw.get('codename')} vs {release_info.codename}",
            EXIT_STATE,
        )
    release = raw.get("release")
    if not isinstance(release, str) or not release:
        raise OtaError("Error: Manifest has no release field", EXIT_STATE)

    components: list[Component] = []
    for item in raw.get("components", []):
        if not isinstance(item, dict):
            raise OtaError("Error: Invalid component entry in manifest", EXIT_STATE)
        package = str(item.get("package", ""))
        if not validate_package_name(package):
            raise OtaError(f"Error: Invalid package name in manifest: {package}", EXIT_STATE)
        components.append(
            Component(
                package=package,
                min_version=str(item.get("min_version", "")),
                required=bool(item.get("required", False)),
                description=str(item.get("description", "")),
            )
        )

    return Manifest(
        release=release,
        codename=str(raw.get("codename", "")),
        release_notes_vi=[str(note) for note in raw.get("release_notes_vi", []) if isinstance(note, str)],
        release_notes_en=[str(note) for note in raw.get("release_notes_en", []) if isinstance(note, str)],
        components=components,
    )

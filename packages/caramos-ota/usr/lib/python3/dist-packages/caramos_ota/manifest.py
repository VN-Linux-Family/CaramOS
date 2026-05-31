"""OTA manifest fetching, parsing and validation."""

from __future__ import annotations

import json
import re
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .constants import (
    EXIT_STATE,
    MANIFEST_BASE_URL,
    MANIFEST_FETCH_TIMEOUT_SECONDS,
    MANIFEST_FILE,
    MANIFEST_MAX_BYTES,
    TOOL_NAME,
    TOOL_VERSION,
)
from .errors import OtaError
from .logging_utils import log_info, log_warn
from .models import Component, Manifest, ReleaseInfo

VALID_PACKAGE = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")
VALID_URL_PART = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ManifestFetchError(Exception):
    """Raised when the online manifest cannot be fetched safely."""


def validate_package_name(package: str) -> bool:
    """Return True when a package name is safe to pass as an APT argument."""

    return bool(VALID_PACKAGE.fullmatch(package))


def parse_manifest(release_info: ReleaseInfo) -> Manifest:
    """Load the online OTA manifest, falling back to the bundled manifest."""

    manifest_url = manifest_url_for(release_info)
    try:
        raw = fetch_online_manifest(manifest_url)
        source = manifest_url
        log_info(f"Using online manifest: {manifest_url}")
    except ManifestFetchError as exc:
        log_warn(f"Online manifest unavailable, using bundled manifest: {exc}")
        raw = load_bundled_manifest()
        source = str(MANIFEST_FILE)
    return validate_manifest(raw, release_info, source)


def manifest_url_for(release_info: ReleaseInfo) -> str:
    """Build the manifest URL for the detected CaramOS channel/codename."""

    if not VALID_URL_PART.fullmatch(release_info.channel):
        raise OtaError(f"Error: Invalid CaramOS channel for manifest URL: {release_info.channel}", EXIT_STATE)
    if not VALID_URL_PART.fullmatch(release_info.codename):
        raise OtaError(f"Error: Invalid CaramOS codename for manifest URL: {release_info.codename}", EXIT_STATE)
    return f"{MANIFEST_BASE_URL.rstrip('/')}/{release_info.channel}/{release_info.codename}/manifest.json"


def fetch_online_manifest(manifest_url: str) -> dict[str, Any]:
    """Fetch and decode the online manifest from the official HTTPS endpoint."""

    parsed = urlparse(manifest_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ManifestFetchError("manifest URL must be absolute HTTPS")

    request = Request(
        manifest_url,
        headers={
            "Accept": "application/json",
            "User-Agent": f"{TOOL_NAME}/{TOOL_VERSION}",
        },
        method="GET",
    )
    try:
        context = ssl.create_default_context()
        with urlopen(request, timeout=MANIFEST_FETCH_TIMEOUT_SECONDS, context=context) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise ManifestFetchError(f"HTTP status {status}")
            content_type = response.headers.get("Content-Type", "")
            if content_type and "json" not in content_type.lower():
                raise ManifestFetchError(f"unexpected Content-Type: {content_type}")
            payload = response.read(MANIFEST_MAX_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ManifestFetchError(str(exc)) from exc

    if len(payload) > MANIFEST_MAX_BYTES:
        raise ManifestFetchError("manifest is too large")
    try:
        raw = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestFetchError(f"invalid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestFetchError("manifest root must be an object")
    return raw


def load_bundled_manifest() -> dict[str, Any]:
    """Load the manifest bundled in the installed caramos-ota package."""

    try:
        with MANIFEST_FILE.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception as exc:
        raise OtaError(f"Error: Cannot read bundled manifest: {exc}", EXIT_STATE) from exc
    if not isinstance(raw, dict):
        raise OtaError("Error: Bundled manifest root must be an object", EXIT_STATE)
    return raw


def validate_manifest(raw: dict[str, Any], release_info: ReleaseInfo, source: str) -> Manifest:
    """Validate one decoded manifest object and return the typed model."""

    if raw.get("schema") != 1:
        schema = raw.get("schema", "?")
        raise OtaError(f"Error: Unsupported manifest schema from {source}: {schema}", EXIT_STATE)
    min_client_version = raw.get("min_client_version")
    if min_client_version is not None and not isinstance(min_client_version, str):
        raise OtaError(f"Error: Invalid min_client_version in manifest from {source}", EXIT_STATE)
    if raw.get("codename") != release_info.codename:
        raise OtaError(
            f"Error: Manifest codename mismatch from {source}: {raw.get('codename')} vs {release_info.codename}",
            EXIT_STATE,
        )
    release = raw.get("release")
    if not isinstance(release, str) or not release:
        raise OtaError(f"Error: Manifest from {source} has no release field", EXIT_STATE)

    components: list[Component] = []
    for item in raw.get("components", []):
        if not isinstance(item, dict):
            raise OtaError(f"Error: Invalid component entry in manifest from {source}", EXIT_STATE)
        package = str(item.get("package", ""))
        if not validate_package_name(package):
            raise OtaError(f"Error: Invalid package name in manifest from {source}: {package}", EXIT_STATE)
        min_version = str(item.get("min_version", ""))
        if not min_version:
            raise OtaError(f"Error: Missing min_version for package {package} in manifest from {source}", EXIT_STATE)
        components.append(
            Component(
                package=package,
                min_version=min_version,
                required=bool(item.get("required", False)),
                description=str(item.get("description", "")),
            )
        )

    return Manifest(
        release=release,
        codename=str(raw.get("codename", "")),
        source=source,
        min_client_version=min_client_version,
        release_notes_vi=[str(note) for note in raw.get("release_notes_vi", []) if isinstance(note, str)],
        release_notes_en=[str(note) for note in raw.get("release_notes_en", []) if isinstance(note, str)],
        components=components,
    )

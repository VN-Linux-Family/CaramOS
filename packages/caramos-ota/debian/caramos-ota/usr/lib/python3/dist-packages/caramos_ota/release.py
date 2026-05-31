"""CaramOS release detection."""

from __future__ import annotations

from pathlib import Path

from .constants import EXIT_NOT_CARAMOS, RELEASE_FILE, TOOL_NAME
from .logging_utils import log_error, log_info, print_ok
from .models import ReleaseInfo


def parse_key_value_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE file with optional double quotes."""

    values: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"')
    return values


def detect_caramos() -> ReleaseInfo:
    """Validate /etc/caramos-release and return parsed release information."""

    if not RELEASE_FILE.exists():
        print("Error: CaramOS not detected.")
        print("This updater can only run on CaramOS.")
        print(f"Missing: {RELEASE_FILE}")
        log_error(f"Release file not found: {RELEASE_FILE}")
        raise SystemExit(EXIT_NOT_CARAMOS)

    values = parse_key_value_file(RELEASE_FILE)
    info = ReleaseInfo(
        name=values.get("NAME", ""),
        version=values.get("VERSION", ""),
        codename=values.get("UBUNTU_CODENAME", ""),
        channel=values.get("CHANNEL", ""),
    )

    if info.name != "CaramOS":
        print("Error: CaramOS not detected.")
        print("This updater can only run on CaramOS.")
        print(f'Found NAME="{info.name}" in {RELEASE_FILE}')
        log_error(f"Wrong OS name: {info.name}")
        raise SystemExit(EXIT_NOT_CARAMOS)
    if info.codename != "noble":
        print(f"Error: Unsupported CaramOS codename: {info.codename}")
        print(f"This version of {TOOL_NAME} only supports codename 'noble'.")
        log_error(f"Unsupported codename: {info.codename}")
        raise SystemExit(EXIT_NOT_CARAMOS)
    if info.channel != "stable":
        print(f"Error: Unsupported CaramOS channel: {info.channel}")
        print(f"This version of {TOOL_NAME} only supports channel 'stable'.")
        log_error(f"Unsupported channel: {info.channel}")
        raise SystemExit(EXIT_NOT_CARAMOS)

    print_ok(f"CaramOS detected: {info.version}")
    log_info(f"CaramOS detected: {info.version} {info.codename} {info.channel}")
    return info

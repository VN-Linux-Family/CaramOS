"""Shared helpers for updating CaramOS version metadata files."""

from __future__ import annotations

import re
from pathlib import Path

_VERSION_RE = re.compile(r"^\d+(?:\.\d+){1,3}(?:[-+~][A-Za-z0-9.+:~_-]+)?$")


class VersionMetadataError(ValueError):
    """Raised when version metadata input is unsafe or invalid."""


def validate_version(version: str) -> str:
    """Validate a CaramOS version string and return it unchanged."""

    if not _VERSION_RE.fullmatch(version):
        raise VersionMetadataError(f"invalid CaramOS version: {version!r}")
    return version


def caramos_release_content(version: str) -> str:
    """Return /etc/caramos-release content for a stable CaramOS noble release."""

    version = validate_version(version)
    return (
        'NAME="CaramOS"\n'
        f'VERSION="{version}"\n'
        'CHANNEL="stable"\n'
        'UBUNTU_CODENAME="noble"\n'
    )


def os_release_content(version: str) -> str:
    """Return /etc/os-release content for CaramOS Cinnamon."""

    version = validate_version(version)
    return (
        'NAME="CaramOS"\n'
        f'VERSION="{version}"\n'
        'ID=caramos\n'
        'ID_LIKE="ubuntu debian linuxmint"\n'
        f'PRETTY_NAME="CaramOS {version} Cinnamon"\n'
        f'VERSION_ID="{version}"\n'
        'HOME_URL="https://github.com/VN-Linux-Family/CaramOS"\n'
        'SUPPORT_URL="https://github.com/VN-Linux-Family/CaramOS/issues"\n'
        'BUG_REPORT_URL="https://github.com/VN-Linux-Family/CaramOS/issues"\n'
        'PRIVACY_POLICY_URL="https://github.com/VN-Linux-Family/CaramOS"\n'
        'VERSION_CODENAME=wilma\n'
        'UBUNTU_CODENAME=noble\n'
        'CARAMOS_BASE="Linux Mint 22.3"\n'
    )


def lsb_release_content(version: str) -> str:
    """Return /etc/lsb-release content for CaramOS."""

    version = validate_version(version)
    return (
        'DISTRIB_ID=CaramOS\n'
        f'DISTRIB_RELEASE={version}\n'
        'DISTRIB_CODENAME=wilma\n'
        f'DISTRIB_DESCRIPTION="CaramOS {version} Cinnamon"\n'
    )


def linuxmint_info_content(version: str) -> str:
    """Return /etc/linuxmint/info content expected by Mint tools."""

    version = validate_version(version)
    return (
        f'RELEASE={version}\n'
        'CODENAME=wilma\n'
        'EDITION="Cinnamon"\n'
        f'DESCRIPTION="CaramOS {version} Cinnamon"\n'
        'DESKTOP=Gnome\n'
        'TOOLKIT=GTK\n'
        'NEW_FEATURES_URL=https://caramos.org/\n'
        'RELEASE_NOTES_URL=https://caramos.org/\n'
        'USER_GUIDE_URL=https://caramos.org/\n'
        f'GRUB_TITLE=CaramOS {version} Cinnamon\n'
    )


def issue_content(version: str) -> str:
    """Return /etc/issue content."""

    version = validate_version(version)
    return f"CaramOS {version} \\n \\l\n"


def issue_net_content(version: str) -> str:
    """Return /etc/issue.net content."""

    version = validate_version(version)
    return f"CaramOS {version}\n"


def version_metadata_files(version: str) -> dict[Path, str]:
    """Return every version metadata file that must be kept in sync."""

    version = validate_version(version)
    return {
        Path("/etc/caramos-release"): caramos_release_content(version),
        Path("/etc/os-release"): os_release_content(version),
        Path("/etc/lsb-release"): lsb_release_content(version),
        Path("/etc/linuxmint/info"): linuxmint_info_content(version),
        Path("/etc/issue"): issue_content(version),
        Path("/etc/issue.net"): issue_net_content(version),
    }


def write_version_metadata(version: str, *, dry_run: bool = False) -> list[Path]:
    """Write all CaramOS version metadata files and return changed paths."""

    changed: list[Path] = []
    for path, content in version_metadata_files(version).items():
        if path.exists() and path.read_text(encoding="utf-8") == content:
            continue
        changed.append(path)
        if dry_run:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return changed

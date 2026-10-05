"""Use the real Linux Mint base codename in the release files Mint tools read.

CaramOS ISOs up to 1.0.16 and the OTA release metadata wrote the codename "wilma" (Mint 22.0) although
CaramOS is built on Mint 22.3 "zena". Mint's System Reports then offers "Upgrade to Linux Mint 22.x",
an upgrade whose removals include power-profiles-daemon, and Software Sources would write Mint repo
lines for the wrong release. Only the codename lines change here; the rest of the files (CaramOS
branding and version) is left as it is and is rewritten by the OTA release finalisation.
"""

from __future__ import annotations

import re
from pathlib import Path

from caramos_ota_update.context import MigrationContext
from caramos_ota_update.version_metadata import MINT_BASE_CODENAME

DESCRIPTION = "Use the Linux Mint base codename so Mint tools stop offering a wrong release upgrade"

CODENAME_KEYS = (
    (Path("/etc/linuxmint/info"), "CODENAME"),
    (Path("/etc/os-release"), "VERSION_CODENAME"),
    (Path("/etc/lsb-release"), "DISTRIB_CODENAME"),
)


def fixed_content(content: str, key: str) -> str:
    """Return content with every `key=...` line set to the Mint base codename."""

    return re.sub(rf"^{key}=.*$", f"{key}={MINT_BASE_CODENAME}", content, flags=re.M)


def run(context: MigrationContext) -> None:
    for path, key in CODENAME_KEYS:
        if not path.is_file():
            context.log(f"skip missing {path}")
            continue
        current = path.read_text(encoding="utf-8")
        updated = fixed_content(current, key)
        if updated == current:
            context.log(f"{path}: {key} already {MINT_BASE_CODENAME}")
            continue
        context.log(f"{path}: set {key}={MINT_BASE_CODENAME}")
        if not context.dry_run:
            path.write_text(updated, encoding="utf-8")

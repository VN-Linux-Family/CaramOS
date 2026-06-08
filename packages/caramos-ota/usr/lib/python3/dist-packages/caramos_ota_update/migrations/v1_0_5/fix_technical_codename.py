"""Migration for 1.0.5: restore Linux Mint technical codename for repo tools."""

from __future__ import annotations

from caramos_ota_update.context import MigrationContext
from caramos_ota_update.version_metadata import write_version_metadata

FROM_VERSION = "1.0.4"
TO_VERSION = "1.0.5"
DESCRIPTION = "Restore VERSION_CODENAME/DISTRIB_CODENAME/CODENAME to wilma for add-apt-repository compatibility"


def run(context: MigrationContext) -> None:
    """Rewrite version metadata with Mint codename wilma and CaramOS branding."""

    if context.dry_run:
        for path in write_version_metadata(TO_VERSION, dry_run=True):
            context.log(f"[dry-run] update version metadata: {path}")
        return

    for path in write_version_metadata(TO_VERSION):
        context.log(f"updated version metadata: {path}")

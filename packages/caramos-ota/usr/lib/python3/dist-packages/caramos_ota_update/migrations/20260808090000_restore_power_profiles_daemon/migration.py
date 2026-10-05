"""Restore Cinnamon power profiles through power-profiles-daemon."""

from __future__ import annotations

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Replace TLP with power-profiles-daemon"


def run(context: MigrationContext) -> None:
    """Install and enable the power profiles backend used by Cinnamon."""

    context.apt_update()
    context.apt_replace(
        install=["power-profiles-daemon"],
        remove=["tlp", "tlp-rdw"],
    )
    context.ensure_service_enabled("power-profiles-daemon.service")

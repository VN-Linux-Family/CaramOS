"""Migration for PR #42: enable default ZRAM at 50% of RAM."""

from __future__ import annotations

from caramos_ota_update.context import MigrationContext

FROM_VERSION = "1.0.2"
TO_VERSION = "1.0.3"
DESCRIPTION = "PR #42: enable default ZRAM swap at 50% RAM with zstd compression"

_ZRAM_CONFIG = """[zram0]
zram-size = ram / 2
compression-algorithm = zstd
swap-priority = 100
"""


def run(context: MigrationContext) -> None:
    """Install and activate the same ZRAM defaults used by new ISO builds."""

    context.apt_update()
    context.apt_install(["systemd-zram-generator"])
    context.write_file_if_changed("/etc/systemd/zram-generator.conf", _ZRAM_CONFIG)
    context.run_command(["systemctl", "daemon-reload"])
    context.run_command(["systemctl", "restart", "systemd-zram-setup@zram0.service"])

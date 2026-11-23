"""The brightness of external monitors in the Control Center (ticket H-1183), on both editions.

A desktop computer's monitor takes its brightness from its own buttons, or over its cable through DDC/CI, which
ddcutil speaks. The Control Center of the package asks caramos-ddc (with ddcutil) for the monitors that answer and
shows a slider for each, under the volume; none when no monitor answers, as on a laptop alone, whose own screen keeps
the backlight slider. ddcutil (about 0.4 MB to download) is installed where it is missing; its udev rule gives the
I2C buses of the graphics card to the user at the screen. Linux makes those buses files with the i2c-dev module:
the package loads it at boot (/usr/lib/modules-load.d/caramos-ddc.conf), and it is loaded here too, so the slider
works without a restart. Not in a chroot (the ISO build), where there is no kernel of the system to load it into.
"""

from __future__ import annotations

from pathlib import Path

from caramos_ota_update.context import MigrationContext, MigrationContextError

DESCRIPTION = "Install ddcutil and load i2c-dev for the brightness of external monitors"

PACKAGE = "ddcutil"
MODULE = "i2c-dev"
SYSTEMD_RUNTIME = Path("/run/systemd/system")
LOADED = Path("/sys/module/i2c_dev")


def run(context: MigrationContext, systemd_runtime: Path = SYSTEMD_RUNTIME, loaded: Path = LOADED) -> None:
    installed = context.run_command(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", PACKAGE], allow_fail=True)
    if installed is not None and installed.returncode == 0 and installed.stdout.startswith("ii"):
        context.log(f"{PACKAGE} is installed")
    else:
        try:
            context.apt_install([PACKAGE], recommends=False)
        except MigrationContextError as exc:
            context.log(f"could not install {PACKAGE} ({exc}); the Control Center shows no slider for monitors")
    if not systemd_runtime.is_dir():
        context.log(f"no running system (a chroot?): {MODULE} loads at the next boot")
    elif loaded.exists():
        context.log(f"{MODULE} is loaded")
    else:
        context.run_command(["modprobe", MODULE], allow_fail=True)

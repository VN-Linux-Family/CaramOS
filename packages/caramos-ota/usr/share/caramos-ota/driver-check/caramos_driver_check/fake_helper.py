"""Development only: pretend to install drivers, to work on the window without root or the hardware.

    CARAMOS_DRIVER_CHECK_FAKE_HELPER=1 caramos-driver-check
    CARAMOS_DRIVER_CHECK_FAKE_HELPER=fail ...   the install fails
    CARAMOS_DRIVER_CHECK_FAKE_HELPER=space ...  the disk is too full (nothing is installed)
"""

from __future__ import annotations

import os
import sys
import time

from .events import emit


def main(argv: list[str]) -> int:
    targets = argv[1:]
    emit("stage", stage="update")
    for percent in range(0, 26, 5):
        emit("progress", percent=percent)
        time.sleep(0.15)
    if os.environ.get("CARAMOS_DRIVER_CHECK_FAKE_HELPER") == "space":
        emit("log", line="Space needed: 940 MiB to download, 2419 MiB once installed, new kernels: 7.0.0-42-generic")
        emit("space", path="/", need=4_100_000_000, free=1_200_000_000)
        emit("log", line="Not enough free space on /: 3910 MiB needed, 1144 MiB free")
        emit("done", ok=False, restart=False, packages=[], error="space")
        return 1
    emit("stage", stage="install")
    for percent in range(25, 96, 5):
        emit("progress", percent=percent)
        emit("log", line=f"Unpacking {targets[0] if targets else 'driver'} ({percent}%)")
        time.sleep(0.12)
    if os.environ.get("CARAMOS_DRIVER_CHECK_FAKE_HELPER") == "fail":
        emit("done", ok=False, restart=False, packages=[], error="apt")
        return 1
    emit("stage", stage="finish")
    emit("progress", percent=100)
    emit("done", ok=True, restart=True, packages=targets, error="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

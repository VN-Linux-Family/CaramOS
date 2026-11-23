"""Whether the disks have room for an install, before it starts.

An install that runs out of room halfway leaves dpkg broken, and every later install fails until it is fixed. Driver
Check measures what APT will download and unpack (caramos_driver_check.helper.needs) and checks it here; automatic
updates (caramos_ota.auto_update) check a fixed estimate, as the migrations decide what they install.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

MIB = 1024 * 1024
# Room kept beyond APT's own figures: the NVIDIA modules are linked while installing and are in no
# Installed-Size (about 200 MiB for 580), and a nearly full file system (btrfs above all) fails before it
# reaches zero. Asking for a little too much only means freeing a little more; too little breaks dpkg.
ROOT_MARGIN = 1024 * MIB
BOOT_MARGIN = 32 * MIB
# vmlinuz, System.map and config of one kernel, which sit in /boot next to its initramfs.
KERNEL_FILES = 64 * MIB


@dataclass(frozen=True)
class Needs:
    """What an install takes, as APT resolves it: bytes to download, bytes unpacked, and the kernels it adds."""

    download: int
    installed: int
    kernels: tuple[str, ...] = ()


@dataclass(frozen=True)
class Shortage:
    """A file system (by its mount point) without room for the install."""

    path: str
    need: int
    free: int


def mount_point(path: str, stat: Callable = os.stat) -> str:
    """The mount point of the file system path is on: its highest parent on the same device."""

    path = os.path.abspath(path)
    device = stat(path).st_dev
    while path != "/":
        parent = os.path.dirname(path)
        if stat(parent).st_dev != device:
            break
        path = parent
    return path


def shortages(need: Needs, archives: str, initramfs: int, *, stat: Callable = os.stat,
              statvfs: Callable = os.statvfs) -> list[Shortage]:
    """The file systems that lack room for the install.

    / takes the unpacked files, the archive cache the download, and /boot an initramfs for each new kernel plus
    the rebuilt one of the running kernel (the NVIDIA and DKMS packages rebuild it). When they share a file
    system, their needs add up there.
    """

    wanted = (
        ("/", max(need.installed, 0) + ROOT_MARGIN),
        ("/boot", len(need.kernels) * (initramfs + KERNEL_FILES) + initramfs + BOOT_MARGIN),
        (archives, need.download),
    )
    totals: dict[int, list] = {}
    for path, size in wanted:
        try:
            device = stat(path).st_dev
        except OSError:
            continue
        if device in totals:
            totals[device][1] += size
        else:
            totals[device] = [path, size]
    found = []
    for path, size in totals.values():
        info = statvfs(path)
        free = info.f_bavail * info.f_frsize
        if size > free:
            found.append(Shortage(mount_point(path, stat), size, free))
    return found

"""How CaramOS's own GTK 4 programs draw: Driver Check, Feedback & Help and Phòng máy (the App Center, in its own
package, has the same rule in caramos_app_center/renderer.py).

GTK 4 draws with OpenGL. Without a graphics card whose driver does OpenGL, the CPU runs OpenGL itself (llvmpipe), and
that is the heavy part of these programs, not Python. Measured on the 2 GB Xfce VM (2026-11-20): the App Center took
178-202 MB and 18-19 s of CPU to scroll 80 steps with OpenGL, and 105-118 MB and 13 s with cairo, GTK's own software
renderer; an empty libadwaita window took 152-213 MB with OpenGL and 73 MB with cairo, in C as in Python.

On a machine with a real graphics card OpenGL is smoother, above all on large screens, and it spares the CPU. So:
cairo when no graphics card has an Intel, AMD or NVIDIA driver, or when the machine has 4 GiB of memory or less; GTK's
own choice otherwise. A GSK_RENDERER the user set stays. Only these programs: Celluloid and other programs that show
OpenGL content need GTK's OpenGL renderer.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping
from pathlib import Path

# The kernel drivers of graphics cards that do OpenGL in hardware (the PCI driver of an NVIDIA card is "nvidia").
GPU_DRIVERS = frozenset({"i915", "xe", "amdgpu", "radeon", "nouveau", "nvidia"})
LOW_MEMORY_KIB = 4 * 1024 * 1024
DRM = Path("/sys/class/drm")
MEMINFO = Path("/proc/meminfo")


def gpu_drivers(drm: Path = DRM) -> set[str]:
    """The drivers of the graphics cards (card0, card1…; card0-HDMI-A-1 and the like are their outputs)."""

    drivers = set()
    for card in drm.glob("card*"):
        if not card.name[4:].isdigit():
            continue
        try:
            drivers.add((card / "device" / "driver").resolve(strict=True).name)
        except OSError:
            continue
    return drivers


def memory_kib(meminfo: Path = MEMINFO) -> int | None:
    try:
        for line in meminfo.read_text(encoding="ascii").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return None


def renderer(environ: Mapping[str, str], drivers: set[str], memory: int | None) -> str | None:
    """"cairo", or None for GTK's own choice."""

    if environ.get("GSK_RENDERER"):
        return None
    if not drivers & GPU_DRIVERS:
        return "cairo"
    if memory is not None and memory <= LOW_MEMORY_KIB:
        return "cairo"
    return None


def apply(environ: MutableMapping[str, str] | None = None) -> str | None:
    """Sets GSK_RENDERER for this program; call it before GTK opens its first window."""

    environ = os.environ if environ is None else environ
    choice = renderer(environ, gpu_drivers(), memory_kib())
    if choice:
        environ["GSK_RENDERER"] = choice
    return choice

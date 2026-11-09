"""What CaramOS knows about specific hardware beyond what the running kernel says.

Kept small on purpose: whether the kernel has a driver for a device comes from the device's modalias at
run time (hardware.SystemReader.modules_for), which stays right as kernels change. Listed here is only
what the kernel cannot tell: hardware that needs a driver from outside the kernel, cameras that need more
than a kernel driver, and which fingerprint readers libfprint supports.
"""

from __future__ import annotations

import re
from pathlib import Path

from .hardware import Device

LIBFPRINT_HWDB = "usr/lib/udev/hwdb.d/60-autosuspend-libfprint-2.hwdb"

BROADCOM = "14e4"
NVIDIA = "10de"
INTEL = "8086"

# Intel IPU6/IPU7 (drivers/media/pci/intel/ipu6): the image processor behind the MIPI cameras of many
# laptops since 2021. The kernel driver alone does not give apps a webcam.
INTEL_IPU = frozenset({
    "9a19",  # Tiger Lake
    "4e19",  # Jasper Lake
    "465d",  # Alder Lake-P
    "462e",  # Alder Lake-N
    "a75d",  # Raptor Lake-P
    "7d19",  # Meteor Lake
    "645d",  # Lunar Lake (IPU7)
    "b05d",  # Panther Lake (IPU7.5)
})

_IPU_NAME = re.compile(r"\bIPU\b|Imaging Signal Processor|Image Processing Unit", re.IGNORECASE)

# The image processor of Atom tablets (Bay Trail 0f38, Cherry Trail 22b8): its kernel driver (atomisp) is
# still in staging and gives apps no camera.
ATOM_ISP = frozenset({"0f38", "22b8"})

# USB vendors whose devices in laptops are fingerprint readers (touchpads are I2C or PS/2, not USB).
FINGERPRINT_VENDORS = frozenset({"27c6", "06cb", "138a", "2808", "1c7a", "10a5", "298d", "2541", "08ff", "147e"})
ELAN = "04f3"   # ELAN fingerprint readers are 04f3:0cxx; other ELAN USB devices are touchscreens

CANON = "04a9"

# Canon laser printers that speak Canon's own CAPT protocol (the captdriver developer's list, mounaiban/studycapt;
# names from usb.ids). The kernel's USB printer driver (usblp) takes them like any printer, so nothing looks
# wrong, but they print nothing without a CAPT driver. The udev rule 71-caramos-capt-printers.rules keeps the
# automatic printer setup from giving them an unrelated PostScript driver; keep its list in step.
CAPT_PRINTERS = {
    "260a": "LBP810",
    "2617": "LBP1210",
    "262b": "LBP1120",
    "2636": "LBP3200",
    "2654": "LBP3600",
    "2657": "LBP3210",
    "266a": "LBP3000",
    "266e": "LBP5200",
    "2676": "LBP2900/LBP2900B",
    "2679": "LBP5000",
    "267e": "LBP3300",
    "268b": "LBP3500",
    "26a1": "LBP5300",
    "26a4": "LBP5100",
    "26b9": "LBP3310",
    "26ba": "LBP5050",
    "26da": "LBP3010/LBP3018/LBP3050",
    "26db": "LBP3100/LBP3108/LBP3150",
    "26ea": "LBP9100C",
    "26f1": "LBP7200C",
    "26ff": "LBP6300",
    "271a": "LBP6000/LBP6018",
    "271b": "LBP6200",
    "271c": "LBP7010C/LBP7018C",
    "2771": "LBP6020",
}
# The models the open-source captdriver drives (package printer-driver-captdriver in the CaramOS PPA, whose
# Modaliases list the same IDs); it works on the first two and is experimental on the others.
CAPTDRIVER_PACKAGE = "printer-driver-captdriver"
CAPTDRIVER_MODELS = ("2676", "26da", "266a", "26db", "271a")
CAPTDRIVER_WORKS = frozenset({"2676", "26da"})


def broadcom_wifi(device: Device) -> bool:
    """Broadcom Wi-Fi: needs Broadcom's driver (bcmwl) or downloaded b43 firmware, both outside the kernel."""

    return device.bus == "pci" and device.vendor == BROADCOM and device.pci_class.startswith("0280")


def nvidia_gpu(device: Device) -> bool:
    return device.bus == "pci" and device.vendor == NVIDIA and device.pci_class.startswith(("0300", "0302", "0380"))


def intel_ipu(device: Device) -> bool:
    if device.bus != "pci" or device.vendor != INTEL or not device.pci_class.startswith("0480"):
        return False
    return device.product in INTEL_IPU or bool(_IPU_NAME.search(device.name))


def atom_isp(device: Device) -> bool:
    return device.bus == "pci" and device.vendor == INTEL and device.product in ATOM_ISP


def fingerprint_like(device: Device) -> bool:
    """A USB device that is very likely a fingerprint reader, whether or not libfprint knows it."""

    if device.bus != "usb":
        return False
    if device.vendor in FINGERPRINT_VENDORS:
        return True
    return device.vendor == ELAN and device.product.startswith("0c")


def capt_printer(device: Device) -> bool:
    """A Canon printer that needs a CAPT driver (LBP2900 and family)."""

    return device.bus == "usb" and device.vendor == CANON and device.product in CAPT_PRINTERS


def read_libfprint_support(root: str | Path = "/") -> dict[str, str]:
    """{"04f3:0c7e": "elanmoc", "27c6:5395": ""}: the libfprint driver of each known reader, "" if unsupported.

    libfprint's hwdb lists the supported readers under "# Supported by libfprint driver <name>" and the
    readers it knows it cannot drive under "# Known unsupported devices".
    """

    try:
        text = (Path(root) / LIBFPRINT_HWDB).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    support: dict[str, str] = {}
    driver: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("# Supported by libfprint driver "):
            driver = line.rsplit(" ", 1)[1]
        elif line.lower().startswith("# known unsupported"):
            driver = ""
        elif line.startswith("usb:v") and driver is not None and len(line) >= 14:
            # usb:v04F3p0C7E*
            vendor, product = line[5:9].lower(), line[10:14].lower()
            support.setdefault(f"{vendor}:{product}", driver)
    return support

"""Driver packages Ubuntu recommends for this computer, the same list Driver Manager shows.

UbuntuDrivers (ubuntu-drivers-common) matches each device's modalias against the Modaliases field of the
driver packages in the APT lists, and marks one NVIDIA driver as recommended. It loads the APT cache and reads
the record of every package: about 6 s of a CPU core on a recent PC, half a minute or more on an old laptop,
and from the live USB every list (about 280 MB) is read through the compressed image. Run inside the window,
that froze old computers in the live session. So lookup() asks it only when its answer can matter (wanted()),
and in a separate process at the lowest CPU and disk priority, with a time and memory limit.

Only drivers Ubuntu itself installs automatically are offered for one-click install (NVIDIA, Broadcom
Wi-Fi, VirtualBox and VMware guest tools); anything else stays with Driver Manager.
"""

from __future__ import annotations

import fnmatch
import json
import re
import resource
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from . import knowledge
from .hardware import PCI_ADDRESS, PCI_DISPLAY, USB_DEVICE, Snapshot

# Ubuntu's own auto-install list (UbuntuDrivers.detect.auto_install_filter), without the OEM archives.
ONE_CLICK = ("nvidia-driver-*", "bcmwl*", "broadcom-sta-dkms", "virtualbox-guest*", "open-vm-tools*")
# Packages the CaramOS USB stick carries: Driver Check can install them without internet.
ON_INSTALL_MEDIA = ("bcmwl-kernel-source", "broadcom-sta-dkms")
PREFERRED = ("bcmwl-kernel-source", "broadcom-sta-dkms")
NVIDIA_DRIVER = re.compile(r"^nvidia-driver-(?P<flavour>\d+(?:-server)?(?:-open)?)$")
# VirtualBox and VMware virtual hardware: their guest tools are one-click drivers.
GUEST_VENDORS = frozenset({"80ee", "15ad"})
LOOKUP_TIMEOUT = 180                # seconds; a busy old computer gets this long, then the window goes on without
LOOKUP_MEMORY = 2 * 1024 ** 3       # address space of the lookup process


@dataclass(frozen=True)
class DriverProposal:
    package: str          # "nvidia-driver-580-open", "bcmwl-kernel-source"
    target: str           # what the helper installs: "nvidia:580-open" or the package name
    address: str          # the PCI address or USB device it drives ("0000:01:00.0", "1-2"), "" if unknown
    vendor: str = ""
    model: str = ""
    free: bool = False
    offline: bool = False  # can be installed from the CaramOS USB stick without internet

    @property
    def nvidia(self) -> bool:
        return self.package.startswith("nvidia-driver-")

    @property
    def version(self) -> str:
        """580 for nvidia-driver-580-open; "" for other drivers."""

        match = NVIDIA_DRIVER.match(self.package)
        return match.group("flavour").split("-")[0] if match else ""

    @property
    def open_kernel_modules(self) -> bool:
        return self.nvidia and self.package.endswith("-open")


def one_click(package: str) -> bool:
    return any(fnmatch.fnmatch(package, pattern) for pattern in ONE_CLICK)


def install_target(package: str) -> str:
    """nvidia-driver-580-open -> nvidia:580-open (ubuntu-drivers then adds the signed kernel modules)."""

    match = NVIDIA_DRIVER.match(package)
    return f"nvidia:{match.group('flavour')}" if match else package


def address_of(syspath: str) -> str:
    for part in reversed(Path(syspath).parts):
        if PCI_ADDRESS.match(part) or USB_DEVICE.match(part):
            return part
    return ""


def choose(drivers: dict[str, dict]) -> str:
    """The package to propose among a device's drivers: the recommended desktop one."""

    candidates = [name for name, info in drivers.items() if not info.get("builtin") and one_click(name)]
    # Server drivers are for headless machines; Driver Manager hides them too.
    desktop = [name for name in candidates if not re.search(r"-server(-open)?$", name)]
    recommended = [name for name in desktop if drivers[name].get("recommended")]
    if recommended:
        return recommended[0]
    if len(desktop) == 1:
        return desktop[0]
    # Ubuntu's Broadcom package first; broadcom-sta-dkms is Debian's build of the same driver.
    for name in PREFERRED:
        if name in desktop:
            return name
    nvidia = sorted((name for name in desktop if NVIDIA_DRIVER.match(name)),
                    key=lambda name: (int(NVIDIA_DRIVER.match(name).group("flavour").split("-")[0]),
                                      name.endswith("-open")))
    return nvidia[-1] if nvidia else ""


def proposals_from(devices: dict[str, dict], installed, usable=lambda package: True) -> list[DriverProposal]:
    """Proposals from UbuntuDrivers.detect.system_device_drivers() output.

    installed(package) -> bool: fully installed; usable(package) -> bool: it can work with the running kernel.
    """

    proposals = []
    for syspath, info in sorted(devices.items()):
        if info.get("manual_install"):
            continue   # a driver installed by hand from NVIDIA's site: leave it alone
        drivers = info.get("drivers") or {}
        if any(installed(name) for name, details in drivers.items() if not details.get("builtin")):
            continue   # one of its drivers is already installed
        drivers = {name: details for name, details in drivers.items() if usable(name)}
        package = choose(drivers)
        if not package:
            continue
        proposals.append(DriverProposal(
            package=package,
            target=install_target(package),
            address=address_of(syspath),
            vendor=str(info.get("vendor") or ""),
            model=str(info.get("model") or ""),
            free=bool(drivers[package].get("free")),
            offline=package in ON_INSTALL_MEDIA,
        ))
    return proposals


def wanted(snapshot: Snapshot) -> str:
    """Why UbuntuDrivers is worth asking on this computer; "" when its answer cannot matter.

    Only one-click drivers (ONE_CLICK) are proposed: for an NVIDIA card not on the NVIDIA driver (not in the live
    session, where it comes after installing), a Broadcom Wi-Fi card without a driver, VirtualBox or VMware.
    """

    reasons = []
    # An NVIDIA driver dpkg could not finish needs a replacement, though the card may still run on it.
    nvidia_broken = any(package.startswith(("nvidia-", "linux-modules-nvidia-")) for package in snapshot.unfinished_packages)
    for device in snapshot.pci:
        if device.vendor == knowledge.NVIDIA and device.pci_class_is(*PCI_DISPLAY) and not snapshot.live \
                and (device.driver != "nvidia" or nvidia_broken):
            reasons.append(f"NVIDIA {device.id}")
        elif knowledge.broadcom_wifi(device) and not device.net:
            reasons.append(f"Broadcom Wi-Fi {device.id}")
        elif device.vendor in GUEST_VENDORS:
            reasons.append(f"guest tools {device.id}")
    return ", ".join(dict.fromkeys(reasons))


@dataclass(frozen=True)
class Lookup:
    proposals: tuple[DriverProposal, ...] = ()
    outcome: str = "skipped"   # skipped, done, timeout or failed
    seconds: float = 0.0
    detail: str = ""           # why it ran or did not, what failed


def _lookup_command() -> list[str]:
    folder = str(Path(__file__).resolve().parents[1])
    code = (f"import sys; sys.path.insert(0, {folder!r}); "
            "from caramos_driver_check.drivers import print_proposals; print_proposals()")
    command = [sys.executable, "-I", "-c", code]
    for tool, options in (("nice", ["-n", "19"]), ("ionice", ["-c", "3"])):
        path = shutil.which(tool)
        if path:
            command = [path, *options, *command]
    return command


def lookup(snapshot: Snapshot, timeout: float = LOOKUP_TIMEOUT) -> Lookup:
    """The proposals for this computer, from UbuntuDrivers in a low-priority process when they can matter."""

    reason = wanted(snapshot)
    if not reason:
        return Lookup(detail="no NVIDIA card to set up, Broadcom Wi-Fi without driver or VirtualBox/VMware")
    start = time.monotonic()
    try:
        done = subprocess.run(_lookup_command(), check=False, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return Lookup(outcome="timeout", seconds=time.monotonic() - start, detail=reason)
    except OSError as exc:
        return Lookup(outcome="failed", seconds=time.monotonic() - start, detail=f"{reason}: {exc}")
    seconds = time.monotonic() - start
    try:
        found = tuple(DriverProposal(**item) for item in json.loads(done.stdout or "null"))
    except (TypeError, ValueError):
        error = (done.stderr or "").strip().splitlines()[-1:] or [f"exit {done.returncode}"]
        return Lookup(outcome="failed", seconds=seconds, detail=f"{reason}: {error[0][:200]}")
    return Lookup(found, "done", seconds, reason)


def print_proposals() -> None:
    """The lookup process: the proposals as JSON on stdout."""

    resource.setrlimit(resource.RLIMIT_AS, (LOOKUP_MEMORY, LOOKUP_MEMORY))
    print(json.dumps([asdict(proposal) for proposal in find_proposals()]))


def find_proposals() -> list[DriverProposal]:
    """Ask UbuntuDrivers, in this process; an empty list when it is missing or the APT cache cannot be read."""

    try:
        import apt_pkg
        from UbuntuDrivers import detect
    except ImportError:
        return []
    try:
        apt_pkg.init_config()
        apt_pkg.init_system()
        cache = apt_pkg.Cache(None)
        devices = detect.system_device_drivers(cache)
    except Exception:
        return []

    def installed(name: str) -> bool:
        # A driver dpkg could not finish (half-configured) does not count: it needs a replacement.
        try:
            package = cache[name]
        except KeyError:
            return False
        return package.current_ver is not None and package.current_state == apt_pkg.CURSTATE_INSTALLED

    def usable(name: str) -> bool:
        # An NVIDIA driver needs signed modules for the kernel: Ubuntu recommends 470 for Maxwell and Pascal
        # cards (GeForce 900, 1000, MX), but 470 has none for Linux 6.12 and later and its DKMS module no
        # longer builds, so installing it left dpkg broken and every later install failed (ticket H-1094).
        # get_linux_modules_metapackage() finds the modules the helper installs, those of the kernel series.
        if not NVIDIA_DRIVER.match(name):
            return True
        try:
            modules = detect.get_linux_modules_metapackage(cache, name)
        except Exception:
            return False
        # Without signed modules it answers nvidia-dkms-<version>: a build that may well fail.
        return bool(modules) and modules.startswith("linux-modules-nvidia-")

    return proposals_from(devices, installed, usable)

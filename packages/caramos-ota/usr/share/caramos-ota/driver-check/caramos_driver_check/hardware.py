"""The machine's hardware and the drivers running it, read from sysfs, /proc and the udev database.

Everything here works without root and in well under a second, so the check can run at every login.
Paths are looked up under `root`, so the tests can build a fake system tree.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

CommandRunner = Callable[[Sequence[str], float], "subprocess.CompletedProcess[str]"]

PCI_ADDRESS = re.compile(r"^[0-9a-f]{4}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]$")
USB_DEVICE = re.compile(r"^\d+-[\d.]+$")
SECURE_BOOT_VARIABLE = "sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
MODPROBE_DIRS = ("etc/modprobe.d", "run/modprobe.d", "usr/lib/modprobe.d", "lib/modprobe.d")
# "install <module> /bin/false" turns a module off as "blacklist" does, and also for explicit loads.
DISABLING_COMMANDS = frozenset({"/bin/false", "/bin/true", "/usr/bin/false", "/usr/bin/true", "false", "true"})
DPKG_STATUS = "var/lib/dpkg/status"
UNFINISHED_STATES = frozenset({"half-installed", "unpacked", "half-configured"})
# Drivers for Canon CAPT printers, by a file each installs: the open-source captdriver (its CUPS filter) and
# Canon's own driver (its daemon, package cndrvcups-capt).
CAPT_DRIVER_FILES = (("captdriver", "usr/lib/cups/filter/rastertocapt"), ("canon", "usr/sbin/ccpd"))

# PCI class prefixes (class + subclass) the check looks at.
PCI_ETHERNET = "0200"
PCI_WIFI = "0280"
PCI_DISPLAY = ("0300", "0302", "0380")
PCI_AUDIO = ("0401", "0403")
PCI_CAMERA = "0480"   # Intel IPU, the chip behind the MIPI cameras of recent laptops
# Other user-facing devices that should have a driver: USB controllers, SD card readers, wireless
# controllers and Realtek card readers, which report "unassigned class" ff00.
PCI_OTHER = ("0c03", "0805", "0d", "ff00")

# USB interface classes: audio, communications, HID, printer, mass storage, CDC data, video.
USB_STANDARD_CLASSES = frozenset({"01", "02", "03", "07", "08", "0a", "0e"})
USB_VIDEO = "0e"
USB_VENDOR_SPECIFIC = "ff"
# Devices on the platform bus that the check looks at, by ACPI hardware ID: the Intel SST sound engines of
# Atom tablets (Bay Trail, Cherry Trail) and Haswell/Broadwell laptops, and Bluetooth chips on a serial port
# (Broadcom, Intel, Realtek), common in Atom tablets. Without them those computers looked as if they had no
# sound and no Bluetooth at all (GitHub issue #80, a Lenovo Yoga Book).
ACPI_AUDIO = {
    "80860F28": "Intel Bay Trail SST audio",
    "808622A8": "Intel Cherry Trail SST audio",
    "INT33C8": "Intel Haswell SST audio",
    "INT3438": "Intel Broadwell SST audio",
}
ACPI_BLUETOOTH = re.compile(r"^(?:BCM2E[0-9A-F]{2}|INT33E[13]|OBDA8723)$")
_ACPI_BLUETOOTH_VENDORS = {"B": "Broadcom", "I": "Intel", "O": "Realtek"}
# Sound cards of test modules (snd-dummy, snd-aloop, snd-virmidi), which belong to no hardware.
VIRTUAL_SOUND_CARDS = frozenset({"Dummy", "Loopback", "VirMIDI"})
# A phone sharing its connection over a USB cable (USB tethering).
PHONE_NET_DRIVERS = frozenset({"rndis_host", "ipheth"})
# Names of USB Wi-Fi adapters in the USB ID database or their own product string.
WIFI_NAME = re.compile(r"802\.11|wireless lan|\bwlan\b|wi-?fi", re.IGNORECASE)

SHORT_VENDOR_NAMES = {
    "8086": "Intel", "8087": "Intel", "10de": "NVIDIA", "1002": "AMD", "1022": "AMD", "14e4": "Broadcom",
    "10ec": "Realtek", "0bda": "Realtek", "14c3": "MediaTek", "0e8d": "MediaTek", "168c": "Qualcomm Atheros",
    "0cf3": "Qualcomm Atheros", "17cb": "Qualcomm", "1969": "Qualcomm Atheros", "11ab": "Marvell",
    "1b4b": "Marvell", "27c6": "Goodix", "06cb": "Synaptics", "04f3": "ELAN", "138a": "Validity",
    "2808": "FocalTech", "1c7a": "EgisTec", "13d3": "IMC Networks", "0489": "Foxconn", "04ca": "Lite-On",
    "148f": "Ralink", "2357": "TP-Link", "1f0a": "Motorcomm", "1d6a": "Aquantia", "1dbe": "Inventec",
}
_VENDOR_SUFFIX = re.compile(
    r"[ ,]+(corporation|corp\.?|inc\.?( and subsidiaries)?|co\.?,? ?ltd\.?|ltd\.?|limited|"
    r"semiconductor.*|technology.*|technologies.*|electronics.*|international.*)$",
    re.IGNORECASE,
)
_DEVICE_WORDS = re.compile(
    r"wi-?fi|wireless|wlan|ethernet|gigabit|bluetooth|geforce|quadro|radeon|graphics|audio|\b(ax|ac|be)\d{3}",
    re.IGNORECASE,
)
# "iwlwifi 0000:00:14.3: Direct firmware load for iwlwifi-so-a0-gf-a0-89.ucode failed with error -2"
_FIRMWARE_LINE = re.compile(
    r"^(?P<driver>\S+) (?P<device>[^\s:]+(?::[^\s:]+)*): "
    r"(?:Direct firmware load for (?P<file>\S+) failed with error|firmware: failed to load (?P<file2>\S+))"
)


@dataclass(frozen=True)
class UsbInterface:
    number: str       # "1.0"
    cls: str          # interface class: "e0" wireless controller, "0e" video, "ff" vendor-specific
    subclass: str
    protocol: str
    driver: str = ""
    modalias: str = ""

    @property
    def bluetooth(self) -> bool:
        return (self.cls, self.subclass, self.protocol) == ("e0", "01", "01")


@dataclass(frozen=True)
class NetInterface:
    name: str
    wireless: bool
    up: bool
    driver: str = ""
    bus: str = ""
    address: str = ""

    @property
    def phone(self) -> bool:
        return self.driver in PHONE_NET_DRIVERS


@dataclass(frozen=True)
class Device:
    bus: str                         # "pci", "usb" or "acpi"
    address: str                     # "0000:00:14.3", "3-10" or "808622A8:00"
    vendor: str                      # "8086"; empty for ACPI devices
    product: str                     # "51f0"; the ACPI hardware ID ("808622A8") for ACPI devices
    name: str
    vendor_name: str = ""            # "Intel"
    driver: str = ""                 # PCI and ACPI devices; USB drivers bind to interfaces
    modalias: str = ""
    pci_class: str = ""              # "028000"
    subsystem: str = ""              # "8086:0094"
    interfaces: tuple[UsbInterface, ...] = ()
    net: tuple[str, ...] = ()        # network interfaces of the device
    # ALSA cards and Bluetooth adapters (hci0) of the device. An ACPI device's card or adapter hangs off
    # another device in sysfs, so it gets those outside PCI and USB.
    sound_cards: int = 0
    bluetooth: tuple[str, ...] = ()
    video_nodes: int = 0             # /dev/video* nodes of the device
    # Kernel modules whose aliases match the device, which of them are loaded, which were installed after
    # this boot (waiting for a restart) and which come from DKMS (signed with the MOK key under Secure
    # Boot). Only filled in for devices the check looks at that have no working driver.
    modules: tuple[str, ...] = ()
    loaded_modules: tuple[str, ...] = ()
    new_modules: tuple[str, ...] = ()
    dkms_modules: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return self.product if self.bus == "acpi" else f"{self.vendor}:{self.product}"

    @property
    def key(self) -> str:
        return f"{self.bus}:{self.id}"

    def pci_class_is(self, *prefixes: str) -> bool:
        return self.bus == "pci" and self.pci_class.startswith(prefixes)

    def interfaces_of(self, *classes: str) -> tuple[UsbInterface, ...]:
        return tuple(interface for interface in self.interfaces if interface.cls in classes)

    @property
    def bluetooth_interfaces(self) -> tuple[UsbInterface, ...]:
        return tuple(interface for interface in self.interfaces if interface.bluetooth)

    @property
    def looks_like_usb_wifi(self) -> bool:
        """A USB Wi-Fi adapter: vendor-specific interfaces only, and a Wi-Fi name."""

        if self.bus != "usb" or self.bluetooth_interfaces or not WIFI_NAME.search(self.name):
            return False
        return all(interface.cls == USB_VENDOR_SPECIFIC for interface in self.interfaces)

    def hardware_page(self) -> str:
        """The device on linux-hardware.org: which drivers and kernels work for it, reported by users."""

        if self.bus == "acpi":
            return ""   # the site lists PCI and USB devices
        if self.bus == "pci" and self.subsystem:
            return "https://linux-hardware.org/?id=pci:%s-%s-%s" % (
                self.vendor, self.product, self.subsystem.replace(":", "-"))
        return f"https://linux-hardware.org/?id={self.bus}:{self.vendor}-{self.product}"


@dataclass(frozen=True)
class RfkillSwitch:
    kind: str     # "wlan", "bluetooth", "wwan"
    soft: bool    # turned off in software (airplane mode, the Wi-Fi switch in the panel)
    hard: bool    # turned off by a switch, an Fn key or the BIOS


@dataclass(frozen=True)
class FirmwareError:
    driver: str   # "iwlwifi" or "bluetooth"
    device: str   # "0000:00:14.3" or "hci0"
    file: str     # "iwlwifi-so-a0-gf-a0-89.ucode"


@dataclass(frozen=True)
class Snapshot:
    pci: tuple[Device, ...] = ()
    usb: tuple[Device, ...] = ()
    acpi: tuple[Device, ...] = ()
    net: tuple[NetInterface, ...] = ()
    rfkill: tuple[RfkillSwitch, ...] = ()
    connected: bool = False          # a default route through a real network interface
    kernel: str = ""
    live: bool = False               # running from the CaramOS USB
    virtual: bool = False            # a virtual machine
    secure_boot: bool = False
    firmware_errors: tuple[FirmwareError, ...] = ()
    cmdline: str = ""                # the kernel command line
    # Modules modprobe refuses to load: (module, where: a modprobe.d file or "the kernel command line").
    blacklists: tuple[tuple[str, str], ...] = ()
    # Packages dpkg could not finish installing (unpacked, half-configured): apt fails until they are fixed.
    unfinished_packages: tuple[str, ...] = ()
    # Drivers for Canon CAPT printers that are installed: "captdriver" and/or "canon" (CAPT_DRIVER_FILES).
    capt_drivers: tuple[str, ...] = ()

    def boot_options(self) -> tuple[str, ...]:
        return tuple(self.cmdline.split())

    def blacklisted(self, module: str) -> str:
        """Where a module is blacklisted, "" when it is not."""

        name = module.replace("-", "_")
        return next((where for blocked, where in self.blacklists if blocked == name), "")

    @property
    def devices(self) -> tuple[Device, ...]:
        return self.pci + self.usb + self.acpi


def run_command(command: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        env={**os.environ, "LC_ALL": "C"},
    )


def _hex(value: str) -> str:
    value = value.strip().lower()
    return value[2:] if value.startswith("0x") else value


def _short_vendor(vendor_id: str, database_name: str) -> str:
    if vendor_id in SHORT_VENDOR_NAMES:
        return SHORT_VENDOR_NAMES[vendor_id]
    return _VENDOR_SUFFIX.sub("", database_name.strip())


def friendly_model(model: str) -> str:
    """The marketing name in a chip name from the PCI database.

    "Alder Lake-P PCH CNVi WiFi (Wi-Fi 6E AX211 160MHz)" -> "Wi-Fi 6E AX211 160MHz" (udev appends the
    subsystem name in parentheses), "TU117M [GeForce GTX 1650 Mobile / Max-Q]" -> the bracketed name.
    A subsystem name that is a computer ("(QEMU Virtual Machine)", "(XPS 15 7590)") is dropped.
    """

    model = model.strip()
    subsystem = re.search(r"\s*\(([^()]*)\)$", model)
    base = model[:subsystem.start()].strip() if subsystem else model
    if subsystem and _DEVICE_WORDS.search(subsystem.group(1)):
        return subsystem.group(1).strip()
    bracket = re.findall(r"\[([^\[\]]+)\]", base)
    if bracket:
        return bracket[-1].strip()
    return base or model


def _compose_name(vendor: str, model: str) -> str:
    model = friendly_model(model)
    if not vendor:
        return model
    if not model:
        return vendor
    if model.lower().startswith(vendor.lower()):
        return model
    return f"{vendor} {model}"


class SystemReader:
    """Reads one snapshot of the hardware; `root` and `runner` are replaced in the tests."""

    def __init__(self, root: str | Path = "/", runner: CommandRunner = run_command) -> None:
        self.root = Path(root)
        self.runner = runner

    # Low-level helpers -------------------------------------------------------------------------

    def _path(self, relative: str) -> Path:
        return self.root / relative.lstrip("/")

    @staticmethod
    def _read(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip()
        except (OSError, ValueError):
            return ""

    @staticmethod
    def _link_name(path: Path) -> str:
        try:
            return os.path.basename(os.readlink(path))
        except OSError:
            return ""

    @staticmethod
    def _entries(directory: Path) -> list[Path]:
        try:
            return sorted(directory.iterdir())
        except OSError:
            return []

    def _udev(self, key: str) -> dict[str, str]:
        properties: dict[str, str] = {}
        for line in self._read(self._path(f"run/udev/data/{key}")).splitlines():
            if line.startswith("E:") and "=" in line:
                name, value = line[2:].split("=", 1)
                properties[name] = value
        return properties

    def _run(self, command: Sequence[str], timeout: float) -> str | None:
        try:
            completed = self.runner(command, timeout)
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout or ""

    @staticmethod
    def _owner(class_device: Path) -> tuple[str, str] | None:
        """The PCI or USB device a network interface, sound card, hci or video node belongs to."""

        link = class_device / "device"
        if not os.path.lexists(link):
            return None   # lo, bridges, VPNs and containers have no device
        for part in reversed(Path(os.path.realpath(link)).parts):
            if USB_DEVICE.match(part):
                return "usb", part
            if PCI_ADDRESS.match(part):
                return "pci", part
        return None

    def _owned(self, class_name: str, pattern: str) -> dict[tuple[str, str], list[str]]:
        owned: dict[tuple[str, str], list[str]] = {}
        for entry in self._entries(self._path(f"sys/class/{class_name}")):
            if not re.fullmatch(pattern, entry.name):
                continue
            owner = self._owner(entry)
            if owner is not None:
                owned.setdefault(owner, []).append(entry.name)
        return owned

    # Devices -----------------------------------------------------------------------------------

    def pci_devices(self) -> list[Device]:
        devices = []
        for entry in self._entries(self._path("sys/bus/pci/devices")):
            vendor = _hex(self._read(entry / "vendor"))
            product = _hex(self._read(entry / "device"))
            if not vendor or not product:
                continue
            subsystem_vendor = _hex(self._read(entry / "subsystem_vendor"))
            subsystem_device = _hex(self._read(entry / "subsystem_device"))
            udev = self._udev(f"+pci:{entry.name}")
            vendor_name = _short_vendor(vendor, udev.get("ID_VENDOR_FROM_DATABASE", ""))
            name = _compose_name(vendor_name, udev.get("ID_MODEL_FROM_DATABASE", ""))
            devices.append(
                Device(
                    bus="pci",
                    address=entry.name,
                    vendor=vendor,
                    product=product,
                    name=name or f"PCI {vendor}:{product}",
                    vendor_name=vendor_name,
                    driver=self._link_name(entry / "driver"),
                    modalias=self._read(entry / "modalias"),
                    pci_class=_hex(self._read(entry / "class")).rjust(6, "0"),
                    subsystem=f"{subsystem_vendor}:{subsystem_device}" if subsystem_vendor else "",
                )
            )
        return devices

    def usb_devices(self) -> list[Device]:
        entries = self._entries(self._path("sys/bus/usb/devices"))
        interfaces: dict[str, list[UsbInterface]] = {}
        for entry in entries:
            if ":" not in entry.name:
                continue
            device_name, number = entry.name.split(":", 1)
            interfaces.setdefault(device_name, []).append(
                UsbInterface(
                    number=number,
                    cls=self._read(entry / "bInterfaceClass").lower(),
                    subclass=self._read(entry / "bInterfaceSubClass").lower(),
                    protocol=self._read(entry / "bInterfaceProtocol").lower(),
                    driver=self._link_name(entry / "driver"),
                    modalias=self._read(entry / "modalias"),
                )
            )
        devices = []
        for entry in entries:
            # Root hubs are "usb1"; hubs have device class 09.
            if not USB_DEVICE.match(entry.name) or self._read(entry / "bDeviceClass") == "09":
                continue
            vendor = self._read(entry / "idVendor").lower()
            product = self._read(entry / "idProduct").lower()
            if not vendor or not product:
                continue
            node = self._read(entry / "dev")
            udev = self._udev(f"c{node}") if node else {}
            model = udev.get("ID_MODEL_FROM_DATABASE", "")
            vendor_name = _short_vendor(
                vendor, udev.get("ID_VENDOR_FROM_DATABASE", "") or self._read(entry / "manufacturer"))
            if model:
                name = _compose_name(vendor_name, model)
            else:
                name = self._read(entry / "product") or f"USB {vendor}:{product}"
            devices.append(
                Device(
                    bus="usb",
                    address=entry.name,
                    vendor=vendor,
                    product=product,
                    name=name,
                    vendor_name=vendor_name,
                    interfaces=tuple(interfaces.get(entry.name, ())),
                )
            )
        return devices

    def acpi_devices(self) -> list[Device]:
        """The ACPI_AUDIO and ACPI_BLUETOOTH devices the firmware reports as present."""

        devices = []
        for entry in self._entries(self._path("sys/bus/acpi/devices")):
            hid = self._read(entry / "hid").upper()
            if hid in ACPI_AUDIO:
                vendor_name, name = "Intel", ACPI_AUDIO[hid]
            elif ACPI_BLUETOOTH.match(hid):
                vendor_name = _ACPI_BLUETOOTH_VENDORS[hid[0]]
                name = f"{vendor_name} Bluetooth (UART)"
            else:
                continue
            status = self._read(entry / "status")
            if status.isdigit() and not int(status) & 1:
                continue   # described by the firmware but not fitted (_STA)
            devices.append(
                Device(
                    bus="acpi",
                    address=entry.name,
                    vendor="",
                    product=hid,
                    name=name,
                    vendor_name=vendor_name,
                    driver=self._link_name(entry / "physical_node" / "driver"),
                    modalias=self._read(entry / "modalias"),
                )
            )
        return devices

    def platform_sound_cards(self) -> tuple[str, ...]:
        """Sound cards of no PCI or USB device: those of SST sound engines (their board's machine driver)."""

        cards = []
        for entry in self._entries(self._path("sys/class/sound")):
            if not re.fullmatch(r"card\d+", entry.name) or not os.path.lexists(entry / "device"):
                continue
            if self._owner(entry) is None and self._read(entry / "id") not in VIRTUAL_SOUND_CARDS:
                cards.append(entry.name)
        return tuple(cards)

    def platform_bluetooth(self) -> tuple[str, ...]:
        """Bluetooth adapters not on USB: those of chips on a serial port (behind a PCI UART on Atom chips)."""

        adapters = []
        for entry in self._entries(self._path("sys/class/bluetooth")):
            if not re.fullmatch(r"hci\d+", entry.name) or not os.path.lexists(entry / "device"):
                continue
            owner = self._owner(entry)
            if owner is None or owner[0] != "usb":
                adapters.append(entry.name)
        return tuple(adapters)

    def net_interfaces(self) -> list[NetInterface]:
        interfaces = []
        for entry in self._entries(self._path("sys/class/net")):
            owner = self._owner(entry)
            if owner is None:
                continue
            uevent = self._read(entry / "uevent")
            wireless = (entry / "wireless").exists() or (entry / "phy80211").exists() or "DEVTYPE=wlan" in uevent
            operstate = self._read(entry / "operstate")
            up = operstate == "up" or (operstate in {"", "unknown"} and self._read(entry / "carrier") == "1")
            interfaces.append(
                NetInterface(
                    name=entry.name,
                    wireless=wireless,
                    up=up,
                    driver=self._link_name(entry / "device" / "driver"),
                    bus=owner[0],
                    address=owner[1],
                )
            )
        return interfaces

    def rfkill(self) -> list[RfkillSwitch]:
        switches = []
        for entry in self._entries(self._path("sys/class/rfkill")):
            kind = self._read(entry / "type")
            if kind:
                switches.append(
                    RfkillSwitch(kind=kind, soft=self._read(entry / "soft") == "1", hard=self._read(entry / "hard") == "1")
                )
        return switches

    def connected(self, interfaces: Sequence[NetInterface]) -> bool:
        """True when a default route goes through a real network interface (not a VPN or a bridge)."""

        names = {interface.name for interface in interfaces}
        for line in self._read(self._path("proc/net/route")).splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 4 and fields[0] in names and fields[1] == "00000000":
                try:
                    if int(fields[3], 16) & 0x1:   # RTF_UP
                        return True
                except ValueError:
                    continue
        for line in self._read(self._path("proc/net/ipv6_route")).splitlines():
            fields = line.split()
            if len(fields) >= 10 and fields[9] in names and fields[0] == "0" * 32 and fields[1] == "00":
                return True
        return False

    # Kernel modules and firmware ---------------------------------------------------------------

    def modules_for(self, modalias: str) -> tuple[str, ...]:
        """Kernel modules of the running kernel (including DKMS ones) whose aliases match the device."""

        if not modalias:
            return ()
        output = self._run(["modprobe", "--resolve-alias", modalias], 3.0)
        if not output:
            return ()
        names = (line.strip().replace("-", "_") for line in output.splitlines())
        return tuple(dict.fromkeys(name for name in names if name))

    def module_loaded(self, module: str) -> bool:
        return self._path(f"sys/module/{module.replace('-', '_')}").is_dir()

    def module_file(self, module: str) -> str:
        output = self._run(["modinfo", "-n", module], 3.0)
        return output.strip() if output else ""

    def modified_after_boot(self, path: str) -> bool:
        """True for a module file written after this boot: a driver installed since then."""

        boot = 0
        for line in self._read(self._path("proc/stat")).splitlines():
            if line.startswith("btime "):
                boot = int(line.split()[1])
        try:
            return boot > 0 and self._path(path).stat().st_mtime > boot
        except OSError:
            return False

    def firmware_errors(self) -> tuple[FirmwareError, ...]:
        """Firmware the kernel could not load in this boot.

        Needs the kernel log, which the first user can read (group adm); otherwise there is nothing.
        Drivers like iwlwifi try newer firmware first and log a failure even when an older one loads,
        so these lines only explain devices that are already known not to work.
        """

        output = self._run(
            ["journalctl", "--dmesg", "--boot=0", "--output=cat", "--no-pager", "--quiet",
             "--grep=firmware", "--case-sensitive=false"],
            8.0,
        )
        errors = []
        for line in (output or "").splitlines():
            match = _FIRMWARE_LINE.match(line.strip())
            if match:
                errors.append(FirmwareError(
                    driver=match.group("driver"),
                    device=match.group("device"),
                    file=match.group("file") or match.group("file2"),
                ))
        return tuple(dict.fromkeys(errors))

    # System facts ------------------------------------------------------------------------------

    def live_session(self) -> bool:
        return "boot=casper" in self._read(self._path("proc/cmdline")).split()

    def virtual_machine(self) -> bool:
        for line in self._read(self._path("proc/cpuinfo")).splitlines():
            if line.startswith("flags"):
                return "hypervisor" in line.split()
        return False

    def kernel_cmdline(self) -> str:
        return self._read(self._path("proc/cmdline"))

    def module_blacklists(self, cmdline: str) -> tuple[tuple[str, str], ...]:
        """blacklist and install-to-false lines of modprobe.d, and modprobe.blacklist= on the command line."""

        found: dict[str, str] = {}
        for option in cmdline.split():
            key, _, value = option.partition("=")
            if key in ("modprobe.blacklist", "module_blacklist"):
                for module in value.split(","):
                    if module:
                        found.setdefault(module.replace("-", "_"), "the kernel command line")
        for folder in MODPROBE_DIRS:
            for conf in sorted(self._entries(self._path(folder))):
                if conf.suffix != ".conf":
                    continue
                for line in self._read(conf).splitlines():
                    words = line.split("#", 1)[0].split()
                    blocked = (len(words) == 2 and words[0] == "blacklist") or (
                        len(words) >= 3 and words[0] == "install" and words[2] in DISABLING_COMMANDS)
                    if blocked:
                        found.setdefault(words[1].replace("-", "_"), "/" + str(conf.relative_to(self.root)))
        return tuple(found.items())

    def unfinished_packages(self) -> tuple[str, ...]:
        """Packages of /var/lib/dpkg/status in the half-installed, unpacked or half-configured state."""

        found = []
        package = ""
        for line in self._read(self._path(DPKG_STATUS)).splitlines():
            if line.startswith("Package:"):
                package = line.split(":", 1)[1].strip()
            elif line.startswith("Status:") and package:
                words = line.split()
                if len(words) == 4 and words[3] in UNFINISHED_STATES:
                    found.append(package)
        return tuple(found)

    def capt_drivers(self) -> tuple[str, ...]:
        """The Canon CAPT printer drivers installed: "captdriver", "canon"."""

        return tuple(name for name, path in CAPT_DRIVER_FILES if self._path(path).is_file())

    def secure_boot(self) -> bool:
        try:
            data = self._path(SECURE_BOOT_VARIABLE).read_bytes()
        except OSError:
            return False
        return len(data) >= 5 and data[4] == 1   # 4 bytes of attributes, then the value

    # The snapshot ------------------------------------------------------------------------------

    @staticmethod
    def _needs_modules(device: Device) -> tuple[str, ...]:
        """Modaliases to look up for a device the check looks at that has no working driver."""

        if device.bus == "acpi":
            working = device.sound_cards or device.bluetooth
            return () if working or not device.modalias else (device.modalias,)
        if device.bus == "pci":
            interesting = device.pci_class_is(PCI_ETHERNET, PCI_WIFI, *PCI_DISPLAY, *PCI_AUDIO, PCI_CAMERA, *PCI_OTHER)
            if not interesting:
                return ()
            # NVIDIA cards on nouveau: is the NVIDIA driver installed and waiting for a restart?
            if device.vendor == "10de" and device.pci_class_is(*PCI_DISPLAY) and device.driver != "nvidia":
                return (device.modalias,)
            if device.driver and not (device.pci_class_is(PCI_ETHERNET, PCI_WIFI) and not device.net):
                return ()
            return (device.modalias,)
        aliases = [
            interface.modalias
            for interface in device.interfaces
            if not interface.driver
            and (interface.cls in USB_STANDARD_CLASSES or interface.bluetooth or device.looks_like_usb_wifi)
        ]
        return tuple(alias for alias in aliases if alias)

    def _with_modules(self, device: Device) -> Device:
        aliases = self._needs_modules(device)
        if not aliases:
            return device
        modules: dict[str, None] = {}
        for alias in aliases:
            modules.update(dict.fromkeys(self.modules_for(alias)))
        names = tuple(modules)
        loaded = tuple(name for name in names if self.module_loaded(name))
        files = {name: self.module_file(name) for name in names if name not in loaded}
        new = tuple(name for name, path in files.items() if path and self.modified_after_boot(path))
        # Modules built by DKMS (Broadcom wl, out-of-tree Wi-Fi drivers) live under updates/.
        dkms = tuple(name for name, path in files.items() if "/updates/" in path)
        return replace(device, modules=names, loaded_modules=loaded, new_modules=new, dkms_modules=dkms)

    @staticmethod
    def _not_working(device: Device) -> bool:
        """Devices whose failure the kernel log may explain (missing firmware)."""

        if device.bus == "pci":
            if device.pci_class_is(PCI_ETHERNET, PCI_WIFI):
                return not device.net
            if device.pci_class_is(*PCI_AUDIO):
                return not device.sound_cards
            return device.pci_class_is(*PCI_DISPLAY) and not device.driver
        if device.bus == "acpi":
            return not (device.sound_cards or device.bluetooth)
        return bool(device.bluetooth_interfaces) and not device.bluetooth

    def snapshot(self) -> Snapshot:
        net = self.net_interfaces()
        net_by_owner: dict[tuple[str, str], list[str]] = {}
        for interface in net:
            net_by_owner.setdefault((interface.bus, interface.address), []).append(interface.name)
        sound = self._owned("sound", r"card\d+")
        bluetooth = self._owned("bluetooth", r"hci\d+")
        video = self._owned("video4linux", r"video\d+")

        def attach(device: Device) -> Device:
            owner = (device.bus, device.address)
            device = replace(
                device,
                net=tuple(net_by_owner.get(owner, ())),
                sound_cards=len(sound.get(owner, ())),
                bluetooth=tuple(bluetooth.get(owner, ())),
                video_nodes=len(video.get(owner, ())),
            )
            return self._with_modules(device)

        def attach_acpi(device: Device) -> Device:
            if device.product in ACPI_AUDIO:
                device = replace(device, sound_cards=len(platform_cards))
            else:
                device = replace(device, bluetooth=platform_adapters)
            return self._with_modules(device)

        pci = tuple(attach(device) for device in self.pci_devices())
        usb = tuple(attach(device) for device in self.usb_devices())
        acpi_found = self.acpi_devices()
        platform_cards = self.platform_sound_cards() if acpi_found else ()
        platform_adapters = self.platform_bluetooth() if acpi_found else ()
        acpi = tuple(attach_acpi(device) for device in acpi_found)
        devices = pci + usb + acpi
        firmware = self.firmware_errors() if any(self._not_working(device) for device in devices) else ()
        cmdline = self.kernel_cmdline()
        return Snapshot(
            pci=pci,
            usb=usb,
            acpi=acpi,
            net=tuple(net),
            rfkill=tuple(self.rfkill()),
            connected=self.connected(net),
            kernel=self._read(self._path("proc/sys/kernel/osrelease")),
            live=self.live_session(),
            virtual=self.virtual_machine(),
            secure_boot=self.secure_boot(),
            firmware_errors=firmware,
            cmdline=cmdline,
            blacklists=self.module_blacklists(cmdline),
            unfinished_packages=self.unfinished_packages(),
            capt_drivers=self.capt_drivers(),
        )

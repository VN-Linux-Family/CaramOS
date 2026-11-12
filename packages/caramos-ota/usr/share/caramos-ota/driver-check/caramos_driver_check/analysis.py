"""Turn a hardware snapshot into what the user sees: a status per area and each problem with its fix.

A device without a working driver is explained from facts read at run time, so the advice stays right as
kernels change: no kernel module matches it (the kernel has no driver yet), a module matches but is not
loaded (just installed: restart), or the driver is loaded and the device still does not start (usually
missing firmware). knowledge.py adds what the kernel cannot tell (Broadcom Wi-Fi, NVIDIA, Intel IPU
cameras, fingerprint readers, Canon CAPT printers), and drivers.py the driver packages Ubuntu recommends, which the window
installs with one click.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace

from caramos_ota.i18n import _

from . import canon_capt, knowledge
from .drivers import DriverProposal
from .hardware import (
    ACPI_AUDIO,
    ACPI_BLUETOOTH,
    PCI_AUDIO,
    PCI_DISPLAY,
    PCI_ETHERNET,
    PCI_OTHER,
    PCI_WIFI,
    USB_STANDARD_CLASSES,
    USB_VIDEO,
    Device,
    Snapshot,
)

# Levels. TIP: works, and there is something worth setting up. ABSENT: the machine has no such hardware.
ABSENT, OK, TIP, INFO, WARNING, CRITICAL = "absent", "ok", "tip", "info", "warning", "critical"
_SEVERITY = {ABSENT: 0, OK: 1, TIP: 2, INFO: 3, WARNING: 4, CRITICAL: 5}
PROBLEM_LEVELS = (WARNING, CRITICAL)

# Actions the window offers; actions.py runs them, INSTALL goes through the privileged helper.
INSTALL = "install"
DRIVER_MANAGER = "driver-manager"
UPDATE_MANAGER = "update-manager"
REBOOT = "reboot"
WIFI_ON = "wifi-on"
FINGERPRINTS = "fingerprints"
REPORT = "report"

AREAS = ("wifi", "ethernet", "graphics", "audio", "bluetooth", "camera", "fingerprint", "printer", "other")
# Shown even when the machine has none, so the user sees that they were checked.
ALWAYS_SHOWN = ("wifi", "ethernet", "graphics", "audio", "bluetooth", "camera")

# Packages of an NVIDIA driver install, whose failed dpkg configure breaks every later install.
NVIDIA_PACKAGES = ("nvidia-", "libnvidia-", "linux-modules-nvidia-", "linux-objects-nvidia-", "linux-signatures-nvidia-",
                   "xserver-xorg-video-nvidia-")

# Framebuffer modules match graphics cards too, but are blacklisted on purpose.
_IGNORED_MODULES = frozenset({
    "nvidiafb", "rivafb", "intelfb", "i810fb", "viafb", "radeonfb", "aty128fb", "atyfb", "sisfb",
    "savagefb", "tdfxfb", "vga16fb", "s3fb", "neofb", "cyber2000fb", "matroxfb_base", "vt8623fb", "arkfb",
})


def area_label(key: str) -> str:
    labels = {
        "wifi": _("Wi-Fi"),
        "ethernet": _("Wired network"),
        "graphics": _("Graphics"),
        "audio": _("Sound"),
        "bluetooth": _("Bluetooth"),
        "camera": _("Webcam"),
        "fingerprint": _("Fingerprint reader"),
        "printer": _("Printer"),
        "other": _("Other devices"),
    }
    return labels.get(key, key)


@dataclass(frozen=True)
class Action:
    kind: str
    label: str
    target: str = ""             # INSTALL: what the helper installs ("nvidia:580-open", "bcmwl-kernel-source")


@dataclass(frozen=True)
class Finding:
    key: str                     # stays the same between checks; remembers what the user has seen
    area: str
    level: str
    title: str
    detail: str
    device: str = ""             # "Broadcom BCM4360 802.11ac Wireless Network Adapter"
    device_id: str = ""          # "PCI 14e4:43a0"
    link: str = ""               # the device on linux-hardware.org
    actions: tuple[Action, ...] = ()
    connect_help: bool = False   # the computer is offline because of this: show how to get online
    offline_media: bool = False  # the driver can be installed from the CaramOS USB stick, without internet
    notes: tuple[tuple[str, bool], ...] = ()   # short facts shown as ✓ (True) or – (False) lines

    @property
    def install(self) -> Action | None:
        return next((action for action in self.actions if action.kind == INSTALL), None)


@dataclass(frozen=True)
class AreaStatus:
    key: str
    level: str
    summary: str


@dataclass(frozen=True)
class Report:
    areas: tuple[AreaStatus, ...]
    findings: tuple[Finding, ...]
    connected: bool
    live: bool
    virtual: bool
    kernel: str
    wired_port: bool             # a working network port to plug a cable into

    @property
    def problems(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.level in PROBLEM_LEVELS)

    @property
    def critical(self) -> tuple[Finding, ...]:
        return tuple(finding for finding in self.findings if finding.level == CRITICAL)

    @property
    def needs_connection(self) -> bool:
        return any(finding.connect_help for finding in self.findings)

    @property
    def offline_media(self) -> bool:
        return any(finding.offline_media for finding in self.problems)

    @property
    def installs(self) -> tuple[Action, ...]:
        """One-click driver installs of the problems that can run now, for the "install all" button.

        Offline, only drivers on the CaramOS USB stick can install. Canon's printer driver is left out: it
        installs on its own, after the user agreed to Canon's terms.
        """

        actions = (finding.install for finding in self.problems if self.can_install(finding))
        return tuple(dict.fromkeys(action for action in actions
                                   if action is not None and not canon_capt.is_target(action.target)))

    def can_install(self, finding: Finding) -> bool:
        return self.connected or finding.offline_media

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def worst(levels: Iterable[str], default: str = OK) -> str:
    result = default
    for level in levels:
        if _SEVERITY[level] > _SEVERITY[result]:
            result = level
    return result


def _action(kind: str) -> Action:
    labels = {
        DRIVER_MANAGER: _("Open Driver Manager"),
        UPDATE_MANAGER: _("Open Update Manager"),
        REBOOT: _("Restart"),
        WIFI_ON: _("Turn on Wi-Fi"),
        FINGERPRINTS: _("Add fingerprints"),
        REPORT: _("Ask for help"),
    }
    return Action(kind, labels[kind])


def kernel_version(release: str) -> str:
    """6.14.0-37-generic -> 6.14"""

    return ".".join(release.split("-")[0].split(".")[:2]) or release


def _device_id(device: Device) -> str:
    return f"{device.bus.upper()} {device.id}"


class _Analysis:
    def __init__(self, snapshot: Snapshot, fingerprint_support: Mapping[str, str],
                 proposals: Sequence[DriverProposal]) -> None:
        self.snapshot = snapshot
        self.fingerprint_support = fingerprint_support
        self.proposals = {proposal.address: proposal for proposal in proposals if proposal.address}
        self.used_proposals: set[str] = set()
        self.findings: list[Finding] = []
        self.areas: dict[str, AreaStatus] = {}

    def _proposal(self, device: Device) -> DriverProposal | None:
        proposal = self.proposals.get(device.address)
        if proposal is not None:
            self.used_proposals.add(device.address)
        return proposal

    # Shared explanations -----------------------------------------------------------------------

    def _candidates(self, device: Device) -> tuple[str, ...]:
        return tuple(module for module in device.modules if module not in _IGNORED_MODULES)

    def _waiting_modules(self, device: Device) -> tuple[str, ...]:
        """Matching modules that are neither loaded nor bound to the device."""

        bound = {device.driver.replace("-", "_")} if device.driver else set()
        return tuple(
            module for module in self._candidates(device)
            if module not in device.loaded_modules and module not in bound
        )

    def _firmware_files(self, device: Device) -> tuple[str, ...]:
        names = {device.address, *device.bluetooth}
        files = [error.file for error in self.snapshot.firmware_errors if error.device in names]
        serial_bluetooth = device.bus == "acpi" and bool(ACPI_BLUETOOTH.match(device.product))
        if not files and (device.bluetooth_interfaces or serial_bluetooth) and not device.bluetooth:
            # A Bluetooth adapter whose firmware failed is gone again; its errors name the old hciN.
            files = [error.file for error in self.snapshot.firmware_errors if error.driver == "bluetooth"]
        return tuple(dict.fromkeys(files))

    def _secure_boot_note(self, device: Device) -> str:
        if self.snapshot.secure_boot and any(module in device.dkms_modules for module in self._waiting_modules(device)):
            return " " + _(
                "Secure Boot is on: if a blue “Perform MOK management” screen appears while restarting, "
                "choose “Enroll MOK” and type the password you set when the driver was installed."
            )
        return ""

    def _modesetting_off(self, device: Device) -> str:
        """The boot option that keeps a graphics driver from starting: nomodeset or <module>.modeset=0."""

        if not device.pci_class_is(*PCI_DISPLAY):
            return ""
        options = self.snapshot.boot_options()
        if "nomodeset" in options:
            return "nomodeset"
        return next((f"{module}.modeset=0" for module in self._candidates(device)
                     if f"{module}.modeset=0" in options), "")

    def _reason(self, device: Device, working_driver: bool) -> str:
        """Why a device does not work: restart, blocked, failed or no-driver."""

        waiting = self._waiting_modules(device)
        # A matching module installed after this boot (a driver just installed) starts at the next boot.
        if any(module in device.new_modules for module in waiting):
            return "restart"
        # A DKMS module is built for this hardware on purpose; not loaded, it is blocked (Secure Boot).
        if any(module in device.dkms_modules for module in waiting):
            return "blocked"
        # Several in-kernel modules can match one device (snd_hda_intel, SOF and AVS for Intel sound) and
        # only one of them binds, so an unloaded module only matters when none of them loaded.
        if waiting and not device.loaded_modules and not working_driver:
            return "blocked"
        if working_driver or device.loaded_modules or self._candidates(device):
            return "failed"
        return "no-driver"

    def _explain(self, device: Device, reason: str, driver: str) -> str:
        if reason == "restart":
            return _(
                "Its driver is installed but not running yet. Restart the computer to start it."
            ) + self._secure_boot_note(device)
        if reason == "blocked":
            modules = ", ".join(self._waiting_modules(device))
            if self.snapshot.secure_boot and any(module in device.dkms_modules for module in self._waiting_modules(device)):
                return _(
                    "Its driver (%s) is installed, but Secure Boot blocks it because it is not signed with an "
                    "enrolled key. Run “sudo update-secureboot-policy --enroll-key” in a terminal, restart and "
                    "choose “Enroll MOK”, or turn off Secure Boot in the BIOS settings."
                ) % modules
            option = self._modesetting_off(device)
            if option:
                return _(
                    "The computer starts with the “%s” boot option, which turns the graphics driver (%s) off. It "
                    "is often added to get past a black screen. To turn the driver on again, "
                    "open a terminal, run “sudo sed -i 's/ *%s//' /etc/default/grub && sudo update-grub” and "
                    "restart."
                ) % (option, modules, option)
            blocked = [(module, self.snapshot.blacklisted(module)) for module in self._waiting_modules(device)]
            blocked = [(module, where) for module, where in blocked if where]
            if blocked:
                module, where = blocked[0]
                if where.startswith("/"):
                    return _(
                        "Its driver (%s) is turned off by a “blacklist %s” line in %s. Remove that line and restart "
                        "the computer to use it."
                    ) % (module, module, where)
                return _(
                    "Its driver (%s) is turned off by the modprobe.blacklist boot option. Remove it from "
                    "/etc/default/grub, run “sudo update-grub” and restart the computer to use it."
                ) % module
            return _(
                "Its driver (%s) is on the computer but did not load: it may be turned off (blacklisted) or "
                "it refused to start."
            ) % modules
        if reason == "failed":
            files = self._firmware_files(device)
            text = _("Its driver (%s) is loaded, but the device does not start.") % (driver or ", ".join(device.loaded_modules or device.modules))
            if files:
                text += " " + _("The firmware it needs is missing: %s.") % ", ".join(files)
            return text + " " + _("Updating CaramOS (the linux-firmware package) or a newer kernel usually fixes this.")
        return _(
            "Linux %s has no driver for it yet. A newer kernel may support it: ask the community for help with "
            "the button below."
        ) % kernel_version(self.snapshot.kernel)

    def _actions_for(self, reason: str) -> tuple[Action, ...]:
        if reason == "restart":
            return (_action(REBOOT),)
        if reason == "blocked":
            return (_action(REPORT),)
        if reason == "failed":
            return (_action(UPDATE_MANAGER), _action(REPORT))
        return (_action(REPORT),)

    def _add(self, area: str, level: str, key: str, title: str, detail: str, device: Device | None = None,
             actions: Iterable[Action] = (), **extra) -> None:
        self.findings.append(
            Finding(
                key=key,
                area=area,
                level=level,
                title=title,
                detail=detail,
                device=device.name if device else "",
                device_id=_device_id(device) if device else "",
                link=device.hardware_page() if device else "",
                actions=tuple(actions),
                **extra,
            )
        )

    def _area(self, key: str, devices: Iterable[Device], summary: str = "") -> None:
        names = list(dict.fromkeys(device.name for device in devices))
        levels = [finding.level for finding in self.findings if finding.area == key]
        if not names and not levels:
            if key in ALWAYS_SHOWN:
                self.areas[key] = AreaStatus(key, ABSENT, summary or _("Not found on this computer"))
            return
        level = worst((level for level in levels if level != TIP), OK)
        self.areas[key] = AreaStatus(key, level, summary or " + ".join(names) or _("Not found on this computer"))

    # Network -----------------------------------------------------------------------------------

    def _network(self) -> None:
        snapshot = self.snapshot
        wireless_owners = {(net.bus, net.address) for net in snapshot.net if net.wireless}
        wifi = [
            device for device in snapshot.devices
            if (device.bus, device.address) in wireless_owners
            or device.pci_class_is(PCI_WIFI)
            or (device.looks_like_usb_wifi and not device.net)
        ]
        wired_owners = {(net.bus, net.address) for net in snapshot.net if not net.wireless and not net.phone}
        wired = [
            device for device in snapshot.devices
            if (device.pci_class_is(PCI_ETHERNET) or (device.bus, device.address) in wired_owners)
            and (device.bus, device.address) not in wireless_owners
        ]
        wifi_up = any(net.wireless for net in snapshot.net)
        self.wired_port = any(not net.wireless and not net.phone for net in snapshot.net)
        offline = not snapshot.connected

        for device in wifi:
            if device.net:
                continue
            reason = self._reason(device, working_driver=bool(device.driver))
            level = CRITICAL if offline else WARNING
            if knowledge.broadcom_wifi(device) and reason in {"failed", "no-driver"}:
                self._broadcom(device, level, offline)
                continue
            titles = {
                "restart": _("Restart to start the Wi-Fi driver"),
                "blocked": _("The Wi-Fi driver did not load"),
                "failed": _("Wi-Fi does not start"),
                "no-driver": _("Wi-Fi has no driver"),
            }
            self._add("wifi", level, f"wifi:{reason}:{device.key}", titles[reason],
                      self._explain(device, reason, device.driver) + self._live_note(), device,
                      self._actions_for(reason), connect_help=offline and reason != "restart")

        for device in wired:
            if device.net:
                continue
            reason = self._reason(device, working_driver=bool(device.driver))
            level = CRITICAL if offline and not wifi_up else WARNING
            titles = {
                "restart": _("Restart to start the network port driver"),
                "blocked": _("The network port driver did not load"),
                "failed": _("The network port does not start"),
                "no-driver": _("The network port has no driver"),
            }
            self._add("ethernet", level, f"ethernet:{reason}:{device.key}", titles[reason],
                      self._explain(device, reason, device.driver) + self._live_note(), device,
                      self._actions_for(reason), connect_help=level == CRITICAL and reason != "restart")

        if offline and not wifi and not wired and not snapshot.net:
            self._add("wifi", CRITICAL, "network:none", _("No network card found"), _(
                "CaramOS finds neither a Wi-Fi card nor a network port. The Wi-Fi card may be turned off in "
                "the BIOS settings. You can still get online with your phone over a USB cable."
            ), connect_help=True)

        wlan = [switch for switch in snapshot.rfkill if switch.kind == "wlan"]
        if wifi_up and any(switch.hard for switch in wlan):
            self._add("wifi", WARNING if offline else INFO, "wifi:hard-blocked", _("Wi-Fi is turned off by a switch"), _(
                "Turn it on with the Wi-Fi switch or the Fn key with the Wi-Fi or airplane symbol. If it stays "
                "off, check that Wi-Fi is enabled in the BIOS settings."
            ))
        elif wifi_up and offline and any(switch.soft for switch in wlan):
            self._add("wifi", WARNING, "wifi:soft-blocked", _("Wi-Fi is turned off"),
                      _("Wi-Fi is switched off, or airplane mode is on."), actions=(_action(WIFI_ON),))

        def connection(devices: list[Device], wireless: bool) -> str:
            nets = {name for device in devices for name in device.net}
            if not nets:
                return ""
            up = any(net.up for net in snapshot.net if net.name in nets and net.wireless == wireless)
            if wireless:
                return _("connected") if up else _("not connected")
            return _("cable plugged in") if up else _("no cable plugged in")

        for key, devices, wireless in (("wifi", wifi, True), ("ethernet", wired, False)):
            names = " + ".join(dict.fromkeys(device.name for device in devices))
            state = connection(devices, wireless)
            self._area(key, devices, f"{names} ({state})" if names and state else names)

    def _broadcom(self, device: Device, level: str, offline: bool) -> None:
        snapshot = self.snapshot
        proposal = self._proposal(device)
        notes: list[tuple[str, bool]] = []
        if proposal is not None:
            detail = _("Broadcom Wi-Fi cards need Broadcom's own driver, which Linux cannot include. "
                       "CaramOS can install it for you.")
            actions = (Action(INSTALL, _("Install the Wi-Fi driver"), proposal.target), _action(DRIVER_MANAGER))
            notes.append((_("Driver recommended by Ubuntu for this card: %s") % proposal.package, True))
        else:
            detail = _("Broadcom Wi-Fi cards need Broadcom's own driver, which Linux cannot include. "
                       "Open Driver Manager and install the Broadcom driver it suggests.")
            actions = (_action(DRIVER_MANAGER), _action(REPORT))
        if offline and not snapshot.live and (proposal is None or proposal.offline):
            notes.append((_("No internet? It installs from the CaramOS USB stick: plug the stick in first."), True))
        if snapshot.secure_boot:
            notes.append((_("Secure Boot is on: after installing, Driver Check shows how to allow the driver."),
                          False))
        self._add("wifi", level, f"wifi:broadcom:{device.key}", _("Wi-Fi needs the Broadcom driver"),
                  detail + self._live_note(), device, actions, connect_help=offline,
                  offline_media=not snapshot.live, notes=tuple(notes))

    def _live_note(self) -> str:
        if not self.snapshot.live:
            return ""
        return " " + _(
            "You can still install CaramOS: after installing, Driver Check opens again and helps you set this up."
        )

    # Graphics ----------------------------------------------------------------------------------

    def _graphics(self) -> None:
        cards = [device for device in self.snapshot.pci if device.pci_class_is(*PCI_DISPLAY)]
        for device in cards:
            if self.snapshot.virtual:
                continue
            if knowledge.nvidia_gpu(device):
                self._nvidia(device)
            elif not device.driver:
                reason = self._reason(device, working_driver=False)
                titles = {
                    "restart": _("Restart to start the graphics driver"),
                    "blocked": _("The graphics driver did not load"),
                    "failed": _("The graphics card does not start"),
                    "no-driver": _("The graphics card has no driver"),
                }
                detail = _(
                    "The screen runs in a basic mode: slower, and resolution or brightness may not change."
                ) + " " + self._explain(device, reason, "")
                self._add("graphics", WARNING, f"graphics:{reason}:{device.key}", titles[reason], detail,
                          device, self._actions_for(reason))
        self._area("graphics", cards)

    def _nvidia(self, device: Device) -> None:
        broken = [package for package in self.snapshot.unfinished_packages if package.startswith(NVIDIA_PACKAGES)]
        if broken:
            self._nvidia_broken(device, broken)
            return
        if device.driver == "nvidia":
            return
        if "nvidia" in device.new_modules:
            self._add("graphics", WARNING, f"graphics:nvidia-restart:{device.key}",
                      _("Restart to start the NVIDIA driver"),
                      _("The NVIDIA driver is installed. Restart the computer to start it.")
                      + self._secure_boot_note(device), device, (_action(REBOOT),))
            return
        if "nvidia" in device.modules and "nvidia" not in device.loaded_modules:
            self._add("graphics", WARNING, f"graphics:nvidia-blocked:{device.key}",
                      _("The NVIDIA driver did not load"), self._explain(device, "blocked", ""), device,
                      (_action(DRIVER_MANAGER), _action(REPORT)))
            return
        if device.driver == "nouveau":
            why = _("This NVIDIA card runs on the open-source nouveau driver: slower in games and videos, and "
                    "the battery runs down faster.")
        else:
            why = _("This NVIDIA card has no driver yet.")
        proposal = self._proposal(device)
        if self.snapshot.live:
            self._add("graphics", INFO, f"graphics:nvidia:{device.key}", _("Install the NVIDIA driver after installing"),
                      why + " " + _("After installing CaramOS, Driver Check helps you install the NVIDIA driver "
                                    "(it needs internet)."), device)
            return
        if proposal is None:
            self._add("graphics", WARNING, f"graphics:nvidia:{device.key}", _("Install the NVIDIA driver"),
                      why + " " + _("Open Driver Manager and install the recommended NVIDIA driver (it needs "
                                    "internet), then restart."), device, (_action(DRIVER_MANAGER),))
            return
        version = proposal.version or proposal.package
        # The modules come with the newest kernel of the series and its headers: on a 1.3.4 install not yet
        # updated, NVIDIA 580 was a 940 MiB download.
        notes = [
            (_("Recommended for this card: NVIDIA %s") % version
             + (" " + _("(open kernel modules)") if proposal.open_kernel_modules else ""), True),
            (_("Needs internet: a download of up to about 1 GB"), False),
            (_("Restart the computer after installing"), False),
        ]
        self._add("graphics", WARNING, f"graphics:nvidia:{device.key}", _("Install the NVIDIA driver"),
                  why + " " + _("CaramOS installs the driver Ubuntu recommends for this card."), device,
                  (Action(INSTALL, _("Install NVIDIA driver %s") % version, proposal.target),
                   _action(DRIVER_MANAGER)), notes=tuple(notes))

    def _nvidia_broken(self, device: Device, broken: list[str]) -> None:
        """An NVIDIA driver dpkg could not finish (its module does not build for this kernel, ticket H-1094)."""

        detail = _(
            "Installing %s did not finish: this NVIDIA driver does not work with Linux %s. Until it is replaced, "
            "installing other software fails too, in the App Center and the Update Center."
        ) % (", ".join(broken[:3]) + ("…" if len(broken) > 3 else ""), kernel_version(self.snapshot.kernel))
        proposal = self._proposal(device)
        if proposal is not None:
            version = proposal.version or proposal.package
            detail += " " + _("Install NVIDIA driver %s instead: the broken driver is removed at the same time.") % version
            actions: tuple[Action, ...] = (Action(INSTALL, _("Install NVIDIA driver %s") % version, proposal.target),
                                           _action(DRIVER_MANAGER))
        else:
            detail += " " + _("Open Driver Manager and choose the open-source nouveau driver to remove it.")
            actions = (_action(DRIVER_MANAGER), _action(REPORT))
        self._add("graphics", CRITICAL, f"graphics:nvidia-broken:{device.key}", _("The NVIDIA driver did not install"),
                  detail, device, actions)

    # Sound -------------------------------------------------------------------------------------

    def _audio(self) -> None:
        devices = [device for device in self.snapshot.pci if device.pci_class_is(*PCI_AUDIO)]
        usb_audio = [device for device in self.snapshot.usb if device.interfaces_of("01")]
        for device in devices:
            gpu_audio = device.vendor in {knowledge.NVIDIA, "1002"}
            if device.driver and (device.sound_cards or gpu_audio):
                continue
            if not device.driver:
                reason = self._reason(device, working_driver=False)
            else:
                reason = "restart" if any(m in device.new_modules for m in self._waiting_modules(device)) else "failed"
            titles = {
                "restart": _("Restart to start the sound driver"),
                "blocked": _("The sound driver did not load"),
                "failed": _("Speakers and microphone are not detected"),
                "no-driver": _("Sound has no driver"),
            }
            detail = _("Speakers and microphone do not work yet (the sound settings show “Dummy Output”).")
            self._add("audio", WARNING, f"audio:{reason}:{device.key}", titles[reason],
                      detail + " " + self._explain(device, reason, device.driver), device, self._actions_for(reason))
        engines = [device for device in self.snapshot.acpi if device.product in ACPI_AUDIO]
        for device in engines:
            if device.sound_cards:
                continue
            reason = self._reason(device, working_driver=bool(device.driver))
            titles = {
                "restart": _("Restart to start the sound driver"),
                "blocked": _("The sound driver did not load"),
                "failed": _("Speakers and microphone are not detected"),
                "no-driver": _("Sound has no driver"),
            }
            if reason in {"failed", "no-driver"} and not self._firmware_files(device):
                # The engine's driver may well run: what is missing is the driver of this computer's board.
                explanation = _(
                    "This computer's sound goes through the Intel SST sound engine, which needs a sound driver "
                    "made for each computer model, and Linux %s has none for this one yet. Ask the community "
                    "for help with the button below."
                ) % kernel_version(self.snapshot.kernel)
                actions: tuple[Action, ...] = (_action(REPORT),)
            else:
                explanation = self._explain(device, reason, device.driver)
                actions = self._actions_for(reason)
            detail = _("Speakers and microphone do not work yet (the sound settings show “Dummy Output”).")
            self._add("audio", WARNING, f"audio:{reason}:{device.key}", titles[reason], detail + " " + explanation,
                      device, actions)
        self._area("audio", devices + usb_audio + engines)

    # Bluetooth ---------------------------------------------------------------------------------

    def _bluetooth(self) -> None:
        devices = [device for device in self.snapshot.usb if device.bluetooth_interfaces]
        devices += [device for device in self.snapshot.acpi if ACPI_BLUETOOTH.match(device.product)]
        for device in devices:
            if device.bluetooth:
                continue
            driver = device.driver or next(
                (interface.driver for interface in device.bluetooth_interfaces if interface.driver), "")
            reason = self._reason(device, working_driver=bool(driver))
            titles = {
                "restart": _("Restart to start the Bluetooth driver"),
                "blocked": _("The Bluetooth driver did not load"),
                "failed": _("Bluetooth does not start"),
                "no-driver": _("Bluetooth has no driver"),
            }
            self._add("bluetooth", WARNING, f"bluetooth:{reason}:{device.key}", titles[reason],
                      self._explain(device, reason, driver), device, self._actions_for(reason))
        if devices and any(switch.kind == "bluetooth" and switch.hard for switch in self.snapshot.rfkill):
            self._add("bluetooth", INFO, "bluetooth:hard-blocked", _("Bluetooth is turned off by a switch"),
                      _("Turn it on with the wireless switch or the Fn key with the airplane symbol."))
        self._area("bluetooth", devices)

    # Webcam ------------------------------------------------------------------------------------

    def _camera(self) -> None:
        webcams = [device for device in self.snapshot.usb if device.interfaces_of(USB_VIDEO)]
        working = False
        for device in webcams:
            if device.video_nodes or any(interface.driver for interface in device.interfaces_of(USB_VIDEO)):
                working = True
                continue
            reason = self._reason(device, working_driver=False)
            titles = {
                "restart": _("Restart to start the webcam driver"),
                "blocked": _("The webcam driver did not load"),
                "failed": _("The webcam does not start"),
                "no-driver": _("The webcam has no driver"),
            }
            self._add("camera", WARNING, f"camera:{reason}:{device.key}", titles[reason],
                      self._explain(device, reason, ""), device, self._actions_for(reason))
        ipu = [device for device in self.snapshot.pci if knowledge.intel_ipu(device)]
        atom = [device for device in self.snapshot.pci if knowledge.atom_isp(device)]
        if working:
            ipu = atom = []
        if ipu:
            self._add("camera", INFO, f"camera:ipu:{ipu[0].key}", _("The built-in camera may not work yet"), _(
                "This laptop's camera is connected through an Intel IPU image processor, common on laptops since "
                "2021. Most apps on Linux cannot use this kind of camera yet; a USB webcam works right away."
            ), ipu[0], (_action(REPORT),))
        if atom:
            self._add("camera", INFO, f"camera:atom-isp:{atom[0].key}", _("The built-in cameras do not work yet"), _(
                "This computer's cameras are connected through the image processor of Intel Atom chips. Linux "
                "only has an unfinished driver for it, so apps cannot use these cameras; a USB webcam works "
                "right away."
            ), atom[0])
        self._area("camera", webcams + ipu + atom)

    # Fingerprint reader ------------------------------------------------------------------------

    def _fingerprint(self) -> None:
        readers = []
        for device in self.snapshot.usb:
            driver = self.fingerprint_support.get(device.id)
            if not driver and device.id not in self.fingerprint_support and not knowledge.fingerprint_like(device):
                continue
            # Readers name themselves things like "ELAN:ARM-M4"; the USB database rarely knows them.
            device = replace(device, name=_("%s fingerprint reader") % (device.vendor_name or device.vendor))
            readers.append(device)
            if driver:
                self._add("fingerprint", TIP, f"fingerprint:supported:{device.key}", _("Log in with your fingerprint"),
                          _("This fingerprint reader works with CaramOS. Add your fingerprints to log in and unlock "
                            "the screen with them."), device, (_action(FINGERPRINTS),))
            else:
                self._add("fingerprint", INFO, f"fingerprint:unsupported:{device.key}",
                          _("The fingerprint reader has no driver"),
                          _("Linux has no driver for this fingerprint reader yet (libfprint). Log in with your "
                            "password."), device)
        self._area("fingerprint", readers)

    # Printers ----------------------------------------------------------------------------------

    def _printers(self) -> None:
        """Canon CAPT printers (LBP2900...): the kernel takes them like any printer, but they need a CAPT driver."""

        printers = [device for device in self.snapshot.usb if knowledge.capt_printer(device)]
        drivers = self.snapshot.capt_drivers
        for device in printers:
            self._proposal(device)   # the driver below is this device's ubuntu-drivers proposal
            supported = device.product in knowledge.CAPTDRIVER_MODELS
            if "canon" in drivers or (supported and "captdriver" in drivers):
                continue
            if supported:
                detail = _(
                    "This Canon printer speaks Canon's own printer language (CAPT), so it prints nothing without a "
                    "CAPT driver. Install captdriver, an open-source driver for it; the printer is then set up "
                    "by itself."
                )
                if device.product not in knowledge.CAPTDRIVER_WORKS:
                    detail += " " + _("Support for this model is still experimental.")
                actions: tuple[Action, ...] = (
                    Action(INSTALL, _("Install the printer driver"), knowledge.CAPTDRIVER_PACKAGE), _action(REPORT))
            elif device.product in canon_capt.USB_MODELS:
                detail = _(
                    "This Canon printer speaks Canon's own printer language (CAPT), and only Canon's driver supports "
                    "this model. Driver Check downloads it from Canon (about 120 MB) once you agree to Canon's terms, "
                    "installs it as Canon made it and sets up the printer."
                )
                actions = (Action(INSTALL, _("Install Canon's driver"), canon_capt.INSTALL_TARGET), _action(REPORT))
            else:
                detail = _(
                    "This Canon printer speaks Canon's own printer language (CAPT), and neither captdriver nor "
                    "Canon's Linux driver supports this model. Ask the community for help with the button below."
                )
                actions = (_action(REPORT),)
            self._add("printer", WARNING, f"printer:capt:{device.key}", _("The printer has no driver"), detail,
                      device, actions)
        self._area("printer", printers)

    # Other devices -----------------------------------------------------------------------------

    def _other(self) -> None:
        devices = []
        for device in self.snapshot.pci:
            if device.driver or not device.pci_class_is(*PCI_OTHER):
                continue
            if device.pci_class_is("ff00") and "card reader" not in device.name.lower():
                continue
            devices.append(device)
        for device in self.snapshot.usb:
            if knowledge.fingerprint_like(device) or device.id in self.fingerprint_support or device.looks_like_usb_wifi \
                    or knowledge.capt_printer(device):
                continue
            standard = [
                interface for interface in device.interfaces
                if interface.cls in USB_STANDARD_CLASSES and interface.cls != USB_VIDEO
            ]
            if standard and not any(interface.driver for interface in standard):
                devices.append(device)
        reported = []
        for device in devices:
            reason = self._reason(device, working_driver=False)
            if reason == "failed":
                continue   # a loaded module that does not bind is not worth a warning for these
            reported.append(device)
            titles = {
                "restart": _("Restart to start a device driver"),
                "blocked": _("A device driver did not load"),
                "no-driver": _("A device has no driver"),
            }
            title = titles[reason]
            self._add("other", INFO, f"other:{reason}:{device.key}", title,
                      self._explain(device, reason, ""), device, self._actions_for(reason))
        if reported:
            self._area("other", reported)

    def _other_proposals(self) -> None:
        devices = {device.address: device for device in self.snapshot.devices}
        for address, proposal in sorted(self.proposals.items()):
            if address in self.used_proposals or proposal.nvidia and self.snapshot.live:
                continue
            device = devices.get(address)
            if device is not None and (device.driver or any(interface.driver for interface in device.interfaces)):
                continue   # it works with the driver it has; another one could make it worse
            name = device.name if device else " ".join(part for part in (proposal.vendor, proposal.model) if part)
            self._add("other", TIP, f"driver:{proposal.package}", _("Recommended driver for %s") % (name or address),
                      _("Ubuntu recommends the %s package for this device.") % proposal.package, device,
                      (Action(INSTALL, _("Install the driver"), proposal.target), _action(DRIVER_MANAGER)))

    def report(self) -> Report:
        self._network()
        self._graphics()
        self._audio()
        self._bluetooth()
        self._camera()
        self._fingerprint()
        self._printers()
        self._other()
        self._other_proposals()
        order = {key: index for index, key in enumerate(AREAS)}
        findings = sorted(self.findings, key=lambda finding: (-_SEVERITY[finding.level], order[finding.area]))
        return Report(
            areas=tuple(self.areas[key] for key in AREAS if key in self.areas),
            findings=tuple(findings),
            connected=self.snapshot.connected,
            live=self.snapshot.live,
            virtual=self.snapshot.virtual,
            kernel=self.snapshot.kernel,
            wired_port=self.wired_port,
        )


def analyze(snapshot: Snapshot, fingerprint_support: Mapping[str, str] | None = None,
            proposals: Sequence[DriverProposal] = ()) -> Report:
    """The report for one snapshot.

    fingerprint_support comes from knowledge.read_libfprint_support(), proposals from
    drivers.lookup() (empty when it was not needed or UbuntuDrivers is not available).
    """

    return _Analysis(snapshot, fingerprint_support or {}, proposals).report()

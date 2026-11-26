"""Driver Check reads the hardware from sysfs, /proc and the udev database (a fake system tree here)."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Driver Check lives in /usr/share/caramos-ota/driver-check, outside dist-packages.
sys.path.insert(0, str(Path(__file__).parents[1] / "usr/share/caramos-ota/driver-check"))

from caramos_driver_check.analysis import REBOOT, analyze
from caramos_driver_check.hardware import SystemReader, friendly_model, kernel_order
from caramos_driver_check.knowledge import intel_ipu, read_libfprint_support

PCI_ROOT = "sys/devices/pci0000:00"
USB_ROOT = f"{PCI_ROOT}/0000:00:14.0/usb3"


def _link(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(os.path.relpath(target, link.parent))


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class FakeSystem:
    """The parts of /sys, /proc and /run/udev that Driver Check reads."""

    def __init__(self, root: Path) -> None:
        self.root = root
        _write(root / "proc/sys/kernel/osrelease", "6.14.0-37-generic\n")
        _write(root / "proc/cmdline", "BOOT_IMAGE=/boot/vmlinuz root=UUID=1 ro quiet splash\n")
        _write(root / "proc/cpuinfo", "processor\t: 0\nflags\t\t: fpu vme de pse\n")
        _write(root / "proc/net/route", "Iface\tDestination\tGateway\tFlags\tRefCnt\tUse\tMetric\tMask\n")

    def pci(self, address: str, vendor: str, device: str, cls: str, *, driver: str = "", model: str = "",
            vendor_name: str = "") -> Path:
        directory = self.root / PCI_ROOT / address
        _write(directory / "vendor", f"0x{vendor}\n")
        _write(directory / "device", f"0x{device}\n")
        _write(directory / "class", f"0x{cls}\n")
        _write(directory / "subsystem_vendor", "0x1028\n")
        _write(directory / "subsystem_device", "0x0a2d\n")
        _write(directory / "modalias",
               f"pci:v0000{vendor.upper()}d0000{device.upper()}sv00001028sd00000A2Dbc{cls[:2]}sc{cls[2:4]}i{cls[4:]}\n")
        if driver:
            target = self.root / "sys/bus/pci/drivers" / driver
            target.mkdir(parents=True, exist_ok=True)
            _link(directory / "driver", target)
        _link(self.root / "sys/bus/pci/devices" / address, directory)
        if model:
            _write(self.root / f"run/udev/data/+pci:{address}",
                   f"E:ID_VENDOR_FROM_DATABASE={vendor_name or 'Vendor Corporation'}\nE:ID_MODEL_FROM_DATABASE={model}\n")
        return directory

    def usb(self, name: str, vendor: str, product: str, interfaces: list[tuple[str, str, str, str]], *,
            product_name: str = "", model: str = "", node: str = "189:5") -> Path:
        directory = self.root / USB_ROOT / name
        _write(directory / "idVendor", f"{vendor}\n")
        _write(directory / "idProduct", f"{product}\n")
        _write(directory / "bDeviceClass", "00\n")
        _write(directory / "dev", f"{node}\n")
        if product_name:
            _write(directory / "product", f"{product_name}\n")
        for index, (cls, subclass, protocol, driver) in enumerate(interfaces):
            interface = directory / f"{name}:1.{index}"
            _write(interface / "bInterfaceClass", f"{cls}\n")
            _write(interface / "bInterfaceSubClass", f"{subclass}\n")
            _write(interface / "bInterfaceProtocol", f"{protocol}\n")
            _write(interface / "modalias", f"usb:v{vendor.upper()}p{product.upper()}d0100dc00dsc00dp00"
                                           f"ic{cls.upper()}isc{subclass.upper()}ip{protocol.upper()}in0{index}\n")
            if driver:
                target = self.root / "sys/bus/usb/drivers" / driver
                target.mkdir(parents=True, exist_ok=True)
                _link(interface / "driver", target)
            _link(self.root / "sys/bus/usb/devices" / interface.name, interface)
        _link(self.root / "sys/bus/usb/devices" / name, directory)
        if model:
            _write(self.root / f"run/udev/data/c{node}", f"E:ID_MODEL_FROM_DATABASE={model}\n")
        return directory

    def acpi(self, name: str, hid: str, *, status: str | None = "15", driver: str = "",
             parent: Path | None = None) -> Path:
        """An ACPI device and the device Linux made for it (under parent), bound to driver."""

        directory = self.root / "sys/devices/LNXSYSTM:00/LNXSYBUS:00" / name
        _write(directory / "hid", f"{hid}\n")
        _write(directory / "modalias", f"acpi:{hid}:\n")
        if status is not None:
            _write(directory / "status", f"{status}\n")
        node = (parent or self.root / "sys/devices/platform") / name
        node.mkdir(parents=True, exist_ok=True)
        _link(directory / "physical_node", node)
        if driver:
            target = self.root / "sys/bus/platform/drivers" / driver
            target.mkdir(parents=True, exist_ok=True)
            _link(node / "driver", target)
        _link(self.root / "sys/bus/acpi/devices" / name, directory)
        return node

    def net(self, name: str, owner: Path, *, wireless: bool = False, operstate: str = "up") -> None:
        directory = owner / "net" / name
        _write(directory / "operstate", f"{operstate}\n")
        _write(directory / "uevent", ("DEVTYPE=wlan\n" if wireless else "") + f"INTERFACE={name}\n")
        if wireless:
            (directory / "wireless").mkdir()
        _link(directory / "device", owner)
        _link(self.root / "sys/class/net" / name, directory)

    def virtual_net(self, name: str) -> None:
        directory = self.root / "sys/devices/virtual/net" / name
        _write(directory / "operstate", "up\n")
        _link(self.root / "sys/class/net" / name, directory)

    def class_device(self, class_name: str, name: str, owner: Path) -> None:
        directory = owner / class_name / name
        directory.mkdir(parents=True)
        _link(directory / "device", owner)
        _link(self.root / "sys/class" / class_name / name, directory)

    def route(self, interface: str) -> None:
        with (self.root / "proc/net/route").open("a", encoding="utf-8") as stream:
            stream.write(f"{interface}\t00000000\t0101A8C0\t0003\t0\t0\t600\t00000000\n")

    def rfkill(self, index: int, kind: str, *, soft: bool = False, hard: bool = False) -> None:
        directory = self.root / f"sys/class/rfkill/rfkill{index}"
        _write(directory / "type", f"{kind}\n")
        _write(directory / "soft", "1\n" if soft else "0\n")
        _write(directory / "hard", "1\n" if hard else "0\n")

    def module(self, name: str) -> None:
        (self.root / "sys/module" / name).mkdir(parents=True, exist_ok=True)

    def dpkg_status(self, packages: dict[str, str]) -> None:
        """/var/lib/dpkg/status: {"nvidia-driver-580": "install ok installed"}."""

        _write(self.root / "var/lib/dpkg/status", "".join(
            f"Package: {name}\nStatus: {status}\nArchitecture: amd64\n\n" for name, status in packages.items()))

    def kernel(self, release: str, *module_files: str, image: bool = True) -> None:
        """A kernel in /lib/modules with these module files (relative to its folder), its image in /boot."""

        (self.root / "lib/modules" / release / "kernel/drivers").mkdir(parents=True, exist_ok=True)
        for name in module_files:
            _write(self.root / "lib/modules" / release / name, "")
        if image:
            _write(self.root / f"boot/vmlinuz-{release}", "")


class FakeRunner:
    """modprobe --resolve-alias, modinfo -n and journalctl, answered from tables."""

    def __init__(self, aliases: dict[str, tuple[str, ...]] | None = None, dkms: tuple[str, ...] = (),
                 kernel_log: str = "") -> None:
        self.aliases = aliases or {}
        self.dkms = dkms
        self.kernel_log = kernel_log
        self.calls: list[list[str]] = []

    def __call__(self, command, timeout):
        command = list(command)
        self.calls.append(command)
        if command[0] == "modprobe":
            modules = next((mods for key, mods in self.aliases.items() if key in command[-1]), ())
            return subprocess.CompletedProcess(command, 0 if modules else 1, "".join(f"{m}\n" for m in modules), "")
        if command[0] == "modinfo":
            folder = "updates/dkms" if command[-1] in self.dkms else "kernel/drivers"
            return subprocess.CompletedProcess(command, 0, f"/lib/modules/6.14.0-37-generic/{folder}/{command[-1]}.ko\n", "")
        if command[0] == "journalctl":
            return subprocess.CompletedProcess(command, 0 if self.kernel_log else 1, self.kernel_log, "")
        raise AssertionError(f"unexpected command {command}")


class HardwareReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.system = FakeSystem(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_reads_devices_drivers_names_and_the_network(self) -> None:
        wifi = self.system.pci("0000:00:14.3", "8086", "51f0", "028000", driver="iwlwifi",
                               model="Alder Lake-P PCH CNVi WiFi (Wi-Fi 6E AX211 160MHz)",
                               vendor_name="Intel Corporation")
        self.system.net("wlp0s20f3", wifi, wireless=True)
        ethernet = self.system.pci("0000:00:1f.6", "8086", "1a1f", "020000", driver="e1000e",
                                   model="Ethernet Connection (16) I219-V")
        self.system.net("enp0s31f6", ethernet, operstate="down")
        self.system.virtual_net("docker0")
        self.system.route("wlp0s20f3")
        runner = FakeRunner()

        snapshot = SystemReader(self.root, runner).snapshot()

        devices = {device.address: device for device in snapshot.pci}
        self.assertEqual("Intel Wi-Fi 6E AX211 160MHz", devices["0000:00:14.3"].name)
        self.assertEqual("iwlwifi", devices["0000:00:14.3"].driver)
        self.assertEqual("028000", devices["0000:00:14.3"].pci_class)
        self.assertEqual("1028:0a2d", devices["0000:00:14.3"].subsystem)
        self.assertEqual(("wlp0s20f3",), devices["0000:00:14.3"].net)
        self.assertEqual(("enp0s31f6",), devices["0000:00:1f.6"].net)
        # docker0 has no device: not a network card.
        self.assertEqual(["enp0s31f6", "wlp0s20f3"], [net.name for net in snapshot.net])
        self.assertTrue(next(net for net in snapshot.net if net.name == "wlp0s20f3").wireless)
        self.assertTrue(snapshot.connected)
        self.assertEqual("6.14.0-37-generic", snapshot.kernel)
        self.assertFalse(snapshot.live or snapshot.virtual or snapshot.secure_boot)
        # Everything works: no module lookups, no kernel log.
        self.assertEqual([], runner.calls)

    def test_a_default_route_through_a_bridge_or_vpn_is_not_a_connection(self) -> None:
        self.system.virtual_net("docker0")
        self.system.route("docker0")
        self.assertFalse(SystemReader(self.root, FakeRunner()).snapshot().connected)

    def test_usb_devices_with_their_bluetooth_adapters_and_video_nodes(self) -> None:
        bluetooth = self.system.usb("3-10", "8087", "0033", [("e0", "01", "01", "btusb"), ("e0", "01", "01", "btusb")],
                                    model="AX211 Bluetooth", node="189:260")
        self.system.class_device("bluetooth", "hci0", bluetooth / "3-10:1.0")
        webcam = self.system.usb("3-1", "05c8", "0b06", [("0e", "01", "00", "uvcvideo"), ("fe", "01", "01", "")],
                                 product_name="HP HD Camera", node="189:257")
        self.system.class_device("video4linux", "video0", webcam / "3-1:1.0")

        devices = {device.address: device for device in SystemReader(self.root, FakeRunner()).snapshot().usb}

        self.assertEqual("Intel AX211 Bluetooth", devices["3-10"].name)
        self.assertEqual(("hci0",), devices["3-10"].bluetooth)
        self.assertEqual(2, len(devices["3-10"].bluetooth_interfaces))
        self.assertEqual("HP HD Camera", devices["3-1"].name)
        self.assertEqual(1, devices["3-1"].video_nodes)
        self.assertEqual("https://linux-hardware.org/?id=usb:05c8-0b06", devices["3-1"].hardware_page())

    def test_sound_cards_belong_to_the_pci_device_above_them(self) -> None:
        audio = self.system.pci("0000:00:1f.3", "8086", "51c8", "040100", driver="sof-audio-pci-intel-tgl")
        platform = audio / "skl_hda_dsp_generic"
        platform.mkdir()
        self.system.class_device("sound", "card0", platform)
        self.system.class_device("sound", "controlC0", platform)   # not a card

        device = SystemReader(self.root, FakeRunner()).snapshot().pci[0]

        self.assertEqual(1, device.sound_cards)

    def test_sound_engines_and_serial_bluetooth_of_atom_tablets(self) -> None:
        # Cherry Trail: the SST engine is an ACPI platform device, its card hangs off the board's machine
        # device; the Broadcom Bluetooth chip sits on the serial port of a PCI UART.
        engine = self.system.acpi("808622A8:00", "808622A8", driver="intel_sst_acpi")
        machine = engine / "cht-bsw-rt5672"
        machine.mkdir()
        self.system.class_device("sound", "card0", machine)
        _write(machine / "sound/card0/id", "chtbswrt5672\n")
        uart = self.system.pci("0000:00:1e.3", "8086", "228c", "078000", driver="intel-lpss") / "dw-apb-uart.3/serial0"
        chip = self.system.acpi("BCM2E7E:00", "BCM2E7E", driver="hci_uart_bcm", parent=uart)
        self.system.class_device("bluetooth", "hci0", chip)
        self.system.acpi("BCM2E3A:00", "BCM2E3A", status="0")   # described by the firmware, not fitted
        self.system.acpi("PNP0C0A:00", "PNP0C0A")                 # the battery: not looked at

        devices = {device.address: device for device in SystemReader(self.root, FakeRunner()).snapshot().acpi}

        self.assertEqual(["808622A8:00", "BCM2E7E:00"], sorted(devices))
        sound, bluetooth = devices["808622A8:00"], devices["BCM2E7E:00"]
        self.assertEqual(("Intel Cherry Trail SST audio", "intel_sst_acpi", 1), (sound.name, sound.driver, sound.sound_cards))
        self.assertEqual(("Broadcom Bluetooth (UART)", "hci_uart_bcm", ("hci0",)),
                         (bluetooth.name, bluetooth.driver, bluetooth.bluetooth))
        self.assertEqual(("808622A8", "acpi:808622A8", ""), (sound.id, sound.key, sound.hardware_page()))

    def test_test_sound_cards_do_not_count_for_a_sound_engine(self) -> None:
        self.system.acpi("80860F28:00", "80860F28", driver="intel_sst_acpi")
        dummy = self.root / "sys/devices/platform/snd_dummy.0"
        dummy.mkdir(parents=True)
        self.system.class_device("sound", "card0", dummy)
        _write(dummy / "sound/card0/id", "Dummy\n")
        runner = FakeRunner(aliases={"acpi:80860F28:": ("snd_intel_sst_acpi",)})

        engine = SystemReader(self.root, runner).snapshot().acpi[0]

        self.assertEqual(0, engine.sound_cards)
        self.assertEqual(("snd_intel_sst_acpi",), engine.modules)

    def test_modules_are_looked_up_only_for_devices_that_do_not_work(self) -> None:
        self.system.pci("0000:02:00.0", "14e4", "43a0", "028000")   # Broadcom, no driver
        self.system.pci("0000:00:02.0", "8086", "4628", "030000", driver="i915")
        self.system.pci("0000:00:14.2", "8086", "51ef", "050000")   # RAM controller: needs no driver
        self.system.module("bcma")
        _write(self.root / "proc/stat", "cpu  1 2 3\nbtime 1760000000\n")
        wl = self.root / "lib/modules/6.14.0-37-generic/updates/dkms/wl.ko"
        _write(wl, "")
        os.utime(wl, (1760000500, 1760000500))   # built by DKMS after this boot
        runner = FakeRunner(aliases={"v000014E4d000043A0": ("bcma", "wl")}, dkms=("wl",))

        devices = {device.address: device for device in SystemReader(self.root, runner).snapshot().pci}

        broadcom = devices["0000:02:00.0"]
        self.assertEqual(("bcma", "wl"), broadcom.modules)
        self.assertEqual(("bcma",), broadcom.loaded_modules)
        self.assertEqual(("wl",), broadcom.dkms_modules)
        self.assertEqual(("wl",), broadcom.new_modules)
        self.assertEqual((), devices["0000:00:02.0"].modules)
        self.assertEqual((), devices["0000:00:14.2"].modules)
        looked_up = [call[-1] for call in runner.calls if call[0] == "modprobe"]
        self.assertEqual(1, len(looked_up))
        self.assertIn("v000014E4d000043A0", looked_up[0])

    def test_nvidia_cards_on_nouveau_are_checked_for_an_installed_nvidia_driver(self) -> None:
        self.system.pci("0000:01:00.0", "10de", "1f99", "030200", driver="nouveau")
        self.system.module("nouveau")
        runner = FakeRunner(aliases={"v000010DEd00001F99": ("nouveau", "nvidia")})

        _write(self.root / "proc/stat", "btime 1760000000\n")
        nvidia = self.root / "lib/modules/6.14.0-37-generic/kernel/drivers/nvidia.ko"
        _write(nvidia, "")
        os.utime(nvidia, (1750000000, 1750000000))   # installed before this boot

        device = SystemReader(self.root, runner).snapshot().pci[0]

        self.assertEqual(("nouveau", "nvidia"), device.modules)
        self.assertEqual(("nouveau",), device.loaded_modules)
        self.assertEqual((), device.new_modules)

    def test_an_nvidia_driver_installed_for_the_next_kernel(self) -> None:
        # Ticket H-1223: NVIDIA 580 came with the signed modules of Linux 7.0 and that kernel; 6.14 still runs, has
        # no NVIDIA module, and the card is on nouveau until the restart.
        self.system.pci("0000:04:00.0", "10de", "1341", "030200", driver="nouveau")
        self.system.module("nouveau")
        runner = FakeRunner(aliases={"v000010DEd00001341": ("nouveau",)})
        self.system.dpkg_status({
            "nvidia-driver-580": "install ok installed",
            "linux-modules-nvidia-580-generic-hwe-24.04": "install ok installed",
            "nvidia-driver-470": "deinstall ok config-files",
        })
        self.system.kernel("6.14.0-37-generic")                                  # running
        self.system.kernel("7.0.0-42-generic", "kernel/nvidia-580/nvidia.ko", "kernel/nvidia-580/nvidia-drm.ko")
        self.system.kernel("6.11.0-29-generic", "updates/dkms/nvidia.ko.zst")   # older
        self.system.kernel("7.0.0-40-generic", "kernel/nvidia-580/nvidia.ko", image=False)   # removed, folder left

        snapshot = SystemReader(self.root, runner).snapshot()

        self.assertEqual(("nvidia-driver-580",), snapshot.nvidia_drivers)
        self.assertEqual(("/lib/modules/7.0.0-42-generic/kernel/nvidia-580/nvidia.ko",), snapshot.nvidia_modules)
        self.assertEqual(("nouveau",), snapshot.pci[0].modules)
        finding = next(finding for finding in analyze(snapshot).findings if finding.area == "graphics")
        self.assertEqual(("graphics:nvidia-restart:pci:10de:1341", [REBOOT]),
                         (finding.key, [action.kind for action in finding.actions]))

    def test_an_nvidia_driver_built_by_dkms_for_the_next_kernel(self) -> None:
        self.system.pci("0000:01:00.0", "10de", "1f99", "030000")
        self.system.dpkg_status({"nvidia-driver-580-open": "install ok installed"})
        self.system.kernel("6.14.0-37-generic")
        self.system.kernel("6.17.0-8-generic", "updates/dkms/nvidia.ko.zst")

        snapshot = SystemReader(self.root, FakeRunner()).snapshot()

        self.assertEqual(("nvidia-driver-580-open",), snapshot.nvidia_drivers)
        self.assertEqual(("/lib/modules/6.17.0-8-generic/updates/dkms/nvidia.ko.zst",), snapshot.nvidia_modules)

    def test_the_nvidia_driver_is_only_looked_for_when_the_card_does_not_run_on_it(self) -> None:
        self.system.dpkg_status({"nvidia-driver-580": "install ok installed"})
        self.system.kernel("7.0.0-42-generic", "kernel/nvidia-580/nvidia.ko")
        card = self.system.pci("0000:01:00.0", "10de", "1f99", "030200", driver="nvidia")

        snapshot = SystemReader(self.root, FakeRunner()).snapshot()

        self.assertEqual(((), ()), (snapshot.nvidia_drivers, snapshot.nvidia_modules))
        # Nor in the live session, where the NVIDIA driver only comes after installing.
        (card / "driver").unlink()
        _write(self.root / "proc/cmdline", "BOOT_IMAGE=/casper/vmlinuz boot=casper quiet splash\n")
        live = SystemReader(self.root, FakeRunner()).snapshot()
        self.assertEqual((True, "", ()), (live.live, live.pci[0].driver, live.nvidia_drivers))

    def test_an_nvidia_driver_dpkg_could_not_finish_is_not_installed(self) -> None:
        self.system.pci("0000:01:00.0", "10de", "1f99", "030200", driver="nouveau")
        self.system.dpkg_status({"nvidia-driver-580": "install ok half-configured",
                                 "nvidia-driver-assistant": "install ok installed"})
        self.system.kernel("7.0.0-42-generic", "kernel/nvidia-580/nvidia.ko")

        snapshot = SystemReader(self.root, FakeRunner()).snapshot()

        self.assertEqual(((), ("nvidia-driver-580",)), (snapshot.nvidia_drivers, snapshot.unfinished_packages))
        self.assertEqual((), snapshot.nvidia_modules)

    def test_the_bluetooth_function_of_a_pci_wifi_card(self) -> None:
        # Ticket H-1223, an ASUS X550LN: the Ralink RT3290's Wi-Fi works with rt2800pci; its Bluetooth function
        # (class 0d11) has no driver in Linux.
        wifi = self.system.pci("0000:03:00.0", "1814", "3290", "028000", driver="rt2800pci",
                               model="RT3290 Wireless 802.11n 1T/1R PCIe", vendor_name="Ralink corp.")
        self.system.net("wlp3s0", wifi, wireless=True)
        self.system.pci("0000:03:00.1", "1814", "3298", "0d1100", model="RT3290 Bluetooth", vendor_name="Ralink corp.")
        runner = FakeRunner()

        snapshot = SystemReader(self.root, runner).snapshot()

        bluetooth = next(device for device in snapshot.pci if device.product == "3298")
        self.assertEqual(("Ralink RT3290 Bluetooth", "0d1100", "", ()), (bluetooth.name, bluetooth.pci_class,
                                                                          bluetooth.driver, bluetooth.bluetooth))
        # Looked up like any device without a driver, and the kernel log is read for a firmware error.
        self.assertIn("pci:v00001814d00003298", " ".join(call[-1] for call in runner.calls if call[0] == "modprobe"))
        self.assertTrue(any(call[0] == "journalctl" for call in runner.calls))
        report = analyze(snapshot)
        self.assertEqual(["bluetooth:no-driver:pci:1814:3298"], [finding.key for finding in report.findings])
        self.assertEqual("Ralink RT3290 Bluetooth (no Linux driver yet)",
                         {area.key: area.summary for area in report.areas}["bluetooth"])

    def test_firmware_errors_are_read_only_when_a_device_does_not_work(self) -> None:
        log = (
            "iwlwifi 0000:00:14.3: Direct firmware load for iwlwifi-so-a0-gf-a0-89.ucode failed with error -2\n"
            "bluetooth hci0: Direct firmware load for rtl_bt/rtl8852bu_fw.bin failed with error -2\n"
            "i915 0000:00:02.0: [drm] Finished loading DMC firmware i915/adlp_dmc.bin (v2.20)\n"
        )
        wifi = self.system.pci("0000:00:14.3", "8086", "51f0", "028000", driver="iwlwifi")
        self.system.net("wlan0", wifi, wireless=True)
        working = FakeRunner(kernel_log=log)
        self.assertEqual((), SystemReader(self.root, working).snapshot().firmware_errors)
        self.assertFalse(any(call[0] == "journalctl" for call in working.calls))

        self.system.usb("3-10", "0bda", "b85c", [("e0", "01", "01", "btusb")])   # no hci: firmware failed
        failing = FakeRunner(kernel_log=log)
        errors = SystemReader(self.root, failing).snapshot().firmware_errors

        self.assertEqual(
            [("iwlwifi", "0000:00:14.3", "iwlwifi-so-a0-gf-a0-89.ucode"), ("bluetooth", "hci0", "rtl_bt/rtl8852bu_fw.bin")],
            [(error.driver, error.device, error.file) for error in errors],
        )

    def test_an_intel_port_stuck_in_ultra_low_power_mode_is_read_from_the_kernel_log(self) -> None:
        log = (
            "e1000e 0000:00:19.0 0000:00:19.0 (uninitialized): Failed to disable ULP\n"
            "e1000e 0000:00:19.0: probe with driver e1000e failed with error -2\n"
        )
        port = self.system.pci("0000:00:19.0", "8086", "15a2", "020000")
        runner = FakeRunner(aliases={"pci:v00008086d000015A2": ("e1000e",)}, kernel_log=log)
        self.assertEqual(("0000:00:19.0",), SystemReader(self.root, runner).snapshot().ulp_stuck)

        # A working port: the kernel log is not read for it.
        self.system.net("enp0s25", port)
        working = FakeRunner(aliases={"pci:v00008086d000015A2": ("e1000e",)}, kernel_log=log)
        self.assertEqual((), SystemReader(self.root, working).snapshot().ulp_stuck)

    def test_live_session_virtual_machine_and_secure_boot(self) -> None:
        _write(self.root / "proc/cmdline", "BOOT_IMAGE=/casper/vmlinuz boot=casper quiet splash\n")
        _write(self.root / "proc/cpuinfo", "flags\t\t: fpu vme hypervisor\n")
        variable = self.root / "sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
        variable.parent.mkdir(parents=True)
        variable.write_bytes(b"\x06\x00\x00\x00\x01")

        snapshot = SystemReader(self.root, FakeRunner()).snapshot()

        self.assertTrue(snapshot.live)
        self.assertTrue(snapshot.virtual)
        self.assertTrue(snapshot.secure_boot)

    def test_rfkill_switches(self) -> None:
        self.system.rfkill(0, "wlan", hard=True)
        self.system.rfkill(1, "bluetooth", soft=True)

        switches = SystemReader(self.root, FakeRunner()).snapshot().rfkill

        self.assertEqual([("wlan", False, True), ("bluetooth", True, False)],
                         [(switch.kind, switch.soft, switch.hard) for switch in switches])

    def test_a_missing_system_tree_gives_an_empty_snapshot(self) -> None:
        snapshot = SystemReader(self.root / "nothing", FakeRunner()).snapshot()
        self.assertEqual((), snapshot.devices)
        self.assertFalse(snapshot.connected)


class NamesAndKnowledgeTests(unittest.TestCase):
    def test_friendly_model_prefers_the_marketing_name(self) -> None:
        self.assertEqual("Wi-Fi 6E AX211 160MHz", friendly_model("Alder Lake-P PCH CNVi WiFi (Wi-Fi 6E AX211 160MHz)"))
        self.assertEqual("GeForce GTX 1650 Mobile / Max-Q", friendly_model("TU117M [GeForce GTX 1650 Mobile / Max-Q]"))
        self.assertEqual("Wireless-AC 9560 160MHz",
                         friendly_model("Cannon Point-LP CNVi [Wireless-AC] (Wireless-AC 9560 160MHz)"))
        self.assertEqual("Ethernet Connection (16) I219-V", friendly_model("Ethernet Connection (16) I219-V"))
        self.assertEqual("BCM4360 802.11ac Wireless Network Adapter",
                         friendly_model("BCM4360 802.11ac Wireless Network Adapter"))
        # A subsystem name that names the computer is not the device's name.
        self.assertEqual("GeForce GTX 1650 Mobile / Max-Q",
                         friendly_model("TU117M [GeForce GTX 1650 Mobile / Max-Q] (XPS 15 7590)"))
        self.assertEqual("82801I (ICH9 Family) HD Audio Controller",
                         friendly_model("82801I (ICH9 Family) HD Audio Controller (QEMU Virtual Machine)"))

    def test_the_newer_of_two_kernels(self) -> None:
        self.assertGreater(kernel_order("7.0.0-42-generic"), kernel_order("6.14.0-37-generic"))
        self.assertGreater(kernel_order("6.14.0-37-generic"), kernel_order("6.8.0-90-generic"))   # not text order
        self.assertGreater(kernel_order("6.14.0-37-generic"), kernel_order("6.14.0-36-generic"))
        self.assertEqual(kernel_order("6.14.0-37-generic"), kernel_order("6.14.0-37-lowlatency"))

    def test_libfprint_hwdb_gives_supported_and_unsupported_readers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            hwdb = Path(temp) / "usr/lib/udev/hwdb.d/60-autosuspend-libfprint-2.hwdb"
            _write(hwdb, (
                "# This file has been generated using fprint-list-udev-hwdb with all drivers enabled\n\n"
                "# Supported by libfprint driver elanmoc\nusb:v04F3p0C7E*\nusb:v04F3p0C82*\n ID_AUTOSUSPEND=1\n\n"
                "# Supported by libfprint driver goodixmoc\nusb:v27C6p5395*\n ID_AUTOSUSPEND=1\n\n"
                "# Known unsupported devices\nusb:v27C6p55A4*\nusb:v06CBp00DA*\n ID_AUTOSUSPEND=1\n"
            ))
            support = read_libfprint_support(temp)
        self.assertEqual("elanmoc", support["04f3:0c7e"])
        self.assertEqual("goodixmoc", support["27c6:5395"])
        self.assertEqual("", support["27c6:55a4"])
        self.assertEqual("", support["06cb:00da"])
        self.assertEqual({}, read_libfprint_support("/nonexistent"))

    def test_the_image_processor_of_atom_tablets(self) -> None:
        from caramos_driver_check.hardware import Device
        from caramos_driver_check.knowledge import atom_isp

        self.assertTrue(atom_isp(Device("pci", "0000:00:03.0", "8086", "22b8", "Intel Atom ISP", pci_class="048000")))
        self.assertFalse(atom_isp(Device("pci", "0000:00:03.0", "8086", "22b0", "Intel HD Graphics", pci_class="030000")))

    def test_intel_ipu_needs_the_multimedia_class(self) -> None:
        from caramos_driver_check.hardware import Device

        self.assertTrue(intel_ipu(Device("pci", "0000:00:05.0", "8086", "465d", "Intel IPU", pci_class="048000")))
        self.assertFalse(intel_ipu(Device("pci", "0000:00:05.0", "8086", "465d", "Intel", pci_class="060000")))
        self.assertTrue(intel_ipu(Device("pci", "0000:00:05.0", "8086", "ffff", "Intel Meteor Lake IPU",
                                         pci_class="048000")))


if __name__ == "__main__":
    unittest.main()

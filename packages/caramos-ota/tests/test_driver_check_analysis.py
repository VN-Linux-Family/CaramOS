"""What Driver Check tells the user for typical machines."""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

# Driver Check lives in /usr/share/caramos-ota/driver-check, outside dist-packages.
sys.path.insert(0, str(Path(__file__).parents[1] / "usr/share/caramos-ota/driver-check"))

from caramos_driver_check.analysis import (
    CRITICAL,
    DRIVER_MANAGER,
    INFO,
    INSTALL,
    OK,
    REBOOT,
    REPORT,
    TIP,
    UPDATE_MANAGER,
    WARNING,
    WIFI_ON,
    analyze,
    worst,
)
from caramos_driver_check.drivers import DriverProposal
from caramos_driver_check.hardware import Device, FirmwareError, NetInterface, RfkillSwitch, Snapshot, UsbInterface

KERNEL = "6.14.0-37-generic"

INTEL_WIFI = Device("pci", "0000:00:14.3", "8086", "51f0", "Intel Wi-Fi 6E AX211", driver="iwlwifi",
                    pci_class="028000", net=("wlp0s20f3",))
INTEL_ETHERNET = Device("pci", "0000:00:1f.6", "8086", "1a1f", "Intel Ethernet I219-V", driver="e1000e",
                        pci_class="020000", net=("enp0s31f6",))
INTEL_GPU = Device("pci", "0000:00:02.0", "8086", "4628", "Intel UHD Graphics", driver="i915", pci_class="030000")
INTEL_AUDIO = Device("pci", "0000:00:1f.3", "8086", "51c8", "Intel HD Audio", driver="sof-audio-pci-intel-tgl",
                     pci_class="040100", sound_cards=1)
BLUETOOTH = Device("usb", "3-10", "8087", "0033", "Intel AX211 Bluetooth", vendor_name="Intel",
                   interfaces=(UsbInterface("1.0", "e0", "01", "01", "btusb"),), bluetooth=("hci0",))
WEBCAM = Device("usb", "3-1", "05c8", "0b06", "HP HD Camera",
                interfaces=(UsbInterface("1.0", "0e", "01", "00", "uvcvideo"), UsbInterface("1.2", "fe", "01", "01")),
                video_nodes=2)
BROADCOM = Device("pci", "0000:02:00.0", "14e4", "43a0", "Broadcom BCM4360 802.11ac Wireless Network Adapter",
                  pci_class="028000", subsystem="106b:0117")
WIFI_UP = NetInterface("wlp0s20f3", wireless=True, up=True, driver="iwlwifi", bus="pci", address="0000:00:14.3")
ETHERNET_DOWN = NetInterface("enp0s31f6", wireless=False, up=False, driver="e1000e", bus="pci", address="0000:00:1f.6")
ETHERNET_UP = replace(ETHERNET_DOWN, up=True)


def laptop(**changes) -> Snapshot:
    """A laptop where everything works, online over Wi-Fi."""

    snapshot = Snapshot(
        pci=(INTEL_WIFI, INTEL_ETHERNET, INTEL_GPU, INTEL_AUDIO),
        usb=(BLUETOOTH, WEBCAM),
        net=(ETHERNET_DOWN, WIFI_UP),
        rfkill=(RfkillSwitch("wlan", False, False), RfkillSwitch("bluetooth", False, False)),
        connected=True,
        kernel=KERNEL,
    )
    return replace(snapshot, **changes)


def broadcom_laptop(**changes) -> Snapshot:
    """The Wi-Fi card is a Broadcom without a driver; the network port works but has no cable."""

    defaults = {"pci": (BROADCOM, INTEL_ETHERNET, INTEL_GPU, INTEL_AUDIO), "net": (ETHERNET_DOWN,), "connected": False}
    return laptop(**{**defaults, **changes})


def kinds(finding) -> list[str]:
    return [action.kind for action in finding.actions]


class AllGoodTests(unittest.TestCase):
    def test_a_working_laptop_has_no_problems(self) -> None:
        report = analyze(laptop())

        self.assertEqual((), report.problems)
        self.assertEqual((), report.findings)
        self.assertEqual(["wifi", "ethernet", "graphics", "audio", "bluetooth", "camera"],
                         [area.key for area in report.areas])
        self.assertTrue(all(area.level == OK for area in report.areas))
        areas = {area.key: area.summary for area in report.areas}
        self.assertEqual("Intel Wi-Fi 6E AX211 (connected)", areas["wifi"])
        self.assertEqual("Intel Ethernet I219-V (no cable plugged in)", areas["ethernet"])
        self.assertTrue(report.wired_port)
        self.assertFalse(report.needs_connection)

    def test_missing_hardware_is_shown_as_absent(self) -> None:
        report = analyze(laptop(usb=()))
        areas = {area.key: area.level for area in report.areas}
        self.assertEqual("absent", areas["bluetooth"])
        self.assertEqual("absent", areas["camera"])
        self.assertNotIn("fingerprint", areas)


class NetworkTests(unittest.TestCase):
    def test_an_intel_port_stuck_in_ultra_low_power_mode(self) -> None:
        # Ticket H-1174: "e1000e 0000:00:19.0: Failed to disable ULP", then the probe failed. No firmware or kernel
        # update helps; the advice is a full power off.
        stuck = Device("pci", "0000:00:19.0", "8086", "15a2", "Intel Ethernet Connection (3) I218-LM",
                       pci_class="020000", modules=("e1000e",), loaded_modules=("e1000e",))
        report = analyze(laptop(pci=(INTEL_WIFI, stuck, INTEL_GPU, INTEL_AUDIO), net=(WIFI_UP,),
                                ulp_stuck=("0000:00:19.0",)))
        finding = report.findings[0]
        self.assertEqual(("ethernet:low-power:pci:8086:15a2", WARNING), (finding.key, finding.level))
        self.assertEqual([REPORT], kinds(finding))
        self.assertIn("Ultra Low Power Mode", finding.detail)
        self.assertNotIn("linux-firmware", finding.detail)

        # Without that kernel line it stays the general "does not start" finding.
        other = analyze(laptop(pci=(INTEL_WIFI, stuck, INTEL_GPU, INTEL_AUDIO), net=(WIFI_UP,))).findings[0]
        self.assertEqual("ethernet:failed:pci:8086:15a2", other.key)

    def test_broadcom_offline_is_critical_and_explains_how_to_get_online(self) -> None:
        report = analyze(broadcom_laptop())

        finding = report.findings[0]
        self.assertEqual(CRITICAL, finding.level)
        self.assertEqual("wifi:broadcom:pci:14e4:43a0", finding.key)
        self.assertEqual([DRIVER_MANAGER, REPORT], kinds(finding))
        self.assertTrue(finding.connect_help)
        self.assertTrue(finding.offline_media)
        self.assertTrue(any("USB" in text for text, _good in finding.notes))
        self.assertEqual("PCI 14e4:43a0", finding.device_id)
        self.assertEqual("https://linux-hardware.org/?id=pci:14e4-43a0-106b-0117", finding.link)
        self.assertTrue(report.needs_connection)
        self.assertTrue(report.offline_media)
        self.assertTrue(report.wired_port)
        self.assertEqual(CRITICAL, {area.key: area.level for area in report.areas}["wifi"])

    def test_broadcom_while_online_is_a_warning_without_connection_help(self) -> None:
        report = analyze(broadcom_laptop(net=(ETHERNET_UP,), connected=True))

        finding = report.findings[0]
        self.assertEqual(WARNING, finding.level)
        self.assertFalse(finding.connect_help)
        self.assertNotIn("CaramOS USB", finding.detail)
        self.assertFalse(report.needs_connection)

    def test_broadcom_in_the_live_session_does_not_offer_the_usb_stick(self) -> None:
        finding = analyze(broadcom_laptop(live=True)).findings[0]
        self.assertFalse(finding.offline_media)
        self.assertIn("after installing", finding.detail)

    def test_a_card_the_kernel_has_no_driver_for(self) -> None:
        mediatek = Device("pci", "0000:01:00.0", "14c3", "7902", "MediaTek MT7902", pci_class="028000")
        report = analyze(laptop(pci=(mediatek, INTEL_GPU, INTEL_AUDIO), net=(), connected=False))

        finding = report.findings[0]
        self.assertEqual("wifi:no-driver:pci:14c3:7902", finding.key)
        self.assertEqual(CRITICAL, finding.level)
        self.assertIn("Linux 6.14 has no driver", finding.detail)
        self.assertEqual([REPORT], kinds(finding))
        self.assertTrue(finding.connect_help)
        self.assertFalse(report.wired_port)

    def test_a_driver_installed_since_boot_asks_for_a_restart(self) -> None:
        installed = replace(BROADCOM, driver="bcma-pci-bridge", modules=("bcma", "wl"), loaded_modules=("bcma",),
                            new_modules=("wl",), dkms_modules=("wl",))
        report = analyze(broadcom_laptop(pci=(installed, INTEL_GPU, INTEL_AUDIO), secure_boot=True))

        finding = report.findings[0]
        self.assertEqual("wifi:restart:pci:14e4:43a0", finding.key)
        self.assertEqual([REBOOT], kinds(finding))
        self.assertIn("Enroll MOK", finding.detail)
        self.assertFalse(finding.connect_help)

    def test_without_secure_boot_there_is_no_mok_note(self) -> None:
        installed = replace(BROADCOM, modules=("wl",), new_modules=("wl",), dkms_modules=("wl",))
        finding = analyze(broadcom_laptop(pci=(installed,))).findings[0]
        self.assertEqual([REBOOT], kinds(finding))
        self.assertNotIn("MOK", finding.detail)

    def test_a_driver_that_exists_but_did_not_load_is_not_a_restart(self) -> None:
        # e1000e blacklisted: the module is there since the kernel was installed, so a restart won't help.
        port = replace(INTEL_ETHERNET, driver="", net=(), modules=("e1000e",))
        report = analyze(laptop(pci=(port, INTEL_GPU, INTEL_AUDIO), net=(), connected=False))

        finding = report.findings[0]
        self.assertEqual(("ethernet:blocked:pci:8086:1a1f", CRITICAL), (finding.key, finding.level))
        self.assertIn("blacklisted", finding.detail)
        self.assertEqual([REPORT], kinds(finding))
        self.assertTrue(finding.connect_help)

    def test_secure_boot_blocking_a_dkms_driver(self) -> None:
        blocked = replace(BROADCOM, driver="bcma-pci-bridge", modules=("bcma", "wl"), loaded_modules=("bcma",),
                          dkms_modules=("wl",))
        finding = analyze(broadcom_laptop(pci=(blocked,), secure_boot=True)).findings[0]
        self.assertEqual("wifi:blocked:pci:14e4:43a0", finding.key)
        self.assertIn("update-secureboot-policy --enroll-key", finding.detail)

    def test_a_loaded_driver_whose_card_does_not_start_names_the_missing_firmware(self) -> None:
        failing = replace(INTEL_WIFI, net=(), modules=("iwlwifi",), loaded_modules=("iwlwifi",))
        report = analyze(laptop(
            pci=(failing, INTEL_ETHERNET, INTEL_GPU, INTEL_AUDIO), net=(ETHERNET_UP,),
            firmware_errors=(FirmwareError("iwlwifi", "0000:00:14.3", "iwlwifi-gl-c0-fm-c0-90.ucode"),),
        ))

        finding = report.findings[0]
        self.assertEqual("wifi:failed:pci:8086:51f0", finding.key)
        self.assertEqual(WARNING, finding.level)
        self.assertIn("iwlwifi-gl-c0-fm-c0-90.ucode", finding.detail)
        self.assertEqual([UPDATE_MANAGER, REPORT], kinds(finding))

    def test_a_broken_network_port_is_not_critical_while_wifi_works(self) -> None:
        port = Device("pci", "0000:03:00.0", "1f0a", "6801", "Motorcomm YT6801", pci_class="020000")
        report = analyze(laptop(pci=(INTEL_WIFI, port, INTEL_GPU, INTEL_AUDIO), net=(WIFI_UP,), connected=False))

        finding = report.findings[0]
        self.assertEqual("ethernet:no-driver:pci:1f0a:6801", finding.key)
        self.assertEqual(WARNING, finding.level)
        self.assertFalse(report.needs_connection)

    def test_no_network_hardware_at_all_offline(self) -> None:
        report = analyze(laptop(pci=(INTEL_GPU, INTEL_AUDIO), net=(), connected=False))
        self.assertEqual(["network:none"], [finding.key for finding in report.critical])
        self.assertTrue(report.needs_connection)

    def test_wifi_switched_off(self) -> None:
        hard = analyze(laptop(connected=False, rfkill=(RfkillSwitch("wlan", False, True),)))
        self.assertEqual(("wifi:hard-blocked", WARNING), (hard.findings[0].key, hard.findings[0].level))

        soft = analyze(laptop(connected=False, rfkill=(RfkillSwitch("wlan", True, False),)))
        self.assertEqual(("wifi:soft-blocked", WARNING), (soft.findings[0].key, soft.findings[0].level))
        self.assertEqual([WIFI_ON], kinds(soft.findings[0]))

        # Airplane mode while online (over a cable) is the user's choice.
        self.assertEqual((), analyze(laptop(rfkill=(RfkillSwitch("wlan", True, False),))).findings)

    def test_usb_wifi_adapter_without_driver(self) -> None:
        dongle = Device("usb", "1-2", "0bda", "8812", "Realtek RTL8812AU 802.11a/b/g/n/ac 2T2R DB WLAN Adapter",
                        interfaces=(UsbInterface("1.0", "ff", "ff", "ff", "", "usb:v0BDAp8812"),))
        report = analyze(laptop(pci=(INTEL_GPU, INTEL_AUDIO), usb=(dongle,), net=(), connected=False))

        self.assertEqual("wifi:no-driver:usb:0bda:8812", report.findings[0].key)
        self.assertEqual(CRITICAL, report.findings[0].level)
        self.assertNotIn("other", [finding.area for finding in report.findings])


class OneClickInstallTests(unittest.TestCase):
    BCMWL = DriverProposal("bcmwl-kernel-source", "bcmwl-kernel-source", BROADCOM.address, offline=True)
    NVIDIA_580 = DriverProposal("nvidia-driver-580-open", "nvidia:580-open", "0000:01:00.0")

    def test_broadcom_with_ubuntu_driver_installs_with_one_click(self) -> None:
        report = analyze(broadcom_laptop(), proposals=[self.BCMWL])
        finding = report.findings[0]
        self.assertEqual([INSTALL, DRIVER_MANAGER], kinds(finding))
        self.assertEqual("bcmwl-kernel-source", finding.install.target)
        self.assertEqual((finding.install,), report.installs)
        self.assertTrue(any("bcmwl-kernel-source" in text for text, good in finding.notes if good))

    def test_the_usb_stick_is_only_mentioned_while_offline(self) -> None:
        online = analyze(broadcom_laptop(net=(ETHERNET_UP,), connected=True), proposals=[self.BCMWL]).findings[0]
        self.assertFalse(any("USB" in text for text, _good in online.notes))

    def test_secure_boot_warns_before_installing_a_dkms_driver(self) -> None:
        finding = analyze(broadcom_laptop(secure_boot=True), proposals=[self.BCMWL]).findings[0]
        self.assertTrue(any("Secure Boot" in text for text, good in finding.notes if not good))

    def test_nvidia_driver_installs_with_one_click(self) -> None:
        nvidia = GraphicsTests.NVIDIA
        report = analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU, nvidia, INTEL_AUDIO)), proposals=[self.NVIDIA_580])
        finding = report.findings[0]
        self.assertEqual([INSTALL, DRIVER_MANAGER], kinds(finding))
        self.assertEqual("nvidia:580-open", finding.install.target)
        self.assertIn("580", finding.install.label)
        self.assertTrue(any("580" in text for text, good in finding.notes if good))

    def test_offline_only_drivers_on_the_usb_stick_can_install(self) -> None:
        nvidia = GraphicsTests.NVIDIA
        offline = analyze(broadcom_laptop(pci=(BROADCOM, INTEL_GPU, nvidia, INTEL_AUDIO)),
                          proposals=[self.BCMWL, self.NVIDIA_580])
        self.assertEqual(["bcmwl-kernel-source"], [action.target for action in offline.installs])
        nvidia_finding = next(f for f in offline.findings if f.area == "graphics")
        self.assertFalse(offline.can_install(nvidia_finding))
        online = analyze(broadcom_laptop(pci=(BROADCOM, INTEL_GPU, nvidia, INTEL_AUDIO), net=(ETHERNET_UP,),
                                         connected=True), proposals=[self.BCMWL, self.NVIDIA_580])
        self.assertEqual(["bcmwl-kernel-source", "nvidia:580-open"], [action.target for action in online.installs])

    def test_no_install_in_the_live_session(self) -> None:
        nvidia = GraphicsTests.NVIDIA
        report = analyze(laptop(pci=(INTEL_WIFI, nvidia, INTEL_AUDIO), live=True), proposals=[self.NVIDIA_580])
        self.assertEqual((), report.installs)

    def test_extra_drivers_only_for_devices_without_one(self) -> None:
        working = DriverProposal("bcmwl-kernel-source", "bcmwl-kernel-source", INTEL_WIFI.address)
        self.assertEqual((), analyze(laptop(), proposals=[working]).findings)
        unknown = Device("pci", "0000:05:00.0", "80ee", "cafe", "VirtualBox Guest Service", pci_class="088000")
        tools = DriverProposal("virtualbox-guest-utils", "virtualbox-guest-utils", unknown.address)
        report = analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU, INTEL_AUDIO, unknown)), proposals=[tools])
        self.assertEqual([("driver:virtualbox-guest-utils", TIP)], [(f.key, f.level) for f in report.findings])
        self.assertEqual("virtualbox-guest-utils", report.findings[0].install.target)
        # Suggestions are not counted in "install all".
        self.assertEqual((), report.installs)


class GraphicsTests(unittest.TestCase):
    NVIDIA = Device("pci", "0000:01:00.0", "10de", "1f99", "NVIDIA GeForce GTX 1650 Mobile / Max-Q",
                    driver="nouveau", pci_class="030200", modules=("nouveau",), loaded_modules=("nouveau",))

    def test_nvidia_on_nouveau_suggests_the_nvidia_driver(self) -> None:
        finding = analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU, self.NVIDIA, INTEL_AUDIO))).findings[0]
        self.assertEqual(("graphics:nvidia:pci:10de:1f99", WARNING), (finding.key, finding.level))
        self.assertEqual([DRIVER_MANAGER], kinds(finding))
        self.assertIn("nouveau", finding.detail)

    # GeForce GT 730 (Kepler): Ubuntu's only driver is NVIDIA 470, which cannot work with Linux 6.12 and later.
    KEPLER = Device("pci", "0000:01:00.0", "10de", "1287", "NVIDIA GeForce GT 730", driver="nouveau",
                    pci_class="030000", modules=("nouveau",), loaded_modules=("nouveau",))
    NVIDIA_470 = DriverProposal(package="nvidia-driver-470", target="nvidia:470", address="0000:01:00.0", usable=False)

    def test_an_nvidia_card_whose_only_driver_cannot_work_stays_on_nouveau(self) -> None:
        # Ticket H-1177: the warning sent the user to Driver Manager, which installs 470 and breaks dpkg.
        report = analyze(laptop(pci=(INTEL_WIFI, self.KEPLER, INTEL_AUDIO)), proposals=[self.NVIDIA_470])
        finding = report.findings[0]
        self.assertEqual(("graphics:nvidia-none:pci:10de:1287", INFO), (finding.key, finding.level))
        self.assertEqual([], kinds(finding))
        self.assertIn("NVIDIA 470", finding.detail)
        self.assertIn("6.14", finding.detail)
        self.assertNotIn(DRIVER_MANAGER, [kind for f in report.findings for kind in kinds(f)])
        self.assertEqual((), report.installs)

    def test_an_nvidia_card_with_neither_driver_asks_for_help(self) -> None:
        bare = replace(self.KEPLER, driver="", loaded_modules=())
        finding = analyze(laptop(pci=(INTEL_WIFI, bare, INTEL_AUDIO)), proposals=[self.NVIDIA_470]).findings[0]
        self.assertEqual(("graphics:nvidia-none:pci:10de:1287", WARNING), (finding.key, finding.level))
        self.assertEqual([REPORT], kinds(finding))

    def test_nvidia_driver_installed_but_not_running_asks_for_a_restart(self) -> None:
        installed = replace(self.NVIDIA, modules=("nouveau", "nvidia"), new_modules=("nvidia",))
        finding = analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU, installed, INTEL_AUDIO))).findings[0]
        self.assertEqual("graphics:nvidia-restart:pci:10de:1f99", finding.key)
        self.assertEqual([REBOOT], kinds(finding))

    def test_nvidia_driver_installed_long_ago_that_does_not_load(self) -> None:
        stuck = replace(self.NVIDIA, modules=("nouveau", "nvidia"))
        finding = analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU, stuck, INTEL_AUDIO))).findings[0]
        self.assertEqual("graphics:nvidia-blocked:pci:10de:1f99", finding.key)

    def test_nvidia_with_its_driver_is_fine(self) -> None:
        working = replace(self.NVIDIA, driver="nvidia", modules=(), loaded_modules=())
        self.assertEqual((), analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU, working, INTEL_AUDIO))).findings)

    def test_nvidia_in_the_live_session_is_only_information(self) -> None:
        finding = analyze(laptop(pci=(INTEL_WIFI, self.NVIDIA, INTEL_AUDIO), live=True)).findings[0]
        self.assertEqual(INFO, finding.level)
        self.assertEqual([], kinds(finding))

    def test_graphics_are_not_judged_in_a_virtual_machine(self) -> None:
        bochs = Device("pci", "0000:00:01.0", "1234", "1111", "QEMU VGA", pci_class="030000")
        report = analyze(laptop(pci=(INTEL_WIFI, bochs, INTEL_AUDIO), virtual=True))
        self.assertEqual((), report.findings)

    def test_a_graphics_card_without_driver(self) -> None:
        new_gpu = Device("pci", "0000:00:02.0", "8086", "b080", "Intel Panther Lake Graphics", pci_class="030000")
        finding = analyze(laptop(pci=(INTEL_WIFI, new_gpu, INTEL_AUDIO))).findings[0]
        self.assertEqual(("graphics:no-driver:pci:8086:b080", WARNING), (finding.key, finding.level))
        self.assertIn("basic mode", finding.detail)

    GM45 = "Intel Mobile 4 Series Chipset Integrated Graphics Controller"

    def test_the_second_display_function_of_old_intel_graphics_needs_no_driver(self) -> None:
        # GM45 (Core 2 laptops): i915 drives 00:02.0, and 00:02.1 is the same chip's second display pipe.
        vga = Device("pci", "0000:00:02.0", "8086", "2a42", self.GM45, driver="i915", pci_class="030000")
        second = Device("pci", "0000:00:02.1", "8086", "2a43", self.GM45, pci_class="038000")
        report = analyze(laptop(pci=(INTEL_WIFI, vga, second, INTEL_AUDIO)))
        self.assertEqual((), report.findings)
        graphics = next(area for area in report.areas if area.key == "graphics")
        self.assertEqual(OK, graphics.level)

    def test_old_intel_graphics_without_driver_is_one_card(self) -> None:
        vga = Device("pci", "0000:00:02.0", "8086", "2a42", self.GM45, pci_class="030000")
        second = Device("pci", "0000:00:02.1", "8086", "2a43", self.GM45, pci_class="038000")
        report = analyze(laptop(pci=(INTEL_WIFI, vga, second, INTEL_AUDIO)))
        self.assertEqual(["graphics:no-driver:pci:8086:2a42"], [finding.key for finding in report.findings])

    def test_a_display_controller_alone_in_its_slot_is_still_checked(self) -> None:
        # Function 0 of 00:1f is not a display device: 00:1f.4 is a card of its own.
        isa = Device("pci", "0000:00:1f.0", "8086", "2a40", "Intel ICH9M LPC Interface Controller", driver="lpc_ich",
                     pci_class="060100")
        display = Device("pci", "0000:00:1f.4", "1234", "5678", "Some Display Controller", pci_class="038000")
        report = analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU, isa, display, INTEL_AUDIO)))
        self.assertEqual(["graphics:no-driver:pci:1234:5678"], [finding.key for finding in report.findings])


class SoundBluetoothCameraTests(unittest.TestCase):
    def test_sound_without_any_driver(self) -> None:
        audio = replace(INTEL_AUDIO, driver="", sound_cards=0)
        finding = analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU, audio))).findings[0]
        self.assertEqual("audio:no-driver:pci:8086:51c8", finding.key)
        self.assertIn("Dummy Output", finding.detail)

    def test_several_in_kernel_sound_drivers_are_not_a_pending_restart(self) -> None:
        # snd_hda_intel is loaded for the HDMI audio; SOF failed; AVS is never loaded on this machine.
        audio = replace(INTEL_AUDIO, driver="", sound_cards=0,
                        modules=("snd_hda_intel", "snd_sof_pci_intel_tgl", "snd_soc_avs"),
                        loaded_modules=("snd_hda_intel", "snd_sof_pci_intel_tgl"))
        finding = analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU, audio))).findings[0]
        self.assertEqual("audio:failed:pci:8086:51c8", finding.key)

    def test_driver_loaded_but_no_sound_card(self) -> None:
        audio = replace(INTEL_AUDIO, sound_cards=0)
        finding = analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU, audio))).findings[0]
        self.assertEqual("audio:failed:pci:8086:51c8", finding.key)

    def test_hdmi_audio_of_a_graphics_card_needs_no_card_of_its_own(self) -> None:
        hdmi = Device("pci", "0000:01:00.1", "10de", "10fa", "NVIDIA HD Audio", driver="snd_hda_intel",
                      pci_class="040300")
        self.assertEqual((), analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU, INTEL_AUDIO, hdmi))).findings)

    def test_bluetooth_firmware_missing(self) -> None:
        realtek = Device("usb", "3-10", "0bda", "b85c", "Realtek Bluetooth Radio",
                         interfaces=(UsbInterface("1.0", "e0", "01", "01", "btusb"),),
                         loaded_modules=())
        report = analyze(laptop(usb=(realtek, WEBCAM), firmware_errors=(
            FirmwareError("bluetooth", "hci0", "rtl_bt/rtl8852bu_fw.bin"),)))

        finding = report.findings[0]
        self.assertEqual("bluetooth:failed:usb:0bda:b85c", finding.key)
        self.assertIn("rtl_bt/rtl8852bu_fw.bin", finding.detail)
        self.assertIn("btusb", finding.detail)

    def test_intel_ipu_camera_without_a_usb_webcam(self) -> None:
        ipu = Device("pci", "0000:00:05.0", "8086", "465d", "Intel Alder Lake Imaging Signal Processor",
                     driver="intel-ipu6", pci_class="048000")
        report = analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU, INTEL_AUDIO, ipu), usb=(BLUETOOTH,)))
        self.assertEqual([("camera:ipu:pci:8086:465d", INFO)], [(f.key, f.level) for f in report.findings])

        with_webcam = analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU, INTEL_AUDIO, ipu)))
        self.assertEqual((), with_webcam.findings)

    def test_an_atom_tablet_is_not_reported_without_sound_bluetooth_and_cameras(self) -> None:
        # GitHub issue #80, a Lenovo Yoga Book (Cherry Trail): sound, Bluetooth and the cameras are not on PCI or
        # USB, and Driver Check said "not found on this computer" and "all drivers present".
        isp = Device("pci", "0000:00:03.0", "8086", "22b8", "Intel Atom ISP", pci_class="048000")
        engine = Device("acpi", "808622A8:00", "", "808622A8", "Intel Cherry Trail SST audio", driver="intel_sst_acpi",
                        modules=("snd_intel_sst_acpi",), loaded_modules=("snd_intel_sst_acpi",))
        serial_bt = Device("acpi", "BCM2E7E:00", "", "BCM2E7E", "Broadcom Bluetooth (UART)", driver="hci_uart_bcm",
                           bluetooth=("hci0",))
        report = analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU, isp), usb=(), acpi=(engine, serial_bt)))

        self.assertEqual([("audio:failed:acpi:808622A8", WARNING), ("camera:atom-isp:pci:8086:22b8", INFO)],
                         [(f.key, f.level) for f in report.findings])
        sound = report.findings[0]
        self.assertIn("Intel SST", sound.detail)
        self.assertEqual(("ACPI 808622A8", ""), (sound.device_id, sound.link))
        self.assertEqual([REPORT], kinds(sound))
        areas = {area.key: (area.level, area.summary) for area in report.areas}
        self.assertEqual((WARNING, "Intel Cherry Trail SST audio"), areas["audio"])
        self.assertEqual((OK, "Broadcom Bluetooth (UART)"), areas["bluetooth"])
        self.assertEqual((INFO, "Intel Atom ISP"), areas["camera"])

    def test_a_sound_engine_with_its_card_works(self) -> None:
        engine = Device("acpi", "80860F28:00", "", "80860F28", "Intel Bay Trail SST audio", driver="intel_sst_acpi",
                        sound_cards=1)
        report = analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU), acpi=(engine,)))
        self.assertEqual((), report.findings)
        self.assertEqual(OK, {area.key: area.level for area in report.areas}["audio"])

    def test_serial_bluetooth_without_its_firmware(self) -> None:
        chip = Device("acpi", "BCM2E7E:00", "", "BCM2E7E", "Broadcom Bluetooth (UART)", driver="hci_uart_bcm",
                      modules=("hci_uart",), loaded_modules=("hci_uart",))
        report = analyze(laptop(usb=(WEBCAM,), acpi=(chip,), firmware_errors=(
            FirmwareError("bluetooth", "hci0", "brcm/BCM4356A2.hcd"),)))
        finding = report.findings[0]
        self.assertEqual("bluetooth:failed:acpi:BCM2E7E", finding.key)
        self.assertIn("brcm/BCM4356A2.hcd", finding.detail)
        self.assertIn("hci_uart_bcm", finding.detail)

    def test_webcam_without_driver(self) -> None:
        broken = replace(WEBCAM, interfaces=(UsbInterface("1.0", "0e", "01", "00"),), video_nodes=0)
        finding = analyze(laptop(usb=(BLUETOOTH, broken))).findings[0]
        self.assertEqual("camera:no-driver:usb:05c8:0b06", finding.key)


class FingerprintAndOtherTests(unittest.TestCase):
    SUPPORT = {"04f3:0c7e": "elanmoc", "27c6:55a4": ""}

    def test_supported_reader_is_a_tip(self) -> None:
        reader = Device("usb", "3-7", "04f3", "0c7e", "ELAN:ARM-M4", vendor_name="ELAN",
                        interfaces=(UsbInterface("1.0", "ff", "00", "00"),))
        report = analyze(laptop(usb=(BLUETOOTH, WEBCAM, reader)), self.SUPPORT)

        finding = report.findings[0]
        self.assertEqual(("fingerprint:supported:usb:04f3:0c7e", TIP), (finding.key, finding.level))
        self.assertEqual("ELAN fingerprint reader", finding.device)
        self.assertEqual((), report.problems)
        self.assertEqual(OK, {area.key: area.level for area in report.areas}["fingerprint"])

    def test_unsupported_and_unknown_readers(self) -> None:
        goodix = Device("usb", "3-7", "27c6", "55a4", "Goodix", vendor_name="Goodix",
                        interfaces=(UsbInterface("1.0", "ff", "00", "00"),))
        unknown = Device("usb", "3-8", "2808", "9338", "FocalTech", vendor_name="FocalTech",
                         interfaces=(UsbInterface("1.0", "ff", "00", "00"),))
        report = analyze(laptop(usb=(goodix, unknown)), self.SUPPORT)
        self.assertEqual(["fingerprint:unsupported:usb:27c6:55a4", "fingerprint:unsupported:usb:2808:9338"],
                         [finding.key for finding in report.findings])
        self.assertTrue(all(finding.level == INFO for finding in report.findings))

    def test_card_reader_without_driver_is_information(self) -> None:
        reader = Device("pci", "0000:03:00.0", "10ec", "5228", "Realtek RTS5228 PCI Express Card Reader",
                        pci_class="ff0000")
        ram = Device("pci", "0000:00:14.2", "8086", "51ef", "Intel Shared SRAM", pci_class="050000")
        report = analyze(laptop(pci=(INTEL_WIFI, INTEL_GPU, INTEL_AUDIO, reader, ram)))
        self.assertEqual([("other:no-driver:pci:10ec:5228", INFO)], [(f.key, f.level) for f in report.findings])

    def test_vendor_specific_usb_devices_need_no_kernel_driver(self) -> None:
        phone = Device("usb", "1-3", "18d1", "4ee7", "Google Pixel", interfaces=(UsbInterface("1.0", "ff", "42", "01"),))
        self.assertEqual((), analyze(laptop(usb=(BLUETOOTH, WEBCAM, phone))).findings)

    def test_findings_are_sorted_by_urgency(self) -> None:
        nvidia = GraphicsTests.NVIDIA
        report = analyze(broadcom_laptop(pci=(BROADCOM, INTEL_GPU, nvidia, INTEL_AUDIO)))
        self.assertEqual([CRITICAL, WARNING], [finding.level for finding in report.findings])

    def test_worst(self) -> None:
        self.assertEqual(WARNING, worst([OK, WARNING, INFO]))
        self.assertEqual(OK, worst([]))

    def test_report_serializes_to_json_types(self) -> None:
        import json

        payload = json.loads(json.dumps(analyze(broadcom_laptop()).to_dict()))
        self.assertEqual("critical", payload["findings"][0]["level"])
        self.assertEqual("driver-manager", payload["findings"][0]["actions"][0]["kind"])


if __name__ == "__main__":
    unittest.main()

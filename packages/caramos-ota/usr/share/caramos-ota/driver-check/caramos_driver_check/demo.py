"""Development only: made-up machines for working on the window without their hardware.

    CARAMOS_DRIVER_CHECK_DEMO=broadcom       Broadcom Wi-Fi without driver, offline, NVIDIA on nouveau
    CARAMOS_DRIVER_CHECK_DEMO=online-later   the same, and the network comes back after 20 seconds
    CARAMOS_DRIVER_CHECK_DEMO=nvidia         online, only the NVIDIA driver is missing
    CARAMOS_DRIVER_CHECK_DEMO=live           the Broadcom laptop in the live USB session
    CARAMOS_DRIVER_CHECK_DEMO=ok             everything works
    CARAMOS_DRIVER_CHECK_DEMO=atom           an Atom tablet (Cherry Trail, like the Lenovo Yoga Book): SST sound
                                             without a driver for its board, Bluetooth on a serial port, cameras
                                             behind the Atom image processor
    CARAMOS_DRIVER_CHECK_DEMO=nvidia-broken  a GeForce 940MX whose NVIDIA 470 install did not finish (its module
                                             does not build for Linux 6.14): dpkg is broken until 580 replaces it
    CARAMOS_DRIVER_CHECK_DEMO=nomodeset      Intel graphics without a driver: the nomodeset boot option
"""

from __future__ import annotations

import time
from time import monotonic

from .analysis import Report, analyze
from .drivers import DriverProposal
from .hardware import Device, NetInterface, RfkillSwitch, Snapshot, UsbInterface

BROADCOM = Device("pci", "0000:02:00.0", "14e4", "43a0", "Broadcom BCM4360 802.11ac Wireless Network Adapter",
                  vendor_name="Broadcom", pci_class="028000", subsystem="106b:0117")
INTEL_WIFI = Device("pci", "0000:00:14.3", "8086", "a0f0", "Intel Wi-Fi 6 AX201 160MHz", vendor_name="Intel",
                    driver="iwlwifi", pci_class="028000", net=("wlp0s20f3",))
ETHERNET = Device("pci", "0000:03:00.0", "10ec", "8168", "Realtek RTL8111/8168/8211/8411 PCI Express Gigabit "
                  "Ethernet Controller", vendor_name="Realtek", driver="r8169", pci_class="020000", net=("enp3s0",))
INTEL_GPU = Device("pci", "0000:00:02.0", "8086", "9b41", "Intel UHD Graphics", vendor_name="Intel", driver="i915",
                   pci_class="030000")
NVIDIA = Device("pci", "0000:01:00.0", "10de", "1f99", "NVIDIA GeForce GTX 1650 Mobile / Max-Q", vendor_name="NVIDIA",
                driver="nouveau", pci_class="030200", modules=("nouveau",), loaded_modules=("nouveau",))
AUDIO = Device("pci", "0000:00:1f.3", "8086", "02c8", "Intel Comet Lake PCH-LP cAVS", vendor_name="Intel",
               driver="sof-audio-pci-intel-cnl", pci_class="040100", sound_cards=1)
BLUETOOTH = Device("usb", "1-10", "8087", "0026", "Intel AX201 Bluetooth", vendor_name="Intel",
                   interfaces=(UsbInterface("1.0", "e0", "01", "01", "btusb"),), bluetooth=("hci0",))
WEBCAM = Device("usb", "1-5", "0bda", "5520", "Integrated Webcam HD", vendor_name="Realtek",
                interfaces=(UsbInterface("1.0", "0e", "01", "00", "uvcvideo"),), video_nodes=2)
FINGERPRINT = Device("usb", "1-9", "27c6", "55a4", "Goodix", vendor_name="Goodix",
                     interfaces=(UsbInterface("1.0", "ff", "00", "00"),))
FINGERPRINTS = {"27c6:55a4": ""}
ATOM_WIFI = Device("pci", "0000:01:00.0", "14e4", "43ec", "Broadcom BCM4356 802.11ac Wireless Network Adapter",
                   vendor_name="Broadcom", driver="brcmfmac", pci_class="028000", net=("wlp1s0",))
ATOM_GPU = Device("pci", "0000:00:02.0", "8086", "22b0", "Intel Atom/Celeron/Pentium Processor x5-E8000/J3xxx/N3xxx "
                  "Integrated Graphics Controller", vendor_name="Intel", driver="i915", pci_class="030000")
ATOM_ISP = Device("pci", "0000:00:03.0", "8086", "22b8", "Intel Atom/Celeron/Pentium Processor x5-E8000/J3xxx/N3xxx "
                  "Series Imaging Unit", vendor_name="Intel", pci_class="048000")
SST = Device("acpi", "808622A8:00", "", "808622A8", "Intel Cherry Trail SST audio", vendor_name="Intel",
             driver="intel_sst_acpi", modules=("snd_intel_sst_acpi",), loaded_modules=("snd_intel_sst_acpi",))
GEFORCE_940MX = Device("pci", "0000:01:00.0", "10de", "179c", "NVIDIA GeForce 940MX", vendor_name="NVIDIA",
                       driver="nouveau", pci_class="030200", modules=("nouveau",), loaded_modules=("nouveau",))
HD520 = Device("pci", "0000:00:02.0", "8086", "1916", "Intel HD Graphics 520", vendor_name="Intel", pci_class="030000",
               modules=("i915",))
SERIAL_BLUETOOTH = Device("acpi", "BCM2E7E:00", "", "BCM2E7E", "Broadcom Bluetooth (UART)", vendor_name="Broadcom",
                          driver="hci_uart_bcm", bluetooth=("hci0",))


class DemoScanner:
    def __init__(self, case: str) -> None:
        self.case = case
        self.demo = case   # the window shows a banner: this is not the computer it runs on
        self.started = monotonic()

    def connected(self) -> bool:
        if self.case == "online-later":
            return monotonic() - self.started > 20
        return self.case not in ("broadcom", "live")

    def snapshot(self) -> Snapshot:
        online = self.connected()
        if self.case == "atom":
            wifi = NetInterface("wlp1s0", wireless=True, up=True, driver="brcmfmac", bus="pci", address="0000:01:00.0")
            return Snapshot(pci=(ATOM_WIFI, ATOM_GPU, ATOM_ISP), acpi=(SST, SERIAL_BLUETOOTH), net=(wifi,),
                            connected=online, kernel="6.14.0-37-generic")
        ethernet = NetInterface("enp3s0", wireless=False, up=online, driver="r8169", bus="pci",
                                address="0000:03:00.0")
        if self.case in ("nvidia-broken", "nomodeset"):
            wifi = NetInterface("wlp0s20f3", wireless=True, up=True, driver="iwlwifi", bus="pci",
                                address="0000:00:14.3")
            broken = self.case == "nvidia-broken"
            return Snapshot(pci=(INTEL_WIFI, ETHERNET, INTEL_GPU if broken else HD520, AUDIO)
                            + ((GEFORCE_940MX,) if broken else ()),
                            usb=(BLUETOOTH, WEBCAM), net=(ethernet, wifi), connected=online, kernel="6.14.0-37-generic",
                            cmdline="BOOT_IMAGE=/boot/vmlinuz-6.14.0-37-generic root=UUID=0b1e ro quiet splash"
                                    + ("" if broken else " nomodeset"),
                            unfinished_packages=("nvidia-dkms-470", "nvidia-driver-470") if broken else ())
        if self.case in ("nvidia", "ok"):
            wifi = NetInterface("wlp0s20f3", wireless=True, up=True, driver="iwlwifi", bus="pci",
                                address="0000:00:14.3")
            pci = (INTEL_WIFI, ETHERNET, INTEL_GPU, AUDIO) + ((NVIDIA,) if self.case == "nvidia" else ())
            net = (ethernet, wifi)
        else:
            pci = (BROADCOM, ETHERNET, INTEL_GPU, NVIDIA, AUDIO)
            net = (ethernet,)
        usb = (BLUETOOTH, WEBCAM) + ((FINGERPRINT,) if self.case != "ok" else ())
        return Snapshot(pci=pci, usb=usb, net=net, rfkill=(RfkillSwitch("bluetooth", False, False),),
                        connected=online, kernel="6.14.0-37-generic", live=self.case == "live")

    def proposals(self, snapshot: Snapshot | None = None) -> list[DriverProposal]:
        time.sleep(1.2)   # UbuntuDrivers loads the APT cache
        if self.case in ("atom", "nomodeset"):
            return []
        if self.case == "nvidia-broken":
            return [DriverProposal("nvidia-driver-580", "nvidia:580", GEFORCE_940MX.address, "NVIDIA", "GM108M [GeForce 940MX]")]
        proposals = [DriverProposal("nvidia-driver-580-open", "nvidia:580-open", NVIDIA.address, "NVIDIA",
                                    "TU117M", free=False)]
        if self.case not in ("nvidia", "ok"):
            proposals.append(DriverProposal("bcmwl-kernel-source", "bcmwl-kernel-source", BROADCOM.address,
                                            "Broadcom", "BCM4360", offline=True))
        return proposals if self.case != "ok" else []

    def analyze(self, snapshot: Snapshot, proposals) -> Report:
        return analyze(snapshot, FINGERPRINTS, proposals)

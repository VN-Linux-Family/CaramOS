"""Driver Check and broken or turned-off graphics drivers.

- Ubuntu recommends NVIDIA 470 for Maxwell and Pascal cards (GeForce 940MX, GTX 1060), but 470 has no modules
  for Linux 6.12 and later and its DKMS build fails: the one-click install left dpkg broken, and every later
  install failed, in the App Center too (ticket H-1094). Only drivers with signed modules are offered now,
  a broken install is shown with a replacement, and the helper installs the kernel those modules are for.
- A graphics driver turned off by nomodeset or a blacklist says so, with the way back (H-1085, H-1108, H-1109).
- system.log carries the boot options and the packages dpkg left unfinished, without firewall notices; how
  the computer starts (UEFI entries, Secure Boot) and its disks, for a grub> prompt (H-1097); and a line the
  journal repeats only once, with a count.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "usr/share/caramos-ota/driver-check"))

from caramos_driver_check import drivers, helper, logs  # noqa: E402
from caramos_driver_check.analysis import CRITICAL, INSTALL, analyze  # noqa: E402
from caramos_driver_check.drivers import DriverProposal  # noqa: E402
from caramos_driver_check.hardware import Device, Snapshot, SystemReader  # noqa: E402

GEFORCE_940MX = Device("pci", "0000:01:00.0", "10de", "179c", "NVIDIA GeForce 940MX", driver="nouveau", pci_class="030200",
                       modules=("nouveau",), loaded_modules=("nouveau",))
HD520 = Device("pci", "0000:00:02.0", "8086", "1916", "Intel HD Graphics 520", pci_class="030000", modules=("i915",))
SYSPATH = "/sys/devices/pci0000:00/0000:00:01.0/0000:01:00.0"
# system_device_drivers() for a GeForce 940MX on Ubuntu 24.04 in November 2026: 470 recommended.
DEVICES = {SYSPATH: {"vendor": "NVIDIA Corporation", "model": "GM108M [GeForce 940MX]", "drivers": {
    "nvidia-driver-470": {"free": False, "from_distro": True, "recommended": True},
    "nvidia-driver-580": {"free": False, "from_distro": True, "recommended": False},
    "nvidia-driver-580-server": {"free": False, "from_distro": True, "recommended": False},
    "xserver-xorg-video-nouveau": {"free": True, "from_distro": True, "recommended": False, "builtin": True},
}}}


class ProposalTests(unittest.TestCase):
    def test_a_driver_without_signed_modules_is_not_offered(self) -> None:
        offered = drivers.proposals_from(DEVICES, lambda name: False, lambda name: name != "nvidia-driver-470")
        self.assertEqual([("nvidia-driver-580", "nvidia:580", "0000:01:00.0")],
                         [(p.package, p.target, p.address) for p in offered])
        # Before: the recommended 470, whose module does not build for Linux 6.14.
        self.assertEqual(["nvidia-driver-470"], [p.package for p in drivers.proposals_from(DEVICES, lambda name: False)])

    def test_no_usable_driver_means_no_one_click_offer(self) -> None:
        self.assertEqual([], drivers.proposals_from(DEVICES, lambda name: False, lambda name: not name.startswith("nvidia")))

    def test_a_broken_install_does_not_count_as_installed(self) -> None:
        # find_proposals() treats a half-configured package as missing; one fully installed driver stops the offer.
        self.assertEqual([], drivers.proposals_from(DEVICES, lambda name: name == "nvidia-driver-580"))

    def test_the_lookup_runs_to_replace_a_broken_nvidia_driver(self) -> None:
        on_nvidia = replace(GEFORCE_940MX, driver="nvidia", loaded_modules=("nvidia",))
        self.assertEqual("", drivers.wanted(Snapshot(pci=(on_nvidia,))))
        self.assertEqual("NVIDIA 10de:179c", drivers.wanted(Snapshot(pci=(on_nvidia,), unfinished_packages=("nvidia-dkms-470",))))


class AnalysisTests(unittest.TestCase):
    def test_a_broken_nvidia_install_offers_the_replacement(self) -> None:
        snapshot = Snapshot(pci=(GEFORCE_940MX,), kernel="6.14.0-37-generic",
                            unfinished_packages=("libc-bin", "nvidia-dkms-470", "nvidia-driver-470"))
        proposal = DriverProposal("nvidia-driver-580", "nvidia:580", "0000:01:00.0", "NVIDIA", "GM108M")
        finding = next(f for f in analyze(snapshot, {}, [proposal]).findings if f.area == "graphics")
        self.assertEqual((CRITICAL, "graphics:nvidia-broken:pci:10de:179c"), (finding.level, finding.key))
        self.assertIn("nvidia-dkms-470, nvidia-driver-470", finding.detail)
        self.assertNotIn("libc-bin", finding.detail)
        self.assertIn("6.14", finding.detail)
        self.assertEqual((INSTALL, "nvidia:580"), (finding.actions[0].kind, finding.actions[0].target))

    def test_a_broken_install_without_a_replacement_points_to_driver_manager(self) -> None:
        snapshot = Snapshot(pci=(GEFORCE_940MX,), kernel="7.0.0-38-generic", unfinished_packages=("nvidia-dkms-470",))
        finding = next(f for f in analyze(snapshot, {}, []).findings if f.area == "graphics")
        self.assertEqual("graphics:nvidia-broken:pci:10de:179c", finding.key)
        self.assertNotIn(INSTALL, [action.kind for action in finding.actions])

    def test_nomodeset_is_named_with_the_way_back(self) -> None:
        snapshot = Snapshot(pci=(HD520,), cmdline="BOOT_IMAGE=/boot/vmlinuz root=UUID=1 ro quiet splash nomodeset")
        finding = next(f for f in analyze(snapshot, {}, []).findings if f.area == "graphics")
        self.assertEqual("graphics:blocked:pci:8086:1916", finding.key)
        self.assertIn("nomodeset", finding.detail)
        self.assertIn("sudo sed -i 's/ *nomodeset//' /etc/default/grub && sudo update-grub", finding.detail)
        snapshot = replace(snapshot, cmdline="ro quiet i915.modeset=0")
        detail = next(f for f in analyze(snapshot, {}, []).findings if f.area == "graphics").detail
        self.assertIn("i915.modeset=0", detail)

    def test_a_blacklist_line_is_named_with_its_file(self) -> None:
        snapshot = Snapshot(pci=(HD520,), blacklists=(("i915", "/etc/modprobe.d/no-intel.conf"),))
        detail = next(f for f in analyze(snapshot, {}, []).findings if f.area == "graphics").detail
        self.assertIn("“blacklist i915” line in /etc/modprobe.d/no-intel.conf", detail)
        snapshot = Snapshot(pci=(HD520,), blacklists=(("i915", "the kernel command line"),))
        detail = next(f for f in analyze(snapshot, {}, []).findings if f.area == "graphics").detail
        self.assertIn("modprobe.blacklist", detail)

    def test_without_a_known_cause_the_old_explanation_stays(self) -> None:
        detail = next(f for f in analyze(Snapshot(pci=(HD520,)), {}, []).findings if f.area == "graphics").detail
        self.assertIn("it may be turned off (blacklisted) or it refused to start", detail)


class ReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def write(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_blacklists_from_modprobe_d_and_the_command_line(self) -> None:
        self.write("etc/modprobe.d/no-intel.conf", "# no Intel graphics\nblacklist i915\noptions snd-hda-intel model=auto\n")
        self.write("etc/modprobe.d/off.conf", "install snd-hda-intel /bin/false\n")
        self.write("usr/lib/modprobe.d/blacklist-framebuffer.conf", "blacklist vesafb\n")
        self.write("etc/modprobe.d/notes.txt", "blacklist r8169\n")
        found = dict(SystemReader(self.root).module_blacklists("ro quiet modprobe.blacklist=nouveau,xe"))
        self.assertEqual("/etc/modprobe.d/no-intel.conf", found["i915"])
        self.assertEqual("/etc/modprobe.d/off.conf", found["snd_hda_intel"])
        self.assertEqual("/usr/lib/modprobe.d/blacklist-framebuffer.conf", found["vesafb"])
        self.assertEqual("the kernel command line", found["nouveau"])
        self.assertNotIn("r8169", found)

    def test_unfinished_packages_from_the_dpkg_status(self) -> None:
        self.write("var/lib/dpkg/status", "Package: libc-bin\nStatus: install ok installed\n\n"
                                          "Package: nvidia-dkms-470\nStatus: install ok half-configured\n\n"
                                          "Package: nvidia-driver-470\nStatus: install ok unpacked\n\n"
                                          "Package: old-thing\nStatus: deinstall ok config-files\n")
        self.assertEqual(("nvidia-dkms-470", "nvidia-driver-470"), SystemReader(self.root).unfinished_packages())
        self.assertEqual(["nvidia-dkms-470", "nvidia-driver-470"], logs.unfinished_packages(self.root))


class HelperTests(unittest.TestCase):
    class Cache(dict):
        pass

    def test_the_kernel_of_the_nvidia_modules_comes_too(self) -> None:
        present = mock.Mock(has_versions=True)
        cache = {"linux-generic-hwe-24.04": present, "linux-generic": present}
        self.assertEqual(["linux-generic-hwe-24.04"], helper.kernel_for_modules(
            ["nvidia-driver-580", "linux-modules-nvidia-580-generic-hwe-24.04"], cache))
        self.assertEqual(["linux-generic-hwe-24.04"], helper.kernel_for_modules(
            ["nvidia-driver-595-open", "linux-modules-nvidia-595-open-generic-hwe-24.04"], cache))
        # DKMS, or the modules of one kernel release: no kernel metapackage to add.
        self.assertEqual([], helper.kernel_for_modules(["nvidia-driver-580", "nvidia-dkms-580"], cache))
        self.assertEqual([], helper.kernel_for_modules(["linux-modules-nvidia-580-6.14.0-37-generic"], cache))
        self.assertEqual([], helper.kernel_for_modules(["linux-modules-nvidia-580-lowlatency-hwe-24.04"], cache))


class SystemLogTests(unittest.TestCase):
    def test_firewall_notices_give_way_to_the_rest(self) -> None:
        output = "\n".join(
            [f"2026-11-04T12:{n:02d}:00+07:00 host kernel: [UFW BLOCK] IN=wlp2s0 SRC=192.168.1.{n}" for n in range(50)]
            + ["2026-11-04T12:59:00+07:00 host kernel: i915 0000:00:02.0: probe failed"])
        with mock.patch.object(logs.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output, "")) as run:
            kept = logs._journal(["-b", "0"], 5)
        self.assertEqual("2026-11-04T12:59:00+07:00 host kernel: i915 0000:00:02.0: probe failed", kept)
        self.assertIn(str(5 * logs.JOURNAL_SCAN), run.call_args.args[0])

    def test_the_head_has_the_boot_options_and_the_unfinished_packages(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for relative, text in (("proc/cmdline", "BOOT_IMAGE=/boot/vmlinuz root=UUID=1 ro quiet splash nomodeset\n"),
                                   ("proc/cpuinfo", "model name\t: Intel(R) Core(TM) i5-6200U\n"),
                                   ("var/lib/dpkg/status", "Package: nvidia-dkms-470\nStatus: install ok half-configured\n")):
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_text(text, encoding="utf-8")
            with mock.patch.object(logs, "_journal", return_value=""), mock.patch.object(logs, "_command", return_value=""):
                head = logs.system_log(root).splitlines()[:5]
        self.assertEqual("Boot options: BOOT_IMAGE=/boot/vmlinuz root=UUID=1 ro quiet splash nomodeset", head[2])
        self.assertEqual("Not fully installed (dpkg): nvidia-dkms-470", head[3])
        self.assertEqual("Boot: BIOS (legacy)", head[4])

    def test_a_line_the_journal_repeats_comes_once_with_a_count(self) -> None:
        burst = ["host kernel: r8169 0000:01:00.0: PCIe Bus Error: severity=Correctable, type=Physical Layer",
                 "host kernel: r8169 0000:01:00.0:    [ 0] RxErr                  (First)"]
        lines = [f"2026-10-30T15:{minute:02d}:03+07:00 {line}" for minute in range(40) for line in burst]
        lines.insert(10, "2026-10-30T15:05:00+07:00 host kernel: nvme nvme0: I/O 12 QID 3 timeout, aborting")
        self.assertEqual([
            "2026-10-30T15:05:00+07:00 host kernel: nvme nvme0: I/O 12 QID 3 timeout, aborting",
            f"2026-10-30T15:39:03+07:00 {burst[0]} [40 times]",
            f"2026-10-30T15:39:03+07:00 {burst[1]} [40 times]",
        ], logs.collapse_repeats(lines))


# efibootmgr 18 on a laptop that had Ubuntu before CaramOS (the serial numbers are made up).
EFIBOOTMGR = """BootCurrent: 0002
Timeout: 0 seconds
BootOrder: 0002,0001,0003,0004
Boot0001* ubuntu\tHD(1,GPT,0b9d3ac4-1111-4c2e-9a39-5d1f0a7e2c11,0x800,0x100000)/File(\\EFI\\ubuntu\\shimx64.efi)
Boot0002* CaramOS\tHD(1,GPT,6f1c2b3a-2222-4c1e-8b1d-2a3b4c5d6e7f,0x800,0x100000)/File(\\EFI\\caramos\\shimx64.efi)
Boot0003* UEFI: KBG40ZNS256G KIOXIA-12AB34CD5678, Partition 1\tHD(1,GPT,6f1c2b3a-2222-4c1e-8b1d-2a3b4c5d6e7f,0x800,0x100000)/File(\\EFI\\BOOT\\BOOTX64.EFI)..BO
Boot0004  IPV4 Network - Realtek PCIe FE Family Controller\tPciRoot(0x0)/Pci(0x1c,0x5)/Pci(0x0,0x0)/MAC(8c47be112233,0)/IPv4(0.0.0.00.0.0.0,0,0)..BO
Boot0005* KBG40ZNS256G KIOXIA-12AB34CD5678\tPciRoot(0x0)/Pci(0x1d,0x0)/Pci(0x0,0x0)/NVMe(0x1,8C-E3-8E-04-03-A0-42-CB)..BO
"""
LSBLK = {"blockdevices": [
    {"name": "loop0", "type": "loop", "size": 4096, "tran": None, "fstype": "squashfs", "mountpoints": ["/snap/bare/5"],
     "model": None, "partuuid": None},
    {"name": "nvme0n1", "type": "disk", "size": 256060514304, "tran": "nvme", "fstype": None, "mountpoints": [None],
     "model": "KBG40ZNS256G NVMe KIOXIA 256GB      ", "partuuid": None, "children": [
         {"name": "nvme0n1p1", "type": "part", "size": 536870912, "tran": "nvme", "fstype": "vfat",
          "mountpoints": ["/boot/efi"], "model": None, "partuuid": "6F1C2B3A-2222-4c1e-8b1d-2a3b4c5d6e7f"},
         {"name": "nvme0n1p2", "type": "part", "size": 255522586624, "tran": "nvme", "fstype": "ext4",
          "mountpoints": ["/"], "model": None, "partuuid": "8a7b6c5d-3333-4f2e-9d1c-0b1a2c3d4e5f"}]},
    {"name": "sda", "type": "disk", "size": 31914983424, "tran": "usb", "fstype": None, "mountpoints": [None],
     "model": "Cruzer Blade", "partuuid": None, "children": [
         {"name": "sda1", "type": "part", "size": 31913934848, "tran": "usb", "fstype": "exfat",
          "mountpoints": ["/media/minh/Ảnh của Minh"], "model": None, "partuuid": "11112222-01"}]},
    {"name": "zram0", "type": "disk", "size": 4110417920, "tran": None, "fstype": "swap", "mountpoints": ["[SWAP]"],
     "model": None, "partuuid": None},
]}


class BootAndDisksTests(unittest.TestCase):
    def fake_command(self, arguments):
        return {"efibootmgr": EFIBOOTMGR, "lsblk": json.dumps(LSBLK)}[arguments[0]]

    def uefi_root(self, folder: str, secure_boot: int) -> Path:
        root = Path(folder)
        variable = root / logs.SECURE_BOOT
        variable.parent.mkdir(parents=True)
        variable.write_bytes(bytes([6, 0, 0, 0, secure_boot]))
        return root

    def test_the_disks_with_their_partitions(self) -> None:
        with mock.patch.object(logs, "_command", side_effect=self.fake_command):
            lines, partitions = logs.disks()
        self.assertEqual([
            "Disk nvme0n1: 238.5 GiB, nvme, KBG40ZNS256G NVMe KIOXIA 256GB · nvme0n1p1 vfat 512 MiB /boot/efi"
            " · nvme0n1p2 ext4 238.0 GiB /",
            "Disk sda: 29.7 GiB, usb, Cruzer Blade · sda1 exfat 29.7 GiB mounted",
        ], lines)
        self.assertEqual("nvme0n1p1", partitions["6f1c2b3a-2222-4c1e-8b1d-2a3b4c5d6e7f"])

    def test_the_boot_entries_name_their_partition_and_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(logs, "_command", side_effect=self.fake_command):
            _lines, partitions = logs.disks()
            lines = logs.boot_lines(self.uefi_root(folder, 1), partitions)
        self.assertEqual([
            "Boot: UEFI · Secure Boot on · started from entry 0002 · order 0002, 0001, 0003, 0004"
            " · the firmware's own entries: 1 disk, 1 network",
            "EFI entry 0001 ubuntu: a partition this computer does not have \\EFI\\ubuntu\\shimx64.efi",
            "EFI entry 0002 CaramOS: nvme0n1p1 \\EFI\\caramos\\shimx64.efi",
            "EFI entry 0003 UEFI: … …, Partition 1: nvme0n1p1 \\EFI\\BOOT\\BOOTX64.EFI",
        ], lines)
        # No serial number, MAC address or partition GUID goes into the log.
        text = "\n".join(lines)
        for private in ("12AB34CD5678", "8c47be112233", "8C-E3-8E", "6f1c2b3a"):
            self.assertNotIn(private, text)

    def test_secure_boot_off_and_a_bios_computer(self) -> None:
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(logs, "_command", return_value=""):
            self.assertEqual(["Boot: UEFI · Secure Boot off"], logs.boot_lines(self.uefi_root(folder, 0), {}))
            self.assertEqual(["Boot: BIOS (legacy)"], logs.boot_lines(Path(folder) / "bios", {}))

    def test_without_lsblk_or_with_odd_output_nothing_breaks(self) -> None:
        for output in ("", "not json", "[]", json.dumps({"blockdevices": [{"name": "sdb", "type": "disk", "size": "4K"}]})):
            with mock.patch.object(logs, "_command", return_value=output):
                lines, _partitions = logs.disks()
            self.assertEqual(["Disk sdb: ?"] if "sdb" in output else [], lines)


if __name__ == "__main__":
    unittest.main()

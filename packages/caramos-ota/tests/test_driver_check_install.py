"""One-click driver installs: which driver is proposed, and what the privileged helper agrees to do."""

from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

# Driver Check lives in /usr/share/caramos-ota/driver-check, outside dist-packages.
sys.path.insert(0, str(Path(__file__).parents[1] / "usr/share/caramos-ota/driver-check"))

from caramos_driver_check import drivers, helper  # noqa: E402
from caramos_driver_check.events import emit, parse_event  # noqa: E402
from caramos_driver_check.install import space_text  # noqa: E402

MIB = helper.MIB
GIB = 1024 * MIB

NVIDIA_SYSPATH = "/sys/devices/pci0000:00/0000:00:01.0/0000:01:00.0"
BROADCOM_SYSPATH = "/sys/devices/pci0000:00/0000:00:1c.0/0000:02:00.0"


class ChooseTests(unittest.TestCase):
    def test_the_recommended_desktop_nvidia_driver(self) -> None:
        options = {
            "nvidia-driver-570": {}, "nvidia-driver-580-open": {"recommended": True},
            "nvidia-driver-580-server": {}, "xserver-xorg-video-nouveau": {"builtin": True},
        }
        self.assertEqual("nvidia-driver-580-open", drivers.choose(options))

    def test_a_recommended_server_driver_is_replaced_by_the_newest_desktop_one(self) -> None:
        options = {"nvidia-driver-570": {}, "nvidia-driver-580": {}, "nvidia-driver-580-server": {"recommended": True}}
        self.assertEqual("nvidia-driver-580", drivers.choose(options))

    def test_ubuntus_broadcom_package_first(self) -> None:
        self.assertEqual("bcmwl-kernel-source", drivers.choose({"broadcom-sta-dkms": {}, "bcmwl-kernel-source": {}}))

    def test_drivers_ubuntu_does_not_install_by_itself_are_left_to_driver_manager(self) -> None:
        self.assertEqual("", drivers.choose({"oem-somerville-tentacool-meta": {}}))
        self.assertEqual("", drivers.choose({"intel-ipu6-dkms": {}}))

    def test_install_targets(self) -> None:
        self.assertEqual("nvidia:580-open", drivers.install_target("nvidia-driver-580-open"))
        self.assertEqual("nvidia:580", drivers.install_target("nvidia-driver-580"))
        self.assertEqual("bcmwl-kernel-source", drivers.install_target("bcmwl-kernel-source"))

    def test_proposals_from_ubuntu_drivers_output(self) -> None:
        devices = {
            NVIDIA_SYSPATH: {"modalias": "pci:v000010DEd00001F99", "vendor": "NVIDIA", "model": "TU117M",
                             "drivers": {"nvidia-driver-580-open": {"recommended": True, "free": False}}},
            BROADCOM_SYSPATH: {"vendor": "Broadcom", "drivers": {"bcmwl-kernel-source": {"free": False}}},
            "/sys/devices/pci0000:00/0000:00:1f.0": {"drivers": {"nvidia-driver-470": {}}, "manual_install": True},
            "/sys/devices/pci0000:00/0000:00:1e.0": {"drivers": {"virtualbox-guest-utils": {}}},
        }
        proposals = drivers.proposals_from(devices, installed=lambda name: name == "virtualbox-guest-utils")
        self.assertEqual(
            [("nvidia-driver-580-open", "nvidia:580-open", "0000:01:00.0", False),
             ("bcmwl-kernel-source", "bcmwl-kernel-source", "0000:02:00.0", True)],
            [(p.package, p.target, p.address, p.offline) for p in proposals],
        )
        nvidia = proposals[0]
        self.assertEqual("580", nvidia.version)
        self.assertTrue(nvidia.open_kernel_modules)

    def test_without_ubuntu_drivers_there_is_nothing_to_propose(self) -> None:
        with mock.patch.dict(sys.modules, {"apt_pkg": None}):
            self.assertEqual([], drivers.find_proposals())


class EventTests(unittest.TestCase):
    def test_space_events_reach_the_window(self) -> None:
        event = parse_event('{"event": "space", "path": "/boot", "need": 300, "free": 100}')
        self.assertEqual({"event": "space", "path": "/boot", "need": 300, "free": 100}, event)

    def test_round_trip_and_garbage(self) -> None:
        out = io.StringIO()
        with redirect_stdout(out):
            emit("progress", percent=140)
            emit("done", ok=True, restart=True, packages=["bcmwl-kernel-source"], error="")
        lines = out.getvalue().splitlines()
        self.assertEqual({"event": "progress", "percent": 100}, parse_event(lines[0]))
        self.assertTrue(parse_event(lines[1])["restart"])
        self.assertIsNone(parse_event("Error executing command as another user: Not authorized"))
        self.assertIsNone(parse_event('{"event": "rm -rf"}'))
        self.assertIsNone(parse_event('{"event": "progress", "percent": "x"}'))


class FakeDetect:
    """The parts of UbuntuDrivers.detect the helper uses."""

    def __init__(self, packages: dict[str, dict], desktop: dict[tuple[str, bool], list[str]] | None = None) -> None:
        self.packages = packages
        self.desktop = desktop or {}
        self.hooks: list[str] = []

    def system_driver_packages(self, cache, include_oem=True):
        assert include_oem is False
        return self.packages

    def get_desktop_package_list(self, cache, include_oem=True, driver_string="", include_dkms=False):
        return self.desktop.get((driver_string, include_dkms), [])

    def nvidia_desktop_pre_installation_hook(self, packages):
        self.hooks.append("pre")

    def nvidia_desktop_post_installation_hook(self):
        self.hooks.append("post")


class FakeCache(dict):
    """apt_pkg.Cache: cache[name].current_ver is set for installed packages."""

    def __init__(self, installed=()):
        super().__init__({name: mock.Mock(current_ver=object()) for name in installed})

    def __missing__(self, name):
        return mock.Mock(current_ver=None)


class HelperArgumentTests(unittest.TestCase):
    def test_accepted_targets(self) -> None:
        self.assertEqual(("install", ["nvidia:580-open", "bcmwl-kernel-source"]),
                         helper.parse_args(["install", "nvidia:580-open", "bcmwl-kernel-source"]))
        # Canon's printer driver: the printers plugged in, and network printers.
        self.assertEqual(("install", ["canon-capt", "canon-capt-net:LBP6300@192.168.1.50"]),
                         helper.parse_args(["install", "canon-capt", "canon-capt-net:LBP6300@192.168.1.50"]))
        self.assertEqual(("setup", ["canon-capt"]), helper.parse_args(["setup", "canon-capt"]))
        self.assertEqual(("remove", ["canon-capt"]), helper.parse_args(["remove", "canon-capt"]))

    def test_refused_arguments(self) -> None:
        for argv in (
            [], ["install"], ["remove", "bcmwl-kernel-source"], ["install", "bcmwl; rm -rf /"],
            ["install", "-o", "APT::Get::Assume-Yes"], ["install", "nvidia:../../x"], ["install", "a", "a"],
            ["install", "a1", "a2", "a3", "a4", "a5"], ["install", "Bcmwl"],
            ["setup"], ["setup", "canon-capt", "canon-capt"], ["remove", "nvidia:580"], ["purge", "canon-capt"],
            ["install", "canon-capt", "bcmwl-kernel-source"],   # Canon's driver installs on its own
            ["install", "canon-capt-net:LBP9999@192.168.1.50"], ["install", "canon-capt-net:LBP6300@127.0.0.1"],
            ["install", "canon-capt-net:LBP6300@192.168.1.256"], ["install", "canon-capt-net:LBP6300@192.168.1.5;id"],
            ["install", "canon-capt-net:LBP6300@192.168.001.050"], ["install", "canon-capt-net:../x@192.168.1.5"],
        ):
            with self.subTest(argv=argv), self.assertRaises(helper.UsageError):
                helper.parse_args(argv)

    def test_apt_progress(self) -> None:
        self.assertEqual(0.25, helper.apt_progress("dlstatus:1:50.0:Retrieving file 1 of 2"))
        self.assertEqual(0.75, helper.apt_progress("pmstatus:bcmwl-kernel-source:50.0:Installing"))
        self.assertIsNone(helper.apt_progress("Setting up dkms (3.0.11)"))

    def test_dpkg_keeps_its_pty_while_status_lines_share_stdout(self) -> None:
        # Both together closed dpkg's stdout, so maintainer scripts failed at their first echo (H-1110).
        self.assertIn("APT::Status-Fd=1", helper.APT)
        self.assertFalse(any(option.lower().startswith("dpkg::use-pty") for option in helper.APT))

    def test_stream_cleans_pty_line_ends_and_redrawn_lines(self) -> None:
        lines: list[str] = []
        code = helper._stream(["sh", "-c", r"printf 'Unpacking x ...\r\n(Reading 5%%\r(Reading 100%%)\r\nend\n'"],
                              lines.append)
        self.assertEqual((0, ["Unpacking x ...", "(Reading 100%)", "end"]), (code, lines))

    def test_objtool_warnings_are_counted_not_shown(self) -> None:
        output = ["pmstatus:linux-modules-nvidia-580-7.0.0-42-generic:60.0:Configuring",
                  "nvidia.o: warning: objtool: _nv000123rm+0x1a: 'naked' return found",
                  "nvidia-modeset.o: warning: objtool: _nv002345kms+0x9: 'naked' return found",
                  "Setting up linux-modules-nvidia-580-7.0.0-42-generic (7.0.0-42.42~24.04.1) ...", ""]

        def fake_stream(args, on_line):
            for line in output:
                on_line(line)
            return 0

        out = io.StringIO()
        with mock.patch.object(helper, "_stream", side_effect=fake_stream), redirect_stdout(out):
            self.assertEqual(0, helper.run_apt(["install"], 25, 95))
        events = [json.loads(line) for line in out.getvalue().splitlines()]
        # pmstatus 60% is 0.8 of the whole APT run (downloads come first), so 25 + 0.8 * 70.
        self.assertEqual([{"event": "progress", "percent": 81},
                          {"event": "log", "line": "Setting up linux-modules-nvidia-580-7.0.0-42-generic "
                                                   "(7.0.0-42.42~24.04.1) ..."},
                          {"event": "log", "line": "(2 objtool warnings from linking the NVIDIA kernel modules "
                                                   "are not shown)"}], events)


class HelperPlanTests(unittest.TestCase):
    def test_nvidia_goes_through_the_desktop_package_list(self) -> None:
        detect = FakeDetect({"nvidia-driver-580-open": {}},
                            {("nvidia:580-open", False): ["nvidia-driver-580-open", "linux-modules-nvidia-580-open-generic-hwe-24.04"]})
        # With the kernel of those modules, so that APT brings its headers too (see kernel_for_modules()).
        self.assertEqual(["nvidia-driver-580-open", "linux-modules-nvidia-580-open-generic-hwe-24.04",
                          "linux-generic-hwe-24.04"], helper.plan(["nvidia:580-open"], FakeCache(), detect))

    def test_nvidia_falls_back_to_dkms_without_signed_modules(self) -> None:
        detect = FakeDetect({"nvidia-driver-580": {}},
                            {("nvidia:580", True): ["nvidia-driver-580", "nvidia-dkms-580"]})
        self.assertEqual(["nvidia-driver-580", "nvidia-dkms-580"], helper.plan(["nvidia:580"], FakeCache(), detect))

    def test_targets_that_are_not_drivers_for_this_computer_are_refused(self) -> None:
        detect = FakeDetect({"bcmwl-kernel-source": {}, "intel-ipu6-dkms": {}})
        for target in ("nvidia:580", "firefox", "intel-ipu6-dkms"):
            with self.subTest(target=target), self.assertRaises(helper.Refused):
                helper.plan([target], FakeCache(), detect)

    def test_installed_packages_are_skipped(self) -> None:
        detect = FakeDetect({"bcmwl-kernel-source": {}})
        self.assertEqual([], helper.plan(["bcmwl-kernel-source"], FakeCache(installed=["bcmwl-kernel-source"]), detect))
        self.assertEqual(["bcmwl-kernel-source"], helper.plan(["bcmwl-kernel-source"], FakeCache(), detect))


class FakeDisks:
    """os.stat and os.statvfs for a few mounted file systems: {mount point: (device, free bytes)}."""

    def __init__(self, mounts: dict[str, tuple[int, int]]) -> None:
        self.mounts = mounts

    def _mount(self, path: str) -> str:
        return max((mount for mount in self.mounts if path == mount or path.startswith(mount.rstrip("/") + "/")),
                   key=len)

    def stat(self, path: str):
        if path.startswith("/missing"):
            raise FileNotFoundError(path)
        return mock.Mock(st_dev=self.mounts[self._mount(path)][0])

    def statvfs(self, path: str):
        return mock.Mock(f_bavail=self.mounts[self._mount(path)][1] // 4096, f_frsize=4096)


class HelperSpaceTests(unittest.TestCase):
    ARCHIVES = "/var/cache/apt/archives"
    # The NVIDIA 580 install on a CaramOS 1.3.4 that was not updated: kernel 7.0 comes with it (H-1110).
    NVIDIA = helper.Needs(download=985 * MIB, installed=2537 * MIB, kernels=("7.0.0-42-generic",))

    def check(self, disks: FakeDisks, need: helper.Needs, initramfs: int = 85 * MIB):
        return helper.shortages(need, self.ARCHIVES, initramfs, stat=disks.stat, statvfs=disks.statvfs)

    def test_enough_room(self) -> None:
        self.assertEqual([], self.check(FakeDisks({"/": (1, 28 * GIB)}), self.NVIDIA))

    def test_needs_add_up_on_one_file_system(self) -> None:
        # Download, unpacked files, margin, and in /boot one new kernel plus the rebuilt running initramfs.
        boot = (85 + 64) * MIB + 85 * MIB + helper.BOOT_MARGIN
        need = 985 * MIB + 2537 * MIB + helper.ROOT_MARGIN + boot
        self.assertEqual([helper.Shortage("/", need, 3 * GIB)], self.check(FakeDisks({"/": (1, 3 * GIB)}), self.NVIDIA))
        self.assertEqual([], self.check(FakeDisks({"/": (1, need)}), self.NVIDIA))

    def test_a_separate_boot_partition_is_checked_on_its_own(self) -> None:
        disks = FakeDisks({"/": (1, 28 * GIB), "/boot": (2, 200 * MIB)})
        boot = (85 + 64) * MIB + 85 * MIB + helper.BOOT_MARGIN
        self.assertEqual([helper.Shortage("/boot", boot, 200 * MIB)], self.check(disks, self.NVIDIA))
        # Without a new kernel, only the running kernel's initramfs is rebuilt there.
        self.assertEqual([], self.check(disks, helper.Needs(500 * MIB, 1200 * MIB)))

    def test_the_archive_cache_on_its_own_file_system(self) -> None:
        disks = FakeDisks({"/": (1, 28 * GIB), "/var": (3, 500 * MIB)})
        self.assertEqual([helper.Shortage("/var", 985 * MIB, 500 * MIB)], self.check(disks, self.NVIDIA))

    def test_removals_do_not_make_room(self) -> None:
        need = helper.Needs(download=0, installed=-800 * MIB)
        self.assertEqual([helper.Shortage("/", helper.ROOT_MARGIN + 85 * MIB + helper.BOOT_MARGIN, 100 * MIB)],
                         self.check(FakeDisks({"/": (1, 100 * MIB)}), need))

    def test_paths_that_do_not_exist_are_skipped(self) -> None:
        disks = FakeDisks({"/": (1, 28 * GIB)})
        found = helper.shortages(self.NVIDIA, "/missing/archives", 85 * MIB, stat=disks.stat, statvfs=disks.statvfs)
        self.assertEqual([], found)

    def test_mount_point(self) -> None:
        disks = FakeDisks({"/": (1, 0), "/boot": (2, 0), "/boot/efi": (3, 0)})
        self.assertEqual("/", helper.mount_point("/var/cache/apt/archives", disks.stat))
        self.assertEqual("/boot", helper.mount_point("/boot/grub", disks.stat))
        self.assertEqual("/boot/efi", helper.mount_point("/boot/efi/EFI", disks.stat))
        self.assertEqual("/", helper.mount_point("/", disks.stat))

    def test_check_space_lets_the_install_go_on_when_it_cannot_tell(self) -> None:
        fake_apt_pkg = mock.Mock()
        fake_apt_pkg.config.find_dir.return_value = self.ARCHIVES
        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"apt_pkg": fake_apt_pkg}), \
                mock.patch.object(helper, "needs", side_effect=SystemError("E:Unable to correct problems")), \
                redirect_stdout(out):
            self.assertEqual([], helper.check_space(FakeCache(), ["nvidia-driver-580"]))
        self.assertIn("Could not check the free space", out.getvalue())

    def test_check_space_reports_what_it_measured(self) -> None:
        fake_apt_pkg = mock.Mock()
        fake_apt_pkg.config.find_dir.return_value = self.ARCHIVES
        lacking = [helper.Shortage("/", 4 * GIB, GIB)]
        out = io.StringIO()
        with mock.patch.dict(sys.modules, {"apt_pkg": fake_apt_pkg}), \
                mock.patch.object(helper, "needs", return_value=self.NVIDIA), \
                mock.patch.object(helper, "shortages", return_value=lacking) as shortages, \
                redirect_stdout(out):
            self.assertEqual(lacking, helper.check_space(FakeCache(), ["nvidia-driver-580"]))
        self.assertEqual((self.NVIDIA, self.ARCHIVES), shortages.call_args.args[:2])
        self.assertIn("Space needed: 985 MiB to download, 2537 MiB once installed, new kernels: 7.0.0-42-generic",
                      out.getvalue())


class SpaceTextTests(unittest.TestCase):
    def size(self, value: int) -> str:
        return f"{value / 10**9:.1f} GB"

    def test_the_system_disk(self) -> None:
        text = space_text([{"event": "space", "path": "/", "need": 4_100_000_000, "free": 1_200_000_000}], self.size)
        self.assertIn("about 4.1 GB of free space on the system disk, which has only 1.2 GB free", text)
        self.assertIn("Trash", text)

    def test_boot_and_other_file_systems(self) -> None:
        text = space_text([{"path": "/boot", "need": 300_000_000, "free": 100_000_000},
                           {"path": "/var", "need": 1_000_000_000, "free": 0}], self.size)
        self.assertIn("in /boot, which has only 0.1 GB free", text)
        self.assertIn("apt autoremove", text)
        self.assertIn("on /var, which has only 0.0 GB free", text)

    def test_odd_fields_do_not_break_it(self) -> None:
        self.assertIn("system disk", space_text([{"path": None, "need": None, "free": -5}], self.size))


class HelperInstallTests(unittest.TestCase):
    def run_install(self, targets, *, online, detect, apt_codes=(0, 0), media_found=True, add_media=True,
                    lacking=()):
        calls: list[list[str]] = []
        codes = list(apt_codes)

        def fake_apt(args, start, end):
            calls.append(["apt-get", *args])
            return codes.pop(0)

        def fake_stream(args, on_line):
            calls.append(list(args))
            return 0

        out = io.StringIO()
        with mock.patch.object(helper, "online", return_value=online), \
                mock.patch.object(helper, "run_apt", side_effect=fake_apt), \
                mock.patch.object(helper, "_stream", side_effect=fake_stream), \
                mock.patch.object(helper, "_detect", return_value=(None, detect, FakeCache())), \
                mock.patch.object(helper, "check_space", return_value=list(lacking)), \
                mock.patch.object(helper.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}" if add_media else None), \
                mock.patch.object(helper, "MEDIA_INFO", mock.Mock(exists=lambda: media_found)), \
                mock.patch.object(helper, "reload_broadcom", return_value=True), \
                mock.patch.object(helper.subprocess, "run") as run, \
                redirect_stdout(out):
            result = helper.install(targets)
        events = [json.loads(line) for line in out.getvalue().splitlines()]
        return result, calls, events, run

    def test_online_nvidia_install(self) -> None:
        detect = FakeDetect({"nvidia-driver-580-open": {}}, {("nvidia:580-open", False): ["nvidia-driver-580-open"]})
        (ok, restart, packages, error), calls, events, _run = self.run_install(["nvidia:580-open"], online=True,
                                                                              detect=detect)
        self.assertEqual((True, True, ["nvidia-driver-580-open"], ""), (ok, restart, packages, error))
        self.assertEqual(["apt-get", "update"], calls[0])
        self.assertEqual(["apt-get", "install", "-y", "-o", "DPkg::options::=--force-confnew", "--",
                          "nvidia-driver-580-open"], calls[1])
        self.assertEqual(["pre", "post"], detect.hooks)
        self.assertIn({"event": "stage", "stage": "install"}, events)

    def test_offline_broadcom_installs_from_the_usb_stick(self) -> None:
        detect = FakeDetect({"bcmwl-kernel-source": {}})
        (ok, restart, packages, error), calls, _events, run = self.run_install(
            ["bcmwl-kernel-source"], online=False, detect=detect, apt_codes=(0,))
        self.assertEqual((True, False, ["bcmwl-kernel-source"], ""), (ok, restart, packages, error))
        self.assertEqual(["mintdrivers-add-live-media"], calls[0])
        self.assertEqual("install", calls[1][1])
        self.assertEqual(["mintdrivers-remove-live-media"], run.call_args.args[0])

    def test_offline_without_the_usb_stick(self) -> None:
        detect = FakeDetect({"bcmwl-kernel-source": {}})
        (ok, _restart, _packages, error), _calls, _events, run = self.run_install(
            ["bcmwl-kernel-source"], online=False, detect=detect, media_found=False)
        self.assertEqual((False, "no-media"), (ok, error))
        self.assertEqual(["mintdrivers-remove-live-media"], run.call_args.args[0])

    def test_offline_nvidia_needs_internet(self) -> None:
        detect = FakeDetect({"nvidia-driver-580": {}})
        (ok, _restart, _packages, error), calls, _events, _run = self.run_install(["nvidia:580"], online=False,
                                                                                 detect=detect)
        self.assertEqual((False, "offline"), (ok, error))
        self.assertEqual([], calls)

    def test_too_little_space_installs_nothing(self) -> None:
        detect = FakeDetect({"nvidia-driver-580": {}},
                            {("nvidia:580", False): ["nvidia-driver-580", "linux-modules-nvidia-580-generic-hwe-24.04"]})
        (ok, restart, packages, error), calls, events, _run = self.run_install(
            ["nvidia:580"], online=True, detect=detect, apt_codes=(0,), lacking=[helper.Shortage("/", 4 * GIB, GIB)])
        self.assertEqual((False, False, [], "space"), (ok, restart, packages, error))
        self.assertEqual([["apt-get", "update"]], calls)
        self.assertEqual([], detect.hooks)
        self.assertIn({"event": "space", "path": "/", "need": 4 * GIB, "free": GIB}, events)
        self.assertNotIn({"event": "stage", "stage": "install"}, events)

    def test_apt_failure(self) -> None:
        detect = FakeDetect({"bcmwl-kernel-source": {}})
        (ok, _restart, _packages, error), _calls, _events, _run = self.run_install(
            ["bcmwl-kernel-source"], online=True, detect=detect, apt_codes=(0, 100))
        self.assertEqual((False, "apt"), (ok, error))

    def test_main_needs_root(self) -> None:
        with mock.patch.object(helper.os, "geteuid", return_value=1000), redirect_stdout(io.StringIO()), \
                mock.patch("sys.stderr", new=io.StringIO()):
            self.assertEqual(helper.EXIT_USAGE, helper.main(["install", "bcmwl-kernel-source"]))


if __name__ == "__main__":
    unittest.main()

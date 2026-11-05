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
        self.assertEqual(["nvidia:580-open", "bcmwl-kernel-source"],
                         helper.parse_args(["install", "nvidia:580-open", "bcmwl-kernel-source"]))

    def test_refused_arguments(self) -> None:
        for argv in (
            [], ["install"], ["remove", "bcmwl-kernel-source"], ["install", "bcmwl; rm -rf /"],
            ["install", "-o", "APT::Get::Assume-Yes"], ["install", "nvidia:../../x"], ["install", "a", "a"],
            ["install", "a1", "a2", "a3", "a4", "a5"], ["install", "Bcmwl"],
        ):
            with self.subTest(argv=argv), self.assertRaises(helper.UsageError):
                helper.parse_args(argv)

    def test_apt_progress(self) -> None:
        self.assertEqual(0.25, helper.apt_progress("dlstatus:1:50.0:Retrieving file 1 of 2"))
        self.assertEqual(0.75, helper.apt_progress("pmstatus:bcmwl-kernel-source:50.0:Installing"))
        self.assertIsNone(helper.apt_progress("Setting up dkms (3.0.11)"))


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


class HelperInstallTests(unittest.TestCase):
    def run_install(self, targets, *, online, detect, apt_codes=(0, 0), media_found=True, add_media=True):
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

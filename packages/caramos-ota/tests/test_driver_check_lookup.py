"""The recommended-driver lookup (UbuntuDrivers): only when it can matter, in a low-priority process with limits,
asked once per computer state, and written to Driver Check's log with the system's state for help requests.

It used to run inside the window on every scan: on an old laptop in the live session (NVIDIA GeForce 310M, the
lists read through the compressed USB image) the computer froze until the window was closed."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "usr/share/caramos-ota/driver-check"))

from caramos_driver_check import app, drivers, logs  # noqa: E402
from caramos_driver_check.hardware import Device, Snapshot  # noqa: E402

INTEL_GPU = Device("pci", "0000:00:02.0", "8086", "0046", "Intel HD Graphics", driver="i915", pci_class="030000")
GEFORCE = Device("pci", "0000:01:00.0", "10de", "0a75", "NVIDIA GeForce 310M", driver="nouveau", pci_class="030000")
BROADCOM = Device("pci", "0000:02:00.0", "14e4", "43a0", "Broadcom BCM4360", pci_class="028000")
ATHEROS = Device("pci", "0000:03:00.0", "168c", "002b", "Qualcomm Atheros AR9285", driver="ath9k", pci_class="028000",
                 net=("wlp3s0",))
VIRTUALBOX = Device("pci", "0000:00:04.0", "80ee", "cafe", "VirtualBox Guest Service", pci_class="088000")


class WantedTests(unittest.TestCase):
    def test_only_when_a_one_click_driver_can_come_out_of_it(self) -> None:
        self.assertEqual("", drivers.wanted(Snapshot(pci=(INTEL_GPU, ATHEROS))))
        self.assertEqual("NVIDIA 10de:0a75", drivers.wanted(Snapshot(pci=(INTEL_GPU, GEFORCE, ATHEROS))))
        self.assertEqual("", drivers.wanted(Snapshot(pci=(replace(GEFORCE, driver="nvidia"),))))
        self.assertEqual("Broadcom Wi-Fi 14e4:43a0", drivers.wanted(Snapshot(pci=(BROADCOM,))))
        self.assertEqual("", drivers.wanted(Snapshot(pci=(replace(BROADCOM, driver="wl", net=("wlp2s0",)),))))
        self.assertEqual("guest tools 80ee:cafe", drivers.wanted(Snapshot(pci=(VIRTUALBOX,))))

    def test_not_for_nvidia_in_the_live_session(self) -> None:
        # The case of the freeze: there the NVIDIA driver is only proposed after installing.
        self.assertEqual("", drivers.wanted(Snapshot(pci=(GEFORCE, ATHEROS), live=True)))
        self.assertEqual("Broadcom Wi-Fi 14e4:43a0", drivers.wanted(Snapshot(pci=(GEFORCE, BROADCOM), live=True)))


class LookupTests(unittest.TestCase):
    PROPOSAL = {"package": "nvidia-driver-580-open", "target": "nvidia:580-open", "address": "0000:01:00.0",
                "vendor": "NVIDIA", "model": "GA107", "free": False, "offline": False}

    def run_lookup(self, snapshot: Snapshot, **result) -> tuple[drivers.Lookup, mock.Mock]:
        with mock.patch.object(drivers.subprocess, "run", **result) as run:
            return drivers.lookup(snapshot), run

    def test_skipped_without_a_process(self) -> None:
        found, run = self.run_lookup(Snapshot(pci=(INTEL_GPU,)))
        self.assertEqual(("skipped", ()), (found.outcome, found.proposals))
        run.assert_not_called()

    def test_runs_apart_at_the_lowest_priority(self) -> None:
        answer = subprocess.CompletedProcess([], 0, json.dumps([self.PROPOSAL]), "")
        found, run = self.run_lookup(Snapshot(pci=(GEFORCE,)), return_value=answer)
        self.assertEqual("done", found.outcome)
        self.assertEqual(("nvidia-driver-580-open",), tuple(proposal.package for proposal in found.proposals))
        command = run.call_args.args[0]
        self.assertTrue(command[0].endswith("ionice") and command[1:3] == ["-c", "3"])
        self.assertTrue(command[3].endswith("nice") and command[4:6] == ["-n", "19"])
        self.assertEqual([sys.executable, "-I", "-c"], command[6:9])
        self.assertIn("print_proposals()", command[9])
        self.assertEqual(drivers.LOOKUP_TIMEOUT, run.call_args.kwargs["timeout"])

    def test_a_slow_or_broken_lookup_gives_nothing(self) -> None:
        found, _run = self.run_lookup(Snapshot(pci=(GEFORCE,)), side_effect=subprocess.TimeoutExpired("python3", 180))
        self.assertEqual(("timeout", ()), (found.outcome, found.proposals))
        broken = subprocess.CompletedProcess([], 1, "", "Traceback…\nMemoryError\n")
        found, _run = self.run_lookup(Snapshot(pci=(GEFORCE,)), return_value=broken)
        self.assertEqual("failed", found.outcome)
        self.assertIn("MemoryError", found.detail)

    def test_the_lookup_process_limits_its_memory(self) -> None:
        proposal = drivers.DriverProposal(**self.PROPOSAL)
        with mock.patch.object(drivers.resource, "setrlimit") as setrlimit, \
                mock.patch.object(drivers, "find_proposals", return_value=[proposal]), \
                mock.patch("builtins.print") as printed:
            drivers.print_proposals()
        setrlimit.assert_called_once_with(drivers.resource.RLIMIT_AS, (drivers.LOOKUP_MEMORY, drivers.LOOKUP_MEMORY))
        self.assertEqual([self.PROPOSAL], json.loads(printed.call_args.args[0]))


class ScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        patcher = mock.patch.dict(os.environ, {"XDG_CACHE_HOME": folder.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.log = Path(folder.name) / "caramos-driver-check/driver-check.log"
        with mock.patch.object(app, "read_libfprint_support", return_value={}):
            self.scanner = app.Scanner()

    def test_asked_once_while_the_computer_stays_the_same(self) -> None:
        snapshot = Snapshot(pci=(GEFORCE,))
        answer = drivers.Lookup((), "done", 31.5, "NVIDIA 10de:0a75")
        with mock.patch.object(app, "lookup", return_value=answer) as lookup:
            self.scanner.proposals(snapshot)
            self.scanner.proposals(snapshot)
            self.assertEqual(1, lookup.call_count)
            self.scanner.proposals(Snapshot(pci=(replace(GEFORCE, driver="nvidia"),)))
            self.assertEqual(2, lookup.call_count)
        text = self.log.read_text(encoding="utf-8")
        self.assertIn("driver lookup for NVIDIA 10de:0a75: 31.5 s, peak ", text)
        self.assertIn("proposals: none", text)
        self.assertIn(" · CPU ", text)

    def test_a_timeout_is_logged_and_asked_again_next_time(self) -> None:
        snapshot = Snapshot(pci=(GEFORCE,))
        answer = drivers.Lookup((), "timeout", 180.2, "NVIDIA 10de:0a75")
        with mock.patch.object(app, "lookup", return_value=answer) as lookup:
            self.scanner.proposals(snapshot)
            self.scanner.proposals(snapshot)
        self.assertEqual(2, lookup.call_count)
        self.assertIn("driver lookup for NVIDIA 10de:0a75 stopped after 180 s", self.log.read_text(encoding="utf-8"))

    def test_reading_the_hardware_is_logged(self) -> None:
        with mock.patch.object(app.SystemReader, "snapshot", return_value=Snapshot(pci=(GEFORCE,), live=True)):
            self.scanner.snapshot()
        self.assertRegex(self.log.read_text(encoding="utf-8"),
                         r"hardware read in \d+\.\d s: 1 PCI, 0 USB, 0 ACPI devices · live USB · CPU ")


class SystemLogTests(unittest.TestCase):
    def fake_root(self, folder: str, *, live: bool) -> Path:
        root = Path(folder)
        (root / "proc").mkdir()
        (root / "etc").mkdir()
        (root / "proc/cmdline").write_text("BOOT_IMAGE=/casper/vmlinuz boot=casper quiet\n" if live else "ro quiet\n")
        (root / "proc/cpuinfo").write_text("processor\t: 0\nmodel name\t: Intel(R) Core(TM) i3 CPU       M 330  @ 2.13GHz\n"
                                           "flags\t\t: fpu vme\n")
        (root / "proc/meminfo").write_text("MemTotal:        3915776 kB\nMemAvailable:     524288 kB\n"
                                           "SwapTotal:       1957884 kB\nSwapFree:          10240 kB\n")
        (root / "proc/loadavg").write_text("7.92 5.10 2.33 3/512 4242\n")
        (root / "proc/uptime").write_text("754.21 1200.00\n")
        (root / "etc/caramos-release").write_text("NAME=CaramOS\nVERSION=1.3.1\n")
        return root

    def test_the_computer_comes_first_and_the_journal_gives_way(self) -> None:
        journal = "\n".join(f"2026-10-19T20:2{n % 10}:00+07:00 host kernel: line {n}" for n in range(3000))
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(logs, "_command", return_value=""), \
                mock.patch.object(logs, "_journal", return_value=journal) as read_journal:
            text = logs.system_log(self.fake_root(folder, live=True))
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith("CaramOS 1.3.1 · Linux "))
        self.assertIn("live USB: yes", lines[0])
        self.assertEqual("CPU Intel(R) Core(TM) i3 CPU M 330 @ 2.13GHz, %s threads · load 7.92 5.10 2.33 · memory 3.7 GiB, "
                         "0.5 GiB available · swap 1.9 GiB, 0.0 GiB free · up 12 min" % (os.cpu_count() or "?"), lines[1])
        self.assertIn("line 2999", text)
        self.assertNotIn("line 10\n", text)
        self.assertLessEqual(len(text), logs.LOG_LIMIT + 200)
        read_journal.assert_called_once()   # a live USB has no previous boot

    def test_an_installed_computer_adds_how_the_previous_boot_ended(self) -> None:
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(logs, "_command", return_value=""), \
                mock.patch.object(logs, "_journal", side_effect=["this boot", "kernel: Out of memory: Killed process"]):
            text = logs.system_log(self.fake_root(folder, live=False))
        self.assertIn("== End of the previous boot", text)
        self.assertIn("Out of memory", text)

    def test_driver_checks_log_keeps_its_end(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "driver-check.log"
            for number in range(3000):
                logs.note(f"hardware read in 0.{number % 10} s, scan {number}", path)
            text = path.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.encode()), 2 * logs.DRIVER_CHECK_LOG_LIMIT)
        self.assertIn("scan 2999", text)
        self.assertNotIn("scan 5\n", text)


class FormTests(unittest.TestCase):
    def test_help_requests_carry_the_system_logs(self) -> None:
        window = (ROOT / "usr/share/caramos-ota/driver-check/caramos_driver_check/ui/window.py").read_text(encoding="utf-8")
        help_window = (ROOT / "usr/share/caramos-ota/driver-check/caramos_driver_check/ui/help_window.py").read_text(
            encoding="utf-8")
        form = (ROOT / "usr/share/caramos-ota/driver-check/caramos_driver_check/ui/help.py").read_text(encoding="utf-8")
        self.assertIn("found = system_logs()", window)
        self.assertIn("self.help_logs = self.app_logs + found", help_window)
        # Like the Driver Check results: with help and bug reports, not with feedback.
        self.assertIn("return bool(self.logs) and self.kinds[self.kind].report is not None", form)


if __name__ == "__main__":
    unittest.main()

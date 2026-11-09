"""When Driver Check speaks up at login, and hardware reports with hw-probe."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Driver Check lives in /usr/share/caramos-ota/driver-check, outside dist-packages.
sys.path.insert(0, str(Path(__file__).parents[1] / "usr/share/caramos-ota/driver-check"))

from caramos_driver_check import hwprobe
from caramos_driver_check import state as user_state
from caramos_driver_check.analysis import CRITICAL, INFO, WARNING, Finding, Report


def finding(key: str, level: str) -> Finding:
    return Finding(key=key, area=key.split(":")[0], level=level, title=key, detail="")


def report(*findings: Finding) -> Report:
    return Report(areas=(), findings=findings, connected=True, live=False, virtual=False, kernel="6.14.0",
                  wired_port=True)


WIFI = finding("wifi:broadcom:pci:14e4:43a0", CRITICAL)
NVIDIA = finding("graphics:nvidia:pci:10de:1f99", WARNING)
IPU = finding("camera:ipu:pci:8086:465d", INFO)
PRINTER = finding("printer:capt:usb:04a9:2676", WARNING)


class DecisionTests(unittest.TestCase):
    def test_first_check_opens_the_window_for_problems(self) -> None:
        decision = user_state.decide(report(NVIDIA, IPU), user_state.UserState())
        self.assertEqual(user_state.SHOW_WINDOW, decision.action)
        self.assertEqual((NVIDIA,), decision.new)

    def test_first_check_opens_the_window_also_when_everything_works(self) -> None:
        # The first login after installing and every live USB boot: people want to see their hardware works.
        for found in (report(IPU), report()):
            decision = user_state.decide(found, user_state.UserState())
            self.assertEqual(user_state.SHOW_WINDOW, decision.action)
            self.assertEqual((), decision.new)

    def test_known_problems_stay_quiet(self) -> None:
        seen = user_state.UserState(first_check_done=True, seen={NVIDIA.key})
        self.assertEqual(user_state.QUIET, user_state.decide(report(NVIDIA, IPU), seen).action)

    def test_a_new_warning_notifies_and_a_new_critical_problem_opens_the_window(self) -> None:
        state = user_state.UserState(first_check_done=True, seen=set())
        self.assertEqual(user_state.NOTIFY_PROBLEMS, user_state.decide(report(NVIDIA), state).action)
        self.assertEqual(user_state.SHOW_WINDOW, user_state.decide(report(WIFI, NVIDIA), state).action)

    def test_a_solved_problem_is_announced_once(self) -> None:
        state = user_state.UserState(first_check_done=True, seen={WIFI.key})
        decision = user_state.decide(report(), state)
        self.assertEqual(user_state.NOTIFY_RESOLVED, decision.action)
        self.assertEqual((WIFI.key,), decision.resolved)
        after = user_state.remember(report(), state)
        self.assertEqual(user_state.QUIET, user_state.decide(report(), after).action)

    def test_remember_keeps_only_problems(self) -> None:
        remembered = user_state.remember(report(WIFI, IPU), user_state.UserState())
        self.assertTrue(remembered.first_check_done)
        self.assertEqual({WIFI.key}, remembered.seen)

    def test_an_unplugged_device_is_away_not_solved(self) -> None:
        # A laptop taken home from the office printer: no "problem solved", and no news when it is back.
        state = user_state.UserState(first_check_done=True, seen={PRINTER.key, NVIDIA.key})
        at_home = {"pci:10de:1f99"}
        decision = user_state.decide(report(NVIDIA), state, at_home)
        self.assertEqual((user_state.QUIET, ()), (decision.action, decision.resolved))
        after = user_state.remember(report(NVIDIA), state, at_home)
        self.assertEqual({PRINTER.key, NVIDIA.key}, after.seen)

        at_work = at_home | {"usb:04a9:2676"}
        self.assertEqual(user_state.QUIET, user_state.decide(report(NVIDIA, PRINTER), after, at_work).action)
        # Solved for real: the printer is plugged in and has its driver.
        decision = user_state.decide(report(NVIDIA), after, at_work)
        self.assertEqual((user_state.NOTIFY_RESOLVED, (PRINTER.key,)), (decision.action, decision.resolved))
        self.assertEqual({NVIDIA.key}, user_state.remember(report(NVIDIA), after, at_work).seen)

    def test_problems_without_a_device_are_solved_when_gone(self) -> None:
        state = user_state.UserState(first_check_done=True, seen={"wifi:soft-blocked"})
        decision = user_state.decide(report(), state, set())
        self.assertEqual(("wifi:soft-blocked",), decision.resolved)
        self.assertEqual(set(), user_state.remember(report(), state, set()).seen)

    def test_device_keys(self) -> None:
        self.assertEqual("usb:04a9:2676", user_state.device_key(PRINTER.key))
        self.assertEqual("pci:14e4:43a0", user_state.device_key(WIFI.key))
        self.assertEqual("", user_state.device_key("network:none"))
        self.assertEqual("", user_state.device_key("driver:nvidia-driver-580"))


class NotificationTextTests(unittest.TestCase):
    def setUp(self) -> None:
        from caramos_driver_check import notify

        self.notify = notify

    def test_new_problems_name_the_first_one(self) -> None:
        one = user_state.Decision(user_state.NOTIFY_PROBLEMS, new=(NVIDIA,))
        title, body = self.notify.text_for(one, report(NVIDIA))
        self.assertEqual(NVIDIA.title, title)
        self.assertNotIn("%d", body)
        two = user_state.Decision(user_state.NOTIFY_PROBLEMS, new=(NVIDIA, WIFI))
        self.assertIn("2", self.notify.text_for(two, report(NVIDIA, WIFI))[1])

    def test_a_solved_problem_says_so(self) -> None:
        decision = user_state.Decision(user_state.NOTIFY_RESOLVED, resolved=(WIFI.key,))
        self.assertEqual("Hardware problem solved", self.notify.text_for(decision, report())[0])

    def test_every_notification_waits_for_its_button(self) -> None:
        for action in (user_state.NOTIFY_PROBLEMS, user_state.NOTIFY_RESOLVED):
            self.assertGreater(self.notify.WAIT_SECONDS[action], 0)


class StateFileTests(unittest.TestCase):
    def test_round_trip_and_damaged_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "caramos-driver-check/state.json"
            self.assertEqual(user_state.UserState(), user_state.load(path))
            user_state.save(path, user_state.UserState(True, {"b", "a"}))
            self.assertEqual(user_state.UserState(True, {"a", "b"}), user_state.load(path))
            self.assertEqual([path.name], os.listdir(path.parent))   # no temporary file left
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(user_state.UserState(), user_state.load(path))
            path.write_text('{"first_check_done": "yes", "seen": "x"}', encoding="utf-8")
            self.assertEqual(user_state.UserState(), user_state.load(path))

    def test_state_lives_in_the_config_directory(self) -> None:
        self.assertEqual(Path("/c/caramos-driver-check/state.json"),
                         user_state.state_path({"XDG_CONFIG_HOME": "/c", "HOME": "/h"}))
        self.assertEqual(Path("/h/.config/caramos-driver-check/state.json"), user_state.state_path({"HOME": "/h"}))


class HwProbeTests(unittest.TestCase):
    def test_probe_link_from_upload_output(self) -> None:
        output = "Probe for hardware ... Ok\nUploaded to DB, Thank you!\n\nProbe URL: https://linux-hardware.org/?probe=1d2b3e4f5a\n"
        self.assertEqual("https://linux-hardware.org/?probe=1d2b3e4f5a", hwprobe.probe_url(output))
        self.assertEqual("https://linux-hardware.org/?probe=abc", hwprobe.probe_url("see http://linux-hardware.org/?probe=abc"))
        self.assertEqual("https://linux-hardware.org/?probe=0f0f", hwprobe.probe_url("Uploaded: probe=0f0f"))
        self.assertEqual("", hwprobe.probe_url("ERROR: failed to upload data"))

    def test_upload_runs_hw_probe_as_root(self) -> None:
        with mock.patch.object(hwprobe, "_stream", return_value=(0, "Probe URL: https://linux-hardware.org/?probe=ab12")) as stream:
            result = hwprobe.upload(lambda line: None)
        self.assertEqual(["pkexec", "/usr/bin/hw-probe", "-all", "-upload"], stream.call_args.args[0])
        self.assertTrue(result.ok)
        self.assertEqual("https://linux-hardware.org/?probe=ab12", result.url)

    def test_failed_upload(self) -> None:
        for code in (126, 127):   # password dialog dismissed / not authorized
            with mock.patch.object(hwprobe, "_stream", return_value=(code, "Error executing command as another user")):
                result = hwprobe.upload(lambda line: None)
            self.assertEqual((False, True), (result.ok, result.refused))
        with mock.patch.object(hwprobe, "_stream", return_value=(1, "ERROR: failed to upload data")):
            result = hwprobe.upload(lambda line: None)
        self.assertEqual((False, False), (result.ok, result.refused))

    def test_saved_report_is_copied_to_the_users_folder(self) -> None:
        def fake_stream(command, on_line):
            scratch = Path(command[command.index("-save") + 1])
            (scratch / "hw.info.txz").write_bytes(b"probe")
            return 0, f"Saved to: {scratch}/hw.info.txz"

        with tempfile.TemporaryDirectory() as temp, mock.patch.object(hwprobe, "_stream", side_effect=fake_stream):
            result = hwprobe.save(lambda line: None, Path(temp) / "hw-probe-log")
            self.assertTrue(result.ok)
            saved = Path(result.saved)
            self.assertEqual(Path(temp) / "hw-probe-log", saved.parent)
            self.assertRegex(saved.name, r"^hw-probe-\d{8}-\d{6}\.txz$")
            self.assertEqual(b"probe", saved.read_bytes())

    def test_save_fails_when_nothing_was_written(self) -> None:
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(hwprobe, "_stream", return_value=(0, "")):
            self.assertFalse(hwprobe.save(lambda line: None, Path(temp)).ok)
        with tempfile.TemporaryDirectory() as temp, mock.patch.object(hwprobe, "_stream", return_value=(126, "")):
            self.assertTrue(hwprobe.save(lambda line: None, Path(temp)).refused)

    def test_stream_collects_lines(self) -> None:
        lines: list[str] = []
        code, output = hwprobe._stream(["sh", "-c", "echo one; echo two >&2; exit 3"], lines.append)
        self.assertEqual(3, code)
        self.assertEqual(["one", "two"], lines)
        self.assertEqual("one\ntwo", output)


if __name__ == "__main__":
    unittest.main()

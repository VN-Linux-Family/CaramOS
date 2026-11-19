"""caramos-boot-success: GRUB's menu comes back after a boot that never reached the desktop.

GRUB shows its menu after a boot whose recordfail mark nobody cleared. Ubuntu clears it as soon as the system is
up (grub-common.service); CaramOS holds that service back and clears the mark once a user's graphical session has
lasted a minute."""

from __future__ import annotations

import configparser
import importlib.machinery
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "usr/share/caramos-ota/boot-success/caramos-boot-success"
UNITS = ROOT / "usr/lib/systemd/system"


def load_script():
    loader = importlib.machinery.SourceFileLoader("caramos_boot_success_test", str(SCRIPT))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


boot = load_script()


def session(**fields: str) -> dict[str, str]:
    base = {"Class": "user", "Type": "x11", "Remote": "no", "TimestampMonotonic": str(20 * 1_000_000)}
    base.update(fields)
    return base


def unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read_string((UNITS / name).read_text(encoding="utf-8"))
    return parser


class DesktopReachedTests(unittest.TestCase):
    def test_a_desktop_session_counts_after_a_minute(self) -> None:
        self.assertFalse(boot.desktop_reached(79.0, [session()]), "20 s into the session")
        self.assertTrue(boot.desktop_reached(80.0, [session()]))

    def test_other_sessions_do_not_count(self) -> None:
        others = [
            session(Class="greeter"),                # the login screen: someone may still see nothing
            session(Type="tty"),                     # a text console (Ctrl+Alt+F2)
            session(Type="unspecified"),             # ssh, cron
            session(Remote="yes", Type="x11"),       # a remote desktop
            session(TimestampMonotonic="0"),
            session(TimestampMonotonic="soon"),
        ]
        self.assertFalse(boot.desktop_reached(10_000.0, others))
        self.assertTrue(boot.desktop_reached(10_000.0, others + [session(Type="wayland")]))


class MainTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.grubenv = self.root / "grubenv"
        self.grubenv.write_text("# GRUB Environment Block\nrecordfail=1\n" + "#" * 990, encoding="ascii")
        self.uptime = self.root / "uptime"
        self.uptime.write_text("300.00 1000.00\n", encoding="ascii")
        for name, value in (("GRUBENV", self.grubenv), ("FLAG", self.root / "flag"), ("UPTIME", self.uptime)):
            patcher = mock.patch.object(boot, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.commands: list[list[str]] = []
        self.listed = [session()]

    def fake_run(self, *args: str) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(args))
        if args[:2] == ("loginctl", "list-sessions"):
            text = "".join(f"{index} 1000 caram seat0 tty7\n" for index, _ in enumerate(self.listed, 2))
            return subprocess.CompletedProcess(args, 0, text, "")
        if args[:2] == ("loginctl", "show-session"):
            fields = self.listed[int(args[2]) - 2]
            return subprocess.CompletedProcess(args, 0, "".join(f"{k}={v}\n" for k, v in fields.items()), "")
        return subprocess.CompletedProcess(args, 0, "", "")

    def main(self) -> int:
        with mock.patch.object(boot, "run", self.fake_run), mock.patch("builtins.print"):
            return boot.main()

    def test_clears_the_mark_once_and_stops_the_timer(self) -> None:
        self.assertEqual(0, self.main())
        self.assertIn(["grub-editenv", str(self.grubenv), "unset", "recordfail"], self.commands)
        self.assertIn(["systemctl", "--no-block", "stop", "caramos-boot-success.timer"], self.commands)
        self.assertTrue((self.root / "flag").exists())
        self.commands.clear()
        self.assertEqual(0, self.main())
        self.assertEqual([], self.commands, "nothing more to do in this boot")

    def test_waits_while_nobody_reached_the_desktop(self) -> None:
        self.listed = [session(Class="greeter")]
        self.assertEqual(0, self.main())
        self.assertFalse(any(command[0] == "grub-editenv" for command in self.commands))
        self.assertFalse((self.root / "flag").exists())

    def test_recreates_an_empty_grubenv_first(self) -> None:
        self.grubenv.write_text("", encoding="ascii")
        self.main()
        editenv = [command for command in self.commands if command[0] == "grub-editenv"]
        self.assertEqual([["grub-editenv", str(self.grubenv), "create"],
                          ["grub-editenv", str(self.grubenv), "unset", "recordfail"]], editenv)

    def test_a_failed_grub_editenv_leaves_the_flag_unset(self) -> None:
        def failing(*args: str) -> subprocess.CompletedProcess[str]:
            if args[0] == "grub-editenv":
                self.commands.append(list(args))
                return subprocess.CompletedProcess(args, 1, "", "read-only file system")
            return self.fake_run(*args)

        with mock.patch.object(boot, "run", failing), mock.patch("builtins.print"):
            self.assertEqual(1, boot.main())
        self.assertFalse((self.root / "flag").exists(), "the timer tries again")


class UnitTests(unittest.TestCase):
    def test_grub_common_waits_for_the_flag(self) -> None:
        dropin = configparser.ConfigParser(interpolation=None)
        dropin.optionxform = str
        dropin.read_string((UNITS / "grub-common.service.d/caramos-boot-success.conf").read_text(encoding="utf-8"))
        self.assertEqual(f"/usr/bin/test -e {boot.FLAG}", dropin["Service"]["ExecCondition"])

    def test_the_timer_runs_the_script_outside_live_sessions(self) -> None:
        service = unit("caramos-boot-success.service")
        self.assertEqual("/usr/share/caramos-ota/boot-success/caramos-boot-success", service["Service"]["ExecStart"])
        self.assertEqual("oneshot", service["Service"]["Type"])
        self.assertIn("!boot=casper", service["Unit"]["ConditionKernelCommandLine"])
        timer = unit("caramos-boot-success.timer")
        self.assertEqual("timers.target", timer["Install"]["WantedBy"])
        self.assertIn("OnUnitInactiveSec", timer["Timer"])
        self.assertEqual(boot.TIMER, "caramos-boot-success.timer")

    def test_an_upgrade_does_not_start_the_timer_again(self) -> None:
        # An upgrade of caramos-ota restarts the timer. In a boot that already told GRUB, the service skips itself
        # and never stops the timer: a "skipped" line in the journal every 30 seconds until the next boot.
        text = (UNITS / "caramos-boot-success.timer").read_text(encoding="utf-8")
        self.assertIn(f"ConditionPathExists=!{boot.FLAG}\n", text)

    def test_the_package_ships_and_enables_them(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        for path in ("usr/lib/systemd/system/caramos-boot-success.service",
                     "usr/lib/systemd/system/caramos-boot-success.timer",
                     "usr/lib/systemd/system/grub-common.service.d/caramos-boot-success.conf",
                     "usr/share/caramos-ota/boot-success "):
            self.assertIn(path, install)
        self.assertIn("dh_installsystemd caramos-boot-success.timer", (ROOT / "debian/rules").read_text(encoding="utf-8"))
        self.assertTrue(SCRIPT.stat().st_mode & 0o111, "the script is executable")


if __name__ == "__main__":
    unittest.main()

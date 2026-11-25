"""Feedback & Help sends this computer's details with every kind of request (computer.log, the Driver Check results and
the system logs), unless the user unticks "Send this computer's details": enough to answer a question about
hardware, drivers, printers or being "logged out" without asking anyone to look anything up."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
APP = ROOT / "usr/share/caramos-ota/driver-check"
# Driver Check lives in /usr/share/caramos-ota/driver-check, outside dist-packages.
sys.path.insert(0, str(APP))

from caramos_driver_check import computer, helpdesk, logs  # noqa: E402

LSPCI = """00:00.0 Host bridge [0600]: Intel Corporation 2nd Generation Core Processor Family DRAM Controller [8086:0100] (rev 09)
\tSubsystem: ASUSTeK Computer Inc. P8H61-M LX [1043:844d]
00:02.0 VGA compatible controller [0300]: Intel Corporation 2nd Generation Core Processor Family Integrated Graphics Controller [8086:0102] (rev 09)
\tKernel driver in use: i915
\tKernel modules: i915
03:00.0 Ethernet controller [0200]: Realtek Semiconductor Co., Ltd. RTL8111/8168/8411 PCI Express Gigabit Ethernet Controller [10ec:8168] (rev 06)
\tKernel driver in use: r8169
"""
LSUSB = "Bus 002 Device 003: ID 0416:5011 Winbond Electronics Corp. Virtual Com Port\n"
LSUSB_TREE = "/:  Bus 002.Port 001: Dev 001, Class=root_hub, Driver=ehci-pci/2p, 480M\n" \
             "    |__ Port 002: Dev 003, If 0, Class=Communications, Driver=cdc_acm, 12M\n"
JOURNAL_THIS = """2026-11-25T08:01:02+0700 office-pc-07 systemd-logind[612]: New session c1 of user lightdm.
2026-11-25T08:01:03+0700 office-pc-07 lightdm[700]: pam_unix(lightdm-greeter:session): session opened for user lightdm(uid=118) by (uid=0)
2026-11-25T08:01:05+0700 office-pc-07 lightdm[701]: pam_unix(lightdm-autologin:session): session opened for user minhanh(uid=1000) by (uid=0)
2026-11-25T08:01:05+0700 office-pc-07 systemd-logind[612]: New session c2 of user minhanh.
2026-11-25T08:01:06+0700 office-pc-07 systemd-logind[612]: Removed session c1.
2026-11-25T10:15:00+0700 office-pc-07 systemd-logind[612]: Lid closed.
2026-11-25T10:15:01+0700 office-pc-07 systemd-logind[612]: The system will suspend now!
2026-11-25T10:15:02+0700 office-pc-07 systemd-sleep[900]: Entering sleep state 'suspend'...
2026-11-25T11:40:00+0700 office-pc-07 systemd-sleep[900]: System returned from sleep state.
2026-11-25T11:40:01+0700 office-pc-07 systemd-logind[612]: Lid opened.
2026-11-25T11:40:02+0700 office-pc-07 systemd-logind[612]: New session c3 of user lan.
2026-11-25T11:41:00+0700 office-pc-07 systemd-logind[612]: New session 7 of user minhanh.
2026-11-25T11:41:09+0700 office-pc-07 systemd-logind[612]: Removed session 7.
2026-11-25T11:40:03+0700 office-pc-07 systemd-logind[612]: Watching system buttons on /dev/input/event3 (Power Button)
"""
CINNAMON_SETTINGS = {
    "org.cinnamon.desktop.session": "org.cinnamon.desktop.session idle-delay uint32 900\n"
                                    "org.cinnamon.desktop.session session-name 'cinnamon'\n",
    "org.cinnamon.desktop.screensaver": "org.cinnamon.desktop.screensaver lock-enabled true\n"
                                        "org.cinnamon.desktop.screensaver lock-delay uint32 600\n",
    "org.cinnamon.settings-daemon.plugins.power":
        "org.cinnamon.settings-daemon.plugins.power lock-on-suspend true\n"
        "org.cinnamon.settings-daemon.plugins.power sleep-inactive-battery-timeout 900\n",
}


class FakeSystem:
    """A computer's files under a folder and the answers of the commands computer.py runs."""

    def __init__(self, root: Path, desktop: str = "cinnamon", keyring: str = "b true", journal: str = JOURNAL_THIS,
                 queues: str = "") -> None:
        self.root = root
        self.desktop = desktop
        self.keyring = keyring
        self.journal = journal
        self.queues = queues
        self.commands: list[list[str]] = []
        files = {
            "etc/caramos-release": 'NAME="CaramOS"\nVERSION="1.5.1"\n',
            "etc/os-release": "UBUNTU_CODENAME=noble\n",
            "etc/upstream-release/lsb-release": 'DISTRIB_DESCRIPTION="Ubuntu 24.04 LTS"\n',
            "proc/meminfo": "MemTotal:        3923464 kB\nMemAvailable:    2000000 kB\n",
            "sys/class/dmi/id/sys_vendor": "ASUSTeK COMPUTER INC.\n",
            "sys/class/dmi/id/product_name": "All Series\n",
            "sys/class/dmi/id/board_vendor": "ASUSTeK COMPUTER INC.\n",
            "sys/class/dmi/id/board_name": "P8H61-M LX\n",
            "sys/class/dmi/id/bios_vendor": "American Megatrends Inc.\n",
            "sys/class/dmi/id/bios_version": "0601\n",
            "sys/class/dmi/id/bios_date": "09/14/2012\n",
            "sys/class/dmi/id/chassis_type": "3\n",
            "etc/lightdm/lightdm.conf": "[Seat:*]\nautologin-guest=false\nautologin-user=minhanh\nautologin-user-timeout=0\n",
        }
        for name, text in files.items():
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(text, encoding="utf-8")

    def run(self, arguments):  # noqa: ANN001
        args = list(arguments)
        self.commands.append(args)

        def ok(out: str = "") -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args, 0, out, "")

        if args[0] == "lspci":
            return ok(LSPCI)
        if args == ["lsusb"]:
            return ok(LSUSB)
        if args == ["lsusb", "-t"]:
            return ok(LSUSB_TREE)
        if args == ["lpstat", "-v"]:
            return ok(self.queues)
        if args == ["lpstat", "-d"]:
            return ok("system default destination: XP-58\n")
        if args[:2] == ["lpoptions", "-p"]:
            model = "Generic Text-Only Printer" if args[2] == "XP-58" else "HP LaserJet Pro M404n, driverless"
            return ok(f"device-uri=x printer-make-and-model='{model}' printer-state=3 printer-state-reasons=none\n")
        if args[:2] == ["gsettings", "list-recursively"]:
            if self.desktop == "xfce" and args[2] == "apps.light-locker":
                return ok("apps.light-locker lock-after-screensaver uint32 900\napps.light-locker lock-on-suspend true\n")
            if self.desktop == "cinnamon" and args[2] in CINNAMON_SETTINGS:
                return ok(CINNAMON_SETTINGS[args[2]])
            return subprocess.CompletedProcess(args, 1, "", "No such schema")
        if args[:2] == ["dconf", "dump"]:
            return ok("[/]\nidle-delay=uint32 900\n" if args[2] == "/org/cinnamon/desktop/session/" else "")
        if args[0] == "xfconf-query":
            if self.desktop != "xfce":
                return subprocess.CompletedProcess(args, 1, "", "no channel")
            return ok("/xfce4-power-manager/blank-on-ac            15\n/xfce4-power-manager/show-panel-label    0\n"
                      "/xfce4-power-manager/lock-screen-suspend-hibernate  true\n")
        if args[0] == "busctl":
            if "ReadAlias" in args:
                return ok('o "/org/freedesktop/secrets/collection/login"\n')
            return ok(f"{self.keyring}\n" if args[-1] == "Locked" else 's "Login"\n')
        if args[0] == "journalctl":
            if args[2] == "-1":
                return subprocess.CompletedProcess(args, 1, "", "Data from the specified boot (-1) is not available")
            return ok(self.journal)
        return subprocess.CompletedProcess(args, 127, "", "not faked")

    def log(self, **environ: str) -> str:
        env = {"XDG_CURRENT_DESKTOP": "X-Cinnamon" if self.desktop == "cinnamon" else "XFCE",
               "XDG_SESSION_TYPE": "x11", **environ}
        with mock.patch.object(computer.getpass, "getuser", return_value="minhanh"), \
                mock.patch.object(logs.getpass, "getuser", return_value="minhanh"):
            return computer.computer_log(self.root, self.run, env)


class ComputerLogTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)

    def test_the_computer_its_devices_and_drivers(self) -> None:
        text = FakeSystem(self.root).log()
        self.assertIn("CaramOS 1.5.1, Cinnamon edition (x11 session) · Ubuntu 24.04 LTS · Linux", text)
        self.assertIn("Computer: ASUSTeK COMPUTER INC. All Series · desktop · board ASUSTeK COMPUTER INC. P8H61-M LX · "
                      "firmware American Megatrends Inc. 0601 (09/14/2012)", text)
        self.assertIn("Memory 3.7 GiB", text)
        self.assertIn("[10ec:8168]", text)
        self.assertIn("Kernel driver in use: r8169", text)
        self.assertIn("ID 0416:5011 Winbond Electronics Corp. Virtual Com Port", text)
        self.assertIn("Driver=cdc_acm", text)
        self.assertLessEqual(len(text), logs.LOG_LIMIT + 2)

    def test_printers_keep_only_the_names_of_usb_queues(self) -> None:
        queues = "device for XP-58: usb://Xprinter/XP-58?serial=ABC123\n" \
                 "device for Phong-Ke-Toan: ipp://192.168.1.20/ipp/print\n"
        text = FakeSystem(self.root, queues=queues).log()
        self.assertIn("XP-58 (default): usb · Generic Text-Only Printer · idle, none", text)
        self.assertIn("queue 2: ipp · HP LaserJet Pro M404n, driverless · idle, none", text)
        for gone in ("Phong-Ke-Toan", "192.168.1.20", "ABC123"):
            self.assertNotIn(gone, text)

    def test_how_the_screen_locks_and_the_computer_sleeps_on_cinnamon(self) -> None:
        text = FakeSystem(self.root).log()
        self.assertIn("Automatic login (LightDM): on\n", text)
        self.assertIn("Keyring for saved sign-ins: “Login”, locked\n", text)
        self.assertIn("[org.cinnamon.desktop.session] idle-delay uint32 900 (set by this user)", text)
        self.assertIn("[org.cinnamon.desktop.screensaver] lock-enabled true, lock-delay uint32 600\n", text)
        self.assertIn("[org.cinnamon.settings-daemon.plugins.power] lock-on-suspend true, "
                      "sleep-inactive-battery-timeout 900", text)
        self.assertNotIn("session-name", text, "only what decides when it locks or sleeps")
        self.assertNotIn("xfce4-power-manager", text)

    def test_how_the_screen_locks_on_xfce(self) -> None:
        text = FakeSystem(self.root, desktop="xfce", keyring="b false").log()
        self.assertIn("Xfce edition", text)
        self.assertIn("Keyring for saved sign-ins: “Login”, unlocked\n", text)
        self.assertIn("[xfce4-power-manager] blank-on-ac 15, lock-screen-suspend-hibernate true (xfconf;", text)
        self.assertNotIn("show-panel-label", text)
        self.assertIn("[apps.light-locker] lock-after-screensaver uint32 900, lock-on-suspend true", text)
        self.assertNotIn("org.cinnamon", text)

    def test_logins_locks_and_sleep_without_names(self) -> None:
        text = FakeSystem(self.root).log()
        events = text[text.index("== Logins"):]
        self.assertIn("The boot before: not in the journal", events)
        for line in ("11-25 08:01:02 session c1 opened for the login screen",
                     "11-25 08:01:03 the login screen opened (the login screen)",
                     "11-25 08:01:05 an automatic login opened (this user)",
                     "11-25 08:01:05 session c2 opened for this user",
                     "11-25 08:01:06 session c1 closed",
                     "11-25 10:15:00 lid closed",
                     "11-25 10:15:01 the system will suspend",
                     "11-25 10:15:02 going to sleep (suspend)",
                     "11-25 11:40:00 woke up",
                     "11-25 11:40:02 session c3 opened for another user",
                     "(1 logins without a desktop, over SSH or a text console, left out)"):
            self.assertIn(line, events)
        self.assertNotIn("session 7", events)
        self.assertNotIn("Watching system buttons", events)
        for gone in ("minhanh", "lan.", "office-pc-07", "uid="):
            self.assertNotIn(gone, text)

    def test_the_journal_the_user_may_not_read(self) -> None:
        text = FakeSystem(self.root, journal="").log()
        self.assertIn("This boot: no logins or sleeps the user may read (the system journal needs the adm group)", text)

    def test_the_keyring_is_never_started_and_each_answer_is_worded(self) -> None:
        system = FakeSystem(self.root)
        system.log()
        calls = [command for command in system.commands if command[0] == "busctl"]
        self.assertTrue(calls and all("--auto-start=no" in command for command in calls))
        self.assertIn("ReadAlias", calls[0])

        def answers(alias: tuple[int, str, str], locked: str = "b true", label: str = 's "Default keyring"'):
            def runner(args):  # noqa: ANN001
                if "ReadAlias" in args:
                    return subprocess.CompletedProcess(args, *alias)
                return subprocess.CompletedProcess(args, 0, (locked if args[-1] == "Locked" else label) + "\n", "")
            return runner

        default = (0, 'o "/org/freedesktop/secrets/collection/Default_5fkeyring"\n', "")
        for runner, word in (
                # An automatic login: the keyring an app made, locked until someone types its password.
                (answers(default), "“Default keyring”, locked"),
                (answers(default, "b false"), "“Default keyring”, unlocked"),
                (answers(default, label='s "Bank of Minh"'), "another keyring, locked"),
                (answers((0, 'o "/"\n', "")), "none yet: the first app that saves a sign-in asks to make one"),
                (answers((1, "", "Call failed: The name org.freedesktop.secrets was not provided by any .service files")),
                 "the keyring service is not running"),
                (answers((1, "", "Call failed: The name is not activatable")), "the keyring service is not running")):
            with self.subTest(word=word):
                self.assertEqual(word, computer.keyring(runner))

    def test_automatic_login_the_later_file_wins_and_no_name_is_said(self) -> None:
        conf = self.root / "etc/lightdm/lightdm.conf.d"
        conf.mkdir(parents=True)
        share = self.root / "usr/share/lightdm/lightdm.conf.d"
        share.mkdir(parents=True)
        (share / "50-ubuntu.conf").write_text("[Seat:*]\nuser-session=cinnamon\n", encoding="utf-8")
        self.assertEqual("off", computer.autologin(self.root))
        (conf / "70-caramos.conf").write_text("[SeatDefaults]\nautologin-user=minhanh\nautologin-user-timeout=10\n",
                                              encoding="utf-8")
        self.assertEqual("on, after 10 s at the login screen", computer.autologin(self.root))
        (self.root / "etc/lightdm/lightdm.conf").write_text("[Seat:*]\n#autologin-user=x\nautologin-user=\n",
                                                            encoding="utf-8")
        self.assertEqual("off", computer.autologin(self.root), "lightdm.conf comes last")

    def test_a_part_that_fails_costs_only_itself(self) -> None:
        system = FakeSystem(self.root)
        with mock.patch.object(computer, "printer_lines", side_effect=RuntimeError("cups")):
            text = system.log()
        self.assertIn("(could not be read: cups)", text)
        self.assertIn("Keyring for saved sign-ins: “Login”, locked", text)


class RequestTests(unittest.TestCase):
    def test_every_request_carries_computer_log_first(self) -> None:
        with mock.patch.object(logs, "system_log", return_value="CaramOS 1.5.1"), \
                mock.patch("caramos_driver_check.computer.computer_log", return_value="== This computer ==\n"), \
                mock.patch.object(logs, "read_log", return_value=None), \
                mock.patch("caramos_driver_check.printers.printer_log", return_value=""):
            found = logs.system_logs()
        self.assertEqual(["computer.log", "system.log"], [log.name for log in found])
        self.assertTrue(all(log.name in logs.COMPUTER_LOGS for log in found))

    def test_without_computer_log_the_other_logs_still_go(self) -> None:
        with mock.patch.object(logs, "system_log", return_value="CaramOS 1.5.1"), \
                mock.patch("caramos_driver_check.computer.computer_log", side_effect=RuntimeError("lspci")), \
                mock.patch.object(logs, "read_log", return_value=None), \
                mock.patch("caramos_driver_check.printers.printer_log", return_value=""):
            self.assertEqual(["system.log"], [log.name for log in logs.system_logs()])

    def test_feedback_carries_the_details_too(self) -> None:
        payload = helpdesk.build_request("Xin driver cho máy in Xprinter XP-58", kind="feedback", app="caramos-help",
                                         report={"areas": [], "findings": []},
                                         logs={"computer.log": "== This computer ==", "system.log": "CaramOS"})
        self.assertEqual("feedback", payload["type"])
        self.assertEqual(["computer.log", "system.log"], sorted(payload["report"]["logs"]))

    def test_computer_log_keeps_its_start_when_the_report_is_too_big(self) -> None:
        start = "== This computer ==\nComputer: ASUSTeK P8H61-M LX\n"
        texts = {"computer.log": start + "x\n" * 9000, "system.log": "y\n" * 24000, "driver-check.log": "z\n" * 24000,
                 "printer.log": "p\n" * 12000}
        report = helpdesk._with_logs({"findings": []}, texts)
        self.assertLessEqual(helpdesk._json_length(report), helpdesk.MAX_REPORT)
        self.assertTrue(report["logs"]["computer.log"].startswith(start))
        self.assertEqual(texts["computer.log"], report["logs"]["computer.log"], "the others give way first")
        # Alone and too long, computer.log loses its end, never its start.
        alone = helpdesk._with_logs({}, {"computer.log": start + "x\n" * 40000})
        self.assertTrue(alone["logs"]["computer.log"].startswith(start))
        self.assertTrue(alone["logs"]["computer.log"].endswith("\n…"))
        self.assertLessEqual(helpdesk._json_length(alone), helpdesk.MAX_REPORT)


FORM_CHECK = textwrap.dedent(
    """
    import json, sys
    sys.path.insert(0, sys.argv[1])
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk
    if not Gtk.init_check():
        print("SKIP"); sys.exit(0)
    Adw.init()
    from caramos_driver_check.analysis import Report
    from caramos_driver_check.logs import Log
    from caramos_driver_check.ui.help import HelpForm

    report = Report(areas=(), findings=(), connected=True, live=False, virtual=False, kernel="6.14", wired_port=True)
    found = (Log("computer.log", "== This computer =="), Log("system.log", "CaramOS 1.5.1"),
             Log("update-failure.log", "the update failed"))
    result = {}
    for kind in ("os", "bug", "feedback"):
        sent = []
        form = HelpForm(kind, ("os", "bug", "feedback"), None, ready=False, title="Feedback & Help", online=True,
                        on_send=sent.append, on_save_probe=lambda: None, on_back=lambda: None, back_label="Close")
        reading = form.with_report.get_visible()
        form.set_report(report)
        form.set_context("", found)
        form.message.get_buffer().set_text("Máy in Xprinter XP-58 không in được")
        form._send()
        form.with_report.set_active(False)
        form._send()
        result[kind] = {"offered_while_reading": reading, "offered": form.with_report.get_visible(),
                        "ticked": form.with_report.get_active() or True, "label": form.with_report.get_label(),
                        "logs_label": form.with_logs.get_label(), "logs_box": form.with_logs.get_visible(),
                        "sent": [{"report": r.with_report, "logs": [log.name for log in r.logs]} for r in sent]}
        form.cleanup()
    print(json.dumps(result))
    """
)


class FormTests(unittest.TestCase):
    def test_every_kind_offers_the_details_ticked(self) -> None:
        done = subprocess.run([sys.executable, "-c", FORM_CHECK, str(APP)], capture_output=True, text=True,
                              env={**os.environ, "PYTHONPATH": str(ROOT / "usr/lib/python3/dist-packages"),
                                   "LANGUAGE": "en", "GSK_RENDERER": "cairo"}, timeout=120, check=False)
        if done.returncode != 0 and ("No module named 'gi'" in done.stderr or "Namespace" in done.stderr):
            self.skipTest("GTK 4 and libadwaita are not installed")
        self.assertEqual(0, done.returncode, done.stderr[-3000:])
        if done.stdout.strip() == "SKIP":
            self.skipTest("no display")
        result = json.loads(done.stdout.strip().splitlines()[-1])
        for kind, seen in result.items():
            with self.subTest(kind=kind):
                self.assertTrue(seen["offered_while_reading"])
                self.assertTrue(seen["offered"])
                self.assertEqual("Send this computer's details", seen["label"])
                self.assertEqual("Attach the app's log (update-failure.log)", seen["logs_label"])
                self.assertTrue(seen["logs_box"])
                self.assertEqual([{"report": True, "logs": ["update-failure.log", "computer.log", "system.log"]},
                                  {"report": False, "logs": ["update-failure.log"]}], seen["sent"])

    def test_the_form_source(self) -> None:
        source = (APP / "caramos_driver_check/ui/help.py").read_text(encoding="utf-8")
        feedback = source[source.index('"feedback": Kind('):]
        self.assertIn("probe=None, report=True),", feedback[:feedback.index("}")])
        self.assertIn('self.with_report = Gtk.CheckButton(label=_("Send this computer\'s details"))', source)
        # What goes is shown before it goes.
        self.assertIn('preview = Gtk.Expander(label=_("See what will be sent"))', source)
        self.assertIn("with_logs=True))", source)


if __name__ == "__main__":
    unittest.main()

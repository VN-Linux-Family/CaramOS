"""Driver Check and Canon CAPT printers (LBP2900 and family), which need a CAPT driver."""

from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

PACKAGE = Path(__file__).parents[1]
# Driver Check lives in /usr/share/caramos-ota/driver-check, outside dist-packages.
sys.path.insert(0, str(PACKAGE / "usr/share/caramos-ota/driver-check"))

from caramos_driver_check import app, knowledge, logs, notify, printers
from caramos_driver_check import state as user_state
from caramos_driver_check.analysis import INSTALL, OK, REPORT, WARNING, analyze
from caramos_driver_check.drivers import DriverProposal, one_click
from caramos_driver_check.hardware import Device, Snapshot, SystemReader, UsbInterface

UDEV_RULE = PACKAGE / "usr/lib/udev/rules.d/71-caramos-capt-printers.rules"
HOTPLUG_UNIT = PACKAGE / "usr/lib/systemd/user/caramos-driver-check-hotplug.service"
# usblp takes the printer interface of a CAPT printer like any printer's.
LBP2900 = Device("usb", "1-1", "04a9", "2676", "Canon LBP2900", vendor_name="Canon",
                 interfaces=(UsbInterface("1.0", "07", "01", "02", "usblp",
                                          "usb:v04A9p2676d0100dc00dsc00dp00ic07isc01ip02in00"),))
LBP6000 = replace(LBP2900, product="271a", name="Canon LBP6000")
LBP3300 = replace(LBP2900, product="267e", name="Canon LBP3300")
HP_PRINTER = Device("usb", "1-2", "03f0", "042a", "HP LaserJet 1020",
                    interfaces=(UsbInterface("1.0", "07", "01", "02", "usblp"),))


def machine(*usb: Device, **changes) -> Snapshot:
    return replace(Snapshot(usb=usb, connected=True, kernel="6.14.0-37-generic"), **changes)


def printer_findings(report):
    return [finding for finding in report.findings if finding.area == "printer"]


class CaptPrinterTests(unittest.TestCase):
    def test_lbp2900_without_a_driver_offers_captdriver(self) -> None:
        report = analyze(machine(LBP2900))

        [finding] = report.findings
        self.assertEqual(("printer", WARNING, "printer:capt:usb:04a9:2676"), (finding.area, finding.level, finding.key))
        self.assertEqual("Canon LBP2900", finding.device)
        self.assertEqual("USB 04a9:2676", finding.device_id)
        self.assertEqual([INSTALL, REPORT], [action.kind for action in finding.actions])
        self.assertEqual("printer-driver-captdriver", finding.install.target)
        self.assertNotIn("experimental", finding.detail)
        self.assertEqual((finding.install,), report.installs)
        self.assertEqual(WARNING, {area.key: area.level for area in report.areas}["printer"])

    def test_with_captdriver_installed_the_printer_is_fine(self) -> None:
        report = analyze(machine(LBP2900, capt_drivers=("captdriver",)))

        self.assertEqual([], printer_findings(report))
        self.assertEqual(("printer", OK, "Canon LBP2900"),
                         next((a.key, a.level, a.summary) for a in report.areas if a.key == "printer"))

    def test_canon_driver_covers_every_model(self) -> None:
        report = analyze(machine(LBP2900, LBP3300, capt_drivers=("canon",)))
        self.assertEqual([], printer_findings(report))

    def test_experimental_models_say_so(self) -> None:
        [finding] = analyze(machine(LBP6000)).findings
        self.assertIn("experimental", finding.detail)
        self.assertEqual("printer-driver-captdriver", finding.install.target)

    def test_models_only_canons_driver_supports_get_no_install(self) -> None:
        report = analyze(machine(LBP3300, capt_drivers=("captdriver",)))

        [finding] = report.findings
        self.assertEqual(WARNING, finding.level)
        self.assertEqual([REPORT], [action.kind for action in finding.actions])
        self.assertEqual((), report.installs)

    def test_other_printers_and_a_blacklisted_usblp_are_not_reported_as_other_devices(self) -> None:
        # Guides for Canon's driver blacklist usblp: the printer interface then has no driver.
        unbound = replace(LBP2900, interfaces=(replace(LBP2900.interfaces[0], driver=""),))
        report = analyze(machine(unbound, HP_PRINTER))

        self.assertEqual(["printer:capt:usb:04a9:2676"], [finding.key for finding in report.findings])
        self.assertEqual("Canon LBP2900", next(a.summary for a in report.areas if a.key == "printer"))

    def test_the_ubuntu_drivers_proposal_is_not_offered_twice(self) -> None:
        proposal = DriverProposal("printer-driver-captdriver", "printer-driver-captdriver", "1-1", "Canon", "LBP2900")
        report = analyze(machine(LBP2900), proposals=[proposal])
        self.assertEqual(["printer:capt:usb:04a9:2676"], [finding.key for finding in report.findings])

    def test_no_printer_no_printer_area(self) -> None:
        self.assertNotIn("printer", [area.key for area in analyze(machine()).areas])

    def test_the_helper_installs_captdriver_with_one_click(self) -> None:
        self.assertTrue(one_click(knowledge.CAPTDRIVER_PACKAGE))


class CaptKnowledgeTests(unittest.TestCase):
    def test_capt_printers(self) -> None:
        self.assertTrue(knowledge.capt_printer(LBP2900))
        self.assertFalse(knowledge.capt_printer(HP_PRINTER))
        self.assertFalse(knowledge.capt_printer(replace(LBP2900, product="1234")))
        self.assertTrue(set(knowledge.CAPTDRIVER_MODELS) <= set(knowledge.CAPT_PRINTERS))
        self.assertTrue(knowledge.CAPTDRIVER_WORKS <= set(knowledge.CAPTDRIVER_MODELS))

    def test_the_udev_rule_lists_the_same_printers(self) -> None:
        rule = UDEV_RULE.read_text(encoding="utf-8")
        captdriver, every = re.findall(r'ATTR\{idProduct\}=="([0-9a-f|]+)"', rule)
        self.assertEqual(set(knowledge.CAPTDRIVER_MODELS), set(captdriver.split("|")))
        self.assertEqual(set(knowledge.CAPT_PRINTERS), set(every.split("|")))

    def test_installed_drivers_are_read_from_their_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            reader = SystemReader(temp)
            self.assertEqual((), reader.capt_drivers())
            filter_path = Path(temp) / "usr/lib/cups/filter/rastertocapt"
            filter_path.parent.mkdir(parents=True)
            filter_path.write_text("", encoding="utf-8")
            self.assertEqual(("captdriver",), reader.capt_drivers())
            daemon = Path(temp) / "usr/sbin/ccpd"
            daemon.parent.mkdir(parents=True)
            daemon.write_text("", encoding="utf-8")
            self.assertEqual(("captdriver", "canon"), reader.capt_drivers())


class FakeScanner:
    def __init__(self, snapshot: Snapshot) -> None:
        self._snapshot = snapshot

    def snapshot(self) -> Snapshot:
        return self._snapshot

    def analyze(self, snapshot: Snapshot, proposals):
        return analyze(snapshot, proposals=proposals)


class PluggedInTests(unittest.TestCase):
    """caramos-driver-check --hotplug: the udev rule has the user's systemd start it when the printer comes."""

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "caramos-driver-check/state.json"
        user_state.save(self.path, user_state.UserState(first_check_done=True))   # logged in, told everything

    def check(self, snapshot: Snapshot, hotplug: bool) -> mock.MagicMock:
        with mock.patch.object(app, "make_scanner", return_value=FakeScanner(snapshot)), \
                mock.patch.object(user_state, "state_path", return_value=self.path), \
                mock.patch.object(app, "open_window", side_effect=AssertionError("no window for a warning")), \
                mock.patch.object(notify, "show", return_value=0) as show:
            self.assertEqual(0, app.autostart(hotplug=hotplug))
        return show

    def test_plugging_the_printer_in_tells_at_once_and_only_once(self) -> None:
        show = self.check(machine(LBP2900), hotplug=True)

        show.assert_called_once()
        self.assertEqual("The printer has no driver", show.call_args.args[0])
        self.assertEqual({"printer:capt:usb:04a9:2676"}, user_state.load(self.path).seen)
        self.check(machine(LBP2900), hotplug=True).assert_not_called()
        self.check(machine(LBP2900), hotplug=False).assert_not_called()   # the next login

    def test_unplugging_it_is_not_a_solved_problem(self) -> None:
        self.check(machine(LBP2900), hotplug=True)

        self.check(machine(), hotplug=False).assert_not_called()   # logged in without the printer
        self.assertEqual({"printer:capt:usb:04a9:2676"}, user_state.load(self.path).seen)
        self.check(machine(LBP2900), hotplug=True).assert_not_called()   # back at the office

    def test_the_driver_installed_is_told_by_the_login_check_not_by_a_plug_in(self) -> None:
        self.check(machine(LBP2900), hotplug=True)

        self.check(machine(LBP2900, capt_drivers=("captdriver",)), hotplug=True).assert_not_called()
        self.assertEqual({"printer:capt:usb:04a9:2676"}, user_state.load(self.path).seen)
        show = self.check(machine(LBP2900, capt_drivers=("captdriver",)), hotplug=False)
        self.assertEqual("Hardware problem solved", show.call_args.args[0])
        self.assertEqual(set(), user_state.load(self.path).seen)

    def test_the_command(self) -> None:
        with mock.patch.object(app, "has_display", return_value=True), \
                mock.patch.object(app, "autostart", return_value=0) as run:
            self.assertEqual(0, app.main(["--hotplug"]))
        run.assert_called_once_with(hotplug=True)
        with mock.patch.object(app, "has_display", return_value=False), \
                mock.patch.object(app, "autostart") as run:
            self.assertEqual(0, app.main(["--hotplug"]))
        run.assert_not_called()

    def test_the_button_opens_the_app_outside_the_short_lived_service(self) -> None:
        with mock.patch.dict(os.environ, {"INVOCATION_ID": "0123abcd"}), \
                mock.patch.object(notify.subprocess, "Popen") as popen:
            notify._start([notify.COMMAND])
        self.assertEqual(["systemd-run", "--user", "--scope", "--quiet", "--collect", "--", notify.COMMAND],
                         popen.call_args.args[0])
        environment = {key: value for key, value in os.environ.items() if key != "INVOCATION_ID"}
        with mock.patch.dict(os.environ, environment, clear=True), \
                mock.patch.object(notify.subprocess, "Popen") as popen:
            notify._start([notify.COMMAND])   # at login: Cinnamon started the check
        self.assertEqual([notify.COMMAND], popen.call_args.args[0])

    def test_the_udev_rule_starts_the_check_only_for_printers_without_a_driver(self) -> None:
        rule = UDEV_RULE.read_text(encoding="utf-8")
        wants = 'TAG+="systemd", ENV{SYSTEMD_USER_WANTS}+="caramos-driver-check-hotplug.service"'
        self.assertEqual(1, rule.count(wants))
        self.assertGreater(rule.index(wants), rule.index("/usr/lib/cups/filter/rastertocapt"))
        self.assertGreater(rule.index(wants), rule.index("/usr/sbin/ccpd"))
        self.assertLess(rule.index(wants), rule.index('LABEL="caramos_capt_end"'))

    def test_the_user_unit(self) -> None:
        unit = HOTPLUG_UNIT.read_text(encoding="utf-8")
        self.assertIn("\nExecStart=/usr/bin/caramos-driver-check --hotplug\n", unit)
        self.assertIn("\nConditionEnvironment=|DISPLAY\n", unit)
        self.assertNotIn("[Install]", unit)   # udev asks for it; nothing enables it
        self.assertIn("usr/lib/systemd/user/caramos-driver-check-hotplug.service usr/lib/systemd/user/\n",
                      (PACKAGE / "debian/install").read_text(encoding="utf-8"))


ERROR_LOG = """E [09/Nov/2026:11:30:02 +0700] [Job 3] CAPT: unable to communicate with printer
D [09/Nov/2026:11:22:57 +0700] [Job 1] argv[3]="Hop dong Cong ty ABC"
D [09/Nov/2026:11:22:57 +0700] [Job 1] envp[21]="DEVICE_URI=usb://Canon/LBP2900?serial=0000A1B2C3D4"
D [09/Nov/2026:11:22:57 +0700] [Job 1] job-name (nameWithoutLanguage) = "Bang luong thang 11"
D [09/Nov/2026:11:23:07 +0700] [Client 6] Writing IPP response, ipp_state=IPP_STATE_DATA
D [09/Nov/2026:11:23:07 +0700] cupsdSetBusyState: newbusy="Printing jobs", busy="Active clients"
"""
COMMANDS = {
    ("lpstat", "-v"): "device for LBP2900: usb://Canon/LBP2900?serial=0000A1B2C3D4\n"
                      "device for Ke_toan: ipp://192.168.1.20/ipp/print\n",
    ("lpoptions", "-p", "LBP2900"): "copies=1 device-uri=usb://Canon/LBP2900?serial=0000A1B2C3D4 "
                                    "printer-make-and-model='Canon LBP2900/LBP3000 r2c, 0.1.4' printer-state=5 "
                                    "printer-state-reasons=paused printer-is-accepting-jobs=true\n",
    ("lpstat", "-p", "LBP2900"): "printer LBP2900 disabled since Mon Nov  9 11:31:00 2026 -\n\tRendering completed\n",
    ("lpstat", "-W", "not-completed", "-o", "LBP2900"): "LBP2900-3  someone  1024  Mon Nov  9 11:30:00 2026\n",
    ("lpstat", "-W", "completed", "-o", "LBP2900"): "".join(f"LBP2900-{n}  someone  1024  Mon Nov  9 2026\n"
                                                           for n in range(1, 3)),
    "dpkg-query": "cups-daemon 2.4.7-1.2ubuntu7.14 ii \nprinter-driver-captdriver 0.2.1~git20260813.f2d2da8-0caramos1 ii \n",
    "journalctl": "2026-11-09T11:22:20+07:00 pc udev-configure-printer[812]: MFG:Canon MDL:LBP2900 SERN:- "
                  "serial:0000A1B2C3D4\n"
                  "2026-11-09T11:22:21+07:00 pc udev-configure-printer[812]: PPD: lsb/usr/captdriver/CanonLBP-2900-3000.ppd; "
                  "Status: 0\n",
}


def fake_runner(arguments) -> str:
    arguments = tuple(arguments)
    return COMMANDS.get(arguments[0]) if arguments[0] in ("dpkg-query", "journalctl") else COMMANDS.get(arguments, "")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class PrinterLogTests(unittest.TestCase):
    """printer.log goes with every help request when there is a printer: CUPS logs nothing to the journal."""

    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        usb = self.root / "sys/bus/usb/devices"
        for name, value in (("idVendor", "04a9"), ("idProduct", "2676"), ("manufacturer", "Canon"), ("product", "LBP2900")):
            write(usb / "3-1" / name, value + "\n")
        for name, value in (("bInterfaceClass", "07"), ("bInterfaceSubClass", "01"), ("bInterfaceProtocol", "02"),
                            ("ieee1284_id", "MFG:Canon;MDL:LBP2900;CMD:CAPT;VER:2.1;CLS:PRINTER;DES:Canon LBP2900;SN:XYZ123;")):
            write(usb / "3-1:1.0" / name, value)
        os.symlink("../../../../bus/usb/drivers/usblp", usb / "3-1:1.0/driver")
        write(usb / "1-1:1.0/bInterfaceClass", "03")   # a keyboard
        write(self.root / "usr/lib/cups/filter/rastertocapt", "")
        write(self.root / printers.ERROR_LOG, ERROR_LOG)

    def test_what_the_team_needs_to_see(self) -> None:
        text = printers.printer_log(self.root, fake_runner)

        for expected in (
            "printer-driver-captdriver 0.2.1~git20260813.f2d2da8-0caramos1 ii",
            "Canon CAPT drivers installed: captdriver",
            "3-1:1.0: USB 04a9:2676 Canon LBP2900 · 7/1/2 · driver usblp",
            "IEEE 1284 id: MFG:Canon;MDL:LBP2900;CMD:CAPT;VER:2.1;CLS:PRINTER;DES:Canon LBP2900;SN:[REDACTED];",
            "Canon CAPT printer (LBP2900/LBP2900B): captdriver drives it",
            "LBP2900: Canon LBP2900/LBP3000 r2c, 0.1.4 · usb://Canon/LBP2900?serial=[REDACTED]",
            "state stopped, reasons paused, accepting jobs true",
            "Rendering completed",
            "jobs not done: 1",
            "LBP2900-3",
            "last jobs done: 2",
            "PPD: lsb/usr/captdriver/CanonLBP-2900-3000.ppd; Status: 0",
            "1 other queue(s)",
            "CAPT: unable to communicate with printer",
        ):
            self.assertIn(expected, text)
        self.assertNotIn("1-1:1.0", text)
        self.assertNotIn("[Client 6]", text)   # debug chatter of cupsd with its clients
        self.assertNotIn("cupsdSetBusyState", text)

    def test_no_serial_numbers_document_names_or_office_printers(self) -> None:
        text = printers.printer_log(self.root, fake_runner)

        for secret in ("0000A1B2C3D4", "XYZ123", "Hop dong", "Bang luong", "192.168.1.20", "Ke_toan"):
            self.assertNotIn(secret, text)
        self.assertIn('argv[3]="[REDACTED_TITLE]"', text)
        self.assertIn("serial:[REDACTED]", text)

    def test_no_printer_no_log(self) -> None:
        self.assertEqual("", printers.printer_log(Path(tempfile.gettempdir()) / "no-such-root", lambda arguments: ""))
        # A print queue alone (a network printer) is enough.
        self.assertIn("1 other queue(s)", printers.printer_log(
            self.root / "nothing", lambda arguments: "device for X: ipp://10.0.0.5/ipp\n" if arguments[:2] == ["lpstat", "-v"] else ""))

    @unittest.skipIf(os.geteuid() == 0, "root reads every file")
    def test_an_error_log_the_user_may_not_read(self) -> None:
        (self.root / printers.ERROR_LOG).chmod(0)
        self.addCleanup((self.root / printers.ERROR_LOG).chmod, 0o644)
        self.assertIn("(not readable: only root and the adm group may read it)",
                      printers.printer_log(self.root, fake_runner))

    def test_help_requests_carry_it(self) -> None:
        with mock.patch.object(logs, "system_log", return_value="system"), \
                mock.patch.object(logs, "driver_check_log_path", return_value=self.root / "none.log"), \
                mock.patch.object(printers, "printer_log", return_value="printer report\n"):
            self.assertEqual(["system.log", "printer.log"], [log.name for log in logs.system_logs()])
        with mock.patch.object(logs, "system_log", return_value="system"), \
                mock.patch.object(logs, "driver_check_log_path", return_value=self.root / "none.log"), \
                mock.patch.object(printers, "printer_log", side_effect=OSError("broken")):
            self.assertEqual(["system.log"], [log.name for log in logs.system_logs()])

    def test_a_failed_install_carries_what_the_helper_printed(self) -> None:
        home = os.path.realpath(os.path.expanduser("~"))
        log = logs.install_failure_log(["printer-driver-captdriver"], "apt",
                                       f"E: Unable to locate package printer-driver-captdriver\nsee {home}/x.log")
        self.assertEqual("driver-install.log", log.name)
        self.assertTrue(log.text.startswith("Driver Check could not install printer-driver-captdriver (error: apt)"))
        self.assertIn("E: Unable to locate package printer-driver-captdriver", log.text)
        self.assertNotIn(home, log.text)


if __name__ == "__main__":
    unittest.main()

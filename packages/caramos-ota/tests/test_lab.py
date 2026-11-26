"""Phòng máy (computer lab): pairing over the LAN, the root helper's Veyon and Epoptes setup, a student's account that
stays awake for Veyon, the Veyon Server check, the packaging."""

from __future__ import annotations

import configparser
import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
LAB = ROOT / "usr/share/caramos-ota/lab"
sys.path.insert(0, str(LAB))

from caramos_lab import EPOPTES, STUDENT, TEACHER, VEYON, awake, helper, pairing, system, watchdog  # noqa: E402
from caramos_ota.i18n import _  # noqa: E402

KEY = b"-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAtest\n-----END PUBLIC KEY-----\n"


class CodeTests(unittest.TestCase):
    def test_code_is_six_digits_of_the_key(self) -> None:
        code = pairing.pairing_code(KEY)
        self.assertRegex(code, r"^\d{6}$")
        self.assertEqual(code, pairing.pairing_code(KEY))
        self.assertNotEqual(code, pairing.pairing_code(KEY + b"\n"))
        self.assertEqual(f"{code[:3]} {code[3:]}", pairing.spaced(code))
        self.assertTrue(pairing.check_code(KEY, pairing.spaced(code)))
        self.assertFalse(pairing.check_code(KEY, "000000" if code != "000000" else "111111"))

    def test_validators(self) -> None:
        self.assertTrue(pairing.valid_hostname("may-hs-01"))
        self.assertFalse(pairing.valid_hostname("máy 1"))
        self.assertFalse(pairing.valid_hostname("-x"))
        self.assertTrue(pairing.valid_ip("192.168.1.20"))
        self.assertTrue(pairing.valid_ip("10.0.0.5"))
        self.assertFalse(pairing.valid_ip("8.8.8.8"), "only addresses of the school network")
        self.assertFalse(pairing.valid_ip("192.168.1.300"))
        self.assertTrue(pairing.valid_mac("52:54:00:12:34:56"))
        self.assertFalse(pairing.valid_mac("00:00:00:00:00:00"))
        self.assertFalse(pairing.valid_mac("52:54:00:12:34"))
        self.assertTrue(pairing.valid_room("Phòng máy 1"))
        self.assertTrue(pairing.valid_room("Lab-A"))
        self.assertFalse(pairing.valid_room(" Phòng"))
        self.assertFalse(pairing.valid_room("a;rm -rf /"))
        self.assertFalse(pairing.valid_room("x" * 41))

    def test_announcement_round_trip_and_bad_ones(self) -> None:
        teacher = pairing.parse_announcement(pairing.announcement("maygv", "Phòng máy 1", VEYON, 47012), "192.168.1.2")
        self.assertEqual(pairing.Teacher("192.168.1.2", "maygv", "Phòng máy 1", VEYON, 47012), teacher)
        self.assertIsNone(pairing.parse_announcement(pairing.announcement("maygv", "P", "nc", 47012), "192.168.1.2"))
        self.assertIsNone(pairing.parse_announcement(pairing.announcement("maygv", "P", VEYON, 80), "192.168.1.2"))
        self.assertIsNone(pairing.parse_announcement(pairing.announcement("maygv", "P", VEYON), "8.8.8.8"))
        self.assertIsNone(pairing.parse_announcement(b"not json", "192.168.1.2"))
        self.assertIsNone(pairing.parse_announcement(pairing.discovery_request(), "192.168.1.2"))

    def test_registration_is_checked(self) -> None:
        good = {"name": "may-hs-01", "ip": "192.168.1.20", "mac": "52:54:00:AA:bb:01"}
        self.assertEqual(pairing.Student("may-hs-01", "192.168.1.20", "52:54:00:aa:bb:01"),
                         pairing.parse_registration(json.dumps(good).encode()))
        for bad in ({**good, "name": "x; reboot"}, {**good, "ip": "1.1.1.1"}, {**good, "mac": "zz"}, [good], "x"):
            with self.assertRaises(pairing.PairingError):
                pairing.parse_registration(json.dumps(bad).encode())


class LanTests(unittest.TestCase):
    """The teacher's server and the student's side talking over the loopback network."""

    def test_discover_download_and_register(self) -> None:
        registered: list[pairing.Student] = []
        server = pairing.TeacherServer("maygv", "Phòng máy 1", VEYON, KEY, registered.append, udp_port=0,
                                       http_port=0, bind="127.0.0.1").start()
        self.addCleanup(server.stop)
        teachers = pairing.discover(timeout=1.0, port=server.udp_port, targets=["127.0.0.1"])
        self.assertEqual([pairing.Teacher("127.0.0.1", "maygv", "Phòng máy 1", VEYON, server.http_port)], teachers)
        key = pairing.fetch_key(teachers[0])
        self.assertEqual(KEY, key)
        self.assertTrue(pairing.check_code(key, server.code))
        pairing.register(teachers[0], pairing.Student("may-hs-01", "127.0.0.1", "52:54:00:12:34:56"))
        self.assertEqual([pairing.Student("may-hs-01", "127.0.0.1", "52:54:00:12:34:56")], registered)
        with self.assertRaises(pairing.PairingError, msg="an address that is not the sender's"):
            pairing.register(teachers[0], pairing.Student("may-hs-02", "192.168.1.9", "52:54:00:12:34:57"))
        self.assertEqual(1, len(registered))

    def test_nobody_answers_when_no_pairing_page_is_open(self) -> None:
        self.assertEqual([], pairing.discover(timeout=0.5, port=1, targets=["127.0.0.1"]))


class FakeVeyon:
    """veyon-cli with an in-memory builtin directory."""

    def __init__(self) -> None:
        self.objects: list[dict] = []
        self.calls: list[list[str]] = []
        self.config: dict[str, str] = {}

    def __call__(self, command, check=True, quiet=False, env=None, stdin=None):
        self.calls.append(list(command))
        out = "[OK]"
        if command[0] == "veyon-cli":
            args = command[1:]
            if args[:2] == ["config", "get"] and args[2] == "BuiltinDirectory/NetworkObjects":
                if not self.objects:  # like Veyon: no key until the first room is added
                    return subprocess.CompletedProcess(command, 1, "[ERROR] Specified key does not exist in "
                                                       "current configuration!", "")
                out = json.dumps(self.objects)
            elif args[:2] == ["config", "set"]:
                self.config[args[2]] = args[3]
            elif args[:3] == ["networkobjects", "add", "location"]:
                self.objects.append({"Type": 2, "Name": args[3], "Uid": "{room-%d}" % len(self.objects)})
            elif args[:3] == ["networkobjects", "add", "computer"]:
                parent = next(item["Uid"] for item in self.objects if item["Type"] == 2 and item["Name"] == args[6])
                self.objects.append({"Type": 3, "Name": args[3], "HostAddress": args[4], "MacAddress": args[5],
                                     "ParentUid": parent, "Uid": "{pc-%d}" % len(self.objects)})
            elif args[:2] == ["networkobjects", "remove"]:
                self.objects = [item for item in self.objects if item["Uid"].strip("{}") != args[2]]
        return subprocess.CompletedProcess(command, 0, out, "")


class HelperTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.fake = FakeVeyon()
        self.events: list[dict] = []
        public = self.root / "public.key"
        public.write_bytes(KEY)
        cert = self.root / "server.crt"
        cert.write_bytes(KEY.replace(b"PUBLIC KEY", b"CERTIFICATE"))
        patches = [
            mock.patch.object(helper, "run", self.fake),
            mock.patch.object(helper, "emit", lambda event, **fields: self.events.append({"event": event, **fields})),
            mock.patch.object(helper, "apt_install", lambda packages: self.fake.calls.append(["apt", *packages])),
            mock.patch.object(helper, "STATE_FILE", self.root / "state.json"),
            mock.patch.object(helper, "LAB_OVERRIDE", self.root / "schemas/70_caramos-lab.gschema.override"),
            mock.patch.object(helper, "EPOPTES_DEFAULT", self.root / "epoptes-client"),
            mock.patch.object(helper, "PRIVATE_KEY", self.root / "private.key"),
            mock.patch.object(system, "VEYON_PUBLIC_KEY", public),
            mock.patch.object(system, "EPOPTES_CERT", cert),
            mock.patch.object(system, "login_user", lambda: "cogiao"),
            mock.patch.object(system, "primary_group", lambda user: user),
            mock.patch.object(system, "hostname", lambda: "maygv"),
            mock.patch.object(system, "local_ip", lambda *a: "192.168.1.2"),
            mock.patch.object(system, "mac_of", lambda ip, links=None: "52:54:00:00:00:02"),
        ]
        (self.root / "schemas").mkdir()
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def veyon_calls(self) -> list[list[str]]:
        return [call[1:] for call in self.fake.calls if call[0] == "veyon-cli"]

    def test_veyon_teacher(self) -> None:
        helper.teacher(VEYON, "Phòng máy 1")
        calls = self.veyon_calls()
        self.assertIn(["authkeys", "create", "giaovien"], calls)
        self.assertIn(["authkeys", "setaccessgroup", "giaovien/private", "cogiao"], calls)
        self.assertEqual("1", self.fake.config["Authentication/Method"])
        self.assertEqual("true", self.fake.config["Master/AutoSelectCurrentLocation"])
        self.assertIn(["apt", *helper.PACKAGES[(VEYON, TEACHER)]], self.fake.calls)
        self.assertIn("libqca-qt5-2-plugins", helper.PACKAGES[(VEYON, TEACHER)], "Veyon needs RSA")
        self.assertIn(["systemctl", "enable", "--now", "veyon.service"], self.fake.calls)
        self.assertIn(["systemctl", "enable", "--now", "caramos-lab-veyon-check.timer"], self.fake.calls,
                      "Veyon Server comes back by itself on the teacher's computer too (Demo needs it)")
        names = [(item["Type"], item["Name"], item.get("HostAddress")) for item in self.fake.objects]
        self.assertEqual([(2, "Phòng máy 1", None), (3, "maygv", "maygv")], names,
                         "the room, with the teacher's computer in it by name")
        state = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        self.assertEqual({"role": TEACHER, "backend": VEYON, "room": "Phòng máy 1", "user": "cogiao",
                          "code": pairing.pairing_code(KEY)}, {k: v for k, v in state.items() if k != "updated"})
        self.assertIn("side-pane-view='tree'", (self.root / "schemas/70_caramos-lab.gschema.override").read_text())
        self.assertEqual("done", self.events[-1]["event"])

    def test_add_computers_replaces_a_computer_whose_address_changed(self) -> None:
        helper.ensure_room("Phòng máy 1")
        lines = [json.dumps({"name": "may-hs-01", "ip": "192.168.1.20", "mac": "52:54:00:00:00:20"}),
                 json.dumps({"name": "may-hs-01", "ip": "192.168.1.21", "mac": "52:54:00:00:00:20"}),
                 '{"name": "bad;name", "ip": "192.168.1.22", "mac": "52:54:00:00:00:22"}', ""]
        helper.add_computers("Phòng máy 1", iter(lines))
        computers = [(item["Name"], item["HostAddress"]) for item in self.fake.objects if item["Type"] == 3]
        self.assertEqual([("may-hs-01", "192.168.1.21")], computers)
        self.assertEqual(["added", "added", "error"], [event["event"] for event in self.events])

    def test_cloned_computers_with_one_name_all_stay(self) -> None:
        helper.ensure_room("Phòng máy 1")
        lines = [json.dumps({"name": "caramos", "ip": f"192.168.1.{n}", "mac": f"52:54:00:00:00:{n}"}) for n in (31, 32)]
        helper.add_computers("Phòng máy 1", iter(lines))
        self.assertEqual(["192.168.1.31", "192.168.1.32"],
                         [item["HostAddress"] for item in self.fake.objects if item["Type"] == 3])

    def test_veyon_student(self) -> None:
        key = self.root / "teacher.pem"
        key.write_bytes(KEY)
        helper.student(VEYON, "Phòng máy 1", "192.168.1.2", "maygv", key)
        calls = self.veyon_calls()
        self.assertIn(["authkeys", "import", "giaovien/public", str(key)], calls)
        self.assertLess(calls.index(["authkeys", "delete", "giaovien/public"]),
                        calls.index(["authkeys", "import", "giaovien/public", str(key)]))
        self.assertIn(["apt", "veyon-service", "libqca-qt5-2-plugins"], self.fake.calls)
        self.assertIn(["systemctl", "enable", "--now", "caramos-lab-veyon-check.timer"], self.fake.calls)
        state = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        self.assertEqual({"host": "192.168.1.2", "name": "maygv"}, state["teacher"])
        self.assertEqual(STUDENT, state["role"])

    def test_epoptes_teacher_gets_distutils_for_its_window(self) -> None:
        helper.teacher(EPOPTES, "Phòng máy 2")
        self.assertIn(["apt", "epoptes", "python3-setuptools"], self.fake.calls)
        self.assertIn(["gpasswd", "-a", "cogiao", "epoptes"], self.fake.calls)

    def test_epoptes_student_points_the_client_at_the_teacher(self) -> None:
        cert = self.root / "teacher.crt"
        cert.write_bytes(KEY.replace(b"PUBLIC KEY", b"CERTIFICATE"))
        with mock.patch.object(system, "EPOPTES_CERT", self.root / "etc-epoptes/server.crt"):
            helper.student(EPOPTES, "Phòng máy 1", "192.168.1.2", "maygv", cert)
            self.assertEqual(cert.read_bytes(), (self.root / "etc-epoptes/server.crt").read_bytes())
        self.assertIn("SERVER=192.168.1.2", (self.root / "epoptes-client").read_text(encoding="utf-8"))
        self.assertIn(["apt", "epoptes-client"], self.fake.calls)

    def test_student_refuses_a_file_that_is_not_a_key(self) -> None:
        bad = self.root / "bad.pem"
        bad.write_text("hello", encoding="utf-8")
        with self.assertRaises(helper.HelperError):
            helper.student(VEYON, "Phòng máy 1", "192.168.1.2", "maygv", bad)

    def test_leave_undoes_the_setup(self) -> None:
        helper.teacher(VEYON, "Phòng máy 1")
        helper.leave()
        self.assertFalse((self.root / "state.json").exists())
        self.assertFalse((self.root / "schemas/70_caramos-lab.gschema.override").exists())
        self.assertEqual("0", self.fake.config["Authentication/Method"])
        self.assertIn(["systemctl", "disable", "--now", "veyon.service"], self.fake.calls)
        self.assertIn(["systemctl", "disable", "--now", "caramos-lab-veyon-check.timer"], self.fake.calls)
        last_config = max(index for index, call in enumerate(self.fake.calls) if call[:2] == ["veyon-cli", "config"])
        self.assertGreater(self.fake.calls.index(["systemctl", "disable", "--now", "veyon.service"]), last_config,
                           "veyon-cli enables veyon.service again when it saves its configuration")

    def test_epoptes_has_no_veyon_check(self) -> None:
        helper.teacher(EPOPTES, "Phòng máy 2")
        self.assertNotIn("caramos-lab-veyon-check.timer", [call[-1] for call in self.fake.calls])

    def test_main_checks_root_and_arguments(self) -> None:
        with mock.patch.object(helper.os, "geteuid", lambda: 1000):
            self.assertEqual(2, helper.main(["leave"]))
        with mock.patch.object(helper.os, "geteuid", lambda: 0):
            self.assertEqual(1, helper.main(["teacher", "--backend", VEYON, "--room", "x;y"]))
            self.assertEqual(1, helper.main(["student", "--backend", VEYON, "--room", "P", "--teacher-host",
                                             "8.8.8.8", "--teacher-name", "maygv", "--key", "/dev/null"]))

class FakeDesktop:
    """gsettings, dconf and xfconf-query of one account: schemas with defaults, the account's own values."""

    def __init__(self, gsettings: dict[tuple[str, str], str], xfconf: dict[str, str] | None = None,
                 broken: tuple[str, ...] = ()) -> None:
        self.defaults = dict(gsettings)
        self.user: dict[tuple[str, str], str] = {}
        self.xfconf = xfconf  # None: no xfconf on this computer
        self.broken = broken  # commands that fail (no session bus)
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(list(command))
        ok = lambda out="": subprocess.CompletedProcess(command, 0, out, "")  # noqa: E731
        fail = subprocess.CompletedProcess(command, 1, "", "error")
        if command[0] in self.broken:
            return fail
        if command[0] == "gsettings":
            action, schema, key = command[1:4]
            if (schema, key) not in self.defaults:
                return fail
            if action == "get":
                return ok(self.user.get((schema, key), self.defaults[(schema, key)]) + "\n")
            if action == "set":
                self.user[(schema, key)] = command[4]
            elif action == "reset":
                self.user.pop((schema, key), None)
            return ok()
        if command[0] == "dconf":
            for (schema, key), value in self.user.items():
                if command[2] == "/" + schema.replace(".", "/") + "/" + key:
                    return ok(value + "\n")
            return ok()
        if command[0] == "xfconf-query":
            if self.xfconf is None:
                return subprocess.CompletedProcess(command, 127, "", "not installed")
            if command[3] == "-l":
                return ok("\n".join(self.xfconf))
            prop = command[4]
            if "-s" in command:
                self.xfconf[prop] = command[command.index("-s") + 1]
                return ok()
            if "-r" in command:
                self.xfconf.pop(prop, None)
                return ok()
            return ok(self.xfconf[prop] + "\n") if prop in self.xfconf else fail
        raise AssertionError(f"unexpected command {command}")


CINNAMON_DEFAULTS = {(s.schema, s.key): v for s, v in zip(awake.CINNAMON_SETTINGS, (
    "uint32 900", "true", "true", "1800", "1800", "0", "900"))}
LIGHT_LOCKER_DEFAULTS = {("apps.light-locker", "lock-after-screensaver"): "uint32 5",
                         ("apps.light-locker", "lock-on-suspend"): "true",
                         ("apps.light-locker", "late-locking"): "false"}


class AwakeTests(unittest.TestCase):
    """A lab student's account: no screensaver, automatic lock, screen sleep or suspend; back as before after."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "state/caramos-lab/desktop-settings.json"

    def test_cinnamon_keeps_what_the_account_had_and_gives_it_back(self) -> None:
        desktop = FakeDesktop(CINNAMON_DEFAULTS)
        desktop.user[("org.cinnamon.desktop.screensaver", "lock-enabled")] = "false"  # its own choice already
        desktop.user[("org.cinnamon.settings-daemon.plugins.power", "sleep-display-ac")] = "600"
        changed = awake.apply(awake.CINNAMON, run=desktop, path=self.state)
        self.assertNotIn("gsettings org.cinnamon.desktop.screensaver lock-enabled", changed)
        for setting in awake.CINNAMON_SETTINGS:
            self.assertEqual(setting.value, desktop.user[(setting.schema, setting.key)], setting.name)
        saved = json.loads(self.state.read_text(encoding="utf-8"))["settings"]
        self.assertIsNone(saved["gsettings org.cinnamon.desktop.session idle-delay"], "no own value: default again")
        self.assertEqual("600", saved["gsettings org.cinnamon.settings-daemon.plugins.power sleep-display-ac"])

        restored = awake.restore(run=desktop, path=self.state)
        self.assertEqual(len(awake.CINNAMON_SETTINGS), len(restored))
        self.assertEqual({("org.cinnamon.desktop.screensaver", "lock-enabled"): "false",
                          ("org.cinnamon.settings-daemon.plugins.power", "sleep-display-ac"): "600"}, desktop.user)
        self.assertFalse(self.state.exists())

    def test_applying_again_keeps_the_values_from_before_the_lab(self) -> None:
        desktop = FakeDesktop(CINNAMON_DEFAULTS)
        awake.apply(awake.CINNAMON, run=desktop, path=self.state)
        desktop.user[("org.cinnamon.desktop.screensaver", "lock-enabled")] = "true"  # turned on again meanwhile
        changed = awake.apply(awake.CINNAMON, run=desktop, path=self.state)  # the next login
        self.assertEqual(["gsettings org.cinnamon.desktop.screensaver lock-enabled"], changed)
        self.assertEqual("false", desktop.user[("org.cinnamon.desktop.screensaver", "lock-enabled")])
        awake.restore(run=desktop, path=self.state)
        self.assertEqual({}, desktop.user, "back to the defaults the account had, not to the lab's values")

    def test_xfce_light_locker_and_power_manager(self) -> None:
        power = {"/xfce4-power-manager/power-button-action": "3", "/xfce4-power-manager/blank-on-ac": "10"}
        desktop = FakeDesktop(LIGHT_LOCKER_DEFAULTS, xfconf=dict(power))
        awake.apply(awake.XFCE, run=desktop, path=self.state)
        self.assertEqual("uint32 0", desktop.user[("apps.light-locker", "lock-after-screensaver")])
        self.assertEqual("false", desktop.user[("apps.light-locker", "lock-on-suspend")])
        self.assertEqual("0", desktop.xfconf["/xfce4-power-manager/blank-on-ac"])
        self.assertEqual("false", desktop.xfconf["/xfce4-power-manager/dpms-enabled"])
        self.assertEqual("14", desktop.xfconf["/xfce4-power-manager/inactivity-on-ac"], "14 minutes: never")
        new = [call for call in desktop.calls
               if call[0] == "xfconf-query" and "/xfce4-power-manager/dpms-enabled" in call and "-s" in call][0]
        self.assertEqual(["-n", "-t", "bool", "-s", "false"], new[-5:], "a property the account does not have yet")
        awake.restore(run=desktop, path=self.state)
        self.assertEqual(power, desktop.xfconf)
        self.assertEqual({}, desktop.user)

    def test_settings_this_computer_does_not_have_are_left_out(self) -> None:
        desktop = FakeDesktop({}, xfconf=None)  # light-locker removed, no xfconf
        self.assertEqual([], awake.apply(awake.XFCE, run=desktop, path=self.state))
        self.assertFalse(self.state.exists())
        self.assertEqual([], awake.apply("other", run=desktop, path=self.state))

    def test_what_could_not_be_given_back_is_tried_at_the_next_login(self) -> None:
        desktop = FakeDesktop(CINNAMON_DEFAULTS)
        awake.apply(awake.CINNAMON, run=desktop, path=self.state)
        desktop.broken = ("gsettings",)
        self.assertEqual([], awake.restore(run=desktop, path=self.state))
        self.assertTrue(self.state.exists())
        desktop.broken = ()
        self.assertEqual(len(awake.CINNAMON_SETTINGS), len(awake.restore(run=desktop, path=self.state)))
        self.assertFalse(self.state.exists())

    def test_at_login(self) -> None:
        desktop = FakeDesktop(CINNAMON_DEFAULTS)
        with mock.patch.object(awake, "current_desktop", lambda: awake.CINNAMON):
            self.assertTrue(awake.at_login(STUDENT, run=desktop, path=self.state).startswith("awake: "))
            self.assertTrue(self.state.exists())
            self.assertEqual("awake: nothing to change", awake.at_login(STUDENT, run=desktop, path=self.state))
            self.assertTrue(awake.at_login(TEACHER, run=desktop, path=self.state).startswith("restored: "))
            self.assertEqual("not a lab student", awake.at_login(None, run=desktop, path=self.state))

    def test_the_desktop_of_the_session(self) -> None:
        self.assertEqual(awake.CINNAMON, awake.current_desktop({"XDG_CURRENT_DESKTOP": "X-Cinnamon"}))
        self.assertEqual(awake.XFCE, awake.current_desktop({"XDG_CURRENT_DESKTOP": "XFCE"}))
        with mock.patch.dict(os.environ, {"CARAMOS_OTA_DESKTOP": "xfce"}):
            self.assertEqual(awake.XFCE, awake.current_desktop({}), "no session variable: the installed desktop")

    def test_the_state_lives_in_the_account(self) -> None:
        self.assertEqual(Path("/home/hs/.local/state/caramos-lab/desktop-settings.json"),
                         awake.state_path({"HOME": "/home/hs"}))
        self.assertEqual(Path("/x/caramos-lab/desktop-settings.json"), awake.state_path({"XDG_STATE_HOME": "/x"}))

    def test_window_and_login_use_it(self) -> None:
        app = (LAB / "caramos_lab/app.py").read_text(encoding="utf-8")
        self.assertIn("awake.apply()", app, "a student's computer stays awake once it is paired")
        self.assertIn("threading.Thread(target=awake.restore", app, "and gets its settings back when it leaves")
        from caramos_lab import app as lab_app
        with mock.patch.object(lab_app.awake, "at_login", return_value="awake: x") as at_login, \
                mock.patch.object(lab_app.system, "read_state", return_value={"role": STUDENT}), \
                mock.patch("builtins.print"):
            self.assertEqual(0, lab_app.main(["--session"]))
        at_login.assert_called_once_with(STUDENT)


class FakeSeat:
    """loginctl, ss and systemctl for the Veyon Server check; `listening` says per check whether 11100 answers."""

    def __init__(self, listening: list[bool], session_type: str = "x11", enabled: bool = True,
                 active_session: str = "c1") -> None:
        self.listening = list(listening)
        self.session_type = session_type
        self.enabled = enabled
        self.active_session = active_session
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str]) -> subprocess.CompletedProcess:
        self.calls.append(list(command))
        out = ""
        if command[:2] == ["loginctl", "show-seat"]:
            out = f"ActiveSession={self.active_session}\n"
        elif command[:2] == ["loginctl", "show-session"]:
            out = f"Type={self.session_type}\nState=active\n"
        elif command[0] == "ss":
            up = self.listening.pop(0) if len(self.listening) > 1 else self.listening[0]
            out = "LISTEN 0 50 *:11100 *:*\n" if up else ""
        elif command[:2] == ["systemctl", "is-enabled"]:
            out = "enabled\n" if self.enabled else "disabled\n"
        return subprocess.CompletedProcess(command, 0, out, "")


class WatchdogTests(unittest.TestCase):
    """caramos-lab-veyon-check: Veyon 4.7.5 did not start its server again; the timer does (a backstop for 4.11.5)."""

    VEYON_STUDENT = {"role": STUDENT, "backend": VEYON}

    def check(self, seat: FakeSeat, state: dict | None = None) -> tuple[str, list[float]]:
        slept: list[float] = []
        message = watchdog.check(self.VEYON_STUDENT if state is None else state, run=seat, sleep=slept.append)
        return message, slept

    def restarted(self, seat: FakeSeat) -> bool:
        return ["systemctl", "restart", "veyon.service"] in seat.calls

    def test_a_running_server_is_left_alone(self) -> None:
        seat = FakeSeat([True])
        message, slept = self.check(seat)
        self.assertIn("running for session c1", message)
        self.assertEqual([], slept)
        self.assertFalse(self.restarted(seat))

    def test_a_server_gone_for_a_while_is_started_again(self) -> None:
        seat = FakeSeat([False])
        message, slept = self.check(seat)
        self.assertTrue(message.startswith("restarted veyon.service"), message)
        self.assertTrue(self.restarted(seat))
        self.assertEqual(watchdog.SETTLE, sum(slept), "it waits while Veyon may still be switching sessions")

    def test_a_server_that_comes_back_on_its_own_is_not_restarted(self) -> None:
        seat = FakeSeat([False, False, True])
        message, slept = self.check(seat)
        self.assertIn("running", message)
        self.assertEqual(2 * watchdog.CHECK_INTERVAL, sum(slept))
        self.assertFalse(self.restarted(seat))

    def test_nothing_to_serve_or_not_ours(self) -> None:
        for seat, state, expected in (
                (FakeSeat([False], active_session=""), None, "no graphical session"),
                (FakeSeat([False], session_type="tty"), None, "no graphical session"),
                (FakeSeat([False], enabled=False), None, "not enabled"),
                (FakeSeat([False]), {"role": STUDENT, "backend": EPOPTES}, "not a Veyon computer"),
                (FakeSeat([False]), {}, "not a Veyon computer")):
            message, _slept = self.check(seat, state)
            self.assertIn(expected, message)
            self.assertFalse(self.restarted(seat), expected)

    def test_only_restarts_reach_the_journal(self) -> None:
        for message, level in (("restarted veyon.service: no Veyon Server", "<5>"), ("Veyon Server is running", "<6>")):
            with mock.patch.object(watchdog, "check", return_value=message), \
                    mock.patch.object(watchdog.system, "read_state", return_value={}), \
                    mock.patch("builtins.print") as printed:
                self.assertEqual(0, watchdog.main())
            printed.assert_called_once_with(level + message, flush=True)

    def test_the_check_loads_little(self) -> None:
        script = (LAB / "caramos-lab-veyon-check").read_text(encoding="utf-8")
        self.assertTrue(script.startswith("#!/usr/bin/python3 -I\n"))
        self.assertIn("from caramos_lab.watchdog import main", script)
        code = (LAB / "caramos_lab/watchdog.py").read_text(encoding="utf-8")
        for heavy in ("import gi", "pairing", "http.server", "caramos_ota"):
            self.assertNotIn(heavy, code)


APP = LAB / "caramos_lab/app.py"


def lab_msgids() -> set[str]:
    import ast

    ids: set[str] = set()
    for path in sorted((LAB / "caramos_lab").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"_", "ngettext"}:
                first = node.args[0] if node.args else None
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    ids.add(first.value)
    return ids


class DesignTests(unittest.TestCase):
    """The window looks like the rest of CaramOS (DESIGN.md): the green accent, two weights, sentences, pills only on
    status pages."""

    def test_the_look_comes_from_caramos_style(self) -> None:
        from caramos_lab import app as lab_app

        source = APP.read_text(encoding="utf-8")
        self.assertIn("adw_style.apply()", source, "the forest green accent instead of libadwaita's blue")
        self.assertNotIn("800", lab_app.CSS)
        self.assertNotRegex(lab_app.CSS, r"#[0-9a-fA-F]{3,6}|rgb|color", "no colour of its own")
        self.assertEqual({"600"}, set(__import__("re").findall(r"font-weight:\s*(\w+)", lab_app.CSS)))

    def test_pills_only_on_status_pages(self) -> None:
        import ast

        tree = ast.parse(APP.read_text(encoding="utf-8"))
        owners = set()
        for function in ast.walk(tree):
            if isinstance(function, ast.FunctionDef):
                for node in ast.walk(function):
                    if isinstance(node, ast.Constant) and node.value == "pill":
                        owners.add(function.name)
        # status_page() and the failure state of run_helper()'s status page; build_window holds both.
        self.assertEqual({"build_window", "status_page", "run_helper", "finished"}, owners)

    def test_details_are_sentences_not_dot_joined(self) -> None:
        for path in sorted((LAB / "caramos_lab").glob("*.py")):
            self.assertNotIn(" · ", path.read_text(encoding="utf-8"), path.name)
        self.assertEqual("Teacher's computer maygv, at 192.168.1.2, with Veyon.",
                         __import__("caramos_lab.app", fromlist=["app"]).teacher_line(
                             pairing.Teacher("192.168.1.2", "maygv", "Phòng máy 1", VEYON)))

    def test_every_window_string_is_translated(self) -> None:
        sys.path.insert(0, str(Path(__file__).parent))
        from test_ota_i18n import msgids

        missing = sorted(lab_msgids() - msgids(ROOT / "po/caramos-ota/vi.po"))
        self.assertEqual([], missing, "translate these in po/caramos-ota/vi.po (and add them to the .pot)")
        self.assertEqual([], sorted(lab_msgids() - msgids(ROOT / "po/caramos-ota/caramos-ota.pot")))


class WindowTests(unittest.TestCase):
    """The pages of the window, built (never shown) for each kind of computer. tests/lab_window_check.py builds them
    in a process of its own, so that GTK 4 does not keep this test run's GTK 3 tests from loading GTK 3."""

    result: dict = {}

    @classmethod
    def setUpClass(cls) -> None:
        env = {**os.environ, "PYTHONPATH": os.pathsep.join(
            [str(ROOT / "usr/lib/python3/dist-packages"), str(LAB), os.environ.get("PYTHONPATH", "")])}
        try:
            done = subprocess.run([sys.executable, str(Path(__file__).with_name("lab_window_check.py"))],
                                  capture_output=True, text=True, timeout=120, env=env, check=False)
            cls.result = json.loads(done.stdout.strip().splitlines()[-1]) if done.stdout.strip() else {}
        except (OSError, subprocess.SubprocessError, ValueError):
            cls.result = {}
        cls.error = done.stderr[-2000:] if "done" in locals() else ""

    def setUp(self) -> None:
        if not self.result:
            self.fail(f"tests/lab_window_check.py printed nothing: {self.error}")
        if not self.result.get("gtk"):
            self.skipTest("needs GTK 4 and libadwaita with a display")

    def test_first_page(self) -> None:
        from xml.sax.saxutils import escape

        first = self.result["first"]
        self.assertEqual([escape(_("Teacher's computer"), {"'": "&apos;"}),
                          escape(_("Student's computer"), {"'": "&apos;"})], first["rows"])
        self.assertEqual([], first["pills"], "round buttons only on status pages")

    def test_teacher_pages_have_one_main_action_at_the_bottom(self) -> None:
        self.assertEqual([_("Open Veyon Master")], self.result["teacher"]["main"])
        self.assertEqual([], self.result["teacher"]["pills"])
        self.assertEqual([_("Set up this computer")], self.result["teacher_setup"]["main"])
        self.assertEqual([], self.result["teacher_setup"]["pills"])

    def test_student_pages(self) -> None:
        self.assertEqual([_("Pair again"), _("Leave the computer lab")], self.result["student"]["rows"])
        self.assertEqual("student-code", self.result["student_code"]["tag"])
        self.assertEqual([_("Pair")], self.result["student_code"]["main"])

    def test_searching_again_replaces_the_search(self) -> None:
        self.assertEqual([["home", "student-find"], ["home", "student-find", "student-code"],
                          ["home", "student-find"]], self.result["search_stacks"],
                         "one search page, never two with the same tag, and a new search starts above the first page")

    def test_leaving_ends_on_a_status_page(self) -> None:
        left = self.result["left"]
        self.assertEqual("left", left["tag"])
        self.assertEqual(_("This computer left the computer lab"), left["status"][0][0])
        self.assertEqual([_("Done")], left["pills"])


class PackagingTests(unittest.TestCase):
    def test_installed_files(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        for line in ("usr/bin/caramos-lab usr/bin/", "usr/share/caramos-ota/lab usr/share/caramos-ota/",
                     "usr/share/applications/caramos-lab.desktop usr/share/applications/"):
            self.assertIn(line, install)
        for path in (ROOT / "usr/bin/caramos-lab", LAB / "caramos-lab-helper", LAB / "caramos-lab-veyon-check"):
            self.assertTrue(path.stat().st_mode & 0o111, path)
        for line in ("etc/xdg/autostart/caramos-lab-session.desktop etc/xdg/autostart/",
                     "usr/lib/systemd/system/caramos-lab-veyon-check.service usr/lib/systemd/system/",
                     "usr/lib/systemd/system/caramos-lab-veyon-check.timer usr/lib/systemd/system/"):
            self.assertIn(line, install)

    def test_veyon_check_units(self) -> None:
        service = (ROOT / "usr/lib/systemd/system/caramos-lab-veyon-check.service").read_text(encoding="utf-8")
        self.assertIn("ExecStart=/usr/share/caramos-ota/lab/caramos-lab-veyon-check\n", service)
        self.assertIn("Type=oneshot\n", service)
        self.assertIn("LogLevelMax=notice\n", service, "no journal lines every 30 seconds")
        timer = (ROOT / "usr/lib/systemd/system/caramos-lab-veyon-check.timer").read_text(encoding="utf-8")
        self.assertIn("OnUnitInactiveSec=30s\n", timer)
        self.assertIn("WantedBy=timers.target\n", timer)
        rules = (ROOT / "debian/rules").read_text(encoding="utf-8")
        self.assertNotIn("caramos-lab-veyon-check", rules, "enabled by the helper on lab computers only")

    def test_session_autostart(self) -> None:
        entry = configparser.ConfigParser(interpolation=None)
        entry.optionxform = str
        entry.read(ROOT / "etc/xdg/autostart/caramos-lab-session.desktop", encoding="utf-8")
        desktop = entry["Desktop Entry"]
        self.assertEqual("/usr/bin/caramos-lab --session", desktop["Exec"])
        self.assertEqual("X-Cinnamon;XFCE;", desktop["OnlyShowIn"])
        self.assertEqual("true", desktop["NoDisplay"])

    def test_polkit_action_runs_only_the_helper(self) -> None:
        policy = ElementTree.parse(ROOT / "usr/share/polkit-1/actions/net.vietnamlinuxfamily.caramos-ota.policy")
        action = next(item for item in policy.getroot() if item.get("id") == "net.vietnamlinuxfamily.caramos-ota.lab")
        annotations = {item.get("key"): item.text for item in action.findall("annotate")}
        self.assertEqual("/usr/share/caramos-ota/lab/caramos-lab-helper",
                         annotations["org.freedesktop.policykit.exec.path"])
        self.assertEqual("auth_admin_keep", action.find("defaults/allow_active").text)

    def test_menu_entry(self) -> None:
        entry = configparser.ConfigParser(interpolation=None)
        entry.optionxform = str
        entry.read(ROOT / "usr/share/applications/caramos-lab.desktop", encoding="utf-8")
        desktop = entry["Desktop Entry"]
        self.assertEqual("Phòng máy", desktop["Name[vi]"])
        self.assertEqual("caramos-lab", desktop["Exec"])
        self.assertEqual("Education;", desktop["Categories"])

    def test_window_strings_are_translated(self) -> None:
        po = (ROOT / "po/caramos-ota/vi.po").read_text(encoding="utf-8")
        for msgid, msgstr in (("Computer Lab", "Phòng máy"), ("Teacher's computer", "Máy giáo viên"),
                              ("Student's computer", "Máy học sinh"), ("Pairing code", "Mã ghép nối")):
            self.assertIn(f'msgid "{msgid}"\nmsgstr "{msgstr}"', po)
        self.assertIn("caramos_lab", (ROOT / "po/README.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

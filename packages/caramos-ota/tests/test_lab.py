"""Phòng máy (computer lab): pairing over the LAN, the root helper's Veyon and Epoptes setup, the packaging."""

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

from caramos_lab import EPOPTES, STUDENT, TEACHER, VEYON, helper, pairing, system  # noqa: E402

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

    def test_main_checks_root_and_arguments(self) -> None:
        with mock.patch.object(helper.os, "geteuid", lambda: 1000):
            self.assertEqual(2, helper.main(["leave"]))
        with mock.patch.object(helper.os, "geteuid", lambda: 0):
            self.assertEqual(1, helper.main(["teacher", "--backend", VEYON, "--room", "x;y"]))
            self.assertEqual(1, helper.main(["student", "--backend", VEYON, "--room", "P", "--teacher-host",
                                             "8.8.8.8", "--teacher-name", "maygv", "--key", "/dev/null"]))


class PackagingTests(unittest.TestCase):
    def test_installed_files(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        for line in ("usr/bin/caramos-lab usr/bin/", "usr/share/caramos-ota/lab usr/share/caramos-ota/",
                     "usr/share/applications/caramos-lab.desktop usr/share/applications/"):
            self.assertIn(line, install)
        for path in (ROOT / "usr/bin/caramos-lab", LAB / "caramos-lab-helper"):
            self.assertTrue(path.stat().st_mode & 0o111, path)

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

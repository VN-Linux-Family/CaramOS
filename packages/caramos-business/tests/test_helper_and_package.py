"""The root helper's checks and commands, the window's text helpers, and the package's files (units, polkit,
translations, dependencies)."""

from __future__ import annotations

import configparser
import datetime
import json
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest import mock

import caramos_business
from caramos_business import HELPER, admin, client, helper, protocol, text, tickets

ROOT = Path(__file__).parents[1]
JPEG = b"\xff\xd8\xff\xe0 a picture"


class HelperFixture(unittest.TestCase):
    """The helper with every path in a temporary folder and no systemctl, ufw or pkexec."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.etc = self.root / "etc"
        self.etc.mkdir()
        self.state = self.root / "state"
        self.agent_state = self.root / "agent"
        self.role_file = self.etc / "role"
        self.run_dir = self.root / "run"
        self.ssh = self.root / "ssh"
        paths = {"ROLE_FILE": self.role_file, "ETC": self.etc, "ADMIN_STATE": self.state,
                 "ADMIN_KEY": self.etc / "admin-key.pem", "ADMIN_BOX_KEY": self.etc / "admin-box.key",
                 "AGENT_CONFIG": self.etc / "agent.json", "AGENT_BOX_KEY": self.etc / "agent-box.key",
                 "AGENT_STATE": self.agent_state, "PUBLIC_AGENT_INFO": self.agent_state / "admin.json",
                 "OS_MACHINE_ID": self.etc / "machine-id", "ENROLL_ON_BOOT": self.etc / "enroll-on-boot.json",
                 "RUN": self.run_dir, "REMOTE_HELP_CONF": self.run_dir / "remote-help.conf",
                 "REMOTE_HELP_PSK": self.run_dir / "remote-help.psk", "PAIRING": self.run_dir / "pairing.json",
                 "DBUS_MACHINE_ID": self.root / "dbus-machine-id", "SSH_DIR": self.ssh, "HOSTS": self.root / "hosts",
                 "PROC_MOUNTS": self.root / "mounts"}
        for name, value in paths.items():
            patcher = mock.patch.object(helper, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        (self.root / "mounts").write_text("/dev/vda2 / ext4 rw,relatime 0 0\n")
        for patcher in (mock.patch.object(caramos_business, "ROLE_FILE", self.role_file),
                        mock.patch.object(helper, "systemctl"), mock.patch.object(helper, "ufw_active",
                                                                                 return_value=False),
                        mock.patch.object(helper, "hostname", return_value="quan-ly"),
                        mock.patch.object(helper, "admin_address", return_value="192.168.1.5")):
            started = patcher.start()
            self.addCleanup(patcher.stop)
            if getattr(patcher, "attribute", "") == "systemctl":
                self.systemctl = started

    def become_admin(self) -> None:
        helper.run(["role", "admin"])

    def picture(self) -> Path:
        path = self.root / "tet.jpg"
        path.write_bytes(JPEG)
        return path


class HelperTests(HelperFixture):
    def test_role_admin(self) -> None:
        self.assertEqual({"role": "admin"}, helper.run(["role", "admin"]))
        self.assertEqual("admin\n", self.role_file.read_text())
        self.assertEqual([mock.call("enable", caramos_business.SERVER_UNIT),
                          mock.call("restart", caramos_business.SERVER_UNIT)], self.systemctl.call_args_list)
        for name in ("admin-key.pem", "admin-box.key"):
            with self.subTest(name):
                self.assertEqual(0o600, (self.etc / name).stat().st_mode & 0o777)
        self.assertFalse((self.etc / "admin-tls.pem").exists(), "part 3: no certificate for remote help")
        self.assertEqual("role", admin.read_audit(self.state)[0]["action"])
        # A signed first policy with nothing on, so that paired machines can check in before anything is saved.
        signed = json.loads((self.state / admin.SIGNED).read_text())
        policy = protocol.verify_signed_policy(signed, admin.read_public_key(self.state))
        self.assertEqual((1, {}, {}), (policy["serial"], policy["settings"], policy["departments"]))
        helper.run(["pairing", "open"])
        self.assertEqual(1, admin.read_policy(self.state)["serial"], "made once")
        with self.assertRaises(helper.HelperError):
            helper.run(["role", "employee"])  # the admin stays the admin
        with self.assertRaises(helper.HelperError):
            helper.run(["pair", "192.168.1.5", "123456"])

    def test_the_firewall_lets_discovery_in(self) -> None:
        with mock.patch.object(helper, "ufw_active", return_value=True), mock.patch.object(helper, "ufw") as ufw:
            helper.run(["role", "employee"])
        self.assertEqual([mock.call("allow", "47021/udp")], ufw.call_args_list, "an employee: discovery's answers")
        self.role_file.unlink()
        with mock.patch.object(helper, "ufw_active", return_value=True), mock.patch.object(helper, "ufw") as ufw:
            helper.run(["role", "admin"])
        self.assertEqual([mock.call("allow", "47021/udp"), mock.call("allow", "47022/tcp")], ufw.call_args_list)

    def test_pairing_and_its_audit_lines(self) -> None:
        self.become_admin()
        first = helper.run(["pairing", "open"])
        self.assertRegex(first["code"], r"^\d{6}$")
        self.assertEqual(first, json.loads((self.run_dir / "pairing.json").read_text()))
        self.assertTrue(admin.pairing_open(self.run_dir / "pairing.json"))
        codes = {helper.run(["pairing", "open"])["code"] for _ in range(8)} | {first["code"]}
        self.assertGreater(len(codes), 1, "a new random code for each window")
        self.assertEqual({}, helper.run(["pairing", "close"]))
        self.assertFalse((self.run_dir / "pairing.json").exists())
        lines = admin.read_audit(self.state)
        self.assertEqual([{"pairing": "closed"}, {"pairing": "open"}], [line["details"] for line in lines[:2]])
        self.assertNotIn(first["code"], json.dumps(lines), "the code is not written into the audit log")
        from caramos_business import summaries
        self.assertEqual("Adding machines closed.", summaries.audit_text(lines[0], str, str))

    def test_admin_commands_need_the_admin_role(self) -> None:
        machine_id = "11111111-2222-4333-8444-555555555555"
        for argv in (["pairing", "open"], ["policy"], ["forget-machine", machine_id], ["command"],
                     ["asset", machine_id], ["asset-new"], ["remote-help", "start"], ["backup", "/tmp/x.cbkp"],
                     ["options"], ["approve", machine_id], ["reject", machine_id], ["licences"], ["ticket"],
                     ["enroll-token", "create", "/tmp/x.json"], ["enroll-token", "revoke", "a1b2c3d4e5f60718"]):
            with self.subTest(argv=argv), self.assertRaises(helper.HelperError):
                helper.run(argv, "{}")

    def test_bad_arguments(self) -> None:
        self.become_admin()
        for argv in (["role", "root"], ["pairing", "maybe"], ["forget-machine", "../../etc"], ["asset", "x"],
                     ["asset", "asset-1"], ["approve", "../x"], ["reject", "x"], ["remote-help", "maybe"],
                     ["backup", "relative.cbkp"], ["nonsense"], [], ["command", "extra"], ["policy", "x"],
                     ["forget-machine", "11111111-2222-4333-8444-555555555555", "x"],
                     ["enroll-token", "create", "relative.json"], ["enroll-token", "revoke", "../x"],
                     ["enroll-token", "maybe", "x"], ["enroll-token", "create"], ["pair-file"],
                     ["prepare-image", "x"], ["enroll-on-boot", "x"], ["options", "x"]):
            with self.subTest(argv=argv), self.assertRaises(helper.HelperError):
                helper.run(argv, "{}")
        with self.assertRaises(helper.HelperError):
            helper.run(["policy"], "not json")
        for request in ({"targets": {"all": True}, "action": "shell", "args": {}},
                        {"targets": {"all": True}, "action": "lock", "args": {}, "extra": 1},
                        {"targets": {"all": True}, "action": "lock", "args": {}, "minutes": 100000}):
            with self.subTest(request=request), self.assertRaises(helper.HelperError):
                helper.run(["command"], json.dumps(request))
        for argv, stdin in ((["options"], '{"approve_machines": "yes"}'), (["ticket"], '{"id": "HT-1"}'),
                            (["licences"], '[{"id": "x"}]'), (["asset-new"], '{"name": ""}')):
            with self.subTest(argv=argv), self.assertRaises(protocol.ProtocolError):
                helper.run(argv, stdin)

    def test_settings_commands_and_assets(self) -> None:
        self.become_admin()
        private = protocol.new_box_key()
        machine_id = admin.register(client_machine(), protocol.b64(protocol.box_public(private)), self.state)
        draft = {"settings": {"wallpaper": {"default": "new:1", "periods": [], "lock": True},
                              "wifi": [{"ssid": "CongTy", "security": "wpa-psk", "hidden": False}]},
                 "departments": {"ke-toan": {"name": "Kế toán", "settings": {"usb": {"storage": "block"}}}},
                 "members": {machine_id: "ke-toan"},
                 "pictures": {"new:1": str(self.picture())}, "wifi_passphrases": {"CongTy": "matkhau-cong-ty"}}
        with mock.patch.dict("os.environ", {"PKEXEC_UID": "0"}):
            self.assertEqual({"serial": 2}, helper.run(["policy"], json.dumps(draft)))  # 1: the empty first one
        policy = admin.read_policy(self.state)
        self.assertEqual("ke-toan", policy["members"][machine_id])
        self.assertIn("sealed", policy["machines"][machine_id])
        line = admin.read_audit(self.state)[0]
        self.assertEqual(("settings", "root"), (line["action"], line["user"]))
        self.assertIn("USB", line["summary"])
        answer = helper.run(["command"], json.dumps({"targets": {"departments": ["ke-toan"]}, "action": "message",
                                                     "args": {"title": "Họp 15h", "body": "", "ack": True}}))
        self.assertEqual(1, answer["seq"])
        envelope = admin.read_commands(self.state)["commands"][0]
        public = admin.read_public_key(self.state)
        self.assertEqual(answer["id"], protocol.verify_command(envelope, public)["id"])
        self.assertIn("Họp 15h", admin.read_audit(self.state)[0]["summary"])
        asset = {"asset_code": "TS-01", "purchase_date": "2024-03-15", "price_vnd": 12000000,
                 "warranty_until": "", "holder": "Minh", "location": "Tầng 2", "note": ""}
        helper.run(["asset", machine_id], json.dumps(asset))
        stored = admin.read_assets(self.state)[machine_id]
        self.assertEqual(asset, {key: stored[key] for key in asset})
        self.assertEqual((machine_id, "computer", "in_use"), (stored["machine_id"], stored["kind"], stored["status"]))
        self.assertEqual([("assigned", "Minh")], [(item["event"], item["note"]) for item in stored["history"]])
        with self.assertRaises(protocol.ProtocolError):
            helper.run(["asset", machine_id], json.dumps(dict(asset, price_vnd="mười hai triệu")))
        helper.run(["asset", machine_id], json.dumps(dict(asset, status="repair")))
        self.assertEqual(["assigned", "repair"],
                         [item["event"] for item in admin.read_assets(self.state)[machine_id]["history"]])
        # Remote help from a ticket: the session key is sealed for that machine, and the ticket is being worked on.
        with server_locked(self.state):
            ticket, _version = tickets.create(self.state, machine_id, {"user": "minh", "note": "", "time": ""}, {},
                                              None)
        with self.assertRaises(helper.HelperError):  # remote help was not started: no session key
            helper.run(["command"], json.dumps(remote_help_request(machine_id, ticket["id"])))
        self.run_dir.mkdir(exist_ok=True)
        helper.REMOTE_HELP_PSK.write_text("rh-0123456789abcdef:" + "ab" * 32 + "\n")
        with self.assertRaises(helper.HelperError):  # one machine at a time
            helper.run(["command"], json.dumps(dict(remote_help_request(machine_id, ticket["id"]),
                                                    targets={"all": True})))
        helper.run(["command"], json.dumps(remote_help_request(machine_id, ticket["id"])))
        envelope = admin.read_commands(self.state)["commands"][-1]
        args = protocol.verify_command(envelope, public)["args"]
        _mac, seal_key = protocol.machine_keys(private, protocol.box_public(admin.read_box_key(self.etc /
                                                                                                "admin-box.key")))
        self.assertEqual({"identity": "rh-0123456789abcdef", "key": "ab" * 32},
                         protocol.unseal(seal_key, machine_id, args["psk"]))
        self.assertEqual("working", tickets.find(tickets.read(self.state), ticket["id"])["status"])
        self.assertEqual({"removed": True}, helper.run(["forget-machine", machine_id]))
        policy = admin.read_policy(self.state)
        self.assertEqual(3, policy["serial"])
        self.assertEqual({}, policy["members"])
        self.assertNotIn(machine_id, policy["machines"], "part 3: a notice, not a policy entry with every section off")
        self.assertNotIn("usb", protocol.effective_settings(policy, machine_id))
        removed = admin.read_removed(self.state)[machine_id]
        protocol.verify_notice(removed["notice"], public, machine_id)

    def test_options_approval_and_rejection(self) -> None:
        self.become_admin()
        self.assertEqual({"approve_machines": True}, helper.run(["options"], '{"approve_machines": true}'))
        with server_locked(self.state):
            waiting = admin.register(client_machine(), protocol.b64(protocol.box_public(protocol.new_box_key())),
                                     self.state, pending=True, department="ke-toan")
            other = admin.register(dict(client_machine(), mac="52:54:00:00:00:02", name="kt-02"),
                                   protocol.b64(protocol.box_public(protocol.new_box_key())), self.state, pending=True)
        helper.run(["policy"], json.dumps({"departments": {"ke-toan": {"name": "Kế toán", "settings": {}}}}))
        self.assertEqual({}, admin.read_policy(self.state)["members"], "a pending machine is no member")
        self.assertEqual({}, helper.run(["approve", waiting]))
        policy = admin.read_policy(self.state)
        self.assertEqual("ke-toan", policy["members"][waiting], "the enrolment file's department, on approval")
        self.assertEqual("approved", admin.read_machines(self.state)[waiting]["state"])
        with self.assertRaises(helper.HelperError):
            helper.run(["approve", waiting])  # not waiting any more
        self.assertEqual({}, helper.run(["reject", other]))
        self.assertNotIn(other, admin.read_machines(self.state))
        self.assertNotIn(other, admin.read_removed(self.state), "no removal notice for a machine never let in")
        self.assertEqual(["reject", "approve"], [line["action"] for line in admin.read_audit(self.state)[:2]])

    def test_enrolment_files(self) -> None:
        self.become_admin()
        helper.run(["policy"], json.dumps({"departments": {"ke-toan": {"name": "Kế toán", "settings": {}}}}))
        target = self.root / "caramos-business-enroll.json"
        with self.assertRaises(protocol.ProtocolError):
            helper.run(["enroll-token", "create", str(target)], '{"department": "kho"}')
        with self.assertRaises(protocol.ProtocolError):
            helper.run(["enroll-token", "create", str(target)], '{"days": 31}')
        answer = helper.run(["enroll-token", "create", str(target)],
                            '{"department": "ke-toan", "days": 7, "max_uses": 30, "hostname_prefix": "phong-may"}')
        data = json.loads(target.read_text())
        self.assertEqual(0o600, target.stat().st_mode & 0o777)
        self.assertEqual(data, protocol.validate_enroll_file(data))
        self.assertEqual((answer["token_id"], answer["expires"]), (data["token_id"], data["expires"]))
        self.assertEqual(("http://192.168.1.5:47022", "quan-ly", "Kế toán", "phong-may"),
                         (data["admin_url"], data["admin_name"], data["department_name"], data["hostname_prefix"]))
        self.assertEqual(protocol.b64(protocol.public_bytes(admin.ensure_key(self.etc / "admin-key.pem", self.state))),
                         data["admin_key"])
        self.assertEqual(protocol.b64(protocol.box_public(admin.read_box_key(self.etc / "admin-box.key"))),
                         data["admin_box_key"], "the copies' first HMAC needs the admin's box key")
        tokens = json.loads((self.state / "enroll-tokens.json").read_text())
        self.assertNotIn(data["token"], json.dumps(tokens), "the admin never keeps the token")
        keys = json.loads((self.state / "enroll-keys.json").read_text())
        self.assertEqual(protocol.enroll_proof_key(protocol.unb64(data["token"], 32)).hex(), keys[data["token_id"]])
        self.assertEqual(0o600, (self.state / "enroll-keys.json").stat().st_mode & 0o777)
        self.assertEqual({}, helper.run(["enroll-token", "revoke", data["token_id"]]))
        self.assertTrue(json.loads((self.state / "enroll-tokens.json").read_text())[data["token_id"]]["revoked"])
        self.assertNotIn(data["token_id"], json.loads((self.state / "enroll-keys.json").read_text()))
        with self.assertRaises(helper.HelperError):
            helper.run(["enroll-token", "revoke", data["token_id"]])
        self.assertEqual(["enroll-token", "enroll-token"], [line["action"] for line in admin.read_audit(self.state)[:2]])
        self.assertNotIn(data["token"], (self.state / "audit.jsonl").read_text())

    def test_licences_and_tickets(self) -> None:
        self.become_admin()
        register = [{"id": "office", "product": "Microsoft Office 2021", "seats": 5, "expires": "", "invoice": "HĐ 12",
                     "note": "", "match": ["onlyoffice-desktopeditors"]}]
        self.assertEqual({"count": 1}, helper.run(["licences"], json.dumps(register)))
        self.assertEqual(register, json.loads((self.state / "licences.json").read_text()))
        machine_id = admin.register(client_machine(), protocol.b64(protocol.box_public(protocol.new_box_key())),
                                    self.state)
        with server_locked(self.state):
            ticket, _version = tickets.create(self.state, machine_id, {"user": "lan", "note": "Máy in", "time": ""},
                                              {}, None)
        with self.assertRaises(helper.HelperError):
            helper.run(["ticket"], '{"id": "HT-9999", "status": "done"}')
        self.assertEqual({"status": "waiting"}, helper.run(["ticket"], json.dumps(
            {"id": ticket["id"], "status": "waiting", "assignee": "Tuấn",
             "note": {"text": "Bạn gửi giúp ảnh lỗi nhé.", "public": True}})))
        stored = tickets.find(tickets.read(self.state), ticket["id"])
        self.assertEqual(("waiting", "Tuấn"), (stored["status"], stored["assignee"]))
        self.assertTrue(stored["first_response"])
        line = admin.read_audit(self.state)[0]
        self.assertEqual(("ticket", "public"), (line["action"], line["details"]["note"]))
        self.assertNotIn("ảnh lỗi", json.dumps(line), "note texts stay out of the audit log")

    def test_assets_without_a_machine(self) -> None:
        self.become_admin()
        answer = helper.run(["asset-new"], json.dumps({"name": "Màn hình Dell 24", "kind": "monitor",
                                                       "asset_code": "TS-07", "purchase_date": "", "price_vnd": None,
                                                       "warranty_until": "", "holder": "", "location": "Kho",
                                                       "note": ""}))
        self.assertRegex(answer["id"], r"^asset-[0-9a-f-]{36}$")
        entry = admin.read_assets(self.state)[answer["id"]]
        self.assertEqual(("monitor", "in_stock", None), (entry["kind"], entry["status"], entry["machine_id"]))
        self.assertEqual(["received"], [item["event"] for item in entry["history"]])
        with self.assertRaises(helper.HelperError):
            helper.run(["asset", "asset-00000000-0000-4000-8000-000000000000"], "{}")

    def test_pictures_copied_at_save(self) -> None:
        picture = self.picture()
        draft = {"settings": {"wallpaper": {"default": "new:1", "lock": False,
                                            "periods": [{"name": "Tết", "from": "01-25", "to": "02-05",
                                                         "image": "new:1"}]}},
                 "departments": {"kho": {"name": "Kho", "settings": {"wallpaper": {
                     "default": "new:2", "lock": False, "periods": [{"name": "x", "from": "03-01", "to": "03-02",
                                                                    "image": "a" * 64}]}}}}}
        with mock.patch.object(helper.admin, "add_image", side_effect=[{"sha256": "b" * 64},
                                                                       {"sha256": "c" * 64}]) as add:
            result = helper.with_pictures(draft, {"new:1": str(picture), "new:2": str(picture)})
        self.assertEqual(2, add.call_count)  # once for a picture used twice
        wallpaper = result["settings"]["wallpaper"]
        self.assertEqual(["b" * 64, "b" * 64], [wallpaper["default"], wallpaper["periods"][0]["image"]])
        other = result["departments"]["kho"]["settings"]["wallpaper"]
        self.assertEqual(["c" * 64, "a" * 64], [other["default"], other["periods"][0]["image"]])
        for pictures in ({"new:1": "relative.jpg"}, {"new:1": str(self.root / "missing.jpg")}, {}, "nope"):
            with self.subTest(pictures=pictures), self.assertRaises(helper.HelperError):
                helper.with_pictures({"settings": {"wallpaper": {"default": "new:1"}}}, pictures)

    def test_remote_help(self) -> None:
        self.become_admin()
        done = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(helper.shutil, "which", side_effect=lambda name: f"/usr/sbin/{name}"), \
                mock.patch.object(helper.subprocess, "run", return_value=done) as run, \
                mock.patch.object(helper, "ufw_active", return_value=True), mock.patch.object(helper, "ufw") as ufw:
            self.assertEqual({"port": 5501}, helper.run(["remote-help", "start"]))
            started = [call.args[0] for call in run.call_args_list if call.args[0][0] == "systemd-run"]
            self.assertEqual(1, len(started))
            self.assertIn(f"--unit={caramos_business.REMOTE_HELP_UNIT}", started[0])
            self.assertEqual(["/usr/sbin/stunnel4", str(helper.REMOTE_HELP_CONF)], started[0][-2:])
            conf = helper.REMOTE_HELP_CONF.read_text()
            self.assertIn("accept = 0.0.0.0:5501\nconnect = 127.0.0.1:5500\n", conf)
            self.assertIn(f"PSKsecrets = {helper.REMOTE_HELP_PSK}\nciphers = PSK\n"
                          "ciphersuites = TLS_AES_128_GCM_SHA256\nsslVersionMin = TLSv1.3\n", conf)
            self.assertNotIn("cert =", conf)
            self.assertEqual(0o600, helper.REMOTE_HELP_CONF.stat().st_mode & 0o777)
            self.assertRegex(helper.REMOTE_HELP_PSK.read_text(), r"^rh-[0-9a-f]{16}:[0-9a-f]{64}\n$")
            self.assertEqual(0o600, helper.REMOTE_HELP_PSK.stat().st_mode & 0o777)
            rule = ["INPUT", "-p", "tcp", "--dport", "5500", "!", "-i", "lo", "-m", "comment", "--comment",
                    "caramos-business-remote-help", "-j", "DROP"]
            commands = [call.args[0] for call in run.call_args_list]
            self.assertIn(["/usr/sbin/iptables", "-I", *rule], commands)
            self.assertIn(["/usr/sbin/ip6tables", "-I", *rule], commands)
            self.assertLess(commands.index(["/usr/sbin/iptables", "-I", *rule]), commands.index(started[0]),
                            "the viewer's port is closed before the session starts")
            ufw.assert_called_with("allow", "5501/tcp")
            run.reset_mock()
            helper.run(["remote-help", "stop"])
            ufw.assert_called_with("delete", "allow", "5501/tcp")
            self.assertFalse(helper.REMOTE_HELP_CONF.exists())
            self.assertFalse(helper.REMOTE_HELP_PSK.exists())
            self.assertIn(["/usr/sbin/iptables", "-D", *rule], [call.args[0] for call in run.call_args_list])
        with mock.patch.object(helper.shutil, "which", side_effect=lambda name: None if "iptables" in name else
                               f"/usr/bin/{name}"), mock.patch.object(helper, "Path") as path, \
                mock.patch.object(helper.subprocess, "run", return_value=done) as run:
            path.return_value.exists.return_value = False
            with self.assertRaises(helper.HelperError):  # without the rule, no session
                helper.remote_help("start")
            self.assertNotIn("systemd-run", [call.args[0][0] for call in run.call_args_list])

    def test_backup_and_restore(self) -> None:
        self.become_admin()
        admin.queue_command(admin.ensure_key(self.etc / "admin-key.pem", self.state), {"all": True}, "lock", {},
                            self.state)
        target = self.root / "sao-luu.cbkp"
        with self.assertRaises(helper.HelperError):
            helper.run(["backup", str(target)], "ngắn")
        self.assertGreater(helper.run(["backup", str(target)], "mật khẩu sao lưu\n")["size"], 100)
        self.assertEqual(b"CBKP1", target.read_bytes()[:5])
        keys = {name: (self.etc / name).read_bytes() for name in ("admin-key.pem", "admin-box.key")}
        with self.assertRaises(helper.HelperError):  # a machine with a role does not take over
            helper.run(["restore", str(target)], "mật khẩu sao lưu")
        # Another machine: nothing of the admin's on it.
        for path in list(self.etc.iterdir()):
            path.unlink()
        for path in sorted(self.state.rglob("*"), reverse=True):
            path.unlink() if path.is_file() else path.rmdir()
        with self.assertRaises(helper.HelperError):
            helper.run(["restore", str(target)], "sai mật khẩu")
        self.assertFalse(self.role_file.exists())
        self.assertEqual({"role": "admin"}, helper.run(["restore", str(target)], "mật khẩu sao lưu\n"))
        self.assertEqual("admin\n", self.role_file.read_text())
        for name, data in keys.items():
            with self.subTest(name):
                self.assertEqual(data, (self.etc / name).read_bytes())
                self.assertEqual(0o600, (self.etc / name).stat().st_mode & 0o777)
        self.assertEqual(1, admin.read_commands(self.state)["seq"])
        self.assertEqual("restore", admin.read_audit(self.state)[0]["action"])

    def test_pair_checks_the_address_first(self) -> None:
        with mock.patch.object(helper.client, "pair") as pair:
            with self.assertRaises(helper.HelperError):
                helper.run(["pair", "nas; rm -rf /", "123456"])
            pair.assert_not_called()
            pair.side_effect = client.PairingError("wrong")
            with self.assertRaises(helper.HelperError):
                helper.run(["pair", "192.168.1.5", "123456"])
        self.assertFalse(self.role_file.exists(), "nothing written for a failed pairing")
        self.assertFalse((self.etc / "agent-box.key").exists())

    def test_pair_and_leave(self) -> None:
        (self.etc / "machine-id").write_text("0123456789abcdef0123456789abcdef\n")
        self.agent_state.mkdir()
        for name in ("clone.json", "removed.json", "enroll-failed.json"):  # old marks go with a new pairing
            (self.agent_state / name).write_text("{}")
        with mock.patch.object(helper.client, "pair", return_value=(agent_config(), "pending")) as pair:
            self.assertEqual({"admin_name": "quan-ly", "state": "pending"},
                             helper.run(["pair", "192.168.1.5", "123456"]))
        stored = json.loads((self.etc / "agent.json").read_text())
        self.assertEqual("0123456789abcdef0123456789abcdef", stored["machine_id_os"])
        self.assertEqual(agent_config()["admin_box_key"], stored["admin_box_key"])
        for name in ("clone.json", "removed.json", "enroll-failed.json"):
            self.assertFalse((self.agent_state / name).exists(), name)
        self.assertEqual("pending", json.loads((self.agent_state / "approval.json").read_text())["state"])
        box_private = pair.call_args.args[2]
        self.assertEqual(box_private, (self.etc / "agent-box.key").read_bytes())
        self.assertEqual(0o600, (self.etc / "agent-box.key").stat().st_mode & 0o777)
        self.assertEqual(0o600, (self.etc / "agent.json").stat().st_mode & 0o777)
        public = json.loads((self.agent_state / "admin.json").read_text())
        self.assertEqual(agent_config()["machine_id"], public["machine_id"])
        self.assertEqual("0123456789abcdef0123456789abcdef", public["machine_id_os"])
        self.assertNotIn("admin_key", public)
        self.assertEqual(["enable", "restart"], [call.args[0] for call in self.systemctl.call_args_list])
        (self.agent_state / "files").mkdir()
        (self.agent_state / "files" / "picture.jpg").write_bytes(b"jpeg")
        frozen_agent = subprocess.CompletedProcess([], 0, "reboot needed\n", "")
        with mock.patch.object(helper.subprocess, "run", return_value=frozen_agent), \
                mock.patch.object(helper, "AGENT", str(self.root / "agent-program")):
            (self.root / "agent-program").write_text("")
            self.assertEqual({"reboot": True}, helper.run(["leave"]))
        for name in ("agent.json", "agent-box.key"):
            self.assertFalse((self.etc / name).exists(), name)
        for name in ("admin.json", "approval.json"):
            self.assertFalse((self.agent_state / name).exists(), name)
        self.assertTrue((self.agent_state / "files" / "picture.jpg").exists(), "the wallpaper keeps its picture")

    def test_pair_with_a_file(self) -> None:
        data = enroll_file()
        path = self.root / "caramos-business-enroll.json"
        path.write_text(json.dumps(data))
        with mock.patch.object(helper.client, "enroll", return_value=(agent_config(), "approved")) as enroll:
            self.assertEqual({"admin_name": "quan-ly", "state": "approved"}, helper.run(["pair-file", str(path)]))
        self.assertEqual(data, enroll.call_args.args[0])
        self.assertTrue((self.etc / "agent.json").exists())
        path.write_text(json.dumps(dict(data, kind="something-else")))
        self.role_file.unlink()
        with self.assertRaises(helper.HelperError):
            helper.run(["pair-file", str(path)])
        path.write_text("not json")
        with self.assertRaises(helper.HelperError):
            helper.run(["pair-file", str(path)])

    def test_prepare_image(self) -> None:
        (self.etc / "machine-id").write_text("0123456789abcdef0123456789abcdef\n")
        (self.root / "dbus-machine-id").write_text("0123456789abcdef0123456789abcdef\n")
        self.ssh.mkdir()
        for name in ("sshd_config", "ssh_host_ed25519_key", "ssh_host_ed25519_key.pub"):
            (self.ssh / name).write_text("x")
        with mock.patch.object(helper.client, "pair", return_value=(agent_config(), "approved")):
            helper.run(["pair", "192.168.1.5", "123456"])
        (self.agent_state / "policy.json").write_text("{}")
        source = self.root / "caramos-business-enroll.json"
        source.write_text(json.dumps(enroll_file()))
        with mock.patch.object(helper.subprocess, "run") as run, mock.patch.object(helper, "leave",
                                                                                  wraps=helper.leave) as leave:
            self.assertEqual({"enroll": True}, helper.run(["prepare-image"], json.dumps({"enroll_file": str(source)})))
        leave.assert_called_once()
        self.assertEqual(b"", (self.etc / "machine-id").read_bytes(), "emptied, not deleted")
        self.assertFalse((self.root / "dbus-machine-id").exists())
        self.assertEqual(["sshd_config"], sorted(path.name for path in self.ssh.iterdir()))
        for name in ("agent.json", "agent-box.key"):
            self.assertFalse((self.etc / name).exists(), name)
        self.assertFalse(self.agent_state.exists())
        self.assertEqual(enroll_file(), json.loads((self.etc / "enroll-on-boot.json").read_text()))
        self.assertEqual(0o600, (self.etc / "enroll-on-boot.json").stat().st_mode & 0o777)
        self.assertIn(mock.call("enable", caramos_business.HOSTNAME_UNIT, caramos_business.ENROLL_UNIT),
                      self.systemctl.call_args_list)
        self.assertEqual("employee\n", self.role_file.read_text())
        del run
        # Without a file: nothing enrols at the next boot.
        with mock.patch.object(helper.subprocess, "run") as run:
            self.assertEqual({"enroll": False}, helper.run(["prepare-image"], json.dumps({"enroll_file": None})))
        self.assertFalse((self.etc / "enroll-on-boot.json").exists())
        self.assertIn(["systemctl", "disable", caramos_business.HOSTNAME_UNIT, caramos_business.ENROLL_UNIT],
                      [call.args[0] for call in run.call_args_list])
        (self.root / "mounts").write_text("overlayroot / overlay rw,relatime 0 0\n")
        with self.assertRaises(helper.HelperError):
            helper.run(["prepare-image"], "{}")
        self.role_file.write_text("admin\n")
        with self.assertRaises(helper.HelperError):
            helper.run(["prepare-image"], "{}")

    def test_enroll_on_boot(self) -> None:
        self.ssh.mkdir()
        (self.ssh / "sshd_config").write_text("x")
        (self.etc / "machine-id").write_text("abcdef0123456789abcdef0123456789\n")
        (self.root / "hosts").write_text("127.0.0.1\tlocalhost\n127.0.1.1\tcaramos\n")
        with mock.patch.dict("os.environ", {"PKEXEC_UID": "1000"}), self.assertRaises(helper.HelperError):
            helper.run(["enroll-on-boot"])
        enabled = subprocess.CompletedProcess([], 0, "enabled\n", "")
        with mock.patch.object(helper.subprocess, "run", return_value=enabled) as run:
            self.assertEqual({"enrolled": False}, helper.run(["enroll-on-boot"]), "nothing to enrol")
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn(["ssh-keygen", "-A"], commands)
        # The socket failed at boot without keys: reset and started again (a try-restart starts nothing).
        self.assertIn(["systemctl", "reset-failed", "ssh.socket", "ssh.service"], commands)
        self.assertIn(["systemctl", "--no-block", "restart", "ssh.socket"], commands)
        (self.etc / "enroll-on-boot.json").write_text(json.dumps(enroll_file(hostname_prefix="phong-may")))
        with mock.patch.object(helper.subprocess, "run") as run, \
                mock.patch.object(helper.client, "enroll", side_effect=client.PairingError("no answer")):
            with self.assertRaises(helper.HelperError):  # the unit tries again a minute later
                helper.run(["enroll-on-boot"])
        self.assertTrue((self.etc / "enroll-on-boot.json").exists())
        self.assertIn(["hostnamectl", "set-hostname", "phong-may-abcdef"], [call.args[0] for call in
                                                                           run.call_args_list])
        self.assertEqual("127.0.0.1\tlocalhost\n127.0.1.1\tphong-may-abcdef\n", (self.root / "hosts").read_text())
        self.systemctl.reset_mock()
        with mock.patch.object(helper.subprocess, "run") as run, \
                mock.patch.object(helper.client, "enroll", return_value=(agent_config(), "approved")):
            self.assertEqual({"admin_name": "quan-ly", "state": "approved", "enrolled": True},
                             helper.run(["enroll-on-boot"]))
        self.assertFalse((self.etc / "enroll-on-boot.json").exists())
        commands = [call.args[0] for call in run.call_args_list]
        disable = ["systemctl", "disable", caramos_business.HOSTNAME_UNIT, caramos_business.ENROLL_UNIT]
        self.assertIn(disable, commands)
        # The unit runs Before= the agent: a blocking restart from it waits for itself (it hung on the copied disk).
        self.assertIn(["systemctl", "--no-block", "restart", caramos_business.AGENT_UNIT], commands)
        self.assertLess(commands.index(disable),
                        commands.index(["systemctl", "--no-block", "restart", caramos_business.AGENT_UNIT]))
        self.assertEqual([], self.systemctl.call_args_list, "no blocking systemctl from the unit")
        self.assertEqual("abcdef0123456789abcdef0123456789",
                         json.loads((self.etc / "agent.json").read_text())["machine_id_os"])
        # A refused token gives up for good, and says why.
        (self.etc / "enroll-on-boot.json").write_text(json.dumps(enroll_file()))
        with mock.patch.object(helper.subprocess, "run"), \
                mock.patch.object(helper.client, "enroll", side_effect=client.TokenRefused("hết hạn")):
            self.assertEqual({"enrolled": False, "error": "hết hạn"}, helper.run(["enroll-on-boot"]))
        self.assertFalse((self.etc / "enroll-on-boot.json").exists())
        self.assertEqual("hết hạn", json.loads((self.agent_state / "enroll-failed.json").read_text())["error"])

    def test_enroll_hostname(self) -> None:
        """The copy's name comes before the login screen: changed after LightDM started its X server, it locked the
        session out of the display ("Authorization required") and the copy showed a black screen."""

        (self.etc / "machine-id").write_text("abcdef0123456789abcdef0123456789\n")
        (self.root / "hosts").write_text("127.0.0.1\tlocalhost\n127.0.1.1\tcaramos-disk\n")
        with mock.patch.dict("os.environ", {"PKEXEC_UID": "1000"}), self.assertRaises(helper.HelperError):
            helper.run(["enroll-hostname"])
        with mock.patch.object(helper.subprocess, "run") as run:
            self.assertEqual({"hostname": None}, helper.run(["enroll-hostname"]), "no file")
            (self.etc / "enroll-on-boot.json").write_text(json.dumps(enroll_file()))
            self.assertEqual({"hostname": None}, helper.run(["enroll-hostname"]), "no prefix: the name stays")
            (self.etc / "enroll-on-boot.json").write_text(json.dumps(enroll_file(hostname_prefix="phong-may")))
            self.assertEqual({"hostname": "phong-may-abcdef"}, helper.run(["enroll-hostname"]))
        self.assertEqual([["hostnamectl", "set-hostname", "phong-may-abcdef"]], [call.args[0] for call in
                                                                                run.call_args_list])
        self.assertEqual("127.0.0.1\tlocalhost\n127.0.1.1\tphong-may-abcdef\n", (self.root / "hosts").read_text())
        self.assertTrue((self.etc / "enroll-on-boot.json").exists(), "the enrolment unit still needs it")
        # enroll-on-boot later sets the same name: nothing changes under the running session.
        with mock.patch.object(helper.subprocess, "run") as run, \
                mock.patch.object(helper.socket, "gethostname", return_value="phong-may-abcdef"), \
                mock.patch.object(helper.client, "enroll", side_effect=client.PairingError("no answer")), \
                self.assertRaises(helper.HelperError):
            helper.run(["enroll-on-boot"])
        self.assertNotIn("hostnamectl", [call.args[0][0] for call in run.call_args_list])

    def test_errors_say_where(self) -> None:
        error = protocol.ProtocolError("x", section="wifi", scope="department:kho")
        self.assertEqual({"section": "wifi", "scope": "department:kho"}, helper.error_place(error))
        self.assertEqual({}, helper.error_place(helper.HelperError("x")))


def server_locked(state: Path):
    from caramos_business.store import locked
    return locked(state)


def remote_help_request(machine_id: str, ticket_id: str) -> dict:
    return {"targets": {"machines": [machine_id]}, "action": "remote_help",
            "args": {"admin_host": "192.168.1.5", "port": 5501, "mode": "control", "admin_name": "IT"},
            "help_id": ticket_id}


def agent_config() -> dict:
    return {"admin_url": "http://192.168.1.5:47022", "admin_name": "quan-ly", "admin_key": protocol.b64(b"k" * 32),
            "admin_box_key": protocol.b64(b"b" * 32), "fingerprint": "0123456789abcdef",
            "machine_id": "11111111-2222-4333-8444-555555555555"}


def enroll_file(**changes) -> dict:
    data = json.loads((ROOT / "tests/protocol-examples/v3/enroll-file.json").read_text())
    data = data.get("file", data)
    future = (datetime.datetime.now().astimezone() + datetime.timedelta(days=3)).isoformat(timespec="seconds")
    return dict(data, expires=future, **changes)


def client_machine() -> dict:
    return {"name": "kt-01", "ip": "192.168.1.20", "mac": "52:54:00:00:00:01", "edition": "xfce", "version": "1.4.0"}


class TextTests(unittest.TestCase):
    def test_days(self) -> None:
        self.assertEqual("01-25", text.month_day("25/1"))
        self.assertEqual("02-29", text.month_day(" 29 / 02 "))
        for bad in ("30/2", "1-25", "25", "32/1", ""):
            self.assertIsNone(text.month_day(bad), bad)
        self.assertEqual("25/1", text.day_month("01-25"))
        self.assertEqual("2024-03-15", text.iso_date("15/3/2024"))
        self.assertEqual("", text.iso_date(" "))
        self.assertIsNone(text.iso_date("31/2/2024"))
        self.assertEqual("15/3/2024", text.vn_date("2024-03-15"))
        self.assertEqual("Mon to Sat", text.days_text([1, 2, 3, 4, 5, 6]))
        self.assertEqual("Mon, Wed", text.days_text([3, 1]))
        self.assertEqual("every day", text.days_text(list(range(1, 8))))

    def test_money(self) -> None:
        self.assertEqual("15.000.000 đ", text.money(15000000))
        self.assertEqual("", text.money(None))
        for typed in ("15.000.000", "15,000,000 đ", "15000000", " 15 000 000 VND "):
            self.assertEqual(15000000, text.parse_money(typed), typed)
        self.assertIsNone(text.parse_money(""))
        with self.assertRaises(ValueError):
            text.parse_money("15 triệu")

    def test_ago(self) -> None:
        now = datetime.datetime(2026, 11, 21, 9, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual("just now", text.ago("2026-11-21T08:59:30+00:00", now))
        self.assertEqual("5 minutes ago", text.ago("2026-11-21T08:55:00+00:00", now))
        self.assertEqual("2 days ago", text.ago("2026-11-19T08:00:00+00:00", now))
        self.assertEqual("never", text.ago("", now))

    def test_inventory_text(self) -> None:
        inventory = {"cpu": {"model": "Intel(R) Core(TM)  i5-10500", "cores": 6, "threads": 12},
                     "memory": {"total_mb": 7834, "modules": [{"type": "DDR4"}]},
                     "disks": [{"size_gb": 512, "rotational": False, "transport": "nvme"},
                               {"size_gb": 1000, "rotational": True, "transport": "sata"}],
                     "system": {"vendor": "Dell Inc.", "product": "OptiPlex 3080"}}
        self.assertEqual("Intel(R) Core(TM) i5-10500, 6 cores, 12 threads", text.cpu_text(inventory))
        self.assertEqual("8 GB DDR4", text.memory_text(inventory))
        self.assertEqual("512 GB SSD NVMe, 1 TB HDD", text.disks_text(inventory))
        self.assertEqual("Dell Inc. OptiPlex 3080", text.model_text(inventory))
        self.assertEqual("", text.cpu_text({}))


class ConnectTests(unittest.TestCase):
    """The share sign-in window's choices (the GTK parts need a display; these do not)."""

    def setUp(self) -> None:
        try:
            from caramos_business.ui import connect
        except (ImportError, ValueError) as exc:  # no GTK 4 / libadwaita here
            self.skipTest(f"GTK 4 is not available: {exc}")
        self.connect = connect

    def test_account(self) -> None:
        self.assertEqual(("minh", "WORKGROUP"), self.connect.split_account(" minh ", "WORKGROUP"))
        self.assertEqual(("minh", "CONGTY"), self.connect.split_account("CONGTY\\minh", "WORKGROUP"))

    def test_remember_only_in_an_open_keyring(self) -> None:
        Gio = self.connect.Gio
        self.assertEqual(Gio.PasswordSave.PERMANENTLY, self.connect.password_save(True, True))
        self.assertEqual(Gio.PasswordSave.FOR_SESSION, self.connect.password_save(True, False))
        self.assertEqual(Gio.PasswordSave.NEVER, self.connect.password_save(False, True))


class PackageTests(unittest.TestCase):
    def test_every_installed_file_exists(self) -> None:
        for line in (ROOT / "debian/install").read_text().splitlines():
            source = line.split()[0]
            self.assertTrue((ROOT / source).exists(), source)

    def test_services_wait_for_a_role(self) -> None:
        rules = (ROOT / "debian/rules").read_text()
        self.assertIn("\tdh_installsystemd --no-enable\n", rules)  # and restarted after upgrades
        for unit, needs in (("caramos-business-server.service", "/etc/caramos-business/admin-key.pem"),
                            ("caramos-business-agent.service", "/etc/caramos-business/agent.json")):
            with self.subTest(unit):
                parser = configparser.ConfigParser(strict=False, interpolation=None)
                parser.read(ROOT / "lib/systemd/system" / unit)
                self.assertEqual(needs, parser["Unit"]["ConditionPathExists"])

    def test_polkit_runs_the_helper(self) -> None:
        policy = ElementTree.parse(ROOT / "usr/share/polkit-1/actions/net.vietnamlinuxfamily.caramos-business.policy")
        paths = [item.text for item in policy.iter("annotate") if item.get("key") == "org.freedesktop.policykit.exec.path"]
        self.assertEqual([HELPER], paths)
        self.assertTrue((ROOT / HELPER.lstrip("/")).is_file())

    def test_session_part_starts_the_agent(self) -> None:
        entry = (ROOT / "etc/xdg/autostart/caramos-business-session.desktop").read_text()
        self.assertIn("Exec=/usr/lib/caramos-business/caramos-business-agent session\n", entry)

    def test_dependencies(self) -> None:
        control = (ROOT / "debian/control").read_text()
        depends = re.search(r"^Package: caramos-business$.*?^Depends:(.*?)^\S", control, re.M | re.S).group(1)
        for package in ("python3-openpyxl", "python3-spake2", "x11vnc", "stunnel4", "tigervnc-viewer", "cups-client",
                        "network-manager", "iptables"):
            with self.subTest(package):
                self.assertRegex(depends, rf"(^|[\s,|]){re.escape(package)}([\s,|]|$)")
        self.assertRegex(depends, r"avahi-utils\s*\|\s*cups-ipp-utils")

    def test_version(self) -> None:
        changelog = (ROOT / "debian/changelog").read_text().splitlines()[0]
        self.assertEqual(f"caramos-business ({caramos_business.VERSION}) noble; urgency=medium", changelog)

    def test_translations_complete(self) -> None:
        def entries(path: Path) -> dict[str, list[str]]:
            """{msgid: [msgstr, ...]} of a .po or .pot file, continuation lines joined, the header left out."""

            found: dict[str, list[str]] = {}
            for block in path.read_text(encoding="utf-8").split("\n\n"):
                if "#, fuzzy" in block and 'msgid ""\nmsgstr ""\n"Project' not in block:
                    found["(fuzzy) " + block[:40]] = []
                fields: dict[str, str] = {}
                key = ""
                for line in block.splitlines():
                    match = re.match(r'^(msgid|msgid_plural|msgstr(?:\[\d+\])?) "(.*)"$', line)
                    if match:
                        key = match.group(1)
                        fields[key] = match.group(2)
                    elif line.startswith('"') and key:
                        fields[key] += line[1:-1]
                if fields.get("msgid") and not block.lstrip().startswith("#~"):
                    found[fields["msgid"]] = [value for name, value in fields.items() if name.startswith("msgstr")]
            return found

        translated = entries(ROOT / "po/vi.po")
        template = entries(ROOT / "po/caramos-business.pot")
        self.assertGreater(len(template), 400)
        self.assertEqual(set(), set(template) - set(translated), "run make pot")
        for msgid, strings in translated.items():
            with self.subTest(msgid=msgid[:60]):
                self.assertTrue(strings and all(strings), "not translated")

    def test_enrol_unit(self) -> None:
        parser = configparser.ConfigParser(strict=False, interpolation=None)
        parser.optionxform = str
        parser.read(ROOT / "lib/systemd/system" / caramos_business.ENROLL_UNIT)
        self.assertEqual("/etc/caramos-business/enroll-on-boot.json", parser["Unit"]["ConditionPathExists"])
        self.assertEqual("0", parser["Unit"]["StartLimitIntervalSec"])
        self.assertEqual("caramos-business-agent.service", parser["Unit"]["Before"])
        self.assertEqual(("oneshot", f"{HELPER} enroll-on-boot", "on-failure", "60"),
                         (parser["Service"]["Type"], parser["Service"]["ExecStart"], parser["Service"]["Restart"],
                          parser["Service"]["RestartSec"]))
        self.assertEqual("multi-user.target", parser["Install"]["WantedBy"])

    def test_toasts_clear_the_save_bar(self) -> None:
        """A refused save's toast covered "Hoàn tác" and "Lưu và gửi" for 8 seconds (GTK is not needed to check the
        wiring: the window marks its toast overlay while the bar shows, and the style lifts toasts there)."""

        window = (ROOT / "usr/lib/python3/dist-packages/caramos_business/ui/admin_window.py").read_text()
        self.assertIn('("above-save-bar")', window)
        style = (ROOT / "usr/share/caramos-business/style.css").read_text()
        rule = style[style.index(".above-save-bar > toast"):]
        self.assertIn("margin-bottom: 64px;", rule[:rule.index("}")])

    def test_machine_page_shows_what_was_saved(self) -> None:
        """The machine page's asset section was built once: after "Lưu thông tin tài sản" its history still said
        "Chưa có gì". It is built again after each save, as on the asset's own page."""

        page = (ROOT / "usr/lib/python3/dist-packages/caramos_business/ui/machines.py").read_text()
        self.assertIn("AssetForm(self.ctx, self.machine_id, saved=self.build_asset_form)", page)
        assets_page = (ROOT / "usr/lib/python3/dist-packages/caramos_business/ui/assets_page.py").read_text()
        self.assertIn("saved=lambda: self.refresh(force=True)", assets_page)

    def test_hostname_unit(self) -> None:
        parser = configparser.ConfigParser(strict=False, interpolation=None)
        parser.optionxform = str
        parser.read(ROOT / "lib/systemd/system" / caramos_business.HOSTNAME_UNIT)
        self.assertEqual("/etc/caramos-business/enroll-on-boot.json", parser["Unit"]["ConditionPathExists"])
        before = parser["Unit"]["Before"].split()
        for unit in ("display-manager.service", "systemd-user-sessions.service", caramos_business.ENROLL_UNIT):
            self.assertIn(unit, before)
        self.assertNotIn("network-online.target", parser["Unit"].get("After", ""), "the login screen waits for it")
        self.assertEqual(("oneshot", f"{HELPER} enroll-hostname"),
                         (parser["Service"]["Type"], parser["Service"]["ExecStart"]))
        self.assertNotIn("Restart", parser["Service"])
        self.assertEqual("multi-user.target", parser["Install"]["WantedBy"])


if __name__ == "__main__":
    unittest.main()


class ResultTextTests(unittest.TestCase):
    """How the machine page words a command's result (the GTK module needs GTK 4, not a display)."""

    def setUp(self) -> None:
        try:
            from caramos_business.ui import machines
        except (ImportError, ValueError) as exc:  # no GTK 4 / libadwaita here
            self.skipTest(f"GTK 4 is not available: {exc}")
        self.machines = machines

    def test_results(self) -> None:
        state_text = self.machines.state_text
        self.assertEqual("Done: đã gửi", state_text("done", "đã gửi", "inventory"))
        self.assertEqual("It was sent while the machine was off or restarting, so it was not done.",
                         state_text("expired", text.BEFORE_THIS_BOOT, "lock"))
        self.assertEqual("It came too late and was not done.", state_text("expired", "the command expired at …", "lock"))
        self.assertEqual("The employee refused.", state_text("refused", "người dùng từ chối", "remote_help"))

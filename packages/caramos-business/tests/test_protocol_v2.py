"""caramos_business.protocol against part 2's vectors (tests/protocol-examples/v2, made by make_v2.py; the Rust
agent's tests read the same files): machine keys, MACs, sealed secrets, the signed format 2 policy, effective
settings, commands, and the checks of inventory and health."""

from __future__ import annotations

import base64
import copy
import datetime
import json
import unittest
from pathlib import Path

from caramos_business import protocol

V2 = Path(__file__).parent / "protocol-examples" / "v2"
KEYS = json.loads((V2 / "keys.json").read_text(encoding="utf-8"))
SIGN_PUBLIC = base64.b64decode(KEYS["admin_sign_public"])
ADMIN_BOX = base64.b64decode(KEYS["admin_box_seed"])
MACHINE_BOX = base64.b64decode(KEYS["machine_box_seed"])
MACHINE_ID = KEYS["machine_id"]
OTHER_MACHINE_ID = "0d9e8f7a-6b5c-4d3e-9f21-0a1b2c3d4e5f"
NOW = datetime.datetime(2026, 11, 21, 15, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=7)))


def vector(name: str) -> object:
    return json.loads((V2 / name).read_text(encoding="utf-8"))


class MachineKeyTests(unittest.TestCase):
    def test_public_halves(self) -> None:
        self.assertEqual(KEYS["admin_box_public"], protocol.b64(protocol.box_public(ADMIN_BOX)))
        self.assertEqual(KEYS["machine_box_public"], protocol.b64(protocol.box_public(MACHINE_BOX)))
        seed = base64.b64decode(KEYS["admin_sign_seed"])
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        self.assertEqual(SIGN_PUBLIC, protocol.public_bytes(Ed25519PrivateKey.from_private_bytes(seed)))

    def test_both_sides_derive_the_same_keys(self) -> None:
        admin_side = protocol.machine_keys(ADMIN_BOX, base64.b64decode(KEYS["machine_box_public"]))
        machine_side = protocol.machine_keys(MACHINE_BOX, base64.b64decode(KEYS["admin_box_public"]))
        self.assertEqual(admin_side, machine_side)
        self.assertEqual(KEYS["shared_secret_hex"], protocol.shared_secret(ADMIN_BOX, base64.b64decode(
            KEYS["machine_box_public"])).hex())
        self.assertEqual((KEYS["mac_key_hex"], KEYS["seal_key_hex"]), (admin_side[0].hex(), admin_side[1].hex()))

    def test_new_box_keys(self) -> None:
        private = protocol.new_box_key()
        self.assertEqual(32, len(private))
        self.assertNotEqual(private, protocol.new_box_key())
        with self.assertRaises(protocol.ProtocolError):
            protocol.machine_keys(private, b"\x00" * 31)


class MacTests(unittest.TestCase):
    mac_key = bytes.fromhex(KEYS["mac_key_hex"])

    def test_vectors(self) -> None:
        for name in ("mac.json", "mac-wait.json"):
            example = vector(name)
            with self.subTest(name):
                body = example["body"].encode("utf-8")
                self.assertEqual(example["message"].encode("utf-8"),
                                 protocol.mac_message(example["method"], example["path"], example["time"], body))
                self.assertEqual(example["mac"], protocol.request_mac(self.mac_key, example["method"],
                                                                      example["path"], example["time"], body))
                self.assertTrue(protocol.check_request_mac(self.mac_key, example["method"], example["path"],
                                                           str(example["time"]), body, example["mac"]))

    def test_anything_changed_fails(self) -> None:
        example = vector("mac.json")
        body = example["body"].encode("utf-8")
        args = (example["method"], example["path"], str(example["time"]), body)
        for changed in (("GET",) + args[1:], (args[0], args[1] + "?x=1") + args[2:],
                        args[:2] + (str(example["time"] + 1), body), args[:3] + (body + b" ",)):
            with self.subTest(changed=changed[:3]):
                self.assertFalse(protocol.check_request_mac(self.mac_key, *changed, example["mac"]))
        self.assertFalse(protocol.check_request_mac(self.mac_key, *args, "not base64!"))
        self.assertFalse(protocol.check_request_mac(b"\x00" * 32, *args, example["mac"]))

    def test_auth_headers(self) -> None:
        headers = protocol.auth_headers(MACHINE_ID, self.mac_key, "GET", "/caramos-business/v1/wait?after=4&serial=12",
                                        now=1795200000)
        self.assertEqual({"X-Caramos-Machine": MACHINE_ID, "X-Caramos-Time": "1795200000",
                          "X-Caramos-Mac": vector("mac-wait.json")["mac"]}, headers)


class SealTests(unittest.TestCase):
    seal_key = bytes.fromhex(KEYS["seal_key_hex"])

    def test_vector(self) -> None:
        example = vector("sealed.json")
        self.assertEqual(example["sealed"], protocol.seal(self.seal_key, MACHINE_ID, example["plaintext"],
                                                          bytes.fromhex(example["nonce_hex"])))
        self.assertEqual(example["plaintext"], protocol.unseal(self.seal_key, MACHINE_ID, example["sealed"]))

    def test_round_trip_with_a_fresh_nonce(self) -> None:
        secrets = {"wifi": {"Văn phòng": "mật-khẩu-không-dấu-12"}}
        first = protocol.seal(self.seal_key, MACHINE_ID, secrets)
        self.assertNotEqual(first, protocol.seal(self.seal_key, MACHINE_ID, secrets))
        self.assertEqual(secrets, protocol.unseal(self.seal_key, MACHINE_ID, first))

    def test_only_that_machine_opens_it(self) -> None:
        sealed = vector("sealed.json")["sealed"]
        with self.assertRaises(protocol.ProtocolError):
            protocol.unseal(self.seal_key, OTHER_MACHINE_ID, sealed)
        with self.assertRaises(protocol.ProtocolError):
            protocol.unseal(bytes(32), MACHINE_ID, sealed)
        broken = base64.b64decode(sealed)
        broken = broken[:-1] + bytes([broken[-1] ^ 1])
        with self.assertRaises(protocol.ProtocolError):
            protocol.unseal(self.seal_key, MACHINE_ID, base64.b64encode(broken).decode())

    def test_the_policy_carries_the_vector(self) -> None:
        self.assertEqual(vector("sealed.json")["sealed"], vector("policy.json")["machines"][MACHINE_ID]["sealed"])


class PolicyV2Tests(unittest.TestCase):
    def test_signed_policy(self) -> None:
        policy = protocol.verify_signed_policy(vector("signed-policy.json"), SIGN_PUBLIC)
        self.assertEqual(vector("policy.json"), policy)
        self.assertEqual((V2 / "remote-help-cert.pem").read_text(encoding="ascii"), policy["remote_help_cert"])
        tampered = dict(vector("signed-policy.json"))
        tampered["policy"] = tampered["policy"].replace("amis.misa.vn", "amis.misa.vm")
        with self.assertRaises(protocol.ProtocolError):
            protocol.verify_signed_policy(tampered, SIGN_PUBLIC)

    def test_effective_settings(self) -> None:
        policy = vector("policy.json")
        self.assertEqual(vector("effective-machine.json"), protocol.effective_settings(policy, MACHINE_ID))
        self.assertEqual(vector("effective-other-machine.json"), protocol.effective_settings(policy, OTHER_MACHINE_ID))
        self.assertEqual(policy["settings"], protocol.effective_settings(policy, "11111111-2222-4333-8444-555555555555"))

    def test_sources(self) -> None:
        sources = protocol.setting_sources(vector("policy.json"), MACHINE_ID)
        self.assertEqual("company", sources["wallpaper"])
        self.assertEqual("department:ke-toan", sources["usb"])
        self.assertEqual(f"machine:{MACHINE_ID}", sources["screen_lock"])
        self.assertNotIn("firewall", sources)
        self.assertNotIn("inventory", sources, "opt-in: the vector policy does not turn it on")
        self.assertEqual("department:kinh-doanh",
                         protocol.setting_sources(vector("policy.json"), OTHER_MACHINE_ID)["browser"])

    def test_invalid_policies(self) -> None:
        names = sorted(path.name for path in V2.glob("invalid-*.json"))
        self.assertGreaterEqual(len(names), 13)
        for name in names:
            with self.subTest(name), self.assertRaises(protocol.ProtocolError):
                protocol.validate_policy(vector(name))

    def test_section_errors_say_where(self) -> None:
        with self.assertRaises(protocol.ProtocolError) as caught:
            protocol.validate_policy(vector("invalid-share-percent-u.json"))
        self.assertEqual(("shares", "department:ke-toan"), (caught.exception.section, caught.exception.scope))

    def test_limits(self) -> None:
        base = vector("policy.json")

        def refused(**sections: object) -> None:
            policy = copy.deepcopy(base)
            policy["settings"].update(sections)
            with self.subTest(sections=str(sections)[:80]), self.assertRaises(protocol.ProtocolError):
                protocol.validate_policy(policy)

        def accepted(**sections: object) -> None:
            policy = copy.deepcopy(base)
            policy["settings"].update(sections)
            with self.subTest(sections=str(sections)[:80]):
                protocol.validate_policy(policy)

        share = {"name": "Kế toán", "url": "smb://nas/ketoan"}
        accepted(shares=[dict(share, url=f"smb://nas/s{i}") for i in range(20)])
        refused(shares=[dict(share, url=f"smb://nas/s{i}") for i in range(21)])
        refused(shares=[dict(share, name="x" * 61)])
        refused(shares=[share, share])
        browser = base["settings"]["browser"]
        accepted(browser=dict(browser, block=[f"site{i}.vn" for i in range(500)]))
        refused(browser=dict(browser, block=[f"site{i}.vn" for i in range(501)]))
        for domain in ("Facebook.com", "facebook", "face book.com", "192.168.1.1", "-a.com", "a..com"):
            refused(browser=dict(browser, block=[domain]))
        accepted(browser=dict(browser, block=["xn--bng-da-6va.vn", "a-b.c.vn"], homepage=None, block_hours=None))
        refused(browser=dict(browser, homepage="ftp://x.vn"))
        refused(browser=dict(browser, bookmarks=[{"name": "x", "url": "javascript:alert(1)"}]))
        refused(browser=dict(browser, bookmarks=[{"name": "x", "url": "https://a.vn"}] * 51))
        refused(browser=dict(browser, block_hours={"days": [1], "ranges": [["08:00", "08:00"]]}))
        refused(browser=dict(browser, block_hours={"days": [], "ranges": [["08:00", "09:00"]]}))
        refused(browser=dict(browser, block_hours={"days": [8], "ranges": [["08:00", "09:00"]]}))
        refused(browser=dict(browser, block_hours={"days": [1], "ranges": [["08:00", "09:00"]] * 7}))
        refused(browser=dict(browser, block_hours={"days": [1], "ranges": [["8:00", "09:00"]]}))
        refused(browser=dict(browser, safe_search="yes"))
        printer = base["settings"]["printers"][0]
        accepted(printers=[dict(printer, name=f"p{i}", default=False) for i in range(20)])
        refused(printers=[dict(printer, name=f"p{i}", default=False) for i in range(21)])
        refused(printers=[dict(printer, uri="ipp://user@192.168.1.50/ipp/print")])
        refused(printers=[dict(printer, uri="ipp:///ipp/print")])
        accepted(printers=[dict(printer, uri="ipps://may-in.local:631/ipp/print")])
        shutdown = base["settings"]["power"]["shutdown"]
        for change in ({"warn_minutes": 0}, {"postpone_minutes": 4}, {"postpone_minutes": 121},
                       {"max_postpones": 6}, {"laptops": "hibernate"}, {"time": "24:00"}, {"days": [1, 1]}):
            refused(power={"shutdown": dict(shutdown, **change), "wake": None})
        accepted(power={"shutdown": None, "wake": {"days": [1, 2, 3, 4, 5, 6, 7], "time": "07:45"}})
        accepted(apps={"required": [f"app-{i}" for i in range(50)], "forbidden": []})
        refused(apps={"required": [f"app-{i}" for i in range(51)], "forbidden": []})
        refused(apps={"required": ["VLC"], "forbidden": []})
        refused(apps={"required": ["x" * 41], "forbidden": []})
        refused(screen_lock={"idle_minutes": 121, "on_suspend": True})
        accepted(screen_lock={"idle_minutes": 120, "on_suspend": False})
        refused(firewall={"enabled": False})
        accepted(firewall={"enabled": True})
        refused(inventory={"enabled": False})
        refused(inventory={})
        accepted(inventory={"enabled": True})
        accepted(inventory=None)
        accepted(wifi=[{"ssid": "Văn phòng tầng 2", "security": "open", "hidden": True}])
        refused(wifi=[{"ssid": "ư" * 17, "security": "open", "hidden": False}])  # 34 bytes
        refused(wifi=[{"ssid": "", "security": "open", "hidden": False}])
        refused(wifi=[{"ssid": "a", "security": "wep", "hidden": False}])
        refused(wifi=[{"ssid": f"n{i}", "security": "open", "hidden": False} for i in range(11)])
        refused(usb=None, wallpaper={"default": "f" * 64, "periods": [], "lock": False})  # a picture not in files
        accepted(usb=None, browser=None, unknown_later_section={"anything": 1})

    def test_departments_and_machines(self) -> None:
        base = vector("policy.json")
        many = copy.deepcopy(base)
        many["departments"] = {f"phong-{i}": {"name": f"Phòng {i}", "settings": {}} for i in range(51)}
        many["members"] = {}
        with self.assertRaises(protocol.ProtocolError):
            protocol.validate_policy(many)
        for change in ({"departments": {"ke-toan": {"name": "", "settings": {}}}},
                       {"departments": {"x" * 33: {"name": "x", "settings": {}}}},
                       {"members": {"not-a-uuid": "ke-toan"}},
                       {"machines": {MACHINE_ID: {"settings": {"usb": {"storage": "x"}}}}},
                       {"machines": {MACHINE_ID: {"settings": {}, "sealed": "c2hvcnQ="}}},
                       {"admin_box_key": "c2hvcnQ="}):
            policy = copy.deepcopy(base)
            policy.update(change)
            with self.subTest(change=str(change)[:60]), self.assertRaises(protocol.ProtocolError):
                protocol.validate_policy(policy)

    def test_signing_refuses_over_one_mebibyte(self) -> None:
        key = protocol.new_key()
        policy = copy.deepcopy(vector("policy.json"))
        policy["machines"] = {f"00000000-0000-4000-8000-{i:012d}": {"settings": {"browser": {
            "homepage": None, "bookmarks": [], "block": [f"very-long-website-name-{j:04d}.vn" for j in range(60)],
            "block_hours": None, "safe_search": False}}} for i in range(500)}
        with self.assertRaises(protocol.ProtocolError) as caught:
            protocol.sign_policy(key, policy)
        self.assertIn("KB", str(caught.exception))

    def test_used_images(self) -> None:
        policy = vector("policy.json")
        sha = next(iter(policy["files"]))
        self.assertEqual([sha], protocol.used_images(policy))


class CommandTests(unittest.TestCase):
    def check(self, name: str, last_seq: int = 0, department: str | None = "ke-toan") -> dict:
        return protocol.check_command(vector(name), SIGN_PUBLIC, MACHINE_ID, department, last_seq, NOW)

    def test_good_commands(self) -> None:
        message = self.check("command-message.json")
        self.assertEqual(("message", 41), (message["action"], message["seq"]))
        self.assertEqual({"title": "Họp 15h", "body": "Phòng họp tầng 3.", "ack": True}, message["args"])
        self.assertEqual("lock", self.check("command-department.json")["action"])
        self.assertEqual("sync", self.check("command-all.json")["action"])

    def test_refused_commands(self) -> None:
        for name, state in (("command-tampered.json", "refused"), ("command-bad-action.json", "refused"),
                            ("command-bad-args.json", "refused"), ("command-expired.json", "expired"),
                            ("command-other-department.json", "ignored")):
            with self.subTest(name), self.assertRaises(protocol.CommandRefused) as caught:
                self.check(name)
            self.assertEqual(state, caught.exception.state)

    def test_seq_and_department(self) -> None:
        with self.assertRaises(protocol.CommandRefused) as caught:
            self.check("command-message.json", last_seq=41)
        self.assertEqual("ignored", caught.exception.state)
        with self.assertRaises(protocol.CommandRefused):
            self.check("command-department.json", department=None)
        self.assertEqual("lock", self.check("command-other-department.json", department="kinh-doanh")["action"])

    def test_sign_and_verify(self) -> None:
        key = protocol.new_key()
        command = {"seq": 1, "id": "11111111-2222-4333-8444-555555555555", "targets": {"departments": ["ke-toan"]},
                   "action": "remote_help", "args": {"admin_host": "192.168.1.5", "port": 5501, "mode": "control",
                                                     "admin_name": "Minh (IT)"},
                   "issued": "2026-11-21T14:00:00+07:00", "expires": "2026-11-21T14:03:00+07:00"}
        envelope = protocol.sign_command(key, command)
        self.assertEqual(command, protocol.verify_command(envelope, protocol.public_bytes(key)))
        with self.assertRaises(protocol.ProtocolError):  # the admin never makes a command for more than a day
            protocol.sign_command(key, dict(command, expires="2026-11-22T14:00:01+07:00"))
        with self.assertRaises(protocol.ProtocolError):
            protocol.sign_command(key, dict(command, expires=command["issued"]))

    def test_every_action_and_its_arguments(self) -> None:
        base = {"seq": 1, "id": "11111111-2222-4333-8444-555555555555", "targets": {"all": True},
                "issued": "2026-11-21T14:00:00+07:00", "expires": "2026-11-21T14:10:00+07:00"}
        good = {"sync": {}, "inventory": {}, "lock": {}, "update": {},
                "message": {"title": "T", "body": "dòng 1\ndòng 2", "ack": False},
                "logout": {"warn_seconds": 0}, "restart": {"warn_seconds": 900}, "shutdown": {"warn_seconds": 60},
                "cancel": {"id": "11111111-2222-4333-8444-555555555555"},
                "remote_help": {"admin_host": "10.0.0.2", "port": 1025, "mode": "view", "admin_name": ""},
                "usb_unlock": {"minutes": 240}}
        self.assertEqual(set(protocol.ACTIONS), set(good))
        for action, args in good.items():
            with self.subTest(action=action):
                protocol.validate_command(dict(base, action=action, args=args))
        bad = [("sync", {"x": 1}), ("message", {"title": "", "body": "", "ack": False}),
               ("message", {"title": "x" * 81, "body": "", "ack": False}),
               ("message", {"title": "x", "body": "y" * 1001, "ack": False}),
               ("restart", {"warn_seconds": 901}), ("logout", {}), ("cancel", {"id": "x"}),
               ("remote_help", {"admin_host": "may-quan-ly", "port": 5501, "mode": "view", "admin_name": ""}),
               ("remote_help", {"admin_host": "10.0.0.2", "port": 80, "mode": "view", "admin_name": ""}),
               ("remote_help", {"admin_host": "10.0.0.2", "port": 5501, "mode": "shell", "admin_name": ""}),
               ("usb_unlock", {"minutes": 0}), ("shell", {})]
        for action, args in bad:
            with self.subTest(action=action, args=args), self.assertRaises(protocol.ProtocolError):
                protocol.validate_command(dict(base, action=action, args=args))
        for targets in ({}, {"all": False}, {"machines": []}, {"machines": ["x"]}, {"departments": ["Kế toán"]},
                        {"all": True, "machines": [MACHINE_ID]}):
            with self.subTest(targets=targets), self.assertRaises(protocol.ProtocolError):
                protocol.validate_command(dict(base, action="sync", args={}, targets=targets))


class ReportTests(unittest.TestCase):
    machine = {"name": "kt-01", "ip": "192.168.1.20", "mac": "52:54:00:12:34:56", "edition": "cinnamon",
               "version": "1.4.0"}
    health = {"disk_free_pct": 23, "disk_health": "ok", "battery_health_pct": None,
              "updates": {"security": 3, "other": 12}, "reboot_required": False, "firewall": "on",
              "caramos_version": "1.4.0", "uptime_hours": 51, "applied": {"browser": "ok", "printers": "failed: no answer"}}

    def test_checkin(self) -> None:
        report = protocol.validate_checkin({"machine_id": MACHINE_ID, "machine": self.machine, "policy_serial": 12,
                                            "users": [], "health": self.health,
                                            "capabilities": list(protocol.CAPABILITIES)})
        self.assertEqual(self.health, {key: report["health"][key] for key in self.health})
        # Part 3's keys, for a 0.2 agent's health: their defaults.
        self.assertEqual({"memory_mb": None, "encryption": "unknown", "screen_lock_on": None, "usb_storage": None,
                          "frozen": False, "freeze_configured": False, "last_maintenance": None,
                          "maintenance_result": "", "last_snapshot": None, "snapshot_space_mb": None},
                         {key: value for key, value in report["health"].items() if key not in self.health})
        self.assertEqual(list(protocol.CAPABILITIES), report["capabilities"])
        bare = protocol.validate_checkin({"machine": self.machine, "policy_serial": None, "users": []})
        self.assertNotIn("health", bare)

    def test_bad_health(self) -> None:
        for change in ({"disk_free_pct": 101}, {"disk_free_pct": "23"}, {"disk_health": "good"},
                       {"firewall": "maybe"}, {"updates": {"security": -1}}, {"reboot_required": "no"},
                       {"applied": {"browser": "broken"}}, {"applied": {"Bad Section": "ok"}},
                       {"applied": {"browser": "failed: " + "x" * 200}}, {"caramos_version": "bản mới"}):
            with self.subTest(change=change), self.assertRaises(protocol.ProtocolError):
                protocol.validate_health(dict(self.health, **change))
        for capabilities in ("wifi", ["Wi-Fi"], ["x"] * 65):
            with self.subTest(capabilities=str(capabilities)[:30]), self.assertRaises(protocol.ProtocolError):
                protocol.validate_capabilities(capabilities)

    def test_inventory(self) -> None:
        inventory = {
            "collected": "2026-11-21T09:00:00+07:00", "hash": "a" * 64,
            "system": {"vendor": "Dell Inc.", "product": "OptiPlex 3080", "serial": "8XK2Q53", "bios": "2.18.0",
                       "chassis": "desktop", "boot_time": "2026-11-21T07:58:00+07:00"},
            "cpu": {"model": "Intel(R) Core(TM) i5-10500", "cores": 6, "threads": 12},
            "memory": {"total_mb": 7834, "modules": [{"size_mb": 8192, "type": "DDR4", "speed_mts": 2666,
                                                      "slot": "DIMM1"}]},
            "disks": [{"name": "nvme0n1", "model": "KINGSTON", "serial": "50026B", "size_gb": 256,
                       "rotational": False, "transport": "nvme", "health": "ok"}],
            "batteries": [], "monitors": [{"connector": "HDMI-A-1", "name": "DELL P2419H", "serial": ""}],
            "network": [{"name": "enp3s0", "mac": "aa:bb:cc:dd:ee:ff", "ipv4": "192.168.1.20", "wired": True}],
            "os": {"caramos": "1.4.0", "edition": "cinnamon", "kernel": "6.14.0-35-generic"},
            "apps": [{"id": "vlc", "name": "VLC", "version": "3.0.20", "source": "deb"}],
            "something_later": {"kept": False}}
        cleaned = protocol.validate_inventory(inventory)
        self.assertNotIn("something_later", cleaned)
        self.assertEqual("OptiPlex 3080", cleaned["system"]["product"])
        self.assertEqual([], protocol.validate_inventory({"collected": "", "hash": ""})["disks"])
        for change in ({"hash": "nope"}, {"system": {"chassis": "tower"}}, {"cpu": {"cores": "6"}},
                       {"apps": [{"id": "x", "source": "snap"}]}, {"monitors": [{"name": "x" * 201}]},
                       {"apps": [{"id": str(i)} for i in range(501)]}, {"disks": {"name": "sda"}}):
            with self.subTest(change=str(change)[:50]), self.assertRaises(protocol.ProtocolError):
                protocol.validate_inventory(dict(inventory, **change))

    def test_result_help(self) -> None:
        # /register with a code is part 3's /pair/start and /pair/finish now: test_protocol_v3.py.
        result = {"id": "00000000-0000-4000-8000-000000000041", "state": "done", "detail": "đã đọc: minh, lan",
                  "time": "2026-11-21T14:01:00+07:00"}
        self.assertEqual(result, protocol.validate_result(result))
        for change in ({"state": "ok"}, {"detail": "x" * 301}, {"id": "41"}):
            with self.subTest(change=change), self.assertRaises(protocol.ProtocolError):
                protocol.validate_result(dict(result, **change))
        request = {"user": "minh", "note": "Máy in không in được.", "time": "2026-11-21T14:01:00+07:00"}
        self.assertEqual(request, protocol.validate_help(request))
        for change in ({"note": "x" * 301}, {"user": "Minh Nguyễn"}):
            with self.subTest(change=change), self.assertRaises(protocol.ProtocolError):
                protocol.validate_help(dict(request, **change))


if __name__ == "__main__":
    unittest.main()

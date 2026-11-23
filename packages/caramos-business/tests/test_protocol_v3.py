"""PROTOCOL.md part 3 (version 0.3) against its test vectors in protocol-examples/v3: SPAKE2 pairing, enrolment
files, the HMAC of GET requests, the new sections and the admin's rules for them, the per-session key of remote
help, removal notices, ticket lists, health and the inventory's app fields."""

from __future__ import annotations

import datetime
import hashlib
import json
import unittest
from pathlib import Path

from caramos_business import admin, licences, protocol, tickets

V3 = Path(__file__).parent / "protocol-examples" / "v3"
KEYS = json.loads((V3 / "keys.json").read_text(encoding="utf-8"))
ADMIN_KEY = protocol.unb64(KEYS["admin_sign_public"], 32)
MACHINE_ID = KEYS["machine_id"]
OTHER_MACHINE_ID = "0d9e8f7a-6b5c-4d3e-9f21-0a1b2c3d4e5f"
MAC_KEY = bytes.fromhex(KEYS["mac_key_hex"])
SEAL_KEY = bytes.fromhex(KEYS["seal_key_hex"])
TOKEN = bytes(range(200, 232))


def vector(name: str) -> dict:
    return json.loads((V3 / name).read_text(encoding="utf-8"))


def entropy(seed: bytes):
    """make_v3.py's stand-in for os.urandom."""

    counter = [0]

    def take(count: int) -> bytes:
        out = b""
        while len(out) < count:
            out += hashlib.sha256(seed + counter[0].to_bytes(4, "big")).digest()
            counter[0] += 1
        return out[:count]

    return take


class PairingVectorTests(unittest.TestCase):
    def setUp(self) -> None:
        try:
            import spake2
        except ImportError as exc:  # a Build-Depends; only missing on a bare host
            self.skipTest(f"python3-spake2 is not installed: {exc}")
        self.spake2 = spake2
        self.data = vector("pair-spake2.json")

    def sides(self, code: bytes = b"482913"):
        ids = {"idA": protocol.PAIR_ID_EMPLOYEE, "idB": protocol.PAIR_ID_ADMIN}
        employee = self.spake2.SPAKE2_A(code, entropy_f=entropy(self.data["entropy_seed_employee"].encode()), **ids)
        admin_side = self.spake2.SPAKE2_B(b"482913", entropy_f=entropy(self.data["entropy_seed_admin"].encode()),
                                          **ids)
        return employee, admin_side

    def test_spake2_messages_keys_and_transcript(self) -> None:
        data = self.data
        self.assertEqual((data["idA"].encode(), data["idB"].encode()),
                         (protocol.PAIR_ID_EMPLOYEE, protocol.PAIR_ID_ADMIN))
        employee, admin_side = self.sides()
        msg_a, msg_b = employee.start(), admin_side.start()
        self.assertEqual(data["start_request"]["msg"], protocol.b64(msg_a))
        self.assertEqual(data["start_answer"]["msg"], protocol.b64(msg_b))
        self.assertEqual(protocol.unb64(data["start_request"]["msg"]), protocol.validate_pair_start(
            data["start_request"]))
        key = employee.finish(msg_b)
        self.assertEqual(key, admin_side.finish(msg_a))
        self.assertEqual(data["K_hex"], key.hex())
        k_employee, k_admin = protocol.pair_keys(key)
        self.assertEqual((data["k_employee_hex"], data["k_admin_hex"]), (k_employee.hex(), k_admin.hex()))
        answer = data["start_answer"]
        finish = data["finish_request"]
        transcript = protocol.pair_transcript(answer["session"], data["start_request"]["msg"], answer["msg"],
                                              answer["admin_name"], answer["admin_key"], answer["admin_box_key"],
                                              finish["box_key"], finish["machine"])
        self.assertEqual(data["T"].encode("utf-8"), transcript)
        self.assertEqual(finish["confirm"], protocol.hmac_b64(k_employee, transcript))
        checked = protocol.validate_pair_finish(finish)
        self.assertEqual(finish["machine"], checked["sent_machine"])
        done = data["finish_answer"]
        self.assertEqual(done["confirm"], protocol.hmac_b64(k_admin, protocol.answer_message(
            transcript, done["machine_id"], done["state"])))
        self.assertFalse(protocol.same_mac(k_admin, protocol.answer_message(transcript, done["machine_id"], "pending"),
                                           done["confirm"]), "the state is covered")

    def test_a_wrong_code_gives_other_keys(self) -> None:
        data = self.data
        ids = {"idA": protocol.PAIR_ID_EMPLOYEE, "idB": protocol.PAIR_ID_ADMIN}
        employee = self.spake2.SPAKE2_A(b"482913", entropy_f=entropy(data["entropy_seed_employee"].encode()), **ids)
        wrong = self.spake2.SPAKE2_B(b"000000", entropy_f=entropy(data["entropy_seed_admin"].encode()), **ids)
        msg_a = employee.start()
        wrong.start()
        wrong_key = wrong.finish(msg_a)
        self.assertEqual(data["wrong_code_admin_K_hex"], wrong_key.hex())
        self.assertNotEqual(data["K_hex"], wrong_key.hex())
        k_employee, _k_admin = protocol.pair_keys(wrong_key)
        transcript = data["T"].encode("utf-8")
        self.assertEqual(data["wrong_code_expected_confirm"], protocol.hmac_b64(k_employee, transcript))
        self.assertFalse(protocol.same_mac(k_employee, transcript, data["finish_request"]["confirm"]))

    def test_bad_messages(self) -> None:
        msg = protocol.unb64(self.data["start_request"]["msg"])
        for body in ({"msg": protocol.b64(b"B" + msg[1:])}, {"msg": protocol.b64(msg[:32])}, {"msg": 5}, []):
            with self.subTest(body=str(body)[:30]), self.assertRaises(protocol.ProtocolError):
                protocol.validate_pair_start(body)
        finish = self.data["finish_request"]
        for change in ({"session": "x"}, {"box_key": "c2hvcnQ="}, {"confirm": "c2hvcnQ="},
                       {"machine": dict(finish["machine"], ip="nope")}):
            with self.subTest(change=change), self.assertRaises(protocol.ProtocolError):
                protocol.validate_pair_finish(dict(finish, **change))


class EnrolmentVectorTests(unittest.TestCase):
    def test_file(self) -> None:
        data = vector("enroll-file.json")
        self.assertEqual(data, protocol.validate_enroll_file(data))
        self.assertEqual(TOKEN, protocol.unb64(data["token"], 32))
        late = datetime.datetime(2099, 1, 2, tzinfo=datetime.timezone.utc)
        for change, now in (({"format": 2}, None), ({"kind": "caramos-business-pair"}, None),
                            ({"fingerprint": "0" * 16}, None), ({"admin_key": "c2hvcnQ="}, None),
                            ({"admin_box_key": None}, None), ({"admin_box_key": "c2hvcnQ="}, None),
                            ({"token": "c2hvcnQ="}, None), ({"admin_url": "https://192.168.1.5:47022"}, None),
                            ({"admin_url": "http://nas.local:47022"}, None), ({"token_id": "A1B2"}, None),
                            ({"max_uses": 501}, None), ({"hostname_prefix": "Phong May"}, None),
                            ({"department": "Kế toán"}, None), ({}, late)):
            with self.subTest(change=change), self.assertRaises(protocol.ProtocolError):
                protocol.validate_enroll_file(dict(data, **change), now)

    def test_register(self) -> None:
        data = vector("enroll-register.json")
        proof_key = protocol.enroll_proof_key(TOKEN)
        self.assertEqual(data["proof_key_hex"], proof_key.hex())
        self.assertEqual({"a1b2c3d4e5f60718": proof_key.hex()}, data["admin_keeps"]["enroll-keys.json"])
        request = data["request"]
        message = protocol.enroll_transcript(request["token_id"], request["time"], KEYS["admin_sign_public"],
                                             request["box_key"], request["machine"])
        self.assertEqual(data["E"].encode("utf-8"), message)
        self.assertEqual(request["proof"], protocol.hmac_b64(proof_key, message))
        checked = protocol.validate_register(request)
        self.assertEqual((request["machine"], request["box_key"]), (checked["sent_machine"], checked["box_key"]))
        answer = data["answer"]
        self.assertEqual(answer["confirm"], protocol.hmac_b64(proof_key, protocol.answer_message(
            message, answer["machine_id"], answer["state"])))
        for change in ({"token_id": "x"}, {"time": "1795200000"}, {"proof": "c2hvcnQ="}, {"box_key": None}):
            with self.subTest(change=change), self.assertRaises(protocol.ProtocolError):
                protocol.validate_register(dict(request, **change))


class RequestMacTests(unittest.TestCase):
    def test_policy_and_files(self) -> None:
        for name in ("mac-policy.json", "mac-files.json"):
            with self.subTest(name):
                data = vector(name)
                headers = data["headers"]
                self.assertEqual(data["message"].encode("ascii"), protocol.mac_message(
                    data["method"], data["path"], data["time"], b""))
                self.assertEqual(headers, protocol.auth_headers(MACHINE_ID, MAC_KEY, data["method"], data["path"], b"",
                                                                now=data["time"]))
                self.assertTrue(protocol.check_request_mac(MAC_KEY, data["method"], data["path"],
                                                           headers["X-Caramos-Time"], b"", headers["X-Caramos-Mac"]))


class SectionTests(unittest.TestCase):
    def test_policy_and_effective_settings(self) -> None:
        policy = vector("policy.json")
        protocol.validate_policy(policy)
        self.assertEqual(policy, protocol.verify_signed_policy(vector("signed-policy.json"), ADMIN_KEY))
        self.assertEqual(vector("effective-machine.json"), protocol.effective_settings(policy, MACHINE_ID))
        self.assertEqual(vector("effective-other-machine.json"), protocol.effective_settings(policy, OTHER_MACHINE_ID))
        self.assertEqual({"wifi": {"CongTy": "matkhau-wifi-123"}},
                         protocol.unseal(SEAL_KEY, MACHINE_ID, policy["machines"][MACHINE_ID]["sealed"]))
        self.assertIsNone(admin.freeze_problem(policy), "the admin signs this one")

    def test_invalid_sections(self) -> None:
        for path in sorted(V3.glob("invalid-*.json")):
            with self.subTest(path.name), self.assertRaises(protocol.ProtocolError) as caught:
                protocol.validate_policy(vector(path.name))
            self.assertIn(caught.exception.section, ("shared", "snapshots"))

    def test_the_admins_freeze_rules(self) -> None:
        without = vector("admin-invalid-freeze-without-maintenance.json")
        protocol.validate_policy(without)  # valid for the agent
        self.assertEqual("department:phong-may", admin.freeze_problem(without)[0])
        conflict = vector("policy-freeze-conflict.json")
        protocol.validate_policy(conflict)
        self.assertEqual(conflict, protocol.verify_signed_policy(vector("signed-policy-freeze-conflict.json"),
                                                                 ADMIN_KEY))
        scope, sentence = admin.freeze_problem(conflict)
        self.assertEqual("department:phong-may", scope)
        self.assertIn("tidying", sentence)
        snapshots = vector("policy.json")
        snapshots["departments"]["phong-may"]["settings"].pop("snapshots")  # the company's weekly snapshots apply
        self.assertIn("snapshots", admin.freeze_problem(snapshots)[1])


class RemoteHelpTests(unittest.TestCase):
    def test_session_key_sealed_in_the_command(self) -> None:
        command = protocol.verify_command(vector("command-remote-help.json"), ADMIN_KEY)
        protocol.validate_command(command)
        psk = vector("remote-help-psk.json")
        opened = protocol.unseal(SEAL_KEY, MACHINE_ID, command["args"]["psk"])
        self.assertEqual(psk["plaintext"], opened)
        self.assertEqual(psk["psk_file_line"], f"{opened['identity']}:{opened['key']}")
        self.assertEqual(bytes.fromhex(psk["nonce_hex"]), protocol.unb64(command["args"]["psk"])[:12])
        with self.assertRaises(protocol.ProtocolError):  # another machine cannot open it
            protocol.unseal(SEAL_KEY, OTHER_MACHINE_ID, command["args"]["psk"])
        self.assertEqual(psk["plaintext"], protocol.unseal(SEAL_KEY, MACHINE_ID, protocol.seal(
            SEAL_KEY, MACHINE_ID, psk["plaintext"])))
        for bad in (dict(command["args"], psk=5), dict(command["args"], psk="x" * 2000)):
            with self.subTest(psk=str(bad["psk"])[:10]), self.assertRaises(protocol.ProtocolError):
                protocol.validate_command(dict(command, args=bad))


class NoticeAndTicketTests(unittest.TestCase):
    def test_removal_notices(self) -> None:
        notice = protocol.verify_notice(vector("removed-notice.json"), ADMIN_KEY, MACHINE_ID)
        self.assertEqual({"kind": "removed", "machine_id": MACHINE_ID, "admin": "quan-ly",
                          "time": "2026-11-23T10:00:00+07:00"}, notice)
        for name in ("removed-notice-other.json", "removed-notice-tampered.json"):
            with self.subTest(name), self.assertRaises(protocol.ProtocolError):
                protocol.verify_notice(vector(name), ADMIN_KEY, MACHINE_ID)
        key = protocol.new_key()
        signed = protocol.sign_notice(key, MACHINE_ID, "quan-ly", "2026-11-23T10:00:00+07:00")
        self.assertEqual(vector("removed-notice.json")["notice"], signed["notice"], "the same compact text")

    def test_ticket_lists(self) -> None:
        listed = protocol.verify_tickets(vector("tickets.json"), ADMIN_KEY, MACHINE_ID)
        self.assertEqual(7, listed["version"])
        with self.assertRaises(protocol.ProtocolError):
            protocol.verify_tickets(vector("tickets.json"), ADMIN_KEY, OTHER_MACHINE_ID)
        lan = vector("tickets-user-lan.json")
        self.assertEqual(lan, {"version": listed["version"],
                               "tickets": [ticket for ticket in listed["tickets"] if ticket["user"] == "lan"]})
        self.assertEqual({"serial": 21, "commands": [], "tickets": 7}, vector("wait-answer.json"))

    def test_the_admin_makes_the_same_list(self) -> None:
        listed = json.loads(vector("tickets.json")["tickets"])
        tz = datetime.timezone(datetime.timedelta(hours=7))
        store = {"next": 8, "versions": {MACHINE_ID: 7}, "tickets": []}
        for item in listed["tickets"]:
            notes = [{"time": update["time"], "by": "caram", "text": update["text"], "public": True,
                      **({"status": update["status"]} if "status" in update else {})} for update in item["updates"]]
            notes.insert(0, {"time": item["created"], "by": "caram", "text": "Hỏng trống mực?", "public": False})
            store["tickets"].append({"id": item["id"], "machine_id": MACHINE_ID, "user": item["user"],
                                     "note": item["note"], "created": item["created"], "status": item["status"],
                                     "closed": item["updates"][-1]["time"] if item["status"] == "done" else None,
                                     "notes": notes})
        store["tickets"].append({"id": "HT-0001", "machine_id": OTHER_MACHINE_ID, "user": "lan", "note": "x",
                                 "created": "2026-11-01T08:00:00+07:00", "status": "new", "notes": []})
        made = tickets.machine_list(store, MACHINE_ID, datetime.datetime(2026, 11, 23, 11, 0, tzinfo=tz))
        self.assertEqual(listed, made)
        later = tickets.machine_list(store, MACHINE_ID, datetime.datetime(2026, 12, 22, 11, 0, tzinfo=tz))
        self.assertEqual(["HT-0007", "HT-0006"], [item["id"] for item in later["tickets"]],
                         "a ticket closed more than 30 days ago leaves the list")


class ReportVectorTests(unittest.TestCase):
    def test_health_and_capabilities(self) -> None:
        data = vector("health.json")
        self.assertEqual(data["health"], protocol.validate_health(data["health"]))
        self.assertEqual(data["capabilities"], protocol.validate_capabilities(data["capabilities"]))
        for change in ({"encryption": "bitlocker"}, {"usb_storage": "open"}, {"frozen": "no"},
                       {"memory_mb": -1}, {"last_snapshot": 5}, {"maintenance_result": "x" * 201},
                       {"snapshot_space_mb": "6780"}, {"screen_lock_on": "yes"}):
            with self.subTest(change=change), self.assertRaises(protocol.ProtocolError):
                protocol.validate_health(dict(data["health"], **change))

    def test_inventory_apps_and_their_classes(self) -> None:
        apps = vector("inventory-apps.json")["apps"]
        cleaned = protocol.validate_inventory({"collected": "", "hash": "", "apps": apps})
        self.assertEqual(apps, cleaned["apps"])
        index = {"google-chrome-stable": {"id": "chrome", "name": "Google Chrome", "class": "freeware", "note": {}},
                 "org.libreoffice.LibreOffice": {"id": "libreoffice", "name": "LibreOffice", "class": "free",
                                                 "note": {}}}
        self.assertEqual(["free", "freeware", "free"], [licences.classify(app, index) for app in apps])
        self.assertEqual("unknown", licences.classify(apps[1], {}), "unknown without the catalog's word")


if __name__ == "__main__":
    unittest.main()

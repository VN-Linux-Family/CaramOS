"""Pairing with a code (SPAKE2) and enrolment by file (PROTOCOL.md part 3), both sides through the real admin server
on this machine: the code that never travels, wrong codes counted until the window closes, the session limits, the
enrolment token's checks, replays and uses, and approval."""

from __future__ import annotations

import datetime
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from caramos_business import admin, client, protocol, server

try:
    from caramos_business import pairing
    import spake2  # noqa: F401 - a Build-Depends
except ImportError:  # pragma: no cover - only on a bare host
    pairing = None

MACHINE = {"name": "kt-01", "ip": "127.0.0.1", "mac": "52:54:00:00:00:01", "edition": "xfce", "version": "1.4.0"}


@unittest.skipIf(pairing is None, "python3-spake2 is not installed")
class PairingFixture(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state = self.root / "state"
        self.pairing_file = self.root / "pairing.json"
        admin.prepare_state(self.state)
        self.key = protocol.new_key()
        self.box = admin.ensure_box_key(self.root / "admin-box.key")
        admin.save_policy(admin.empty_draft(), self.key, "quan-ly", self.state, box_private=self.box)
        self.admin = server.Admin(self.key, "quan-ly", self.state, self.pairing_file, self.root / "admin-box.key")
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.admin))
        self.http.daemon_threads = True
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.port = self.http.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"

    def box_key(self) -> tuple[bytes, str]:
        private = protocol.new_box_key()
        return private, protocol.b64(protocol.box_public(private))

    def post(self, path: str, body: object) -> tuple[int, object]:
        return pairing.post_json(f"{self.url}{protocol.PREFIX}{path}", body)


class CodeTests(PairingFixture):
    def test_pairing_with_the_right_code(self) -> None:
        code = admin.open_pairing(600, self.pairing_file)["code"]
        private, box_key = self.box_key()
        answer = pairing.pair_with_code(self.url, code, MACHINE, box_key)
        self.assertEqual(("quan-ly", "approved"), (answer["admin_name"], answer["state"]))
        self.assertEqual(protocol.b64(protocol.public_bytes(self.key)), answer["admin_key"])
        self.assertEqual(protocol.b64(protocol.box_public(self.box)), answer["admin_box_key"])
        entry = admin.read_machines(self.state)[answer["machine_id"]]
        self.assertEqual((box_key, "code", "approved"), (entry["box_key"], entry["via"], entry["state"]))
        self.assertEqual("register", admin.read_audit(self.state)[0]["action"])
        # The keys work at once: the machine reads the settings with its MAC.
        mac_key, _seal = protocol.machine_keys(private, protocol.box_public(self.box))
        status, _signed = client.authed(self.url, answer["machine_id"], mac_key, "GET", protocol.PREFIX + "/policy")
        self.assertEqual(200, status)

    def test_the_code_never_travels(self) -> None:
        code = admin.open_pairing(600, self.pairing_file)["code"]
        sent: list[bytes] = []

        def spy(url: str, body: dict) -> tuple[int, object]:
            sent.append(json.dumps(body).encode())
            return pairing.post_json(url, body)

        pairing.pair_with_code(self.url, code, MACHINE, self.box_key()[1], post=spy)
        self.assertEqual(2, len(sent))
        self.assertFalse(any(code.encode() in body for body in sent))

    def test_a_wrong_code_is_counted_and_twenty_close_the_window(self) -> None:
        code = admin.open_pairing(600, self.pairing_file)["code"]
        wrong = f"{(int(code) + 1) % 1_000_000:06d}"
        with self.assertRaises(pairing.PairingError) as caught:
            pairing.pair_with_code(self.url, wrong, MACHINE, self.box_key()[1])
        self.assertEqual("The code is not right.", str(caught.exception))
        self.assertEqual(1, self.admin.sessions.failures)
        self.assertEqual({}, admin.read_machines(self.state))
        for _attempt in range(pairing.MAX_FAILURES - 2):
            with self.assertRaises(pairing.PairingError):
                pairing.pair_with_code(self.url, wrong, dict(MACHINE, ip="127.0.0.2"), self.box_key()[1])
        self.assertTrue(admin.pairing_open(self.pairing_file), "19 failures: still open")
        answer = pairing.pair_with_code(self.url, code, MACHINE, self.box_key()[1])
        self.assertEqual("approved", answer["state"], "the right code still works after 19 failures")
        with self.assertRaises(pairing.PairingError):
            pairing.pair_with_code(self.url, wrong, MACHINE, self.box_key()[1])
        self.assertFalse(admin.pairing_open(self.pairing_file), "the 20th failure closes the window")
        with self.assertRaises(pairing.PairingError) as caught:
            pairing.pair_with_code(self.url, code, MACHINE, self.box_key()[1])
        self.assertEqual("The admin machine is not adding machines now.", str(caught.exception))
        # A new window: a new code, and the count starts again.
        code = admin.open_pairing(600, self.pairing_file)["code"]
        self.assertEqual("approved", pairing.pair_with_code(self.url, code, MACHINE, self.box_key()[1])["state"])
        self.assertEqual(0, self.admin.sessions.failures)

    def test_closed_pairing_and_bad_requests(self) -> None:
        msg = {"msg": protocol.b64(b"A" + bytes(32))}
        self.assertEqual(403, self.post("/pair/start", msg)[0])
        admin.open_pairing(600, self.pairing_file)
        self.assertEqual(400, self.post("/pair/start", {"msg": "short"})[0])
        self.assertEqual(400, self.post("/pair/start", {"msg": protocol.b64(b"B" + bytes(32))})[0])
        finish = {"session": "6f1d2c3b-4a59-4e68-8d7c-1b2a3c4d5e6f", "machine": MACHINE,
                  "box_key": self.box_key()[1], "confirm": protocol.b64(bytes(32))}
        self.assertEqual((403, {"error": "session"}), self.post("/pair/finish", finish), "an unknown session")
        self.assertEqual(0, self.admin.sessions.failures, "an unknown session is not a guess")

    def test_a_session_is_used_once(self) -> None:
        code = admin.open_pairing(600, self.pairing_file)["code"]
        sent: list[tuple[str, dict]] = []

        def spy(url: str, body: dict) -> tuple[int, object]:
            sent.append((url, body))
            return pairing.post_json(url, body)

        pairing.pair_with_code(self.url, code, MACHINE, self.box_key()[1], post=spy)
        url, body = sent[1]
        self.assertEqual(403, pairing.post_json(url, body)[0], "a finish sent again finds no session")
        self.assertEqual(1, len(admin.read_machines(self.state)))

    def test_session_limits(self) -> None:
        admin.open_pairing(600, self.pairing_file)
        statuses = []
        for _attempt in range(pairing.SESSIONS_PER_IP + 1):
            employee = spake2.SPAKE2_A(b"123456", idA=protocol.PAIR_ID_EMPLOYEE, idB=protocol.PAIR_ID_ADMIN)
            statuses.append(self.post("/pair/start", {"msg": protocol.b64(employee.start())})[0])
        self.assertEqual([200] * pairing.SESSIONS_PER_IP + [429], statuses)
        sessions = pairing.Sessions()
        msg = spake2.SPAKE2_A(b"123456", idA=protocol.PAIR_ID_EMPLOYEE, idB=protocol.PAIR_ID_ADMIN).start()
        for number in range(pairing.MAX_SESSIONS):
            sessions.start("123456", msg, f"192.168.1.{number}", now=1000.0)
        with self.assertRaises(pairing.PairingBusy):
            sessions.start("123456", msg, "192.168.1.200", now=1000.0)
        sessions.start("123456", msg, "192.168.1.200", now=1000.0 + pairing.SESSION_SECONDS)  # the old ones ran out

    def test_approval(self) -> None:
        admin.write_options({"approve_machines": True}, self.state)
        code = admin.open_pairing(600, self.pairing_file)["code"]
        private, box_key = self.box_key()
        answer = pairing.pair_with_code(self.url, code, MACHINE, box_key)
        self.assertEqual("pending", answer["state"])
        mac_key, _seal = protocol.machine_keys(private, protocol.box_public(self.box))
        self.assertEqual((403, {"error": "pending"}), client.authed(self.url, answer["machine_id"], mac_key, "GET",
                                                                    protocol.PREFIX + "/policy"))
        with server.locked(self.state):
            admin.approve_machine(answer["machine_id"], self.state)
        self.assertEqual(200, client.authed(self.url, answer["machine_id"], mac_key, "GET",
                                            protocol.PREFIX + "/policy")[0])

    def test_a_forged_answer_is_refused(self) -> None:
        """A stranger answering for the admin cannot make the admin's confirmation without the code."""

        code = admin.open_pairing(600, self.pairing_file)["code"]

        def forger(url: str, body: dict) -> tuple[int, object]:
            status, answer = pairing.post_json(url, body)
            if url.endswith("/pair/finish") and status == 200:
                answer = dict(answer, state="approved" if answer["state"] == "pending" else "pending")
            return status, answer

        with self.assertRaises(pairing.PairingError):
            pairing.pair_with_code(self.url, code, MACHINE, self.box_key()[1], post=forger)

    def test_the_employee_side_through_the_client(self) -> None:
        code = admin.open_pairing(600, self.pairing_file)["code"]
        private = protocol.new_box_key()
        with mock.patch.object(client, "machine_info", return_value=dict(MACHINE)):
            with self.assertRaises(client.PairingError):
                client.pair("127.0.0.1", "12345", private, self.port)  # 5 digits
            config, state = client.pair("127.0.0.1", f" {code} ", private, self.port)
        self.assertEqual("approved", state)
        self.assertEqual(protocol.fingerprint(protocol.public_bytes(self.key)), config["fingerprint"])
        self.assertEqual(self.url, config["admin_url"])
        self.assertEqual({"admin_url", "admin_name", "admin_key", "admin_box_key", "fingerprint", "machine_id"},
                         set(config))
        self.assertEqual(protocol.b64(protocol.box_public(self.box)), config["admin_box_key"],
                         "the agent's first HMAC needs the admin's box key")
        with self.assertRaises(client.PairingError):  # nobody there
            with mock.patch.object(client, "machine_info", return_value=dict(MACHINE)):
                client.pair("127.0.0.1", code, private, 1)


class EnrolmentTests(PairingFixture):
    def token(self, **options) -> dict:
        chosen = pairing.validate_token_options(dict({"department": None, "days": 7, "max_uses": 30}, **options),
                                                admin.read_policy(self.state).get("departments") or {})
        with server.locked(self.state):
            return pairing.create_token(self.state, chosen, admin_url=self.url, admin_name="quan-ly",
                                        admin_key=protocol.b64(protocol.public_bytes(self.key)),
                                        admin_box_key=protocol.b64(protocol.box_public(self.box)),
                                        department_name="", by="caram")

    def enroll(self, data: dict, machine: dict | None = None, post=None, now: float | None = None) -> dict:
        extra = {"post": post} if post else {}
        return pairing.enroll_with_file(data, machine or MACHINE, self.box_key()[1], self.url, now=now, **extra)

    def test_enrolment_with_a_department(self) -> None:
        admin.save_policy({"departments": {"ke-toan": {"name": "Kế toán", "settings": {}}}}, self.key, "quan-ly",
                          self.state, box_private=self.box)
        data = self.token(department="ke-toan")
        protocol.validate_enroll_file(json.loads(json.dumps(data)))
        answer = self.enroll(data)
        self.assertEqual("approved", answer["state"])
        self.assertEqual(protocol.b64(protocol.box_public(self.box)), answer["admin_box_key"])
        entry = admin.read_machines(self.state)[answer["machine_id"]]
        self.assertEqual(f"enroll:{data['token_id']}", entry["via"])
        policy = admin.read_policy(self.state)
        self.assertEqual("ke-toan", policy["members"][answer["machine_id"]], "signed again with the membership")
        record = pairing.read_tokens(self.state)[data["token_id"]]
        self.assertEqual((1, [answer["machine_id"]]), (record["uses"], record["machines"]))

    def test_uses_run_out(self) -> None:
        data = self.token(max_uses=2)
        self.enroll(data)
        self.enroll(data, dict(MACHINE, mac="52:54:00:00:00:02"))
        with self.assertRaises(pairing.TokenRefused):
            self.enroll(data, dict(MACHINE, mac="52:54:00:00:00:03"))
        self.assertEqual(2, len(admin.read_machines(self.state)))

    def test_revoked_and_expired_tokens(self) -> None:
        data = self.token()
        with server.locked(self.state):
            pairing.revoke_token(self.state, data["token_id"])
        with self.assertRaises(pairing.TokenRefused):
            self.enroll(data)
        old = self.token(days=1)
        later = datetime.datetime.now().astimezone() + datetime.timedelta(days=2)
        with server.locked(self.state):
            self.assertEqual("token", pairing.check_enrolment(self.state, {"token_id": old["token_id"]}, "",
                                                              later, pairing.Replays())[0])
        unknown = dict(data, token_id="0123456789abcdef")
        with self.assertRaises(pairing.TokenRefused):
            self.enroll(unknown)

    def test_wrong_proofs_are_counted_and_disable_the_token(self) -> None:
        data = self.token()
        forged = dict(data, token=protocol.b64(bytes(32)))  # the right id, a wrong token
        for _attempt in range(pairing.MAX_FAILURES - 1):
            with self.assertRaises(pairing.PairingError) as caught:
                self.enroll(forged)
            self.assertNotIsInstance(caught.exception, pairing.TokenRefused)
        self.assertEqual(pairing.MAX_FAILURES - 1, pairing.read_tokens(self.state)[data["token_id"]]["failures"])
        self.assertEqual("approved", self.enroll(data)["state"], "the real file still works")
        with self.assertRaises(pairing.PairingError):
            self.enroll(forged)
        self.assertTrue(pairing.read_tokens(self.state)[data["token_id"]]["revoked"])
        self.assertEqual("enroll-token", admin.read_audit(self.state)[0]["action"])
        with self.assertRaises(pairing.TokenRefused):
            self.enroll(data, dict(MACHINE, mac="52:54:00:00:00:09"))

    def test_a_replay_and_a_late_clock(self) -> None:
        data = self.token()
        sent: list[tuple[str, dict]] = []

        def spy(url: str, body: dict) -> tuple[int, object]:
            sent.append((url, body))
            return pairing.post_json(url, body)

        self.enroll(data, post=spy)
        url, body = sent[0]
        self.assertEqual((403, {"error": "proof"}), pairing.post_json(url, body), "the same request again")
        self.assertEqual(0, pairing.read_tokens(self.state)[data["token_id"]]["failures"], "a replay is not counted")
        with self.assertRaises(pairing.PairingError):
            self.enroll(data, dict(MACHINE, mac="52:54:00:00:00:05"),
                        now=datetime.datetime.now().timestamp() - pairing.CLOCK_WINDOW - 60)
        self.assertEqual(1, len(admin.read_machines(self.state)))

    def test_a_sniffed_request_cannot_enrol_another_machine(self) -> None:
        data = self.token()
        sent: list[tuple[str, dict]] = []

        def spy(url: str, body: dict) -> tuple[int, object]:
            sent.append((url, body))
            return 599, None  # never reaches the admin

        with self.assertRaises(pairing.PairingError):
            self.enroll(data, post=spy)
        url, body = sent[0]
        for change in ({"box_key": self.box_key()[1]}, {"machine": dict(MACHINE, name="ke-gian")}):
            with self.subTest(change=list(change)):
                self.assertEqual((403, {"error": "proof"}), pairing.post_json(url, dict(body, **change)))

    def test_pending_after_enrolment(self) -> None:
        admin.write_options({"approve_machines": True}, self.state)
        answer = self.enroll(self.token())
        self.assertEqual("pending", answer["state"])

    def test_the_employee_side_through_the_client(self) -> None:
        data = self.token()
        moved = dict(data, admin_url="http://127.0.0.1:1")  # the admin's address changed since the file was made
        private = protocol.new_box_key()
        found = [{"name": "quan-ly", "ip": "127.0.0.1", "port": self.port,
                  "fingerprint": protocol.fingerprint(protocol.public_bytes(self.key)), "pairing": False}]
        with mock.patch.object(client, "machine_info", return_value=dict(MACHINE)):
            config, state = client.enroll(moved, private, find=lambda _timeout: found)
            self.assertEqual((self.url, "approved"), (config["admin_url"], state))
            with self.assertRaises(client.PairingError):
                client.enroll(moved, private, find=lambda _timeout: [])
            with server.locked(self.state):
                pairing.revoke_token(self.state, data["token_id"])
            with self.assertRaises(client.TokenRefused):
                client.enroll(data, private)


if __name__ == "__main__":
    unittest.main()

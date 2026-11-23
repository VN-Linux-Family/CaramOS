"""caramos_business.protocol against part 1's shared examples (PROTOCOL.md; the Rust agent's tests use the same).

Format 1 is gone in 0.2: its rules for the wallpaper and the folders now hold inside format 2's settings, so the
invalid part 1 policies are checked again in that shape. test_protocol_v2.py has part 2's vectors."""

from __future__ import annotations

import base64
import datetime
import json
import unittest
from pathlib import Path

from caramos_business import protocol

EXAMPLES = Path(__file__).parent / "protocol-examples"
TEST_KEY = json.loads((EXAMPLES / "test-key.json").read_text(encoding="utf-8"))
PUBLIC = base64.b64decode(TEST_KEY["public"])
BOX_KEY = protocol.b64(protocol.box_public(bytes(range(32, 64))))


def example(name: str) -> object:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def as_format_2(policy: dict) -> dict:
    """A part 1 policy in format 2's shape: its wallpaper and folders as company settings."""

    return {"format": 2 if policy["format"] == 1 else policy["format"], "serial": policy["serial"],
            "issued": policy["issued"], "admin": policy["admin"], "admin_box_key": BOX_KEY, "files": policy["files"],
            "settings": {"wallpaper": policy["wallpaper"], "folders": policy["folders"]}}


class KeyTests(unittest.TestCase):
    def test_fingerprint(self) -> None:
        self.assertEqual(TEST_KEY["fingerprint"], protocol.fingerprint(PUBLIC))
        # Part 3: the pairing code is random for each pairing window (SPAKE2), no longer made from the key.
        self.assertFalse(hasattr(protocol, "pairing_code"))

    def test_sign_then_verify(self) -> None:
        key = protocol.new_key()
        policy = as_format_2(example("policy.json"))
        signed = protocol.sign_policy(key, policy)
        self.assertEqual(policy, protocol.verify_signed_policy(signed, protocol.public_bytes(key)))
        again = protocol.key_from_pem(protocol.key_to_pem(key))
        self.assertEqual(protocol.public_bytes(key), protocol.public_bytes(again))

    def test_the_shared_signed_policy(self) -> None:
        # The signature of part 1's example still checks out; its format 1 is refused.
        text = protocol.verify_signed_text(example("signed-policy.json"), PUBLIC, "policy")
        self.assertEqual(example("policy.json"), json.loads(text))
        with self.assertRaises(protocol.ProtocolError):
            protocol.verify_signed_policy(example("signed-policy.json"), PUBLIC)
        with self.assertRaises(protocol.ProtocolError):
            protocol.verify_signed_text(example("signed-policy-tampered.json"), PUBLIC, "policy")
        with self.assertRaises(protocol.ProtocolError):
            protocol.verify_signed_text(example("signed-policy.json"), b"\x01" * 32, "policy")


class PolicyTests(unittest.TestCase):
    def test_valid(self) -> None:
        protocol.validate_policy(as_format_2(example("policy.json")))
        protocol.validate_policy({"format": 2, "serial": 1, "admin_box_key": BOX_KEY})

    def test_invalid_examples(self) -> None:
        names = sorted(path.name for path in EXAMPLES.glob("invalid-*.json"))
        self.assertGreaterEqual(len(names), 9)
        for name in names:
            with self.subTest(name, shape="as written"), self.assertRaises(protocol.ProtocolError):
                protocol.validate_policy(example(name))
            if name == "invalid-bad-format.json":  # format 2 was the unknown format of part 1
                continue
            with self.subTest(name, shape="format 2"), self.assertRaises(protocol.ProtocolError):
                protocol.validate_policy(as_format_2(example(name)))

    def test_shares(self) -> None:
        for share in ("smb://nas/share", "smb://nas.congty.local/nhanvien/%u", "smb://10.0.0.5/data/phong-ke-toan/%u/"):
            self.assertTrue(protocol.valid_share(share), share)
        for share in ("smb://nas", "smb://u@nas/share", "smb://nas/share/../x", "smb://nas/sh are", "file:///etc"):
            self.assertFalse(protocol.valid_share(share), share)

    def test_wallpaper_for_the_day(self) -> None:
        policy = example("policy.json")
        sha = policy["wallpaper"]["default"]
        other = "b" * 64
        policy["files"][other] = {"size": 1, "type": "png"}
        policy["wallpaper"] = {"default": sha, "lock": False, "periods": [
            {"name": "Tết", "from": "12-25", "to": "01-05", "image": other},
            {"name": "29/2", "from": "02-29", "to": "02-29", "image": other}]}
        for day, expected in ((datetime.date(2026, 12, 31), other), (datetime.date(2027, 1, 5), other),
                              (datetime.date(2027, 1, 6), sha), (datetime.date(2028, 2, 29), other),
                              (datetime.date(2027, 3, 1), sha)):
            with self.subTest(day=day):
                self.assertEqual(expected, protocol.wallpaper_for(policy, day))
        self.assertIsNone(protocol.wallpaper_for({"wallpaper": None}, datetime.date(2026, 1, 1)))


class MessageTests(unittest.TestCase):
    def test_machine(self) -> None:
        machine = {"name": "ke-toan-01", "ip": "192.168.1.20", "mac": "52:54:00:12:34:56", "edition": "xfce",
                   "version": "1.4.0"}
        self.assertEqual(machine, protocol.validate_machine(machine))
        for bad in (dict(machine, name="bad name"), dict(machine, ip="300.1.1.1"), dict(machine, edition="kde"),
                    dict(machine, mac="zz"), "nope"):
            with self.subTest(bad=bad), self.assertRaises(protocol.ProtocolError):
                protocol.validate_machine(bad)

    def test_user_status(self) -> None:
        status = {"user": "minh", "wallpaper": "applied", "folders": "server", "detail": "", "time": "2026-11-21T09:00:00+07:00"}
        self.assertEqual(status, protocol.validate_user_status(status))
        with self.assertRaises(protocol.ProtocolError):
            protocol.validate_user_status(dict(status, user="Root;rm"))

    def test_discovery(self) -> None:
        datagram = protocol.here_datagram("máy-quản-lý", PUBLIC, True)
        self.assertEqual({"name": "máy-quản-lý", "port": 47022, "fingerprint": TEST_KEY["fingerprint"], "pairing": True},
                         protocol.parse_here(datagram))
        for bad in (b"CARAMOS-BUSINESS/1 HERE {", b"HELLO", b"CARAMOS-BUSINESS/1 HERE " + b"x" * 3000,
                    b'CARAMOS-BUSINESS/1 HERE {"name": "a", "port": 0, "fingerprint": "00", "pairing": true}'):
            with self.subTest(bad=bad[:40]):
                self.assertIsNone(protocol.parse_here(bad))


if __name__ == "__main__":
    unittest.main()

"""The admin side: its state (caramos_business.admin), the server (HTTP, the long poll, discovery, Wake-on-LAN) and
the requests of employees (pairing itself is in test_pairing.py), all on this machine with temporary directories."""

from __future__ import annotations

import datetime
import json
import os
import socket
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from caramos_business import admin, assets, client, health, protocol, server, tickets

JPEG = b"\xff\xd8\xff\xe0" + b"picture" * 10
PNG = b"\x89PNG\r\n\x1a\n" + b"picture" * 10
TZ = datetime.timezone(datetime.timedelta(hours=7))
NOW = datetime.datetime(2026, 11, 21, 9, 0, tzinfo=TZ)
MACHINE = {"name": "kt-01", "ip": "192.168.1.20", "mac": "52:54:00:00:00:01", "edition": "cinnamon",
           "version": "1.4.0"}


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state = self.root / "state"
        self.pairing = self.root / "pairing.json"
        admin.prepare_state(self.state)
        self.key = protocol.new_key()
        self.box = admin.ensure_box_key(self.root / "admin-box.key")

    def picture(self, data: bytes, name: str) -> dict:
        path = self.root / name
        path.write_bytes(data)
        return admin.add_image(path, self.state)

    def save(self, draft: dict, passphrases: dict | None = None, now: datetime.datetime | None = None) -> dict:
        return admin.save_policy(draft, self.key, "quan-ly", self.state, now, box_private=self.box,
                                 passphrases=passphrases)

    def machine(self, number: int = 1, pending: bool = False) -> tuple[str, bytes]:
        """A paired machine: (machine_id, its private box key)."""

        private = protocol.new_box_key()
        machine = dict(MACHINE, name=f"kt-{number:02d}", mac=f"52:54:00:00:00:{number:02x}")
        machine_id = admin.register(machine, protocol.b64(protocol.box_public(private)), self.state, pending=pending)
        return machine_id, private


class AdminStateTests(Fixture):
    def test_keys(self) -> None:
        self.assertEqual(self.box, admin.ensure_box_key(self.root / "admin-box.key"))
        self.assertEqual(0o600, (self.root / "admin-box.key").stat().st_mode & 0o777)

    def test_pictures(self) -> None:
        jpeg = self.picture(JPEG, "a.jpg")
        self.assertEqual("jpg", jpeg["type"])
        self.assertTrue((self.state / "files" / jpeg["sha256"]).is_file())
        self.assertEqual("png", self.picture(PNG, "b.png")["type"])
        with self.assertRaises(protocol.ProtocolError):
            self.picture(b"MZ\x90\x00 an exe", "c.jpg")

    def test_save_policy(self) -> None:
        jpeg, png = self.picture(JPEG, "a.jpg"), self.picture(PNG, "b.png")
        draft = {"settings": {"wallpaper": {"default": jpeg["sha256"], "lock": True, "periods": []},
                              "folders": {"share": "smb://nas/nhanvien/%u", "tidy": True}},
                 "departments": {"ke-toan": {"name": "Kế toán", "settings": {"wallpaper": {
                     "default": None, "lock": False,
                     "periods": [{"name": "Tết", "from": "01-25", "to": "02-05", "image": png["sha256"]}]}}}}}
        first = self.save(draft, now=NOW)
        self.assertEqual(1, first["serial"])
        self.assertEqual({jpeg["sha256"], png["sha256"]}, set(first["files"]))
        self.assertEqual("2026-11-21T09:00:00+07:00", first["issued"])
        self.assertEqual(protocol.b64(protocol.box_public(self.box)), first["admin_box_key"])
        self.assertNotIn("remote_help_cert", first)  # part 3: remote help has a key per session
        second = self.save(draft)
        self.assertEqual(2, second["serial"])
        signed = json.loads((self.state / admin.SIGNED).read_text(encoding="utf-8"))
        self.assertEqual(second, protocol.verify_signed_policy(signed, protocol.public_bytes(self.key)))

    def test_save_policy_checks_everything(self) -> None:
        with self.assertRaises(protocol.ProtocolError):  # a picture never copied in
            self.save({"settings": {"wallpaper": {"default": "a" * 64, "periods": [], "lock": False}}})
        with self.assertRaises(protocol.ProtocolError) as caught:
            self.save({"departments": {"kho": {"name": "Kho", "settings": {
                "folders": {"share": "smb://u:p@nas/x", "tidy": False}}}}})
        self.assertEqual(("folders", "department:kho"), (caught.exception.section, caught.exception.scope))
        self.assertFalse((self.state / admin.SIGNED).exists())

    def test_wifi_passphrases_are_sealed_for_each_machine(self) -> None:
        first, first_box = self.machine(1)
        second, second_box = self.machine(2)
        draft = {"settings": {"wifi": [{"ssid": "CongTy", "security": "wpa-psk", "hidden": False},
                                       {"ssid": "Khach", "security": "open", "hidden": False}]},
                 "departments": {"kho": {"name": "Kho", "settings": {
                     "wifi": [{"ssid": "Kho", "security": "wpa-psk", "hidden": True}]}}},
                 "members": {second: "kho"}}
        with self.assertRaises(protocol.ProtocolError) as caught:  # no passphrase for Kho
            self.save(draft, {"CongTy": "matkhau-cong-ty"})
        self.assertIn("Kho", str(caught.exception))
        with self.assertRaises(protocol.ProtocolError):
            self.save(draft, {"CongTy": "ngắn", "Kho": "matkhau-kho-123"})
        policy = self.save(draft, {"CongTy": "matkhau-cong-ty", "Kho": "matkhau-kho-123"})

        def opened(machine_id: str, private: bytes, current: dict) -> dict:
            _mac, seal_key = protocol.machine_keys(private, protocol.box_public(self.box))
            return protocol.unseal(seal_key, machine_id, current["machines"][machine_id]["sealed"])

        self.assertEqual({"wifi": {"CongTy": "matkhau-cong-ty"}}, opened(first, first_box, policy))
        self.assertEqual({"wifi": {"Kho": "matkhau-kho-123"}}, opened(second, second_box, policy))
        self.assertEqual(0o600, (self.state / admin.SECRETS).stat().st_mode & 0o777)
        for name in (admin.POLICY, admin.SIGNED):
            self.assertNotIn("matkhau", (self.state / name).read_text(encoding="utf-8"))
        again = self.save(draft)  # kept from the last save
        self.assertEqual({"wifi": {"Kho": "matkhau-kho-123"}}, opened(second, second_box, again))
        draft["departments"]["kho"]["settings"] = {}
        self.save(draft)  # Kho no longer listed: its passphrase goes
        self.assertEqual({"CongTy"}, set(admin.read_secrets(self.state)["wifi"]))

    def test_members_and_overrides_of_unknown_machines_are_dropped(self) -> None:
        known, _box = self.machine()
        unknown = "11111111-2222-4333-8444-555555555555"
        policy = self.save({"departments": {"kho": {"name": "Kho", "settings": {}}},
                            "members": {known: "kho", unknown: "kho"},
                            "machines": {known: {"settings": {"usb": {"storage": "block"}}},
                                         unknown: {"settings": {"usb": {"storage": "allow"}}}}})
        self.assertEqual({known: "kho"}, policy["members"])
        self.assertEqual([known], list(policy["machines"]))

    def test_a_removed_machine_gets_a_signed_notice(self) -> None:
        machine_id, private = self.machine()
        self.save({"settings": {"usb": {"storage": "block"}}, "members": {}})
        self.assertTrue(admin.forget_machine(machine_id, self.state, NOW, key=self.key, admin_name="quan-ly"))
        self.assertNotIn(machine_id, admin.read_machines(self.state))
        record = admin.read_removed(self.state)[machine_id]
        self.assertEqual(protocol.b64(protocol.box_public(private)), record["box_key"])
        notice = protocol.verify_notice(record["notice"], protocol.public_bytes(self.key), machine_id)
        self.assertEqual(("removed", "quan-ly", "2026-11-21T09:00:00+07:00"),
                         (notice["kind"], notice["admin"], notice["time"]))
        policy = self.save(admin.draft_from_policy(admin.read_policy(self.state)), now=NOW)
        self.assertNotIn(machine_id, policy["machines"])  # no released entry any more (part 3)
        other, _box = self.machine(2)
        admin.forget_machine(other, self.state, NOW + datetime.timedelta(days=366), key=self.key)
        self.assertEqual([other], list(admin.read_removed(self.state)), "kept 365 days")
        (self.state / admin.REMOVED).write_text(json.dumps({machine_id: "2026-11-21T09:00:00+07:00"}))
        self.assertEqual({"time": "2026-11-21T09:00:00+07:00"}, admin.read_removed(self.state)[machine_id])

    def test_a_removed_machine_keeps_its_asset_history(self) -> None:
        """The computer is still the company's: its asset record stays as a thing without a machine, history and all
        (0.3.0 dropped it with the pairing, and with it the holder, the handover and the leaver's steps)."""

        typed, _box = self.machine()
        blank, _box2 = self.machine(2)
        stored = {typed: {"asset_code": "MT-01", "holder": "Lan", "status": "in_use", "kind": "computer",
                          "history": [{"time": "2026-11-20T09:00:00+07:00", "event": "assigned", "by": "caram",
                                       "note": "Lan"}]},
                  blank: {"asset_code": "", "holder": "", "history": []}}
        (self.state / admin.ASSETS).write_text(json.dumps(stored))
        self.assertTrue(admin.forget_machine(typed, self.state, NOW, key=self.key, by="caram"))
        self.assertTrue(admin.forget_machine(blank, self.state, NOW, key=self.key))
        kept = admin.read_assets(self.state)
        self.assertEqual(1, len(kept), "an empty record goes with its machine")
        asset_id, entry = next(iter(kept.items()))
        self.assertTrue(assets.ASSET_ID.match(asset_id))
        self.assertEqual((None, "MT-01", "Lan", "in_use"),
                         (entry["machine_id"], entry["asset_code"], entry["holder"], entry["status"]))
        self.assertEqual("kt-01", entry["name"], "named after the machine")
        self.assertEqual(["assigned", "note"], [item["event"] for item in entry["history"]])
        self.assertEqual("caram", entry["history"][-1]["by"])
        assets.validate(dict(entry), machine_id=None)  # the window can open and save it as any other thing

    def test_pending_machines_get_nothing(self) -> None:
        approved, approved_box = self.machine()
        pending, _box = self.machine(2, pending=True)
        self.assertEqual("pending", admin.read_machines(self.state)[pending]["state"])
        policy = self.save({"settings": {"wifi": [{"ssid": "CongTy", "security": "wpa-psk", "hidden": False}]},
                            "departments": {"kho": {"name": "Kho", "settings": {}}},
                            "members": {approved: "kho", pending: "kho"}}, {"CongTy": "matkhau-cong-ty"})
        self.assertEqual({approved: "kho"}, policy["members"])
        self.assertEqual([approved], list(policy["machines"]))
        self.assertIsNotNone(admin.approve_machine(pending, self.state))
        self.assertIsNone(admin.approve_machine(pending, self.state), "approved already")
        third, _box = self.machine(3, pending=True)
        self.assertIsNotNone(admin.reject_machine(third, self.state))
        self.assertNotIn(third, admin.read_machines(self.state))
        self.assertNotIn(third, admin.read_removed(self.state))

    def test_options(self) -> None:
        self.assertEqual({"approve_machines": False}, admin.read_options(self.state))
        admin.write_options({"approve_machines": True}, self.state)
        self.assertEqual({"approve_machines": True}, admin.read_options(self.state))
        with self.assertRaises(protocol.ProtocolError):
            admin.write_options({"approve_machines": "yes"}, self.state)

    def test_freeze_rules(self) -> None:
        lab = {"guest": True, "freeze": True, "maintenance": {"days": [7], "time": "02:00", "max_minutes": 60}}
        self.save({"departments": {"phong-may": {"name": "Phòng máy", "settings": {"shared": lab}}}})
        for settings, department, words in (
                ({}, {"shared": dict(lab, maintenance=None)}, "maintenance"),
                ({"folders": {"share": "smb://nas/nv/%u", "tidy": True}}, {"shared": lab}, "tidying"),
                ({"snapshots": {"schedule": "weekly", "keep": 3, "before_update": True}}, {"shared": lab}, "snapshots")):
            with self.subTest(words=words), self.assertRaises(protocol.ProtocolError) as caught:
                self.save({"settings": settings,
                           "departments": {"phong-may": {"name": "Phòng máy", "settings": department}}})
            self.assertEqual(("shared", "department:phong-may"), (caught.exception.section, caught.exception.scope))
            self.assertIn(words, str(caught.exception))
        # Off for the lab: snapshots for the company stay fine.
        self.save({"settings": {"snapshots": {"schedule": "weekly", "keep": 3, "before_update": True}},
                   "departments": {"phong-may": {"name": "Phòng máy", "settings": {"shared": lab, "snapshots": None}}}})

    def test_a_policy_from_0_1(self) -> None:
        (self.state / admin.POLICY).write_text(json.dumps({"format": 1, "serial": 4, "files": {}, "wallpaper": None,
                                                           "folders": {"share": "smb://nas/nv/%u", "tidy": True}}))
        policy = admin.read_policy(self.state)
        self.assertEqual((2, 4), (policy["format"], policy["serial"]))
        self.assertEqual({"folders": {"share": "smb://nas/nv/%u", "tidy": True}}, policy["settings"])
        self.assertEqual(5, self.save(admin.draft_from_policy(policy))["serial"])

    def test_changes(self) -> None:
        old = {"settings": {"usb": {"storage": "allow"}}, "departments": {"kho": {"name": "Kho", "settings": {}}}}
        new = {"settings": {"usb": {"storage": "block"}, "firewall": {"enabled": True}},
               "departments": {"kho": {"name": "Kho", "settings": {"browser": None}}}, "members": {"x": "kho"}}
        self.assertEqual([("company", "usb"), ("company", "firewall"), ("department:kho", "browser"),
                          ("company", "members")], admin.changes(old, new))

    def test_the_cards_a_machine_reports_from(self) -> None:
        box_key = protocol.b64(protocol.box_public(protocol.new_box_key()))
        machine_id = admin.register(MACHINE, box_key, self.state)
        other = "52:54:00:00:00:99"
        for minute, mac in enumerate((MACHINE["mac"], MACHINE["mac"], other, MACHINE["mac"])):
            report = protocol.validate_checkin({"machine": dict(MACHINE, mac=mac), "policy_serial": 4, "users": []})
            entry = admin.check_in(machine_id, report, self.state, now=NOW + datetime.timedelta(minutes=minute))
        self.assertEqual({MACHINE["mac"], other}, set(entry["macs"]))
        self.assertEqual([(NOW + datetime.timedelta(minutes=minute)).isoformat() for minute in (2, 3)],
                         [datetime.datetime.fromisoformat(when).isoformat() for when in entry["mac_switches"]])

    def test_pairing_window(self) -> None:
        self.assertFalse(admin.pairing_open(self.pairing))
        admin.open_pairing(600, self.pairing, now=1000.0)
        self.assertTrue(admin.pairing_open(self.pairing, now=1500.0))
        self.assertFalse(admin.pairing_open(self.pairing, now=1700.0))
        admin.close_pairing(self.pairing)
        self.assertFalse(admin.pairing_open(self.pairing, now=1500.0))

    def test_machines(self) -> None:
        box_key = protocol.b64(protocol.box_public(protocol.new_box_key()))
        machine_id = admin.register(MACHINE, box_key, self.state)
        report = protocol.validate_checkin({"machine": MACHINE, "policy_serial": 3, "users": [],
                                            "capabilities": ["wallpaper"]})
        entry = admin.check_in(machine_id, report, self.state)
        self.assertEqual((3, ["wallpaper"], box_key), (entry["policy_serial"], entry["capabilities"], entry["box_key"]))
        report = protocol.validate_checkin({"machine": MACHINE, "policy_serial": 4, "users": []})
        self.assertEqual(["wallpaper"], admin.check_in(machine_id, report, self.state)["capabilities"])
        self.assertIsNone(admin.check_in("11111111-2222-4333-8444-555555555555", report, self.state))
        again = admin.register(MACHINE, box_key, self.state)  # the same card pairs again: one entry
        self.assertEqual([again], list(admin.read_machines(self.state)))
        (self.state / admin.INVENTORY / f"{again}.json").write_text("{}")
        self.assertTrue(admin.forget_machine(again, self.state))
        self.assertEqual({}, admin.read_machines(self.state))
        self.assertFalse((self.state / admin.INVENTORY / f"{again}.json").exists())
        self.assertIn(again, admin.read_removed(self.state))
        self.assertNotIn("notice", admin.read_removed(self.state)[again], "no key given: no notice")

    def test_commands(self) -> None:
        first = admin.queue_command(self.key, {"all": True}, "lock", {}, self.state, NOW)
        second = admin.queue_command(self.key, {"departments": ["kho"]}, "message",
                                     {"title": "Họp", "body": "", "ack": True}, self.state, NOW)
        self.assertEqual((1, 2), (first["seq"], second["seq"]))
        self.assertEqual("2026-11-21T09:10:00+07:00", first["expires"])
        store = admin.read_commands(self.state)
        self.assertEqual(2, store["seq"])
        public = protocol.public_bytes(self.key)
        self.assertEqual(second, protocol.verify_command(store["commands"][1], public))
        with self.assertRaises(protocol.ProtocolError):
            admin.queue_command(self.key, {"all": True}, "shell", {"run": "id"}, self.state, NOW)
        machine_id, _box = self.machine()
        known = {first["id"], second["id"]}
        result = {"id": first["id"], "state": "done", "detail": "", "time": ""}
        self.assertTrue(admin.record_result(machine_id, result, known, self.state))
        self.assertFalse(admin.record_result(machine_id, dict(result, id="11111111-2222-4333-8444-555555555555"),
                                             known, self.state))
        self.assertEqual("done", admin.read_results(self.state)[first["id"]][machine_id]["state"])
        # A week later the old ones go, and their results with them.
        admin.queue_command(self.key, {"all": True}, "sync", {}, self.state, NOW + datetime.timedelta(days=8))
        store = admin.read_commands(self.state)
        self.assertEqual([3], [admin.command_of(item)["seq"] for item in store["commands"]])
        self.assertEqual({}, admin.read_results(self.state))

    def test_at_most_1000_commands(self) -> None:
        store = {"seq": 0, "commands": []}
        for seq in range(1, 1006):
            command = admin.make_command({"all": True}, "sync", {}, seq, NOW)
            store["commands"].append({"command": json.dumps(command), "signature": ""})
        pruned = admin.prune_commands(store, NOW)
        self.assertEqual(1000, len(pruned["commands"]))
        self.assertEqual(6, admin.command_of(pruned["commands"][0])["seq"])

    def test_assets(self) -> None:
        asset = {"asset_code": "TS-001", "purchase_date": "2024-03-15", "price_vnd": 15000000,
                 "warranty_until": "2027-03-15", "holder": "Minh", "location": "Tầng 2", "note": "Màn hình rời"}
        self.assertEqual(asset, admin.validate_asset(asset))
        self.assertEqual({"price_vnd": None, "asset_code": "", "purchase_date": "", "warranty_until": "",
                          "holder": "", "location": "", "note": ""}, admin.validate_asset({}))
        for change in ({"purchase_date": "15/3/2024"}, {"price_vnd": -1}, {"price_vnd": "15tr"},
                       {"asset_code": "x" * 41}, {"holder": "a\nb"}):
            with self.subTest(change=change), self.assertRaises(protocol.ProtocolError):
                admin.validate_asset(dict(asset, **change))
        machine_id, _box = self.machine()
        admin.set_asset(machine_id, asset, self.state)
        self.assertEqual(asset, admin.read_assets(self.state)[machine_id])

    def test_audit(self) -> None:
        for number in range(5):
            admin.audit("command", f"Khóa máy {number}", "minh", self.state, NOW, command_id=str(number))
        lines = admin.read_audit(self.state, limit=3)
        self.assertEqual(["Khóa máy 4", "Khóa máy 3", "Khóa máy 2"], [line["summary"] for line in lines])
        self.assertEqual({"time": "2026-11-21T09:00:00+07:00", "user": "minh", "action": "command",
                          "summary": "Khóa máy 4", "details": {"command_id": "4"}}, lines[0])
        with mock.patch.dict(os.environ, {"PKEXEC_UID": str(os.getuid())}):
            self.assertEqual(__import__("pwd").getpwuid(os.getuid()).pw_name, admin.pkexec_user())


class HealthTests(unittest.TestCase):
    def entry(self, **health_values: object) -> dict:
        values = {"disk_free_pct": 50, "disk_health": "ok", "battery_health_pct": None,
                  "updates": {"security": 0, "other": 0}, "reboot_required": False, "firewall": "on",
                  "caramos_version": "1.4.0", "uptime_hours": 3, "applied": {}}
        values.update(health_values)
        return {"health": values, "capabilities": list(protocol.CAPABILITIES), "last_seen": NOW.isoformat()}

    def keys(self, entry: dict, record: dict | None = None, effective: dict | None = None,
             now: datetime.datetime = NOW) -> list[str]:
        if entry.get("last_seen") == NOW.isoformat():
            entry = dict(entry, last_seen=now.isoformat())  # seen at the time of the check
        return [problem.key for problem in health.problems(entry, record, effective or {}, now)]

    def test_a_healthy_machine(self) -> None:
        self.assertEqual([], self.keys(self.entry()))

    def test_thresholds(self) -> None:
        self.assertEqual(["disk_space"], self.keys(self.entry(disk_free_pct=9)))
        self.assertEqual([], self.keys(self.entry(disk_free_pct=10)))
        self.assertEqual(["disk_failing"], self.keys(self.entry(disk_health="failing")))
        self.assertEqual(["battery"], self.keys(self.entry(battery_health_pct=59)))
        self.assertEqual([], self.keys(self.entry(battery_health_pct=60)))
        self.assertEqual(["firewall"], self.keys(self.entry(firewall="off"), effective={"firewall": {"enabled": True}}))
        self.assertEqual([], self.keys(self.entry(firewall="off")))  # not managed
        self.assertEqual(["applied:printers"], self.keys(self.entry(applied={"printers": "failed: no answer",
                                                                             "browser": "ok"})))
        self.assertEqual(["clock"], self.keys(self.entry(), {"skew": 121}))
        self.assertEqual([], self.keys(self.entry(), {"skew": -120}))
        old = dict(self.entry(), last_seen=(NOW - datetime.timedelta(days=3, minutes=1)).isoformat())
        self.assertEqual(["offline"], self.keys(old))

    def test_capabilities(self) -> None:
        entry = dict(self.entry(), capabilities=["wallpaper", "commands"])
        self.assertEqual(["capability:usb"], self.keys(entry, effective={"usb": {"storage": "block"},
                                                                         "wallpaper": {}, "browser": None}))
        self.assertEqual([], self.keys({"health": None, "capabilities": []}, effective={"usb": {"storage": "x"}}))

    def test_waiting_updates_and_restart(self) -> None:
        entry = self.entry(updates={"security": 3, "other": 1}, reboot_required=True)
        record = health.update_record(None, entry, {}, NOW)
        self.assertEqual(NOW.isoformat(), record["security_since"])
        self.assertEqual([], self.keys(entry, record))
        later = NOW + datetime.timedelta(days=4)
        record = health.update_record(record, entry, {}, later)
        self.assertEqual(["reboot"], self.keys(entry, record, now=later))
        week = NOW + datetime.timedelta(days=7, hours=1)
        record = health.update_record(record, entry, {}, week)
        self.assertEqual(["security_updates", "reboot"], self.keys(entry, record, now=week))
        self.assertEqual(later.isoformat(), record["problems"]["reboot"], "first seen stays")
        fixed = self.entry()
        record = health.update_record(record, fixed, {}, week)
        self.assertEqual((None, None, {}), (record["security_since"], record["reboot_since"], record["problems"]))

    def test_cards_back_and_forth_may_be_a_cloned_disk(self) -> None:
        def ago(minutes: int) -> str:
            return (NOW - datetime.timedelta(minutes=minutes)).isoformat()

        macs = {"52:54:00:00:00:01": ago(4), "52:54:00:00:00:02": ago(0)}
        two = dict(self.entry(), macs=macs, mac_switches=[ago(14), ago(9), ago(4)])
        self.assertEqual(["clone"], self.keys(two))
        problem = health.problems(two, None, {}, NOW)[0]
        self.assertIn("52:54:00:00:00:01, 52:54:00:00:00:02", problem.text)
        laptop = dict(self.entry(), macs=macs, mac_switches=[ago(20), ago(4)])
        self.assertEqual([], self.keys(laptop), "a laptop moved to Wi-Fi and back to its cable")
        earlier = dict(self.entry(), macs=macs, mac_switches=[ago(200), ago(100), ago(50)])
        self.assertEqual([], self.keys(earlier), "card changes spread over hours")

    def test_skew_is_recorded(self) -> None:
        record = health.update_record(None, self.entry(), {}, NOW, skew=-300)
        self.assertEqual(-300, record["skew"])
        self.assertEqual(["clock"], list(record["problems"]))
        self.assertIn("5", health.problems(self.entry(), record, {}, NOW)[0].text)

    def test_snapshots_late(self) -> None:
        weekly = {"snapshots": {"schedule": "weekly", "keep": 3, "before_update": True}}
        entry = self.entry(last_snapshot=None)
        record = health.update_record(None, entry, weekly, NOW)
        self.assertEqual(NOW.isoformat(), record["snapshots_since"])
        self.assertEqual([], self.keys(entry, record, weekly))
        later = NOW + datetime.timedelta(days=14, hours=1)
        self.assertEqual(["snapshot_old"], self.keys(entry, record, weekly, later), "none 2 periods after it came on")
        taken = self.entry(last_snapshot=(later - datetime.timedelta(days=13)).isoformat())
        self.assertEqual([], self.keys(taken, record, weekly, later))
        old = self.entry(last_snapshot=(later - datetime.timedelta(days=15)).isoformat())
        self.assertEqual(["snapshot_old"], self.keys(old, record, weekly, later))
        daily = {"snapshots": {"schedule": "daily", "keep": 3, "before_update": False}}
        self.assertEqual(["snapshot_old"], self.keys(self.entry(last_snapshot=(NOW - datetime.timedelta(days=3))
                                                                .isoformat()), record, daily))
        self.assertIsNone(health.update_record(record, entry, {}, NOW)["snapshots_since"], "turned off")

    def test_frozen_machines(self) -> None:
        frozen = {"shared": {"guest": False, "freeze": True, "maintenance": {"days": [7], "time": "02:00",
                                                                             "max_minutes": 60}}}
        entry = self.entry(frozen=True, freeze_configured=True, last_maintenance=None)
        record = health.update_record(None, entry, frozen, NOW)
        self.assertEqual([], self.keys(entry, record, frozen))
        later = NOW + datetime.timedelta(days=8, hours=1)
        self.assertEqual(["maintenance_late"], self.keys(entry, record, frozen, later))
        done = self.entry(frozen=True, freeze_configured=True, last_maintenance=(later - datetime.timedelta(days=6))
                          .isoformat())
        self.assertEqual([], self.keys(done, record, frozen, later))
        # Turned on in the policy, applied to the disk, but not running until a restart.
        waiting = self.entry(frozen=False, freeze_configured=True)
        record = health.update_record(None, waiting, frozen, NOW)
        self.assertEqual([], self.keys(waiting, record, frozen))
        tomorrow = NOW + datetime.timedelta(days=1, hours=1)
        record = health.update_record(record, waiting, frozen, tomorrow)
        self.assertEqual(["freeze_pending"], self.keys(waiting, record, frozen, tomorrow))
        self.assertIn("start", health.problems(dict(waiting, last_seen=tomorrow.isoformat()), record, frozen,
                                               tomorrow)[0].text)
        record = health.update_record(record, entry, frozen, tomorrow)
        self.assertIsNone(record["freeze_pending_since"], "restarted: frozen now")
        self.assertEqual("Shared machine", health.section_title("shared"))


class ServerTests(Fixture):
    def setUp(self) -> None:
        super().setUp()
        self.admin = server.Admin(self.key, "quan-ly", self.state, self.pairing, self.root / "admin-box.key")
        self.admin.wait_seconds = 2.0
        self.stop = threading.Event()
        self.addCleanup(self.stop.set)
        threading.Thread(target=self.admin.watch, args=(self.stop,), daemon=True).start()
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.admin))
        self.http.daemon_threads = True
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.base = f"http://127.0.0.1:{self.http.server_address[1]}"
        self.url = self.base + protocol.PREFIX

    def call(self, path: str, body: object = None) -> tuple[int, object]:
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        request = urllib.request.Request(self.url + path, data=data)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                raw = response.read()
                return response.status, (json.loads(raw) if response.headers.get_content_type() == "application/json" else raw)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def pair(self, number: int = 1, pending: bool = False) -> tuple[str, bytes]:
        """A paired machine (pairing itself is tested in test_pairing.py): (machine_id, mac_key)."""

        machine_id, private = self.machine(number, pending)
        mac_key, _seal = protocol.machine_keys(private, protocol.box_public(self.box))
        return machine_id, mac_key

    def authed(self, machine_id: str, mac_key: bytes, method: str, path: str, body: object = None,
               now: float | None = None) -> tuple[int, object]:
        return client.authed(self.base, machine_id, mac_key, method, protocol.PREFIX + path, body, timeout=10,
                             now=now)

    def test_hello_and_no_key(self) -> None:
        self.assertEqual({"name": "quan-ly", "fingerprint": protocol.fingerprint(protocol.public_bytes(self.key)),
                          "pairing": False}, self.call("/hello")[1])
        self.assertEqual(404, self.call("/key")[0], "part 3: the pairing code no longer comes from the key")
        admin.open_pairing(600, self.pairing)
        self.assertTrue(self.call("/hello")[1]["pairing"])

    def raw_get(self, machine_id: str, mac_key: bytes, path: str) -> tuple[int, bytes]:
        target = protocol.PREFIX + path
        request = urllib.request.Request(self.base + target,
                                         headers=protocol.auth_headers(machine_id, mac_key, "GET", target))
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def test_policy_and_files_need_a_paired_machine(self) -> None:
        machine_id, mac_key = self.pair()
        self.assertEqual(404, self.authed(machine_id, mac_key, "GET", "/policy")[0], "no policy yet")
        jpeg = self.picture(JPEG, "a.jpg")
        self.save({"settings": {"wallpaper": {"default": jpeg["sha256"], "periods": [], "lock": False}}})
        self.assertEqual(401, self.call("/policy")[0], "part 3: only paired machines read the settings")
        self.assertEqual(401, self.call(f"/files/{jpeg['sha256']}")[0])
        status, signed = self.authed(machine_id, mac_key, "GET", "/policy")
        self.assertEqual(200, status)
        self.assertEqual(1, protocol.verify_signed_policy(signed, protocol.public_bytes(self.key))["serial"])
        self.assertEqual((200, JPEG), self.raw_get(machine_id, mac_key, f"/files/{jpeg['sha256']}"))
        other = self.picture(PNG, "b.png")  # copied in, not in the policy
        self.assertEqual(404, self.raw_get(machine_id, mac_key, f"/files/{other['sha256']}")[0])
        self.assertEqual(404, self.call("/files/../../etc/passwd")[0])

    def test_pending_and_removed_machines(self) -> None:
        self.save({"settings": {"firewall": {"enabled": True}}})
        pending, pending_key = self.pair(2, pending=True)
        for method, path, body in (("GET", "/policy", None), ("GET", "/wait?after=0&serial=0", None),
                                   ("GET", "/tickets", None), ("POST", "/checkin", {"machine": MACHINE, "users": []}),
                                   ("POST", "/help", {"user": "", "note": "", "time": ""})):
            with self.subTest(path=path):
                self.assertEqual((403, {"error": "pending"}), self.authed(pending, pending_key, method, path, body))
        machine_id, mac_key = self.pair(3)
        admin.forget_machine(machine_id, self.state, key=self.key, admin_name="quan-ly")
        status, notice = self.authed(machine_id, mac_key, "GET", "/policy")
        self.assertEqual(200, status)
        self.assertEqual(["notice", "signature"], sorted(notice))
        protocol.verify_notice(notice, protocol.public_bytes(self.key), machine_id)
        self.assertEqual(410, self.raw_get(machine_id, mac_key, "/wait?after=0&serial=0")[0])
        self.assertEqual(410, self.authed(machine_id, mac_key, "POST", "/checkin", {"machine": MACHINE, "users": []})[0])

    def test_authenticated_check_in(self) -> None:
        machine_id, mac_key = self.pair()
        health_values = {"disk_free_pct": 5, "disk_health": "ok", "battery_health_pct": None,
                         "updates": {"security": 0, "other": 2}, "reboot_required": False, "firewall": "on",
                         "caramos_version": "1.4.0", "uptime_hours": 2, "applied": {}}
        body = {"machine_id": machine_id, "machine": MACHINE, "policy_serial": None,
                "users": [{"user": "minh", "wallpaper": "applied", "folders": "server", "detail": "", "time": "t"}],
                "health": health_values, "capabilities": list(protocol.CAPABILITIES)}
        self.assertEqual((200, {"ok": True}), self.authed(machine_id, mac_key, "POST", "/checkin", body))
        entry = admin.read_machines(self.state)[machine_id]
        self.assertEqual(("minh", 5), (entry["users"][0]["user"], entry["health"]["disk_free_pct"]))
        self.assertIn("disk_space", admin.read_health(self.state)[machine_id]["problems"])
        # Wrong key, unknown machine, a day off: 401.
        self.assertEqual(401, self.authed(machine_id, b"\x00" * 32, "POST", "/checkin", body)[0])
        self.assertEqual(401, self.authed("11111111-2222-4333-8444-555555555555", mac_key, "POST", "/checkin",
                                          body)[0])
        self.assertEqual(401, self.authed(machine_id, mac_key, "POST", "/checkin", body,
                                          now=time.time() - 86400 - 60)[0])
        # An hour off is accepted, and the skew is recorded for the health checks.
        self.assertEqual(200, self.authed(machine_id, mac_key, "POST", "/checkin", body, now=time.time() - 3600)[0])
        record = admin.read_health(self.state)[machine_id]
        self.assertAlmostEqual(3600, record["skew"], delta=5)
        self.assertIn("clock", record["problems"])
        # A body that is not the protocol's, or names another machine.
        self.assertEqual(400, self.authed(machine_id, mac_key, "POST", "/checkin", dict(body, users=[{"user": "X Y"}]))[0])
        self.assertEqual(400, self.authed(machine_id, mac_key, "POST", "/checkin",
                                          dict(body, machine_id="11111111-2222-4333-8444-555555555555"))[0])
        self.assertEqual(413, self.call("/checkin", b"x" * (protocol.MAX_BODY + 1))[0])
        self.assertEqual(401, self.call("/checkin", body)[0])  # no MAC at all


    def wait_in_thread(self, machine_id: str, mac_key: bytes, after: int, serial: int) -> dict:
        found: dict = {}

        def run() -> None:
            start = time.monotonic()
            found["answer"] = self.authed(machine_id, mac_key, "GET", f"/wait?after={after}&serial={serial}")
            found["seconds"] = time.monotonic() - start

        thread = threading.Thread(target=run)
        thread.start()
        found["thread"] = thread
        return found

    def test_wait_returns_early_on_a_new_command(self) -> None:
        machine_id, mac_key = self.pair()
        self.admin.wait_seconds = 30.0
        found = self.wait_in_thread(machine_id, mac_key, 0, 0)
        time.sleep(0.5)
        command = admin.queue_command(self.key, {"machines": [machine_id]}, "lock", {}, self.state)
        found["thread"].join(10)
        status, answer = found["answer"]
        self.assertEqual(200, status)
        self.assertLess(found["seconds"], 0.5 + 1.5, "woken within a second")
        self.assertEqual([command], [protocol.verify_command(item, protocol.public_bytes(self.key))
                                     for item in answer["commands"]])

    def test_wait_returns_early_on_a_new_serial(self) -> None:
        machine_id, mac_key = self.pair()
        self.admin.wait_seconds = 30.0
        found = self.wait_in_thread(machine_id, mac_key, 0, 0)
        time.sleep(0.5)
        self.save({"settings": {"firewall": {"enabled": True}}})
        found["thread"].join(10)
        self.assertEqual((200, {"serial": 1, "commands": [], "tickets": 0}), found["answer"])
        self.assertLess(found["seconds"], 0.5 + 1.5)

    def test_a_restored_admin_catches_up_with_its_machines(self) -> None:
        """Restored from a backup made before the last saves, the admin's serial is below the machines' own: they
        refused its policy ("its serial 35 is lower than that of the stored policy, 38", on the VMs). A check-in that
        reports a higher serial makes the admin sign the same settings again above it."""

        machine_id, mac_key = self.pair()
        self.save({"settings": {"usb": {"storage": "block"}}})
        body = {"machine_id": machine_id, "machine": MACHINE, "policy_serial": 7, "users": []}
        self.assertEqual(200, self.authed(machine_id, mac_key, "POST", "/checkin", body)[0])
        policy = admin.read_policy(self.state)
        self.assertEqual((8, {"usb": {"storage": "block"}}), (policy["serial"], policy["settings"]))
        signed = json.loads((self.state / admin.SIGNED).read_text())
        self.assertEqual(8, json.loads(signed["policy"])["serial"])
        line = json.loads((self.state / admin.AUDIT).read_text().splitlines()[-1])
        self.assertEqual(("settings", "catch-up", 8), (line["action"], line["details"]["reason"],
                                                      line["details"]["serial"]))
        # Not again at the same serial, and never for a machine that is behind or absurdly ahead.
        for reported in (8, 3, None, 8 + server.MAX_CATCH_UP + 1):
            body["policy_serial"] = reported
            self.assertEqual(200, self.authed(machine_id, mac_key, "POST", "/checkin", body)[0])
            self.assertEqual(8, admin.read_policy(self.state)["serial"], reported)

    def test_wait_returns_early_on_a_ticket_change(self) -> None:
        machine_id, mac_key = self.pair()
        self.save({"settings": {}})
        request = {"user": "lan", "note": "Máy in không in được", "time": ""}
        self.assertEqual(200, self.authed(machine_id, mac_key, "POST", "/help", request)[0])
        self.admin.wait_seconds = 0.5
        self.assertEqual(1, self.authed(machine_id, mac_key, "GET", "/wait?after=0&serial=1")[1]["tickets"])
        self.admin.wait_seconds = 30.0
        found = self.wait_in_thread(machine_id, mac_key, 0, 1)
        time.sleep(0.5)
        with server.locked(self.state):
            tickets.change(self.state, {"id": "HT-0001", "note": {"text": "Hỏng trống mực", "public": False}}, "caram")
        time.sleep(1.5)
        self.assertTrue(found["thread"].is_alive(), "an internal note changes nothing the employee sees")
        with server.locked(self.state):
            tickets.change(self.state, {"id": "HT-0001", "note": {"text": "Đang xem.", "public": True}}, "caram")
        found["thread"].join(10)
        self.assertEqual((200, {"serial": 1, "commands": [], "tickets": 2}), found["answer"])
        self.assertLess(found["seconds"], 0.5 + 1.5 + 1.5, "woken within a second of the public note")
        # A change between two waits answers the next one at once.
        with server.locked(self.state):
            tickets.change(self.state, {"id": "HT-0001", "status": "done"}, "caram")
        start = time.monotonic()
        self.assertEqual(3, self.authed(machine_id, mac_key, "GET", "/wait?after=0&serial=1")[1]["tickets"])
        self.assertLess(time.monotonic() - start, 1.5)

    def test_wait_times_out(self) -> None:
        machine_id, mac_key = self.pair()
        self.save({"settings": {}})
        self.admin.wait_seconds = 1.0
        start = time.monotonic()
        self.assertEqual((200, {"serial": 1, "commands": [], "tickets": 0}),
                         self.authed(machine_id, mac_key, "GET", "/wait?after=0&serial=1"))
        self.assertGreaterEqual(time.monotonic() - start, 0.9)
        self.assertEqual(50, server.protocol.WAIT_SECONDS)

    def test_wait_answers_at_once(self) -> None:
        machine_id, mac_key = self.pair()
        other_id, _key = self.pair(2)
        self.save({"departments": {"kho": {"name": "Kho", "settings": {}}}, "members": {machine_id: "kho"}})
        self.admin.wait_seconds = 30.0
        start = time.monotonic()
        self.assertEqual((200, {"serial": 1, "commands": [], "tickets": 0}),
                         self.authed(machine_id, mac_key, "GET", "/wait?after=0&serial=0"))
        mine = [admin.queue_command(self.key, {"departments": ["kho"]}, "sync", {}, self.state),
                admin.queue_command(self.key, {"machines": [other_id]}, "lock", {}, self.state),
                admin.queue_command(self.key, {"all": True}, "inventory", {}, self.state)]
        self.admin.snapshot.refresh()
        status, answer = self.authed(machine_id, mac_key, "GET", "/wait?after=0&serial=1")
        seqs = [protocol.verify_command(item, protocol.public_bytes(self.key))["seq"] for item in answer["commands"]]
        self.assertEqual([mine[0]["seq"], mine[2]["seq"]], seqs)
        status, answer = self.authed(machine_id, mac_key, "GET", f"/wait?after={mine[0]['seq']}&serial=1")
        self.assertEqual(1, len(answer["commands"]))
        self.assertLess(time.monotonic() - start, 3)
        for _ in range(60):
            admin.queue_command(self.key, {"all": True}, "sync", {}, self.state)
        self.admin.snapshot.refresh()
        self.assertEqual(50, len(self.authed(machine_id, mac_key, "GET", "/wait?after=0&serial=1")[1]["commands"]))
        self.assertEqual(400, self.authed(machine_id, mac_key, "GET", "/wait?after=x&serial=1")[0])
        self.assertEqual(401, self.call("/wait?after=0&serial=1")[0])

    def test_no_commands_from_before_pairing(self) -> None:
        early = admin.queue_command(self.key, {"all": True}, "message", {"title": "Sáng nay", "body": "", "ack": False},
                                    self.state, datetime.datetime.now().astimezone() - datetime.timedelta(minutes=30))
        machine_id, mac_key = self.pair()
        late = admin.queue_command(self.key, {"all": True}, "sync", {}, self.state)
        self.admin.snapshot.refresh()
        status, answer = self.authed(machine_id, mac_key, "GET", "/wait?after=0&serial=0")
        seqs = [protocol.verify_command(item, protocol.public_bytes(self.key))["seq"] for item in answer["commands"]]
        self.assertEqual([late["seq"]], seqs)
        self.assertNotIn(early["seq"], seqs)

    def test_inventory_result_help(self) -> None:
        machine_id, mac_key = self.pair()
        inventory = {"collected": "2026-11-21T09:00:00+07:00", "hash": "b" * 64,
                     "system": {"vendor": "Dell Inc.", "product": "OptiPlex 3080", "serial": "8XK2Q53", "bios": "",
                                "chassis": "desktop", "boot_time": ""}}
        self.assertEqual(403, self.authed(machine_id, mac_key, "POST", "/inventory", inventory)[0], "opt-in")
        self.save({"settings": {"inventory": {"enabled": True}}})
        self.assertEqual(200, self.authed(machine_id, mac_key, "POST", "/inventory", inventory)[0])
        self.assertEqual("8XK2Q53", admin.read_inventory(machine_id, self.state)["system"]["serial"])
        self.assertEqual(400, self.authed(machine_id, mac_key, "POST", "/inventory", {"hash": "x"})[0])
        big = dict(inventory, apps=[{"id": "x" * 200, "name": "y" * 200, "version": "z" * 200}] * 500)
        self.assertEqual(200, self.authed(machine_id, mac_key, "POST", "/inventory", big)[0], "under 1 MiB")
        command = admin.queue_command(self.key, {"all": True}, "message", {"title": "Họp", "body": "", "ack": True},
                                      self.state)
        self.admin.snapshot.refresh()
        result = {"id": command["id"], "state": "done", "detail": "đã đọc: minh", "time": "2026-11-21T09:01:00+07:00"}
        self.assertEqual(200, self.authed(machine_id, mac_key, "POST", "/result", result)[0])
        self.assertEqual("đã đọc: minh", admin.read_results(self.state)[command["id"]][machine_id]["detail"])
        self.save({"settings": {}})  # turned off again: the inventory goes
        self.assertIsNone(admin.read_inventory(machine_id, self.state))
        unknown = dict(result, id="11111111-2222-4333-8444-555555555555")
        self.assertEqual(200, self.authed(machine_id, mac_key, "POST", "/result", unknown)[0])
        self.assertNotIn(unknown["id"], admin.read_results(self.state))
        self.assertEqual(400, self.authed(machine_id, mac_key, "POST", "/result", dict(result, state="ok"))[0])
        request = {"user": "minh", "note": "Máy in không in được.", "time": "2026-11-21T09:02:00+07:00"}
        self.assertEqual((200, {"ticket": "HT-0001", "tickets": 1}),
                         self.authed(machine_id, mac_key, "POST", "/help", request))
        stored = tickets.read(self.state)["tickets"]
        self.assertEqual([(machine_id, "Máy in không in được.", "new")],
                         [(item["machine_id"], item["note"], item["status"]) for item in stored])

    def test_an_answered_command_is_not_delivered_again(self) -> None:
        machine_id, mac_key = self.pair()
        command = admin.queue_command(self.key, {"all": True}, "sync", {}, self.state)
        self.admin.snapshot.refresh()
        self.assertEqual(1, len(self.authed(machine_id, mac_key, "GET", "/wait?after=0&serial=0")[1]["commands"]))
        result = {"id": command["id"], "state": "done", "detail": "thiết lập bản 1", "time": ""}
        self.assertEqual(200, self.authed(machine_id, mac_key, "POST", "/result", result)[0])
        self.admin.wait_seconds = 0.5
        # A frozen machine asks again from the seq its disk remembers: the answered command does not come again.
        self.assertEqual([], self.authed(machine_id, mac_key, "GET", "/wait?after=0&serial=0")[1]["commands"])

    def test_tickets_over_http(self) -> None:
        machine_id, mac_key = self.pair()
        request = {"user": "lan", "note": "Máy in không in được", "time": ""}
        self.assertEqual(200, self.authed(machine_id, mac_key, "POST", "/help", request)[0])
        with server.locked(self.state):
            tickets.change(self.state, {"id": "HT-0001", "note": {"text": "Đang xem.", "public": True}}, "caram")
            tickets.change(self.state, {"id": "HT-0001", "note": {"text": "Hỏng trống mực", "public": False}}, "caram")
        self.admin.wait_seconds = 0.5
        self.assertEqual(2, self.authed(machine_id, mac_key, "GET", "/wait?after=0&serial=0")[1]["tickets"])
        status, signed = self.authed(machine_id, mac_key, "GET", "/tickets")
        self.assertEqual(200, status)
        listed = protocol.verify_tickets(signed, protocol.public_bytes(self.key), machine_id)
        self.assertEqual(2, listed["version"])
        self.assertEqual([{"time": listed["tickets"][0]["updates"][0]["time"], "text": "Đang xem."}],
                         listed["tickets"][0]["updates"], "internal notes never leave the admin")
        self.assertEqual(signed, self.authed(machine_id, mac_key, "GET", "/tickets")[1], "signed once per version")

    def test_a_late_machine_gets_its_wifi_sealed(self) -> None:
        self.save({"settings": {"wifi": [{"ssid": "CongTy", "security": "wpa-psk", "hidden": False}]}},
                  {"CongTy": "matkhau-cong-ty"})
        private = protocol.new_box_key()
        machine_id, state = self.admin.register(MACHINE, protocol.b64(protocol.box_public(private)))
        self.assertEqual("approved", state)
        policy = admin.read_policy(self.state)
        self.assertEqual(2, policy["serial"])
        _mac, seal_key = protocol.machine_keys(private, protocol.box_public(self.box))
        self.assertEqual({"wifi": {"CongTy": "matkhau-cong-ty"}},
                         protocol.unseal(seal_key, machine_id, policy["machines"][machine_id]["sealed"]))

    def test_an_enrolment_file_puts_the_machine_in_its_department(self) -> None:
        self.save({"departments": {"ke-toan": {"name": "Kế toán", "settings": {}}}})
        machine_id, _state = self.admin.register(MACHINE, protocol.b64(protocol.box_public(protocol.new_box_key())),
                                                 via="file", department="ke-toan")
        policy = admin.read_policy(self.state)
        self.assertEqual((2, "ke-toan"), (policy["serial"], policy["members"][machine_id]))
        self.assertEqual("file", admin.read_machines(self.state)[machine_id]["via"])

    def test_a_computer_paired_again_keeps_its_department_and_asset(self) -> None:
        self.save({"departments": {"ke-toan": {"name": "Kế toán", "settings": {}}}})
        old_id, _state = self.admin.register(MACHINE, protocol.b64(protocol.box_public(protocol.new_box_key())),
                                             via="file", department="ke-toan")
        with server.locked(self.state):
            admin.set_asset(old_id, {"asset_code": "TS-01", "holder": "Lan", "machine_id": old_id}, self.state)
        (self.state / admin.INVENTORY / f"{old_id}.json").write_text("{}")
        new_id, _state = self.admin.register(MACHINE, protocol.b64(protocol.box_public(protocol.new_box_key())))
        self.assertNotEqual(old_id, new_id)
        self.assertEqual([new_id], list(admin.read_machines(self.state)))
        self.assertEqual("ke-toan", admin.read_policy(self.state)["members"][new_id])
        self.assertEqual({"asset_code": "TS-01", "holder": "Lan", "machine_id": new_id},
                         admin.read_assets(self.state)[new_id])
        self.assertNotIn(old_id, admin.read_assets(self.state))
        self.assertFalse((self.state / admin.INVENTORY / f"{old_id}.json").exists())

    def test_approval(self) -> None:
        self.save({"settings": {"firewall": {"enabled": True}}})
        admin.write_options({"approve_machines": True}, self.state)
        private = protocol.new_box_key()
        machine_id, state = self.admin.register(MACHINE, protocol.b64(protocol.box_public(private)))
        self.assertEqual("pending", state)
        self.assertEqual("pending", admin.read_machines(self.state)[machine_id]["state"])
        self.assertEqual("register", admin.read_audit(self.state)[0]["action"])
        mac_key, _seal = protocol.machine_keys(private, protocol.box_public(self.box))
        self.assertEqual((403, {"error": "pending"}), self.authed(machine_id, mac_key, "GET", "/policy"))
        with server.locked(self.state):
            admin.approve_machine(machine_id, self.state)
        self.assertEqual(200, self.authed(machine_id, mac_key, "GET", "/policy")[0])

    def test_discovery(self) -> None:
        listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listener.bind(("127.0.0.1", 0))
        self.addCleanup(listener.close)
        threading.Thread(target=server.serve_discovery, args=(self.admin, listener), daemon=True).start()
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as asker:
            asker.settimeout(3)
            asker.sendto(protocol.DISCOVER.encode(), listener.getsockname())
            answer = protocol.parse_here(asker.recvfrom(4096)[0])
            asker.sendto(b"something else", listener.getsockname())
        self.assertEqual("quan-ly", answer["name"])


class WakeTests(Fixture):
    def test_due_wakes(self) -> None:
        first, _box = self.machine(1)
        second, _box = self.machine(2)
        policy = self.save({"settings": {"power": {"shutdown": None, "wake": {"days": [1, 2, 3, 4, 5], "time": "07:45"}}},
                            "departments": {"kho": {"name": "Kho", "settings": {"power": None}}},
                            "members": {second: "kho"}})
        machines = admin.read_machines(self.state)
        monday = datetime.datetime(2026, 11, 23, 7, 45, 20, tzinfo=TZ)
        self.assertEqual([first], server.due_wakes(policy, machines, monday))
        self.assertEqual([], server.due_wakes(policy, machines, monday.replace(minute=46)))
        self.assertEqual([], server.due_wakes(policy, machines, monday + datetime.timedelta(days=5)))  # Saturday

    def test_magic_packet_and_cards(self) -> None:
        packet = server.magic_packet("52:54:00:aa:bb:cc")
        self.assertEqual(6 + 16 * 6, len(packet))
        self.assertEqual(b"\xff" * 6 + bytes.fromhex("525400aabbcc") * 16, packet)
        machine_id, _box = self.machine(1)
        admin.write_inventory(machine_id, {"network": [{"mac": "aa:bb:cc:dd:ee:ff", "wired": True},
                                                       {"mac": "11:22:33:44:55:66", "wired": False}]}, self.state)
        entry = admin.read_machines(self.state)[machine_id]
        self.assertEqual(["52:54:00:00:00:01", "aa:bb:cc:dd:ee:ff"], server.wake_macs(machine_id, entry, self.state))

    def test_sending(self) -> None:
        sock = mock.Mock()
        server.send_wake("52:54:00:aa:bb:cc", sock)
        self.assertEqual([("255.255.255.255", 9), ("255.255.255.255", 7)],
                         [call.args[1] for call in sock.sendto.call_args_list])


class ClientTests(unittest.TestCase):
    def test_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp) / "caramos-release"
            release.write_text('NAME="CaramOS"\nVERSION="1.4.0"\nCHANNEL="stable"\n', encoding="utf-8")
            self.assertEqual("1.4.0", client.caramos_version(release))
            self.assertEqual("", client.caramos_version(Path(tmp) / "missing"))

    def test_machine_on_this_computer(self) -> None:
        machine = client.machine_info("127.0.0.1")
        self.assertEqual("127.0.0.1", machine["ip"])


if __name__ == "__main__":
    unittest.main()

"""The employee's side without a display: the --prompt contract (options, answers), the help request's outbox file,
what the transparency page lists, and the admin's readable summaries and audit lines."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from caramos_business import protocol, summaries, transparency
from caramos_business.ui import prompts

ROOT = Path(__file__).parents[1]
V2 = Path(__file__).parent / "protocol-examples" / "v2"


class PromptContractTests(unittest.TestCase):
    def test_options_of_each_kind(self) -> None:
        self.assertEqual({"title": "Họp 15h", "body": "Phòng 3", "admin": "IT", "ack": True},
                         prompts.parse("message", ["--title", "Họp 15h", "--body", "Phòng 3", "--admin", "IT", "--ack"]))
        self.assertEqual({"action": "shutdown", "seconds": 600, "postpones_left": 2, "postpone_minutes": 30},
                         prompts.parse("countdown", ["--action", "shutdown", "--seconds", "600", "--postpones-left", "2",
                                                     "--postpone-minutes", "30"]))
        self.assertEqual({"action": "logout", "seconds": 60, "postpones_left": 0, "postpone_minutes": 0},
                         prompts.parse("countdown", ["--action", "logout", "--seconds", "60"]))
        self.assertEqual({"admin": "Minh", "mode": "control"},
                         prompts.parse("consent", ["--admin", "Minh", "--mode", "control"]))
        self.assertEqual({"admin": "Minh", "mode": "view"}, prompts.parse("banner", ["--admin", "Minh", "--mode", "view"]))
        self.assertEqual({}, prompts.parse("notice", []))
        self.assertEqual({}, prompts.parse("frozen", []))  # part 3

    def test_refused_options(self) -> None:
        for kind, argv in (("shell", []), ("message", []), ("countdown", ["--action", "reboot", "--seconds", "5"]),
                           ("countdown", ["--action", "shutdown", "--seconds", "-1"]),
                           ("countdown", ["--action", "shutdown", "--seconds", "10", "--postpones-left", "-2"]),
                           ("consent", ["--admin", "x", "--mode", "everything"]), ("notice", ["--extra"]),
                           ("frozen", ["--title", "x"])):
            with self.subTest(kind=kind, argv=argv), self.assertRaises(prompts.PromptError):
                prompts.parse(kind, argv)

    def test_answers(self) -> None:
        self.assertEqual('{"answer": "read"}', prompts.answer_line("read"))
        self.assertEqual({"message": "closed", "countdown": "timeout", "consent": "refuse", "banner": "stop",
                          "notice": "ok", "frozen": "ok"}, prompts.DEFAULT_ANSWER)
        self.assertEqual(60, prompts.CONSENT_SECONDS)
        self.assertEqual(("9:05", "1:02:03", "0:00"), (prompts.remaining_text(545), prompts.remaining_text(3723),
                                                      prompts.remaining_text(-4)))

    def test_bad_options_still_answer_one_line(self) -> None:
        """The agent always gets one JSON line and exit 0, even for options it got wrong."""

        result = subprocess.run([sys.executable, str(ROOT / "usr/bin/caramos-business"), "--prompt", "countdown",
                                 "--action", "explode"], capture_output=True, text=True, timeout=30,
                                env={"PYTHONPATH": str(ROOT / "usr/lib/python3/dist-packages"), "PATH": "/usr/bin",
                                     "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(0, result.returncode)
        self.assertEqual({"answer": "timeout"}, json.loads(result.stdout.strip().splitlines()[-1]))

    def test_help_request_outbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "caramos-business" / "outbox"
            first = prompts.write_help_request("  Máy in không in được.  ", folder, now=1795200000)
            second = prompts.write_help_request("x" * 400, folder, now=1795200000)
            self.assertEqual("help-1795200000.json", first.name)
            self.assertEqual("help-1795200000-1.json", second.name)
            self.assertEqual({"note": "Máy in không in được."}, json.loads(first.read_text(encoding="utf-8")))
            self.assertEqual(300, len(json.loads(second.read_text(encoding="utf-8"))["note"]))
            self.assertEqual([], [path.name for path in folder.iterdir() if path.name.startswith(".")])
        self.assertEqual(Path("/run/user/1000/caramos-business/outbox"),
                         prompts.outbox({"XDG_RUNTIME_DIR": "/run/user/1000"}))


class NoticeShownTests(unittest.TestCase):
    """0.3.1's full pass: the firewall, the browser and USB rules applied before the notice showed. The notice's window
    now says when it is on the screen, and the session part tells the daemon only then."""

    def test_the_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = prompts.shown_marker({"XDG_RUNTIME_DIR": tmp})
            self.assertEqual(Path(tmp) / "caramos-business" / "notice-shown", marker)
            prompts.mark_shown(marker)
            first = marker.stat().st_mtime_ns
            prompts.mark_shown(marker)
            self.assertGreaterEqual(marker.stat().st_mtime_ns, first)
            self.assertEqual(["notice-shown"], sorted(path.name for path in marker.parent.iterdir()), "renamed whole")
            blocked = Path(tmp) / "a-file"
            blocked.touch()
            prompts.mark_shown(blocked / "caramos-business" / "notice-shown")  # its folder cannot be made: no error


class DiscoveryTests(unittest.TestCase):
    def test_asks_from_discoverys_port(self) -> None:
        """The window's discovery sends from UDP 47021 when it is free (a firewall lets the answers in there)."""

        import socket

        from caramos_business import client

        sent: list[tuple[str, int]] = []

        class FakeSocket:
            def __init__(self, *_args: object) -> None:
                self.bound: tuple[str, int] | None = None

            def __enter__(self) -> "FakeSocket":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def setsockopt(self, *_args: object) -> None:
                return None

            def settimeout(self, _value: float) -> None:
                return None

            def bind(self, address: tuple[str, int]) -> None:
                self.bound = address

            def sendto(self, _data: bytes, _target: tuple[str, int]) -> None:
                sent.append(self.bound or ("", 0))

            def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
                raise OSError("no answer in the test")

        with mock.patch.object(client.socket, "socket", FakeSocket):
            self.assertEqual([], client.discover(0.1))
        self.assertEqual([("0.0.0.0", 47021)], sent)
        self.assertIs(socket.socket, client.socket.socket)


class CloneTests(unittest.TestCase):
    def test_a_cloned_disk(self) -> None:
        from caramos_business import client

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            machine_id, marker = root / "machine-id", root / "clone.json"
            info = {"machine_id_os": "0123456789abcdef0123456789abcdef"}
            machine_id.write_text("0123456789abcdef0123456789abcdef\n")
            self.assertFalse(client.cloned(info, machine_id, marker), "the machine that was paired")
            machine_id.write_text("fedcba9876543210fedcba9876543210\n")
            self.assertTrue(client.cloned(info, machine_id, marker))
            self.assertFalse(client.cloned({}, machine_id, marker), "paired before machine_id_os was kept")
            self.assertFalse(client.cloned(info, root / "missing", marker))
            marker.write_text("{}")
            self.assertTrue(client.cloned({}, machine_id, marker), "the agent marked it")
            machine_id.write_text("not a machine id")
            self.assertEqual("", client.os_machine_id(machine_id))

    def test_a_pairing_by_version_0_1(self) -> None:
        from caramos_business import client

        with tempfile.TemporaryDirectory() as tmp:
            box_key = Path(tmp) / "agent-box.key"
            self.assertTrue(client.paired_by_older_version({"admin_name": "quan-ly"}, box_key))
            self.assertFalse(client.paired_by_older_version(None, box_key), "not paired at all")
            box_key.write_bytes(b"k" * 32)
            self.assertFalse(client.paired_by_older_version({"admin_name": "quan-ly"}, box_key))


class TransparencyTests(unittest.TestCase):
    def test_only_what_is_in_effect(self) -> None:
        policy = json.loads((V2 / "policy.json").read_text(encoding="utf-8"))
        machine_id = json.loads((V2 / "keys.json").read_text(encoding="utf-8"))["machine_id"]
        items = dict(transparency.managed_items(protocol.effective_settings(policy, machine_id)))
        self.assertEqual({"Wallpaper", "Browser", "Printers", "Power schedule", "USB storage", "Screen lock", "Wi-Fi",
                          "Shared drives", "Apps"}, set(items))
        self.assertNotIn("Automatic inventory", items, "the inventory is opt-in, and off in this policy")
        self.assertIn("Máy in tầng 2", items["Printers"])
        self.assertIn("5 minutes", items["Screen lock"])
        self.assertEqual([], transparency.managed_items({"browser": None, "usb": None}))
        self.assertEqual(["Automatic inventory"],
                         [title for title, _sentence in transparency.managed_items({"inventory": {"enabled": True}})])

    def test_the_fixed_lists(self) -> None:
        self.assertEqual(5, len(transparency.never_items()))
        self.assertEqual(2, len(transparency.always_items()))

    def test_stored_settings(self) -> None:
        policy = json.loads((V2 / "policy.json").read_text(encoding="utf-8"))
        machine_id = json.loads((V2 / "keys.json").read_text(encoding="utf-8"))["machine_id"]
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            self.assertEqual(({}, ""), transparency.stored_settings(state))
            (state / "policy.json").write_text(json.dumps(policy), encoding="utf-8")
            (state / "admin.json").write_text(json.dumps({"admin_name": "x", "machine_id": machine_id}),
                                              encoding="utf-8")
            settings, admin_name = transparency.stored_settings(state)
            self.assertEqual("máy-quản-lý", admin_name)
            self.assertEqual({"storage": "block"}, settings["usb"], "this machine's department blocks USB")
            # The agent's effective.json wins: the daemon merged it for this machine.
            (state / "effective.json").write_text(json.dumps({"serial": 12, "machine_id": machine_id,
                                                              "admin_name": "quan-ly", "settings": {"firewall": {
                                                                  "enabled": True}}}), encoding="utf-8")
            self.assertEqual(({"firewall": {"enabled": True}}, "quan-ly"), transparency.stored_settings(state))


class SummaryTests(unittest.TestCase):
    def test_sections(self) -> None:
        self.assertEqual("Off.", summaries.summary("usb", None))
        self.assertEqual("USB storage blocked.", summaries.summary("usb", {"storage": "block"}))
        self.assertEqual("Shuts down at 18:30, Mon to Sat.", summaries.summary(
            "power", {"shutdown": {"days": [1, 2, 3, 4, 5, 6], "time": "18:30"}, "wake": None}))
        browser = summaries.summary("browser", {"homepage": None, "bookmarks": [], "block": ["facebook.com"],
                                                "block_hours": None, "safe_search": False})
        self.assertEqual("Blocks 1 other website all the time.", browser)
        for section in protocol.SECTIONS:
            with self.subTest(section):
                self.assertTrue(summaries.summary(section, None))

    def test_audit_lines_in_the_readers_language(self) -> None:
        lines = [
            ({"action": "register", "summary": "kt-01 đã vào công ty", "details": {"name": "kt-01", "ip": "10.0.0.5"}},
             "kt-01 joined the company (10.0.0.5)."),
            ({"action": "settings", "summary": "x", "details": {"changes": [["department:kho", "usb"],
                                                                            ["company", "members"]]}},
             "Settings saved: USB storage (department Kho hàng), who is in which department."),
            ({"action": "command", "summary": "x", "details": {"command": "message", "targets": {"all": True},
                                                               "args": {"title": "Họp"}, "names": []}},
             "Send a message “Họp”: all machines."),
            ({"action": "command", "summary": "x", "details": {"command": "lock", "targets": {"machines": ["m"]},
                                                               "args": {}, "names": ["kt-01"]}}, "Lock: kt-01."),
            ({"action": "pairing", "summary": "x", "details": {"pairing": "open"}},
             "Adding machines opened for 10 minutes."),
            ({"action": "help", "summary": "x", "details": {"outcome": "closed", "name": "kt-01"}},
             "A help request from kt-01 was closed."),
            ({"action": "ticket", "summary": "x", "details": {"ticket": "HT-0001", "note": "internal"}},
             "Ticket HT-0001: an internal note."),
            ({"action": "ticket", "summary": "x", "details": {"ticket": "HT-0001", "status": "done"}},
             "Ticket HT-0001: Finished."),
            ({"action": "asset", "summary": "x", "details": {"name": "Màn hình Dell", "event": "added"}},
             "The asset Màn hình Dell was added."),
            ({"action": "licences", "summary": "x", "details": {"count": 1}},
             "The list of bought licences was changed (1 entry)."),
            ({"action": "licences", "summary": "x", "details": {"count": 3}},
             "The list of bought licences was changed (3 entries)."),
            ({"action": "unknown", "summary": "written by a later version"}, "written by a later version"),
            ({"action": "settings", "summary": "broken details", "details": {"changes": "nope"}}, "broken details"),
        ]
        for line, expected in lines:
            with self.subTest(action=line["action"]):
                self.assertEqual(expected, summaries.audit_text(line, lambda key: {"kho": "Kho hàng"}.get(key, key),
                                                                lambda key: key))

    def test_remote_help_results(self) -> None:
        """The agent words the result in Vietnamese with the mode in English: 0.3.0 showed "Xong: chạy 19 giây
        (control), người dùng dừng"."""

        self.assertEqual("chạy 19 giây (control), người dùng dừng",
                         summaries.result_detail("remote_help", "chạy 19 giây (control), người dùng dừng"))
        self.assertEqual("chạy 3 phút (view only), bên quản lý đã đóng",
                         summaries.result_detail("remote_help", "chạy 3 phút (view), bên quản lý đã đóng"))
        self.assertEqual("người dùng từ chối", summaries.result_detail("remote_help", "người dùng từ chối"))
        self.assertEqual("x (view)", summaries.result_detail("lock", "x (view)"))

    def test_update_results(self) -> None:
        """0.3.1's full pass: "caramos-ota --check: ok; 321 security updates installed" showed in English in the
        Vietnamese window. The agent now sends the steps; an older agent's words are read as steps."""

        steps = [{"step": "snapshot", "ok": True}, {"step": "caramos-ota", "ok": True},
                 {"step": "security", "ok": True, "count": 321}]
        expected = "system snapshot taken; CaramOS update checked; 321 security updates installed"
        self.assertEqual(expected, summaries.result_detail("update", "the older words", steps))
        self.assertEqual(expected, summaries.result_detail(
            "update", "đã chụp bản lưu hệ thống; caramos-ota --check: ok; 321 security updates installed"))
        self.assertEqual("CaramOS update checked; 1 security update installed",
                         summaries.result_detail("update", "caramos-ota --check: ok; 1 security updates installed"))
        self.assertEqual("no security updates", summaries.result_detail("update", "no security updates"))
        self.assertEqual("no system snapshot: timeshift: x; the CaramOS update check failed: exit status 1; security "
                         "updates failed: apt-get update: E: y",
                         summaries.result_detail("update", "không chụp được bản lưu hệ thống: timeshift: x; caramos-ota "
                                                           "--check: exit status 1; apt-get update: E: y"))
        self.assertEqual("something else", summaries.result_detail("update", "something else"), "unknown words stay")
        self.assertEqual("the machine is frozen: it updates in its maintenance time",
                         summaries.result_detail("update", summaries.FROZEN_UPDATE))

    def test_maintenance_results(self) -> None:
        text = summaries.maintenance_text
        self.assertEqual("CaramOS update checked; no security updates; apps done",
                         text("cập nhật: caramos-ota --check: ok; no security updates; ứng dụng: xong"))
        self.assertEqual("security updates failed: apt-get update: E: x", text("lỗi cập nhật: apt-get update: E: x"))
        self.assertEqual("skipped: someone was using the machine", text("bỏ qua: có người đang dùng"))
        self.assertEqual("error: grub-reboot: failed", text("lỗi: grub-reboot: failed"))
        self.assertEqual("CaramOS update checked; apps: flatpak: x",
                         text("cập nhật: …", [{"step": "caramos-ota", "ok": True},
                                             {"step": "apps", "ok": False, "error": "flatpak: x"}]))
        self.assertEqual(("", "lạ"), (text(""), text("lạ")))

    def test_in_vietnamese(self) -> None:
        """0.3.1's sentences through po/vi.po: the remote help mode, and a scope inside a sentence ("Đã yêu cầu Mọi
        máy …" in 0.3.0); after the full test pass, an update's and a maintenance's result (English in 0.3.1)."""

        msgfmt = shutil.which("msgfmt")
        if msgfmt is None:
            self.skipTest("msgfmt (gettext) is not installed")
        code = """if True:
            from caramos_business import summaries
            from caramos_business.i18n import _
            print(_("Done: %s") % summaries.result_detail("remote_help", "chạy 19 giây (control), người dùng dừng"))
            print(summaries.result_detail("remote_help", "chạy 2 phút (view), bên quản lý đã đóng"))
            print(_("Asked %s to take inventory again.") % summaries.targets_text({"all": True}, str, []))
            print(_("Sent to %s.") % summaries.targets_text({"departments": ["kt"]}, lambda key: "Kế toán", []))
            print(_("Locking %s.") % summaries.targets_text({"machines": ["m"]}, str, ["ke-toan-01"]))
            print(_("Done: %s") % summaries.result_detail(
                "update", "đã chụp bản lưu hệ thống; caramos-ota --check: ok; 321 security updates installed"))
            print(summaries.maintenance_text("cập nhật: caramos-ota --check: ok; no security updates; ứng dụng: xong"))
            print(summaries.audit_text({"action": "licences", "details": {"count": 1}}, str, str))
        """
        with tempfile.TemporaryDirectory() as folder:
            mo = Path(folder) / "vi" / "LC_MESSAGES" / "caramos-business.mo"
            mo.parent.mkdir(parents=True)
            subprocess.run([msgfmt, "-o", str(mo), str(ROOT / "po" / "vi.po")], check=True)
            result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30,
                                    env={"PYTHONPATH": str(ROOT / "usr/lib/python3/dist-packages"),
                                         "CARAMOS_BUSINESS_LOCALEDIR": folder, "LANGUAGE": "vi", "LANG": "C.UTF-8",
                                         "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
                                         "PATH": os.environ.get("PATH", "/usr/bin")})
        self.assertEqual("", result.stderr)
        self.assertEqual(["Xong: chạy 19 giây (điều khiển), người dùng dừng",
                          "chạy 2 phút (chỉ xem), bên quản lý đã đóng",
                          "Đã yêu cầu mọi máy gửi thông tin kiểm kê.",
                          "Đã gửi tới phòng Kế toán.",
                          "Đang khóa ke-toan-01.",
                          "Xong: đã chụp bản lưu hệ thống; đã kiểm tra bản cập nhật CaramOS; đã cài 321 bản vá bảo mật",
                          "đã kiểm tra bản cập nhật CaramOS; không có bản vá bảo mật; ứng dụng: xong",
                          "Đã sửa danh sách bản quyền đã mua (1 mục)."], result.stdout.splitlines())


if __name__ == "__main__":
    unittest.main()

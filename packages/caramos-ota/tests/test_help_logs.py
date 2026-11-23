"""Asking for help after a failure: the logs the App Center and the Update Center hand to Feedback & Help, how
personal data is taken out of them, and where they go in the request (only VNLF's team sees them)."""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
# Driver Check lives in /usr/share/caramos-ota/driver-check, outside dist-packages.
sys.path.insert(0, str(ROOT / "usr/share/caramos-ota/driver-check"))

from caramos_driver_check import help_app, helpdesk, logs  # noqa: E402
from caramos_ota_notifier import problem  # noqa: E402

URL = "https://github.com/VN-Linux-Family/zalo-for-linux/releases/download/26.10.11/Zalo-26.10.11%2BZaDark-26.2.1-285ba91-x86_64.AppImage"
SHA = "44316b4441adc4d68375b48092eac0465a35885ec55611f44c7680b93315473b"


class RedactTests(unittest.TestCase):
    def test_personal_data_goes_and_what_helps_debugging_stays(self) -> None:
        home = os.path.realpath(os.path.expanduser("~"))
        text = (f"sized the middle panel icons of minhanh at 32 px\n"
                f"open {home}/.config/ZaloData/cal/main.meta\n"
                f"mail tu.nguyen@example.com from 192.168.1.23 on {socket.gethostname()} (aa:bb:cc:dd:ee:ff)\n"
                f"password=hunter2\n"
                f"download {URL}\nsha256 {SHA}\n"
                f"minhanhos is not the user\n")
        redacted = logs.redact(text, user="minhanh")
        for gone in ("minhanh at", home, "tu.nguyen@example.com", "192.168.1.23", "aa:bb:cc:dd:ee:ff", "hunter2"):
            self.assertNotIn(gone, redacted)
        self.assertIn("icons of [REDACTED_USER] at 32 px", redacted)
        self.assertIn(URL, redacted)
        self.assertIn(SHA, redacted)
        self.assertIn("minhanhos is not the user", redacted)

    def test_short_login_names_are_ordinary_words(self) -> None:
        self.assertEqual("an toàn", logs.redact("an toàn", user="an"))

    def test_a_log_keeps_its_end(self) -> None:
        text = "\n".join(f"line {number}" for number in range(10000))
        kept = logs.tail(text, 1000)
        self.assertTrue(kept.startswith("…\nline "))
        self.assertTrue(kept.endswith("line 9999"))
        self.assertLessEqual(len(kept), 1002)
        self.assertEqual("short", logs.tail("short", 1000))

    def test_read_logs(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for number in range(6):
                path = Path(folder) / f"log{number}.log"
                path.write_text(f"failure {number}\n", encoding="utf-8")
                paths.append(path)
            (Path(folder) / "empty.log").write_text("\n", encoding="utf-8")
            read = logs.read_logs([Path(folder) / "missing.log", Path(folder) / "empty.log", *paths])
        self.assertEqual(["log0.log", "log1.log"], [log.name for log in read])   # at most MAX_LOGS paths are read
        self.assertEqual("failure 0", read[0].text)


class RequestTests(unittest.TestCase):
    REPORT = {"areas": [], "findings": [{"key": "audio:failed", "level": "warning", "title": "No sound"}]}

    def test_logs_go_with_the_report_which_only_moderators_see(self) -> None:
        payload = helpdesk.build_request("App Center chưa cài được Zalo.", report=self.REPORT, kind="bug",
                                         app="caramos-help", logs={"install-failure.log": "Reason: offline"})
        self.assertEqual({"install-failure.log": "Reason: offline"}, payload["report"]["logs"])
        self.assertEqual(self.REPORT["findings"], payload["report"]["findings"])
        self.assertNotIn("logs", payload)
        without_report = helpdesk.build_request("App Center chưa cài được Zalo.", logs={"a.log": "x"})
        self.assertEqual({"logs": {"a.log": "x"}}, without_report["report"])

    def test_long_logs_are_cut_from_the_start_to_fit_the_api(self) -> None:
        big = "\n".join(f"line {number} " + "x" * 80 for number in range(3000))
        payload = helpdesk.build_request("The update failed again.", report=self.REPORT,
                                         logs={"update-failure.log": big, "other.log": big})
        report = payload["report"]
        self.assertLessEqual(helpdesk.length(json.dumps(report, ensure_ascii=False, separators=(",", ":"))),
                             helpdesk.MAX_REPORT)
        for text in report["logs"].values():
            self.assertTrue(text.startswith("…line "))
            self.assertTrue(text.endswith("line 2999 " + "x" * 80))
        self.assertEqual(self.REPORT["findings"], report["findings"])

    def test_the_preview_shows_the_logs_but_a_post_to_paste_does_not(self) -> None:
        payload = helpdesk.build_request("The update failed again.", logs={"update-failure.log": "E: broken"})
        self.assertIn("--- update-failure.log ---\nE: broken", helpdesk.as_text(payload, with_logs=True))
        self.assertNotIn("E: broken", helpdesk.as_text(payload))

    def test_the_contract_documents_the_logs(self) -> None:
        document = (ROOT / "HELP_API.md").read_text(encoding="utf-8")
        self.assertIn('"logs"', document)
        self.assertIn("caramos-help --type bug --message", document)


class CommandTests(unittest.TestCase):
    def test_an_app_that_failed_starts_the_form(self) -> None:
        args = help_app.parse_args(["--type", "bug", "--message", "App Center chưa cài được Zalo.",
                                    "--log", "/tmp/a.log", "--log", "b.log"])
        self.assertEqual(("bug", "App Center chưa cài được Zalo.", ["/tmp/a.log", "b.log"]),
                         (args.kind, args.message, args.logs))
        self.assertEqual(("os", "", []), (help_app.parse_args([]).kind, help_app.parse_args([]).message,
                                          help_app.parse_args([]).logs))


class UpdateCenterTests(unittest.TestCase):
    INFO = {"title": "Biểu tượng giữa thanh tác vụ nằm gọn trong khung", "title_en": "Taskbar icons fit their dock again",
            "current_version": "1.3.1", "migration_ids": ["20261018120000_restore_taskbar_after_cinnamon_update"]}

    def test_the_log_has_the_output_and_the_end_of_the_ota_log(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / "2026-10-17.log").write_text("old day\n", encoding="utf-8")
            (Path(folder) / "2026-10-18.log").write_text("x" * 100000 + "\nMigration 2026 failed: disk full\n",
                                                          encoding="utf-8")
            text = problem.failure_log_text("Error: Migration update failed.", self.INFO, Path(folder))
        self.assertIn("Installed: CaramOS 1.3.1; update: Taskbar icons fit their dock again", text)
        self.assertIn("Migrations: 20261018120000_restore_taskbar_after_cinnamon_update", text)
        self.assertIn("== Output of caramos-ota --upgrade ==\nError: Migration update failed.", text)
        self.assertIn("2026-10-18.log ==", text)
        self.assertIn("Migration 2026 failed: disk full", text)
        self.assertNotIn("old day", text)
        self.assertLess(len(text), problem.OTA_LOG_TAIL + 2000)

    def test_without_a_readable_ota_log_the_output_is_enough(self) -> None:
        text = problem.failure_log_text("Error", None, Path("/nonexistent"))
        self.assertIn("== Output of caramos-ota --upgrade ==\nError", text)
        self.assertNotIn("== End of", text)

    def test_ask_for_help_opens_feedback_and_help_with_the_log(self) -> None:
        with tempfile.TemporaryDirectory() as cache, mock.patch.dict(os.environ, {"XDG_CACHE_HOME": cache}), \
                mock.patch.object(problem.subprocess, "Popen") as popen, \
                mock.patch.object(problem, "help_message", return_value="Trung tâm cập nhật không cài được."):
            self.assertTrue(problem.ask_for_help("Error", self.INFO))
            log = Path(cache) / "caramos-ota/update-failure.log"
            self.assertTrue(log.read_text(encoding="utf-8").startswith("Update Center: the update failed"))
        self.assertEqual(["/usr/bin/caramos-help", "--type", "bug", "--message", "Trung tâm cập nhật không cài được.",
                          "--log", str(log)], popen.call_args.args[0])

    def test_the_failed_page_offers_it(self) -> None:
        ui = (ROOT / "usr/lib/python3/dist-packages/caramos_ota_notifier/ui.py").read_text(encoding="utf-8")
        app = (ROOT / "usr/lib/python3/dist-packages/caramos_ota_notifier/app.py").read_text(encoding="utf-8")
        self.assertIn('_button(Gtk, _("Ask for help"), on_help', ui)
        self.assertIn("problem.ask_for_help(detail, self.update_info)", app)


if __name__ == "__main__":
    unittest.main()

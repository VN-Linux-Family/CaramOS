"""The daily count of CaramOS computers in use (caramos_ota.stats): once a day the daily check sends an id that changes
every day, the version and the edition, nothing else; off with /etc/caramos-ota/stats.conf STATS=no or
`caramos-ota --stats off`. Never the real address in these tests: a fake sender, or a server on 127.0.0.1."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from caramos_ota import cli, stats

MACHINE = "0123456789abcdef0123456789abcdef"
ICT = timezone(timedelta(hours=7))


class Sender:
    """Answers like the site would, and keeps what it was given."""

    def __init__(self, status: int = 204, error: Exception | None = None) -> None:
        self.status = status
        self.error = error
        self.calls: list[tuple[str, dict, float]] = []

    def __call__(self, address: str, data: bytes, timeout: float) -> int:
        self.calls.append((address, json.loads(data), timeout))
        if self.error is not None:
            raise self.error
        return self.status


class Folder(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.settings = self.root / "etc/caramos-ota/stats.conf"
        self.last = self.root / "var/lib/caramos-ota/stats.json"
        self.machine = self.root / "etc/machine-id"
        self.machine.parent.mkdir(parents=True)
        self.machine.write_text(MACHINE + "\n", encoding="ascii")
        patcher = mock.patch.dict(os.environ, {"CARAMOS_OTA_STATS_URL": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def daily(self, sender: Sender, now: datetime, edition: str = "cinnamon", live: bool = False) -> str:
        with mock.patch.object(stats, "log_info"):
            return stats.daily("1.5.2", edition, now=now, sender=sender, settings=self.settings, last=self.last,
                               machine=self.machine, live=lambda: live)


class CountTests(Folder):
    NOW = datetime(2026, 11, 25, 9, 30, tzinfo=ICT)

    def test_what_is_sent(self) -> None:
        sender = Sender()
        self.assertEqual(stats.SENT, self.daily(sender, self.NOW))
        address, data, timeout = sender.calls[0]
        self.assertEqual("https://caramos.vietnamlinuxfamily.net/api/active", address)
        expected = hashlib.sha256(f"{MACHINE}:2026-11-25:caramos-active".encode()).hexdigest()
        self.assertEqual({"id": expected, "version": "1.5.2", "edition": "cinnamon"}, data)
        self.assertLessEqual(timeout, 10)
        self.assertEqual({"last_sent": "2026-11-25"}, json.loads(self.last.read_text(encoding="utf-8")))

    def test_once_a_day_with_an_id_of_that_day(self) -> None:
        sender = Sender()
        self.daily(sender, self.NOW)
        self.assertEqual(stats.ALREADY, self.daily(sender, self.NOW + timedelta(hours=5)))
        self.assertEqual(1, len(sender.calls))
        self.assertEqual(stats.SENT, self.daily(sender, self.NOW + timedelta(days=1)))
        first, second = (call[1]["id"] for call in sender.calls)
        self.assertNotEqual(first, second, "two days of one computer cannot be linked")
        self.assertEqual(64, len(first))
        self.assertNotIn(MACHINE, json.dumps([call[1] for call in sender.calls]))

    def test_the_day_is_the_utc_day(self) -> None:
        self.assertEqual("2026-11-25", stats.today(datetime(2026, 11, 26, 6, 59, tzinfo=ICT)))
        self.assertEqual("2026-11-26", stats.today(datetime(2026, 11, 26, 7, 0, tzinfo=ICT)))

    def test_a_failure_waits_for_the_next_check(self) -> None:
        for sender in (Sender(error=OSError("no network")), Sender(error=TimeoutError()), Sender(status=500),
                       Sender(status=404)):
            with self.subTest(sender=sender.status):
                self.assertEqual(stats.FAILED, self.daily(sender, self.NOW))
                self.assertFalse(self.last.exists(), "not counted: the next check tries again")
        self.assertEqual(stats.SENT, self.daily(Sender(status=200), self.NOW))

    def test_when_nothing_is_sent(self) -> None:
        sender = Sender()
        self.assertEqual(stats.LIVE, self.daily(sender, self.NOW, live=True))
        self.assertEqual(stats.OTHER_DESKTOP, self.daily(sender, self.NOW, edition="other"))
        self.machine.write_text("", encoding="ascii")
        self.assertEqual(stats.NO_ID, self.daily(sender, self.NOW))
        self.assertEqual([], sender.calls)

    def test_the_setting_turns_it_off(self) -> None:
        sender = Sender()
        stats.set_enabled(False, self.settings)
        self.assertEqual(0o644, self.settings.stat().st_mode & 0o777)
        self.assertIn("STATS=no\n", self.settings.read_text(encoding="utf-8"))
        self.assertEqual(stats.OFF, self.daily(sender, self.NOW))
        self.assertEqual([], sender.calls)
        stats.set_enabled(True, self.settings)
        self.assertEqual(stats.SENT, self.daily(sender, self.NOW))
        for text, enabled in (("STATS=no\n", False), ('STATS="off"\n', False), ("# STATS=no\n", True),
                              ("STATS=maybe\n", True), ("STATS=yes\n", True)):
            with self.subTest(text=text):
                self.settings.write_text(text, encoding="utf-8")
                self.assertIs(enabled, stats.is_enabled(self.settings))

    def test_a_test_computer_can_point_it_elsewhere(self) -> None:
        with mock.patch.dict(os.environ, {"CARAMOS_OTA_STATS_URL": "http://192.168.122.1:8765/api/active"}):
            self.assertEqual("http://192.168.122.1:8765/api/active", stats.url())
        self.assertEqual(stats.URL, stats.url())


class Server:
    """A local server answering every POST with a status, and keeping each request."""

    def __init__(self, status: int) -> None:
        self.requests: list[tuple[str, dict, bytes]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):   # noqa: N802 - http.server API
                data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}, data))
                self.send_response(status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/api/active"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class HttpTests(Folder):
    def test_the_request_carries_only_the_json(self) -> None:
        server = Server(204)
        self.addCleanup(server.close)
        with mock.patch.dict(os.environ, {"CARAMOS_OTA_STATS_URL": server.url}):
            self.assertEqual(stats.SENT, self.daily(None, datetime(2026, 11, 25, 9, 0, tzinfo=ICT), edition="xfce"))
        path, headers, data = server.requests[0]
        self.assertEqual("/api/active", path)
        self.assertEqual("application/json", headers["content-type"])
        self.assertEqual("caramos-ota", headers["user-agent"])
        self.assertNotIn("cookie", headers)
        self.assertEqual(["edition", "id", "version"], sorted(json.loads(data)))

    def test_an_error_status_is_a_failure(self) -> None:
        server = Server(503)
        self.addCleanup(server.close)
        with mock.patch.dict(os.environ, {"CARAMOS_OTA_STATS_URL": server.url}):
            self.assertEqual(stats.FAILED, self.daily(None, datetime(2026, 11, 25, 9, 0, tzinfo=ICT)))
        self.assertFalse(self.last.exists())


class CliTests(unittest.TestCase):
    def test_stats_on_off_changes_the_setting_without_the_ota_lock(self) -> None:
        parser = cli.build_parser()
        self.assertEqual("stats", cli.selected_action(parser.parse_args(["--stats", "off"])))
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            parser.parse_args(["--stats", "maybe"])
        with mock.patch.object(cli, "require_root"), mock.patch.object(cli, "init_log"), \
                mock.patch.object(cli, "acquire_lock") as lock, \
                mock.patch.object(cli.stats, "change_setting") as change, mock.patch("builtins.print"):
            self.assertEqual(0, cli.main(["--stats", "off"]))
            self.assertEqual(0, cli.main(["--stats", "on"]))
        lock.assert_not_called()
        self.assertEqual([False, True], [call.args[0] for call in change.call_args_list])

    def test_the_daily_check_counts_first(self) -> None:
        order = []
        release = SimpleNamespace(version="1.5.2")
        with mock.patch.object(cli, "require_root"), mock.patch.object(cli, "init_log"), \
                mock.patch.object(cli, "acquire_lock"), mock.patch.object(cli, "log_info"), \
                mock.patch.object(cli, "load_state", return_value={}), mock.patch.object(cli, "save_state"), \
                mock.patch.object(cli, "detect_caramos", return_value=release), mock.patch.object(cli, "banner"), \
                mock.patch.object(cli.stats, "run_from_check", side_effect=lambda v: order.append(("count", v))), \
                mock.patch.object(cli, "verify_repo", side_effect=lambda: order.append(("repo",))), \
                mock.patch.object(cli, "apt_update"), mock.patch.object(cli, "self_update_ota_if_needed"), \
                mock.patch.object(cli.zalo_update, "resume_in_background"), \
                mock.patch.object(cli, "detect_updates", return_value=(None, [])), mock.patch("builtins.print"):
            self.assertEqual(0, cli.main(["--check"]))
        self.assertEqual([("count", "1.5.2"), ("repo",)], order)

    def test_counting_never_stops_the_check(self) -> None:
        with mock.patch.object(stats, "daily", side_effect=RuntimeError("bug")), \
                mock.patch.object(stats, "log_info") as log:
            stats.run_from_check("1.5.2")
        self.assertIn("skipped", log.call_args.args[0])

    def test_status_says_whether_it_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            last = Path(folder) / "stats.json"
            last.write_text('{"last_sent": "2026-11-25"}', encoding="utf-8")
            with mock.patch.object(stats, "LAST_FILE", last), \
                    mock.patch.object(stats, "SETTINGS_FILE", Path(folder) / "stats.conf"):
                self.assertEqual(["Daily count:          on, last counted 2026-11-25"], stats.status_lines())


if __name__ == "__main__":
    unittest.main()

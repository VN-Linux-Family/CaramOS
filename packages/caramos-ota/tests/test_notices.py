"""Notices from the CaramOS team (caramos_ota.notices, caramos-ota-notices): the list the landing serves
(CaramOSLanding server/notices.js), which of them this computer shows, and what each user has seen."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from caramos_ota import notices, notices_window

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 27, 2, 0, tzinfo=timezone.utc)


def item(**overrides):
    """A notice as /api/thong-bao serves it (server/notices.js publicNotice)."""

    base = {
        "id": 3, "level": "warning", "title": {"vi": "Máy chưa cập nhật", "en": "Not updated"},
        "body": {"vi": "Mở Trung tâm cập nhật\nrồi bấm Cập nhật.", "en": "Open the Update Center."},
        "editions": "all", "min_version": "", "max_version": "", "condition": "all",
        "link": {"url": "https://caramos.vietnamlinuxfamily.net/", "label": {"vi": "Xem", "en": "See"}},
        "starts_at": "2026-11-27T00:00:00Z", "ends_at": "",
    }
    base.update(overrides)
    return base


def computer(version="1.4.0", edition="cinnamon", waiting=False, failing=False):
    return notices.Computer(version, edition, waiting, failing)


class ParseTests(unittest.TestCase):
    def test_the_servers_notice(self) -> None:
        [notice] = notices.parse({"schema": 1, "notices": [item()]})
        self.assertEqual(3, notice.id)
        self.assertEqual(("Máy chưa cập nhật", "Mở Trung tâm cập nhật\nrồi bấm Cập nhật."), notice.text(english=False))
        self.assertEqual(("Not updated", "Open the Update Center."), notice.text(english=True))
        self.assertEqual("See", notice.link_label(english=True))
        self.assertEqual(datetime(2026, 11, 27, tzinfo=timezone.utc), notice.starts_at)
        self.assertIsNone(notice.ends_at)

    def test_english_falls_back_to_vietnamese(self) -> None:
        [notice] = notices.parse({"schema": 1, "notices": [item(title={"vi": "Chào", "en": ""}, body={"vi": "Nội dung", "en": ""},
                                                                  link=None)]})
        self.assertEqual(("Chào", "Nội dung"), notice.text(english=True))
        self.assertEqual("", notice.link_label(english=True))

    def test_a_bad_notice_is_left_out_alone(self) -> None:
        bad = [
            item(id=True), item(id=0), item(id="4"), item(level="urgent"), item(editions="kde"), item(condition="always"),
            item(title={"vi": "", "en": ""}), item(body={"vi": "x" * 2001, "en": ""}), item(min_version="1.5.x"),
            item(link={"url": "https://example.com/", "label": {"vi": "Xem", "en": ""}}),
            item(link={"url": "http://caramos.vietnamlinuxfamily.net/", "label": {"vi": "Xem", "en": ""}}),
            item(link={"url": "https://caramos.vietnamlinuxfamily.net/", "label": {"vi": "", "en": ""}}),
            "not a notice",
        ]
        good = item(id=9)
        found = notices.parse({"schema": 1, "notices": [*bad, good]})
        self.assertEqual([9], [notice.id for notice in found])

    def test_another_schema_is_ignored(self) -> None:
        self.assertEqual([], notices.parse({"schema": 2, "notices": [item()]}))
        self.assertEqual([], notices.parse({"notices": [item()]}))
        self.assertEqual([], notices.parse([item()]))

    def test_links_as_the_server_allows_them(self) -> None:
        self.assertTrue(notices.link_allowed("https://vietnamlinuxfamily.net/caramos/H-1"))
        self.assertTrue(notices.link_allowed("https://caramos.vietnamlinuxfamily.net/"))
        for url in ("http://vietnamlinuxfamily.net/", "https://evilvietnamlinuxfamily.net/",
                    "https://vietnamlinuxfamily.net.evil.com/", "https://u:p@vietnamlinuxfamily.net/", "file:///etc/passwd"):
            self.assertFalse(notices.link_allowed(url), url)


class FetchTests(unittest.TestCase):
    def opener(self, data: bytes):
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = lambda limit: data[:limit]
        calls = []

        def open_(request, timeout):
            calls.append((request, timeout))
            return response
        return open_, calls

    def test_the_request_says_nothing_about_the_computer(self) -> None:
        open_, calls = self.opener(json.dumps({"schema": 1, "notices": [item()]}).encode())
        found = notices.fetch(opener=open_)
        self.assertEqual([3], [notice.id for notice in found])
        request, timeout = calls[0]
        self.assertEqual(notices.URL, request.full_url)
        self.assertEqual("https://caramos.vietnamlinuxfamily.net/api/thong-bao", request.full_url)
        self.assertEqual("caramos-ota-notices/1", request.get_header("User-agent"))
        self.assertIsNone(request.data)
        self.assertEqual(notices.TIMEOUT_SECONDS, timeout)

    def test_too_large_or_not_json(self) -> None:
        open_, _ = self.opener(b"x" * (notices.MAX_BYTES + 10))
        with self.assertRaises(ValueError):
            notices.fetch(opener=open_)
        open_, _ = self.opener(b"<html>")
        with self.assertRaises(ValueError):
            notices.fetch(opener=open_)


class AppliesTests(unittest.TestCase):
    def notice(self, **overrides):
        return notices.parse({"schema": 1, "notices": [item(**overrides)]})[0]

    def test_edition(self) -> None:
        self.assertTrue(notices.applies(self.notice(editions="xfce"), computer(edition="xfce"), NOW))
        self.assertFalse(notices.applies(self.notice(editions="xfce"), computer(edition="cinnamon"), NOW))
        self.assertTrue(notices.applies(self.notice(editions="all"), computer(edition="other"), NOW))

    def test_versions_compare_by_number(self) -> None:
        stuck = self.notice(max_version="1.5.1")
        for version, expected in (("1.0.12", True), ("1.0.16.1", True), ("1.5.1", True), ("1.5.2", False), ("", False)):
            self.assertEqual(expected, notices.applies(stuck, computer(version=version), NOW), version)
        newer = self.notice(min_version="1.0.16")
        self.assertTrue(notices.applies(newer, computer(version="1.0.16.1"), NOW))
        self.assertFalse(notices.applies(newer, computer(version="1.0.12"), NOW))
        self.assertTrue(notices.applies(self.notice(), computer(version=""), NOW), "no bounds: every version")

    def test_conditions(self) -> None:
        waiting = self.notice(condition="update-waiting")
        failing = self.notice(condition="update-failing")
        self.assertTrue(notices.applies(waiting, computer(waiting=True), NOW))
        self.assertFalse(notices.applies(waiting, computer(waiting=False), NOW))
        self.assertTrue(notices.applies(failing, computer(failing=True), NOW))
        self.assertFalse(notices.applies(failing, computer(failing=False), NOW))

    def test_time_window(self) -> None:
        self.assertFalse(notices.applies(self.notice(starts_at="2026-11-28T00:00:00Z"), computer(), NOW))
        self.assertFalse(notices.applies(self.notice(ends_at="2026-11-27T01:00:00Z"), computer(), NOW))
        self.assertTrue(notices.applies(self.notice(ends_at="2026-11-28T00:00:00Z"), computer(), NOW))

    def test_the_most_urgent_first_and_seen_ones_never(self) -> None:
        found = notices.parse({"schema": 1, "notices": [item(id=1, level="info"), item(id=2, level="critical"),
                                                          item(id=3, level="warning"), item(id=4, level="critical")]})
        self.assertEqual([2, 4, 3, 1], [n.id for n in notices.pending(found, computer(), set(), NOW)])
        self.assertEqual([4, 1], [n.id for n in notices.pending(found, computer(), {2, 3}, NOW)])


class ComputerTests(unittest.TestCase):
    def test_update_state(self) -> None:
        long_up, just_up = timedelta(hours=5), timedelta(minutes=10)
        fresh = {"last_check": "2026-11-26T20:00:00+07:00", "available_update": None}
        self.assertEqual((False, False), notices.update_state(fresh, NOW, long_up))
        self.assertEqual((True, False), notices.update_state({**fresh, "available_update": {"to_version": "1.5.2"}}, NOW, long_up))
        failed = {**fresh, "auto_update": {"outcome": "failed"}}
        self.assertEqual((False, True), notices.update_state(failed, NOW, just_up))
        old = {"last_check": "2026-11-20T08:00:00+07:00"}
        self.assertEqual((False, True), notices.update_state(old, NOW, long_up))
        self.assertEqual((False, False), notices.update_state(old, NOW, just_up), "just switched on: the check comes soon")
        self.assertEqual((False, True), notices.update_state({}, NOW, long_up), "never checked")

    def test_this_computer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state.json"
            release = Path(tmp) / "caramos-release"
            state.write_text(json.dumps({"available_update": {"to_version": "1.5.2"}, "last_check": "2026-11-27T01:00:00Z"}),
                             encoding="utf-8")
            release.write_text('NAME="CaramOS"\nVERSION="1.0.16.1"\n', encoding="utf-8")
            with mock.patch.dict(os.environ, {"CARAMOS_OTA_DESKTOP": "xfce"}):
                found = notices.this_computer(NOW, state, release, uptime=timedelta(hours=3))
            self.assertEqual(notices.Computer("1.0.16.1", "xfce", True, False), found)
            state.write_text("{broken", encoding="utf-8")
            with mock.patch.dict(os.environ, {"CARAMOS_OTA_DESKTOP": "cinnamon"}):
                self.assertEqual(notices.Computer("", "cinnamon", False, False),
                                 notices.this_computer(NOW, state, Path(tmp) / "missing", uptime=timedelta(0)))


class SeenTests(unittest.TestCase):
    def test_each_user_remembers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = notices.seen_file({"HOME": tmp})
            self.assertEqual(Path(tmp) / ".local/state/caramos-ota/notices.json", path)
            self.assertEqual(set(), notices.read_seen(path))
            notices.mark_seen(path, 3)
            notices.mark_seen(path, 1)
            notices.mark_seen(path, 3)
            self.assertEqual({1, 3}, notices.read_seen(path))
            path.write_text("[not json", encoding="utf-8")
            self.assertEqual(set(), notices.read_seen(path))
            self.assertEqual(Path(tmp) / "state/caramos-ota/notices.json",
                             notices.seen_file({"XDG_STATE_HOME": f"{tmp}/state", "HOME": tmp}))


class CommandTests(unittest.TestCase):
    def test_list_and_no_desktop(self) -> None:
        found = notices.parse({"schema": 1, "notices": [item(id=5, level="critical")]})
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(notices_window, "to_show", return_value=(found, Path(tmp) / "seen.json")), \
                mock.patch.object(notices_window, "show") as show:
            output = io.StringIO()
            with redirect_stdout(output), mock.patch.dict(os.environ, {"LANGUAGE": "vi"}):
                self.assertEqual(0, notices_window.main(["--list"]))
            self.assertEqual("#5 [critical] Máy chưa cập nhật\n", output.getvalue())
            with mock.patch.dict(os.environ, {"DISPLAY": "", "WAYLAND_DISPLAY": ""}):
                self.assertEqual(0, notices_window.main([]))
            show.assert_not_called()
            with mock.patch.dict(os.environ, {"DISPLAY": ":0"}):
                notices_window.main([])
            show.assert_called_once()

    def test_offline_is_quiet(self) -> None:
        with mock.patch.object(notices_window, "to_show", side_effect=OSError("no network")):
            self.assertEqual(0, notices_window.main([]))


class PackagingTests(unittest.TestCase):
    def test_every_session_gets_the_timer(self) -> None:
        timer = (ROOT / "usr/lib/systemd/user/caramos-ota-notices.timer").read_text(encoding="utf-8")
        service = (ROOT / "usr/lib/systemd/user/caramos-ota-notices.service").read_text(encoding="utf-8")
        self.assertIn("OnStartupSec=3min\n", timer)
        self.assertIn("OnUnitActiveSec=4h\n", timer)
        self.assertIn("WantedBy=timers.target\n", timer, "dh_installsystemduser enables it for every user")
        self.assertIn("ExecStart=/usr/bin/caramos-ota-notices\n", service)
        self.assertIn("Type=exec\n", service)
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        for line in ("usr/bin/caramos-ota-notices usr/bin/", "usr/lib/systemd/user/caramos-ota-notices.service usr/lib/systemd/user/",
                     "usr/lib/systemd/user/caramos-ota-notices.timer usr/lib/systemd/user/"):
            self.assertIn(line, install)
        self.assertTrue(os.access(ROOT / "usr/bin/caramos-ota-notices", os.X_OK))

    def test_vietnamese(self) -> None:
        po = (ROOT / "po/caramos-ota/vi.po").read_text(encoding="utf-8")
        self.assertIn('msgid "A notice from CaramOS"\nmsgstr "Thông báo từ CaramOS"', po)
        self.assertIn('msgid "Got it"\nmsgstr "Đã hiểu"', po)


if __name__ == "__main__":
    unittest.main()

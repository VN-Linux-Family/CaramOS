"""The admin's 0.3 records and reports (PROTOCOL.md part 3): tickets, the asset lifecycle and its handover document,
the licence report, the security report and the files they are exported to."""

from __future__ import annotations

import datetime
import io
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from caramos_business import admin, assets, handover, licences, protocol, reports, security, tickets

ROOT = Path(__file__).parents[1]
TZ = datetime.timezone(datetime.timedelta(hours=7))
NOW = datetime.datetime(2026, 11, 23, 9, 0, tzinfo=TZ)
MACHINE_A = "11111111-2222-4333-8444-555555555555"
MACHINE_B = "66666666-7777-4888-9999-000000000000"


class StateFixture(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state = self.root / "state"
        admin.prepare_state(self.state)


class TicketTests(StateFixture):
    def test_lifecycle(self) -> None:
        request = {"user": "lan", "note": "Máy in không in được", "time": ""}
        health = {"disk_free_pct": 40}
        inventory = {"system": {"vendor": "Dell Inc.", "product": "OptiPlex 3080"}, "cpu": {"model": "i5"},
                     "memory": {"total_mb": 7834}, "disks": [{"model": "KINGSTON", "size_gb": 256, "health": "ok"}],
                     "os": {"caramos": "1.4.0"}}
        ticket, version = tickets.create(self.state, MACHINE_A, request, health, inventory, NOW)
        self.assertEqual(("HT-0001", 1, "new"), (ticket["id"], version, ticket["status"]))
        self.assertEqual({"model": "Dell Inc. OptiPlex 3080", "cpu": "i5", "memory_mb": 7834,
                          "disks": [{"model": "KINGSTON", "size_gb": 256, "health": "ok"}], "caramos": "1.4.0"},
                         ticket["snapshot"]["inventory_summary"])
        second, _version = tickets.create(self.state, MACHINE_B, request, None, None, NOW)
        self.assertEqual("HT-0002", second["id"])
        # An internal note is not a response, and the employee sees no difference.
        internal = tickets.validate_change({"id": "HT-0001", "note": {"text": "Hỏng trống mực", "public": False}})
        tickets.change(self.state, internal, "caram", NOW)
        store = tickets.read(self.state)
        self.assertEqual((1, None), (tickets.version(store, MACHINE_A), tickets.find(store, "HT-0001")["first_response"]))
        later = NOW + datetime.timedelta(minutes=12)
        tickets.change(self.state, tickets.validate_change({"id": "HT-0001", "status": "working", "assignee": "Tuấn"}),
                       "caram", later)
        store = tickets.read(self.state)
        found = tickets.find(store, "HT-0001")
        self.assertEqual((2, later.isoformat(), "Tuấn"), (tickets.version(store, MACHINE_A), found["first_response"],
                                                          found["assignee"]))
        tickets.change(self.state, tickets.validate_change({"id": "HT-0001", "status": "done",
                                                            "note": {"text": "Đã thay mực.", "public": True}}),
                       "caram", later)
        found = tickets.find(tickets.read(self.state), "HT-0001")
        self.assertEqual(("done", later.isoformat()), (found["status"], found["closed"]))
        self.assertEqual([{"time": later.isoformat(), "status": "working", "text": ""},
                          {"time": later.isoformat(), "status": "done", "text": "Đã thay mực."}],
                         tickets.machine_list(tickets.read(self.state), MACHINE_A, later)["tickets"][0]["updates"])
        self.assertIsNone(tickets.change(self.state, {"id": "HT-0099", "status": "done"}, "caram"))
        report = tickets.month_report(tickets.read(self.state), 2026, 11)
        self.assertEqual((2, 12, {"new": 1, "working": 0, "waiting": 0, "done": 1}),
                         (report["total"], report["median_first_response_minutes"], report["counts"]))

    def test_bad_changes(self) -> None:
        for change in ({"id": "HT-1"}, {"id": "HT-0001", "status": "closed"}, {"id": "HT-0001", "assignee": "x" * 61},
                       {"id": "HT-0001", "note": {"text": "", "public": True}},
                       {"id": "HT-0001", "note": {"text": "x", "public": "yes"}}, []):
            with self.subTest(change=change), self.assertRaises(protocol.ProtocolError):
                tickets.validate_change(change)

    def test_at_most_twenty_open_tickets_per_machine(self) -> None:
        for number in range(tickets.MAX_OPEN_PER_MACHINE + 2):
            tickets.create(self.state, MACHINE_A, {"user": "lan", "note": str(number), "time": ""}, None, None, NOW)
        store = tickets.read(self.state)
        open_ = [item for item in store["tickets"] if item["status"] != "done"]
        self.assertEqual(tickets.MAX_OPEN_PER_MACHINE, len(open_))
        self.assertEqual(["0", "1"], [item["note"] for item in store["tickets"] if item["status"] == "done"])


class AssetTests(StateFixture):
    def values(self, **changes: object) -> dict:
        base = {"asset_code": "TS-01", "purchase_date": "2024-03-15", "price_vnd": 12000000,
                "warranty_until": "2026-12-10", "holder": "", "location": "Tầng 2", "note": ""}
        base.update(changes)
        return base

    def test_history(self) -> None:
        admin.write_json(self.state / admin.MACHINES, {MACHINE_A: {"machine": {"name": "kt-01"}}})
        entry = assets.update(self.state, MACHINE_A, self.values(), "caram", NOW)
        self.assertEqual(("computer", "in_use", []), (entry["kind"], entry["status"], entry["history"]))
        entry = assets.update(self.state, MACHINE_A, self.values(holder="Lan"), "caram", NOW)
        self.assertEqual("2026-11-23", entry["holder_since"])
        self.assertEqual([("assigned", "Lan")], [(item["event"], item["note"]) for item in entry["history"]])
        entry = assets.update(self.state, MACHINE_A, self.values(holder="Lan", status="repair",
                                                                 add_event={"event": "note",
                                                                            "note": "Gửi hãng bảo hành"}),
                              "caram", NOW)
        self.assertEqual(["assigned", "repair", "note"], [item["event"] for item in entry["history"]])
        self.assertEqual([MACHINE_A], assets.in_repair(admin.read_assets(self.state)))
        self.assertEqual([MACHINE_A], assets.warranty_ending(admin.read_assets(self.state), NOW.date()))
        self.assertEqual([], assets.warranty_ending(admin.read_assets(self.state), NOW.date(), days=10))
        thing_id, thing = assets.create(self.state, self.values(name="Màn hình Dell", kind="monitor"), "caram", NOW)
        self.assertEqual(("in_stock", None, ["received"]), (thing["status"], thing["machine_id"],
                                                           [item["event"] for item in thing["history"]]))
        listed = assets.rows({MACHINE_A: {"machine": {"name": "kt-01"}}}, admin.read_assets(self.state))
        self.assertEqual([(MACHINE_A, "kt-01"), (thing_id, "Màn hình Dell")], [(row["id"], row["name"])
                                                                              for row in listed])
        for bad in ({"kind": "tablet"}, {"status": "lost"}, {"holder_since": "15/3/2024"}, {"leaver": ["x"]},
                    {"add_event": {"event": "stolen"}}):
            with self.subTest(bad=bad), self.assertRaises(protocol.ProtocolError):
                assets.validate(self.values(**bad), machine_id=MACHINE_A)
        with self.assertRaises(protocol.ProtocolError):
            assets.validate(self.values(), machine_id=None)  # a thing without a machine needs a name

    def test_history_is_capped(self) -> None:
        entry: dict = {"history": [{"time": "", "event": "note", "by": "", "note": str(n)} for n in range(200)]}
        assets._event(entry, "note", "caram", "mới", NOW)  # noqa: SLF001
        self.assertEqual((admin.MAX_HISTORY, "1", "mới"), (len(entry["history"]), entry["history"][0]["note"],
                                                           entry["history"][-1]["note"]))


class HandoverTests(unittest.TestCase):
    def test_the_committed_template_is_the_tools(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            subprocess.run([sys.executable, str(ROOT / "tools/make-handover-template.py"), "--out", folder],
                           check=True, capture_output=True)
            made = (Path(folder) / "bien-ban-ban-giao-tai-san.docx").read_bytes()
        self.assertEqual(made, (ROOT / "usr/share/caramos-business/templates/bien-ban-ban-giao-tai-san.docx")
                         .read_bytes(), "run tools/make-handover-template.py")

    def test_fill(self) -> None:
        template = ROOT / "usr/share/caramos-business/templates/bien-ban-ban-giao-tai-san.docx"
        rows = [handover.asset_row(1, "kt-01", {"asset_code": "TS-01", "kind": "computer", "note": "Kèm sạc"},
                                   {"system": {"vendor": "Dell Inc.", "product": "OptiPlex 3080", "serial": "8XK2"}}),
                handover.asset_row(2, "Màn hình <Dell> & co", {"kind": "monitor"}, None)]
        values = dict(handover.date_values(datetime.date(2026, 11, 23)), TEN_CONG_TY="CÔNG TY TNHH AN PHÁT",
                      DIA_DIEM="Hà Nội", BEN_GIAO="Nguyễn Văn Tuấn", CHUC_VU_GIAO="Nhân viên IT", BEN_NHAN="Trần Thị Lan",
                      LY_DO="Nhân viên mới")
        data = handover.fill(values, rows, template)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8")
            names = archive.namelist()
        self.assertNotIn("{{", xml)
        self.assertIn(">CÔNG TY TNHH AN PHÁT<", xml)
        self.assertEqual(2, xml.count(">Hà Nội<"))
        self.assertIn(">kt-01 (Dell Inc. OptiPlex 3080)<", xml)
        self.assertIn(">TS-01, 8XK2<", xml)
        self.assertIn(">Màn hình &lt;Dell&gt; &amp; co<", xml)
        self.assertIn(">Kèm sạc<", xml)
        self.assertEqual(2 + 1 + 2 + 1, xml.count("<w:tr>"), "the page header, the table's header, two assets and "
                         "the signers")
        self.assertIn(f">{handover.EMPTY}<", xml, "the number and the titles left empty become dotted lines")
        self.assertIn("word/styles.xml", names)
        with self.assertRaises(handover.HandoverError):
            handover.fill(values, rows, ROOT / "missing.docx")


class LicenceTests(unittest.TestCase):
    def test_free_licences(self) -> None:
        for expression in ("GPL-2+", "GPL-2+ or Artistic", "MPL-2.0 AND (MIT OR Apache-2.0)", "LGPL-2.1+",
                           "GPL-2 with OpenSSL exception", "Expat", "BSD-3-clause", "GPL-2+-OpenSSL",
                           "GPL-3+-with-Bison-exception"):
            with self.subTest(expression):
                self.assertTrue(licences.is_free(expression))
        for expression in ("unknown", "", "LicenseRef-proprietary", "GPL-2+ and Proprietary", "Freeware",
                           "GPL-2+-proprietary", "Proprietary-OpenSSL"):
            with self.subTest(expression):
                self.assertFalse(licences.is_free(expression))

    def test_the_installed_catalog(self) -> None:
        catalog = ROOT.parent / "caramos-app-center/usr/share/caramos-app-center/catalog.json"
        if not catalog.exists():
            self.skipTest("the App Center submodule is not checked out")
        index = licences.catalog_index(catalog)
        self.assertEqual("freeware", index["google-chrome-stable"]["class"])
        self.assertEqual("free", index["vlc"]["class"])
        self.assertEqual("commercial", index["geogebra"]["class"])

    def test_report_and_register(self) -> None:
        index = {"google-chrome-stable": {"id": "chrome", "name": "Google Chrome", "class": "freeware", "note": {}},
                 "wps-office": {"id": "wps", "name": "WPS Office", "class": "unknown", "note": {}}}
        vlc = {"id": "vlc.desktop", "name": "VLC", "package": "vlc", "licence": "GPL-2+", "origin": "ubuntu-universe"}
        chrome = {"id": "google-chrome.desktop", "name": "Google Chrome", "package": "google-chrome-stable",
                  "licence": "unknown", "origin": "third-party:dl.google.com"}
        wps = {"id": "wps.desktop", "name": "WPS Office", "package": "wps-office", "licence": "unknown",
               "origin": "local-deb"}
        machines = {MACHINE_A: {}, MACHINE_B: {}, "77777777-2222-4333-8444-555555555555": {}}
        inventories = {MACHINE_A: {"apps": [vlc, chrome, wps]}, MACHINE_B: {"apps": [chrome, wps]}}
        register = licences.validate_register([{"id": "wps", "product": "WPS Office", "seats": 1, "expires": "",
                                                "invoice": "", "note": "", "match": ["wps-office"]}])
        report = licences.report(machines, inventories, index, register)
        self.assertEqual(["WPS Office", "Google Chrome", "VLC"], [app["name"] for app in report["apps"]])
        self.assertEqual({"free": 1, "freeware": 1, "commercial": 0, "unknown": 1}, report["totals"])
        self.assertEqual(2, report["register"][0]["used"])
        self.assertEqual("Thiếu 1 bản quyền", reports.register_state(report["register"][0]))
        self.assertEqual(["77777777-2222-4333-8444-555555555555"], report["without_inventory"])
        for bad in ([{"id": "x", "product": "", "seats": 1}], [{"id": "X!", "product": "a", "seats": 1}],
                    [{"id": "x", "product": "a", "seats": -1}], [{"id": "x", "product": "a", "seats": 1,
                                                                   "expires": "15/3/2024"}], {"id": "x"}):
            with self.subTest(bad=bad), self.assertRaises(protocol.ProtocolError):
                licences.validate_register(bad)
        try:
            import openpyxl
        except ImportError:
            self.skipTest("python3-openpyxl is not installed")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ban-quyen.xlsx"
            reports.write_licence_xlsx(report, {MACHINE_A: "kt-01", MACHINE_B: "kt-02"}, path, NOW)
            book = openpyxl.load_workbook(path)
            self.assertEqual(["Tổng hợp", "kt-01", "kt-02"], book.sheetnames)
            summary = [cell for row in book["Tổng hợp"].iter_rows(values_only=True) for cell in row if cell]
            self.assertIn(licences.DISCLAIMER, summary)
            self.assertIn("Người lập", summary)
            self.assertIn("Giám đốc", summary)
            self.assertIn("Thiếu 1 bản quyền", summary)
            self.assertIn("BÁO CÁO PHẦN MỀM", [cell for row in book["kt-02"].iter_rows(values_only=True)
                                               for cell in row if cell])
            book.close()


class SecurityTests(unittest.TestCase):
    def machines(self) -> dict:
        healthy = {"disk_free_pct": 50, "disk_health": "ok", "updates": {"security": 0, "other": 1},
                   "reboot_required": False, "firewall": "on", "screen_lock_on": True, "usb_storage": "block",
                   "encryption": "luks", "frozen": True, "freeze_configured": True,
                   "last_maintenance": "2026-11-22T02:10:00+07:00", "last_snapshot": None}
        open_ = {"disk_free_pct": 50, "disk_health": "ok", "updates": {"security": 4, "other": 1},
                 "reboot_required": True, "firewall": "off", "screen_lock_on": False, "usb_storage": "allow",
                 "encryption": "none", "frozen": False, "freeze_configured": False}
        return {MACHINE_A: {"machine": {"name": "phong-may-01"}, "health": healthy, "last_seen": NOW.isoformat(),
                            "capabilities": list(protocol.CAPABILITIES)},
                MACHINE_B: {"machine": {"name": "ke-toan-01"}, "health": open_, "last_seen": NOW.isoformat(),
                            "capabilities": list(protocol.CAPABILITIES)},
                "77777777-2222-4333-8444-555555555555": {"machine": {"name": "cho-duyet"}, "state": "pending"}}

    def test_rows_and_totals(self) -> None:
        policy = {"settings": {"firewall": {"enabled": True}},
                  "departments": {"phong-may": {"name": "Phòng máy", "settings": {"shared": {
                      "guest": True, "freeze": True, "maintenance": {"days": [7], "time": "02:00", "max_minutes": 60}},
                      "screen_lock": {"idle_minutes": 5, "on_suspend": True}}}},
                  "members": {MACHINE_A: "phong-may"}, "machines": {}}
        records = {MACHINE_B: {"security_since": (NOW - datetime.timedelta(days=9)).isoformat()}}
        table = security.rows(self.machines(), policy, records, NOW)
        self.assertEqual(["ke-toan-01", "phong-may-01"], [row["name"] for row in table], "pending machines left out")
        office, lab = table
        self.assertEqual(("Tắt", "4, từ 14/11/2026", "Có", "Tắt", "Cho dùng", "Không", "Không"),
                         (office["firewall"], office["updates"], office["reboot"], office["screen_lock"], office["usb"],
                          office["encryption"], office["frozen"]))
        self.assertIn("firewall", office["problems"].lower())
        self.assertEqual(("Bật", "Bật, sau 5 phút", "Chặn", "Có (LUKS)", "Đang đóng băng", "Phòng máy"),
                         (lab["firewall"], lab["screen_lock"], lab["usb"], lab["encryption"], lab["frozen"],
                          lab["department"]))
        self.assertEqual("02:10 22/11/2026", lab["last_maintenance"])
        nobody = dict(self.machines()[MACHINE_A], health=dict(self.machines()[MACHINE_A]["health"],
                                                                screen_lock_on=None))
        self.assertEqual("Chưa rõ", security.row(MACHINE_A, nobody, policy, None, NOW)["screen_lock"],
                         "nobody logged in: not known, whatever the policy asks")
        counted = security.totals(table)
        self.assertEqual({"machines": 2, "reported": 2, "firewall_on": 1, "security_waiting": 1, "security_late": 1,
                          "reboot": 1, "screen_lock": 1, "usb_limited": 1, "encrypted": 1, "frozen": 1,
                          "with_problems": 1}, counted)

    def test_labour_rules_and_audit(self) -> None:
        paragraph = security.labour_rules_paragraph({"settings": {"usb": {"storage": "block"}, "browser": None},
                                                     "departments": {"kho": {"name": "Kho", "settings": {
                                                         "screen_lock": {"idle_minutes": 5, "on_suspend": True}}}}})
        self.assertIn("91/2025/QH15", paragraph)
        self.assertIn("ổ USB có thể bị chặn", paragraph)
        self.assertIn("màn hình tự khóa", paragraph)
        self.assertNotIn("trình duyệt", paragraph, "a section turned off is not a measure")
        self.assertIn("không ghi lại phím gõ", paragraph)
        self.assertTrue(paragraph.splitlines()[-3].endswith("."), "the list ends with a full stop")
        lines = [{"time": "2026-11-01T08:00:00+07:00", "action": "role"},
                 {"time": "2026-11-20T08:00:00+07:00", "action": "settings"},
                 {"time": "2026-11-23T08:00:00+07:00", "action": "command"}]
        self.assertEqual(["settings", "command"], [line["action"] for line in security.audit_extract(
            list(reversed(lines)), datetime.date(2026, 11, 15), datetime.date(2026, 11, 23))])

    def test_xlsx(self) -> None:
        try:
            import openpyxl
        except ImportError:
            self.skipTest("python3-openpyxl is not installed")
        table = security.rows(self.machines(), {}, {}, NOW)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "an-toan.xlsx"
            audit = [{"time": "2026-11-20T08:00:00+07:00", "user": "caram", "action": "settings"}]
            reports.write_security_xlsx(table, audit, ["Đã lưu thiết lập."], "Điều …\n1. …", datetime.date(2026, 11, 1),
                                        datetime.date(2026, 11, 23), path, NOW)
            book = openpyxl.load_workbook(path)
            self.assertEqual(["Báo cáo an toàn", "Nhật ký", "Nội quy"], book.sheetnames)
            cells = [cell for row in book["Báo cáo an toàn"].iter_rows(values_only=True) for cell in row if cell]
            self.assertIn(security.DISCLAIMER, cells)
            self.assertIn("Đã lưu thiết lập.", [cell for row in book["Nhật ký"].iter_rows(values_only=True)
                                                for cell in row if cell])
            # Every sheet prints one page wide: the PDF of 0.3.0's "Nội quy" sheet lost its right edge.
            for name in book.sheetnames:
                self.assertTrue(book[name].sheet_properties.pageSetUpPr.fitToPage, name)
                self.assertEqual(1, book[name].page_setup.fitToWidth, name)
            self.assertEqual("portrait", book["Nội quy"].page_setup.orientation)
            book.close()

    def test_tickets_xlsx(self) -> None:
        try:
            import openpyxl
        except ImportError:
            self.skipTest("python3-openpyxl is not installed")
        report = {"counts": {"new": 1, "working": 0, "waiting": 0, "done": 0}, "total": 1,
                  "median_first_response_minutes": None,
                  "tickets": [{"id": "HT-0001", "machine_id": MACHINE_A, "user": "lan", "note": "Máy in",
                               "created": NOW.isoformat(), "status": "new"}]}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "phieu.xlsx"
            reports.write_tickets_xlsx(report, {MACHINE_A: "kt-01"}, 2026, 11, path, NOW)
            book = openpyxl.load_workbook(path)
            cells = [cell for row in book.active.iter_rows(values_only=True) for cell in row if cell]
            book.close()
        self.assertIn("PHIẾU HỖ TRỢ THÁNG 11/2026", cells)
        self.assertIn("Mới", cells)


class PdfTests(unittest.TestCase):
    def test_which_libreoffice(self) -> None:
        with mock.patch.object(reports.shutil, "which", side_effect=lambda name: "/usr/bin/soffice"
                               if name == "soffice" else None):
            self.assertEqual(["/usr/bin/soffice"], reports.soffice())
        done = subprocess.CompletedProcess([], 0)
        with mock.patch.object(reports.shutil, "which", side_effect=lambda name: "/usr/bin/flatpak"
                               if name == "flatpak" else None), \
                mock.patch.object(reports.subprocess, "run", return_value=done):
            self.assertEqual(["/usr/bin/flatpak", "run", "org.libreoffice.LibreOffice"], reports.soffice(),
                             "the app's own command: Flathub's LibreOffice has no soffice on its PATH")
        with mock.patch.object(reports.shutil, "which", return_value=None):
            self.assertIsNone(reports.soffice())
            with self.assertRaises(reports.ReportError):
                reports.to_pdf(Path("x.xlsx"), Path("x.pdf"))
        command = reports.pdf_command(["soffice"], Path("/home/u/.cache/r/report.xlsx"), Path("/home/u/.cache/r"),
                                      Path("/home/u/.cache/r/profile"))
        self.assertEqual(["soffice", "-env:UserInstallation=file:///home/u/.cache/r/profile", "--headless",
                          "--convert-to", "pdf", "--outdir", "/home/u/.cache/r", "/home/u/.cache/r/report.xlsx"],
                         command)


if __name__ == "__main__":
    unittest.main()

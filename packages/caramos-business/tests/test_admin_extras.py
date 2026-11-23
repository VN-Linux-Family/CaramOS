"""The admin's other parts that need no display: the backup format, the asset export, the browser presets, finding
printers and reading the App Center's catalogue."""

from __future__ import annotations

import csv
import datetime
import importlib.util
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from caramos_business import backup, catalog, export, presets, printers, protocol

TZ = datetime.timezone(datetime.timedelta(hours=7))
NOW = datetime.datetime(2026, 11, 21, 15, 30, tzinfo=TZ)
APP_CENTER = Path(__file__).parents[2] / "caramos-app-center" / "usr/share/caramos-app-center"


class BackupTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.etc, self.state = self.root / "etc", self.root / "state"
        self.etc.mkdir()
        (self.state / "files").mkdir(parents=True)
        (self.etc / "admin-key.pem").write_text("key")
        (self.etc / "admin-box.key").write_bytes(b"b" * 32)
        (self.etc / "admin-tls.pem").write_text("cert")  # 0.2's, not part of a 0.3 backup
        (self.etc / "role").write_text("admin\n")
        (self.state / "policy.json").write_text('{"serial": 3}')
        (self.state / "enroll-keys.json").write_text('{"a1b2c3d4e5f60718": "proof key"}')
        (self.state / "files" / ("a" * 64)).write_bytes(b"picture")

    def test_round_trip(self) -> None:
        blob = backup.make_backup("mật khẩu dài", self.etc, self.state)
        self.assertEqual(b"CBKP1", blob[:5])
        self.assertEqual(5 + 16 + 12, len(backup.MAGIC) + backup.SALT_SIZE + backup.NONCE_SIZE)
        other_etc, other_state = self.root / "other-etc", self.root / "other-state"
        written = backup.restore(blob, "mật khẩu dài", other_etc, other_state)
        self.assertIn("etc/caramos-business/admin-key.pem", written)
        self.assertEqual("key", (other_etc / "admin-key.pem").read_text())
        self.assertEqual(0o600, (other_etc / "admin-box.key").stat().st_mode & 0o777)
        self.assertFalse((other_etc / "admin-tls.pem").exists(), "remote help has a key per session since 0.3")
        self.assertEqual(0o600, (other_state / "enroll-keys.json").stat().st_mode & 0o777)
        self.assertEqual(0o644, (other_state / "policy.json").stat().st_mode & 0o777)
        self.assertFalse((other_etc / "role").exists(), "the role comes from the helper, not the backup")
        self.assertEqual(b"picture", (other_state / "files" / ("a" * 64)).read_bytes())

    def test_the_format(self) -> None:
        salt, nonce = bytes(range(16)), bytes(range(12))
        blob = backup.encrypt(b"tar", "passphrase", salt, nonce)
        self.assertEqual(backup.MAGIC + salt + nonce, blob[:33])
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
        key = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(b"passphrase")
        self.assertEqual(b"tar", AESGCM(key).decrypt(nonce, blob[33:], None))

    def test_refusals(self) -> None:
        blob = backup.make_backup("mật khẩu dài", self.etc, self.state)
        for passphrase, data in (("sai mật khẩu", blob), ("mật khẩu dài", b"PK\x03\x04 a zip"),
                                 ("mật khẩu dài", blob[:-1] + bytes([blob[-1] ^ 1]))):
            with self.subTest(data=data[:5]), self.assertRaises(backup.BackupError):
                backup.restore(data, passphrase, self.root / "x", self.root / "y")
        with self.assertRaises(backup.BackupError):
            backup.encrypt(b"tar", "short")
        with self.assertRaises(backup.BackupError):
            backup.make_backup("mật khẩu dài", self.root / "empty", self.state)

    def test_only_its_own_files_come_back(self) -> None:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            for name, data in (("etc/caramos-business/admin-key.pem", b"key"), ("etc/shadow", b"x"),
                               ("var/lib/caramos-business/admin/../../../../etc/passwd", b"x"),
                               ("/etc/caramos-business/admin-box.key", b"x"),
                               ("var/lib/caramos-business/admin/machines.json", b"{}")):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            link = tarfile.TarInfo("var/lib/caramos-business/admin/link")
            link.type, link.linkname = tarfile.SYMTYPE, "/etc/shadow"
            tar.addfile(link)
        written = backup.restore(backup.encrypt(buffer.getvalue(), "mật khẩu dài"), "mật khẩu dài",
                                 self.root / "e", self.root / "s")
        self.assertEqual(["etc/caramos-business/admin-key.pem", "var/lib/caramos-business/admin/machines.json"],
                         written)
        self.assertFalse((self.root / "s" / "link").exists())


class ExportTests(unittest.TestCase):
    def table(self) -> list[dict]:
        machines = {
            "11111111-2222-4333-8444-555555555555": {
                "machine": {"name": "kt-01", "ip": "192.168.1.20"}, "last_seen": NOW.isoformat(),
                "users": [{"user": "minh"}], "health": None},
            "22222222-2222-4333-8444-555555555555": {
                "machine": {"name": "kho-02", "ip": "192.168.1.21"},
                "last_seen": (NOW - datetime.timedelta(days=5)).isoformat(), "users": [], "health": None}}
        assets = {"11111111-2222-4333-8444-555555555555": {
            "asset_code": "TS-001", "purchase_date": "2024-03-15", "price_vnd": 15000000,
            "warranty_until": "2027-03-15", "holder": "Nguyễn Văn Minh", "location": "Tầng 2", "note": "Màn hình rời"}}
        inventories = {"11111111-2222-4333-8444-555555555555": {
            "system": {"vendor": "Dell Inc.", "product": "OptiPlex 3080", "serial": "8XK2Q53"},
            "cpu": {"model": "Intel Core i5-10500", "cores": 6, "threads": 12},
            "memory": {"total_mb": 7834, "modules": []}, "disks": [{"size_gb": 256, "transport": "nvme"}]}}
        policy = {"departments": {"ke-toan": {"name": "Kế toán"}},
                  "members": {"11111111-2222-4333-8444-555555555555": "ke-toan"}}
        return export.rows(machines, assets, inventories, policy, {}, NOW)

    def test_rows(self) -> None:
        first, second = self.table()
        self.assertEqual((1, "TS-001", "Máy tính kt-01 (Dell Inc. OptiPlex 3080)", "8XK2Q53", "Kế toán",
                          "Nguyễn Văn Minh", "Đang dùng"),
                         (first["index"], first["asset_code"], first["name"], first["serial"], first["department"],
                          first["holder"], first["state"]))
        self.assertIn("6 cores", first["config"])
        self.assertEqual((2, "", "Lâu không bật"), (second["index"], second["asset_code"], second["state"]))

    def test_csv(self) -> None:
        data = export.csv_bytes(self.table())
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"), "a BOM, so that Excel reads UTF-8")
        rows = list(csv.reader(io.StringIO(data[3:].decode("utf-8"))))
        self.assertEqual("Mã tài sản", rows[0][1])
        self.assertEqual(["1", "TS-001"], rows[1][:2])
        self.assertIn("15/3/2024", rows[1])
        self.assertIn("15000000", rows[1])

    @unittest.skipUnless(importlib.util.find_spec("openpyxl"), "python3-openpyxl is not installed here")
    def test_xlsx(self) -> None:
        from openpyxl import load_workbook

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "kiem-ke.xlsx"
            export.write_xlsx(self.table(), path, NOW)
            sheet = load_workbook(path).active
        self.assertEqual("BIÊN BẢN KIỂM KÊ MÁY TÍNH", sheet["A4"].value)
        self.assertIn("15 giờ 30, ngày 21 tháng 11 năm 2026", sheet["A5"].value)
        headers = [cell.value for cell in sheet[8]]
        self.assertEqual(["STT", "Mã tài sản", "Tên tài sản"], headers[:3])
        self.assertEqual("TS-001", sheet.cell(row=9, column=2).value)
        self.assertEqual(datetime.datetime(2024, 3, 15), sheet.cell(row=9, column=9).value)
        self.assertEqual(15000000, sheet.cell(row=9, column=10).value)
        self.assertEqual("Tổng cộng", sheet.cell(row=11, column=1).value)
        self.assertEqual(2, sheet.cell(row=11, column=12).value)


class PresetTests(unittest.TestCase):
    def test_lists(self) -> None:
        self.assertEqual(set(presets.ORDER), set(presets.PRESETS))
        for preset, domains in presets.PRESETS.items():
            with self.subTest(preset):
                self.assertTrue(all(protocol.valid_domain(domain) for domain in domains))
                self.assertFalse([domain for domain in domains if "zalo" in domain], "Zalo is for work")
                self.assertEqual(len(set(domains)), len(domains))

    def test_round_trip(self) -> None:
        block = presets.expand(["social", "shopping"], ["baomoi.com", "facebook.com"])
        self.assertEqual(len(set(block)), len(block))
        self.assertEqual((["social", "shopping"], ["baomoi.com"]), presets.chosen(block))
        self.assertEqual(([], ["youtube.com"]), presets.chosen(["youtube.com"]))
        self.assertEqual({"days": [1, 2, 3, 4, 5, 6], "ranges": [["08:00", "12:00"], ["13:30", "17:30"]]},
                         presets.OFFICE_HOURS)

    def test_typed_domains(self) -> None:
        for typed, expected in (("https://www.Facebook.com/groups/abc", "facebook.com"), ("m.youtube.com", "youtube.com"),
                                ("  vnexpress.net ", "vnexpress.net"), ("www.co.uk", "www.co.uk"),
                                ("bóngđá.vn", "xn--bngđ-6qa1a.vn" if False else None), ("localhost", None),
                                ("192.168.1.1", None), ("", None)):
            with self.subTest(typed=typed):
                result = presets.normalize_domain(typed)
                if typed.startswith("bóng"):
                    self.assertTrue(result and result.startswith("xn--") and protocol.valid_domain(result))
                else:
                    self.assertEqual(expected, result)


class PrinterTests(unittest.TestCase):
    def test_avahi(self) -> None:
        output = ('+;enp1s0;IPv4;HP\\032LaserJet;_ipp._tcp;local\n'
                  '=;enp1s0;IPv4;HP\\032LaserJet\\032M404;_ipp._tcp;local;hp.local;192.168.1.50;631;'
                  '"txtvers=1" "rp=ipp/print" "ty=HP LaserJet M404" "note=Tầng 2"\n'
                  '=;enp1s0;IPv6;HP\\032LaserJet\\032M404;_ipp._tcp;local;hp.local;fe80::1;631;"rp=ipp/print"\n'
                  '=;enp1s0;IPv4;Canon;_ipp._tcp;local;canon.local;192.168.1.51;8631;"rp=ipp/printer"\n')
        found = printers.parse_avahi(output)
        self.assertEqual([printers.Found("HP LaserJet M404", "ipp://192.168.1.50/ipp/print", "Tầng 2"),
                          printers.Found("Canon", "ipp://192.168.1.51:8631/ipp/printer", "")], found)

    def test_ippfind(self) -> None:
        output = "ipp://hp.local:631/ipp/print\tHP LaserJet M404\tTầng 2\nnot a uri\n"
        self.assertEqual([printers.Found("HP LaserJet M404", "ipp://hp.local:631/ipp/print", "Tầng 2")],
                         printers.parse_ippfind(output))

    def test_by_address(self) -> None:
        self.assertEqual("ipp://192.168.1.50/ipp/print", printers.uri_for_address(" 192.168.1.50 "))
        self.assertIsNone(printers.uri_for_address("may in@x"))
        self.assertIsNone(printers.uri_for_address(""))


class CatalogTests(unittest.TestCase):
    def test_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "catalog.json"
            path.write_text(json.dumps({"apps": [
                {"id": "vlc", "name": "VLC", "icon": "vlc.png", "summary": {"vi": "Xem phim", "en": "Videos"}},
                {"id": "ms-fonts", "name": "Fonts", "icon_name": "font-x-generic", "summary": {"en": "Fonts"}},
                {"name": "no id"}, "junk"]}), encoding="utf-8")
            apps = catalog.load(path, Path(tmp), "vi")
        self.assertEqual(["vlc", "ms-fonts"], [app.id for app in apps])
        self.assertEqual(("Xem phim", Path(tmp) / "vlc.png"), (apps[0].summary, apps[0].icon_path))
        self.assertEqual(("Fonts", None, "font-x-generic"), (apps[1].summary, apps[1].icon_path, apps[1].icon_name))
        self.assertEqual([], catalog.load(Path(tmp) / "missing.json"))

    @unittest.skipUnless((APP_CENTER / "catalog.json").is_file(), "the App Center submodule is not checked out")
    def test_the_app_centers_catalogue(self) -> None:
        apps = catalog.load(APP_CENTER / "catalog.json", APP_CENTER / "icons", "vi")
        self.assertGreater(len(apps), 10)
        for app in apps:
            with self.subTest(app.id):
                self.assertRegex(app.id, protocol.APP_ID.pattern)


if __name__ == "__main__":
    unittest.main()

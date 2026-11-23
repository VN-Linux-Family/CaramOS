"""Chuyển dữ liệu từ Windows (usr/share/caramos-ota/windows-transfer): finding the Windows data and its accounts,
copying without overwriting, bookmarks, Outlook mail, fonts and the typing method; and the migrations of the Windows
migration kit."""

from __future__ import annotations

import importlib
import json
import os
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "usr/share/caramos-ota/windows-transfer"))

from caramos_ota_update.context import MigrationContext, MigrationContextError  # noqa: E402
from caramos_transfer import app, input_method, sources, transfer  # noqa: E402

LSBLK = json.dumps({"blockdevices": [
    {"name": "sda", "path": "/dev/sda", "fstype": None, "label": None, "size": 256060514304, "mountpoints": [None],
     "hotplug": False, "rm": False, "children": [
         {"name": "sda1", "path": "/dev/sda1", "fstype": "vfat", "label": "SYSTEM", "size": 104857600,
          "mountpoints": [None], "hotplug": False, "rm": False},
         {"name": "sda3", "path": "/dev/sda3", "fstype": "ntfs", "label": "OS", "size": 254000000000,
          "mountpoints": [None], "hotplug": False, "rm": False},
         {"name": "sda4", "path": "/dev/sda4", "fstype": "ntfs", "label": "WINRETOOLS", "size": 990904320,
          "mountpoints": [None], "hotplug": False, "rm": False}]},
    {"name": "sdb", "path": "/dev/sdb", "fstype": None, "label": None, "size": 500107862016, "mountpoints": [None],
     "hotplug": True, "rm": False, "children": [
         {"name": "sdb1", "path": "/dev/sdb1", "fstype": "ntfs", "label": "Data", "size": 500105764864,
          "mountpoints": ["/media/lan/Data"], "hotplug": True, "rm": False}]},
]})

CHROME_BOOKMARKS = {"roots": {
    "bookmark_bar": {"type": "folder", "name": "Bookmarks bar", "date_added": "13300000000000000", "children": [
        {"type": "url", "name": "Thuế điện tử", "url": "https://thuedientu.gdt.gov.vn/",
         "date_added": "13300000000000000"},
        {"type": "folder", "name": "Ngân hàng & <Công ty>", "children": [
            {"type": "url", "name": "VCB", "url": "https://vcbdigibank.vietcombank.com.vn/?a=1&b=2"}]}]},
    "other": {"type": "folder", "name": "Other", "children": [
        {"type": "url", "name": "", "url": "https://zalo.me/"}]},
    "synced": {"type": "folder", "name": "Mobile", "children": []}}}


def write(path: Path, data: bytes | str = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path


def make_font(path: Path, copyright_text: str) -> Path:
    """A minimal font file: an offset table with one 'name' table holding a Windows copyright string."""

    text = copyright_text.encode("utf-16-be")
    name = struct.pack(">HHH", 0, 1, 6 + 12) + struct.pack(">HHHHHH", 3, 1, 0x409, 0, len(text), 0) + text
    header = struct.pack(">IHHHH", 0x00010000, 1, 16, 0, 0)
    record = struct.pack(">4sIII", b"name", 0, 12 + 16, len(name))
    return write(path, header + record + name)


def windows_disk(root: Path) -> Path:
    """C:\\ of an office computer: two accounts, the usual folders, Zalo, two browsers, Outlook and fonts."""

    lan = root / "Users/Lan"
    write(lan / "NTUSER.DAT")
    write(lan / "Desktop/Báo cáo tháng 10.docx", b"a" * 1000)
    write(lan / "Desktop/desktop.ini", "[.ShellClassInfo]")
    write(lan / "Desktop/MISA SME.lnk", b"L")
    write(lan / "Documents/Hợp đồng/HĐ-01.xlsx", b"b" * 2000)
    write(lan / "Documents/~$HĐ-01.xlsx", b"lock")
    write(lan / "Documents/Zalo Received Files/ảnh.jpg", b"c" * 300)
    write(lan / "Documents/Outlook Files/lan@congty.vn.pst", b"!BDN" + b"\0" * 60)
    os.symlink(lan / "Music", lan / "Documents/My Music")               # Windows' junction, as Linux shows it
    write(lan / "Pictures/Tết/1.png", b"d" * 400)
    write(lan / "Music/bài hát.mp3", b"e" * 500)
    (lan / "Downloads").mkdir()
    (lan / "Videos").mkdir()
    write(lan / "AppData/Local/Google/Chrome/User Data/Default/Bookmarks", json.dumps(CHROME_BOOKMARKS))
    write(lan / "AppData/Local/CocCoc/Browser/User Data/Profile 1/Bookmarks", json.dumps(CHROME_BOOKMARKS))
    make_font(lan / "AppData/Local/Microsoft/Windows/Fonts/UTM Avo.ttf", "Copyright UTM")
    make_font(lan / "AppData/Local/Microsoft/Windows/Fonts/SomeFont.ttf", "(c) 2006 Microsoft Corporation")
    make_font(lan / "AppData/Local/Microsoft/Windows/Fonts/calibri.ttf", "anything")
    write(root / "Users/Minh/Desktop/x.txt")
    write(root / "Users/Minh/NTUSER.DAT")
    for name in ("Public/Desktop/p.txt", "Default/NTUSER.DAT", "All Users/x"):
        write(root / "Users" / name)
    return lan


class SourceTests(unittest.TestCase):
    def test_windows_partitions(self) -> None:
        found = sources.parse_lsblk(LSBLK)
        self.assertEqual(["/dev/sda3", "/dev/sdb1"], [partition.device for partition in found])  # not the 1 GB one
        self.assertEqual("/media/lan/Data", found[1].mountpoint)
        self.assertTrue(found[1].removable)
        self.assertFalse(found[0].removable)
        self.assertEqual([], sources.parse_lsblk("not json"))

    def test_mount_read_only(self) -> None:
        partition = sources.parse_lsblk(LSBLK)[0]
        calls = []

        def udisksctl(args, **_kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "Mounted /dev/sda3 at /media/lan/OS\n", "")

        with mock.patch.object(sources.subprocess, "run", side_effect=udisksctl):
            self.assertEqual((Path("/media/lan/OS"), True), sources.mount_read_only(partition))
        self.assertEqual(["udisksctl", "mount", "--block-device", "/dev/sda3", "--options", "ro"], calls[0])
        mounted = sources.parse_lsblk(LSBLK)[1]
        with mock.patch.object(sources.subprocess, "run") as run:
            self.assertEqual((Path("/media/lan/Data"), False), sources.mount_read_only(mounted))
            run.assert_not_called()

    def test_mount_errors_say_what_to_do(self) -> None:
        partition = sources.parse_lsblk(LSBLK)[0]
        failure = subprocess.CompletedProcess([], 1, "", "Error mounting /dev/sda3: wrong fs type: The disk contains "
                                                         "an unclean file system (0, 0). Metadata kept in Windows "
                                                         "cache, refused to mount.")
        with mock.patch.object(sources.subprocess, "run", return_value=failure):
            with self.assertRaises(sources.MountError) as raised:
                sources.mount_read_only(partition)
        self.assertIn("Shift", str(raised.exception))

    def test_smb_addresses(self) -> None:
        for text in ("\\\\MAY-CU\\Users", "MAY-CU\\Users", "smb://may-cu/Users", "//MAY-CU/Users/", "may-cu/Users"):
            self.assertIn(sources.smb_uri(text), ("smb://MAY-CU/Users", "smb://may-cu/Users"), text)
        self.assertEqual("smb://192.168.1.5/C$/Users", sources.smb_uri("\\\\192.168.1.5\\C$\\Users"))
        for text in ("", "MAY-CU", "\\\\", "a b/c"):
            self.assertIsNone(sources.smb_uri(text), text)

    def test_accounts_of_a_drive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            windows_disk(root)
            profiles = sources.find_profiles(root)
            self.assertEqual(["Lan", "Minh"], [profile.name for profile in profiles])
            self.assertEqual(profiles, [p for p in sources.find_profiles(root / "Users")])
            self.assertEqual(["Lan"], [profile.name for profile in sources.find_profiles(root / "Users/Lan")])
            lan = profiles[0]
            self.assertEqual(set(sources.FOLDER_ITEMS), set(lan.folders))
            self.assertIsInstance(lan.last_used, datetime)
            items = sources.items_of(lan)
            self.assertEqual({*sources.FOLDER_ITEMS, sources.ZALO, sources.BOOKMARKS, sources.OUTLOOK, sources.FONTS},
                             set(items))
            self.assertEqual(["Google Chrome", "Cốc Cốc"], [b for b, _p, _f in sources.bookmark_files(lan)])
            self.assertEqual(3, len(items[sources.FONTS].sources))

    def test_windows_xp(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root / "Documents and Settings/Hoa/NTUSER.DAT")
            write(root / "Documents and Settings/Hoa/My Documents/My Pictures/a.jpg")
            write(root / "Documents and Settings/Hoa/Desktop/b.doc")
            [profile] = sources.find_profiles(root)
            self.assertEqual(root / "Documents and Settings/Hoa/My Documents", profile.folders["Documents"])
            self.assertEqual(root / "Documents and Settings/Hoa/My Documents/My Pictures", profile.folders["Pictures"])

    def test_sizes_skip_links_and_clutter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lan = windows_disk(Path(tmp))
            size = sources.measure(lan / "Documents", skip=transfer.skipped)
            # HĐ-01.xlsx, ảnh.jpg, the .pst: not the lock file, not My Music (a link to Music).
            self.assertEqual((3, 2000 + 300 + 64), (size.files, size.bytes))


class CopyTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = self.root / "home"
        self.folders = {"Desktop": "Màn hình nền", "Documents": "Tài liệu", "Pictures": "Ảnh", "Downloads": "Tải về",
                        "Music": "Nhạc", "Videos": "Video"}
        patcher = mock.patch.object(transfer, "user_dir", lambda key, home=None: self.home / self.folders[key])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_names(self) -> None:
        write(self.root / "a.docx")
        self.assertEqual(self.root / "a (2).docx", transfer.free_name(self.root / "a.docx"))
        write(self.root / "a (2).docx")
        self.assertEqual(self.root / "a (3).docx", transfer.free_name(self.root / "a.docx"))
        self.assertEqual(self.root / "b.docx", transfer.free_name(self.root / "b.docx"))
        self.assertEqual((".bashrc", ""), transfer.split_name(".bashrc"))
        self.assertEqual(("archive.tar", ".gz"), transfer.split_name("archive.tar.gz"))
        for name in ("desktop.ini", "Thumbs.db", "MISA.lnk", "~$HĐ.xlsx"):
            self.assertTrue(transfer.skipped(Path(name)), name)
        self.assertFalse(transfer.skipped(Path("báo cáo.docx")))

    def test_merge_without_overwriting(self) -> None:
        source = self.root / "win"
        write(source / "Hợp đồng/HĐ-01.xlsx", b"new")
        write(source / "Ghi chú.txt", b"from windows")
        write(source / "Thumbs.db")
        write(source / "Kế toán", b"a file where a folder exists here")
        target = self.root / "Tài liệu"
        write(target / "Hợp đồng/HĐ-01.xlsx", b"mine")
        write(target / "Ghi chú.txt", b"mine too")
        (target / "Kế toán").mkdir()
        report = transfer.Report("Documents")
        transfer.Copier(100, lambda *a: None).copy_tree(source, target, report)
        self.assertEqual(b"mine", (target / "Hợp đồng/HĐ-01.xlsx").read_bytes())
        self.assertEqual(b"new", (target / "Hợp đồng/HĐ-01 (2).xlsx").read_bytes())
        self.assertEqual(b"from windows", (target / "Ghi chú (2).txt").read_bytes())
        self.assertFalse((target / "Thumbs.db").exists())
        self.assertTrue((target / "Kế toán").is_dir())
        self.assertEqual(b"a file where a folder exists here", (target / "Kế toán (2)").read_bytes())
        self.assertEqual(3, report.files)

    def test_stop_removes_the_unfinished_file(self) -> None:
        source = write(self.root / "big.bin", b"z" * (3 * transfer.CHUNK))
        copier = transfer.Copier(source.stat().st_size, lambda done, *_a: done > transfer.CHUNK and copier.stop.set())
        with self.assertRaises(transfer.Cancelled):
            copier.copy_file(source, self.root / "out", "Documents")
        self.assertEqual([], list((self.root / "out").iterdir()))

    def test_bookmarks_page(self) -> None:
        page, count = transfer.bookmark_page([("Google Chrome", "Default", CHROME_BOOKMARKS),
                                              ("Cốc Cốc", "Profile 1", CHROME_BOOKMARKS)], "Dấu trang")
        self.assertEqual(6, count)
        self.assertTrue(page.startswith("<!DOCTYPE NETSCAPE-Bookmark-file-1>"))
        self.assertIn('<A HREF="https://vcbdigibank.vietcombank.com.vn/?a=1&amp;b=2"', page)
        self.assertIn("Ngân hàng &amp; &lt;Công ty&gt;", page)
        self.assertIn("<H3>Cốc Cốc (Profile 1)</H3>", page)
        self.assertIn(">https://zalo.me/</A>", page, "a bookmark without a name shows its address")
        self.assertIn('ADD_DATE="1655526400"', page)     # Chrome's 13300000000000000 µs since 1601
        self.assertEqual(page.count("<DL><p>"), page.count("</DL><p>"))

    def test_fonts(self) -> None:
        own = make_font(self.root / "UTM Avo.ttf", "Copyright UTM")
        microsoft = make_font(self.root / "SomeFont.ttf", "(c) 2006 Microsoft Corporation. All Rights Reserved.")
        self.assertEqual(["Copyright UTM"], transfer.font_names(own))
        self.assertFalse(transfer.microsoft_font(own))
        self.assertTrue(transfer.microsoft_font(microsoft))
        self.assertTrue(transfer.microsoft_font(make_font(self.root / "CALIBRIB.TTF", "")))
        self.assertEqual([], transfer.font_names(write(self.root / "broken.ttf", b"\0\1")))

    def test_the_whole_plan(self) -> None:
        lan = windows_disk(self.root / "C")
        profile = sources.find_profiles(self.root / "C")[0]
        items = sources.items_of(profile)
        for key, item in items.items():
            item.size = sources.measure(item.sources[0], skip=transfer.skipped) if key in (
                *sources.FOLDER_ITEMS, sources.ZALO) else sources.Size(len(item.sources), sum(
                    path.stat().st_size for path in item.sources))
        plan = transfer.Plan(profile, items, list(items))
        self.assertNotIn(sources.ZALO, plan.effective(), "Zalo's folder comes with Documents")
        seen = []
        copier = transfer.Copier(plan.total_bytes(), lambda done, total, item, name: seen.append((done, total)))
        with mock.patch.object(transfer, "readpst", return_value="/usr/bin/readpst"), \
                mock.patch.object(transfer, "convert_pst", return_value=(True, "")) as convert, \
                mock.patch.object(transfer.subprocess, "run") as fc_cache:
            reports = {report.key: report for report in transfer.run_plan(plan, copier, self.home)}
        documents = self.home / "Tài liệu"
        self.assertTrue((self.home / "Màn hình nền/Báo cáo tháng 10.docx").exists())
        self.assertFalse((self.home / "Màn hình nền/MISA SME.lnk").exists())
        self.assertFalse((self.home / "Màn hình nền/desktop.ini").exists())
        self.assertTrue((documents / "Hợp đồng/HĐ-01.xlsx").exists())
        self.assertTrue((documents / "Zalo Received Files/ảnh.jpg").exists())
        self.assertFalse((documents / "My Music").exists(), "links are not followed")
        self.assertTrue((self.home / "Ảnh/Tết/1.png").exists())
        self.assertTrue((self.home / "Nhạc/bài hát.mp3").exists())
        page = (documents / "Bookmarks from Windows.html").read_text(encoding="utf-8")
        self.assertIn("Thuế điện tử", page)
        self.assertEqual(6, reports[sources.BOOKMARKS].extra)
        convert.assert_called_once()
        self.assertEqual(documents / "Outlook mail" / "lan@congty.vn", convert.call_args.args[1])
        fonts = self.home / ".local/share/fonts"
        self.assertEqual(["UTM Avo.ttf"], sorted(path.name for path in fonts.iterdir()))
        self.assertEqual(2, reports[sources.FONTS].extra, "SomeFont (Microsoft) and calibri are left out")
        fc_cache.assert_called_once()
        self.assertEqual(seen[-1][0], seen[-1][1], "the progress reaches the end")
        self.assertTrue((lan / "Desktop/Báo cáo tháng 10.docx").exists(), "the source is untouched")

    def test_outlook_without_readpst_copies_the_files(self) -> None:
        windows_disk(self.root / "C")
        profile = sources.find_profiles(self.root / "C")[0]
        items = sources.items_of(profile)
        items[sources.OUTLOOK].size = sources.Size(1, 64)
        plan = transfer.Plan(profile, items, [sources.OUTLOOK])
        with mock.patch.object(transfer, "readpst", return_value=None):
            [report] = transfer.run_plan(plan, transfer.Copier(64, lambda *a: None), self.home)
        self.assertEqual("copied", report.note)
        self.assertTrue((self.home / "Tài liệu/Outlook mail/lan@congty.vn.pst").exists())

    def test_readpst_command(self) -> None:
        calls = []

        def fake(args, **_kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, "", "")

        with mock.patch.object(transfer, "readpst", return_value="/usr/bin/readpst"):
            ok, _detail = transfer.convert_pst(Path("/x/a.pst"), self.root / "mail", runner=fake)
        self.assertTrue(ok)
        self.assertEqual(["/usr/bin/readpst", "-8", "-q", "-o", str(self.root / "mail"), "/x/a.pst"], calls[0])


class InputMethodTests(unittest.TestCase):
    def test_conf(self) -> None:
        skel = '# CaramOS defaults for Lotus.\nInputMethod="Telex"\nMode="Preedit"\n'
        self.assertEqual('# CaramOS defaults for Lotus.\nInputMethod="VNI"\nMode="Preedit"\n',
                         input_method.with_method(skel, "VNI"))
        self.assertEqual('Mode="Preedit"\nInputMethod="VNI"\n', input_method.with_method('Mode="Preedit"\n', "VNI"))
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            skel_file = write(home / "skel.conf", skel)
            input_method.write_conf("VNI", home, skel_file)
            self.assertEqual("VNI", input_method.current(home))
            self.assertIn('Mode="Preedit"', (home / input_method.CONF).read_text(encoding="utf-8"))

    def test_without_fcitx_the_file_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            write(home / input_method.CONF, 'InputMethod="Telex"\n')
            # No session bus, with or without PyGObject (Launchpad's builders have none).
            gio = SimpleNamespace(bus_get_sync=mock.Mock(side_effect=RuntimeError("no bus")),
                                  BusType=SimpleNamespace(SESSION=0))
            repository = SimpleNamespace(Gio=gio, GLib=SimpleNamespace())
            fake_gi = SimpleNamespace(require_version=lambda *_args: None, repository=repository)
            with mock.patch.dict(sys.modules, {"gi": fake_gi, "gi.repository": repository}):
                self.assertEqual("file", input_method.set_method("VNI", home))
            self.assertEqual("VNI", input_method.current(home))
        with self.assertRaises(ValueError):
            input_method.set_method("VIQR")


class TextTests(unittest.TestCase):
    def test_sizes_and_counts(self) -> None:
        with mock.patch.object(app, "prefers_vietnamese", return_value=True):
            self.assertEqual("2,3 GB", app.human_size(int(2.3 * 1024 ** 3)))
            self.assertEqual("512 KB", app.human_size(512 * 1024))
        with mock.patch.object(app, "prefers_vietnamese", return_value=False):
            self.assertEqual("2.3 GB", app.human_size(int(2.3 * 1024 ** 3)))
            self.assertIn("1,234", app.count_text(1234))


class PackagingTests(unittest.TestCase):
    def test_package_ships_it(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        for line in ("usr/bin/caramos-windows-transfer usr/bin/", "usr/share/caramos-ota/windows-transfer "
                     "usr/share/caramos-ota/", "usr/share/applications/caramos-windows-transfer.desktop "
                     "usr/share/applications/"):
            self.assertIn(line, install)
        self.assertTrue(os.access(ROOT / "usr/bin/caramos-windows-transfer", os.X_OK))
        entry = (ROOT / "usr/share/applications/caramos-windows-transfer.desktop").read_text(encoding="utf-8")
        self.assertIn("Name[vi]=Chuyển dữ liệu từ Windows", entry)
        self.assertIn("Exec=caramos-windows-transfer", entry)


class MigrationTests(unittest.TestCase):
    def run_install(self, module, installed: bool, apt_fails: bool = False) -> tuple[list, list]:
        context = MigrationContext()
        commands, logged = [], []

        def run_command(args, allow_fail=False, env=None):  # noqa: ANN001, ANN202
            commands.append(list(args))
            return subprocess.CompletedProcess(args, 0 if installed else 1, "ii " if installed else "", "")

        apt = mock.Mock(side_effect=MigrationContextError("offline") if apt_fails else None)
        with mock.patch.object(context, "run_command", side_effect=run_command), \
                mock.patch.object(context, "apt_install", apt), mock.patch.object(context, "log",
                                                                                  side_effect=logged.append):
            module.run(context)
        return [call.args[0] for call in apt.call_args_list], logged

    def test_carlito_and_readpst(self) -> None:
        for name, package in (("20261122100000_carlito_font", "fonts-crosextra-carlito"),
                              ("20261122100200_windows_migration_tools", "pst-utils")):
            module = importlib.import_module(f"caramos_ota_update.migrations.{name}.migration")
            self.assertEqual([[package]], self.run_install(module, installed=False)[0], name)
            self.assertEqual([], self.run_install(module, installed=True)[0], name)
            _apt, logged = self.run_install(module, installed=False, apt_fails=True)
            self.assertTrue(any("could not install" in line for line in logged), name)
            manifest = json.loads((Path(module.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
            self.assertNotIn("desktops", manifest, "both editions")
            self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))

    @unittest.skipUnless((ROOT.parents[1] / "config").is_dir(), "the source package has no config/")
    def test_new_installs_get_them(self) -> None:
        packages = (ROOT.parents[1] / "config/packages.txt").read_text(encoding="utf-8").split()
        self.assertIn("fonts-crosextra-carlito", packages)
        self.assertIn("pst-utils", packages)

    def test_dry_run_installs_nothing(self) -> None:
        module = importlib.import_module("caramos_ota_update.migrations.20261122100000_carlito_font.migration")
        context = MigrationContext(dry_run=True)
        with mock.patch.object(transfer.subprocess, "run") as run, mock.patch("builtins.print"), \
                mock.patch("caramos_ota_update.context.log_info"):
            module.run(context)
        run.assert_not_called()


class TranslationTests(unittest.TestCase):
    def test_every_message_is_in_the_vietnamese_catalog(self) -> None:
        sys.path.insert(0, str(Path(__file__).parent))
        from test_ota_i18n import PO, msgids, source_msgids

        translated = msgids(PO)
        for path in sorted((ROOT / "usr/share/caramos-ota/windows-transfer/caramos_transfer").glob("*.py")):
            missing = sorted(source_msgids(path) - translated)
            self.assertEqual([], missing, f"{path.name}: add these to po/caramos-ota/vi.po (see po/README.md)")


if __name__ == "__main__":
    unittest.main()

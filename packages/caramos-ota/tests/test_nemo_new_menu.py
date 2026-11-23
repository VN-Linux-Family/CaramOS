"""Files (Nemo): right-click > "Mới" > "Thư mục", like Windows and the Tin học textbooks.

caramos-nemo-menu reads Nemo's menu XML from libnemo-extension and writes changed copies, which
/etc/X11/Xsession.d/85caramos-nemo-menu hands to Nemo through G_RESOURCE_OVERLAYS; po/nemo relabels the moved
items; caramos-templates puts the Word, Excel and PowerPoint templates into the user's Templates folder once."""

from __future__ import annotations

import configparser
import importlib
import importlib.machinery
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.dom.minidom
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
MENU_SCRIPT = ROOT / "usr/share/caramos-ota/nemo-menu/caramos-nemo-menu"
TEMPLATES_SCRIPT = ROOT / "usr/share/caramos-ota/nemo-menu/caramos-templates"
TEMPLATES = ROOT / "usr/share/caramos-ota/templates"
ND30_NAMES = ["Báo cáo.docx", "Biên bản bàn giao tài sản.docx", "Biên bản.docx", "Công văn.docx", "Giấy mời.docx",
              "Quyết định.docx", "Thông báo.docx", "Tờ trình.docx"]
ND30_FOLDERS = {"vi": "Văn bản hành chính", "en": "Vietnamese Official Documents"}
ND30_STATE = Path(".local/state/caramos/templates-nd30.json")
GENERATOR = ROOT / "tools/make-nd30-templates.py"
TEMPLATES_MIGRATION = (ROOT / "usr/lib/python3/dist-packages/caramos_ota_update/migrations/"
                       "20261122100100_administrative_templates")
XSESSION = ROOT / "etc/X11/Xsession.d/85caramos-nemo-menu"
FIXTURES = ROOT / "tests/data/nemo-6.6.3"
MIGRATION = ROOT / "usr/lib/python3/dist-packages/caramos_ota_update/migrations/20261118090000_files_new_menu"


def load(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


menu = load(MENU_SCRIPT, "caramos_nemo_menu_test")
templates = load(TEMPLATES_SCRIPT, "caramos_templates_test")
VIEW_XML = (FIXTURES / "nemo-directory-view-ui.xml").read_text(encoding="utf-8")
TREE_XML = (FIXTURES / "nemo-tree-sidebar-ui.xml").read_text(encoding="utf-8")


def popup(dom: xml.dom.minidom.Document, name: str):
    return next(node for node in dom.getElementsByTagName("popup") if node.getAttribute("name") == name)


def elements(node):
    return [child for child in node.childNodes if child.nodeType == child.ELEMENT_NODE]


def gi_available() -> bool:
    try:
        import gi  # noqa: F401
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio  # noqa: F401
    except (ImportError, ValueError):
        return False
    return True


class ViewMenuTests(unittest.TestCase):
    def test_new_folder_is_the_first_item_of_new(self) -> None:
        changed = menu.view_menus(VIEW_XML)
        dom = xml.dom.minidom.parseString(changed)          # still well-formed
        for parent in (popup(dom, "background"), dom.getElementsByTagName("menubar")[0]):
            new_menu = next(node for node in parent.getElementsByTagName("menu")
                            if node.getAttribute("action") == "New Documents")
            first, second = elements(new_menu)[:2]
            self.assertEqual(("menuitem", "New Folder"), (first.tagName, first.getAttribute("action")))
            self.assertEqual("separator", second.tagName)
            # Nowhere else: the old place right before the submenu is empty now.
            outside = [node for node in elements(new_menu.parentNode) if node.getAttribute("action") == "New Folder"]
            self.assertEqual([], outside)
        self.assertEqual(2, changed.count(menu.VIEW_NEW_FOLDER))

    def test_templates_and_empty_document_stay_in_new(self) -> None:
        changed = menu.view_menus(VIEW_XML)
        background = popup(xml.dom.minidom.parseString(changed), "background")
        new_menu = next(node for node in background.getElementsByTagName("menu")
                        if node.getAttribute("action") == "New Documents")
        names = [node.getAttribute("name") for node in elements(new_menu)]
        self.assertEqual(["New Folder", "After New Folder", "No Templates", "New Documents Placeholder",
                          "After New Documents", "New Empty Document"], names)

    def test_refuses_unknown_or_changed_xml(self) -> None:
        with self.assertRaises(menu.MenuError):
            menu.view_menus(menu.view_menus(VIEW_XML))
        with self.assertRaises(menu.MenuError):
            menu.view_menus(VIEW_XML.replace(menu.VIEW_NEW_FOLDER, "", 1))
        with self.assertRaises(menu.MenuError):
            menu.view_menus("<ui/>")


class TreeMenuTests(unittest.TestCase):
    def test_the_folder_tree_menu_drops_its_lone_new_folder(self) -> None:
        changed = menu.tree_menu(TREE_XML)
        actions = [node.getAttribute("action") for node in xml.dom.minidom.parseString(changed)
                   .getElementsByTagName("menuitem")]
        self.assertNotIn("New Folder", actions)
        self.assertIn("Paste", actions)
        with self.assertRaises(menu.MenuError):
            menu.tree_menu(changed)


class UpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.out = self.root / "nemo-menu"

    def test_a_library_without_the_menus_leaves_nemo_alone(self) -> None:
        self.out.mkdir()
        (self.out / "nemo-directory-view-ui.xml").write_text("old", encoding="utf-8")
        library = self.root / "libnemo-extension.so.1"
        library.write_bytes(b"\x7fELF" + bytes(64))
        with mock.patch("builtins.print"):
            self.assertFalse(menu.update(library, self.out))
            self.assertFalse(menu.update(None, self.out))
        self.assertEqual([], list(self.out.iterdir()), "no half-changed menus")

    @unittest.skipUnless(gi_available() and shutil.which("glib-compile-resources"), "needs gi and glib-compile-resources")
    def test_reads_the_menus_compiled_into_the_library(self) -> None:
        bundle_xml = self.root / "nemo.gresource.xml"
        bundle_xml.write_text('<?xml version="1.0" encoding="UTF-8"?><gresources><gresource prefix="/org/nemo">'
                              "<file>nemo-directory-view-ui.xml</file><file>nemo-tree-sidebar-ui.xml</file>"
                              "</gresource></gresources>", encoding="utf-8")
        bundle = self.root / "nemo.gresource"
        subprocess.run(["glib-compile-resources", f"--sourcedir={FIXTURES}", f"--target={bundle}", str(bundle_xml)],
                       check=True)
        library = self.root / "libnemo-extension.so.1"
        # Like the real library: code and other strings, then the bundle (aligned, as the compiler emits it).
        library.write_bytes(b"\x7fELF" + b"GVariant\x00nemo" + bytes(1000) + bundle.read_bytes() + bytes(64))
        with mock.patch("builtins.print"):
            self.assertTrue(menu.update(library, self.out))
        self.assertEqual(menu.view_menus(VIEW_XML), (self.out / "nemo-directory-view-ui.xml").read_text(encoding="utf-8"))
        self.assertEqual(menu.tree_menu(TREE_XML), (self.out / "nemo-tree-sidebar-ui.xml").read_text(encoding="utf-8"))
        self.assertEqual(0o644, (self.out / "nemo-tree-sidebar-ui.xml").stat().st_mode & 0o777)
        menu.remove(self.out)
        self.assertEqual([], list(self.out.iterdir()))


class XsessionTests(unittest.TestCase):
    def overlays(self, files: bool, **environ: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "nemo-menu"
            directory.mkdir()
            if files:
                for name in ("nemo-directory-view-ui.xml", "nemo-tree-sidebar-ui.xml"):
                    (directory / name).write_text("<ui/>", encoding="utf-8")
            snippet = Path(tmp) / "snippet"
            snippet.write_text(XSESSION.read_text(encoding="utf-8").replace("/var/lib/caramos-ota/nemo-menu",
                                                                            str(directory)), encoding="utf-8")
            env = {"PATH": "/usr/bin:/bin", **environ}
            result = subprocess.run(["sh", "-ec", f'. "{snippet}"; printf %s "${{G_RESOURCE_OVERLAYS-}}|${{CARAMOS_NEMO_MENU-unset}}"'],
                                    env=env, capture_output=True, text=True, check=True)
            return result.stdout.replace(str(directory), "DIR")

    def test_vietnamese_and_us_english_sessions_get_the_menus(self) -> None:
        expected = ("/org/nemo/nemo-directory-view-ui.xml=DIR/nemo-directory-view-ui.xml:"
                    "/org/nemo/nemo-tree-sidebar-ui.xml=DIR/nemo-tree-sidebar-ui.xml|unset")
        self.assertEqual(expected, self.overlays(True, LANG="vi_VN", LANGUAGE="vi_VN:vi"))
        self.assertEqual(expected, self.overlays(True, LANG="vi_VN.UTF-8"))
        self.assertEqual(expected, self.overlays(True, LANG="en_US.UTF-8"))

    def test_other_languages_and_missing_menus_keep_nemo_alone(self) -> None:
        self.assertEqual("|unset", self.overlays(True, LANG="fr_FR.UTF-8"))
        self.assertEqual("|unset", self.overlays(True, LANG="en_GB.UTF-8", LANGUAGE="en_GB:en"))
        self.assertEqual("|unset", self.overlays(False, LANG="vi_VN", LANGUAGE="vi_VN:vi"))

    def test_other_overlays_are_kept(self) -> None:
        self.assertTrue(self.overlays(True, LANG="vi_VN", G_RESOURCE_OVERLAYS="/org/x=/tmp/x")
                        .endswith(":/org/x=/tmp/x|unset"))


class CatalogTests(unittest.TestCase):
    def messages(self, name: str) -> dict[str, str]:
        text = (ROOT / "po/nemo" / name).read_text(encoding="utf-8")
        self.assertNotIn("#, fuzzy", text)
        found, msgid = {}, None
        for line in text.splitlines():
            if line.startswith("msgid "):
                msgid = line[7:-1]
            elif line.startswith("msgstr ") and msgid:
                found[msgid] = line[8:-1]
        return found

    def test_vietnamese_words_follow_windows(self) -> None:
        self.assertEqual({"Create New _Document": "_Mới", "Create New _Folder": "_Thư mục", "_Paste": "_Dán"},
                         self.messages("vi_VN.po"))

    def test_english_words(self) -> None:
        self.assertEqual({"Create New _Document": "_New", "Create New _Folder": "_Folder"}, self.messages("en.po"))


class TemplateFileTests(unittest.TestCase):
    NAMES = {
        "vi": ["Bảng tính Excel.xlsx", "Trình chiếu PowerPoint.pptx", "Tệp văn bản.txt", "Văn bản Word.docx"],
        "en": ["Excel Spreadsheet.xlsx", "PowerPoint Presentation.pptx", "Text Document.txt", "Word Document.docx"],
    }
    MAIN_PART = {".docx": "word/document.xml", ".xlsx": "xl/workbook.xml", ".pptx": "ppt/presentation.xml"}

    def test_each_language_has_the_four_documents(self) -> None:
        for lang, names in self.NAMES.items():
            self.assertEqual(sorted(names), sorted(path.name for path in (TEMPLATES / lang).iterdir()), lang)
            for path in (TEMPLATES / lang).iterdir():
                if path.suffix == ".txt":
                    self.assertEqual(0, path.stat().st_size)
                    continue
                with zipfile.ZipFile(path) as document:
                    self.assertIsNone(document.testzip())
                    self.assertIn("[Content_Types].xml", document.namelist())
                    self.assertIn(self.MAIN_PART[path.suffix], document.namelist())
                    core = document.read("docProps/core.xml").decode("utf-8")
                    self.assertIn("<dc:creator></dc:creator>", core, "no author name in the templates")

    def test_page_sizes(self) -> None:
        with zipfile.ZipFile(TEMPLATES / "vi/Trình chiếu PowerPoint.pptx") as deck:
            self.assertIn('<p:sldSz cx="10080625" cy="5670550"/>', deck.read("ppt/presentation.xml").decode())  # 16:9
        with zipfile.ZipFile(TEMPLATES / "vi/Văn bản Word.docx") as document:
            self.assertIn('<w:pgSz w:w="11906" w:h="16838"/>', document.read("word/document.xml").decode())   # A4
            self.assertIn('w:val="vi-VN"', document.read("word/styles.xml").decode())


class SeedTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.home.mkdir()
        self.folder = self.home / "Mẫu"
        self.answer = str(self.folder)

    def run_seed(self, **environ: str) -> int:
        def xdg_user_dir(args, **_kwargs):
            return subprocess.CompletedProcess(args, 0, self.answer + "\n", "")

        with mock.patch.object(templates.subprocess, "run", xdg_user_dir), mock.patch("builtins.print"):
            return templates.run(self.home, environ, TEMPLATES)

    def test_puts_the_vietnamese_templates_once(self) -> None:
        self.assertEqual(0, self.run_seed(LANGUAGE="vi_VN:vi", LANG="vi_VN"))
        self.assertEqual(sorted(TemplateFileTests.NAMES["vi"] + [ND30_FOLDERS["vi"]]),
                         sorted(path.name for path in self.folder.iterdir()))
        self.assertEqual(sorted(ND30_NAMES), sorted(path.name for path in (self.folder / ND30_FOLDERS["vi"]).iterdir()))
        state = json.loads((self.home / templates.STATE).read_text(encoding="utf-8"))
        self.assertEqual("vi", state["language"])
        shutil.rmtree(self.folder / ND30_FOLDERS["vi"])
        for path in self.folder.iterdir():
            path.unlink()
        self.run_seed(LANGUAGE="vi_VN:vi")
        self.assertEqual([], list(self.folder.iterdir()), "deleted templates do not come back")

    def test_english_session_and_existing_files(self) -> None:
        self.folder.mkdir()
        (self.folder / "Word Document.docx").write_text("mine", encoding="utf-8")
        self.run_seed(LANG="en_US.UTF-8")
        self.assertEqual("mine", (self.folder / "Word Document.docx").read_text(encoding="utf-8"))
        self.assertEqual(sorted(TemplateFileTests.NAMES["en"] + [ND30_FOLDERS["en"]]),
                         sorted(path.name for path in self.folder.iterdir()))
        # English sessions get the Vietnamese documents too (schools on the English Xfce edition write them).
        self.assertEqual(sorted(ND30_NAMES), sorted(path.name for path in (self.folder / ND30_FOLDERS["en"]).iterdir()))

    def test_waits_while_there_is_no_templates_folder(self) -> None:
        self.answer = str(self.home)        # xdg-user-dir answers the home folder before xdg-user-dirs ran
        self.run_seed(LANG="vi_VN")
        self.assertFalse((self.home / templates.STATE).exists())
        self.assertFalse((self.home / ND30_STATE).exists())
        self.assertEqual([], [path for path in self.home.iterdir() if path.is_file()])

    def test_users_of_an_earlier_version_get_the_new_set_once(self) -> None:
        # 1.4.0 put the office documents in and wrote templates.json; the user deleted two and changed one.
        self.folder.mkdir()
        (self.folder / "Văn bản Word.docx").write_text("của tôi", encoding="utf-8")
        state = self.home / templates.STATE
        state.parent.mkdir(parents=True)
        state.write_text('{"language": "vi", "folder": "x", "copied": []}\n', encoding="utf-8")
        mine = self.folder / ND30_FOLDERS["vi"]
        mine.mkdir()
        (mine / "Công văn.docx").write_text("mẫu riêng", encoding="utf-8")
        self.run_seed(LANGUAGE="vi_VN:vi", LANG="vi_VN")
        self.assertEqual(sorted(["Văn bản hành chính", "Văn bản Word.docx"]),
                         sorted(path.name for path in self.folder.iterdir()), "the office set is not put in again")
        self.assertEqual("của tôi", (self.folder / "Văn bản Word.docx").read_text(encoding="utf-8"))
        self.assertEqual("mẫu riêng", (mine / "Công văn.docx").read_text(encoding="utf-8"), "a file of the user stays")
        self.assertEqual(sorted(ND30_NAMES), sorted(path.name for path in mine.iterdir()))
        record = json.loads((self.home / ND30_STATE).read_text(encoding="utf-8"))
        self.assertNotIn("Công văn.docx", record["copied"])
        shutil.rmtree(mine)
        self.run_seed(LANGUAGE="vi_VN:vi", LANG="vi_VN")
        self.assertFalse(mine.exists(), "a deleted folder does not come back")

    def test_a_file_where_the_folder_would_go_is_left_alone(self) -> None:
        self.folder.mkdir()
        (self.folder / ND30_FOLDERS["vi"]).write_text("không phải thư mục", encoding="utf-8")
        self.assertEqual(0, self.run_seed(LANG="vi_VN.UTF-8"))
        self.assertEqual("không phải thư mục", (self.folder / ND30_FOLDERS["vi"]).read_text(encoding="utf-8"))
        self.assertIn("error", json.loads((self.home / ND30_STATE).read_text(encoding="utf-8")))

    def test_an_error_is_tried_again_at_the_next_login(self) -> None:
        with mock.patch.object(templates, "seed", side_effect=PermissionError("denied")):
            with self.assertRaises(PermissionError):
                self.run_seed(LANG="vi_VN")
        self.assertFalse((self.home / templates.STATE).exists(), "no record: the service fails and runs again")

    def test_a_missing_set_is_tried_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shipped = Path(tmp)
            shutil.copytree(TEMPLATES / "vi", shipped / "vi")
            with mock.patch.object(templates.subprocess, "run",
                                   lambda args, **_k: subprocess.CompletedProcess(args, 0, self.answer + "\n", "")), \
                    mock.patch("builtins.print"):
                templates.run(self.home, {"LANG": "vi_VN"}, shipped)
        self.assertTrue((self.home / templates.STATE).exists())
        self.assertFalse((self.home / ND30_STATE).exists(), "no record without the documents")


class AdministrativeTemplateTests(unittest.TestCase):
    """The documents of Nghị định 30/2020/NĐ-CP (Phụ lục I: layout; Phụ lục III: one per kind of document)."""

    KINDS = {"Công văn.docx": None, "Quyết định.docx": "QUYẾT ĐỊNH", "Tờ trình.docx": "TỜ TRÌNH",
             "Báo cáo.docx": "BÁO CÁO", "Thông báo.docx": "THÔNG BÁO", "Giấy mời.docx": "GIẤY MỜI",
             "Biên bản.docx": "BIÊN BẢN", "Biên bản bàn giao tài sản.docx": "BIÊN BẢN BÀN GIAO TÀI SẢN"}
    NUMBERS = {"Công văn.docx": "Số: …/…-…", "Quyết định.docx": "Số: …/QĐ-…", "Tờ trình.docx": "Số: …/TTr-…",
               "Báo cáo.docx": "Số: …/BC-…", "Thông báo.docx": "Số: …/TB-…", "Giấy mời.docx": "Số: …/GM-…",
               "Biên bản.docx": "Số: …/BB-…", "Biên bản bàn giao tài sản.docx": "Số: …/BB-…"}

    def parts(self, name: str) -> dict[str, str]:
        with zipfile.ZipFile(TEMPLATES / "nd30" / name) as document:
            self.assertIsNone(document.testzip())
            return {part: document.read(part).decode("utf-8") for part in document.namelist()}

    @staticmethod
    def run_props(document: str, text: str) -> list[str]:
        """The formatting of each run whose whole text is `text`, as a list like ["b", "sz=24"]."""

        found = []
        for props in re.findall(r"<w:r><w:rPr>((?:(?!</w:rPr>).)*)</w:rPr><w:t xml:space=\"preserve\">"
                                + re.escape(text) + "</w:t>", document):
            found.append(sorted(set(re.findall(r"<w:(b|i)/>", props))
                                | {f"sz={size}" for size in re.findall(r'<w:sz w:val="(\d+)"/>', props)}))
        return found

    def test_the_eight_documents(self) -> None:
        self.assertEqual(sorted(ND30_NAMES), sorted(path.name for path in (TEMPLATES / "nd30").iterdir()))
        self.assertEqual(sorted(ND30_NAMES), sorted(self.KINDS))

    def test_the_generator_writes_the_shipped_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run([sys.executable, "-I", str(GENERATOR), "--out", tmp], check=True, capture_output=True)
            for name in ND30_NAMES:
                self.assertEqual((TEMPLATES / "nd30" / name).read_bytes(), (Path(tmp) / name).read_bytes(),
                                 f"{name}: run tools/make-nd30-templates.py and commit the result")

    def test_paper_margins_font_and_page_numbers(self) -> None:
        for name in ND30_NAMES:
            with self.subTest(name):
                parts = self.parts(name)
                document = parts["word/document.xml"]
                self.assertIn('<w:pgSz w:w="11906" w:h="16838"/>', document)          # A4, portrait
                margins = re.search(r"<w:pgMar ([^>]*)/>", document).group(1)
                mm = {key: int(value) * 25.4 / 1440 for key, value in re.findall(r'w:(\w+)="(\d+)"', margins)}
                self.assertTrue(20 <= round(mm["top"]) <= 25 and 20 <= round(mm["bottom"]) <= 25, mm)
                self.assertTrue(30 <= round(mm["left"]) <= 35 and 15 <= round(mm["right"]) <= 20, mm)
                styles = parts["word/styles.xml"]
                self.assertIn('<w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman"', styles)
                self.assertIn('<w:lang w:val="vi-VN"', styles)
                self.assertIn('<w:color w:val="000000"/>', styles)
                self.assertIn('<w:ind w:firstLine="720"/><w:jc w:val="both"/>', styles)   # the body: 1.27 cm
                self.assertIn('w:after="120"', styles)                                     # 6 pt between paragraphs
                self.assertIn("<dc:creator></dc:creator>", parts["docProps/core.xml"], "no author name")
                self.assertIn("<w:titlePg/>", document)                    # no number on the first page
                self.assertIn('w:instr=" PAGE "', parts["word/header1.xml"])
                self.assertNotIn("PAGE", parts["word/header2.xml"])

    def test_header(self) -> None:
        for name in ND30_NAMES:
            with self.subTest(name):
                document = self.parts(name)["word/document.xml"]
                self.assertEqual([["b", "sz=24"]], self.run_props(document, "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"))
                self.assertEqual([["b", "sz=26"]], self.run_props(document, "Độc lập - Tự do - Hạnh phúc"))
                self.assertEqual([["sz=26"]], self.run_props(document, self.NUMBERS[name]))
                body_name = "TÊN CÔNG TY, TỔ CHỨC" if "bàn giao" in name else "TÊN CƠ QUAN, TỔ CHỨC"
                self.assertEqual([["b", "sz=24"]], self.run_props(document, body_name))
                date = self.run_props(document, "…………, ngày … tháng … năm 20…")
                # A biên bản has no place and date in its header (Mẫu 1.9): its time is in the text.
                self.assertEqual([] if name == "Biên bản.docx" else [["i", "sz=26"]], date)
                # The rule under the motto is exactly as long as the motto (158.91 pt = 3178 twips).
                motto = document.index("Độc lập - Tự do - Hạnh phúc")
                rule = re.search(r'<w:pBdr><w:top w:val="single"[^>]*/></w:pBdr>.*?<w:ind w:left="(\d+)" '
                                 r'w:right="(\d+)"', document[motto:])
                left, right = int(rule.group(1)), int(rule.group(2))
                right_column = 11906 - 1701 - 1134 - 3402
                self.assertLessEqual(abs(right_column - left - right - 3178), 1)

    def test_title_recipients_and_signature(self) -> None:
        for name, kind in self.KINDS.items():
            with self.subTest(name):
                document = self.parts(name)["word/document.xml"]
                if kind:
                    self.assertEqual([["b", "sz=28"]], self.run_props(document, kind))
                self.assertEqual("Kính gửi" in document, name in ("Công văn.docx", "Tờ trình.docx", "Báo cáo.docx"))
                if "bàn giao" not in name:
                    self.assertEqual([["b", "i", "sz=24"]], self.run_props(document, "Nơi nhận:"))
                    self.assertIn("Lưu: VT", document)
                    self.assertIn(["b", "sz=28"], self.run_props(document, "Họ và tên"))
                if name not in ("Biên bản.docx", "Biên bản bàn giao tài sản.docx"):
                    self.assertEqual([["b", "sz=28"]], self.run_props(document, "QUYỀN HẠN, CHỨC VỤ CỦA NGƯỜI KÝ"))
                self.assertTrue(document.count("./.") >= 1 or "bàn giao" in name)
        decision = self.parts("Quyết định.docx")["word/document.xml"]
        self.assertEqual([["b", "sz=28"]], self.run_props(decision, "THẨM QUYỀN BAN HÀNH"))
        self.assertEqual([["i", "sz=28"], ["i", "sz=28"]], self.run_props(decision, "Căn cứ "))  # căn cứ in italics
        letter = self.parts("Công văn.docx")["word/document.xml"]
        self.assertEqual([["sz=24"]], self.run_props(letter, "V/v " + "…" * 10))      # ô 5b: 12 pt, upright
        record = self.parts("Biên bản.docx")["word/document.xml"]
        self.assertEqual([["b", "sz=28"]], self.run_props(record, "THƯ KÝ"))
        self.assertEqual([["b", "sz=28"]], self.run_props(record, "CHỦ TỌA"))
        handover = self.parts("Biên bản bàn giao tài sản.docx")["word/document.xml"]
        for column in ("STT", "Tên tài sản", "Đơn vị tính", "Số lượng", "Tình trạng", "Ghi chú"):
            self.assertIn(f">{column}<", handover)
        self.assertIn("<w:tblHeader/>", handover)
        self.assertIn("ĐẠI DIỆN BÊN GIAO", handover)


class AdministrativeTemplatesMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.migration = importlib.import_module(
            "caramos_ota_update.migrations.20261122100100_administrative_templates.migration")

    def test_starts_the_service_in_open_sessions(self) -> None:
        from caramos_ota_update.context import MigrationContext

        calls: list[tuple] = []
        logged: list[str] = []
        module = self.migration.files_new_menu
        context = MigrationContext()
        with tempfile.TemporaryDirectory() as tmp:
            service = Path(tmp) / "caramos-templates.service"
            service.write_text("[Unit]\n", encoding="utf-8")
            with mock.patch.object(self.migration, "SERVICE_FILE", service), \
                    mock.patch.object(module, "_desktop_users", return_value=[("lan", 1000), ("minh", 1001)]), \
                    mock.patch.object(module, "_user_manager_running", side_effect=lambda uid: uid == 1000), \
                    mock.patch.object(module, "_systemctl", side_effect=lambda user, uid, *args: (
                        calls.append((user, *args)), subprocess.CompletedProcess(args, 0, "", ""))[1]), \
                    mock.patch.object(context, "log", side_effect=logged.append):
                self.migration.run(context)
        self.assertEqual([("lan", "daemon-reload"), ("lan", "start", "caramos-templates.service")], calls)
        self.assertIn("started caramos-templates.service for lan", logged)

    def test_dry_run_changes_nothing(self) -> None:
        from caramos_ota_update.context import MigrationContext

        with mock.patch.object(self.migration.files_new_menu, "_systemctl") as systemctl, mock.patch("builtins.print"):
            self.migration.run(MigrationContext(dry_run=True))
        systemctl.assert_not_called()

    def test_manifest(self) -> None:
        manifest = json.loads((TEMPLATES_MIGRATION / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("feature", manifest["severity"])
        self.assertNotIn("desktops", manifest)                     # Nemo is the file manager of both editions
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertIn("Mới > Văn bản hành chính", manifest["summary"])
        self.assertIn("New > Vietnamese Official Documents", manifest["summary_en"])
        self.assertIn("Microsoft Core Fonts", " ".join(manifest["release_notes_vi"]))


class PackagingTests(unittest.TestCase):
    def test_package_ships_and_runs_everything(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        for line in ("usr/share/caramos-ota/nemo-menu usr/share/caramos-ota/",
                     "usr/share/caramos-ota/templates usr/share/caramos-ota/",
                     "usr/lib/systemd/user/caramos-templates.timer usr/lib/systemd/user/",
                     "usr/lib/systemd/user/caramos-templates.service usr/lib/systemd/user/",
                     "etc/X11/Xsession.d/85caramos-nemo-menu etc/X11/Xsession.d/"):
            self.assertIn(line, install)
        self.assertIn("interest-noawait /usr/lib/x86_64-linux-gnu/libnemo-extension.so.1",
                      (ROOT / "debian/triggers").read_text(encoding="utf-8"))
        postinst = (ROOT / "debian/postinst").read_text(encoding="utf-8")
        self.assertEqual(2, postinst.count("/usr/share/caramos-ota/nemo-menu/caramos-nemo-menu || true"))
        self.assertIn("caramos-nemo-menu --remove", (ROOT / "debian/prerm").read_text(encoding="utf-8"))
        for script in (MENU_SCRIPT, TEMPLATES_SCRIPT):
            self.assertTrue(script.stat().st_mode & 0o111, script)

    def test_user_timer_runs_once_after_login(self) -> None:
        timer = configparser.ConfigParser(interpolation=None, strict=False)
        timer.read(ROOT / "usr/lib/systemd/user/caramos-templates.timer", encoding="utf-8")
        self.assertEqual("timers.target", timer["Install"]["WantedBy"])
        self.assertIn("OnStartupSec", timer["Timer"])
        service = configparser.ConfigParser(interpolation=None, strict=False)
        service.read(ROOT / "usr/lib/systemd/user/caramos-templates.service", encoding="utf-8")
        self.assertEqual("/" + TEMPLATES_SCRIPT.relative_to(ROOT).as_posix(), service["Service"]["ExecStart"])
        # Both units run while the record of any set is missing ("|": one of these conditions is enough).
        expected = [f"ConditionPathExists=|!%h/{item.state.as_posix()}" for item in templates.SETS]
        for unit in ("caramos-templates.service", "caramos-templates.timer"):
            lines = (ROOT / "usr/lib/systemd/user" / unit).read_text(encoding="utf-8").splitlines()
            self.assertEqual(expected, [line for line in lines if line.startswith("ConditionPathExists=")], unit)

    @unittest.skipUnless((REPO / "config").is_dir(), "the source package has no config/")
    def test_new_installs_get_the_folder_tree(self) -> None:
        override = REPO / "config/includes.chroot/usr/share/glib-2.0/schemas/99_caramos.gschema.override"
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        parser.read(override, encoding="utf-8")
        self.assertEqual("'tree'", parser["org.nemo.window-state"]["side-pane-view"])

    def test_migration_announces_the_menu(self) -> None:
        manifest = json.loads((MIGRATION / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("feature", manifest["severity"])
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertIn("Mới > Thư mục", " ".join(manifest["release_notes_vi"]))
        self.assertIn("đăng nhập sau", manifest["release_notes_vi"][-1])


if __name__ == "__main__":
    unittest.main()

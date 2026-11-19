"""Office documents and archives open in an app that opens them (caramos-open-document, /etc/xdg/mimeapps.list).

CaramOS comes without an office suite. Until 1.4.0 a .docx, .xlsx or .pptx then went to the default app of
application/zip, its parent type, which the ISO's ~/.config/mimeapps.list said was Nemo: Nemo only showed the folder
the file is in. The same happened to .zip files.
"""

from __future__ import annotations

import configparser
import importlib
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
REPO_CONFIG = ROOT.parents[1] / "config"
OPEN_DOCUMENT = ROOT / "usr/share/caramos-ota/open-document"
sys.path.insert(0, str(OPEN_DOCUMENT))

import caramos_open_document as opener  # noqa: E402

MIGRATION_ID = "20261119100000_open_office_documents"
migration = importlib.import_module(f"caramos_ota_update.migrations.{MIGRATION_ID}.migration")

SKEL_LIST = """[Default Applications]
text/html=google-chrome.desktop

text/plain=xed.desktop

application/zip=nemo.desktop
application/x-tar=nemo.desktop
"""


def read_list(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, delimiters=("=",))
    parser.optionxform = str  # MIME types are case-sensitive (macroEnabled)
    parser.read(path, encoding="utf-8")
    return parser


class App:
    def __init__(self, desktop_id: str, name: str = "", shown: bool = True, files: bool = True) -> None:
        self.desktop_id = desktop_id
        self.name = name or desktop_id
        self.shown = shown
        self.files = files

    def get_id(self) -> str:
        return self.desktop_id

    def get_display_name(self) -> str:
        return self.name

    def should_show(self) -> bool:
        return self.shown

    def supports_files(self) -> bool:
        return self.files

    def supports_uris(self) -> bool:
        return False


class DefaultAppsTests(unittest.TestCase):
    def test_the_system_list_is_the_programs_list(self) -> None:
        defaults = read_list(ROOT / "etc/xdg/mimeapps.list")["Default Applications"]
        written = {content_type: tuple(filter(None, value.split(";"))) for content_type, value in defaults.items()}
        self.assertEqual(opener.DEFAULTS, written)

    def test_the_suites_come_first_and_this_program_last(self) -> None:
        for content_type, apps in opener.DEFAULTS.items():
            self.assertEqual(opener.DESKTOP_ID, apps[-1], content_type)
            self.assertEqual(len(apps), len(set(apps)), content_type)
            self.assertIn("org.onlyoffice.desktopeditors.desktop", apps, content_type)
            self.assertTrue(any(app.startswith("wps-office-") for app in apps), content_type)
            self.assertTrue(any("libreoffice" in app.lower() for app in apps), content_type)

    def test_word_excel_and_powerpoint_files(self) -> None:
        for content_type, kind in (
            ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", opener.DOCUMENT),
            ("application/msword", opener.DOCUMENT),
            ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", opener.SPREADSHEET),
            ("application/vnd.ms-excel", opener.SPREADSHEET),
            ("application/vnd.openxmlformats-officedocument.presentationml.presentation", opener.PRESENTATION),
            ("application/vnd.oasis.opendocument.text", opener.DOCUMENT),
        ):
            self.assertEqual(kind, opener.TYPES[content_type])
        self.assertIn("wps-office-et.desktop", opener.DEFAULTS[
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"])
        self.assertIn("wps-office-wpp.desktop", opener.DEFAULTS["application/vnd.ms-powerpoint"])
        self.assertIn("wps-office-wps.desktop", opener.DEFAULTS["application/msword"])

    def test_archives_are_not_given_to_the_file_manager(self) -> None:
        defaults = read_list(ROOT / "etc/xdg/mimeapps.list")["Default Applications"]
        self.assertNotIn("application/zip", defaults)
        for value in defaults.values():
            self.assertNotIn("nemo.desktop", value)

    @unittest.skipUnless(REPO_CONFIG.is_dir(), "the source package has no config/")
    def test_new_users_do_not_open_archives_with_nemo(self) -> None:
        skel = REPO_CONFIG / "includes.chroot/etc/skel/.config/mimeapps.list"
        self.assertIsNone(migration.cleaned(skel.read_text(encoding="utf-8")))
        self.assertNotIn("=nemo.desktop", skel.read_text(encoding="utf-8"))


class DesktopEntryTests(unittest.TestCase):
    def test_hidden_and_claims_no_type(self) -> None:
        entry = configparser.ConfigParser(interpolation=None)
        entry.optionxform = str
        entry.read(ROOT / "usr/share/applications" / opener.DESKTOP_ID, encoding="utf-8")
        desktop = entry["Desktop Entry"]
        self.assertEqual("true", desktop["NoDisplay"])
        self.assertNotIn("MimeType", desktop)
        self.assertEqual("Bộ ứng dụng văn phòng", desktop["Name[vi]"])
        program = desktop["Exec"].split()[0]
        self.assertEqual("/usr/share/caramos-ota/open-document/caramos-open-document", program)
        launcher = ROOT / program.lstrip("/")
        self.assertTrue(launcher.stat().st_mode & stat.S_IXUSR)
        self.assertIn("caramos_open_document", launcher.read_text(encoding="utf-8"))

    def test_packaged(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8").splitlines()
        for line in ("usr/share/caramos-ota/open-document usr/share/caramos-ota/",
                     "usr/share/applications/caramos-open-document.desktop usr/share/applications/",
                     "etc/xdg/mimeapps.list etc/xdg/"):
            self.assertIn(line, install)


class PlanTests(unittest.TestCase):
    def test_an_app_that_opens_the_type_gets_the_files(self) -> None:
        gnumeric = App("org.gnome.Gnumeric.desktop")
        files = [("a.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                 ("b.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")]
        launches, left = opener.plan(files, lambda _type: [App(opener.DESKTOP_ID), gnumeric])
        self.assertEqual([(gnumeric, ["a.xlsx", "b.xlsx"])], launches)
        self.assertEqual([], left)

    def test_archive_and_file_managers_do_not_count(self) -> None:
        apps = [App("org.gnome.FileRoller.desktop"), App("nemo.desktop"), App(opener.DESKTOP_ID)]
        launches, left = opener.plan([("a.docx", "application/msword")], lambda _type: apps)
        self.assertEqual([], launches)
        self.assertEqual([("a.docx", "application/msword")], left)

    def test_each_type_its_own_app(self) -> None:
        writer, calc = App("writer.desktop"), App("calc.desktop")
        apps = {"application/msword": [writer], "application/vnd.ms-excel": [calc], "application/rtf": []}
        launches, left = opener.plan([("a.doc", "application/msword"), ("b.xls", "application/vnd.ms-excel"),
                                      ("c.rtf", "application/rtf"), ("d.doc", "application/msword")],
                                     lambda content_type: apps[content_type])
        self.assertEqual([(writer, ["a.doc", "d.doc"]), (calc, ["b.xls"])], launches)
        self.assertEqual([("c.rtf", "application/rtf")], left)


class ChoicesTests(unittest.TestCase):
    def test_menu_apps_by_name_without_hidden_ones_or_this_program(self) -> None:
        apps = [App("xed.desktop", "Trình soạn thảo văn bản"), App("firefox.desktop", "Firefox"),
                App("evolution-data-server-oauth2.desktop", "OAuth2 Handler", shown=False),
                App(opener.DESKTOP_ID, "Bộ ứng dụng văn phòng"), App("nemo.desktop", "Tệp"),
                App("org.gnome.FileRoller.desktop", "Archive Manager"), App("xviewer.desktop", "bộ xem ảnh"),
                App("mugshot.desktop", "About Me", files=False)]
        self.assertEqual(["bộ xem ảnh", "Firefox", "Trình soạn thảo văn bản"],
                         [app.get_display_name() for app in opener.choices(apps)])


class DialogTextTests(unittest.TestCase):
    def test_says_what_the_file_is(self) -> None:
        texts = {opener.describe(["Bảng tính.xlsx"], [content_type])[1] for content_type in (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/x-unknown")}
        self.assertEqual(4, len(texts))
        for text in texts:
            self.assertIn("Bảng tính.xlsx", text)
            self.assertIn("App Center", text)
            self.assertIn("ONLYOFFICE", text)

    def test_several_files(self) -> None:
        one = opener.describe(["a.docx"], ["application/msword"])
        three = opener.describe(["a.docx", "b.xlsx", "c.pptx"], ["application/msword"] * 3)
        self.assertNotEqual(one[0], three[0])
        self.assertIn("a.docx", three[1])
        self.assertIn("2", three[1])


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.home = Path(tempfile.mkdtemp())
        (self.home / ".config").mkdir()
        self.list = self.home / ".config/mimeapps.list"
        self.uid = os.getuid()

    def tearDown(self) -> None:
        for path in sorted(self.home.rglob("*"), reverse=True):
            path.unlink() if path.is_file() or path.is_symlink() else path.rmdir()
        self.home.rmdir()

    def test_removes_only_the_isos_lines(self) -> None:
        self.assertEqual("[Default Applications]\ntext/html=google-chrome.desktop\n\ntext/plain=xed.desktop\n\n",
                         migration.cleaned(SKEL_LIST))
        mine = "[Default Applications]\napplication/zip=org.gnome.FileRoller.desktop\n"
        self.assertIsNone(migration.cleaned(mine))
        added = "[Added Associations]\napplication/zip=nemo.desktop;\n"
        self.assertIsNone(migration.cleaned(added))
        self.assertEqual("[Default Applications]\n", migration.cleaned("[Default Applications]\napplication/zip=nemo.desktop;\n"))

    def test_rewrites_the_users_file(self) -> None:
        self.list.write_text(SKEL_LIST, encoding="utf-8")
        self.list.chmod(0o640)
        self.assertIn("removed", migration.fix(self.home, self.uid))
        self.assertNotIn("nemo.desktop", self.list.read_text(encoding="utf-8"))
        self.assertIn("text/plain=xed.desktop", self.list.read_text(encoding="utf-8"))
        self.assertEqual(0o640, stat.S_IMODE(self.list.stat().st_mode))
        self.assertEqual(["mimeapps.list"], [path.name for path in (self.home / ".config").iterdir()])
        self.assertIn("no Nemo default", migration.fix(self.home, self.uid))

    def test_dry_run_changes_nothing(self) -> None:
        self.list.write_text(SKEL_LIST, encoding="utf-8")
        self.assertIn("would remove", migration.fix(self.home, self.uid, dry_run=True))
        self.assertEqual(SKEL_LIST, self.list.read_text(encoding="utf-8"))

    def test_symbolic_links_and_other_owners_are_left_alone(self) -> None:
        elsewhere = self.home / "elsewhere"
        elsewhere.write_text(SKEL_LIST, encoding="utf-8")
        self.list.symlink_to(elsewhere)
        self.assertIn("skip", migration.fix(self.home, self.uid))
        self.assertEqual(SKEL_LIST, elsewhere.read_text(encoding="utf-8"))
        self.list.unlink()
        self.list.write_text(SKEL_LIST, encoding="utf-8")
        self.assertIn("skip", migration.fix(self.home, self.uid + 1))
        self.assertEqual(SKEL_LIST, self.list.read_text(encoding="utf-8"))

    def test_a_linked_config_folder_is_left_alone(self) -> None:
        (self.home / ".config").rmdir()
        target = self.home / "target"
        target.mkdir()
        (target / "mimeapps.list").write_text(SKEL_LIST, encoding="utf-8")
        (self.home / ".config").symlink_to(target)
        self.assertIn("skip", migration.fix(self.home, self.uid))
        self.assertEqual(SKEL_LIST, (target / "mimeapps.list").read_text(encoding="utf-8"))
        (self.home / ".config").unlink()

    def test_run_covers_skel_and_every_user(self) -> None:
        user = mock.Mock(pw_dir=str(self.home), pw_uid=self.uid)
        self.list.write_text(SKEL_LIST, encoding="utf-8")
        skel = Path(tempfile.mkdtemp())
        context = mock.Mock(dry_run=False)
        try:
            with mock.patch.object(migration, "SKEL", skel), \
                    mock.patch.object(migration, "_desktop_users", return_value=[user]):
                migration.run(context)
        finally:
            skel.rmdir()
        logged = " ".join(call.args[0] for call in context.log.call_args_list)
        self.assertIn(f"no {skel}/.config/mimeapps.list", logged)
        self.assertIn("removed", logged)
        self.assertNotIn("nemo.desktop", self.list.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

"""Migration 20261117100100_nemo_actions_in_menu: the three Nemo actions CaramOS installs get their action files,
so the file manager's right-click menu shows them, translated."""

from __future__ import annotations

import configparser
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext, MigrationContextError

ROOT = Path(__file__).parents[1]
REPO = ROOT.parents[1]
HOOK = REPO / "config/hooks/live/0170-cinnamon-task17-spices.hook.chroot"
MIGRATION_DIR = ROOT / "usr/lib/python3/dist-packages/caramos_ota_update/migrations/20261117100100_nemo_actions_in_menu"

migration = importlib.import_module("caramos_ota_update.migrations.20261117100100_nemo_actions_in_menu.migration")
translate_spices = importlib.import_module(migration.TRANSLATE_SPICES)

COPY = "copy-path-to-clipboard@claudiux"
SHORTCUT = "create-desktop-shortcut@anaximeno"
KDE = "send-with-kdeconnect@rcalixte"

VI_COPY = '''\
# Vietnamese translation.
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"

#. copy-path-to-clipboard@claudiux.nemo_action.in->Name
msgid "Copy path to clipboard"
msgstr "Sao chép đường dẫn vào clipboard"

#. copy-path-to-clipboard@claudiux.nemo_action.in->Comment
msgid "Copy the full path of the selected item to the clipboard"
msgstr ""
"Sao chép đường dẫn đầy đủ "
"của mục được chọn vào clipboard"
'''

VI_SHORTCUT = '''\
msgid ""
msgstr "Content-Type: text/plain; charset=UTF-8\\n"

msgid "Create a desktop shortcut"
msgstr "Tạo lối tắt trên màn hình"

#, fuzzy
msgid "Create a shortcut of the selected items on the Desktop folder"
msgstr "Bản dịch cũ, chưa duyệt"

msgid "Couldn't create all shortcuts!"
msgstr "Không tạo được hết các lối tắt!"
'''


def parse(text: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(text)
    return parser


class PoReaderTests(unittest.TestCase):
    def test_entries_continuations_escapes_and_fuzzy(self) -> None:
        text = VI_SHORTCUT + '''
msgid "A \\"quoted\\" word"
msgstr "Một từ \\"trong ngoặc\\""
msgid "Untranslated"
msgstr ""

msgid "One file"
msgid_plural "%d files"
msgstr[0] "%d tệp"

#~ msgid "Old"
#~ msgstr "Cũ"
'''
        entries = migration.read_po(text)
        self.assertEqual({
            "Create a desktop shortcut": "Tạo lối tắt trên màn hình",
            "Couldn't create all shortcuts!": "Không tạo được hết các lối tắt!",
            'A "quoted" word': 'Một từ "trong ngoặc"',
        }, entries)
        self.assertEqual("Sao chép đường dẫn đầy đủ của mục được chọn vào clipboard",
                         migration.read_po(VI_COPY)["Copy the full path of the selected item to the clipboard"])


class BuildActionTests(unittest.TestCase):
    def test_copy_path_gets_translations_and_the_system_path(self) -> None:
        text = migration.build_action(COPY, migration.TEMPLATES[COPY], {
            "vi": migration.read_po(VI_COPY),
            "fr": {"Copy path to clipboard": "Copier le chemin"},
        })
        action = parse(text)["Nemo Action"]
        self.assertEqual("Copy path to clipboard", action["Name"])
        self.assertEqual("Sao chép đường dẫn vào clipboard", action["Name[vi]"])
        self.assertEqual("Copier le chemin", action["Name[fr]"])
        self.assertEqual("Sao chép đường dẫn đầy đủ của mục được chọn vào clipboard", action["Comment[vi]"])
        self.assertEqual(
            "/usr/bin/env bash -c '/usr/share/nemo/actions/copy-path-to-clipboard@claudiux/copy-pah.sh %F %U'",
            action["Exec"])
        self.assertEqual("xclip;", action["Dependencies"])
        self.assertNotIn("_Name", action)
        self.assertLess(text.index("Name[fr]"), text.index("Name[vi]"), "languages are sorted")
        self.assertLess(text.index("Name[vi]"), text.index("Comment="), "each translation follows its key")

    def test_relative_execs_stay_relative(self) -> None:
        action = parse(migration.build_action(SHORTCUT, migration.TEMPLATES[SHORTCUT], {}))["Nemo Action"]
        self.assertEqual('<create-desktop-shortcut@anaximeno/action.py "%F">', action["Exec"])
        self.assertEqual('exec <create-desktop-shortcut@anaximeno/check.sh "%P">;', action["Conditions"])
        self.assertEqual("Create a desktop shortcut", action["Name"])

    def test_every_template_is_a_valid_action(self) -> None:
        for uuid, template in migration.TEMPLATES.items():
            action = parse(migration.build_action(uuid, template, {}))["Nemo Action"]
            self.assertTrue(action["Name"] and action["Exec"], uuid)


class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.actions = self.root / "actions"
        for uuid, po in ((COPY, VI_COPY), (SHORTCUT, VI_SHORTCUT), (KDE, "")):
            (self.actions / uuid / "po").mkdir(parents=True)
            if po:
                (self.actions / uuid / "po" / "vi.po").write_text(po, encoding="utf-8")
        self.skel = self.root / "skel"
        self.skel.mkdir()
        for target, value in ((migration, {"ACTIONS": self.actions, "XCLIP": self.root / "xclip"}),
                              (translate_spices, {"SKEL": self.skel, "SKEL_OWNER": (self.skel.stat().st_uid,
                                                                                      self.skel.stat().st_gid)})):
            for name, replacement in value.items():
                patcher = mock.patch.object(target, name, replacement)
                patcher.start()
                self.addCleanup(patcher.stop)
        patcher = mock.patch.object(translate_spices, "_desktop_users", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.installs: list[list[str]] = []

    def run_migration(self, dry_run: bool = False, apt_fails: bool = False) -> None:
        def apt_install(context, packages, recommends=True):
            self.installs.append(list(packages))
            if apt_fails:
                raise MigrationContextError("no network")

        with mock.patch("builtins.print"), mock.patch("caramos_ota_update.context.log_info"), \
                mock.patch.object(MigrationContext, "apt_install", apt_install):
            migration.run(MigrationContext(dry_run=dry_run))

    def test_writes_the_three_actions_and_installs_xclip(self) -> None:
        self.run_migration()
        copy = parse((self.actions / f"{COPY}.nemo_action").read_text(encoding="utf-8"))["Nemo Action"]
        self.assertEqual("Sao chép đường dẫn vào clipboard", copy["Name[vi]"])
        shortcut = parse((self.actions / f"{SHORTCUT}.nemo_action").read_text(encoding="utf-8"))["Nemo Action"]
        self.assertEqual("Tạo lối tắt trên màn hình", shortcut["Name[vi]"])
        self.assertNotIn("Comment[vi]", shortcut, "a fuzzy translation is left out")
        kde = parse((self.actions / f"{KDE}.nemo_action").read_text(encoding="utf-8"))["Nemo Action"]
        self.assertEqual("Send with KDE Connect", kde["Name"])
        self.assertEqual([["xclip"]], self.installs)
        mo = self.skel / ".local/share/locale/vi/LC_MESSAGES" / f"{SHORTCUT}.mo"
        if Path(translate_spices.MSGFMT).is_file():
            self.assertTrue(mo.is_file(), "the dialogs of Create a desktop shortcut are translated")

    def test_keeps_existing_files_skips_missing_actions_and_xclip_present(self) -> None:
        own = self.actions / f"{COPY}.nemo_action"
        own.write_text("[Nemo Action]\nName=Mine\nExec=true\n", encoding="utf-8")
        (self.root / "xclip").write_text("", encoding="utf-8")
        for path in sorted((self.actions / KDE).rglob("*"), reverse=True):
            path.rmdir() if path.is_dir() else path.unlink()
        (self.actions / KDE).rmdir()
        self.run_migration()
        self.assertEqual("[Nemo Action]\nName=Mine\nExec=true\n", own.read_text(encoding="utf-8"))
        self.assertFalse((self.actions / f"{KDE}.nemo_action").exists())
        self.assertTrue((self.actions / f"{SHORTCUT}.nemo_action").exists())
        self.assertEqual([], self.installs)

    def test_prefers_the_template_the_iso_kept(self) -> None:
        own = migration.TEMPLATES[COPY].replace("copy-pah.sh", "copy-path.sh")
        (self.actions / COPY / f"{COPY}.nemo_action.in").write_text(own, encoding="utf-8")
        self.run_migration()
        copy = parse((self.actions / f"{COPY}.nemo_action").read_text(encoding="utf-8"))["Nemo Action"]
        # The script runs from where the action is installed (ACTIONS, /usr/share/nemo/actions on a real system).
        self.assertEqual(
            f"/usr/bin/env bash -c '{self.actions}/copy-path-to-clipboard@claudiux/copy-path.sh %F %U'",
            copy["Exec"])

    def test_a_failed_xclip_install_does_not_fail_the_update(self) -> None:
        self.run_migration(apt_fails=True)
        self.assertEqual([["xclip"]], self.installs)
        self.assertTrue((self.actions / f"{COPY}.nemo_action").exists())

    def test_dry_run_writes_nothing(self) -> None:
        self.run_migration(dry_run=True)
        self.assertEqual([], sorted(self.actions.glob("*.nemo_action")))
        self.assertFalse((self.skel / ".local").exists())

    def test_no_actions_folder(self) -> None:
        with mock.patch.object(migration, "ACTIONS", self.root / "missing"):
            self.run_migration()
        self.assertEqual([], self.installs)

    def test_manifest_texts(self) -> None:
        manifest = json.loads((MIGRATION_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(2, manifest["schema"])
        for key in ("title", "summary", "title_en", "summary_en", "size", "size_en"):
            self.assertTrue(manifest[key].strip(), key)
        self.assertIn("Sao chép đường dẫn vào clipboard", " ".join(manifest["release_notes_vi"]))


@unittest.skipUnless(HOOK.exists(), "the ISO hooks are not in the source package")
class SpicesHookTests(unittest.TestCase):
    def test_the_iso_keeps_the_action_templates(self) -> None:
        hook = HOOK.read_text(encoding="utf-8")
        self.assertIn('-name "${uuid}.nemo_action.in"', hook)
        for uuid in migration.TEMPLATES:
            self.assertIn(f'"{uuid}" "/usr/share/nemo/actions"', hook)


if __name__ == "__main__":
    unittest.main()

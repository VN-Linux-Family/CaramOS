"""Translation checks for the Update Center, the Audit tool and update metadata."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from caramos_ota.i18n import localized, prefers_vietnamese, ui_language

ROOT = Path(__file__).parents[1]
DIST = ROOT / "usr/lib/python3/dist-packages"
PO = ROOT / "po/caramos-ota/vi.po"
POT = ROOT / "po/caramos-ota/caramos-ota.pot"
UI_SOURCES = [
    DIST / "caramos_ota_notifier/ui.py",
    DIST / "caramos_ota_notifier/app.py",
    DIST / "caramos_ota_notifier/state.py",
    DIST / "caramos_ota_audit/ui.py",
    DIST / "caramos_ota_audit/cli.py",
]
MIGRATIONS = DIST / "caramos_ota_update/migrations"
VIETNAMESE = re.compile(r"[À-ỹĐđ]")
TIMESTAMP_ID = re.compile(r"^\d{14}_[a-z0-9_]+$")


def msgids(path: Path) -> set[str]:
    """msgid values of a .po/.pot file (singular forms), unescaped."""

    ids: set[str] = set()
    current: list[str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines() + [""]:
        if line.startswith("msgid "):
            current = [line[6:]]
        elif current is not None and line.startswith('"'):
            current.append(line)
        else:
            if current is not None:
                text = "".join(ast.literal_eval(part) for part in current)
                if text:
                    ids.add(text)
            current = None
    return ids


def source_msgids(path: Path) -> set[str]:
    ids: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"_", "ngettext"}:
            first = node.args[0] if node.args else None
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                ids.add(first.value)
    return ids


class LanguageSelectionTests(unittest.TestCase):
    def test_language_follows_gettext_variable_order(self) -> None:
        self.assertEqual("vi", ui_language({"LANGUAGE": "vi_VN:vi", "LANG": "en_US.UTF-8"}))
        self.assertEqual("en", ui_language({"LANGUAGE": "en_US", "LC_ALL": "vi_VN.UTF-8"}))
        self.assertEqual("en", ui_language({"LANG": "en_US.UTF-8", "LC_TIME": "vi_VN"}))
        self.assertEqual("vi", ui_language({"LANG": "vi_VN"}))
        self.assertEqual("en", ui_language({"LC_ALL": "C.UTF-8", "LANG": "vi_VN.UTF-8"}))
        self.assertEqual("en", ui_language({}))

    def test_localized_falls_back_to_vietnamese_when_english_is_missing(self) -> None:
        en = {"LANG": "en_US.UTF-8"}
        vi = {"LANG": "vi_VN.UTF-8"}
        item = {"title": "Sửa lỗi", "title_en": "Fix bug", "summary": "Tóm tắt", "summary_en": ""}
        self.assertEqual("Fix bug", localized(item, "title", en))
        self.assertEqual("Sửa lỗi", localized(item, "title", vi))
        self.assertEqual("Tóm tắt", localized(item, "summary", en))
        self.assertTrue(prefers_vietnamese(vi))


class CatalogTests(unittest.TestCase):
    def test_sources_have_no_vietnamese_literals(self) -> None:
        for path in UI_SOURCES:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and VIETNAMESE.search(node.value):
                    self.fail(f"{path.name}:{node.lineno}: Vietnamese literal {node.value[:40]!r}; use _() with English")

    def test_every_source_msgid_is_translated(self) -> None:
        translated = msgids(PO)
        missing = sorted(set().union(*(source_msgids(path) for path in UI_SOURCES)) - translated)
        self.assertEqual([], missing, "add these to po/caramos-ota/vi.po (and regenerate the .pot)")

    def test_po_matches_template_and_compiles(self) -> None:
        self.assertEqual(msgids(POT), msgids(PO))
        if shutil.which("msgfmt") is None:
            self.skipTest("msgfmt not installed")
        subprocess.run(["msgfmt", "--check", "-o", os.devnull, str(PO)], check=True)

    def test_vietnamese_session_gets_the_old_wording(self) -> None:
        if shutil.which("msgfmt") is None:
            self.skipTest("msgfmt not installed")
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "vi/LC_MESSAGES"
            target.mkdir(parents=True)
            subprocess.run(["msgfmt", "-o", str(target / "caramos-ota.mo"), str(PO)], check=True)
            code = (
                "from caramos_ota.i18n import _, ngettext\n"
                "print(_('CaramOS - Update Center'))\n"
                "print(ngettext('%d change in this update', '%d changes in this update', 2) % 2)\n"
            )
            for language, expected in (
                ("vi_VN:vi", ["CaramOS - Trung tâm cập nhật", "Nội dung sẽ cập nhật (2)"]),
                ("en_US:en", ["CaramOS - Update Center", "2 changes in this update"]),
            ):
                env = dict(os.environ, CARAMOS_OTA_LOCALEDIR=tmp, LANGUAGE=language, PYTHONPATH=str(DIST))
                output = subprocess.run([sys.executable, "-c", code], env=env, check=True, capture_output=True, text=True)
                self.assertEqual(expected, output.stdout.splitlines())


class ManifestLanguageTests(unittest.TestCase):
    def test_timestamp_manifests_have_english_title_and_summary(self) -> None:
        for directory in sorted(MIGRATIONS.iterdir()):
            if not TIMESTAMP_ID.match(directory.name):
                continue
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            for key in ("title_en", "summary_en"):
                value = manifest.get(key, "")
                self.assertTrue(value.strip(), f"{directory.name}: missing {key}")
                self.assertIsNone(VIETNAMESE.search(value), f"{directory.name}: {key} is not English")

    def test_registry_and_saved_state_carry_both_languages(self) -> None:
        from caramos_ota_update.registry import discover_migrations

        locale_fix = {item.migration_id: item for item in discover_migrations()}["20261006090000_fix_forced_locale"]
        self.assertTrue(locale_fix.title_en)
        self.assertTrue(locale_fix.summary_en)
        apt_source = (DIST / "caramos_ota/apt.py").read_text(encoding="utf-8")
        state_source = (DIST / "caramos_ota_notifier/state.py").read_text(encoding="utf-8")
        for source in (apt_source, state_source):
            self.assertIn('"title_en": manifest.title_en', source)
            self.assertIn('"summary_en": manifest.summary_en', source)
        self.assertIn("name_en=item.title_en", apt_source)
        self.assertIn('"name_en": item.title_en', state_source)


class PackagingTests(unittest.TestCase):
    def test_catalogs_are_compiled_and_installed(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        control = (ROOT / "debian/control").read_text(encoding="utf-8")
        testkit = (ROOT / "tools/caramos-ota-testkit.sh").read_text(encoding="utf-8")
        self.assertIn("usr/share/locale usr/share/", install)
        self.assertRegex(control, r"Build-Depends:[^\n]*\n(?: [^\n]*\n)*? gettext,")
        self.assertIn('msgfmt --check --output-file="usr/share/locale/${lang}/LC_MESSAGES/${domain}.mo"', testkit)
        for domain in ("caramos-ota", "caramos-control-center"):
            self.assertTrue((ROOT / f"po/{domain}/vi.po").is_file(), domain)


if __name__ == "__main__":
    unittest.main()

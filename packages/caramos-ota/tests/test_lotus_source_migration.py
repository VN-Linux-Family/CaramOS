"""Migration 20261117100000_lotus_source_amd64_only: the Lotus package source asks for 64-bit packages only, so
`apt update` stops printing the i386 notice on Mint, which turns i386 on."""

from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).parents[1]
REPO = ROOT.parents[1]
HOOK = REPO / "config/hooks/live/0150-fcitx5-lotus.hook.chroot"
MIGRATION_DIR = ROOT / "usr/lib/python3/dist-packages/caramos_ota_update/migrations/20261117100000_lotus_source_amd64_only"

migration = importlib.import_module("caramos_ota_update.migrations.20261117100000_lotus_source_amd64_only.migration")

SHIPPED = ("deb [signed-by=/etc/apt/keyrings/fcitx5-lotus.gpg] https://fcitx5-lotus.pages.dev/apt/noble noble main\n")
FIXED = ("deb [arch=amd64 signed-by=/etc/apt/keyrings/fcitx5-lotus.gpg] https://fcitx5-lotus.pages.dev/apt/noble "
         "noble main\n")


class LotusSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "sources.list.d"
        self.dir.mkdir()
        patcher = mock.patch.object(migration, "SOURCES_DIR", self.dir)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_migration(self, dry_run: bool = False) -> None:
        with mock.patch("builtins.print"), mock.patch("caramos_ota_update.context.log_info"):
            migration.run(MigrationContext(dry_run=dry_run))

    def test_the_shipped_line_gets_amd64(self) -> None:
        path = self.dir / "fcitx5-lotus.list"
        path.write_text(SHIPPED, encoding="utf-8")
        self.run_migration()
        self.assertEqual(FIXED, path.read_text(encoding="utf-8"))
        self.run_migration()
        self.assertEqual(FIXED, path.read_text(encoding="utf-8"), "a second run changes nothing")

    def test_a_line_without_options_gets_them(self) -> None:
        path = self.dir / "lotus.list"
        path.write_text("deb https://fcitx5-lotus.pages.dev/apt/noble noble main\n", encoding="utf-8")
        self.run_migration()
        self.assertEqual("deb [arch=amd64] https://fcitx5-lotus.pages.dev/apt/noble noble main\n",
                         path.read_text(encoding="utf-8"))

    def test_architectures_already_named_are_kept(self) -> None:
        texts = {
            "a.list": "deb [arch=amd64,i386 signed-by=/k.gpg] https://fcitx5-lotus.pages.dev/apt/noble noble main\n",
            "b.list": "deb [ arch+=amd64 ] https://fcitx5-lotus.pages.dev/apt/noble noble main\n",
            "c.list": "# deb https://fcitx5-lotus.pages.dev/apt/noble noble main\n",
        }
        for name, text in texts.items():
            (self.dir / name).write_text(text, encoding="utf-8")
        self.run_migration()
        for name, text in texts.items():
            self.assertEqual(text, (self.dir / name).read_text(encoding="utf-8"), name)

    def test_only_the_lotus_lines_change(self) -> None:
        path = self.dir / "mixed.list"
        other = "deb [signed-by=/etc/apt/keyrings/other.gpg] https://example.org/apt noble main\n"
        path.write_text(other + SHIPPED + "deb-src https://fcitx5-lotus.pages.dev/apt/noble noble main",
                        encoding="utf-8")
        (self.dir / "official-package-repositories.list").write_text(
            "deb http://packages.linuxmint.com zena main upstream import backport\n", encoding="utf-8")
        self.run_migration()
        self.assertEqual(other + FIXED + "deb-src [arch=amd64] https://fcitx5-lotus.pages.dev/apt/noble noble main",
                         path.read_text(encoding="utf-8"))
        self.assertEqual("deb http://packages.linuxmint.com zena main upstream import backport\n",
                         (self.dir / "official-package-repositories.list").read_text(encoding="utf-8"))

    def test_a_deb822_stanza_gets_architectures(self) -> None:
        path = self.dir / "fcitx5-lotus.sources"
        lotus = ("Types: deb\nURIs: https://fcitx5-lotus.pages.dev/apt/noble\nSuites: noble\nComponents: main\n"
                 "Signed-By: /etc/apt/keyrings/fcitx5-lotus.gpg\n")
        other = "Types: deb\nURIs: https://example.org/apt\nSuites: noble\nComponents: main\n"
        path.write_text(lotus + "\n" + other, encoding="utf-8")
        self.run_migration()
        self.assertEqual(lotus + "Architectures: amd64\n\n" + other, path.read_text(encoding="utf-8"))
        named = self.dir / "named.sources"
        named.write_text(lotus.replace("Suites:", "Architectures: amd64 i386\nSuites:"), encoding="utf-8")
        before = named.read_text(encoding="utf-8")
        self.run_migration()
        self.assertEqual(before, named.read_text(encoding="utf-8"))

    def test_dry_run_and_no_sources_dir_change_nothing(self) -> None:
        path = self.dir / "fcitx5-lotus.list"
        path.write_text(SHIPPED, encoding="utf-8")
        self.run_migration(dry_run=True)
        self.assertEqual(SHIPPED, path.read_text(encoding="utf-8"))
        with mock.patch.object(migration, "SOURCES_DIR", self.dir / "missing"):
            self.run_migration()

    def test_manifest_texts(self) -> None:
        manifest = json.loads((MIGRATION_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(2, manifest["schema"])
        for key in ("title", "summary", "title_en", "summary_en", "size", "size_en"):
            self.assertTrue(manifest[key].strip(), key)
        self.assertTrue(manifest["release_notes_vi"] and manifest["release_notes_en"])


@unittest.skipUnless(HOOK.exists(), "the ISO hooks are not in the source package")
class LotusHookTests(unittest.TestCase):
    def test_the_iso_writes_the_fixed_line(self) -> None:
        hook = HOOK.read_text(encoding="utf-8")
        self.assertIn("deb [arch=amd64 signed-by=/etc/apt/keyrings/fcitx5-lotus.gpg] https://fcitx5-lotus.pages.dev",
                      hook)
        line = next(line for line in hook.splitlines() if line.startswith("printf 'deb "))
        written = line.split("'")[1].replace("%s", "noble").replace("\\n", "\n")
        self.assertEqual(FIXED, written)
        self.assertEqual(FIXED, migration.fix_one_line(written))


if __name__ == "__main__":
    unittest.main()

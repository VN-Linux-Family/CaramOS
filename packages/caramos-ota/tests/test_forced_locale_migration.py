"""Tests for removing the forced Vietnamese system locale (#65)."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from caramos_ota_update.context import MigrationContext

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "usr/lib/python3/dist-packages/caramos_ota_update/migrations"
    / "20261006090000_fix_forced_locale/migration.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("fix_forced_locale_test", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = load_migration()

# What the CaramOS hook wrote, and what the installer left after rewriting LANG.
ISO_LOCALE = "LANG=vi_VN.UTF-8\nLANGUAGE=vi_VN:vi\nLC_ALL=vi_VN.UTF-8\n"
INSTALLED_VI = 'LANG="vi_VN"\nLANGUAGE=vi_VN:vi\nLC_ALL=vi_VN.UTF-8\n'
INSTALLED_EN = "LANG=en_US.UTF-8\nLANGUAGE=vi_VN:vi\nLC_ALL=vi_VN.UTF-8\n"


class FixedContentTests(unittest.TestCase):
    def test_iso_file_keeps_vietnamese_but_drops_lc_all(self) -> None:
        self.assertEqual("LANG=vi_VN.UTF-8\nLANGUAGE=vi_VN:vi\n", migration.fixed_content(ISO_LOCALE))

    def test_installed_vietnamese_gets_a_codeset_mint_tools_recognise(self) -> None:
        self.assertEqual("LANG=vi_VN.UTF-8\nLANGUAGE=vi_VN:vi\n", migration.fixed_content(INSTALLED_VI))

    def test_english_install_no_longer_prefers_vietnamese_translations(self) -> None:
        self.assertEqual("LANG=en_US.UTF-8\nLANGUAGE=en_US:en\n", migration.fixed_content(INSTALLED_EN))

    def test_system_wide_choice_from_languages_tool_is_untouched(self) -> None:
        # What Settings > Languages > Apply System-Wide writes (mintlocale template).
        content = "LANG=en_US.UTF-8\nLANGUAGE=en_US:en\nLC_NUMERIC=vi_VN\nLC_TIME=vi_VN\n"
        self.assertEqual(content, migration.fixed_content(content))

    def test_other_lc_all_values_and_comments_are_kept(self) -> None:
        content = "# managed by admin\nLANG=de_DE.UTF-8\nLC_ALL=de_DE.UTF-8\n"
        self.assertEqual(content, migration.fixed_content(content))

    def test_c_locale_drops_the_vietnamese_language_list(self) -> None:
        self.assertEqual("LANG=C.UTF-8\n", migration.fixed_content("LANG=C.UTF-8\nLANGUAGE=vi_VN:vi\nLC_ALL=vi_VN.UTF-8\n"))


class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        (root / "etc/default").mkdir(parents=True)
        self.locale_conf = root / "etc/locale.conf"
        self.default_locale = root / "etc/default/locale"
        self.locale_conf.write_text(INSTALLED_VI, encoding="utf-8")
        self.locale_conf.chmod(0o644)
        # Mint 22: /etc/default/locale -> ../locale.conf
        self.default_locale.symlink_to(Path("../locale.conf"))
        patcher = patch.object(migration, "LOCALE_FILES", (self.locale_conf, self.default_locale))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_rewrites_the_real_file_once_and_keeps_the_symlink(self) -> None:
        migration.run(MigrationContext())

        self.assertEqual("LANG=vi_VN.UTF-8\nLANGUAGE=vi_VN:vi\n", self.locale_conf.read_text(encoding="utf-8"))
        self.assertTrue(self.default_locale.is_symlink())
        self.assertEqual(0o644, self.locale_conf.stat().st_mode & 0o777)

    def test_is_idempotent(self) -> None:
        migration.run(MigrationContext())
        first = self.locale_conf.read_text(encoding="utf-8")
        migration.run(MigrationContext())
        self.assertEqual(first, self.locale_conf.read_text(encoding="utf-8"))

    def test_dry_run_changes_nothing(self) -> None:
        migration.run(MigrationContext(dry_run=True))
        self.assertEqual(INSTALLED_VI, self.locale_conf.read_text(encoding="utf-8"))

    @unittest.skipUnless((Path(__file__).parents[3] / "config").is_dir(), "ISO tree is not in the source package")
    def test_iso_build_hook_and_overlay_no_longer_force_lc_all(self) -> None:
        repo = Path(__file__).parents[3]
        hook = (repo / "config/hooks/live/0100-caramos-setup.hook.chroot").read_text(encoding="utf-8")
        overlay = (repo / "config/includes.chroot/etc/default/locale").read_text(encoding="utf-8")
        self.assertNotIn("LC_ALL=", overlay)
        self.assertNotRegex(hook, r"(?m)^LC_ALL=")


if __name__ == "__main__":
    unittest.main()

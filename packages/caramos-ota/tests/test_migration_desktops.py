"""Migrations for one desktop: the Xfce edition skips the ones that change only Cinnamon.

A manifest may say "desktops": ["cinnamon"]; the runner then records the migration as done without running it on
another desktop, and the Update Center does not list its notes there. Without the field a migration runs on every
edition, as before."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update import desktop
from caramos_ota_update.registry import MigrationRegistryError, _descriptor, discover_migrations
from caramos_ota_update.runner import MigrationRunner

CINNAMON_ONLY = {
    "20260715090258_install_control_center", "20260803120000_apply_three_dock_taskbar",
    "20260804223346_change_default_wallpaper", "20260805111120_update_taskbar_pins_cleanup_desktop",
    "20261012180000_add_help_applet", "20261016220000_translate_cinnamon_spices",
    "20261018120000_restore_taskbar_after_cinnamon_update", "20261105120100_search_menu_while_composing",
    "20261105120200_start_menu_file_search_without_freeze", "20261111090000_start_menu_ctrl_scroll_icon_size",
    "20261112100000_screenshot_shortcuts", "v1_0_7", "v1_0_8", "v1_0_10",
}
XFCE_ONLY = {"20261118090100_xfce_wallpapers", "20261119100200_lighten_xfce_session"}
# Migrations that run on both editions although their code talks about Cinnamon, and why that is right on Xfce.
SHARED_ON_PURPOSE = {
    "20260808090000_restore_power_profiles_daemon": "power-profiles-daemon is a system service, not part of Cinnamon",
    "20261010120100_lighten_desktop_session": "its Cinnamon overrides go to /etc/xdg/xdg-cinnamon, which Xfce never reads",
    "20261022120000_start_fcitx_at_login": "Fcitx starts at login on both; it only looks for a running Cinnamon session",
    "20261117100100_nemo_actions_in_menu": "Nemo is the file manager of both editions",
    "v1_0_9": "Fcitx/Lotus setup for both; it only resets old Cinnamon keybinding experiments",
    "v1_0_12": "Fcitx/Lotus setup for both; it only resets old Cinnamon keybinding experiments",
}
PACKAGE = Path(__file__).resolve().parents[1]
MIGRATIONS = PACKAGE / "usr/lib/python3/dist-packages/caramos_ota_update/migrations"
REPO_CONFIG = Path(__file__).resolve().parents[3] / "config"


class DesktopDetectionTests(unittest.TestCase):
    def test_reads_the_session_binaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"CARAMOS_OTA_DESKTOP": ""}):
            root = Path(tmp)
            self.assertEqual("other", desktop.current_desktop(root))
            (root / "usr/bin").mkdir(parents=True)
            (root / "usr/bin/xfce4-session").touch()
            self.assertEqual("xfce", desktop.current_desktop(root))
            (root / "usr/bin/cinnamon").touch()
            self.assertEqual("cinnamon", desktop.current_desktop(root))

    def test_environment_override(self) -> None:
        with mock.patch.dict(os.environ, {"CARAMOS_OTA_DESKTOP": "xfce"}):
            self.assertEqual("xfce", desktop.current_desktop(Path("/nonexistent")))


class RegistryTests(unittest.TestCase):
    def test_the_cinnamon_only_migrations(self) -> None:
        catalog = discover_migrations()
        flagged = {item.migration_id: item.desktops for item in catalog if item.desktops}
        self.assertEqual(CINNAMON_ONLY, {key for key, value in flagged.items() if value == ("cinnamon",)},
                         "a new Cinnamon-only migration must say so in its manifest")
        self.assertEqual(XFCE_ONLY, {key for key, value in flagged.items() if value == ("xfce",)})
        for item in catalog:
            self.assertIn(item.desktops, ((), ("cinnamon",), ("xfce",)), item.migration_id)

    def test_unknown_desktop_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "20990101000000_example"
            directory.mkdir()
            (directory / "migration.py").write_text('DESCRIPTION = "x"\n\ndef run(context):\n    pass\n', encoding="utf-8")
            manifest = {"schema": 2, "codename": "noble", "channel": "stable", "desktops": ["kde"]}
            (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(MigrationRegistryError):
                _descriptor(directory)
            manifest["desktops"] = ["xfce"]
            (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(("xfce",), _descriptor(directory).desktops)


class EditionBoundaryTests(unittest.TestCase):
    """Every change says which edition it is for, so a Cinnamon fix never lands on Xfce by accident or the other way."""

    WORDS = {"cinnamon": re.compile(r"cinnamon|cinnamenu", re.I), "xfce": re.compile(r"xfce|xfconf|xfdesktop|xfwm", re.I)}

    def test_a_migration_about_one_desktop_says_so(self) -> None:
        catalog = {item.migration_id: item.desktops for item in discover_migrations()}
        for migration_id, desktops in sorted(catalog.items()):
            code = "\n".join(path.read_text(encoding="utf-8") for path in (MIGRATIONS / migration_id).rglob("*.py"))
            if desktops or migration_id in SHARED_ON_PURPOSE:
                continue
            for name, words in self.WORDS.items():
                if words.search(code):
                    self.fail(f"{migration_id} runs on both editions but talks about {name.capitalize()}: add "
                              f"\"desktops\": [\"{name}\"] to its manifest.json, or list it in SHARED_ON_PURPOSE with "
                              "the reason it is right on both")

    def test_the_shared_list_is_up_to_date(self) -> None:
        catalog = {item.migration_id: item.desktops for item in discover_migrations()}
        for migration_id, reason in SHARED_ON_PURPOSE.items():
            self.assertIn(migration_id, catalog)
            self.assertEqual((), catalog[migration_id], f"{migration_id} is flagged now: take it off SHARED_ON_PURPOSE")
            self.assertTrue(reason)

    def autostarts(self) -> list[Path]:
        # The package's own, which the source package built on Launchpad has without the repository's config/.
        files = sorted((PACKAGE / "etc/xdg/autostart").glob("*.desktop"))
        if REPO_CONFIG.is_dir():
            files += sorted(REPO_CONFIG.glob("includes.chroot*/etc/xdg/autostart/*.desktop"))
        return files

    def test_every_login_program_says_which_desktops(self) -> None:
        files = self.autostarts()
        self.assertTrue(files)
        for path in files:
            text = path.read_text(encoding="utf-8")
            shown = re.search(r"^OnlyShowIn=(.*)$", text, re.M)
            self.assertIsNotNone(shown, f"{path}: add OnlyShowIn=X-Cinnamon; or XFCE; or both")
            desktops = set(filter(None, shown.group(1).split(";")))
            self.assertTrue(desktops & {"X-Cinnamon", "XFCE"}, path)

    @unittest.skipUnless(REPO_CONFIG.is_dir(), "the source package has no config/")
    def test_the_xfce_overlay_only_starts_xfce_things(self) -> None:
        for path in REPO_CONFIG.glob("includes.chroot.xfce/etc/xdg/autostart/*.desktop"):
            shown = re.search(r"^OnlyShowIn=(.*)$", path.read_text(encoding="utf-8"), re.M).group(1)
            self.assertNotIn("X-Cinnamon", shown.split(";"), path)

    @unittest.skipUnless(REPO_CONFIG.is_dir(), "the source package has no config/")
    def test_fcitx_starts_once_on_xfce(self) -> None:
        # xfce4-session runs every autostart entry, even two that provide "inputmethod": with Fcitx's own entry and
        # the CaramOS helper both running "fcitx5 -d --replace", a login could end with no Fcitx at all.
        override = REPO_CONFIG / "includes.chroot.xfce/etc/xdg/caramos-xfce/autostart/org.fcitx.Fcitx5.desktop"
        entry = override.read_text(encoding="utf-8")
        self.assertIn("\nHidden=true\n", entry)
        self.assertIn("\nOnlyShowIn=XFCE;\n", entry)
        session = (REPO_CONFIG / "includes.chroot.xfce/etc/X11/Xsession.d/61caramos-xfce").read_text(encoding="utf-8")
        self.assertIn('XDG_CONFIG_DIRS="/etc/xdg/caramos-xfce${XDG_CONFIG_DIRS:+:$XDG_CONFIG_DIRS}"', session)
        hook = (REPO_CONFIG / "hooks/live/0150-fcitx5-lotus.hook.chroot").read_text(encoding="utf-8")
        helper = hook[hook.index("cat > /etc/xdg/autostart/caramos-fcitx5-lotus-enable.desktop"):]
        shown = re.search(r"^OnlyShowIn=(.*)$", helper, re.M).group(1).split(";")
        self.assertIn("XFCE", shown, "the helper must still start Fcitx on Xfce")

    @unittest.skipUnless(REPO_CONFIG.is_dir(), "the source package has no config/")
    def test_the_cinnamon_theme_applier_stays_off_xfce(self) -> None:
        entry = (REPO_CONFIG / "includes.chroot/etc/xdg/autostart/caramos-theme.desktop").read_text(encoding="utf-8")
        self.assertIn("OnlyShowIn=X-Cinnamon;\n", entry)


class RunnerTests(unittest.TestCase):
    def run_one(self, migration_id: str, desktop_name: str) -> bool:
        migration = next(item for item in discover_migrations() if item.migration_id == migration_id)
        runner = MigrationRunner.__new__(MigrationRunner)
        ran = []
        with mock.patch.dict(os.environ, {"CARAMOS_OTA_DESKTOP": desktop_name}), \
                mock.patch.object(MigrationRunner, "_load_module", lambda self, m: ran.append(m) or self), \
                mock.patch.object(MigrationRunner, "_validate_module", lambda *a: None), \
                mock.patch("caramos_ota_update.runner.log_info"):
            runner.run = lambda context: None
            runner.context = None
            runner._run_one(migration)
        return bool(ran)

    def test_cinnamon_migration_is_skipped_on_xfce(self) -> None:
        self.assertFalse(self.run_one("20260715090258_install_control_center", "xfce"))
        self.assertTrue(self.run_one("20260715090258_install_control_center", "cinnamon"))

    def test_an_unknown_desktop_runs_everything_as_before(self) -> None:
        # A package build or a chroot without a session: no edition is known, nothing is skipped.
        self.assertTrue(self.run_one("20260715090258_install_control_center", "other"))
        self.assertTrue(desktop.applies(("cinnamon",), "other"))
        self.assertFalse(desktop.applies(("cinnamon",), "xfce"))
        self.assertTrue(desktop.applies((), "xfce"))

    def test_xfce_wallpapers_only_on_xfce(self) -> None:
        self.assertTrue(self.run_one("20261118090100_xfce_wallpapers", "xfce"))
        self.assertFalse(self.run_one("20261118090100_xfce_wallpapers", "cinnamon"))

    def test_other_migrations_run_everywhere(self) -> None:
        self.assertTrue(self.run_one("20261118090000_files_new_menu", "xfce"))
        self.assertTrue(self.run_one("20261117100200_daily_wallpaper", "xfce"))


class UpdateCenterTests(unittest.TestCase):
    def test_xfce_does_not_list_cinnamon_notes(self) -> None:
        from caramos_ota.manifest import _manifest_from_descriptors
        from caramos_ota.models import ReleaseInfo

        catalog = {item.migration_id: item for item in discover_migrations()}
        pending = [catalog["20261112100000_screenshot_shortcuts"], catalog["20261118090000_files_new_menu"]]
        info = mock.Mock(spec=ReleaseInfo, version="1.3.11", codename="noble", channel="stable")
        with mock.patch.dict(os.environ, {"CARAMOS_OTA_DESKTOP": "xfce"}):
            manifest = _manifest_from_descriptors(pending, info, "1.4.0")
        self.assertTrue(manifest.release_notes_vi)
        self.assertTrue(all(note.startswith("20261118090000_files_new_menu") for note in manifest.release_notes_vi))
        with mock.patch.dict(os.environ, {"CARAMOS_OTA_DESKTOP": "cinnamon"}):
            manifest = _manifest_from_descriptors(pending, info, "1.4.0")
        self.assertTrue(any(note.startswith("20261112100000") for note in manifest.release_notes_vi))



class XfceWallpaperTests(unittest.TestCase):
    def migration(self):
        import importlib
        return importlib.import_module("caramos_ota_update.migrations.20261118090100_xfce_wallpapers.migration")

    def test_the_five_wallpapers_in_a_folder_of_their_own(self) -> None:
        migration = self.migration()
        context = mock.Mock(dry_run=False)
        with tempfile.TemporaryDirectory() as tmp:
            old = Path(tmp) / "caramos"          # also the boot splash pictures: not a folder to pick wallpapers in
            old.mkdir()
            (old / "default.png").write_bytes(b"the lotus drawing of the ISO")
            (old / "throbber-0001.png").write_bytes(b"a boot splash frame")
            folder = Path(tmp) / "CaramOS"
            migration.install(context, migration.PAYLOAD, folder, old / "default.png")
            self.assertEqual(sorted(path.name for path in migration.PAYLOAD.glob("*.jpg")),
                             sorted(path.name for path in folder.iterdir()), "only the five wallpapers")
            self.assertEqual("../CaramOS/03-sage-mist-2k.jpg", os.readlink(old / "default.png"))
            self.assertEqual((folder / "03-sage-mist-2k.jpg").read_bytes(), (old / "default.png").read_bytes())
            migration.install(context, migration.PAYLOAD, folder, old / "default.png")   # again: nothing to do
            self.assertEqual("../CaramOS/03-sage-mist-2k.jpg", os.readlink(old / "default.png"))
            empty = Path(tmp) / "empty"
            empty.mkdir()
            other = Path(tmp) / "other"
            migration.install(context, empty, other, other / "default.png")
            self.assertFalse(other.exists(), "no payload: nothing changes")

    @unittest.skipUnless((Path(__file__).resolve().parents[3] / "config").is_dir(), "the source package has no config/")
    def test_new_xfce_users_start_on_sage_mist_in_that_folder(self) -> None:
        migration = self.migration()
        desktop_xml = (Path(__file__).resolve().parents[3] / "config/includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4"
                       / "xfconf/xfce-perchannel-xml/xfce4-desktop.xml").read_text(encoding="utf-8")
        images = set(re.findall(r'name="(?:image-path|last-image|last-single-image)" type="string" value="([^"]+)"',
                                desktop_xml))
        self.assertEqual({str(migration.WALLPAPER_DIR / migration.DEFAULT_NAME)}, images)


class EditionNameTests(unittest.TestCase):
    def test_release_files_name_the_edition(self) -> None:
        from caramos_ota_update import version_metadata

        self.assertEqual("Xfce", version_metadata.edition_name("xfce"))
        self.assertEqual("Cinnamon", version_metadata.edition_name("cinnamon"))
        self.assertEqual("Cinnamon", version_metadata.edition_name("other"), "unknown: as before")
        with mock.patch.dict(os.environ, {"CARAMOS_OTA_DESKTOP": "xfce"}):
            self.assertIn('PRETTY_NAME="CaramOS 1.4.0 Xfce"', version_metadata.os_release_content("1.4.0"))
            self.assertIn('EDITION="Xfce"', version_metadata.linuxmint_info_content("1.4.0"))
            self.assertIn('DISTRIB_DESCRIPTION="CaramOS 1.4.0 Xfce"', version_metadata.lsb_release_content("1.4.0"))
        with mock.patch.dict(os.environ, {"CARAMOS_OTA_DESKTOP": "cinnamon"}):
            self.assertIn('PRETTY_NAME="CaramOS 1.4.0 Cinnamon"', version_metadata.os_release_content("1.4.0"))


if __name__ == "__main__":
    unittest.main()

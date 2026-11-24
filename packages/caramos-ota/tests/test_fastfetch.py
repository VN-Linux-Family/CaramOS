"""fastfetch with the CaramOS logo on both editions (ticket H-1203): migration 20261124130000_install_fastfetch, and
the ISO side (the PPA package comes from the migration, not from config/packages.txt or hook 0200)."""

from __future__ import annotations

import importlib
import json
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext, MigrationContextError

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
MIGRATION_ID = "20261124130000_install_fastfetch"
migration = importlib.import_module(f"caramos_ota_update.migrations.{MIGRATION_ID}.migration")
MANIFEST = Path(migration.__file__).parent / "manifest.json"


class FastfetchMigrationTests(unittest.TestCase):
    def run_migration(self, *, installed: bool, apt_error: Exception | None = None) -> tuple[list, list]:
        context = MigrationContext()
        logged: list[str] = []

        def run_command(args, allow_fail=False, env=None):  # noqa: ANN001, ANN202
            self.assertEqual(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", "fastfetch"], list(args))
            return subprocess.CompletedProcess(args, 0 if installed else 1, "ii " if installed else "", "")

        apt = mock.Mock(side_effect=apt_error)
        with mock.patch.object(context, "run_command", side_effect=run_command), \
                mock.patch.object(context, "apt_install", apt), \
                mock.patch.object(context, "log", side_effect=logged.append):
            migration.run(context)
        return apt.call_args_list, logged

    def test_installs_fastfetch_without_recommends(self) -> None:
        calls, _logged = self.run_migration(installed=False)
        self.assertEqual([mock.call(["fastfetch"], recommends=False)], calls)

    def test_leaves_an_installed_fastfetch_alone(self) -> None:
        # One the user installed from elsewhere (GitHub, another PPA) included.
        calls, logged = self.run_migration(installed=True)
        self.assertEqual([], calls)
        self.assertIn("fastfetch is installed", logged)

    def test_a_failed_install_is_logged_and_the_update_goes_on(self) -> None:
        calls, logged = self.run_migration(installed=False, apt_error=MigrationContextError("offline"))
        self.assertEqual(1, len(calls))
        self.assertTrue(any(line.startswith("could not install fastfetch (offline)") for line in logged), logged)

    def test_dry_run_changes_nothing(self) -> None:
        context = MigrationContext(dry_run=True)
        with mock.patch("caramos_ota_update.context.subprocess.run") as run, mock.patch("builtins.print"), \
                mock.patch("caramos_ota_update.context.log_info"):
            migration.run(context)
        run.assert_not_called()

    def test_manifest(self) -> None:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(2, manifest["schema"])
        # Installing a package changes nothing on the screen of someone at work.
        self.assertEqual("anytime", manifest["unattended"])
        self.assertNotIn("desktops", manifest, "both editions")
        for key in ("release", "version", "from_version", "to_version"):
            self.assertNotIn(key, manifest)
        for key in ("title", "summary", "size"):
            self.assertTrue(manifest[key])
            self.assertTrue(manifest[f"{key}_en"])
        self.assertIn("fastfetch", manifest["size"])
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))


@unittest.skipUnless((REPO / "config").is_dir(), "the source package has no config/")
class FastfetchIsoTests(unittest.TestCase):
    def test_not_in_the_package_lists(self) -> None:
        # config/packages*.txt are installed before the CaramOS PPA is in the image, so fastfetch would not be found.
        for path in sorted((REPO / "config").glob("packages*.txt")):
            names = [line.split("#")[0].strip() for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertNotIn("fastfetch", names, path.name)

    def test_debrand_hook_wraps_neofetch_only(self) -> None:
        # The package's /etc/xdg/fastfetch/config.jsonc shows the CaramOS logo; a /usr/local/bin/fastfetch wrapper with
        # --logo would replace it with the neofetch logo file.
        hook = (REPO / "config/hooks/live/0200-caramos-debrand.hook.chroot").read_text(encoding="utf-8")
        self.assertIn("cat > /usr/local/bin/neofetch", hook)
        self.assertNotIn("/usr/local/bin/fastfetch", hook)
        self.assertNotIn("/usr/bin/fastfetch", hook)

    def test_iso_build_stops_without_fastfetch(self) -> None:
        customize = (REPO / "scripts/customize.sh").read_text(encoding="utf-8")
        check = customize.index("command -v fastfetch")
        self.assertLess(customize.index("step_ota_bootstrap"), check, "after the migrations ran")
        self.assertLess(check, customize.index("date -u"), "before the image is marked as customized")


if __name__ == "__main__":
    unittest.main()

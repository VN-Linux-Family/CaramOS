"""Migration 20261125120100_veyon_lock_and_demo_show: Veyon from the CaramOS PPA, whose Lock and full-screen Demo show
on the students' computers and whose server comes back by itself (packages/veyon)."""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext, MigrationContextError

migration = importlib.import_module("caramos_ota_update.migrations.20261125120100_veyon_lock_and_demo_show.migration")
UBUNTU = "4.7.5+repack1-1ubuntu5"
PACKAGE_DIR = Path(__file__).parents[2] / "veyon"


class FakeContext(MigrationContext):
    """Answers dpkg-query and apt-mark from a table; compares versions with the real dpkg."""

    def __init__(self, versions: dict[str, str], auto: tuple[str, ...] = (), apt_error: str = "",
                 after: str = "") -> None:
        super().__init__()
        self.versions = dict(versions)
        self.auto = set(auto)
        self.apt_error = apt_error
        self.after = after
        self.commands: list[list[str]] = []
        self.installed: tuple | None = None
        self.logs: list[str] = []

    def log(self, message: str) -> None:
        self.logs.append(message)

    def run_command(self, args, *, allow_fail=False, env=None):  # noqa: ANN001, ANN201 - the context's signature
        args = [str(part) for part in args]
        self.commands.append(args)
        if args[0] == "dpkg-query":
            version = self.versions.get(args[-1], "")
            return subprocess.CompletedProcess(args, 0 if version else 1, f"ii {version}" if version else "", "")
        if args[:2] == ["dpkg", "--compare-versions"]:
            return subprocess.CompletedProcess(args, subprocess.run(args, check=False).returncode, "", "")
        if args[:2] == ["apt-mark", "showauto"]:
            return subprocess.CompletedProcess(args, 0, "\n".join(p for p in args[2:] if p in self.auto), "")
        if args[:2] == ["apt-mark", "auto"]:
            return subprocess.CompletedProcess(args, 0, "", "")
        raise AssertionError(f"unexpected command {args}")

    def apt_install(self, packages, *, recommends=True, only_upgrade=False):  # noqa: ANN001, ANN201
        self.installed = (list(packages), recommends, only_upgrade)
        if self.apt_error:
            raise MigrationContextError(self.apt_error)
        if self.after:
            for package in packages:
                self.versions[package] = self.after


def needs_dpkg(test: unittest.TestCase) -> None:
    if not shutil.which("dpkg"):
        test.skipTest("dpkg is unavailable")


class RunTests(unittest.TestCase):
    def test_without_veyon(self) -> None:
        context = FakeContext({})
        migration.run(context)
        self.assertIsNone(context.installed)
        self.assertIn("no Veyon here", context.logs[-1])

    def test_the_fixed_version_or_a_newer_one_stays(self) -> None:
        needs_dpkg(self)
        for version in (migration.FIXED_VERSION, "4.7.5+repack1-1ubuntu5.1", "4.9.7-1"):
            context = FakeContext({"libveyon-core": version, "veyon-service": version})
            migration.run(context)
            self.assertIsNone(context.installed, version)

    def test_upgrades_the_installed_veyon_packages_only(self) -> None:
        needs_dpkg(self)
        student = {"libveyon-core": UBUNTU, "veyon-plugins": UBUNTU, "veyon-service": UBUNTU}
        context = FakeContext(student, auto=("libveyon-core", "veyon-plugins"), after=migration.FIXED_VERSION)
        migration.run(context)
        packages, recommends, only_upgrade = context.installed
        self.assertEqual(["libveyon-core", "veyon-plugins", "veyon-service"], packages, "no Veyon Master on a student")
        self.assertFalse(recommends)
        self.assertTrue(only_upgrade)
        self.assertIn(["apt-mark", "auto", "libveyon-core", "veyon-plugins"], context.commands)
        self.assertIn("Lock and full-screen Demo show", context.logs[-1])

    def test_an_apt_failure_is_logged_and_the_marks_come_back(self) -> None:
        needs_dpkg(self)
        context = FakeContext({"libveyon-core": UBUNTU}, auto=("libveyon-core",), apt_error="exit code 100")
        migration.run(context)  # does not raise: the rest of the update goes on
        self.assertIn("could not upgrade Veyon", context.logs[-1])
        self.assertIn(["apt-mark", "auto", "libveyon-core"], context.commands)

    def test_a_ppa_without_the_package_yet_is_a_warning(self) -> None:
        needs_dpkg(self)
        context = FakeContext({"libveyon-core": UBUNTU})
        migration.run(context)
        self.assertTrue(context.logs[-1].startswith("warning:"), context.logs[-1])

    def test_a_dry_run_changes_nothing(self) -> None:
        context = MigrationContext(dry_run=True)
        with mock.patch.object(MigrationContext, "log"), mock.patch.object(MigrationContext, "apt_install") as apt:
            migration.run(context)
        apt.assert_not_called()

    def test_the_version_is_the_one_packages_veyon_builds(self) -> None:
        self.assertIn(migration.CORE_PACKAGE, migration.PACKAGES)
        makefile = PACKAGE_DIR / "Makefile"
        if not makefile.exists():
            self.skipTest("packages/veyon is not next to this package")
        text = makefile.read_text(encoding="utf-8")
        self.assertIn(f"VERSION := {migration.FIXED_VERSION}\n", text)
        for patch in ("caramos-lockwidget-show-after-raise.patch", "caramos-restart-crashed-server.patch",
                      "caramos-restart-server-after-session-closes.patch"):
            self.assertIn(patch, text)
            self.assertTrue((PACKAGE_DIR / "patches" / patch).is_file(), patch)

    def test_the_lock_patch_shows_the_window_after_raising_it(self) -> None:
        patch = PACKAGE_DIR / "patches/caramos-lockwidget-show-after-raise.patch"
        if not patch.exists():
            self.skipTest("packages/veyon is not next to this package")
        added = [line[1:].strip() for line in patch.read_text(encoding="utf-8").splitlines()
                 if line.startswith("+") and not line.startswith("+++")]
        self.assertEqual("showFullScreen();", added[added.index("#ifdef Q_OS_LINUX", 3) + 1],
                         "full screen again after raiseWindow() hid the window")

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("desktops", manifest)
        self.assertEqual("anytime", manifest["unattended"], "a no-op outside labs: must not hold back updates")
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))


if __name__ == "__main__":
    unittest.main()

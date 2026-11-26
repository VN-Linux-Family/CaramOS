"""Migration 20261126120000_computer_lab_veyon_4_11: the Veyon packages a lab computer has go up to Veyon 4.11.5 from
the CaramOS PPA (packages/veyon/4.11)."""

from __future__ import annotations

import importlib
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext, MigrationContextError

migration = importlib.import_module("caramos_ota_update.migrations.20261126120000_computer_lab_veyon_4_11.migration")
previous = importlib.import_module("caramos_ota_update.migrations.20261125120100_veyon_lock_and_demo_show.migration")
UBUNTU = "4.7.5+repack1-1ubuntu5"
CARAMOS_475 = previous.FIXED_VERSION
RECIPE = Path(__file__).parents[2] / "veyon" / "4.11"


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

    def test_veyon_4_11_5_or_newer_stays(self) -> None:
        needs_dpkg(self)
        for version in (migration.VERSION, "4.11.5+repack1-0caramos2", "4.12.0-1"):
            context = FakeContext({"libveyon-core": version, "veyon-service": version})
            migration.run(context)
            self.assertIsNone(context.installed, version)

    def test_a_student_computer_upgrades_its_veyon_packages_only(self) -> None:
        needs_dpkg(self)
        for old in (CARAMOS_475, UBUNTU):
            student = {"libveyon-core": old, "veyon-plugins": old, "veyon-service": old}
            context = FakeContext(student, auto=("libveyon-core", "veyon-plugins"), after=migration.VERSION)
            migration.run(context)
            packages, recommends, only_upgrade = context.installed
            self.assertEqual(["libveyon-core", "veyon-plugins", "veyon-service"], packages,
                             "no Veyon Master on a student's computer")
            self.assertFalse(recommends)
            self.assertTrue(only_upgrade)
            self.assertIn(["apt-mark", "auto", "libveyon-core", "veyon-plugins"], context.commands)
            self.assertIn("Veyon 4.11.5", context.logs[-1])

    def test_a_teacher_computer_upgrades_all_five(self) -> None:
        needs_dpkg(self)
        teacher = {package: CARAMOS_475 for package in migration.PACKAGES}
        context = FakeContext(teacher, after=migration.VERSION)
        migration.run(context)
        self.assertEqual(list(migration.PACKAGES), context.installed[0])
        self.assertNotIn("auto", [c[1] for c in context.commands if c[0] == "apt-mark"], "nothing was automatic")

    def test_an_apt_failure_is_logged_and_the_marks_come_back(self) -> None:
        needs_dpkg(self)
        context = FakeContext({"libveyon-core": CARAMOS_475}, auto=("libveyon-core",), apt_error="exit code 100")
        migration.run(context)  # does not raise: the rest of the update goes on
        self.assertIn("could not upgrade Veyon", context.logs[-1])
        self.assertIn(["apt-mark", "auto", "libveyon-core"], context.commands)

    def test_a_ppa_without_the_package_yet_is_a_warning(self) -> None:
        needs_dpkg(self)
        context = FakeContext({"libveyon-core": CARAMOS_475})
        migration.run(context)
        self.assertTrue(context.logs[-1].startswith("warning:"), context.logs[-1])

    def test_a_dry_run_changes_nothing(self) -> None:
        context = MigrationContext(dry_run=True)
        with mock.patch.object(MigrationContext, "log"), mock.patch.object(MigrationContext, "apt_install") as apt:
            migration.run(context)
        apt.assert_not_called()


class PackagingTests(unittest.TestCase):
    def test_the_same_packages_as_the_4_7_5_upgrade(self) -> None:
        self.assertEqual(previous.PACKAGES, migration.PACKAGES)
        self.assertIn(migration.CORE_PACKAGE, migration.PACKAGES)

    def test_runs_after_the_4_7_5_upgrade(self) -> None:
        # A computer still on 1.5.1 runs both; the older one then already installs the PPA's newest Veyon.
        self.assertGreater(migration.__name__.split(".")[-2], previous.__name__.split(".")[-2])

    def test_packages_veyon_4_11_builds_this_version_or_a_newer_one(self) -> None:
        # The daily check (.github/workflows/veyon-upstream.yml) moves the recipe to newer Veyon releases. A recipe
        # older than VERSION would leave every lab computer with the warning.
        needs_dpkg(self)
        changelog = RECIPE / "debian" / "changelog"
        if not changelog.exists():
            self.skipTest("packages/veyon/4.11 is not next to this package")
        first = changelog.read_text(encoding="utf-8").splitlines()[0]
        recipe = re.match(r"veyon \(([^)]+)\) noble;", first).group(1)
        result = subprocess.run(["dpkg", "--compare-versions", recipe, "ge", migration.VERSION], check=False)
        self.assertEqual(0, result.returncode, f"packages/veyon/4.11 builds {recipe}, older than {migration.VERSION}")

    def test_newer_than_every_4_7_5(self) -> None:
        needs_dpkg(self)
        for old in (UBUNTU, CARAMOS_475, "4.9.7+repack1-1"):
            result = subprocess.run(["dpkg", "--compare-versions", migration.VERSION, "gt", old], check=False)
            self.assertEqual(0, result.returncode, old)

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("desktops", manifest)
        self.assertEqual("anytime", manifest["unattended"], "a no-op outside labs: must not hold back updates")
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertIn("4.11.5", manifest["title"])


if __name__ == "__main__":
    unittest.main()

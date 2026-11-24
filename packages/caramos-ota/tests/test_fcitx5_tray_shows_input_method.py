"""Migration 20261125090000_fcitx5_tray_shows_input_method: fcitx5 from the CaramOS PPA, whose tray shows the input
method in use (Lotus's V) from the login on."""

from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext, MigrationContextError

migration = importlib.import_module(
    "caramos_ota_update.migrations.20261125090000_fcitx5_tray_shows_input_method.migration")
UBUNTU = "5.1.7-1build3"


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
            self.versions["fcitx5-modules"] = self.after


def needs_dpkg(test: unittest.TestCase) -> None:
    if not shutil.which("dpkg"):
        test.skipTest("dpkg is unavailable")


class RunTests(unittest.TestCase):
    def test_without_fcitx5(self) -> None:
        context = FakeContext({})
        migration.run(context)
        self.assertIsNone(context.installed)
        self.assertIn("not installed", context.logs[-1])

    def test_the_fixed_version_or_a_newer_one_stays(self) -> None:
        needs_dpkg(self)
        for version in (migration.FIXED_VERSION, "5.1.7-1ubuntu0.1", "5.1.8-1"):
            context = FakeContext({"fcitx5": version, "fcitx5-modules": version})
            migration.run(context)
            self.assertIsNone(context.installed, version)

    def test_upgrades_the_installed_fcitx5_packages_only(self) -> None:
        needs_dpkg(self)
        versions = {"fcitx5": UBUNTU, "fcitx5-data": UBUNTU, "fcitx5-modules": UBUNTU, "libfcitx5core7": UBUNTU}
        context = FakeContext(versions, auto=("fcitx5-data", "libfcitx5core7"), after=migration.FIXED_VERSION)
        migration.run(context)
        packages, recommends, only_upgrade = context.installed
        self.assertEqual(["fcitx5", "fcitx5-data", "fcitx5-modules", "libfcitx5core7"], packages)
        self.assertFalse(recommends)
        self.assertTrue(only_upgrade)
        self.assertIn(["apt-mark", "auto", "fcitx5-data", "libfcitx5core7"], context.commands)
        self.assertIn("next login", context.logs[-1])

    def test_an_apt_failure_is_logged_and_the_marks_come_back(self) -> None:
        needs_dpkg(self)
        context = FakeContext({"fcitx5-modules": UBUNTU}, auto=("fcitx5-modules",), apt_error="exit code 100")
        migration.run(context)  # does not raise: the rest of the update goes on
        self.assertIn("could not upgrade fcitx5", context.logs[-1])
        self.assertIn(["apt-mark", "auto", "fcitx5-modules"], context.commands)

    def test_a_ppa_without_the_package_yet_is_a_warning(self) -> None:
        needs_dpkg(self)
        context = FakeContext({"fcitx5-modules": UBUNTU})
        migration.run(context)
        self.assertTrue(context.logs[-1].startswith("warning:"), context.logs[-1])
        self.assertNotIn(["apt-mark", "auto"], [command[:2] for command in context.commands])

    def test_a_dry_run_changes_nothing(self) -> None:
        context = MigrationContext(dry_run=True)
        with mock.patch.object(MigrationContext, "log"), mock.patch.object(MigrationContext, "apt_install") as apt:
            migration.run(context)
        apt.assert_not_called()

    def test_apt_get_only_upgrades(self) -> None:
        with mock.patch.object(MigrationContext, "_apt_get") as apt:
            MigrationContext().apt_install(["fcitx5-modules"], recommends=False, only_upgrade=True)
        apt.assert_called_once_with("install", "--yes", "--no-install-recommends", "--only-upgrade", "--",
                                    "fcitx5-modules")

    def test_the_packages_are_the_fcitx5_source_ones(self) -> None:
        self.assertIn(migration.TRAY_PACKAGE, migration.PACKAGES)
        makefile = (Path(__file__).parents[2] / "fcitx5" / "Makefile")
        if not makefile.exists():
            self.skipTest("packages/fcitx5 is not next to this package")
        self.assertIn(f"VERSION := {migration.FIXED_VERSION}\n", makefile.read_text(encoding="utf-8"))

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(["cinnamon"], manifest["desktops"])
        self.assertEqual("anytime", manifest["unattended"])  # fcitx5 keeps running on the old code until the login
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertIn("đăng nhập sau", manifest["release_notes_vi"][-1])


if __name__ == "__main__":
    unittest.main()

"""Tests for installing Zalo from VN-Linux-Family/zalo-for-linux on new ISOs and installed machines."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from caramos_ota_update.context import MigrationContext, MigrationContextError

ROOT = Path(__file__).parents[3]
MIGRATION_DIR = (
    Path(__file__).parents[1]
    / "usr/lib/python3/dist-packages/caramos_ota_update/migrations"
    / "20261005110000_update_zalo_appimage"
)
HOOK = ROOT / "config/hooks/live/0300-zalo-unoffical.hook.chroot"


def load_migration():
    spec = importlib.util.spec_from_file_location("update_zalo_appimage_test", MIGRATION_DIR / "migration.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = load_migration()

OLD = b"zalo 26.5.10 shipped by CaramOS"
NEW = b"zalo 26.10.10 from VN-Linux-Family"
REBUILT = b"zalo 26.10.10 rebuilt upstream"
USER = b"zalo the user installed"
REBUILT_NAME = "Zalo-26.10.10+ZaDark-26.2.1-abc1234-x86_64.AppImage"

# Asset names as release 26.10.10 lists them, all flavours and architectures.
RELEASE_ASSET_NAMES = (
    "Zalo-26.10.10+ZaDark-26.2.1-ed91566-aarch64.AppImage",
    "Zalo-26.10.10+ZaDark-26.2.1-ed91566-aarch64.AppImage.zsync",
    "Zalo-26.10.10+ZaDark-26.2.1-ed91566-Full-x86_64.AppImage",
    "Zalo-26.10.10+ZaDark-26.2.1-ed91566-Full-x86_64.AppImage.zsync",
    "Zalo-26.10.10+ZaDark-26.2.1-ed91566-x86_64.AppImage",
    "Zalo-26.10.10+ZaDark-26.2.1-ed91566-x86_64.AppImage.zsync",
    "Zalo-26.10.10-Original-ed91566-aarch64.AppImage",
    "Zalo-26.10.10-Original-ed91566-Full-x86_64.AppImage",
    "Zalo-26.10.10-Original-ed91566-x86_64.AppImage",
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def api_asset(name: str, data: bytes) -> dict:
    return {
        "name": name,
        "size": len(data),
        "digest": f"sha256:{sha(data)}",
        "browser_download_url": migration.release_download_url(name),
    }


class FakeGitHub:
    """Serves release URLs from a dict; a missing URL is a 404 and an exception value is raised."""

    def __init__(self, responses: dict) -> None:
        self.responses = responses
        self.requests: list[str] = []

    def __call__(self, url: str, accept: str | None = None):
        self.requests.append(url)
        value = self.responses.get(url)
        if value is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if isinstance(value, list):
            value = value.pop(0)
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(value)


class PlanActionTests(unittest.TestCase):
    def test_actions(self) -> None:
        old = next(iter(migration.CARAMOS_BUILDS))
        cases = [
            ((None, False, {}), "absent"),
            ((None, True, {}), "install"),
            ((migration.ASSET_SHA256, True, {}), "current"),
            ((old, True, {}), "replace"),
            ((old, False, {}), "replace"),
            ((sha(USER), True, {}), "user"),
            # A rebuilt asset this migration installed earlier.
            ((sha(REBUILT), True, {"tag": migration.RELEASE_TAG, "sha256": sha(REBUILT)}), "current"),
            # A Zalo an older CaramOS migration installed.
            ((sha(REBUILT), True, {"tag": "26.9.10", "sha256": sha(REBUILT)}), "replace"),
        ]
        for args, expected in cases:
            with self.subTest(args=args):
                self.assertEqual(expected, migration.plan_action(*args))


class ReleaseAssetTests(unittest.TestCase):
    def test_pinned_asset_is_the_zadark_x86_64_build_of_the_tag(self) -> None:
        self.assertTrue(migration.ASSET_PATTERN.fullmatch(migration.ASSET_NAME))
        self.assertEqual(
            "https://github.com/VN-Linux-Family/zalo-for-linux/releases/download/26.10.10/"
            "Zalo-26.10.10%2BZaDark-26.2.1-ed91566-x86_64.AppImage",
            migration.PINNED_ASSET.url,
        )
        self.assertRegex(migration.ASSET_SHA256, r"^[0-9a-f]{64}$")

    def test_pattern_picks_only_the_same_flavour(self) -> None:
        matched = [name for name in RELEASE_ASSET_NAMES if migration.ASSET_PATTERN.fullmatch(name)]
        self.assertEqual(["Zalo-26.10.10+ZaDark-26.2.1-ed91566-x86_64.AppImage"], matched)
        self.assertTrue(migration.ASSET_PATTERN.fullmatch(REBUILT_NAME))
        self.assertFalse(migration.ASSET_PATTERN.fullmatch("Zalo-26.9.10+ZaDark-26.2.1-8ec7c5b-x86_64.AppImage"))

    def test_hook_writes_only_the_launcher_for_the_migration(self) -> None:
        source = HOOK.read_text(encoding="utf-8")
        self.assertIn('APPIMAGE_PATH="$INSTALL_DIR/Zalo.AppImage"', source)
        self.assertIn("Exec=$APPIMAGE_PATH", source)
        self.assertEqual(Path("/usr/local/bin/Zalo.AppImage"), migration.ZALO_APPIMAGE)
        self.assertNotIn("zalo-for-linux/releases", source)
        self.assertNotIn("hthienloc", source)
        self.assertIn(MIGRATION_DIR.name, source)


class ZaloMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.bin = root / "usr/local/bin"
        self.bin.mkdir(parents=True)
        self.appimage = self.bin / "Zalo.AppImage"
        self.launcher = root / "zalo.desktop"
        self.state = root / "var/lib/caramos-ota/zalo-appimage.json"
        self.launcher.write_text(
            f"[Desktop Entry]\nName=Zalo\nExec={self.appimage}\n", encoding="utf-8"
        )
        pinned = migration.Asset(migration.ASSET_NAME, migration.PINNED_ASSET.url, sha(NEW), len(NEW))
        self.api_url = f"https://api.github.com/repos/{migration.REPOSITORY}/releases/tags/{migration.RELEASE_TAG}"
        self.github = FakeGitHub({pinned.url: NEW})
        self.sleeps: list[float] = []
        for name, value in {
            "ZALO_APPIMAGE": self.appimage,
            "ZALO_LAUNCHER": self.launcher,
            "STATE_FILE": self.state,
            "ASSET_SHA256": sha(NEW),
            "ASSET_SIZE": len(NEW),
            "PINNED_ASSET": pinned,
            "CARAMOS_BUILDS": {sha(OLD): "26.5.10 (test)"},
            "_open": self.github,
        }.items():
            patcher = patch.object(migration, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for patcher in (
            patch.object(migration.time, "sleep", self.sleeps.append),
            patch("caramos_ota_update.context.log_info"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_appimage(self, data: bytes) -> None:
        self.appimage.write_bytes(data)
        self.appimage.chmod(0o755)

    def run_migration(self, dry_run: bool = False) -> None:
        with patch("builtins.print"):
            migration.run(MigrationContext(dry_run=dry_run))

    def assert_installed(self, data: bytes, asset_name: str) -> None:
        self.assertEqual(data, self.appimage.read_bytes())
        self.assertEqual(0o755, self.appimage.stat().st_mode & 0o7777)
        self.assertEqual(
            {
                "repository": "VN-Linux-Family/zalo-for-linux",
                "tag": migration.RELEASE_TAG,
                "asset": asset_name,
                "sha256": sha(data),
            },
            json.loads(self.state.read_text(encoding="utf-8")),
        )
        self.assertEqual(["Zalo.AppImage"], sorted(path.name for path in self.bin.iterdir()))

    def test_replaces_the_zalo_caramos_shipped(self) -> None:
        self.write_appimage(OLD)

        self.run_migration()

        self.assert_installed(NEW, migration.ASSET_NAME)

    def test_installs_for_the_iso_launcher_without_appimage(self) -> None:
        self.run_migration()

        self.assert_installed(NEW, migration.ASSET_NAME)

    def test_is_idempotent(self) -> None:
        self.write_appimage(OLD)
        self.run_migration()
        self.github.requests.clear()

        self.run_migration()

        self.assertEqual([], self.github.requests)
        self.assert_installed(NEW, migration.ASSET_NAME)

    def test_leaves_a_user_installed_zalo_alone(self) -> None:
        self.write_appimage(USER)

        self.run_migration()

        self.assertEqual(USER, self.appimage.read_bytes())
        self.assertEqual([], self.github.requests)
        self.assertFalse(self.state.exists())

    def test_leaves_a_symlinked_zalo_alone(self) -> None:
        target = self.bin.parent / "zalo-from-elsewhere"
        target.write_bytes(OLD)
        self.appimage.symlink_to(target)

        self.run_migration()

        self.assertTrue(self.appimage.is_symlink())
        self.assertEqual([], self.github.requests)

    def test_does_nothing_when_zalo_was_removed(self) -> None:
        self.launcher.unlink()

        self.run_migration()

        self.assertFalse(self.appimage.exists())
        self.assertEqual([], self.github.requests)

    def test_dry_run_downloads_nothing(self) -> None:
        self.write_appimage(OLD)

        self.run_migration(dry_run=True)

        self.assertEqual(OLD, self.appimage.read_bytes())
        self.assertEqual([], self.github.requests)
        self.assertFalse(self.state.exists())

    def test_uses_the_rebuilt_asset_of_the_same_tag_when_the_pinned_one_is_gone(self) -> None:
        self.write_appimage(OLD)
        del self.github.responses[migration.PINNED_ASSET.url]
        release = {"assets": [api_asset(name, b"other") for name in RELEASE_ASSET_NAMES if "ed91566-x86_64" not in name]}
        release["assets"].append(api_asset(REBUILT_NAME, REBUILT))
        self.github.responses[self.api_url] = json.dumps(release).encode()
        self.github.responses[migration.release_download_url(REBUILT_NAME)] = REBUILT

        self.run_migration()

        self.assert_installed(REBUILT, REBUILT_NAME)

    def test_refuses_a_rebuilt_asset_without_a_sha256(self) -> None:
        self.write_appimage(OLD)
        del self.github.responses[migration.PINNED_ASSET.url]
        asset = api_asset(REBUILT_NAME, REBUILT)
        del asset["digest"]
        self.github.responses[self.api_url] = json.dumps({"assets": [asset]}).encode()
        self.github.responses[migration.release_download_url(REBUILT_NAME)] = REBUILT

        with self.assertRaisesRegex(MigrationContextError, "could not download Zalo"):
            self.run_migration()

        self.assertEqual(OLD, self.appimage.read_bytes())
        self.assertNotIn(migration.release_download_url(REBUILT_NAME), self.github.requests)

    def test_refuses_a_download_outside_the_release(self) -> None:
        self.write_appimage(OLD)
        del self.github.responses[migration.PINNED_ASSET.url]
        asset = api_asset(REBUILT_NAME, REBUILT)
        asset["browser_download_url"] = "https://example.com/Zalo.AppImage"
        self.github.responses[self.api_url] = json.dumps({"assets": [asset]}).encode()

        with self.assertRaisesRegex(MigrationContextError, "could not download Zalo"):
            self.run_migration()

        self.assertNotIn("https://example.com/Zalo.AppImage", self.github.requests)

    def test_retries_a_dropped_connection(self) -> None:
        self.write_appimage(OLD)
        url = migration.PINNED_ASSET.url
        self.github.responses[url] = [urllib.error.URLError("connection reset"), NEW]

        self.run_migration()

        self.assert_installed(NEW, migration.ASSET_NAME)
        self.assertEqual([url, url], self.github.requests)
        self.assertEqual(1, len(self.sleeps))

    def test_corrupt_download_fails_and_keeps_the_old_zalo(self) -> None:
        self.write_appimage(OLD)
        self.github.responses[migration.PINNED_ASSET.url] = [NEW[:-1], NEW + b"!", USER]

        with self.assertRaisesRegex(MigrationContextError, "failed verification"):
            self.run_migration()

        self.assertEqual(OLD, self.appimage.read_bytes())
        self.assertEqual(["Zalo.AppImage"], sorted(path.name for path in self.bin.iterdir()))
        self.assertEqual(migration.DOWNLOAD_ATTEMPTS, len(self.github.requests))
        self.assertFalse(self.state.exists())

    def test_checks_free_space_before_downloading(self) -> None:
        self.write_appimage(OLD)
        with patch.object(migration.shutil, "disk_usage", return_value=SimpleNamespace(free=10 * 1024 * 1024)):
            with self.assertRaisesRegex(MigrationContextError, "not enough free space"):
                self.run_migration()

        self.assertEqual([], self.github.requests)
        self.assertEqual(OLD, self.appimage.read_bytes())


if __name__ == "__main__":
    unittest.main()

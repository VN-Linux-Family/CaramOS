"""Tests for returning user-owned system files to root through OTA.

Ownership is simulated through the migration's ``_lstat``/``_fstat``/chown hooks so the tests behave
the same as a normal user and as root (the ISO build runs the package tests as root).
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from caramos_ota_update.context import MigrationContext

MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "usr/lib/python3/dist-packages/caramos_ota_update/migrations"
    / "20261003210000_fix_system_file_ownership/migration.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("fix_system_file_ownership_migration_test", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load migration module: {MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = load_migration()


def with_owner(info: os.stat_result, uid: int, gid: int) -> os.stat_result:
    values = list(info)
    values[stat.ST_UID] = uid
    values[stat.ST_GID] = gid
    return os.stat_result(values)


class FixSystemFileOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.etc = self.root / "etc"
        self.usr = self.root / "usr"
        self.local = self.usr / "local"
        for directory in (
            self.etc / "skel",
            self.etc / "ssl",
            self.usr / "bin",
            self.usr / "share/icons/Bibata",
            self.local / "bin",
            self.local / "share/ca-certificates",
            self.local / "share/admin-app",
        ):
            directory.mkdir(parents=True)
        for path in (
            self.etc / "hostname",
            self.etc / "skel/.bashrc",
            self.etc / "ssl/private.key",
            self.etc / "team.conf",
            self.usr / "bin/caramos-theme-apply",
            self.usr / "bin/setuid-tool",
            self.usr / "share/icons/Bibata/cursor",
            self.local / "bin/admin-tool",
            self.local / "share/admin-app/data",
        ):
            path.write_text("x", encoding="utf-8")
        os.chmod(self.usr / "bin/caramos-theme-apply", 0o775)
        os.chmod(self.usr / "bin/setuid-tool", 0o4775)
        (self.etc / "skel/link").symlink_to("/etc/shadow")

        # Default: everything is root-owned; tests mark what the ISO left with a regular owner.
        self.owners: dict[Path, tuple[int, int]] = {}
        self.chowned: list[object] = []
        real_lstat = os.lstat
        real_fstat = os.fstat

        def fake_lstat(path):
            info = real_lstat(path)
            uid, gid = self.owners.get(Path(path), (0, 0))
            return with_owner(info, uid, gid)

        def fake_fstat(fd):
            info = real_fstat(fd)
            path = Path(os.readlink(f"/proc/self/fd/{fd}"))
            uid, gid = self.owners.get(path, (0, 0))
            return with_owner(info, uid, gid)

        def fake_fchown(fd):
            path = Path(os.readlink(f"/proc/self/fd/{fd}"))
            self.owners[path] = (0, 0)
            self.chowned.append(path)

        def fake_lchown(path):
            self.owners[Path(path)] = (0, 0)
            self.chowned.append(Path(path))

        patches = [
            patch.object(migration, "_lstat", fake_lstat),
            patch.object(migration, "_fstat", fake_fstat),
            patch.object(migration, "_fchown_root", fake_fchown),
            patch.object(migration, "_lchown_root", fake_lchown),
            patch.object(migration, "SCAN_ROOTS", (self.etc, self.usr)),
            patch.object(migration, "LOCAL_ROOT", self.local),
            patch.object(
                migration,
                "LOCAL_SKELETON",
                (self.local, self.local / "bin", self.local / "share", self.local / "share/ca-certificates"),
            ),
            patch.object(migration, "BACKUP_DIR", self.root / "backups"),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.addCleanup(self._tmp.cleanup)

    def mark_iso_owned(self, *paths: Path, uid: int = 1001, gid: int = 1001) -> None:
        for path in paths:
            self.owners[path] = (uid, gid)

    def found(self) -> list[Path]:
        return [fix.path for fix in migration.find_fixes(migration.SCAN_ROOTS, migration.LOCAL_ROOT, migration.LOCAL_SKELETON)]

    def test_finds_only_items_owned_by_regular_accounts(self) -> None:
        self.mark_iso_owned(self.etc, self.etc / "hostname", self.usr / "bin", self.usr / "bin/caramos-theme-apply")
        self.mark_iso_owned(self.usr / "share/icons/Bibata", self.usr / "share/icons/Bibata/cursor", uid=1000, gid=1000)
        self.owners[self.etc / "ssl/private.key"] = (0, 110)  # root:ssl-cert
        self.owners[self.etc / "team.conf"] = (0, 1005)  # admin gave a team group access on purpose
        self.owners[self.usr / "share"] = (65534, 65534)  # nobody is not a login account

        self.assertEqual(
            {
                self.etc,
                self.usr / "bin",
                self.etc / "hostname",
                self.usr / "bin/caramos-theme-apply",
                self.usr / "share/icons/Bibata",
                self.usr / "share/icons/Bibata/cursor",
            },
            set(self.found()),
        )

    def test_usr_local_content_is_left_to_the_administrator(self) -> None:
        self.mark_iso_owned(self.local, self.local / "bin", self.local / "share/ca-certificates")
        self.mark_iso_owned(
            self.local / "bin/admin-tool",
            self.local / "share/admin-app",
            self.local / "share/admin-app/data",
            uid=1000,
            gid=1000,
        )

        self.assertEqual(
            {self.local, self.local / "bin", self.local / "share/ca-certificates"},
            set(self.found()),
        )

    def test_parents_are_fixed_before_children(self) -> None:
        self.mark_iso_owned(self.etc / "skel/.bashrc", self.etc / "skel", self.etc)

        self.assertEqual([self.etc, self.etc / "skel", self.etc / "skel/.bashrc"], self.found())

    def test_symlinks_are_not_followed(self) -> None:
        self.mark_iso_owned(self.etc / "skel/link")

        fixes = migration.find_fixes(migration.SCAN_ROOTS, migration.LOCAL_ROOT, migration.LOCAL_SKELETON)
        self.assertEqual([self.etc / "skel/link"], [fix.path for fix in fixes])

        self.assertIsNone(migration.apply_fix(fixes[0]))
        self.assertEqual([self.etc / "skel/link"], self.chowned)
        self.assertTrue((self.etc / "skel/link").is_symlink())

    def test_mount_points_are_skipped_but_overlay_files_are_not(self) -> None:
        mounted = self.usr / "share/icons"
        overlay_file = self.etc / "hostname"
        self.mark_iso_owned(mounted, mounted / "Bibata", overlay_file)
        current_lstat = migration._lstat

        def other_device(path):
            info = current_lstat(path)
            if Path(path) in (mounted, overlay_file):
                values = list(info)
                values[stat.ST_DEV] = info.st_dev + 1
                return os.stat_result(values)
            return info

        with patch.object(migration, "_lstat", other_device):
            found = self.found()

        # A directory on another device is a mount point; a file reporting another device is how
        # overlayfs shows files from its lower layer, and must still be fixed.
        self.assertEqual([overlay_file], found)

    def test_apply_returns_to_root_and_drops_write_and_setid_bits(self) -> None:
        tool = self.usr / "bin/caramos-theme-apply"
        setuid_tool = self.usr / "bin/setuid-tool"
        self.mark_iso_owned(self.usr / "bin", tool, setuid_tool)
        os.chmod(self.usr / "bin", 0o775)

        for fix in migration.find_fixes(migration.SCAN_ROOTS, migration.LOCAL_ROOT, migration.LOCAL_SKELETON):
            self.assertIsNone(migration.apply_fix(fix))

        self.assertEqual([self.usr / "bin", tool, setuid_tool], self.chowned)
        self.assertEqual(0o755, stat.S_IMODE(os.lstat(self.usr / "bin").st_mode))
        self.assertEqual(0o755, stat.S_IMODE(os.lstat(tool).st_mode))
        self.assertEqual(0o755, stat.S_IMODE(os.lstat(setuid_tool).st_mode))

    def test_swapped_path_is_skipped(self) -> None:
        hostname = self.etc / "hostname"
        self.mark_iso_owned(hostname)
        fix = migration.find_fixes(migration.SCAN_ROOTS, migration.LOCAL_ROOT, migration.LOCAL_SKELETON)[0]
        replacement = self.etc / "hostname.new"
        replacement.write_text("replaced", encoding="utf-8")
        os.replace(replacement, hostname)  # new inode while the old one still exists

        reason = migration.apply_fix(fix)

        self.assertEqual("changed since scan", reason)
        self.assertEqual([], self.chowned)

    def test_dry_run_changes_nothing_and_writes_no_backup(self) -> None:
        self.mark_iso_owned(self.etc, self.etc / "hostname")
        mode_before = stat.S_IMODE(os.lstat(self.etc / "hostname").st_mode)

        migration.run(MigrationContext(dry_run=True))

        self.assertEqual([], self.chowned)
        self.assertFalse((self.root / "backups").exists())
        self.assertEqual(mode_before, stat.S_IMODE(os.lstat(self.etc / "hostname").st_mode))

    def test_run_saves_previous_owners_and_is_idempotent(self) -> None:
        self.mark_iso_owned(self.etc, self.etc / "hostname", self.usr / "bin")
        context = MagicMock(spec=MigrationContext)
        context.dry_run = False

        migration.run(context)

        self.assertEqual({self.etc, self.etc / "hostname", self.usr / "bin"}, set(self.chowned))
        backups = list((self.root / "backups").glob("ownership-before-*.json"))
        self.assertEqual(1, len(backups))
        self.assertEqual(0o600, stat.S_IMODE(backups[0].stat().st_mode))
        saved = json.loads(backups[0].read_text(encoding="utf-8"))
        self.assertEqual("20261003210000_fix_system_file_ownership", saved["migration"])
        record = next(item for item in saved["items"] if item["path"] == str(self.etc / "hostname"))
        self.assertEqual((1001, 1001, "-"), (record["uid"], record["gid"], record["type"]))
        self.assertRegex(record["mode"], r"^0o[0-7]+$")

        self.chowned.clear()
        migration.run(context)

        self.assertEqual([], self.chowned)
        self.assertEqual(1, len(list((self.root / "backups").glob("ownership-before-*.json"))))

    def test_unfixable_path_is_logged_and_does_not_fail_the_migration(self) -> None:
        self.mark_iso_owned(self.etc / "hostname", self.etc / "team.conf")
        context = MagicMock(spec=MigrationContext)
        context.dry_run = False
        real_apply = migration.apply_fix

        def flaky_apply(fix):
            if fix.path.name == "hostname":
                raise PermissionError(1, "Operation not permitted")
            return real_apply(fix)

        with patch.object(migration, "apply_fix", flaky_apply):
            migration.run(context)

        messages = [entry.args[0] for entry in context.log.call_args_list]
        self.assertIn(f"warning: left {self.etc / 'hostname'} unchanged: Operation not permitted", messages)
        self.assertIn("returned 1 path(s) to root:root; 1 skipped", messages)
        self.assertEqual([self.etc / "team.conf"], self.chowned)


if __name__ == "__main__":
    unittest.main()

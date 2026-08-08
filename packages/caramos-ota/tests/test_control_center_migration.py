"""Tests for Control Center timestamp migration safety and panel handling."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# Network state behavior is exercised in the GJS/VM test matrix; migration
# tests stay focused on package and panel safety.


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "usr/lib/python3/dist-packages/caramos_ota_update/migrations/20260715090258_install_control_center/migration.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("control_center_migration_test", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load migration module: {MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = load_migration()


class ControlCenterMigrationTests(unittest.TestCase):
    def test_update_preserves_other_panel_entries_and_positions(self) -> None:
        current = (
            "['panel1:right:4:power@cinnamon.org:0', "
            "'panel1:right:9:calendar@cinnamon.org:0', "
            "'panel1:left:0:menu@cinnamon.org:0']"
        )

        updated = migration._update_enabled_applets(current)

        self.assertEqual(
            "['panel1:right:9:calendar@cinnamon.org:0', "
            "'panel1:left:0:menu@cinnamon.org:0', "
            "'panel1:right:10:caramos-control-center@caramos:0']",
            updated,
        )

    def test_update_removes_stock_indicators_and_preserves_other_entries(self) -> None:
        current = (
            "['panel1:left:0:Cinnamenu@json:0', "
            "'panel1:right:1:network@cinnamon.org:3', "
            "'panel1:right:2:sound@cinnamon.org:4', "
            "'panel1:right:3:notifications@cinnamon.org:5', "
            "'panel1:right:4:power@cinnamon.org:6', "
            "'panel1:right:9:calendar@cinnamon.org:7', "
            "'panel2:left:8:custom@example:2']"
        )

        updated = migration._update_enabled_applets(current)

        self.assertEqual(
            "['panel1:left:0:Cinnamenu@json:0', "
            "'panel1:right:3:notifications@cinnamon.org:5', "
            "'panel1:right:9:calendar@cinnamon.org:7', "
            "'panel2:left:8:custom@example:2', "
            "'panel1:right:10:caramos-control-center@caramos:0']",
            updated,
        )

    def test_update_accepts_mixed_four_and_five_field_entries(self) -> None:
        current = (
            "['panel1:right:1:network@cinnamon.org', "
            "'panel1:right:2:sound@cinnamon.org:4', "
            "'panel1:right:3:power@cinnamon.org', "
            "'panel1:right:7:calendar@cinnamon.org']"
        )

        self.assertEqual(
            "['panel1:right:7:calendar@cinnamon.org', "
            "'panel1:right:8:caramos-control-center@caramos:0']",
            migration._update_enabled_applets(current),
        )

    def test_update_uses_exact_uuid_matching(self) -> None:
        current = (
            "['panel1:right:1:my-network@cinnamon.org:1', "
            "'panel1:right:2:sound@cinnamon.org.extra:2', "
            "'power@cinnamon.org']"
        )

        updated = migration._update_enabled_applets(current)

        self.assertIn("my-network@cinnamon.org", updated)
        self.assertIn("sound@cinnamon.org.extra", updated)
        self.assertIn("'power@cinnamon.org'", updated)

    def test_update_is_idempotent_and_does_not_duplicate_control_center(self) -> None:
        current = (
            "['panel1:right:1:network@cinnamon.org:3', "
            "'panel1:right:4:caramos-control-center@caramos:0']"
        )

        updated = migration._update_enabled_applets(current)

        self.assertEqual("['panel1:right:4:caramos-control-center@caramos:0']", updated)
        self.assertEqual(updated, migration._update_enabled_applets(updated))

    def test_append_rejects_unknown_format(self) -> None:
        self.assertIsNone(migration._update_enabled_applets("not-a-gsettings-list"))

    def test_system_defaults_update_without_live_users(self) -> None:
        source = (
            "[org/cinnamon]\n"
            "enabled-applets=['panel1:left:0:Cinnamenu@json', "
            "'panel1:left:1:grouped-window-list@cinnamon.org', "
            "'panel1:right:1:network@cinnamon.org', "
            "'panel1:right:2:sound@cinnamon.org', "
            "'panel1:right:3:power@cinnamon.org', "
            "'panel1:right:4:custom@example']\n"
            "panels-height=['1:32']\n"
        )

        updated = migration._updated_dconf_text(source)

        self.assertNotIn("network@cinnamon.org", updated)
        self.assertNotIn("sound@cinnamon.org", updated)
        self.assertNotIn("power@cinnamon.org", updated)
        self.assertIn("custom@example", updated)
        self.assertEqual(1, updated.count(migration.APPLET_UUID))
        self.assertEqual(updated, migration._updated_dconf_text(updated))

    def test_missing_system_defaults_get_canonical_control_center_layout(self) -> None:
        updated = migration._updated_dconf_text("")

        self.assertIn("[org/cinnamon]", updated)
        self.assertIn("enabled-applets=", updated)
        self.assertIn(migration.APPLET_UUID, updated)
        self.assertIn("panel1:center:0:grouped-window-list@cinnamon.org", updated)

    def test_blueman_status_icon_disable_preserves_plugins_and_is_idempotent(self) -> None:
        current = "['Menu']"

        updated = migration._update_blueman_plugins(current)

        self.assertEqual("['Menu', '!ShowConnected', '!StatusIcon']", updated)
        self.assertEqual(updated, migration._update_blueman_plugins(updated))

    def test_blueman_status_icon_disable_accepts_gsettings_empty_array_annotation(self) -> None:
        self.assertEqual(
            "['!ShowConnected', '!StatusIcon']",
            migration._update_blueman_plugins("@as []"),
        )

    def test_all_users_include_offline_desktop_accounts(self) -> None:
        users = [
            MagicMock(pw_name="tester", pw_uid=1000, pw_dir="/home/tester"),
            MagicMock(pw_name="service", pw_uid=999, pw_dir="/srv/service"),
            MagicMock(pw_name="missing", pw_uid=1001, pw_dir="/home/missing"),
        ]

        with (
            patch.object(migration.pwd, "getpwall", return_value=users),
            patch.object(Path, "is_dir", autospec=True, side_effect=lambda path: str(path) == "/home/tester"),
        ):
            self.assertEqual(
                [("tester", 1000, Path("/home/tester"))],
                migration._desktop_users(),
            )

    def test_offline_user_gsettings_uses_private_dbus_session(self) -> None:
        env = {"HOME": "/home/tester", "USER": "tester", "LOGNAME": "tester"}
        completed = MagicMock(returncode=0, stdout="[]", stderr="")

        with patch.object(migration.subprocess, "run", return_value=completed) as run:
            result = migration._run_gsettings("tester", env, ["get", "org.cinnamon", "enabled-applets"])

        self.assertIs(result, completed)
        self.assertEqual(
            [
                "runuser",
                "-u",
                "tester",
                "--",
                "dbus-run-session",
                "--",
                "gsettings",
                "get",
                "org.cinnamon",
                "enabled-applets",
            ],
            run.call_args.args[0],
        )

    def test_live_user_update_uses_one_atomic_set(self) -> None:
        context = MagicMock()
        current = (
            "['panel1:right:1:network@cinnamon.org:3', "
            "'panel1:right:2:sound@cinnamon.org:4', "
            "'panel1:right:3:power@cinnamon.org:6']\n"
        )
        applet_read = MagicMock(returncode=0, stdout=current, stderr="")
        plugin_read = MagicMock(returncode=0, stdout="['Menu']\n", stderr="")
        write_result = MagicMock(returncode=0, stdout="", stderr="")

        with (
            patch.object(migration, "_user_environment", return_value={"DISPLAY": ":0"}),
            patch.object(
                migration,
                "_run_gsettings",
                side_effect=[applet_read, write_result, plugin_read, write_result],
            ) as run_gsettings,
        ):
            migration._apply_to_user(context, "tester", 1000, Path("/home/tester"))

        self.assertEqual(4, run_gsettings.call_count)
        applet_set = run_gsettings.call_args_list[1]
        self.assertEqual(["set", "org.cinnamon", "enabled-applets"], applet_set.args[2][:-1])
        final_value = applet_set.args[2][-1]
        self.assertNotIn("network@cinnamon.org", final_value)
        self.assertNotIn("sound@cinnamon.org", final_value)
        self.assertNotIn("power@cinnamon.org", final_value)
        self.assertIn(migration.APPLET_UUID, final_value)

        plugin_set = run_gsettings.call_args_list[3]
        self.assertEqual(["set", "org.blueman.general", "plugin-list"], plugin_set.args[2][:-1])
        self.assertEqual("['Menu', '!ShowConnected', '!StatusIcon']", plugin_set.args[2][-1])

    def test_live_user_noop_does_not_set(self) -> None:
        context = MagicMock()
        applet_read = MagicMock(
            returncode=0,
            stdout="['panel1:right:4:caramos-control-center@caramos:0']\n",
            stderr="",
        )
        plugin_read = MagicMock(
            returncode=0,
            stdout="['Menu', '!ShowConnected', '!StatusIcon']\n",
            stderr="",
        )

        with (
            patch.object(migration, "_user_environment", return_value={"DISPLAY": ":0"}),
            patch.object(
                migration,
                "_run_gsettings",
                side_effect=[applet_read, plugin_read],
            ) as run_gsettings,
        ):
            migration._apply_to_user(context, "tester", 1000, Path("/home/tester"))

        self.assertEqual(2, run_gsettings.call_count)
        self.assertEqual("get", run_gsettings.call_args_list[0].args[2][0])
        self.assertEqual("get", run_gsettings.call_args_list[1].args[2][0])

    def test_missing_source_fails_before_install(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            context = MagicMock()

            with (
                patch.object(migration, "SOURCE_APPLET_DIR", source),
                patch.object(migration, "TARGET_APPLET_DIR", target),
            ):
                with self.assertRaisesRegex(RuntimeError, "source directory not found"):
                    migration._install_applet(context)

            self.assertFalse(target.exists())

    def test_copy_failure_restores_previous_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            old_file = target / "applet.js"
            old_file.write_text("old", encoding="utf-8")
            for name in migration.REQUIRED_APPLET_FILES:
                path = source / name
                if name == "metadata.json":
                    path.write_text(
                        '{"uuid": "caramos-control-center@caramos"}\n',
                        encoding="utf-8",
                    )
                else:
                    path.write_text("new", encoding="utf-8")
            context = MagicMock()

            with (
                patch.object(migration, "SOURCE_APPLET_DIR", source),
                patch.object(migration, "TARGET_APPLET_DIR", target),
                patch.object(migration.shutil, "copytree", side_effect=OSError("copy failed")),
            ):
                with self.assertRaisesRegex(OSError, "copy failed"):
                    migration._install_applet(context)

            self.assertEqual("old", old_file.read_text(encoding="utf-8"))

    def test_install_does_not_rename_target_across_filesystems(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (target / "old.txt").write_text("old", encoding="utf-8")
            for name in migration.REQUIRED_APPLET_FILES:
                path = source / name
                if name == "metadata.json":
                    path.write_text(
                        '{"uuid": "caramos-control-center@caramos"}\n',
                        encoding="utf-8",
                    )
                else:
                    path.write_text("new", encoding="utf-8")
            context = MagicMock()

            with (
                patch.object(migration, "SOURCE_APPLET_DIR", source),
                patch.object(migration, "TARGET_APPLET_DIR", target),
                patch.object(migration.os, "replace", side_effect=OSError(18, "Invalid cross-device link")) as replace,
            ):
                migration._install_applet(context)

            replace.assert_not_called()
            self.assertFalse((target / "old.txt").exists())
            self.assertEqual("new", (target / "applet.js").read_text(encoding="utf-8"))

    def test_validation_failure_restores_previous_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            old_file = target / "old.txt"
            old_file.write_text("old", encoding="utf-8")
            for name in migration.REQUIRED_APPLET_FILES:
                path = source / name
                if name == "metadata.json":
                    path.write_text(
                        '{"uuid": "caramos-control-center@caramos"}\n',
                        encoding="utf-8",
                    )
                else:
                    path.write_text("new", encoding="utf-8")
            context = MagicMock()
            original_validate = migration._validate_applet
            calls = 0

            def fail_installed_target(directory: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise RuntimeError("installed target invalid")
                original_validate(directory)

            with (
                patch.object(migration, "SOURCE_APPLET_DIR", source),
                patch.object(migration, "TARGET_APPLET_DIR", target),
                patch.object(migration, "_validate_applet", side_effect=fail_installed_target),
            ):
                with self.assertRaisesRegex(RuntimeError, "installed target invalid"):
                    migration._install_applet(context)

            self.assertEqual("old", old_file.read_text(encoding="utf-8"))
            self.assertFalse((target / "applet.js").exists())

    def test_install_validates_metadata_and_replaces_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            (target / "old.txt").write_text("old", encoding="utf-8")
            for name in migration.REQUIRED_APPLET_FILES:
                path = source / name
                if name == "metadata.json":
                    path.write_text(
                        '{"uuid": "caramos-control-center@caramos"}\n',
                        encoding="utf-8",
                    )
                else:
                    path.write_text("new", encoding="utf-8")
            context = MagicMock()

            with (
                patch.object(migration, "SOURCE_APPLET_DIR", source),
                patch.object(migration, "TARGET_APPLET_DIR", target),
            ):
                migration._install_applet(context)

            self.assertFalse((target / "old.txt").exists())
            self.assertEqual("new", (target / "applet.js").read_text(encoding="utf-8"))
            context.log.assert_called_once()


if __name__ == "__main__":
    unittest.main()

"""Tests for migration execution and release metadata recovery."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from caramos_ota_update.registry import MigrationDescriptor
from caramos_ota_update.runner import MigrationRunner


class MigrationRunnerTests(unittest.TestCase):
    def test_runs_bundled_timestamp_migration_and_finalizes_release(self) -> None:
        context = MagicMock()
        context.dry_run = False
        runner = MigrationRunner(context=context)
        legacy_ids = {f"v1_0_{version}" for version in range(2, 13)}
        ledger = {
            "schema": 1,
            "applied_migrations": [
                {"id": migration_id, "release": "1.0.12"}
                for migration_id in sorted(legacy_ids)
            ]
            + [
                {"id": "20260715090258_install_control_center"},
                {"id": "20260803120000_apply_three_dock_taskbar"},
                {"id": "20260804223346_change_default_wallpaper"},
            ],
        }

        with (
            patch("caramos_ota_update.runner.bootstrap_ledger", return_value=ledger),
            patch("caramos_ota_update.runner.start_transaction", return_value="timestamp-batch") as start,
            patch("caramos_ota_update.runner.mark_transaction_success") as success,
            patch("caramos_ota_update.runner.mark_migration_running"),
            patch("caramos_ota_update.runner.mark_migration_complete"),
            patch("caramos_ota_update.runner.mark_applied"),
            patch.object(runner, "_run_one") as run_one,
        ):
            runner.run(current_version="1.0.15", target_version="1.0.16")

        start.assert_called_once_with(
            target_version="1.0.16",
            migration_ids=[
                "20260805111120_update_taskbar_pins_cleanup_desktop",
                "20260808090000_restore_power_profiles_daemon",
                "20261003210000_fix_system_file_ownership",
                "20261004120000_fix_mint_base_codename",
                "20261005110000_update_zalo_appimage",
                "20261005190000_install_grub_theme",
                "20261006090000_fix_forced_locale",
                "20261006090100_fix_lotus_boot_deadlock",
                "20261009120000_add_app_center_launcher",
                "20261010120000_remove_unused_icon_colours",
                "20261010120100_lighten_desktop_session",
                "20261012120000_add_driver_check",
                "20261012180000_add_help_applet",
                "20261014120000_stop_copyq_autostart",
                "20261016220000_translate_cinnamon_spices",
                "20261018120000_restore_taskbar_after_cinnamon_update",
                "20261018120100_update_zalo_native_calls",
                "20261022120000_start_fcitx_at_login",
                "20261105120000_keep_lotus_settings",
                "20261105120100_search_menu_while_composing",
                "20261105120200_start_menu_file_search_without_freeze",
                "20261111090000_start_menu_ctrl_scroll_icon_size",
                "20261112100000_screenshot_shortcuts",
                "20261117100000_lotus_source_amd64_only",
                "20261117100100_nemo_actions_in_menu",
                "20261117100200_daily_wallpaper",
                "20261118090000_files_new_menu",
                "20261118090100_xfce_wallpapers",
                "20261119100000_open_office_documents",
                "20261119100200_lighten_xfce_session",
                "20261120100000_clipboard_history",
                "20261120100100_taskbar_alignment",
                "20261120100200_lunar_calendar",
                "20261120100300_external_monitor_brightness",
                "20261120100400_xfce_lunar_clock",
                "20261120100500_xfce_round_menus",
                "20261120100600_round_menus",
                "20261120100700_windows_shortcuts",
                "20261122100000_carlito_font",
                "20261122100100_administrative_templates",
                "20261122100200_windows_migration_tools",
                "20261123100000_automatic_updates",
                "20261123120000_hidden_password_typing",
                "20261123120100_desktop_shortcuts_anywhere",
                "20261124100000_show_desktop_button",
                "20261124100100_xfce_super_d_super_e",
                "20261124100200_print_screen_to_clipboard",
                "20261124100300_xfce_event_sounds",
                "20261124120000_desktop_icon_labels",
                "20261124130000_install_fastfetch",
                "20261124140000_show_trash_on_desktop",
                "20261124170000_tray_icons_follow_theme",
                "20261124180000_tray_icons_keep_their_place",
                "20261125090000_fcitx5_tray_shows_input_method",
            ],
        )
        self.assertEqual(54, run_one.call_count)
        self.assertEqual(
            [
                "20260805111120_update_taskbar_pins_cleanup_desktop",
                "20260808090000_restore_power_profiles_daemon",
                "20261003210000_fix_system_file_ownership",
                "20261004120000_fix_mint_base_codename",
                "20261005110000_update_zalo_appimage",
                "20261005190000_install_grub_theme",
                "20261006090000_fix_forced_locale",
                "20261006090100_fix_lotus_boot_deadlock",
                "20261009120000_add_app_center_launcher",
                "20261010120000_remove_unused_icon_colours",
                "20261010120100_lighten_desktop_session",
                "20261012120000_add_driver_check",
                "20261012180000_add_help_applet",
                "20261014120000_stop_copyq_autostart",
                "20261016220000_translate_cinnamon_spices",
                "20261018120000_restore_taskbar_after_cinnamon_update",
                "20261018120100_update_zalo_native_calls",
                "20261022120000_start_fcitx_at_login",
                "20261105120000_keep_lotus_settings",
                "20261105120100_search_menu_while_composing",
                "20261105120200_start_menu_file_search_without_freeze",
                "20261111090000_start_menu_ctrl_scroll_icon_size",
                "20261112100000_screenshot_shortcuts",
                "20261117100000_lotus_source_amd64_only",
                "20261117100100_nemo_actions_in_menu",
                "20261117100200_daily_wallpaper",
                "20261118090000_files_new_menu",
                "20261118090100_xfce_wallpapers",
                "20261119100000_open_office_documents",
                "20261119100200_lighten_xfce_session",
                "20261120100000_clipboard_history",
                "20261120100100_taskbar_alignment",
                "20261120100200_lunar_calendar",
                "20261120100300_external_monitor_brightness",
                "20261120100400_xfce_lunar_clock",
                "20261120100500_xfce_round_menus",
                "20261120100600_round_menus",
                "20261120100700_windows_shortcuts",
                "20261122100000_carlito_font",
                "20261122100100_administrative_templates",
                "20261122100200_windows_migration_tools",
                "20261123100000_automatic_updates",
                "20261123120000_hidden_password_typing",
                "20261123120100_desktop_shortcuts_anywhere",
                "20261124100000_show_desktop_button",
                "20261124100100_xfce_super_d_super_e",
                "20261124100200_print_screen_to_clipboard",
                "20261124100300_xfce_event_sounds",
                "20261124120000_desktop_icon_labels",
                "20261124130000_install_fastfetch",
                "20261124140000_show_trash_on_desktop",
                "20261124170000_tray_icons_follow_theme",
                "20261124180000_tray_icons_keep_their_place",
                "20261125090000_fcitx5_tray_shows_input_method",
            ],
            [entry.args[0].migration_id for entry in run_one.call_args_list],
        )
        self.assertTrue(all(entry.args[0].release is None for entry in run_one.call_args_list))
        context.update_release_file.assert_called_once_with("1.0.16")
        success.assert_called_once_with(
            transaction_id="timestamp-batch",
            installed_version="1.0.16",
        )

    def test_finalizes_release_when_target_migrations_are_already_applied(self) -> None:
        migration = MigrationDescriptor(
            migration_id="20260714090000_first_change",
            release=None,
            description="First change",
            source="test",
            directory=Path("/tmp/20260714090000_first_change"),
            module_path=Path("/tmp/20260714090000_first_change/migration.py"),
            schema=2,
            codename="noble",
            channel="stable",
            severity="normal",
            size="migration update",
            title="Update",
            summary="First change",
            release_notes_vi=[],
            release_notes_en=[],
        )
        ledger = {
            "schema": 1,
            "applied_migrations": [
                {"id": migration.migration_id},
            ],
        }
        context = MagicMock()
        context.dry_run = False
        runner = MigrationRunner(context=context)
        runner.discover = MagicMock(return_value=[migration])

        with (
            patch("caramos_ota_update.runner.bootstrap_ledger", return_value=ledger),
            patch("caramos_ota_update.runner.start_transaction", return_value="recovery") as start,
            patch("caramos_ota_update.runner.mark_transaction_success") as success,
        ):
            runner.run(current_version="1.0.2", target_version="1.0.3")

        start.assert_called_once_with(target_version="1.0.3", migration_ids=[])
        context.update_release_file.assert_called_once_with("1.0.3")
        success.assert_called_once_with(
            transaction_id="recovery",
            installed_version="1.0.3",
        )


if __name__ == "__main__":
    unittest.main()

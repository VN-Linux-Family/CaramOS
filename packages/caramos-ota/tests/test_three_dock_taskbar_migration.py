"""Tests for taskbar zone-only migration."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "usr/lib/python3/dist-packages/caramos_ota_update/migrations/20260803120000_apply_three_dock_taskbar/migration.py"
)


def load_migration():
    spec = importlib.util.spec_from_file_location("three_dock_taskbar_test", MIGRATION_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load migration module: {MIGRATION_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = load_migration()


class TaskbarZoneOnlyMigrationTests(unittest.TestCase):
    def test_moves_only_menu_and_task_list(self) -> None:
        current = (
            "['panel1:right:8:calendar@cinnamon.org:7', "
            "'panel1:left:5:Cinnamenu@json:0', "
            "'panel1:left:6:grouped-window-list@cinnamon.org:1', "
            "'panel1:right:2:network@cinnamon.org:3', "
            "'panel1:right:9:caramos-control-center@caramos:0', "
            "'panel2:left:0:workspace-switcher@cinnamon.org:3']"
        )
        self.assertEqual(
            "['panel1:right:8:calendar@cinnamon.org:7', "
            "'panel1:left:0:Cinnamenu@json:0', "
            "'panel1:center:0:grouped-window-list@cinnamon.org:1', "
            "'panel1:right:2:network@cinnamon.org:3', "
            "'panel1:right:9:caramos-control-center@caramos:0', "
            "'panel2:left:0:workspace-switcher@cinnamon.org:3']",
            migration._arrange_applets(current),
        )

    def test_moves_four_field_fresh_iso_entries(self) -> None:
        current = (
            "['panel1:left:4:Cinnamenu@json', "
            "'panel1:left:5:grouped-window-list@cinnamon.org', "
            "'panel1:right:1:calendar@cinnamon.org']"
        )

        self.assertEqual(
            "['panel1:left:0:Cinnamenu@json', "
            "'panel1:center:0:grouped-window-list@cinnamon.org', "
            "'panel1:right:1:calendar@cinnamon.org']",
            migration._arrange_applets(current),
        )

    def test_system_defaults_update_without_live_users(self) -> None:
        source = (
            "[org/cinnamon]\n"
            "enabled-applets=['panel1:left:4:Cinnamenu@json', "
            "'panel1:left:5:grouped-window-list@cinnamon.org', "
            "'panel1:right:3:caramos-control-center@caramos:0']\n"
            "panels-height=['1:32']\n"
            "panel-zone-icon-sizes='[{\"panelId\": 1, \"maxSize\": 18}]'\n"
            "custom-key='keep-me'\n"
        )

        updated = migration._updated_dconf_defaults(migration.PANEL_DCONF_FILE, source)

        self.assertIn("panel1:center:0:grouped-window-list@cinnamon.org", updated)
        self.assertIn("panels-height=['1:48']", updated)
        self.assertIn('"left": 32', updated)
        self.assertIn("custom-key='keep-me'", updated)
        self.assertEqual(updated, migration._updated_dconf_defaults(migration.PANEL_DCONF_FILE, updated))

    def test_arrangement_is_idempotent(self) -> None:
        current = (
            "['panel1:left:0:Cinnamenu@json:0', "
            "'panel1:center:0:grouped-window-list@cinnamon.org:1', "
            "'panel1:right:4:power@cinnamon.org:6']"
        )
        self.assertEqual(current, migration._arrange_applets(current))

    def test_rejects_unknown_layout_format(self) -> None:
        self.assertIsNone(migration._arrange_applets("not-a-list"))
        self.assertIsNone(migration._arrange_applets("[broken"))

    def test_removes_old_marker_css_instead_of_installing_css(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            theme = Path(temp_dir) / "cinnamon.css"
            theme.write_text(
                "base\n/* @caramos-three-dock-taskbar:start */\nbad-css\n"
                "/* @caramos-three-dock-taskbar:end */\ntail\n",
                encoding="utf-8",
            )
            context = MagicMock(dry_run=False)
            with patch.object(migration, "THEME_CSS", theme):
                self.assertTrue(migration._remove_old_css(context))
            result = theme.read_text(encoding="utf-8")
            self.assertEqual("base\n\ntail\n", result)
            self.assertNotIn("taskbar", result)

    def test_systray_hover_stretches_button_without_resizing_icon(self) -> None:
        source = (
            "            icon.set_y_align(Clutter.ActorAlign.CENTER);\n"
            "            button.set_y_align(Clutter.ActorAlign.CENTER);\n"
        )
        patched = migration._build_systray_hover(source)
        self.assertIsNotNone(patched)
        self.assertEqual(1, patched.count(migration.SYSTRAY_HOVER_MARKER))
        self.assertIn("icon.set_y_align(Clutter.ActorAlign.CENTER)", patched)
        self.assertIn("button.set_y_align(Clutter.ActorAlign.FILL)", patched)
        self.assertNotIn("icon.set_size", patched)
        self.assertEqual(patched, migration._build_systray_hover(patched))

    def test_unknown_systray_is_not_patched(self) -> None:
        self.assertIsNone(migration._build_systray_hover("distro update"))

    def test_cinnamenu_scales_with_horizontal_panel_height(self) -> None:
        source = (
            "  on_panel_height_changed: function() {\n"
            "    this.refresh();\n"
            "  },\n"
            "    if (this.state.settings.menuIconCustom && this.state.settings.menuIcon === '') {\n"
        )
        patched = migration._build_cinnamenu_dynamic_scale(source)
        self.assertIsNotNone(patched)
        self.assertEqual(1, patched.count(migration.CINNAMENU_SCALE_MARKER))
        self.assertIn("this._updateIconAndLabel();", patched)
        self.assertIn(
            "const horizontal = this.orientation === St.Side.TOP || this.orientation === St.Side.BOTTOM",
            patched,
        )
        self.assertIn(
            "this.panel && this.panel.actor ? this.panel.actor.height : this._panelHeight",
            patched,
        )
        self.assertIn("this._applet_icon.icon_size = panelHeight - 16", patched)
        self.assertEqual(patched, migration._build_cinnamenu_dynamic_scale(patched))

    def test_unknown_cinnamenu_is_not_patched(self) -> None:
        self.assertIsNone(migration._build_cinnamenu_dynamic_scale("distro update"))

    def test_running_dot_patch_is_idempotent_and_running_based(self) -> None:
        source = (
            "        this.actor.add_child(this.label);\n"
            "        this.iconSize = iconSize;\n"
            "        this.actor.style = existingStyle + 'margin-' + direction + ':' + spacing + 'px;';\n"
            "            this.actor.height = panelHeight;\n"
            "        const iconYPadding = Math.floor(Math.max(0, allocHeight - naturalHeight) / 2);\n"
            "        const notifBadgeBox = new Clutter.ActorBox();\n"
            "                alloc.natural_size = iconNaturalSize + 6 * global.ui_scale;\n"
            "        this.iconBox.allocate(childBox, flags);\n"
            "        this.groupState.metaWindows.splice(refWindow, 1);\n"
            "    setActiveStatus(state) {\n"
            "        if (state && !this.actor.has_style_pseudo_class('active')) {\n"
            "            this.actor.add_style_pseudo_class('active');\n"
            "        } else {\n"
            "            this.actor.remove_style_pseudo_class('active');\n"
            "        }\n"
            "    }\n"
            "        this.groupState.set({windowCount: this.groupState.metaWindows ? this.groupState.metaWindows.length : 0});\n"
        )
        patched = migration._build_app_group_with_running_dot(source)
        self.assertIsNotNone(patched)
        self.assertEqual(1, patched.count(migration.RUNNING_DOT_MARKER))
        self.assertIn(
            "this.runningDot.visible = this.groupState.windowCount > 0 && this.state.isHorizontal",
            patched,
        )
        self.assertIn(
            "this.runningDot.visible = this.groupState.metaWindows.length > 0 && this.state.isHorizontal",
            patched,
        )
        self.assertEqual(1, patched.count(migration.RUNNING_DOT_CLOSE_MARKER))
        self.assertIn("this.iconSize = this.state.isHorizontal ? 32 * global.ui_scale", patched)
        self.assertIn("margin-' + direction + ':0px", patched)
        self.assertIn("this.actor.height = 40 * global.ui_scale", patched)
        self.assertIn("/ 2) + global.ui_scale", patched)
        self.assertIn("iconNaturalSize + 16 * global.ui_scale", patched)
        self.assertIn("const dotSize = 3 * global.ui_scale", patched)
        self.assertIn("runningDotBox.y2 = box.y2", patched)
        self.assertNotIn("focus", patched)
        self.assertEqual(patched, migration._build_app_group_with_running_dot(patched))

    def test_existing_running_dot_gains_close_state_fix(self) -> None:
        source = (
            f"        // {migration.RUNNING_DOT_MARKER}\n"
            "        this.runningDot = new St.Widget();\n"
            "        this.groupState.metaWindows.splice(refWindow, 1);\n"
        )
        patched = migration._build_app_group_with_running_dot(source)
        self.assertIsNotNone(patched)
        self.assertEqual(1, patched.count(migration.RUNNING_DOT_MARKER))
        self.assertEqual(1, patched.count(migration.RUNNING_DOT_CLOSE_MARKER))
        self.assertEqual(patched, migration._build_app_group_with_running_dot(patched))

    def test_existing_running_dot_without_close_anchor_fails_closed(self) -> None:
        source = f"// {migration.RUNNING_DOT_MARKER}\ndistro update\n"
        self.assertIsNone(migration._build_app_group_with_running_dot(source))

    def test_unknown_app_group_is_not_patched(self) -> None:
        self.assertIsNone(migration._build_app_group_with_running_dot("distro update"))

    def test_css_falls_back_to_underline_when_js_patch_is_unsafe(self) -> None:
        css = migration._build_theme_with_docks("base", running_dot=False)
        self.assertNotIn(".caramos-running-dot", css)
        self.assertNotIn("border-color: transparent", css)
        self.assertIn(".panelCenter", css)

    def test_only_previous_bad_settings_are_reset(self) -> None:
        context = MagicMock()
        env = {"DISPLAY": ":0"}
        get_bad = MagicMock(
            returncode=0,
            stdout="'[{\"panelId\": 1, \"left\": 22, \"center\": 24, \"right\": 18}]'\n",
            stderr="",
        )
        reset_ok = MagicMock(returncode=0, stdout="", stderr="")
        with patch.object(migration, "_run_as_user", side_effect=[get_bad, reset_ok]) as runner:
            migration._reset_previous_override(context, "tester", env, "panel-zone-icon-sizes")
        self.assertEqual("reset", runner.call_args_list[1].args[2][1])

    def test_custom_setting_is_not_reset(self) -> None:
        context = MagicMock()
        env = {"DISPLAY": ":0"}
        custom = MagicMock(returncode=0, stdout="['1:36']\n", stderr="")
        with patch.object(migration, "_run_as_user", return_value=custom) as runner:
            migration._reset_previous_override(context, "tester", env, "panels-height")
        runner.assert_called_once()

    def test_dock_css_is_paint_only_and_idempotent(self) -> None:
        for forbidden in migration.FORBIDDEN_DOCK_CSS:
            self.assertNotIn(forbidden, migration.DOCK_CSS)
        self.assertIn(".panelLeft .applet-box", migration.DOCK_CSS)
        self.assertIn(".panelCenter", migration.DOCK_CSS)
        self.assertIn(".panelRight", migration.DOCK_CSS)
        self.assertIn(".panelRight > .applet-box:hover", migration.DOCK_CSS)
        self.assertIn(".panelRight > .systray .applet-box:hover", migration.DOCK_CSS)
        right_hover_css = migration.DOCK_CSS.split(
            ".panelRight > .applet-box:hover,", 1
        )[1].split("}", 1)[0]
        self.assertIn("background-color: rgba(239, 230, 239, 0.69)", right_hover_css)
        self.assertIn("border-radius: 999px", right_hover_css)
        self.assertNotIn("height:", right_hover_css)
        self.assertIn("#panel {\n  background-color: transparent;", migration.DOCK_CSS)
        self.assertIn("background-color", migration.DOCK_CSS)
        self.assertIn("border-radius", migration.DOCK_CSS)
        self.assertIn("box-shadow: inset", migration.DOCK_CSS)
        self.assertIn(".caramos-running-dot", migration.DOCK_CSS)
        self.assertIn(".panelCenter .grouped-window-list-item-box:hover", migration.DOCK_CSS)
        self.assertIn(".panelCenter .grouped-window-list-item-box:focus", migration.DOCK_CSS)
        hover_css = migration.DOCK_CSS.split(
            ".panelCenter .grouped-window-list-item-box:hover,", 1
        )[1].split("}", 1)[0]
        self.assertIn("border-radius: 999px", hover_css)
        self.assertNotIn("background-color", hover_css)
        self.assertIn("width: 3px", migration.DOCK_CSS)
        self.assertIn("height: 3px", migration.DOCK_CSS)
        self.assertIn("border-color: transparent", migration.DOCK_CSS)
        self.assertNotIn("border-bottom-width", migration.DOCK_CSS)
        first = migration._build_theme_with_docks("base")
        self.assertEqual(first, migration._build_theme_with_docks(first))

    def test_dock_css_replaces_existing_marker_block(self) -> None:
        old = (
            "base\n/* CARAMOS_20260803120000_PANEL_DOCKS_START */\nold\n"
            "/* CARAMOS_20260803120000_PANEL_DOCKS_END */\ntail\n"
        )
        result = migration._build_theme_with_docks(old)
        self.assertIn("base", result)
        self.assertIn("tail", result)
        self.assertNotIn("\nold\n", result)
        self.assertEqual(1, result.count("CARAMOS_20260803120000_PANEL_DOCKS_START"))

    def test_sets_48px_panel_only_from_known_baseline(self) -> None:
        context = MagicMock()
        env = {"DISPLAY": ":0"}
        current = MagicMock(returncode=0, stdout="['1:32']\n", stderr="")
        changed = MagicMock(returncode=0, stdout="", stderr="")
        with patch.object(migration, "_run_as_user", side_effect=[current, changed]) as runner:
            migration._set_dock_panel_height(context, "tester", env)
        self.assertEqual(
            ["gsettings", "set", "org.cinnamon", "panels-height", "['1:48']"],
            runner.call_args_list[1].args[2],
        )

    def test_preserves_custom_panel_height(self) -> None:
        context = MagicMock()
        env = {"DISPLAY": ":0"}
        current = MagicMock(returncode=0, stdout="['1:36']\n", stderr="")
        with patch.object(migration, "_run_as_user", return_value=current) as runner:
            migration._set_dock_panel_height(context, "tester", env)
        runner.assert_called_once()

    def test_dry_run_calls_no_mutating_helpers(self) -> None:
        context = MagicMock(dry_run=True)
        with (
            patch.object(migration, "_remove_old_css") as css,
            patch.object(migration, "_install_cinnamenu_dynamic_scale") as cinnamenu_scale,
            patch.object(migration, "_install_systray_hover") as systray_hover,
            patch.object(migration, "_install_running_dot") as running_dot,
            patch.object(migration, "_remove_bad_dconf") as dconf,
            patch.object(migration, "_install_dock_shell_css") as dock_css,
            patch.object(migration, "_live_desktop_users") as users,
        ):
            migration.run(context)
        css.assert_not_called()
        cinnamenu_scale.assert_not_called()
        systray_hover.assert_not_called()
        running_dot.assert_not_called()
        dconf.assert_not_called()
        dock_css.assert_not_called()
        users.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""Static scope checks for taskbar zone-only migration."""

from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATION = (
    ROOT
    / "usr/lib/python3/dist-packages/caramos_ota_update/migrations/20260803120000_apply_three_dock_taskbar/migration.py"
)


class TaskbarZoneOnlyStaticTests(unittest.TestCase):
    def test_no_taskbar_css_or_javascript_payload_is_shipped(self) -> None:
        self.assertFalse((ROOT / "usr/share/caramos-ota/taskbar").exists())
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        self.assertNotIn("usr/share/caramos-ota/taskbar", install)

    def test_migration_uses_inline_paint_only_css(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertNotIn("SOURCE_CSS", source)
        self.assertNotIn("SOURCE_APP_GROUP", source)
        self.assertNotIn("_install_theme", source)
        self.assertNotIn("_install_app_group", source)
        self.assertIn("_install_dock_shell_css", source)
        self.assertIn("DOCK_CSS =", source)
        self.assertNotIn("PANEL_HEIGHTS =", source)
        self.assertIn("LEFT_DOCK_ICON_SIZES", source)
        self.assertIn("_remove_old_css", source)
        self.assertIn("_install_running_dot", source)
        self.assertIn("RUNNING_DOT_MARKER", source)
        self.assertIn("RUNNING_DOT_CLOSE_MARKER", source)
        self.assertIn("_install_cinnamenu_dynamic_scale", source)
        self.assertIn("CINNAMENU_SCALE_MARKER", source)
        self.assertIn("_install_systray_hover", source)
        self.assertIn("SYSTRAY_HOVER_MARKER", source)
        self.assertNotIn("Main.loadTheme", source)
        self.assertNotIn("org.Cinnamon.Eval", source)

    def test_only_menu_and_task_list_define_target_zones(self) -> None:
        source = MIGRATION.read_text(encoding="utf-8")
        self.assertIn('APPLET_MENU = "Cinnamenu@json"', source)
        self.assertIn('APPLET_TASKLIST = "grouped-window-list@cinnamon.org"', source)
        self.assertNotIn("STATUS_APPLETS", source)
        self.assertNotIn("CONTROL_CENTER_UUID", source)


if __name__ == "__main__":
    unittest.main()

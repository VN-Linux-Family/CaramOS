"""Static checks for user-facing OTA update list content."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
UI = ROOT / "usr/lib/python3/dist-packages/caramos_ota_notifier/ui.py"


class NotifierUiStaticTests(unittest.TestCase):
    def test_update_list_shows_descriptions_without_versions_or_badges(self) -> None:
        source = UI.read_text(encoding="utf-8")
        self.assertIn('pkg.get("description") or pkg.get("name")', source)
        self.assertIn("Nội dung sẽ cập nhật", source)
        self.assertNotIn('badge = "bắt buộc"', source)
        self.assertNotIn("ver_lbl.set_text", source)
        self.assertNotIn("set_tooltip_text(str(pkg", source)
        update_page = source.split("def build_update_page", 1)[1].split("def _screen_dialog_size", 1)[0]
        self.assertNotIn("Gtk.Paned", update_page)
        self.assertNotIn("Nội dung cập nhật", update_page)
        self.assertNotIn("notes_panel", update_page)


if __name__ == "__main__":
    unittest.main()

"""Tests for user-facing OTA notifier package normalization."""

from __future__ import annotations

import unittest

from caramos_ota_notifier.state import normalize_package


class NotifierStateTests(unittest.TestCase):
    def test_technical_pending_item_keeps_description_for_ui(self) -> None:
        package = normalize_package(
            {
                "name": "20260805111120_update_taskbar_pins_cleanup_desktop",
                "current_version": "pending",
                "available_version": None,
                "description": "Ghim ứng dụng cần thiết vào taskbar và dọn Desktop.",
                "required": True,
            }
        )

        self.assertEqual("Ghim ứng dụng cần thiết vào taskbar và dọn Desktop.", package["description"])
        self.assertEqual("pending", package["current"])

    def test_blank_display_versions_use_fallback_without_crashing(self) -> None:
        package = normalize_package(
            {
                "name": "Cập nhật taskbar CaramOS",
                "current_version": "",
                "available_version": "",
                "description": "Cập nhật bố cục taskbar.",
                "required": False,
            }
        )

        self.assertEqual("Chưa rõ", package["current"])
        self.assertEqual("Chưa rõ", package["available"])
        self.assertEqual("Cập nhật bố cục taskbar.", package["description"])


if __name__ == "__main__":
    unittest.main()

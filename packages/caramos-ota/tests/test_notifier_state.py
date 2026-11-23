"""Tests for user-facing OTA notifier package normalization."""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from caramos_ota.models import ReleaseInfo
from caramos_ota_notifier import state
from caramos_ota_notifier.state import change_rows, normalize_package, size_parts, update_versions


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

        # No compiled catalog in the source tree, so the English fallback shows.
        self.assertEqual("Unknown", package["current"])
        self.assertEqual("Unknown", package["available"])
        self.assertEqual("Cập nhật bố cục taskbar.", package["description"])


class ChangeRowTests(unittest.TestCase):
    """What the update page lists; no compiled catalog in the source tree, so English shows."""

    def test_each_change_shows_its_title_and_description(self) -> None:
        info = {"packages": [{"name": "Phím tắt quen thuộc như trên Windows", "description": "Super+L khóa máy."},
                             {"name": "Các menu bo tròn góc", "description": "Các menu bo tròn góc"}]}
        self.assertEqual([("Phím tắt quen thuộc như trên Windows", "Super+L khóa máy."),
                          ("Các menu bo tròn góc", "")], change_rows(info))

    def test_a_migration_id_is_not_shown(self) -> None:
        info = {"packages": [{"name": "20260805111120_update_taskbar_pins_cleanup_desktop",
                              "description": "Ghim ứng dụng cần thiết vào taskbar và dọn Desktop."},
                             {"name": "v1_0_12", "description": ""}, "Zalo"]}
        self.assertEqual([("Ghim ứng dụng cần thiết vào taskbar và dọn Desktop.", ""), ("Zalo", "")],
                         change_rows(info))
        self.assertEqual([("CaramOS update", "")], change_rows({"packages": [{"name": "v1_0_9"}]}))

    def test_an_update_of_the_version_number_alone_says_so_in_words(self) -> None:
        info = {"release": "1.4.1", "current_version": "1.4.0",
                "packages": [{"name": state.RELEASE_METADATA_NAME,
                              "description": "Update CaramOS release metadata to packaged target."}]}
        self.assertEqual([("Version information", "The system will record that it runs CaramOS 1.4.1.")],
                         change_rows(info))

    def test_versions_and_sizes(self) -> None:
        self.assertEqual(("1.3.11", "1.4.0"), update_versions({"current_version": "1.3.11", "release": "1.4.0"}))
        self.assertEqual(("1.0.20", "1.3.0"), update_versions({"from_version": "1.0.20", "to_version": "1.3.0"}))
        self.assertEqual(("", ""), update_versions({"current_version": "Unknown", "release": " "}))
        self.assertEqual(["CopyQ (~3 MB)", "Look (under 1 MB)", "Shortcuts (under 1 MB)"],
                         size_parts("CopyQ (~3 MB) + Look (under 1 MB) + Look (under 1 MB) + Shortcuts (under 1 MB)"))
        self.assertEqual([], size_parts(None))


class ManualCheckTests(unittest.TestCase):
    def test_changes_for_the_other_edition_are_not_listed(self) -> None:
        release = ReleaseInfo(name="CaramOS", version="1.4.0", codename="noble", channel="stable")
        cinnamon = SimpleNamespace(migration_id="20261112100000_screenshot_shortcuts", desktops=("cinnamon",),
                                   title="PrtSc", summary="", title_en="PrtSc", summary_en="")
        everywhere = SimpleNamespace(migration_id="20261119100000_open_office_documents", desktops=(),
                                     title="Office", summary="", title_en="Office", summary_en="")
        manifest = SimpleNamespace(release="1.4.0", source="", channel="stable", severity="normal", size="", size_en="",
                                   title="", summary="", title_en="", summary_en="", release_notes_vi=[],
                                   release_notes_en=[])
        for pending, listed in (([cinnamon, everywhere], ["Office"]), ([cinnamon], ["PrtSc"])):
            plan = SimpleNamespace(migrations=pending, target_version="1.4.0")
            with mock.patch.dict(os.environ, {"CARAMOS_OTA_DESKTOP": "xfce"}), \
                    mock.patch.object(state, "_read_release_info", return_value=release), \
                    mock.patch.object(state, "read_no_update_status", return_value={}), \
                    mock.patch.object(state, "resolve_update_plan", return_value=plan), \
                    mock.patch.object(state, "manifest_for_plan", return_value=manifest):
                update_info, _status = state.resolve_available_update_now()
            self.assertEqual(listed, [package["name"] for package in update_info["packages"]])
            self.assertEqual([item.migration_id for item in pending], update_info["migration_ids"])


if __name__ == "__main__":
    unittest.main()

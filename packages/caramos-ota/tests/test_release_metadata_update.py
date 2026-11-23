"""Tests for product-target and metadata-only OTA detection."""

from __future__ import annotations

import dataclasses
import os
import unittest
from unittest import mock

from caramos_ota import apt, manifest
from caramos_ota.models import Manifest, ReleaseInfo
from caramos_ota_update.registry import MigrationPlan


class ReleaseMetadataUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.release_info = ReleaseInfo(
            name="CaramOS",
            version="1.0.15",
            codename="noble",
            channel="stable",
        )

    def test_empty_plan_builds_metadata_update_manifest(self) -> None:
        result = manifest._manifest_from_descriptors([], self.release_info, "1.0.16")

        self.assertEqual("1.0.16", result.release)
        self.assertEqual("Cập nhật CaramOS", result.title)
        self.assertIn("1.0.15", result.summary)
        self.assertIn("1.0.16", result.summary)
        self.assertEqual("normal", result.severity)

    def test_the_headline_is_the_newest_feature_or_fix_not_housekeeping(self) -> None:
        from caramos_ota_update.registry import discover_migrations

        catalog = {item.migration_id: item for item in discover_migrations()}
        pending = [catalog[name] for name in ("20261010120000_remove_unused_icon_colours",
                                              "20261012180000_add_help_applet",
                                              "20261014120000_stop_copyq_autostart")]
        current = ReleaseInfo(name="CaramOS", version="1.0.20", codename="noble", channel="stable")
        result = manifest._manifest_from_descriptors(pending, current, "1.3.0")
        self.assertEqual(catalog["20261012180000_add_help_applet"].title, result.title)
        self.assertEqual("feature", result.severity)
        # Every change is still listed.
        for item in pending:
            self.assertTrue(any(note.startswith(f"{item.migration_id}: ") for note in result.release_notes_en))
        # Only housekeeping pending: the newest one.
        result = manifest._manifest_from_descriptors(pending[::2], current, "1.3.0")
        self.assertEqual(catalog["20261014120000_stop_copyq_autostart"].title, result.title)

    def test_metadata_only_target_creates_available_update(self) -> None:
        plan = MigrationPlan(
            current_version="1.0.15",
            target_version="1.0.16",
            migrations=[],
        )
        ota_manifest = Manifest(
            release="1.0.16",
            codename="noble",
            source="packaged CaramOS release metadata",
            min_client_version="1.0.16-0caramos1",
            channel="stable",
            severity="normal",
            size="Release metadata",
            title="Cập nhật CaramOS",
            summary="Cập nhật thông tin hệ thống.",
            release_notes_vi=[],
            release_notes_en=[],
        )
        state = {"available_update": None}

        with (
            mock.patch.object(apt, "resolve_update_plan", return_value=plan),
            mock.patch.object(apt, "manifest_for_plan", return_value=ota_manifest),
            mock.patch.object(apt, "save_state"),
        ):
            _, updates = apt.detect_updates(self.release_info, state)

        self.assertEqual(1, len(updates))
        self.assertEqual("CaramOS release metadata", updates[0].name)
        self.assertEqual("1.0.16", state["available_update"]["to_version"])
        self.assertEqual([], state["available_update"]["migration_ids"])
        self.assertEqual("Cập nhật CaramOS", state["available_update"]["title"])

    def test_same_target_without_pending_migrations_has_no_update(self) -> None:
        current = ReleaseInfo(name="CaramOS", version="1.0.16", codename="noble", channel="stable")
        plan = MigrationPlan(current_version="1.0.16", target_version="1.0.16", migrations=[])
        ota_manifest = manifest._manifest_from_descriptors([], current, "1.0.16")
        state = {"available_update": {"stale": True}}

        with (
            mock.patch.object(apt, "resolve_update_plan", return_value=plan),
            mock.patch.object(apt, "manifest_for_plan", return_value=ota_manifest),
            mock.patch.object(apt, "save_state"),
        ):
            _, updates = apt.detect_updates(current, state)

        self.assertEqual([], updates)
        self.assertIsNone(state["available_update"])

    def test_one_security_fix_makes_a_security_update(self) -> None:
        from caramos_ota_update.registry import discover_migrations

        catalog = {item.migration_id: item for item in discover_migrations()}
        pending = [catalog["20261117100000_lotus_source_amd64_only"], catalog["20261119100000_open_office_documents"]]
        current = ReleaseInfo(name="CaramOS", version="1.3.11", codename="noble", channel="stable")
        self.assertEqual("normal", manifest._manifest_from_descriptors(pending, current, "1.4.0").severity)
        pending[0] = dataclasses.replace(pending[0], severity="security")
        # The Update Center says so first, whichever change leads.
        self.assertEqual("security", manifest._manifest_from_descriptors(pending, current, "1.4.0").severity)

    def test_the_update_center_lists_only_the_changes_for_this_edition(self) -> None:
        from caramos_ota_update.registry import discover_migrations

        catalog = {item.migration_id: item for item in discover_migrations()}
        cinnamon_only = catalog["20261112100000_screenshot_shortcuts"]
        everywhere = catalog["20261119100000_open_office_documents"]
        self.assertEqual(("cinnamon",), cinnamon_only.desktops)
        current = ReleaseInfo(name="CaramOS", version="1.4.0", codename="noble", channel="stable")
        for pending, listed in (([cinnamon_only, everywhere], [everywhere]), ([cinnamon_only], [cinnamon_only])):
            with self.subTest(pending=[item.migration_id for item in pending]):
                plan = MigrationPlan(current_version="1.4.0", target_version="1.4.0", migrations=pending)
                state = {"available_update": None}
                with (
                    mock.patch.dict(os.environ, {"CARAMOS_OTA_DESKTOP": "xfce"}),
                    mock.patch.object(apt, "resolve_update_plan", return_value=plan),
                    mock.patch.object(apt, "save_state"),
                ):
                    _, updates = apt.detect_updates(current, state)
                # Whether there is an update, and what the runner does, stay as they were.
                self.assertEqual(len(pending), len(updates))
                self.assertEqual([item.migration_id for item in pending], state["available_update"]["migration_ids"])
                self.assertEqual([item.title for item in listed],
                                 [package["name"] for package in state["available_update"]["packages"]])


if __name__ == "__main__":
    unittest.main()

"""Tests for product-target and metadata-only OTA detection."""

from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()

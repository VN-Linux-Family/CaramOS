"""20261125130200_online_accounts_sign_in: Firefox hands the Online Accounts sign-in back without asking."""

from __future__ import annotations

import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext

from caramos_ota_update import firefox_policies

migration = importlib.import_module("caramos_ota_update.migrations.20261125130200_online_accounts_sign_in.migration")
apps_site = importlib.import_module("caramos_ota_update.migrations.20261125130300_apps_site_install_links.migration")
ROOT = Path(__file__).resolve().parents[1]
GOOGLE = migration.GOOGLE_SCHEME


class OnlineAccountsSignInTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp())
        self.policies = self.folder / "etc/firefox/policies/policies.json"
        self.distribution = self.folder / "usr/lib/firefox/distribution/policies.json"
        for name, path in (("POLICIES", self.policies), ("DISTRIBUTION", self.distribution)):
            patcher = mock.patch.object(firefox_policies, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_migration(self) -> None:
        migration.run(MigrationContext(dry_run=False))

    def entries(self) -> dict:
        document = json.loads(self.policies.read_text(encoding="utf-8"))
        return {entry["protocol"]: entry["allowed_origins"] for entry in document["policies"]["AutoLaunchProtocolsFromOrigins"]}

    def test_the_handler_links_open_from_the_sign_in_pages_only(self) -> None:
        self.run_migration()
        self.assertEqual({GOOGLE: ["https://accounts.google.com"],
                          "goa-oauth2": ["https://login.microsoftonline.com", "https://login.live.com"]}, self.entries())

    def test_the_scheme_is_the_one_gnome_online_accounts_registers(self) -> None:
        self.assertEqual("com.googleusercontent.apps.44438659992-7kgjeitenc16ssihbtdjbgguch7ju55s", GOOGLE)

    def test_without_a_file_it_starts_from_mints_distribution_policies(self) -> None:
        self.distribution.parent.mkdir(parents=True)
        self.distribution.write_text(json.dumps({"policies": {"DisableAppUpdate": True}}), encoding="utf-8")
        self.run_migration()
        document = json.loads(self.policies.read_text(encoding="utf-8"))
        self.assertTrue(document["policies"]["DisableAppUpdate"])
        self.assertIn(GOOGLE, self.entries())

    def test_a_company_file_keeps_its_keys_and_entries(self) -> None:
        # CaramOS Doanh nghiệp writes its keys in the same file.
        self.policies.parent.mkdir(parents=True)
        company = {"policies": {"Homepage": {"URL": "https://intranet.example", "Locked": True},
                                "AutoLaunchProtocolsFromOrigins": [{"protocol": "zoommtg", "allowed_origins": ["https://zoom.us"]},
                                                                   {"protocol": GOOGLE, "allowed_origins": ["https://example.org"]}]}}
        self.policies.write_text(json.dumps(company), encoding="utf-8")
        self.run_migration()
        document = json.loads(self.policies.read_text(encoding="utf-8"))
        self.assertEqual({"URL": "https://intranet.example", "Locked": True}, document["policies"]["Homepage"])
        entries = self.entries()
        self.assertEqual(["https://zoom.us"], entries["zoommtg"])
        self.assertEqual(["https://example.org", "https://accounts.google.com"], entries[GOOGLE])

    def test_running_twice_changes_nothing(self) -> None:
        self.run_migration()
        first = self.policies.read_text(encoding="utf-8")
        self.run_migration()
        self.assertEqual(first, self.policies.read_text(encoding="utf-8"))

    def test_a_broken_file_is_left_alone(self) -> None:
        self.policies.parent.mkdir(parents=True)
        self.policies.write_text("{not json", encoding="utf-8")
        self.run_migration()
        self.assertEqual("{not json", self.policies.read_text(encoding="utf-8"))

    def test_the_apps_website_opens_the_app_center_without_asking(self) -> None:
        self.run_migration()
        apps_site.run(MigrationContext(dry_run=False))
        entries = self.entries()
        self.assertEqual(["https://apps.vietnamlinuxfamily.net"], entries["caramos-app"])
        self.assertIn(GOOGLE, entries)
        apps_site.run(MigrationContext(dry_run=False))
        self.assertEqual(3, len(json.loads(self.policies.read_text(encoding="utf-8"))["policies"]["AutoLaunchProtocolsFromOrigins"]))

    def test_the_manifest_runs_anytime_on_both_editions(self) -> None:
        manifest = json.loads((ROOT / "usr/lib/python3/dist-packages/caramos_ota_update/migrations"
                               / "20261125130200_online_accounts_sign_in/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("anytime", manifest["unattended"])
        self.assertNotIn("desktops", manifest)
        self.assertTrue(manifest["release_notes_vi"] and manifest["release_notes_en"])


if __name__ == "__main__":
    unittest.main()

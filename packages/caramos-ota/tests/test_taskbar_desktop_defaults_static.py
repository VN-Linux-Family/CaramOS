"""Static checks for fresh ISO taskbar pins and Desktop cleanup."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[3]
TARGET_IDS = (
    "google-chrome.desktop",
    "wps-office-prometheus.desktop",
    "zalo.desktop",
    "mintinstall.desktop",
    "cinnamon-settings.desktop",
)


@unittest.skipUnless((ROOT / "config").is_dir(), "fresh ISO tree unavailable")
class TaskbarDesktopDefaultsStaticTests(unittest.TestCase):
    def test_fresh_iso_defaults_include_required_taskbar_pins(self) -> None:
        files = (
            ROOT / "config/includes.chroot/etc/dconf/db/local.d/00-caramos-theme",
            ROOT / "config/hooks/live/0100-caramos-setup.hook.chroot",
            ROOT / "config/hooks/live/0170-cinnamon-task17-spices.hook.chroot",
        )
        for path in files:
            source = path.read_text(encoding="utf-8")
            for desktop_id in TARGET_IDS:
                self.assertIn(desktop_id, source, str(path))

    def test_grouped_window_list_schema_has_required_pins(self) -> None:
        schema_path = (
            ROOT
            / "config/includes.chroot/usr/share/cinnamon/applets/grouped-window-list@cinnamon.org/settings-schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.assertEqual(list(TARGET_IDS), schema["pinned-apps"]["default"])

    def test_fresh_iso_does_not_seed_stock_desktop_shortcuts(self) -> None:
        desktop = ROOT / "config/includes.chroot/etc/skel/Desktop"
        for filename in (
            "wps-office-prometheus.desktop",
            "zalo.desktop",
            "mintinstall.desktop",
        ):
            self.assertFalse((desktop / filename).exists())

    def test_zalo_hook_installs_application_launcher_only(self) -> None:
        hook = ROOT / "config/hooks/live/0300-zalo-unoffical.hook.chroot"
        source = hook.read_text(encoding="utf-8")
        self.assertIn('/usr/share/applications/zalo.desktop', source)
        self.assertNotIn("SKEL_DESKTOP", source)
        self.assertNotIn('/etc/skel/Desktop', source)


if __name__ == "__main__":
    unittest.main()

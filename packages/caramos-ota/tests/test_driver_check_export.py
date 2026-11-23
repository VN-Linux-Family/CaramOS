"""Driver Check > Lưu báo cáo (export.py): the findings as a web page and as JSON, and the button that saves them."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "usr/share/caramos-ota/driver-check"))

from caramos_driver_check import export  # noqa: E402
from caramos_driver_check.demo import DemoScanner  # noqa: E402

WHEN = datetime(2026, 11, 22, 9, 30)
SYSTEM = {"model": "Dell Latitude 5490 <test & co>", "board": "Dell Inc. 0KP0FT", "cpu": "Intel Core i5-8250U",
          "threads": 8, "memory": 8 * 1024 ** 3, "uefi": True, "system": "CaramOS 1.4.0 Cinnamon",
          "disks": [{"model": "SAMSUNG MZ7LN256", "size": 256 * 1024 ** 3, "ssd": True, "connection": "sata"}]}


def scan(case: str):
    scanner = DemoScanner(case)
    snapshot = scanner.snapshot()
    with mock.patch("time.sleep"):
        proposals = scanner.proposals(snapshot)
    return scanner.analyze(snapshot, proposals), snapshot


class ExportTests(unittest.TestCase):
    def test_page_and_json(self) -> None:
        report, snapshot = scan("live")
        with tempfile.TemporaryDirectory() as tmp:
            page, data = export.save(Path(tmp) / "báo cáo", report, snapshot, WHEN, SYSTEM)
            self.assertEqual(("báo cáo.html", "báo cáo.json"), (page.name, data.name))
            html = page.read_text(encoding="utf-8")
            parsed = json.loads(data.read_text(encoding="utf-8"))
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn('<meta charset="utf-8">', html)
        self.assertIn("Dell Latitude 5490 &lt;test &amp; co&gt;", html)
        self.assertNotIn("<test & co>", html)
        self.assertIn("Broadcom BCM4360", html)          # the problem found and the device list
        self.assertIn("8.0 GB", html)
        self.assertIn("256.0 GB", html)
        self.assertIn("UEFI", html)
        self.assertIn("2026-11-22T09:30:00", parsed["saved"])
        self.assertEqual("Intel Core i5-8250U", parsed["computer"]["cpu"])
        self.assertTrue(parsed["result"]["live"])
        self.assertTrue(any(device["id"] == "14e4:43a0" for device in parsed["devices"]))
        self.assertTrue(any(device["driver"] == "btusb" for device in parsed["devices"]), "USB drivers too")

    def test_nothing_to_do_and_no_overwrite_of_the_json(self) -> None:
        report, snapshot = scan("ok")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "r.json").write_text("mine", encoding="utf-8")
            page, data = export.save(Path(tmp) / "r.html", report, snapshot, WHEN, SYSTEM)
            self.assertEqual("mine", (Path(tmp) / "r.json").read_text(encoding="utf-8"))
            self.assertEqual("r (2).json", data.name)
            self.assertNotIn("<h2>To do</h2>", page.read_text(encoding="utf-8"))

    def test_no_snapshot(self) -> None:
        report, _snapshot = scan("nvidia")
        self.assertEqual([], export.devices(None))
        self.assertIn("NVIDIA", export.report_html(report, None, {}, WHEN))

    def test_system_info_from_sysfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dmi = root / "sys/class/dmi/id"
            dmi.mkdir(parents=True)
            for name, value in (("sys_vendor", "HP"), ("product_name", "ProDesk 400 G4 MT"),
                                ("product_version", "To Be Filled By O.E.M.")):
                (dmi / name).write_text(value + "\n", encoding="utf-8")
            (root / "proc").mkdir()
            (root / "proc/cpuinfo").write_text("model name\t: Intel(R) Core(TM) i3-7100\n", encoding="utf-8")
            (root / "proc/meminfo").write_text("MemTotal:        4022412 kB\n", encoding="utf-8")
            (root / "etc").mkdir()
            (root / "etc/os-release").write_text('PRETTY_NAME="CaramOS 1.4.0 Cinnamon"\n', encoding="utf-8")
            with mock.patch.object(export.subprocess, "run", side_effect=OSError):
                info = export.system_info(root)
        self.assertEqual("HP ProDesk 400 G4 MT", info["model"])
        self.assertEqual("Intel(R) Core(TM) i3-7100", info["cpu"])
        self.assertEqual(4022412 * 1024, info["memory"])
        self.assertEqual("CaramOS 1.4.0 Cinnamon", info["system"])
        self.assertFalse(info["uefi"])

    def test_the_results_page_has_the_button(self) -> None:
        results = (ROOT / "usr/share/caramos-ota/driver-check/caramos_driver_check/ui/results.py").read_text(
            encoding="utf-8")
        window = (ROOT / "usr/share/caramos-ota/driver-check/caramos_driver_check/ui/window.py").read_text(
            encoding="utf-8")
        self.assertIn('_("Save report")', results)
        self.assertIn("on_save=self.save_report", window)
        self.assertIn("Gtk.FileDialog", window)


if __name__ == "__main__":
    unittest.main()

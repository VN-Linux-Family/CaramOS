from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from caramos_ota_audit import cli


class CaramOSTest(unittest.TestCase):
    def test_build_report_from_args(self) -> None:
        args = cli.build_parser().parse_args(
            [
                "--cli",
                "--summary",
                "App crash",
                "--steps",
                "open app; click button",
                "--expected",
                "App stays open",
                "--actual",
                "App exits",
                "--area",
                "UI",
            ]
        )
        report = cli.build_report_from_args(args)
        self.assertEqual(report.summary, "App crash")
        self.assertEqual(report.steps, ["open app", "click button"])
        self.assertEqual(report.expected, "App stays open")
        self.assertEqual(report.actual, "App exits")
        self.assertEqual(report.area, "UI")

    def test_create_audit_bundle_fallback(self) -> None:
        report = cli.AuditReport(
            summary="Crash",
            steps=["open", "click"],
            expected="No crash",
            actual="Crash",
            area="UI",
            created_at="2026-07-29T00:00:00+00:00",
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = cli.create_audit_bundle(report, tmp)
            self.assertTrue(result.bundle_path.exists())
            self.assertEqual(result.output_dir, Path(tmp))
            self.assertEqual(len(result.bundle_sha256), 64)

    def test_main_cli_prints_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("caramos_ota_audit.cli._has_display", return_value=False):
            code = cli.main(
                [
                    "--cli",
                    "--summary",
                    "Crash",
                    "--steps",
                    "open",
                    "--expected",
                    "No crash",
                    "--actual",
                    "Crash",
                    "--area",
                    "UI",
                    "--output",
                    tmp,
                ]
            )
            self.assertEqual(code, 0)

    def test_cli_allows_one_click_collection_without_report_fields(self) -> None:
        report = cli.build_report_from_args(cli.build_parser().parse_args(["--cli"]))
        self.assertEqual(report.area, "automatic")
        self.assertTrue(report.summary)
        self.assertTrue(report.steps)


if __name__ == "__main__":
    unittest.main()

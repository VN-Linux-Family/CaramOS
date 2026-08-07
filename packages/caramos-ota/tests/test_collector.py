from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from caramos_ota_audit.collector import collect_audit
from caramos_ota_audit.sources import command_source, file_source


class CollectorTest(unittest.TestCase):
    def test_collect_audit_continues_on_failure_and_redacts(self) -> None:
        calls: list[tuple[str, ...]] = []

        def fake_command_runner(command: list[str] | tuple[str, ...], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
            calls.append(tuple(command))
            if command[0] == "uname":
                return subprocess.CompletedProcess(command, 0, stdout="name=CaramOS\nowner=alice@example.com\npassword=secret\n", stderr="")
            raise RuntimeError("boom")

        def fake_file_reader(path: Path, max_bytes: int, max_lines: int) -> tuple[str, bool]:
            if path.name == "os-release":
                return "NAME=CaramOS\nVERSION=1.2.3\nCONTACT=admin@example.com\n", False
            raise FileNotFoundError(path)

        report = collect_audit(
            sources=(
                file_source("/etc/os-release", name="os-release"),
                command_source(("uname", "-a"), name="uname"),
                command_source(("id",), name="id"),
            ),
            command_runner=fake_command_runner,
            file_reader=fake_file_reader,
        )

        summary = report.summary()
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["ok"], 2)
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(calls[0][0], "uname")
        os_release = report.sources[0]
        self.assertEqual(os_release.data["CONTACT"], "[REDACTED_EMAIL]")
        self.assertEqual(report.sources[1].data["owner"], "[REDACTED_EMAIL]")
        self.assertEqual(report.sources[2].status, "failed")
        self.assertIn("boom", report.notes[0])


if __name__ == "__main__":
    unittest.main()

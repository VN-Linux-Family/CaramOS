from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from caramos_ota_audit.archive import build_archive_bytes, write_archive, create_audit_bundle
from caramos_ota_audit.models import AuditReport, AuditSourceResult


class ArchiveTest(unittest.TestCase):
    def test_write_archive_contains_summary_and_sources(self) -> None:
        report = AuditReport(
            schema_version=1,
            collected_at="2026-07-29T00:00:00+00:00",
            system={"hostname": "caram"},
            sources=(
                AuditSourceResult(
                    name="os release",
                    kind="file",
                    target="/etc/os-release",
                    status="ok",
                    collected_at="2026-07-29T00:00:00+00:00",
                    elapsed_ms=1,
                    data={"NAME": "CaramOS"},
                ),
                AuditSourceResult(
                    name="/etc/apt/sources.list.d/main",
                    kind="directory",
                    target="/etc/apt/sources.list.d",
                    status="ok",
                    collected_at="2026-07-29T00:00:00+00:00",
                    elapsed_ms=2,
                    data=[],
                ),
            ),
        )

        archive_bytes = build_archive_bytes(report)
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
            names = tar.getnames()
            self.assertIn("manifest.json", names)
            self.assertIn("report.json", names)
            self.assertIn("report.md", names)
            self.assertIn("checksums.sha256", names)
            self.assertIn("redaction-policy.txt", names)
            self.assertIn("redaction-summary.json", names)
            self.assertIn("failures.json", names)
            self.assertIn("sources/000-os_release.json", names)
            self.assertIn("sources/001-etc_apt_sources.list.d_main.json", names)
            report_file = tar.extractfile("report.json")
            assert report_file is not None
            self.assertIn(b"CaramOS", report_file.read())
            self.assertTrue(all(not name.startswith("/") and ".." not in Path(name).parts for name in names))

        with tempfile.TemporaryDirectory() as tmpdir:
            out = write_archive(report, Path(tmpdir) / "audit.tar.gz")
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 0)

    def test_create_audit_bundle_returns_hash_and_paths(self) -> None:
        report = AuditReport(
            schema_version=1,
            collected_at="2026-07-29T00:00:00+00:00",
            system={"hostname": "caram"},
            sources=(),
        )
        stages: list[tuple[str, dict[str, object]]]=[]
        with tempfile.TemporaryDirectory() as tmpdir:
            result = create_audit_bundle(report, tmpdir, progress_callback=lambda stage, payload: stages.append((stage, payload)))
            self.assertTrue(result.archive_path.exists())
            self.assertTrue(result.metadata_path.exists())
            self.assertTrue(result.summary_path.exists())
            self.assertEqual(len(result.sha256), 64)
            self.assertGreater(result.archive_size, 0)
            self.assertGreaterEqual(len(stages), 3)


if __name__ == "__main__":
    unittest.main()

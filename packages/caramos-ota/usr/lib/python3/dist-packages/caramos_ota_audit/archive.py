"""Create bounded, offline CaramOS audit archives."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import tarfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from caramos_ota_audit.models import AuditReport
from caramos_ota_audit.redaction import redact_value

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_ARCHIVE_BYTES = 20 * 1024 * 1024


@dataclass(frozen=True)
class AuditBundleResult:
    """Result of archive bundle creation."""

    archive_path: Path
    sha256: str
    archive_size: int
    report: AuditReport
    metadata_path: Path
    summary_path: Path

    @property
    def bundle_path(self) -> Path:
        return self.archive_path

    @property
    def bundle_sha256(self) -> str:
        return self.sha256

    @property
    def output_dir(self) -> Path:
        return self.archive_path.parent

    @property
    def report_path(self) -> Path:
        return self.metadata_path


def _safe_name(name: str) -> str:
    slug = _SAFE_NAME_RE.sub("_", name).strip("._-")
    return slug or "source"


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _tarinfo(name: str, data: bytes) -> tarfile.TarInfo:
    if name.startswith("/") or ".." in Path(name).parts:
        raise ValueError(f"unsafe archive member: {name}")
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mtime = 0
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    return info


def _progress(progress_callback: Callable[..., None] | None, stage: str, **payload: Any) -> None:
    if progress_callback is not None:
        try:
            progress_callback(stage, payload)
        except TypeError:
            progress_callback(stage)


def _report_entries(report: AuditReport) -> list[tuple[str, bytes]]:
    safe_report = redact_value(report.to_dict())
    sources = safe_report.get("sources", [])
    collected_at = safe_report.get("collected_at", "")
    summary = safe_report.get("summary", {})
    entries: list[tuple[str, bytes]] = [
        ("manifest.json", _json_bytes({
            "schema_version": 1,
            "collector": "caramos-ota-audit",
            "collected_at": collected_at,
            "summary": summary,
            "sources": [item.get("name", "") for item in sources],
        })),
        ("report.json", _json_bytes(safe_report)),
        ("report.md", _render_report_markdown(safe_report).encode("utf-8")),
        ("redaction-policy.txt", (
            "Redaction is applied before archive creation.\n"
            "Secrets, credentials, private keys, email addresses, hostnames, local home paths, IP and MAC addresses are replaced.\n"
            "The collector does not upload data or read browser profiles, clipboard history, SSH/GPG data, keyrings, or network secret profiles.\n"
        ).encode("utf-8")),
        ("redaction-summary.json", _json_bytes({"applied": True, "placeholder": "[REDACTED]"})),
        ("failures.json", _json_bytes({
            "failures": [item for item in sources if item.get("status") == "failed"],
        })),
    ]
    checksums = hashlib.sha256
    checksum_text = "".join(f"{checksums(data).hexdigest()}  {name}\n" for name, data in entries)
    entries.append(("checksums.sha256", checksum_text.encode("utf-8")))
    for index, source in enumerate(sources):
        name = f"sources/{index:03d}-{_safe_name(str(source.get('name', 'source')))}.json"
        entries.append((name, _json_bytes(source)))
    return entries


def _render_report_markdown(report: dict[str, Any]) -> str:
    user = next((item.get("data") for item in report.get("sources", []) if item.get("name") == "user-report"), {})
    if not isinstance(user, dict):
        user = {}
    steps = user.get("steps") or []
    lines = [
        "# CaramOS Audit Report", "", f"- Area: {user.get('area', '')}",
        f"- Created at: {user.get('created_at', report.get('collected_at', ''))}", "",
        "## Summary", str(user.get("summary", "")), "", "## Steps",
    ]
    lines.extend(f"- {step}" for step in steps)
    lines += ["", "## Expected", str(user.get("expected", "")), "", "## Actual", str(user.get("actual", "")), ""]
    return "\n".join(lines)


def build_archive_bytes(report: AuditReport) -> bytes:
    """Return gzipped tar archive bytes for redacted report."""
    stream = io.BytesIO()
    with gzip.GzipFile(fileobj=stream, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w|", format=tarfile.PAX_FORMAT) as tar:
            for name, data in _report_entries(report):
                tar.addfile(_tarinfo(name, data), io.BytesIO(data))
    payload = stream.getvalue()
    if len(payload) > _MAX_ARCHIVE_BYTES:
        raise ValueError(f"audit archive exceeds {_MAX_ARCHIVE_BYTES} bytes")
    return payload


def _next_archive_path(destination: Path, stamp: str) -> Path:
    base = destination / f"CaramOS-audit-{stamp}.tar.gz"
    if not base.exists():
        return base
    index = 2
    while True:
        candidate = destination / f"CaramOS-audit-{stamp}-{index}.tar.gz"
        if not candidate.exists():
            return candidate
        index += 1


def create_audit_bundle(report: AuditReport, output_dir: str | Path, progress_callback: Callable[..., None] | None = None) -> AuditBundleResult:
    """Create one atomically-installed audit bundle in output directory."""
    destination = Path(output_dir).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    _progress(progress_callback, "collecting", output_dir=str(destination))
    _progress(progress_callback, "building", sources=len(report.sources))
    archive_bytes = build_archive_bytes(report)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive_path = _next_archive_path(destination, stamp)
    temporary = archive_path.with_name(f".{archive_path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_bytes(archive_bytes)
        os.replace(temporary, archive_path)
    finally:
        temporary.unlink(missing_ok=True)
    sha256 = hashlib.sha256(archive_bytes).hexdigest()
    _progress(progress_callback, "complete", path=str(archive_path), bytes=len(archive_bytes), sha256=sha256)
    return AuditBundleResult(
        archive_path=archive_path,
        sha256=sha256,
        archive_size=len(archive_bytes),
        report=report,
        metadata_path=archive_path,
        summary_path=archive_path,
    )


def write_archive(report: AuditReport, destination: str | Path) -> Path:
    """Write archive bytes atomically to destination."""
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = build_archive_bytes(report)
    temporary = target.with_name(f".{target.name}.tmp-{os.getpid()}")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target

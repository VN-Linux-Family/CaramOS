"""Audit bundle CLI for CaramOS."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import textwrap
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable


def _load_collector_api():
    """Return collector API when available."""

    try:
        from .archive import AuditBundleResult as CollectorAuditResult
        from .archive import create_audit_bundle as collector_create_audit_bundle
        from .collector import collect_audit
        from .models import AuditReport as CollectorAuditReport, AuditSourceResult
    except Exception:
        return None
    return CollectorAuditReport, CollectorAuditResult, collector_create_audit_bundle, collect_audit, AuditSourceResult


def _collect_report(report: AuditReport, output_dir, progress_callback=None):
    """Collect environment evidence and attach user reproduction report."""

    collector_api = _load_collector_api()
    if collector_api is None:
        return None
    _, _, _, collect_audit, AuditSourceResult = collector_api
    evidence = collect_audit()
    user_data = {
        "summary": report.summary,
        "steps": list(report.steps),
        "expected": report.expected,
        "actual": report.actual,
        "area": report.area,
        "created_at": report.created_at or _now_iso(),
    }
    user_source = AuditSourceResult(
        name="user-report",
        kind="report",
        target="user-input",
        status="ok",
        collected_at=evidence.collected_at,
        elapsed_ms=0,
        data=user_data,
    )
    return dataclasses.replace(evidence, sources=evidence.sources + (user_source,))


@dataclass(frozen=True)
class AuditReport:
    """Audit request payload."""

    summary: str
    steps: list[str]
    expected: str
    actual: str
    area: str
    created_at: str | None = None


@dataclass(frozen=True)
class AuditResult:
    """Audit bundle result."""

    bundle_path: Path
    bundle_sha256: str
    output_dir: Path
    report_path: Path | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slugify(text: str, *, fallback: str = "audit") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or fallback


def _split_steps(steps: str | Iterable[str]) -> list[str]:
    if isinstance(steps, str):
        items = [part.strip() for part in re.split(r"\r?\n+|\s*;\s*", steps) if part.strip()]
        return items or [steps.strip()] if steps.strip() else []
    return [str(step).strip() for step in steps if str(step).strip()]


def _progress(progress_callback: Callable[[str], None] | None, message: str) -> None:
    if progress_callback is not None:
        progress_callback(message)


def _render_report_json(report: AuditReport) -> str:
    payload = {
        "summary": report.summary,
        "steps": report.steps,
        "expected": report.expected,
        "actual": report.actual,
        "area": report.area,
        "created_at": report.created_at or _now_iso(),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _render_report_text(report: AuditReport) -> str:
    steps = "\n".join(f"- {step}" for step in report.steps) or "- (không có bước)"
    return textwrap.dedent(
        f"""
        CaramOS Audit Report
        ====================

        Summary:
        {report.summary}

        Area:
        {report.area}

        Steps:
        {steps}

        Expected:
        {report.expected}

        Actual:
        {report.actual}

        Created at:
        {report.created_at or _now_iso()}
        """
    ).strip() + "\n"


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fallback_create_audit_bundle(
    report: AuditReport,
    output_dir: str | os.PathLike[str],
    progress_callback: Callable[[str], None] | None = None,
) -> AuditResult:
    output_path = Path(output_dir).expanduser()
    output_path.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    stem = f"caramos-audit-{stamp}-{_slugify(report.summary)}"
    bundle_path = output_path / f"{stem}.zip"
    report_path_name = f"{stem}/report.json"
    text_path_name = f"{stem}/report.txt"
    meta_path_name = f"{stem}/metadata.json"

    _progress(progress_callback, "Chuẩn bị gói báo cáo")
    payload = dataclasses.asdict(report)
    payload["created_at"] = report.created_at or _now_iso()

    _progress(progress_callback, "Ghi nội dung báo cáo")
    with zipfile.ZipFile(bundle_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(report_path_name, _render_report_json(report))
        archive.writestr(text_path_name, _render_report_text(report))
        archive.writestr(
            meta_path_name,
            json.dumps(
                {
                    "bundle_name": bundle_path.name,
                    "created_at": payload["created_at"],
                    "area": report.area,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
        )

    _progress(progress_callback, "Tính mã kiểm tra")
    bundle_sha256 = _hash_file(bundle_path)
    return AuditResult(
        bundle_path=bundle_path,
        bundle_sha256=bundle_sha256,
        output_dir=output_path,
        report_path=bundle_path,
    )


def create_audit_bundle(
    report: AuditReport,
    output_dir: str | os.PathLike[str],
    progress_callback: Callable[[str], None] | None = None,
) -> AuditResult:
    """Create audit bundle with collector API when present."""

    collector_api = _load_collector_api()
    if collector_api is None:
        return _fallback_create_audit_bundle(report, output_dir, progress_callback=progress_callback)

    CollectorAuditReport, CollectorAuditResult, collector_create_audit_bundle, _, _ = collector_api
    collector_report = _collect_report(report, output_dir, progress_callback)
    if collector_report is None:
        return _fallback_create_audit_bundle(report, output_dir, progress_callback=progress_callback)

    result = collector_create_audit_bundle(collector_report, output_dir, progress_callback=progress_callback)
    if isinstance(result, CollectorAuditResult):
        bundle_path = Path(getattr(result, "archive_path"))
        bundle_sha256 = str(getattr(result, "sha256", ""))
        output_path = bundle_path.parent
        report_path = getattr(result, "metadata_path", None)
        return AuditResult(
            bundle_path=bundle_path,
            bundle_sha256=bundle_sha256,
            output_dir=output_path,
            report_path=Path(report_path) if report_path else None,
        )
    if isinstance(result, dict):
        return AuditResult(
            bundle_path=Path(result.get("bundle_path", "")),
            bundle_sha256=str(result.get("bundle_sha256", "")),
            output_dir=Path(result.get("output_dir", output_dir)),
            report_path=Path(result["report_path"]) if result.get("report_path") else None,
        )
    return result


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""

    parser = argparse.ArgumentParser(
        prog="caramos-ota-audit",
        description="Create offline CaramOS audit bundle.",
    )
    parser.add_argument("--cli", action="store_true", help="Run headless and print result path")
    parser.add_argument("--summary", help="Optional short symptom note")
    parser.add_argument("--steps", help="Optional reproduction steps")
    parser.add_argument("--expected", help="Optional expected result")
    parser.add_argument("--actual", help="Optional actual result")
    parser.add_argument("--area", help="Optional affected area")
    parser.add_argument("--output", help="Output directory for bundle", default=str(Path.home() / "Desktop"))
    return parser


def build_report_from_args(args: argparse.Namespace) -> AuditReport:
    """Build optional user context for automatic collection."""

    summary = str(args.summary or "").strip()
    return AuditReport(
        summary=summary or "Báo cáo tự động sau khi lỗi xảy ra",
        steps=_split_steps(str(args.steps or "")) or ["Người dùng tái hiện lỗi rồi chạy CaramOS Audit"],
        expected=str(args.expected or "").strip() or "Tính năng hoạt động bình thường",
        actual=str(args.actual or "").strip() or summary or "Xem trạng thái và log được thu thập tự động",
        area=str(args.area or "").strip() or "automatic",
        created_at=_now_iso(),
    )


def _print_cli_result(result: AuditResult) -> None:
    print(f"Bundle: {result.bundle_path}")
    print(f"SHA256: {result.bundle_sha256}")
    print(f"Folder: {result.output_dir}")


def main(argv: list[str] | None = None) -> int:
    """Run CaramOS audit CLI."""

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cli or not _has_display():
        report = build_report_from_args(args)
        result = create_audit_bundle(report, args.output)
        _print_cli_result(result)
        return 0

    from .ui import run_gui

    run_gui(
        summary=args.summary or "",
        steps=args.steps or "",
        expected=args.expected or "",
        actual=args.actual or "",
        area=args.area or "",
        output_dir=args.output,
    )
    return 0


def _has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


if __name__ == "__main__":
    raise SystemExit(main())

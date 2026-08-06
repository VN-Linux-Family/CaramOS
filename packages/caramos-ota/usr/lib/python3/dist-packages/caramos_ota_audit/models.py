"""Data models for CaramOS audit collection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AuditSourceResult:
    """One collected audit source."""

    name: str
    kind: str
    target: str
    status: str
    collected_at: str
    elapsed_ms: int
    data: Any | None = None
    error: str | None = None
    truncated: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-friendly payload."""

        payload: dict[str, Any] = {
            "name": self.name,
            "kind": self.kind,
            "target": self.target,
            "status": self.status,
            "collected_at": self.collected_at,
            "elapsed_ms": self.elapsed_ms,
            "truncated": self.truncated,
        }
        if self.data is not None:
            payload["data"] = self.data
        if self.error is not None:
            payload["error"] = self.error
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class AuditReport:
    """Complete audit collection."""

    schema_version: int
    collected_at: str
    system: dict[str, Any]
    sources: tuple[AuditSourceResult, ...]
    notes: tuple[str, ...] = ()

    def summary(self) -> dict[str, int]:
        """Return compact counts for staging and dashboards."""

        counts = {"total": len(self.sources), "ok": 0, "failed": 0, "skipped": 0, "truncated": 0}
        for source in self.sources:
            counts[source.status] = counts.get(source.status, 0) + 1
            if source.truncated:
                counts["truncated"] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-friendly payload."""

        return {
            "schema_version": self.schema_version,
            "collected_at": self.collected_at,
            "system": dict(self.system),
            "summary": self.summary(),
            "notes": list(self.notes),
            "sources": [source.to_dict() for source in self.sources],
        }


@dataclass(frozen=True)
class AuditResult:
    """Archive bundle result."""

    archive_path: str
    sha256: str
    report: AuditReport
    archive_size: int
    metadata_path: str
    summary_path: str

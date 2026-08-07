"""Offline audit collection."""

from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic
from typing import Any

from caramos_ota_audit.models import AuditReport, AuditSourceResult
from caramos_ota_audit.redaction import redact_text, redact_value
from caramos_ota_audit.sources import AuditSource, default_sources

CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]
FileReader = Callable[[Path, int, int], tuple[str, bool]]


class AuditCollectionError(RuntimeError):
    """Raised when collection stops early or source validation fails."""


@dataclass(frozen=True)
class _FilePayload:
    text: str
    truncated: bool


@dataclass(frozen=True)
class _CommandPayload:
    stdout: str
    stderr: str
    returncode: int
    truncated: bool


def _system_context() -> dict[str, Any]:
    return redact_value(
        {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "executable": os.path.basename(sys.executable),
            "session_type": os.environ.get("XDG_SESSION_TYPE", ""),
        }
    )


def _default_command_runner(command: Sequence[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/sbin:/usr/bin:/sbin:/bin"),
        "LC_ALL": "C",
        "LANG": "C",
    }
    return subprocess.run(
        list(command),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        cwd="/",
        env=env,
    )


def _read_file(path: Path, max_bytes: int, max_lines: int) -> tuple[str, bool]:
    if not path.exists():
        raise FileNotFoundError(path)
    chunks: list[str] = []
    total_bytes = 0
    total_lines = 0
    truncated = False
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            encoded = line.encode("utf-8", errors="replace")
            if total_bytes + len(encoded) > max_bytes:
                remaining = max(0, max_bytes - total_bytes)
                if remaining:
                    chunks.append(encoded[:remaining].decode("utf-8", errors="replace"))
                truncated = True
                break
            chunks.append(line)
            total_bytes += len(encoded)
            total_lines += 1
            if total_lines >= max_lines:
                truncated = True
                break
    return "".join(chunks), truncated


def _parse_key_value_text(text: str) -> dict[str, str] | None:
    values: dict[str, str] = {}
    seen_line = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            return None
        seen_line = True
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"')
    return values if seen_line else None


def _parse_command_stdout(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return ""
    parsed_kv = _parse_key_value_text(text)
    if parsed_kv is not None:
        return parsed_kv
    if stripped[:1] in "[{":
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    return text


def _collect_file_source(source: AuditSource, file_reader: FileReader) -> AuditSourceResult:
    started = monotonic()
    try:
        text, truncated = file_reader(Path(source.target), source.max_bytes, source.max_lines)
        payload: Any = _parse_key_value_text(text) or text
        payload = redact_value(payload)
        return AuditSourceResult(
            name=source.name,
            kind=source.kind,
            target=redact_text(source.target),
            status="ok",
            collected_at="",
            elapsed_ms=int((monotonic() - started) * 1000),
            data=payload,
            truncated=truncated,
        )
    except Exception as exc:
        return AuditSourceResult(
            name=source.name,
            kind=source.kind,
            target=redact_text(source.target),
            status="failed",
            collected_at="",
            elapsed_ms=int((monotonic() - started) * 1000),
            error=redact_text(str(exc)),
        )


def _collect_directory_source(source: AuditSource, file_reader: FileReader) -> AuditSourceResult:
    started = monotonic()
    directory = Path(source.target)
    try:
        if not directory.exists():
            raise FileNotFoundError(directory)
        entries: list[dict[str, Any]] = []
        truncated = False
        for child in sorted(directory.iterdir(), key=lambda item: item.name):
            if not child.is_file():
                continue
            if len(entries) >= source.max_entries:
                truncated = True
                break
            text, child_truncated = file_reader(child, source.max_bytes, source.max_lines)
            entries.append(
                {
                    "name": child.name,
                    "path": redact_text(str(child)),
                    "content": redact_value(_parse_key_value_text(text) or text),
                    "truncated": child_truncated,
                }
            )
        return AuditSourceResult(
            name=source.name,
            kind=source.kind,
            target=source.target,
            status="ok",
            collected_at="",
            elapsed_ms=int((monotonic() - started) * 1000),
            data=entries,
            truncated=truncated,
            metadata={"entries": len(entries)},
        )
    except Exception as exc:
        return AuditSourceResult(
            name=source.name,
            kind=source.kind,
            target=redact_text(source.target),
            status="failed",
            collected_at="",
            elapsed_ms=int((monotonic() - started) * 1000),
            error=redact_text(str(exc)),
        )


def _collect_command_source(source: AuditSource, command_runner: CommandRunner) -> AuditSourceResult:
    started = monotonic()
    try:
        completed = command_runner(source.command, source.timeout_seconds)
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        stdout_bytes = stdout.encode("utf-8", errors="replace")
        stderr_bytes = stderr.encode("utf-8", errors="replace")
        truncated = len(stdout_bytes) > source.max_bytes or len(stderr_bytes) > source.max_bytes
        if len(stdout_bytes) > source.max_bytes:
            stdout = stdout_bytes[:source.max_bytes].decode("utf-8", errors="replace")
        if len(stderr_bytes) > source.max_bytes:
            stderr = stderr_bytes[:source.max_bytes].decode("utf-8", errors="replace")
        payload = redact_value(_parse_command_stdout(stdout))
        status = "ok" if completed.returncode == 0 else "failed"
        error = None if completed.returncode == 0 else redact_text(f"command exited with {completed.returncode}")
        metadata = {
            "command": list(source.command),
            "returncode": completed.returncode,
            "stderr": redact_text(stderr),
        }
        return AuditSourceResult(
            name=source.name,
            kind=source.kind,
            target=source.target,
            status=status,
            collected_at="",
            elapsed_ms=int((monotonic() - started) * 1000),
            data=payload,
            error=error,
            truncated=truncated,
            metadata=metadata,
        )
    except subprocess.TimeoutExpired as exc:
        return AuditSourceResult(
            name=source.name,
            kind=source.kind,
            target=source.target,
            status="failed",
            collected_at="",
            elapsed_ms=int((monotonic() - started) * 1000),
            error=redact_text(f"command timed out after {source.timeout_seconds}s: {exc}"),
        )
    except Exception as exc:
        return AuditSourceResult(
            name=source.name,
            kind=source.kind,
            target=redact_text(source.target),
            status="failed",
            collected_at="",
            elapsed_ms=int((monotonic() - started) * 1000),
            error=redact_text(str(exc)),
        )


def _collect_one(source: AuditSource, command_runner: CommandRunner, file_reader: FileReader) -> AuditSourceResult:
    if not source.is_allowed():
        raise AuditCollectionError(f"source not allowlisted: {source.kind} {source.target}")
    if source.kind == "file":
        return _collect_file_source(source, file_reader)
    if source.kind == "directory":
        return _collect_directory_source(source, file_reader)
    if source.kind == "command":
        return _collect_command_source(source, command_runner)
    raise AuditCollectionError(f"unsupported source kind: {source.kind}")


def collect_audit(
    *,
    sources: Sequence[AuditSource] | None = None,
    continue_on_failures: bool = True,
    command_runner: CommandRunner | None = None,
    file_reader: FileReader | None = None,
) -> AuditReport:
    """Collect offline audit data from allowlisted sources."""

    selected_sources = tuple(sources or default_sources())
    runner = command_runner or _default_command_runner
    reader = file_reader or _read_file
    collected_at = datetime.now().astimezone().isoformat()
    results: list[AuditSourceResult] = []
    notes: list[str] = []
    for source in selected_sources:
        result = _collect_one(source, runner, reader)
        results.append(
            AuditSourceResult(
                name=result.name,
                kind=result.kind,
                target=result.target,
                status=result.status,
                collected_at=collected_at,
                elapsed_ms=result.elapsed_ms,
                data=result.data,
                error=result.error,
                truncated=result.truncated,
                metadata=result.metadata,
            )
        )
        if result.status == "failed":
            notes.append(f"{source.name}: {result.error or 'failed'}")
            if not continue_on_failures:
                raise AuditCollectionError(notes[-1])
    return AuditReport(
        schema_version=1,
        collected_at=collected_at,
        system=_system_context(),
        sources=tuple(results),
        notes=tuple(notes),
    )

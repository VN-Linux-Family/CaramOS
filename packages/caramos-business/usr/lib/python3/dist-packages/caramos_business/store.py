"""Writing state files: whole files only (a temporary file renamed into place), so a reader never sees half a file
and a crash leaves the old one. The server and the helper both change files of the admin's state; they take
locked() around every read-modify-write."""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any


def write_atomic(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(staging, mode)
        os.replace(staging, path)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise


def write_json(path: Path, value: Any, mode: int = 0o644) -> None:
    write_atomic(path, (json.dumps(value, ensure_ascii=False, indent=1) + "\n").encode("utf-8"), mode)


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def append_line(path: Path, value: Any, mode: int = 0o644) -> None:
    """One JSON line at the end of a file (audit.jsonl)."""

    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(value, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, mode)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def read_lines(path: Path, limit: int) -> list[Any]:
    """The last limit JSON lines of a file, newest first; broken lines are skipped."""

    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - limit * 2048))
            data = handle.read()
    except OSError:
        return []
    found = []
    for raw in reversed(data.splitlines()):
        try:
            found.append(json.loads(raw.decode("utf-8")))
        except (UnicodeDecodeError, ValueError):
            continue
        if len(found) >= limit:
            break
    return found


@contextlib.contextmanager
def locked(directory: Path) -> Iterator[None]:
    """An exclusive lock on directory/.lock, between processes and between threads (each call opens its own file
    description, and flock locks conflict across descriptions)."""

    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)

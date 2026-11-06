"""The JSON-lines protocol between the privileged helper and the window."""

from __future__ import annotations

import json
import sys
from typing import Any

EVENTS = frozenset({"stage", "progress", "log", "space", "done"})


def emit(event: str, **fields: Any) -> None:
    sys.stdout.write(json.dumps({"event": event, **fields}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def parse_event(line: str) -> dict[str, Any] | None:
    """One event, or None for anything else the helper (or pkexec) printed."""

    try:
        event = json.loads(line)
    except ValueError:
        return None
    if not isinstance(event, dict) or event.get("event") not in EVENTS:
        return None
    if event["event"] == "progress":
        try:
            event["percent"] = max(0, min(100, int(event.get("percent", 0))))
        except (TypeError, ValueError):
            return None
    return event

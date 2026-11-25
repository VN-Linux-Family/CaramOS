"""Firefox's system-wide policies, as migrations change them: links of a given kind that Firefox opens without asking.

Firefox asks "Allow … to open the … link with …?" before handing a link of another program (a URL scheme) to that
program. The AutoLaunchProtocolsFromOrigins policy skips the question for one scheme, and only when the link comes
from the listed sites. The policies live in /etc/firefox/policies/policies.json; everything else in that file stays as
it is. CaramOS Doanh nghiệp writes a company's keys in the same file (caramos-business agent/src/sections/browser.rs)
and keeps what it found there. Without the file, it starts from Mint's /usr/lib/firefox/distribution/policies.json,
which Firefox no longer reads once /etc has one. A file that is not valid JSON is left alone. Firefox reads the policies
when it starts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Mapping

from caramos_ota_update.context import MigrationContext

POLICIES = Path("/etc/firefox/policies/policies.json")
DISTRIBUTION = Path("/usr/lib/firefox/distribution/policies.json")
KEY = "AutoLaunchProtocolsFromOrigins"


def merged(document: dict, entries: Iterable[Mapping]) -> dict:
    """The policies with these {protocol, allowed_origins} entries in AutoLaunchProtocolsFromOrigins; every other key,
    entry and origin kept."""

    policies = document.setdefault("policies", {})
    current = policies.get(KEY)
    if not isinstance(current, list):
        current = []
    for wanted in entries:
        same = [entry for entry in current if isinstance(entry, dict) and entry.get("protocol") == wanted["protocol"]]
        if not same:
            current.append({"protocol": wanted["protocol"], "allowed_origins": list(wanted["allowed_origins"])})
            continue
        origins = same[0].setdefault("allowed_origins", [])
        if isinstance(origins, list):
            origins.extend(origin for origin in wanted["allowed_origins"] if origin not in origins)
    policies[KEY] = current
    return document


def _load(path: Path) -> dict | None:
    """The JSON object in path; {} when the file is missing; None when it is there but unreadable or not an object."""

    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def allow_auto_launch(context: MigrationContext, entries: Iterable[Mapping]) -> bool:
    """Add the entries to Firefox's policies; False when the policies file is there but unreadable (left alone)."""

    if POLICIES.exists():
        document = _load(POLICIES)
        if document is None:
            context.log(f"{POLICIES} is not valid JSON; left as it is")
            return False
    else:
        document = _load(DISTRIBUTION) or {}
    context.write_file_if_changed(POLICIES, json.dumps(merged(document, entries), indent=2, ensure_ascii=False) + "\n")
    return True

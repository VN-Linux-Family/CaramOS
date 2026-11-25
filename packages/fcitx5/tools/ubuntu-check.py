#!/usr/bin/python3 -I
"""Has Ubuntu published a newer fcitx5 for noble than the one our patched build is made from?

CaramOS ships fcitx5 UBUNTU_VERSION+caramosN (Makefile) with the tray patch. A newer Ubuntu fcitx5 (an update or a
security fix in noble-updates or noble-security) sorts above ours, so apt would replace our build and the tray would
show the keyboard's "A" after a login again. The weekly workflow (.github/workflows/fcitx5-ubuntu.yml) runs this
check; when Ubuntu has a newer one, rebuild ours on top of it (README.md, "Khi Ubuntu cập nhật fcitx5").

Exit 0: nothing newer; 1: Ubuntu has a newer fcitx5 (printed); 2: Launchpad could not be read.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.launchpad.net/1.0/ubuntu/+archive/primary"
SERIES = "https://api.launchpad.net/1.0/ubuntu/noble"
MAKEFILE = Path(__file__).resolve().parent.parent / "Makefile"


def base_version(makefile: Path = MAKEFILE) -> str:
    match = re.search(r"^UBUNTU_VERSION\s*:=\s*(\S+)\s*$", makefile.read_text(encoding="utf-8"), re.MULTILINE)
    if not match:
        raise SystemExit("UBUNTU_VERSION not found in the Makefile")
    return match.group(1)


def published(fetch=urllib.request.urlopen) -> list[tuple[str, str]]:
    """(version, pocket) of every fcitx5 source Ubuntu publishes for noble now."""

    query = urllib.parse.urlencode({
        "ws.op": "getPublishedSources", "source_name": "fcitx5", "exact_match": "true",
        "distro_series": SERIES, "status": "Published",
    })
    with fetch(f"{API}?{query}", timeout=60) as response:
        data = json.load(response)
    return [(entry["source_package_version"], entry["pocket"]) for entry in data.get("entries", [])]


def newer(version: str, than: str) -> bool:
    return subprocess.run(["dpkg", "--compare-versions", version, "gt", than], check=False).returncode == 0


def main() -> int:
    base = base_version()
    try:
        entries = published()
    except Exception as error:  # noqa: BLE001 - any network or format problem means "could not read"
        print(f"Launchpad could not be read: {error}")
        return 2
    if not entries:
        print("Launchpad lists no published fcitx5 for noble")
        return 2
    ahead = sorted({(version, pocket) for version, pocket in entries if newer(version, base)})
    if not ahead:
        print(f"fcitx5 for noble: nothing newer than {base} ({', '.join(f'{v} {p}' for v, p in sorted(set(entries)))})")
        return 0
    print(f"Ubuntu has a newer fcitx5 than our base {base}:")
    for version, pocket in ahead:
        print(f"  {version} ({pocket})")
    return 1


if __name__ == "__main__":
    sys.exit(main())

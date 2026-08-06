#!/usr/bin/env python3
"""Atomically stamp CaramOS product and package release metadata."""

from __future__ import annotations

import argparse
import re
import tempfile
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path

VERSION_RE = re.compile(r"^\d+(?:\.\d+){1,3}(?:[-+~][A-Za-z0-9.+:~_-]+)?$")
PACKAGE_REVISION = "0caramos1"

PKG_DIR = Path(__file__).resolve().parents[1]
ROOT = PKG_DIR.parents[1]
CONFIG = ROOT / "scripts/config.sh"
CHANGELOG = PKG_DIR / "debian/changelog"
RELEASE_METADATA = PKG_DIR / "usr/lib/python3/dist-packages/caramos_ota/release_metadata.py"
CONSTANTS = PKG_DIR / "usr/lib/python3/dist-packages/caramos_ota/constants.py"


def replace_once(source: str, pattern: str, replacement: str, path: Path) -> str:
    updated, count = re.subn(pattern, replacement, source, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"expected one release marker in {path}: {pattern}")
    return updated


def update_config(source: str, version: str) -> str:
    return replace_once(
        source,
        r'^CARAMOS_VERSION="[^"]+"$',
        f'CARAMOS_VERSION="{version}"',
        CONFIG,
    )


def update_release_metadata(source: str, version: str) -> str:
    return replace_once(
        source,
        r'^PRODUCT_VERSION = "[^"]+"$',
        f'PRODUCT_VERSION = "{version}"',
        RELEASE_METADATA,
    )


def update_constants(source: str, package_version: str) -> str:
    return replace_once(
        source,
        r'^TOOL_VERSION = "[^"]+"$',
        f'TOOL_VERSION = "{package_version}"',
        CONSTANTS,
    )


def update_changelog(source: str, package_version: str, version: str, timestamp: str) -> str:
    top = source.splitlines()[0] if source else ""
    expected_prefix = "caramos-ota ("
    if not top.startswith(expected_prefix):
        raise RuntimeError(f"unexpected changelog header in {CHANGELOG}: {top!r}")
    if top == f"caramos-ota ({package_version}) noble; urgency=medium":
        return source

    entry = (
        f"caramos-ota ({package_version}) noble; urgency=medium\n\n"
        f"  * Release CaramOS {version}.\n"
        "  * Run all pending timestamp migrations by migration ID ledger.\n\n"
        " -- Vietnam Linux Family <developer@vietnamlinuxfamily.net>  "
        f"{timestamp}\n\n"
    )
    return entry + source


def atomic_write(path: Path, content: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temp = Path(handle.name)
    temp.chmod(path.stat().st_mode)
    temp.replace(path)


def prepare(version: str, *, check: bool, timestamp: str | None = None) -> None:
    if not VERSION_RE.fullmatch(version):
        raise ValueError(f"invalid CaramOS release version: {version!r}")

    package_version = f"{version}-{PACKAGE_REVISION}"
    changelog_timestamp = timestamp or format_datetime(datetime.now().astimezone())
    original = {
        CONFIG: CONFIG.read_text(encoding="utf-8"),
        RELEASE_METADATA: RELEASE_METADATA.read_text(encoding="utf-8"),
        CONSTANTS: CONSTANTS.read_text(encoding="utf-8"),
        CHANGELOG: CHANGELOG.read_text(encoding="utf-8"),
    }
    updated = {
        CONFIG: update_config(original[CONFIG], version),
        RELEASE_METADATA: update_release_metadata(original[RELEASE_METADATA], version),
        CONSTANTS: update_constants(original[CONSTANTS], package_version),
        CHANGELOG: update_changelog(original[CHANGELOG], package_version, version, changelog_timestamp),
    }

    if check:
        mismatched = [str(path.relative_to(ROOT)) for path in updated if updated[path] != original[path]]
        if mismatched:
            raise RuntimeError("release metadata is not stamped: " + ", ".join(mismatched))
        print(f"[OK] Release metadata matches {version}")
        return

    written: list[Path] = []
    try:
        for path, content in updated.items():
            if content != original[path]:
                atomic_write(path, content)
                written.append(path)
    except Exception:
        for path in written:
            atomic_write(path, original[path])
        raise

    print(f"[OK] Prepared CaramOS {version} ({package_version})")
    for path in written:
        print(f"  {path.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    prepare(args.version, check=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

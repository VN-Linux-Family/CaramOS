#!/usr/bin/env python3
"""Keep packages/veyon/4.11 in step with Veyon's releases. Run it through make:

    make check-upstream      is there a stable Veyon release newer than the one this recipe builds?
                             Exit 0: no, 1: yes, 2: GitHub could not be read.
    make bump [NEW=x.y.z]    move the recipe to that release (the newest one without NEW): a changelog entry
                             x.y.z+repack1-0caramos1 and the sha256 of its source tarball in the Makefile

The daily GitHub Actions check (.github/workflows/veyon-upstream.yml) runs the same two, then builds and tests the
packages and reports in an issue. Nothing here commits or uploads: the lab test in VMs and `make source upload` stay a
person's steps (packages/README.md, "veyon/4.11").

The sha256 is the one GitHub gives for the release asset, as the first pin in the Makefile was (upstream signs neither
the tarball nor the tag). `make orig` checks the download against it.
"""

from __future__ import annotations

import argparse
import email.utils
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = ROOT / "debian" / "changelog"
MAKEFILE = ROOT / "Makefile"
REPOSITORY = "veyon/veyon"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases?per_page=50"
DOWNLOAD_PREFIX = f"https://github.com/{REPOSITORY}/releases/download/"
RELEASE_PAGE = f"https://github.com/{REPOSITORY}/releases/tag/"
# Stable releases only (drafts and pre-releases are skipped too).
TAG = re.compile(r"v(\d+)\.(\d+)\.(\d+)")
FIRST_LINE = re.compile(r"veyon \((?P<version>(?P<upstream>\d+\.\d+\.\d+)\+repack\d+-[^)\s]+)\) ")
SHA256_LINE = re.compile(r"^UPSTREAM_SHA256 := [0-9a-f]{64}$", re.MULTILINE)
MAINTAINER = "Vietnam Linux Family <developer@vietnamlinuxfamily.net>"
DISTRIBUTION = "noble"
TIMEOUT = 60


class UpstreamError(Exception):
    pass


class Release(NamedTuple):
    version: str
    sha256: str
    page: str
    published: str = ""

    @property
    def key(self) -> tuple[int, ...]:
        return numbers(self.version)


def numbers(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def packaged(changelog: Path = CHANGELOG) -> tuple[str, str]:
    """The Debian version and the Veyon version of the newest changelog entry."""

    first = changelog.read_text(encoding="utf-8").partition("\n")[0]
    match = FIRST_LINE.match(first)
    if match is None:
        raise UpstreamError(f"{changelog}: unexpected first line {first!r}")
    return match["version"], match["upstream"]


def fetch_releases() -> list[object]:
    request = urllib.request.Request(API_URL, headers={"Accept": "application/vnd.github+json",
                                                       "User-Agent": "caramos-veyon-upstream"})
    # In GitHub Actions: the job's token, so a busy shared address does not hit the anonymous limit (60 an hour).
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN") or ""
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            data = json.load(response)
    except (OSError, ValueError) as exc:
        raise UpstreamError(f"{API_URL}: {exc}") from exc
    if not isinstance(data, list):
        raise UpstreamError(f"{API_URL}: not a list of releases")
    return data


def stable_releases(data: list[object]) -> list[Release]:
    """Every stable release that has its source tarball with the sha256 GitHub gives for it."""

    found: list[Release] = []
    for item in data:
        if not isinstance(item, dict) or item.get("draft") or item.get("prerelease"):
            continue
        tag = TAG.fullmatch(str(item.get("tag_name") or ""))
        if tag is None:
            continue
        version = ".".join(str(int(part)) for part in tag.groups())
        name = f"veyon-{version}-src.tar.bz2"
        for asset in item.get("assets") or []:
            if not isinstance(asset, dict) or asset.get("name") != name:
                continue
            digest = str(asset.get("digest") or "")
            if re.fullmatch(r"sha256:[0-9a-f]{64}", digest) and \
                    asset.get("browser_download_url") == f"{DOWNLOAD_PREFIX}v{version}/{name}":
                found.append(Release(version, digest.removeprefix("sha256:"), f"{RELEASE_PAGE}v{version}",
                                     str(item.get("published_at") or "")[:10]))
    return found


def choose(found: list[Release], version: str = "") -> Release:
    """The release of that version, or the newest one."""

    if version:
        for release in found:
            if release.version == version:
                return release
        raise UpstreamError(f"GitHub has no stable Veyon {version} with a source tarball and its sha256")
    if not found:
        raise UpstreamError("GitHub has no stable Veyon release with a source tarball and its sha256")
    return max(found, key=lambda release: release.key)


def check(version: str = "", output: str = "", changelog: Path = CHANGELOG) -> int:
    debian, current = packaged(changelog)
    release = choose(stable_releases(fetch_releases()), version)
    newer = release.key > numbers(current)
    series = "same" if release.key[:2] == numbers(current)[:2] else "new"
    print(f"packaged: Veyon {current} ({debian})")
    print(f"upstream: Veyon {release.version}, published {release.published or '?'}: {release.page}")
    print("newer:    " + ("yes" + (", a new series" if series == "new" else "") if newer else "no"))
    if output:
        with open(output, "a", encoding="utf-8") as lines:
            for key, value in (("version", release.version), ("sha256", release.sha256), ("page", release.page),
                               ("packaged", current), ("newer", "true" if newer else "false"), ("series", series)):
                lines.write(f"{key}={value}\n")
    return 1 if newer else 0


def write_bump(release: Release, changelog: Path = CHANGELOG, makefile: Path = MAKEFILE,
               now: datetime | None = None) -> str:
    """The changelog entry and the Makefile's pin for the release; the new Debian version."""

    text, count = SHA256_LINE.subn(f"UPSTREAM_SHA256 := {release.sha256}", makefile.read_text(encoding="utf-8"))
    if count != 1:
        raise UpstreamError(f"{makefile}: {count} lines 'UPSTREAM_SHA256 := <sha256>', expected one")
    version = f"{release.version}+repack1-0caramos1"
    date = email.utils.format_datetime(now or datetime.now(timezone.utc))
    entry = (f"veyon ({version}) {DISTRIBUTION}; urgency=medium\n\n"
             f"  * New upstream release {release.version}:\n"
             f"    {release.page}\n\n"
             f" -- {MAINTAINER}  {date}\n\n")
    changelog.write_text(entry + changelog.read_text(encoding="utf-8"), encoding="utf-8")
    makefile.write_text(text, encoding="utf-8")
    return version


def bump(version: str = "", sha256: str = "", changelog: Path = CHANGELOG, makefile: Path = MAKEFILE) -> int:
    debian, current = packaged(changelog)
    if version and sha256:
        release = Release(version, sha256, f"{RELEASE_PAGE}v{version}")
    else:
        release = choose(stable_releases(fetch_releases()), version)
    if release.key == numbers(current):
        print(f"packages/veyon/4.11 already builds Veyon {current} ({debian})")
        return 0
    if release.key < numbers(current):
        raise UpstreamError(f"Veyon {release.version} is older than {current}, which packages/veyon/4.11 builds")
    new = write_bump(release, changelog, makefile)
    print(f"packages/veyon/4.11: Veyon {current} -> {release.version} ({new}), sha256 {release.sha256}")
    return 0


def version_argument(value: str) -> str:
    if not re.fullmatch(r"\d+\.\d+\.\d+", value):
        raise argparse.ArgumentTypeError(f"not a Veyon version like 4.11.6: {value!r}")
    return ".".join(str(int(part)) for part in value.split("."))


def sha256_argument(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise argparse.ArgumentTypeError("not a sha256 in hex")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Keep packages/veyon/4.11 in step with Veyon's releases.")
    commands = parser.add_subparsers(dest="command", required=True)
    check_parser = commands.add_parser("check", help="compare the newest stable release with the recipe")
    check_parser.add_argument("--version", type=version_argument, help="that release instead of the newest one")
    check_parser.add_argument("--output", default="",
                              help="append version=, sha256=, page=, packaged=, newer= and series= lines to this file "
                                   "($GITHUB_OUTPUT)")
    bump_parser = commands.add_parser("bump", help="move the recipe to a newer release")
    bump_parser.add_argument("--version", type=version_argument, help="that release instead of the newest one")
    bump_parser.add_argument("--sha256", type=sha256_argument,
                             help="the sha256 of its source tarball, from `check` (GitHub is not asked again)")
    args = parser.parse_args(argv)
    if args.command == "bump" and args.sha256 and not args.version:
        parser.error("--sha256 needs --version")
    try:
        if args.command == "check":
            return check(args.version or "", args.output)
        return bump(args.version or "", args.sha256 or "")
    except UpstreamError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

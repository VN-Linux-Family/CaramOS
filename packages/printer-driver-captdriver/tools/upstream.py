#!/usr/bin/env python3
"""Keep printer-driver-captdriver in step with upstream captdriver. Run it through make (README, "Bảo trì"):

    make check-upstream   what changed upstream since the last review (upstream-refs.txt): the pinned branch,
                          new commits, branches, tags and pull requests, a repository that appeared.
                          Exit 0: nothing new, 1: something to look at, 2: a repository could not be read.
    make record-upstream  save the current upstream state as reviewed
    make bump             move the pin to a new upstream commit (the head of the pinned branch by default):
                          orig tarball, the pins in the Makefile, a changelog entry, and which Debian patches
                          still apply, are already upstream, or need refreshing

Without --url, --branch and --commit it takes the pins from the Makefile, as the weekly GitHub Actions check
does (.github/workflows/captdriver-upstream.yml). Nothing here changes the PPA or GitHub: uploading stays
`make source upload`.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PACKAGE = "printer-driver-captdriver"
ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "upstream-refs.txt"
MAKEFILE = ROOT / "Makefile"
PATCHES = ROOT / "debian/patches"
MAINTAINER = {"DEBFULLNAME": "Vietnam Linux Family", "DEBEMAIL": "developer@vietnamlinuxfamily.net"}
DISTRIBUTION = "noble"

# Where captdriver work happens (the research report, 2026-11-08).
WATCHED = {
    "mounaiban": "https://github.com/mounaiban/captdriver.git",        # the pinned branch, pull request #55
    "valdikss": "https://github.com/ValdikSS/captdriver.git",          # where the 2026 fixes come from
    "agalakhov": "https://github.com/agalakhov/captdriver.git",        # the original project
    "openprinting": "https://github.com/OpenPrinting/captdriver.git",  # ValdikSS's finished version is to go here
}
MISSING = "-"   # the "ref" of a repository that does not exist
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "TZ": "UTC"}

State = dict[tuple[str, str], str]   # (repository name, ref) -> commit


class UpstreamError(Exception):
    pass


def git(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise UpstreamError(f"git {args[0]}: {result.stderr.strip() or result.returncode}")
    return result.stdout


def ls_remote(url: str) -> dict[str, str] | None:
    """ref -> commit of the branches, tags and pull request heads; None when the repository does not exist."""

    try:
        result = subprocess.run(["git", "ls-remote", url], env=GIT_ENV, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired as error:
        raise UpstreamError(f"{url}: no answer") from error
    if result.returncode != 0:
        # GitHub answers for a repository that does not exist by asking for a login.
        if "could not read Username" in result.stderr or "Repository not found" in result.stderr:
            return None
        lines = result.stderr.strip().splitlines()
        raise UpstreamError(f"{url}: {lines[-1] if lines else 'git ls-remote failed'}")
    refs = {}
    for line in result.stdout.splitlines():
        commit, _, ref = line.partition("\t")
        # refs/pull/N/merge is left out: GitHub remakes it whenever the target branch moves.
        if ref.startswith(("refs/heads/", "refs/tags/")) or re.fullmatch(r"refs/pull/\d+/head", ref):
            refs[ref] = commit
    return refs


def current(watched: dict[str, str]) -> State:
    state: State = {}
    for name, url in watched.items():
        refs = ls_remote(url)
        if refs is None:
            state[(name, MISSING)] = MISSING
        else:
            state.update({(name, ref): commit for ref, commit in refs.items()})
    return state


def load() -> State:
    state: State = {}
    if not SNAPSHOT.exists():
        return state
    for line in SNAPSHOT.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, ref, commit = line.split()
            state[(name, ref)] = commit
    return state


def save(state: State) -> None:
    lines = ["# Upstream captdriver as last reviewed: make check-upstream compares, make record-upstream rewrites.",
             "# repository ref commit (- -: the repository does not exist)"]
    lines += [f"{name} {ref} {commit}" for (name, ref), commit in sorted(state.items())]
    SNAPSHOT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def web(url: str) -> str:
    return url.removesuffix(".git")


def link(url: str, ref: str, old: str | None, new: str | None) -> str:
    pull = re.fullmatch(r"refs/pull/(\d+)/head", ref)
    if pull:
        return f"{web(url)}/pull/{pull.group(1)}"
    if old and new:
        return f"{web(url)}/compare/{old[:12]}...{new[:12]}"
    return f"{web(url)}/tree/{ref.removeprefix('refs/heads/').removeprefix('refs/tags/')}"


def changes(before: State, now: State, watched: dict[str, str]) -> list[str]:
    lines = []
    for key in sorted(set(before) | set(now)):
        old, new = before.get(key), now.get(key)
        if old == new:
            continue
        name, ref = key
        url = watched[name]
        if ref == MISSING:
            lines.append(f"{name}: the repository {'exists now' if new is None else 'is gone'}: {web(url)}")
        elif (name, MISSING) in before or (name, MISSING) in now:
            continue   # the whole repository appeared or went: told above
        elif old is None:
            lines.append(f"{name}: new {ref} at {new[:7]}: {link(url, ref, None, new)}")
        elif new is None:
            lines.append(f"{name}: {ref} is gone (was {old[:7]})")
        else:
            lines.append(f"{name}: {ref} moved {old[:7]} -> {new[:7]}: {link(url, ref, old, new)}")
    return lines


def watched_with(url: str) -> dict[str, str]:
    """The watched repositories, plus the pinned one if the pin moved somewhere else (a fork, OpenPrinting)."""

    return WATCHED if url in WATCHED.values() else {**WATCHED, "pinned": url}


def check(args: argparse.Namespace) -> int:
    watched = watched_with(args.url)
    try:
        now = current(watched)
    except UpstreamError as error:
        print(f"Could not read upstream: {error}", file=sys.stderr)
        return 2
    name = next(name for name, url in watched.items() if url == args.url)
    head = now.get((name, f"refs/heads/{args.branch}"))
    print(f"Pinned: {web(args.url)} {args.branch} @ {args.commit[:7]}")
    if head is None:
        print(f"  ! the branch {args.branch} is gone upstream: the pinned commit may disappear from GitHub;"
              " the PPA keeps the orig tarball already uploaded")
    elif head == args.commit:
        print(f"  {args.branch} is still at the pinned commit")
    else:
        print(f"  ! {args.branch} moved to {head[:7]}: {web(args.url)}/compare/{args.commit[:12]}...{head[:12]}")
    before = load()
    if not before:
        print(f"No reviewed state yet ({SNAPSHOT.name}): look at upstream, then make record-upstream")
        return 1
    found = changes(before, now, watched)
    if found:
        print(f"Changed since the last review ({SNAPSHOT.name}):")
        print("\n".join(f"  {line}" for line in found))
        print("Look at each change. To package a new commit: make bump (README, \"Bảo trì\"); "
              "when everything is looked at: make record-upstream")
    else:
        print("Nothing else changed since the last review")
    return 1 if found or head != args.commit else 0


def record(args: argparse.Namespace) -> int:
    try:
        save(current(watched_with(args.url)))
    except UpstreamError as error:
        print(f"Could not read upstream: {error}", file=sys.stderr)
        return 2
    print(f"Saved the upstream state as reviewed: {SNAPSHOT.relative_to(ROOT)}")
    return 0


def changelog_version() -> str:
    return subprocess.run(["dpkg-parsechangelog", "-S", "Version"], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout.strip()


def newer(version: str, than: str) -> bool:
    return subprocess.run(["dpkg", "--compare-versions", version, "gt", than]).returncode == 0


def next_version(upstream: str, date: str, short: str) -> str:
    """0.2.1~git20260813.f2d2da8 -> 0.2.1~git<date>.<short>; after a release 0.2.1 -> 0.2.1+git<date>.<short>."""

    base, snapshot, _ = upstream.partition("~git")
    return f"{base}~git{date}.{short}" if snapshot else f"{upstream}+git{date}.{short}"


def patch_report(source: Path) -> list[tuple[str, str]]:
    """How each patch in debian/patches/series fares on the new source, in order, as dpkg-source applies them."""

    names = [line.split()[0] for line in (PATCHES / "series").read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.startswith("#")]
    report = []
    for name in names:
        patch = ["patch", "-p1", "--force", "--fuzz=0", "--silent", "-i", str(PATCHES / name)]

        def works(*extra: str) -> bool:
            return subprocess.run([*patch, "--dry-run", *extra], cwd=source, capture_output=True).returncode == 0

        if works():
            subprocess.run(patch, cwd=source, capture_output=True, check=True)
            report.append((name, "applies"))
        elif works("--reverse"):
            report.append((name, "already upstream: remove it from debian/patches/series"))
        else:
            report.append((name, "does not apply: refresh it (README, \"Bảo trì\")"))
    return report


def set_variable(text: str, name: str, value: str) -> str:
    text, count = re.subn(rf"^{name} := .*$", f"{name} := {value}", text, flags=re.M)
    if count != 1:
        raise UpstreamError(f"Makefile: expected one line '{name} := ...'")
    return text


def bump(args: argparse.Namespace) -> int:
    url, branch, commit = args.url, args.branch, args.commit
    if not commit:
        refs = ls_remote(url) or {}
        commit = refs.get(f"refs/heads/{branch}", "")
        if not commit:
            raise UpstreamError(f"{web(url)} has no branch {branch}")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise UpstreamError("COMMIT must be a full 40-character commit id")
    makefile = MAKEFILE.read_text(encoding="utf-8")
    pinned = re.search(r"^UPSTREAM_COMMIT := (\S+)$", makefile, re.M)
    if pinned and pinned.group(1) == commit and not args.version:
        print(f"Already pinned to {commit[:7]}: nothing to do")
        return 0
    old_upstream = changelog_version().rsplit("-", 1)[0]

    with tempfile.TemporaryDirectory() as temp:
        work = Path(temp)
        git("init", "-q", cwd=work)
        git("fetch", "-q", "--depth", "1", url, commit, cwd=work)
        if git("rev-parse", "FETCH_HEAD", cwd=work).strip() != commit:
            raise UpstreamError(f"{web(url)} gave another commit for {commit}")
        date = git("log", "-1", "--format=%cd", "--date=format-local:%Y%m%d", "FETCH_HEAD", cwd=work).strip()
        version = args.version or next_version(old_upstream, date, commit[:7])
        if not newer(version, old_upstream):
            raise UpstreamError(f"{version} is not newer than {old_upstream}: give the version, "
                                "make bump NEW_VERSION=...")
        # The same bytes as the Makefile's orig target, whose checksum is pinned below.
        orig = ROOT / "build" / f"{PACKAGE}_{version}.orig.tar.gz"
        orig.parent.mkdir(exist_ok=True)
        archive = subprocess.Popen(["git", "archive", "--format=tar", f"--prefix={PACKAGE}-{version}/", "FETCH_HEAD"],
                                   cwd=work, env=GIT_ENV, stdout=subprocess.PIPE)
        with orig.open("wb") as out:
            subprocess.run(["gzip", "-n", "-9"], stdin=archive.stdout, stdout=out, check=True)
        if archive.wait() != 0:
            raise UpstreamError("git archive failed")
        sha256 = hashlib.sha256(orig.read_bytes()).hexdigest()
        subprocess.run(["tar", "-xzf", str(orig), "-C", temp], check=True)
        report = patch_report(work / f"{PACKAGE}-{version}")

    for name, value in (("UPSTREAM_URL", url), ("UPSTREAM_BRANCH", branch), ("UPSTREAM_COMMIT", commit),
                        ("ORIG_SHA256", sha256)):
        makefile = set_variable(makefile, name, value)
    MAKEFILE.write_text(makefile, encoding="utf-8")
    owner_repo = web(url).removeprefix("https://github.com/")
    subprocess.run(["dch", "--newversion", f"{version}-0caramos1", "--distribution", DISTRIBUTION,
                    "--force-distribution",
                    f"New upstream snapshot: {owner_repo}, branch {branch} at {commit[:7]} ({date[:4]}-{date[4:6]}-{date[6:]})."],
                   cwd=ROOT, env={**os.environ, **MAINTAINER}, check=True)

    print(f"Pinned {owner_repo} {branch} @ {commit[:7]} as {version}: {orig.relative_to(ROOT)}, sha256 {sha256[:16]}...")
    print("Debian patches on the new source:")
    for name, outcome in report:
        print(f"  {name}: {outcome}")
    print("Next: fix the patches above if needed and say so in debian/changelog, then make deb test, "
          "the virtual printer in the test VM, make source upload (README, \"Bảo trì\").")
    return 0


def makefile_pins() -> dict[str, str]:
    text = MAKEFILE.read_text(encoding="utf-8")
    found = (re.search(rf"^{name} := (\S+)$", text, re.M) for name in ("UPSTREAM_URL", "UPSTREAM_BRANCH", "UPSTREAM_COMMIT"))
    url, branch, commit = (match.group(1) if match else "" for match in found)
    return {"url": url, "branch": branch, "commit": commit}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="upstream.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "record", "bump"):
        command = commands.add_parser(name)
        command.add_argument("--url", help="the upstream repository (default: UPSTREAM_URL)")
        command.add_argument("--branch", help="the pinned branch (default: UPSTREAM_BRANCH)")
        command.add_argument("--commit", help="a full commit id (default for check: UPSTREAM_COMMIT; "
                                              "for bump: the head of the branch)")
        if name == "bump":
            command.add_argument("--version", help="the upstream version, e.g. 0.2.2 for a release")
    args = parser.parse_args(argv)
    pins = makefile_pins()
    args.url = args.url or pins["url"]
    args.branch = args.branch or pins["branch"]
    if args.command == "check":
        args.commit = args.commit or pins["commit"]
    try:
        return {"check": check, "record": record, "bump": bump}[args.command](args)
    except UpstreamError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

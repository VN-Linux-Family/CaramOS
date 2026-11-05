"""APT/dpkg operations and migration update detection for CaramOS OTA."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .constants import EXIT_APT, PPA_PATTERN
from .errors import OtaError
from .logging_utils import current_log_file, log_error, log_info, log_warn, now_iso, print_fail, print_ok
from .manifest import manifest_for_plan, resolve_update_plan
from caramos_ota_update.registry import version_lt
from .models import Manifest, ReleaseInfo, UpdatePackage
from .state import save_state


def run_command(args: list[str], *, capture: bool = False, allow_fail: bool = False,
                env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    log_info("Running: " + " ".join(args))
    stderr_target: Any = subprocess.PIPE if capture else None
    stdout_target: Any = subprocess.PIPE if capture else None
    active_log = current_log_file()
    with (active_log.open("a", encoding="utf-8") if active_log and not capture else open(os.devnull, "a", encoding="utf-8")) as log_handle:
        if not capture:
            stderr_target = log_handle
        result = subprocess.run(args, check=False, text=True, stdout=stdout_target, stderr=stderr_target, env=env)
    if result.returncode != 0 and not allow_fail:
        raise subprocess.CalledProcessError(result.returncode, args, output=result.stdout, stderr=result.stderr)
    return result


APT_SOURCES_LIST = Path("/etc/apt/sources.list")
APT_SOURCES_DIR = Path("/etc/apt/sources.list.d")


def disable_cdrom_sources() -> None:
    source_files = [APT_SOURCES_LIST]
    if APT_SOURCES_DIR.exists():
        source_files.extend(sorted(APT_SOURCES_DIR.glob("*.list")))
    for source_file in source_files:
        try:
            if not source_file.exists() or not source_file.is_file():
                continue
            original = source_file.read_text(encoding="utf-8")
            changed = False
            updated_lines: list[str] = []
            for line in original.splitlines(keepends=True):
                stripped = line.lstrip()
                if stripped.startswith("deb cdrom:") or stripped.startswith("deb-src cdrom:"):
                    updated_lines.append("# disabled by caramos-ota: " + line)
                    changed = True
                else:
                    updated_lines.append(line)
            if not changed:
                continue
            backup = source_file.with_suffix(source_file.suffix + ".caramos-ota.bak")
            if not backup.exists():
                backup.write_text(original, encoding="utf-8")
            source_file.write_text("".join(updated_lines), encoding="utf-8")
            log_info(f"Disabled cdrom APT source entries in {source_file}")
        except OSError as exc:
            log_error(f"Failed to inspect APT source file {source_file}: {exc}")


# apt's messages in English, which failed_sources() and candidate_version() read, whatever the system language:
# on a Vietnamese system apt-cache policy says "Ứng cử:", not "Candidate:".
APT_ENV_OVERRIDES = {"LC_ALL": "C.UTF-8"}


def english_environment() -> dict[str, str]:
    environment = {name: value for name, value in os.environ.items() if name != "LANGUAGE"}
    environment.update(APT_ENV_OVERRIDES)
    return environment
FAILED_FETCH_RE = re.compile(r"^[EW]: Failed to fetch (\S+)")
REPOSITORY_RE = re.compile(r"^[EW]: The repository '(\S+)")
# The end of a fetched URL: /dists/<suite>/..., or the file of a flat repository ("https://x ./").
INDEX_PATH_RE = re.compile(r"(/dists/.*|(/\.)?/(In)?Release(\.gpg)?|(/\.)?/Packages(\.\w+)?)$")


def _source_files() -> list[Path]:
    files = [APT_SOURCES_LIST]
    if APT_SOURCES_DIR.is_dir():
        files.extend(sorted(APT_SOURCES_DIR.glob("*.list")) + sorted(APT_SOURCES_DIR.glob("*.sources")))
    return [path for path in files if path.is_file()]


def _base_uri(text: str) -> str:
    """https://github.io/./InRelease or "https://github.io ./" -> https://github.io (the URI of the source)."""

    uri = text.split()[0] if text.split() else text
    return INDEX_PATH_RE.sub("", uri).rstrip("/")


def failed_sources(output: str) -> list[str]:
    """The source URIs apt-get update could not fetch, from its E:/W: lines."""

    found: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        match = REPOSITORY_RE.match(line) or FAILED_FETCH_RE.match(line)
        if match:
            uri = _base_uri(match.group(1))
            if uri and uri not in found:
                found.append(uri)
    return found


def source_files_mentioning(uri: str) -> list[str]:
    files = []
    for path in _source_files():
        try:
            if uri in path.read_text(encoding="utf-8", errors="ignore"):
                files.append(str(path))
        except OSError:
            continue
    return files


def _append_to_log(text: str) -> None:
    log_file = current_log_file()
    if log_file is not None and text.strip():
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(text if text.endswith("\n") else text + "\n")


def _apt_get_update(extra: list[str]) -> subprocess.CompletedProcess[str]:
    args = ["apt-get", "update", "-qq", *extra]
    log_info("Running: " + " ".join(args))
    result = subprocess.run(args, check=False, text=True, capture_output=True, env=english_environment())
    _append_to_log((result.stdout or "") + (result.stderr or ""))
    return result


def update_caramos_sources() -> bool:
    """apt-get update of the CaramOS PPA alone, leaving the other package lists as they are."""

    one_line: list[str] = []
    deb822: list[Path] = []
    for path in _source_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if PPA_PATTERN not in text:
            continue
        if path.suffix == ".sources":
            deb822.append(path)
        else:
            one_line.extend(line for line in text.splitlines()
                            if PPA_PATTERN in line and not line.lstrip().startswith("#"))
    if not one_line and not deb822:
        return False
    with tempfile.TemporaryDirectory(prefix="caramos-ota-apt.") as folder:
        source_list = Path(folder) / "caramos.list"
        source_list.write_text("".join(line + "\n" for line in one_line), encoding="utf-8")
        parts = Path(folder) / "sources.list.d"
        parts.mkdir()
        for path in deb822:
            shutil.copyfile(path, parts / path.name)
        result = _apt_get_update(["-o", f"Dir::Etc::SourceList={source_list}", "-o", f"Dir::Etc::SourceParts={parts}",
                                  "-o", "APT::Get::List-Cleanup=0"])
    return result.returncode == 0


def apt_update() -> None:
    print_ok("Updating package index...")
    disable_cdrom_sources()
    result = _apt_get_update([])
    if result.returncode == 0:
        log_info("apt-get update completed")
        return
    # A source added by hand or by another program that no longer works (a moved repository, a typo, a
    # captive portal) fails apt-get update as a whole, though the other lists are fresh. The CaramOS update
    # only needs the CaramOS PPA: refresh it alone and go on.
    failed = failed_sources(result.stderr or "")
    if failed and not any(PPA_PATTERN in uri for uri in failed) and update_caramos_sources():
        for uri in failed:
            files = source_files_mentioning(uri)
            where = f" (in {', '.join(files)})" if files else ""
            log_warn(f"Skipped a software source that could not be updated: {uri}{where}")
        print("Warning: some software sources that are not part of CaramOS could not be updated; "
              "the CaramOS update goes on.")
        log_info("apt-get update completed for the CaramOS repository")
        return
    print("Error: Failed to update package index.")
    print("Check your network connection and repository configuration.")
    print(f"Log: {current_log_file()}")
    log_error("apt-get update failed")
    raise SystemExit(EXIT_APT)


def installed_version(package: str) -> str:
    result = run_command(["dpkg-query", "-W", "-f=${Version}", package], capture=True, allow_fail=True)
    return (result.stdout or "").strip() if result.returncode == 0 else ""


# dpkg states of a package it started to install or remove and could not finish: half-installed,
# unpacked, half-configured (the second letter of ${db:Status-Abbrev}).
UNFINISHED_STATES = frozenset("HUF")
# Packages CaramOS installs whose broken maintainer script a newer version replaces: Lotus 3.5.6's postinst
# had a syntax error, and the half-configured package failed every later apt-get install (ticket H-1100).
REPAIRABLE_BY_UPGRADE = ("fcitx5-lotus",)


def package_status(package: str) -> tuple[str, str]:
    """(${db:Status-Abbrev}, ${Version}) of an installed package, ("", "") when dpkg does not know it."""

    result = run_command(["dpkg-query", "-W", "-f=${db:Status-Abbrev}|${Version}", package], capture=True,
                         allow_fail=True)
    if result.returncode != 0 or "|" not in (result.stdout or ""):
        return "", ""
    status, version = (result.stdout or "").split("|", 1)
    return status.strip(), version.strip()


def is_installed(package: str, version: str = "") -> bool:
    status, installed = package_status(package)
    return status.startswith("ii") and (not version or installed == version)


def broken_packages() -> list[str]:
    """Packages dpkg could not finish installing, which every apt-get install tries to configure again."""

    result = run_command(["dpkg-query", "-W", "-f=${binary:Package} ${db:Status-Abbrev}\n"], capture=True,
                         allow_fail=True)
    broken = []
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and len(parts[1]) >= 2 and parts[1][1] in UNFINISHED_STATES:
            broken.append(parts[0].split(":")[0])
    return broken


def repairable_packages() -> list[str]:
    """REPAIRABLE_BY_UPGRADE packages left unfinished for which APT has another version."""

    found = []
    for package in REPAIRABLE_BY_UPGRADE:
        status, installed = package_status(package)
        if len(status) >= 2 and status[1] in UNFINISHED_STATES:
            candidate = candidate_version(package)
            if candidate and candidate not in ("(none)", installed):
                found.append(package)
    return found


def candidate_version(package: str) -> str:
    result = run_command(["apt-cache", "policy", package], capture=True, allow_fail=True, env=english_environment())
    for line in (result.stdout or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("Candidate:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def version_ge(left: str, right: str) -> bool:
    return run_command(["dpkg", "--compare-versions", left, "ge", right], allow_fail=True).returncode == 0


def detect_updates(
    release_info: ReleaseInfo,
    state: dict[str, Any],
    *,
    persist_ledger: bool = True,
    persist_state: bool = True,
) -> tuple[Manifest, list[UpdatePackage]]:
    """Detect pending migration IDs, including same-release migrations."""

    try:
        plan = resolve_update_plan(release_info, persist_ledger=persist_ledger)
        manifest = manifest_for_plan(plan, release_info)
    except OtaError as exc:
        print(str(exc))
        log_error("Migration registry parse failed")
        raise SystemExit(exc.exit_code)

    updates = [
        UpdatePackage(
            name=item.title,
            current_version="",
            available_version="",
            description=item.summary,
            required=False,
            name_en=item.title_en,
            description_en=item.summary_en,
        )
        for item in plan.migrations
    ]
    target_newer = version_lt(release_info.version, manifest.release)
    if target_newer and not updates:
        updates.append(
            UpdatePackage(
                name="CaramOS release metadata",
                current_version=release_info.version,
                available_version=manifest.release,
                description="Update CaramOS release metadata to packaged target.",
                required=True,
            )
        )
    if updates:
        state["available_update"] = {
            "detected_at": now_iso(),
            "release": manifest.release,
            "to_version": manifest.release,
            "manifest_source": manifest.source,
            "current_version": release_info.version,
            "from_version": release_info.version,
            "channel": manifest.channel,
            "severity": manifest.severity,
            "size": manifest.size,
            "size_en": manifest.size_en,
            "title": manifest.title,
            "summary": manifest.summary,
            "title_en": manifest.title_en,
            "summary_en": manifest.summary_en,
            "release_notes_vi": manifest.release_notes_vi,
            "release_notes_en": manifest.release_notes_en,
            "migration_ids": [item.migration_id for item in plan.migrations],
            "packages": [update.__dict__ for update in updates],
        }
    else:
        state["available_update"] = None
    if persist_state:
        save_state(state)
    log_info(
        f"Migration update detection complete: {len(plan.migrations)} pending migration(s); "
        f"target {manifest.release}; available={bool(updates)}"
    )
    return manifest, updates


def install_packages(packages: list[str]) -> bool:
    try:
        run_command(["apt-get", "install", "--yes", "--", *packages])
        return True
    except subprocess.CalledProcessError:
        return False


def remove_package(package: str) -> bool:
    return run_command(["apt-get", "remove", "--yes", "--", package], allow_fail=True).returncode == 0


def downgrade_package(package: str, old_version: str) -> bool:
    return run_command(["apt-get", "install", "--yes", "--allow-downgrades", "--", f"{package}={old_version}"], allow_fail=True).returncode == 0


def repair_dpkg() -> bool:
    return run_command(["dpkg", "--configure", "-a"], allow_fail=True).returncode == 0


def repair_apt() -> bool:
    return run_command(["apt-get", "--fix-broken", "install", "--yes"], allow_fail=True).returncode == 0


def print_repair_result(ok: bool, success_message: str, failure_message: str) -> None:
    if ok:
        print_ok(success_message)
        log_info(success_message)
    else:
        print_fail(failure_message)
        log_error(failure_message)

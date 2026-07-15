"""APT/dpkg operations and migration update detection for CaramOS OTA."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .constants import EXIT_APT
from .errors import OtaError
from .logging_utils import current_log_file, log_error, log_info, now_iso, print_fail, print_ok
from .manifest import manifest_for_plan, resolve_update_plan
from .models import Manifest, ReleaseInfo, UpdatePackage
from .state import save_state


def run_command(args: list[str], *, capture: bool = False, allow_fail: bool = False) -> subprocess.CompletedProcess[str]:
    log_info("Running: " + " ".join(args))
    stderr_target: Any = subprocess.PIPE if capture else None
    stdout_target: Any = subprocess.PIPE if capture else None
    active_log = current_log_file()
    with (active_log.open("a", encoding="utf-8") if active_log and not capture else open(os.devnull, "a", encoding="utf-8")) as log_handle:
        if not capture:
            stderr_target = log_handle
        result = subprocess.run(args, check=False, text=True, stdout=stdout_target, stderr=stderr_target)
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


def apt_update() -> None:
    print_ok("Updating package index...")
    disable_cdrom_sources()
    try:
        run_command(["apt-get", "update", "-qq"])
    except subprocess.CalledProcessError:
        print("Error: Failed to update package index.")
        print("Check your network connection and repository configuration.")
        print(f"Log: {current_log_file()}")
        log_error("apt-get update failed")
        raise SystemExit(EXIT_APT)
    log_info("apt-get update completed")


def installed_version(package: str) -> str:
    result = run_command(["dpkg-query", "-W", "-f=${Version}", package], capture=True, allow_fail=True)
    return (result.stdout or "").strip() if result.returncode == 0 else ""


def candidate_version(package: str) -> str:
    result = run_command(["apt-cache", "policy", package], capture=True, allow_fail=True)
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
            name=item.migration_id,
            current_version="pending",
            available_version=item.release,
            description=item.summary,
            required=True,
        )
        for item in plan.migrations
    ]
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
            "title": manifest.title,
            "summary": manifest.summary,
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
        f"Migration update detection complete: {len(updates)} pending migration(s) "
        f"through release {manifest.release}"
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

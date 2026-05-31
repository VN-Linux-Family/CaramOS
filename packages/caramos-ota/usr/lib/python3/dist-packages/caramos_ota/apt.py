"""APT/dpkg operations for CaramOS OTA."""

from __future__ import annotations

import os
import subprocess
from typing import Any

from .constants import EXIT_APT, TOOL_NAME
from .errors import OtaError
from .logging_utils import current_log_file, log_error, log_info, now_iso, print_fail, print_ok
from .manifest import parse_manifest
from .models import Manifest, ReleaseInfo, UpdatePackage
from .state import save_state


def run_command(args: list[str], *, capture: bool = False, allow_fail: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a system command safely without a shell."""

    log_info("Running: " + " ".join(args))
    stderr_target: Any = subprocess.PIPE if capture else None
    stdout_target: Any = subprocess.PIPE if capture else None
    active_log = current_log_file()
    with (active_log.open("a", encoding="utf-8") if active_log and not capture else open(os.devnull, "a", encoding="utf-8")) as log_handle:
        if not capture:
            stderr_target = log_handle
        result = subprocess.run(
            args,
            check=False,
            text=True,
            stdout=stdout_target,
            stderr=stderr_target,
        )
    if result.returncode != 0 and not allow_fail:
        raise subprocess.CalledProcessError(result.returncode, args, output=result.stdout, stderr=result.stderr)
    return result


def apt_update() -> None:
    """Refresh APT metadata."""

    print_ok("Updating package index...")
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
    """Return the installed version for a package, or an empty string."""

    result = run_command(["dpkg-query", "-W", "-f=${Version}", package], capture=True, allow_fail=True)
    return (result.stdout or "").strip() if result.returncode == 0 else ""


def candidate_version(package: str) -> str:
    """Return APT candidate version for a package, or an empty string."""

    result = run_command(["apt-cache", "policy", package], capture=True, allow_fail=True)
    for line in (result.stdout or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("Candidate:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def version_ge(left: str, right: str) -> bool:
    """Return True when Debian version `left` is greater or equal to `right`."""

    result = run_command(["dpkg", "--compare-versions", left, "ge", right], allow_fail=True)
    return result.returncode == 0


def detect_updates(release_info: ReleaseInfo, state: dict[str, Any]) -> tuple[Manifest, list[UpdatePackage]]:
    """Detect packages that need install/upgrade for the current manifest."""

    try:
        manifest = parse_manifest(release_info)
    except OtaError as exc:
        print(str(exc))
        log_error("Manifest parse failed")
        raise SystemExit(exc.exit_code)

    updates: list[UpdatePackage] = []
    for component in manifest.components:
        installed = installed_version(component.package)
        candidate = candidate_version(component.package)
        if not candidate or candidate == "(none)":
            if component.required:
                print(f"Error: Required package '{component.package}' is not available in the repository.")
                print("Please check the CaramOS PPA.")
                log_error(f"Package not available: {component.package}")
                raise SystemExit(EXIT_APT)
            continue

        needs_update = not installed or not version_ge(installed, component.min_version)
        if not needs_update:
            continue
        if not version_ge(candidate, component.min_version):
            if component.required:
                print(f"Error: Package '{component.package}' candidate version {candidate} is below required {component.min_version}.")
                log_error(f"Candidate too old: {component.package} {candidate} < {component.min_version}")
                raise SystemExit(EXIT_APT)
            continue
        updates.append(
            UpdatePackage(
                name=component.package,
                current_version=installed or "(new)",
                available_version=candidate,
                description=component.description,
            )
        )

    if updates:
        state["available_update"] = {
            "detected_at": now_iso(),
            "release": manifest.release,
            "manifest_source": manifest.source,
            "current_version": release_info.version,
            "release_notes_vi": manifest.release_notes_vi,
            "release_notes_en": manifest.release_notes_en,
            "packages": [update.__dict__ for update in updates],
        }
    else:
        state["available_update"] = None
    save_state(state)
    log_info(
        f"Update detection complete: {len(updates)} updates for release {manifest.release} "
        f"using manifest {manifest.source}"
    )
    return manifest, updates


def install_packages(packages: list[str]) -> bool:
    """Install packages with APT."""

    try:
        run_command(["apt-get", "install", "--yes", "--", *packages])
        return True
    except subprocess.CalledProcessError:
        return False


def remove_package(package: str) -> bool:
    """Remove one package with APT."""

    return run_command(["apt-get", "remove", "--yes", "--", package], allow_fail=True).returncode == 0


def downgrade_package(package: str, old_version: str) -> bool:
    """Downgrade one package to an older version with APT."""

    return run_command(["apt-get", "install", "--yes", "--allow-downgrades", "--", f"{package}={old_version}"], allow_fail=True).returncode == 0


def repair_dpkg() -> bool:
    """Run dpkg --configure -a."""

    return run_command(["dpkg", "--configure", "-a"], allow_fail=True).returncode == 0


def repair_apt() -> bool:
    """Run apt-get --fix-broken install."""

    return run_command(["apt-get", "--fix-broken", "install", "--yes"], allow_fail=True).returncode == 0


def print_repair_result(ok: bool, success_message: str, failure_message: str) -> None:
    """Print and log a repair step result."""

    if ok:
        print_ok(success_message)
        log_info(success_message)
    else:
        print_fail(failure_message)
        log_error(failure_message)

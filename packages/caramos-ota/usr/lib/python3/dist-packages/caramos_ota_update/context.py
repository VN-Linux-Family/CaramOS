"""Execution context exposed to CaramOS OTA migrations."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from caramos_ota.logging_utils import log_info

from .version_metadata import validate_version, version_metadata_files, write_version_metadata

_PACKAGE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9+.-]+$")
_SERVICE_NAME_RE = re.compile(r"^[A-Za-z0-9_.@:-]+$")


class MigrationContextError(RuntimeError):
    """Raised when a migration helper rejects an unsafe or invalid action."""


@dataclass
class MigrationContext:
    """Safe helper surface for migration modules.

    Dry-run mode must never mutate the system. Helpers therefore log planned
    actions and return without invoking APT, systemctl, or filesystem writes.
    """

    dry_run: bool = False
    release_values: dict[str, str] = field(default_factory=dict)

    def log(self, message: str) -> None:
        """Log a migration message."""

        prefix = "[dry-run] " if self.dry_run else ""
        log_info(f"{prefix}{message}")
        print(f"{prefix}{message}")

    def run_command(
        self,
        args: Sequence[str],
        *,
        allow_fail: bool = False,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str] | None:
        """Run a command safely with shell=False.

        Args are passed as a sequence to avoid shell interpolation. In dry-run
        mode this method only logs the planned command.
        """

        if not args:
            raise MigrationContextError("refusing to run an empty command")
        command = [str(part) for part in args]
        self.log(f"run: {' '.join(command)}")
        if self.dry_run:
            return None
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        if completed.returncode != 0 and not allow_fail:
            raise MigrationContextError(
                f"command failed with exit code {completed.returncode}: {command[0]}"
            )
        return completed

    def apt_update(self) -> None:
        """Refresh APT metadata."""

        self.run_command(["apt-get", "update"])

    def apt_install(self, packages: Sequence[str]) -> None:
        """Install packages through APT after validating package names."""

        package_list = self._validate_packages(packages)
        self.run_command(["apt-get", "install", "--yes", "--", *package_list])

    def apt_remove(self, packages: Sequence[str]) -> None:
        """Remove packages through APT after validating package names."""

        package_list = self._validate_packages(packages)
        self.run_command(["apt-get", "remove", "--yes", "--", *package_list])

    def ensure_service_enabled(self, service: str) -> None:
        """Enable a systemd service after validating the unit name."""

        self._validate_service(service)
        self.run_command(["systemctl", "enable", service])

    def ensure_service_disabled(self, service: str) -> None:
        """Disable a systemd service after validating the unit name."""

        self._validate_service(service)
        self.run_command(["systemctl", "disable", service])

    def file_contains(self, path: str | Path, text: str) -> bool:
        """Return whether a text file contains the given text."""

        file_path = Path(path)
        if not file_path.exists():
            return False
        return text in file_path.read_text(encoding="utf-8")

    def append_line_once(self, path: str | Path, line: str) -> None:
        """Append a line only when it does not already exist."""

        file_path = Path(path)
        normalized = line.rstrip("\n")
        if self.file_contains(file_path, normalized):
            self.log(f"line already exists in {file_path}: {normalized}")
            return
        self.log(f"append line to {file_path}: {normalized}")
        if self.dry_run:
            return
        with file_path.open("a", encoding="utf-8") as handle:
            handle.write(normalized + "\n")

    def write_file_if_changed(self, path: str | Path, content: str) -> None:
        """Write a file only if content changed."""

        file_path = Path(path)
        if file_path.exists() and file_path.read_text(encoding="utf-8") == content:
            self.log(f"file unchanged: {file_path}")
            return
        self.log(f"write file: {file_path}")
        if self.dry_run:
            return
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")

    def update_release_file(self, version: str) -> None:
        """Update all CaramOS version metadata files after a migration."""

        version = validate_version(version)
        self.log(f"set CaramOS system version to {version}")
        if self.dry_run:
            for path in version_metadata_files(version):
                self.log(f"would write version metadata: {path}")
            return
        changed = write_version_metadata(version)
        if not changed:
            self.log(f"version metadata already up to date: {version}")
        else:
            for path in changed:
                self.log(f"updated version metadata: {path}")
        self.release_values = {
            "NAME": "CaramOS",
            "VERSION": version,
            "CHANNEL": "stable",
            "UBUNTU_CODENAME": "noble",
        }

    def _validate_packages(self, packages: Sequence[str]) -> list[str]:
        if not packages:
            raise MigrationContextError("package list must not be empty")
        result: list[str] = []
        for package in packages:
            if not _PACKAGE_NAME_RE.fullmatch(package):
                raise MigrationContextError(f"invalid package name: {package}")
            result.append(package)
        return result

    def _validate_service(self, service: str) -> None:
        if not _SERVICE_NAME_RE.fullmatch(service):
            raise MigrationContextError(f"invalid service name: {service}")

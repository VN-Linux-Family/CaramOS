"""Allowlisted audit sources."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

SourceKind = Literal["file", "directory", "command"]

_ALLOWED_FILE_PATHS = frozenset(
    {
        "/etc/caramos-release", "/etc/hostname", "/etc/os-release", "/etc/lsb-release",
        "/etc/linuxmint/info", "/proc/cmdline", "/proc/version", "/var/lib/caramos-ota/state.json",
    }
)
_ALLOWED_DIRECTORIES = frozenset({"/etc/apt/sources.list.d", "/var/log/caramos-ota"})
_ALLOWED_COMMANDS = frozenset(
    {
        ("df", "-P", "-h"), ("findmnt", "--json", "--output", "TARGET,SOURCE,FSTYPE,OPTIONS"),
        ("free", "-h"), ("id",), ("lsblk", "--json", "--output", "NAME,TYPE,SIZE,FSTYPE,MOUNTPOINT,MODEL"),
        ("lscpu",), ("systemd-detect-virt",), ("uname", "-a"),
        ("xrandr", "--current"), ("pactl", "info"), ("pactl", "list", "short", "sinks"),
        ("pactl", "list", "short", "sources"), ("aplay", "-l"), ("arecord", "-l"),
        ("nmcli", "general", "status"), ("nmcli", "device", "status"), ("ip", "-brief", "addr"),
        ("ip", "route"), ("rfkill", "list", "bluetooth"), ("bluetoothctl", "show"),
        ("bluetoothctl", "devices"), ("upower", "-e"), ("loginctl", "show-session", "self"),
        ("cinnamon", "--version"),
        ("journalctl", "--boot=0", "--no-pager", "--output=short-iso", "--lines=400", "-u", "NetworkManager"),
        ("journalctl", "--boot=0", "--no-pager", "--output=short-iso", "--lines=300", "-u", "caramos-ota-check.service"),
        ("journalctl", "--boot=0", "--no-pager", "--output=short-iso", "--lines=300", "_COMM=cinnamon"),
    }
)


@dataclass(frozen=True)
class AuditSource:
    """Allowlisted source definition."""

    kind: SourceKind
    target: str
    name: str
    command: tuple[str, ...] = ()
    max_bytes: int = 32_768
    max_lines: int = 256
    max_entries: int = 16
    timeout_seconds: float = 5.0

    def is_allowed(self) -> bool:
        if self.kind == "file":
            if self.target in _ALLOWED_FILE_PATHS:
                return True
            home = Path.home().resolve(strict=False)
            path = Path(self.target).resolve(strict=False)
            return path == home / ".xsession-errors"
        if self.kind == "directory":
            return self.target in _ALLOWED_DIRECTORIES
        if self.kind == "command":
            return self.command in _ALLOWED_COMMANDS
        return False


def _reject_home_path(path: Path) -> None:
    resolved = path.expanduser().resolve(strict=False)
    home = Path.home().resolve(strict=False)
    if resolved == home or (home in resolved.parents and resolved != home / ".xsession-errors"):
        raise ValueError(f"home paths are not allowed: {path}")


def file_source(path: str | Path, *, name: str | None = None, max_bytes: int = 32_768, max_lines: int = 256) -> AuditSource:
    resolved = Path(path).expanduser()
    _reject_home_path(resolved)
    source = AuditSource(kind="file", target=str(resolved), name=name or resolved.name, max_bytes=max_bytes, max_lines=max_lines)
    if not source.is_allowed():
        raise ValueError(f"file source not allowlisted: {resolved}")
    return source


def directory_source(path: str | Path, *, name: str | None = None, max_entries: int = 16, max_bytes: int = 32_768, max_lines: int = 256) -> AuditSource:
    resolved = Path(path).expanduser()
    _reject_home_path(resolved)
    source = AuditSource(kind="directory", target=str(resolved), name=name or resolved.name, max_entries=max_entries, max_bytes=max_bytes, max_lines=max_lines)
    if not source.is_allowed():
        raise ValueError(f"directory source not allowlisted: {resolved}")
    return source


def command_source(command: Sequence[str], *, name: str | None = None, timeout_seconds: float = 5.0, max_bytes: int = 32_768) -> AuditSource:
    parts = tuple(str(part) for part in command)
    source = AuditSource(kind="command", target=parts[0] if parts else "", name=name or " ".join(parts), command=parts, timeout_seconds=timeout_seconds, max_bytes=max_bytes)
    if not source.is_allowed():
        raise ValueError(f"command not allowlisted: {' '.join(parts)}")
    return source


def default_sources() -> tuple[AuditSource, ...]:
    """Return default offline audit sources; optional commands fail softly."""
    files = (
        file_source("/etc/caramos-release", name="caramos-release", max_bytes=4096, max_lines=64),
        file_source("/etc/os-release", name="os-release", max_bytes=4096, max_lines=64),
        file_source("/etc/lsb-release", name="lsb-release", max_bytes=4096, max_lines=64),
        file_source("/etc/linuxmint/info", name="linuxmint-info", max_bytes=4096, max_lines=64),
        file_source("/var/lib/caramos-ota/state.json", name="ota-state", max_bytes=64_000, max_lines=512),
        file_source(Path.home() / ".xsession-errors", name="xsession-errors", max_bytes=2 * 1024 * 1024, max_lines=4000),
    )
    directories = (
        directory_source("/etc/apt/sources.list.d", name="apt-sources", max_entries=16, max_bytes=8192, max_lines=128),
        directory_source("/var/log/caramos-ota", name="ota-logs", max_entries=16, max_bytes=2 * 1024 * 1024, max_lines=2000),
    )
    commands = (
        command_source(("uname", "-a"), name="uname"), command_source(("systemd-detect-virt",), name="virt"),
        command_source(("lscpu",), name="cpu", max_bytes=64_000), command_source(("free", "-h"), name="memory"),
        command_source(("lsblk", "--json", "--output", "NAME,TYPE,SIZE,FSTYPE,MOUNTPOINT,MODEL"), name="storage"),
        command_source(("df", "-P", "-h"), name="disk-space"), command_source(("xrandr", "--current"), name="display"),
        command_source(("pactl", "info"), name="audio-info"), command_source(("pactl", "list", "short", "sinks"), name="audio-sinks"),
        command_source(("pactl", "list", "short", "sources"), name="audio-sources"), command_source(("aplay", "-l"), name="alsa-playback"),
        command_source(("arecord", "-l"), name="alsa-record"), command_source(("nmcli", "general", "status"), name="network-general"),
        command_source(("nmcli", "device", "status"), name="network-devices"), command_source(("ip", "-brief", "addr"), name="network-addresses"),
        command_source(("ip", "route"), name="network-routes"), command_source(("rfkill", "list", "bluetooth"), name="bluetooth-rfkill"),
        command_source(("bluetoothctl", "show"), name="bluetooth-controller"), command_source(("bluetoothctl", "devices"), name="bluetooth-devices"),
        command_source(("upower", "-e"), name="power-devices"), command_source(("loginctl", "show-session", "self"), name="session"),
        command_source(("cinnamon", "--version"), name="cinnamon"),
        command_source(("journalctl", "--boot=0", "--no-pager", "--output=short-iso", "--lines=400", "-u", "NetworkManager"), name="network-manager-log", max_bytes=128 * 1024),
        command_source(("journalctl", "--boot=0", "--no-pager", "--output=short-iso", "--lines=300", "-u", "caramos-ota-check.service"), name="ota-log", max_bytes=128 * 1024),
        command_source(("journalctl", "--boot=0", "--no-pager", "--output=short-iso", "--lines=300", "_COMM=cinnamon"), name="cinnamon-log", max_bytes=128 * 1024),
    )
    return files + directories + commands

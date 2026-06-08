"""Data models used by CaramOS OTA modules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReleaseInfo:
    """Parsed CaramOS release metadata."""

    name: str
    version: str
    codename: str
    channel: str


@dataclass(frozen=True)
class Manifest:
    """Validated migration-based OTA manifest."""

    release: str
    codename: str
    source: str
    min_client_version: str | None
    channel: str
    severity: str
    size: str
    title: str
    summary: str
    release_notes_vi: list[str]
    release_notes_en: list[str]


@dataclass(frozen=True)
class UpdatePackage:
    """Display-only update item for the notifier UI."""

    name: str
    current_version: str
    available_version: str
    description: str
    required: bool = True

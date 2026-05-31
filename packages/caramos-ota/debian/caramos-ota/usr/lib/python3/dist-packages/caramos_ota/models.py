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
class Component:
    """One package component declared in the OTA manifest."""

    package: str
    min_version: str
    required: bool
    description: str


@dataclass(frozen=True)
class Manifest:
    """Validated OTA manifest."""

    release: str
    codename: str
    release_notes_vi: list[str]
    release_notes_en: list[str]
    components: list[Component]


@dataclass(frozen=True)
class UpdatePackage:
    """One package that needs install/upgrade."""

    name: str
    current_version: str
    available_version: str
    description: str

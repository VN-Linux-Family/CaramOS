"""APT helper namespace for CaramOS OTA migrations.

Migration modules should normally call the dry-run aware helpers on
MigrationContext instead of importing this module directly. This module exists as
a stable location for future APT-specific utilities shared by the runner.
"""

from __future__ import annotations

from collections.abc import Sequence

from .context import MigrationContext


def update(context: MigrationContext) -> None:
    """Refresh APT metadata through the migration context."""

    context.apt_update()


def install(context: MigrationContext, packages: Sequence[str]) -> None:
    """Install packages through the migration context."""

    context.apt_install(packages)


def remove(context: MigrationContext, packages: Sequence[str]) -> None:
    """Remove packages through the migration context."""

    context.apt_remove(packages)

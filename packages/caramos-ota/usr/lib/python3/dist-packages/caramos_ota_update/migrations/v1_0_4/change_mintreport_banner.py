"""Migration for PR #43: update mintreport banner logo and background."""

from __future__ import annotations

from pathlib import Path

from caramos_ota_update.context import MigrationContext

FROM_VERSION = "1.0.3"
TO_VERSION = "1.0.4"
DESCRIPTION = "PR #43: change mintreport banner logo and background color"

_MINTREPORT_UI = Path("/usr/share/linuxmint/mintreport/mintreport.ui")
_MINTREPORT_APP = Path("/usr/lib/linuxmint/mintreport/app.py")


def _replace_once(context: MigrationContext, path: Path, old: str, new: str) -> None:
    if not path.exists():
        context.log(f"skip missing file: {path}")
        return
    text = path.read_text(encoding="utf-8")
    updated = text.replace(old, new)
    if updated == text:
        context.log(f"pattern already absent or migrated in {path}: {old}")
        return
    context.write_file_if_changed(path, updated)


def run(context: MigrationContext) -> None:
    """Apply mintreport branding changes from PR #43."""

    _replace_once(
        context,
        _MINTREPORT_UI,
        "linuxmint-logo-filled-ring",
        "caramos",
    )
    _replace_once(
        context,
        _MINTREPORT_APP,
        "#86be43",
        "shade(@theme_bg_color, 0.96)",
    )

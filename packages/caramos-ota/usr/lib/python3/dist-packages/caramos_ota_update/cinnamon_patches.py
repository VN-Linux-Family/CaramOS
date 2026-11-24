"""Make the CaramOS changes to Cinnamon's own files again after a Cinnamon update put the originals back.

CaramOS changes these files of the Mint package cinnamon-common:
- grouped-window-list@cinnamon.org/appGroup.js: 32 px icons in the 40 px dock in the middle of the panel and
  a dot under running apps (migration 20260803120000_apply_three_dock_taskbar);
- systray@cinnamon.org/applet.js: a tray hover as high as the dock (the same migration);
- cinnamon-settings/modules/cs_backgrounds.py: the "CaramOS" wallpaper collection in System Settings >
  Backgrounds (migration 20260804223346_change_default_wallpaper);
- calendar@cinnamon.org/calendar.js and applet.js: lunar dates in the calendar (migration
  20261120100200_lunar_calendar);
- js/misc/inputMethod.js: password boxes are passwords for the input method, so Lotus shows nothing in clear there
  (migration 20261123120000_hidden_password_typing);
- systray@cinnamon.org/applet.js again: the tray icons in a fixed order (migration
  20261124180000_tray_icons_keep_their_place).
An update of Cinnamon installs the original files again: after 6.6.4 -> 6.6.9 the icons in the middle grew
to 48 px and spilled out of their dock (ticket H-1046). Migration 20261018120000 makes the changes again,
and the dpkg trigger of this package (debian/triggers) runs this module after each later update:

    python3 -I -m caramos_ota_update.cinnamon_patches

Run that way, a change is made again only when the migration that first made it is in the ledger, so a
computer that never had the CaramOS taskbar keeps Cinnamon as it is. Each change checks the code it edits
and leaves a file it does not recognise alone, so a Cinnamon that changed those lines keeps working as is.
The changes show from the next login.
"""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
from collections.abc import Collection
from pathlib import Path
from types import ModuleType

from caramos_ota.logging_utils import init_log, log_error

from .context import MigrationContext
from .ledger import MigrationLedgerError, applied_ids, load_ledger

TASKBAR_MIGRATION = "20260803120000_apply_three_dock_taskbar"
WALLPAPER_MIGRATION = "20260804223346_change_default_wallpaper"
LUNAR_MIGRATION = "20261120100200_lunar_calendar"
PASSWORD_MIGRATION = "20261123120000_hidden_password_typing"
TRAY_ORDER_MIGRATION = "20261124180000_tray_icons_keep_their_place"
# Since 6.6.9 Cinnamon itself makes tray buttons as high as the panel, which is what the hover change did.
NATIVE_FULL_HEIGHT_TRAY = "            button.set_y_align(Clutter.ActorAlign.FILL);\n"


def _migration(name: str) -> ModuleType:
    return importlib.import_module(f"caramos_ota_update.migrations.{name}.migration")


def _write_atomic(path: Path, content: str, mode: int) -> None:
    descriptor, staging_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    staging = Path(staging_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        staging.chmod(mode)
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def restore_taskbar(context: MigrationContext) -> None:
    taskbar = _migration(TASKBAR_MIGRATION)
    taskbar._install_running_dot(context)
    try:
        tray = taskbar.SYSTRAY_TARGET.read_text(encoding="utf-8")
    except OSError:
        tray = ""
    if taskbar.SYSTRAY_HOVER_MARKER not in tray and NATIVE_FULL_HEIGHT_TRAY in tray:
        context.log(f"Cinnamon already gives tray icons a full-height hover: {taskbar.SYSTRAY_TARGET}")
    else:
        taskbar._install_systray_hover(context)


def restore_wallpaper_collection_name(context: MigrationContext) -> None:
    wallpaper = _migration(WALLPAPER_MIGRATION)
    module = wallpaper.CINNAMON_BACKGROUNDS_MODULE
    if module.is_symlink() or not module.is_file():
        context.log(f"warning: {module} is not a regular file; the collection keeps its name")
        return
    source = module.read_text(encoding="utf-8")
    try:
        patched = wallpaper._patched_cinnamon_source(source)
    except RuntimeError as exc:
        context.log(f"warning: {module}: {exc}; the collection keeps its name")
        return
    if patched == source:
        context.log(f"CaramOS wallpaper collection already named in {module}")
        return
    context.log(f"name the CaramOS wallpaper collection again: {module}")
    if not context.dry_run:
        _write_atomic(module, patched, module.stat().st_mode & 0o777)


def restore(context: MigrationContext, applied: Collection[str] | None = None) -> None:
    """Make the changes again; with applied, only those of the migrations in it."""

    if applied is None or TASKBAR_MIGRATION in applied:
        restore_taskbar(context)
    if applied is None or WALLPAPER_MIGRATION in applied:
        restore_wallpaper_collection_name(context)
    if applied is None or LUNAR_MIGRATION in applied:
        _migration(LUNAR_MIGRATION).restore(context)
    if applied is None or PASSWORD_MIGRATION in applied:
        _migration(PASSWORD_MIGRATION).restore(context)
    if applied is None or TRAY_ORDER_MIGRATION in applied:
        _migration(TRAY_ORDER_MIGRATION).restore(context)


def main() -> int:
    if os.geteuid() != 0:
        print("caramos_ota_update.cinnamon_patches must run as root", file=sys.stderr)
        return 2
    init_log()
    try:
        ledger = load_ledger()
    except MigrationLedgerError as exc:
        log_error(f"Cinnamon changes not restored: {exc}")
        return 1
    if ledger is None:
        print("no CaramOS migration ledger: Cinnamon stays as it is")
        return 0
    try:
        restore(MigrationContext(), applied_ids(ledger))
    except Exception as exc:  # the package manager must finish the Cinnamon update regardless
        log_error(f"Cinnamon changes not restored: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

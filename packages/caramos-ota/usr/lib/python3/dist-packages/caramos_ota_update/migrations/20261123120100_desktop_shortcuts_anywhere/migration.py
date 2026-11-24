"""Create a desktop shortcut works for Google Drive, network shares and phones, and for names with a "#" (ticket
H-1190: "bị lỗi khi tạo Shortcut từ thư mục trong Google Drive, còn thư mục nội bộ trong ổ cứng tạo ok").

The right-click item Create a desktop shortcut of Files (Nemo) is the spice create-desktop-shortcut@anaximeno;
migration 20261117100100_nemo_actions_in_menu wrote its action file. Its script gets the selection as paths (%F) and
puts a symbolic link to each on the Desktop. For a place GVfs opens (Google Drive of Online Accounts, smb://, sftp://,
mtp://), the path is in GVfs's FUSE folder (/run/user/UID/gvfs/...): Google Drive names folders there by their IDs,
and any such link breaks once the place is unmounted. Nemo also passes a "#" in a name as "\\#", which the script
keeps, so it reports "Couldn't create all shortcuts!" for "Báo cáo #1" even on the computer's own disk.

The action now runs /usr/share/caramos-ota/desktop-shortcut/caramos-desktop-shortcut with the URIs (%U): local files and
folders still get the spice's symbolic links, from plain paths; a place of GVfs gets a link launcher
(Type=Link, URL=<its URI>) named as Files shows it, which opens the place from the Desktop and mounts it when needed,
on Cinnamon and on Xfce.

Only an Exec line that is the spice's own is changed; an action file someone edited, or one that is not there, stays
as it is. Nemo reads the change at once.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Create a desktop shortcut also for Google Drive, network shares and phones"

ACTION = Path("/usr/share/nemo/actions/create-desktop-shortcut@anaximeno.nemo_action")
HELPER = Path("/usr/share/caramos-ota/desktop-shortcut/caramos-desktop-shortcut")
EXEC = f'Exec={HELPER} "%U"'
# The spice's Exec line (cinnamon-spices-actions, 2026-11-17), with or without the quotes.
SPICE_EXEC = re.compile(r'^Exec=<create-desktop-shortcut@anaximeno/action\.py "?%F"?>[ \t]*$')


def updated(text: str) -> str:
    """The action file with this Exec line; the same text when it has it already, "" when its Exec line is not the
    spice's own."""

    lines = text.splitlines(keepends=True)
    execs = [index for index, line in enumerate(lines) if line.startswith("Exec=")]
    if len(execs) != 1:
        return ""
    line = lines[execs[0]].rstrip("\r\n")
    if line == EXEC:
        return text
    if not SPICE_EXEC.match(line):
        return ""
    lines[execs[0]] = EXEC + "\n"
    return "".join(lines)


def _write(path: Path, content: str) -> None:
    fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.chmod(staging, path.stat().st_mode & 0o777)
        os.replace(staging, path)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise


def run(context: MigrationContext, action: Path = ACTION) -> None:
    if action.is_symlink() or not action.is_file():
        context.log(f"{action} is not installed; nothing to change")
        return
    text = action.read_text(encoding="utf-8")
    new = updated(text)
    if not new:
        context.log(f"warning: the Exec line of {action} is not the spice's own; it stays as it is")
        return
    if new == text:
        context.log(f"{action} already makes shortcuts to any place")
        return
    context.log(f"make shortcuts to Google Drive, network shares and phones too: {action}")
    if not context.dry_run:
        _write(action, new)

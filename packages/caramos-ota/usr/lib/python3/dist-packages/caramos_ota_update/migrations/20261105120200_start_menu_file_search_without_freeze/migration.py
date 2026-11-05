"""Keep the desktop responsive while the Start Menu searches the home folder.

The Cinnamenu Start Menu also searches file names in the home folder ("Search home folder", on by default),
and that search runs on Cinnamon's main loop, so whatever it waits for freezes the whole desktop:

- the Cinnamenu of the CaramOS 1.3.0 to 1.3.3 ISOs (5.4.14) asks, for every file of every folder it reads,
  for the icon and the content type, which makes GIO read the start of every file whose name does not tell
  its type, and it reads the folders with the blocking next_file();
- the Cinnamenu ISOs built after 2026-10-30 carry (5.7) reads the folders in the background but asks for the
  icon and the content type of each match with a blocking query_info().

Both also go down into every folder, the disks and network drives mounted in the home folder included (Google
Drive mounted with rclone, a data partition). A user reported the menu freezing and turned the home folder
search off. Measured in the test VMs, with the longest stall of Cinnamon's main loop:
- typing "img" in a home folder of 14,000 photos and notes, on a slow disk (100 IOPS) with a cold cache:
  4.9 s with Cinnamenu 5.4.14 and 11 s with 5.7; 0.4 s and 0.3 s with this change; 0.3 s with the search off;
- typing "drive" with a network drive (sshfs, 80 ms round trips) mounted in the home folder, Cinnamenu 5.4.14:
  Cinnamon stalled 17 s in all, in 20 stalls of over half a second; 0.5 s in all with this change.

The search now takes the type of a file from its name (standard::fast-content-type, read with the folder, and
the icon of that type), and stays on the file system of the folder it starts in, as `find -xdev` does. The
Cinnamenu version folders whose search has the code the change goes into are patched; any other is left as it
is. Cinnamenu is reloaded in the sessions of logged-in users.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from caramos_ota_update.context import MigrationContext

composing = importlib.import_module("caramos_ota_update.migrations.20261105120100_search_menu_while_composing.migration")
start_fcitx = importlib.import_module("caramos_ota_update.migrations.20261022120000_start_fcitx_at_login.migration")

DESCRIPTION = "Start Menu file search no longer freezes the desktop"

SYSTEMD_RUNTIME = Path("/run/systemd/system")
CINNAMENU = Path("/usr/share/cinnamon/applets/Cinnamenu@json")
MARKER = "// CaramOS: the file search runs on Cinnamon's main loop"
BLOCK_START = "//----home folder search--------"
BLOCK_END = "///----search providers--------"

START_FOLDER = re.compile(r"(?P<indent>[ \t]*)foldersToDo\.push\(this\.settings\.searchStartFolder\);[^\n]*\n")
HELPERS = """{indent}// CaramOS: the file search runs on Cinnamon's main loop, so it must not wait for the disk or the network:
{indent}// the type of a file comes from its name, read with the folder, and the search stays on the file
{indent}// system it starts in, out of disks and network drives mounted in the home folder.
{indent}const caramosDevice = (() => {{
{indent}    try {{
{indent}        return Gio.file_new_for_path(this.settings.searchStartFolder)
{indent}            .query_info('unix::device', Gio.FileQueryInfoFlags.NONE, null).get_attribute_uint32('unix::device');
{indent}    }} catch (e) {{
{indent}        return null;
{indent}    }}
{indent}}})();
{indent}const caramosOnStartDevice = (info) =>
{indent}    caramosDevice === null || info.get_attribute_uint32('unix::device') === caramosDevice;
{indent}const caramosType = (info) => info.get_file_type() === Gio.FileType.DIRECTORY ? 'inode/directory' :
{indent}    info.get_attribute_string('standard::fast-content-type') || 'application/octet-stream';
"""

# (pattern, replacement) pairs; each pattern must occur exactly once in the home folder search.
OLD_SEARCH = (  # Cinnamenu 5.4.14: reads each folder with next_file() and asks for every file's icon and type
    (re.compile(r"'standard::name,standard::type,standard::icon,standard::content-type,'(\s*)\+(\s*)"
                r"'standard::is-hidden,standard::is-symlink'"),
     r"'standard::name,standard::type,standard::fast-content-type,unix::device,'\1+\2"
     r"'standard::is-hidden,standard::is-symlink'"),
    (re.compile(r"gicon: next\.get_icon\(\),"), "gicon: Gio.content_type_get_icon(caramosType(next)),"),
    (re.compile(r"mimeType: next\.get_content_type\(\),"), "mimeType: caramosType(next),"),
    (re.compile(r"if \(isDirectory && !next\.get_is_symlink\(\) &&"),
     "if (isDirectory && !next.get_is_symlink() && caramosOnStartDevice(next) &&"),
)
NEW_SEARCH = (  # Cinnamenu 5.7: reads the folders in the background, asks for each match's icon and type
    (re.compile(r"enumerate_children_async\('standard::name,standard::type,standard::is-symlink',"),
     "enumerate_children_async('standard::name,standard::type,standard::is-symlink,"
     "standard::fast-content-type,unix::device',"),
    (re.compile(r"const extraFileInfo = file\.query_info\('standard::icon,standard::content-type',\s*"
                r"Gio\.FileQueryInfoFlags\.NONE, null\);"),
     "const extraFileInfo = {get_icon: () => Gio.content_type_get_icon(caramosType(fileInfo)),\n"
     "                                                              get_content_type: () => caramosType(fileInfo)};"),
    (re.compile(r"if \(isDirectory && \(!fileInfo\.get_is_symlink\(\) \|\| FOLLOW_SYMLINKS\) &&"),
     "if (isDirectory && (!fileInfo.get_is_symlink() || FOLLOW_SYMLINKS) && caramosOnStartDevice(fileInfo) &&"),
)


def _apply(block: str, edits) -> str | None:
    for pattern, _replacement in edits:
        if len(pattern.findall(block)) != 1:
            return None
    for pattern, replacement in edits:
        block = pattern.sub(lambda match: match.expand(replacement), block, count=1)
    return block


def patched(applet: str) -> str | None:
    """applet.js with the change; None when its home folder search is not one of the two known forms."""

    start = applet.find(BLOCK_START)
    end = applet.find(BLOCK_END, start)
    if start < 0 or end < 0 or applet.count(BLOCK_START) != 1 or "const Gio = imports.gi.Gio;" not in applet:
        return None
    block = applet[start:end]
    folders = list(START_FOLDER.finditer(block))
    if len(folders) != 1:
        return None
    for edits in (OLD_SEARCH, NEW_SEARCH):
        result = _apply(block, edits)
        if result is not None:
            break
    else:
        return None
    folder = START_FOLDER.search(result)
    result = result[:folder.end()] + HELPERS.format(indent=folder.group("indent")) + result[folder.end():]
    return applet[:start] + result + applet[end:]


def patch_folder(context: MigrationContext, folder: Path) -> bool:
    applet_path = folder / "applet.js"
    if not applet_path.is_file() or applet_path.is_symlink():
        return False
    applet = applet_path.read_text(encoding="utf-8")
    if MARKER in applet:
        context.log(f"the file search of {folder} already keeps the desktop responsive")
        return False
    result = patched(applet)
    if result is None:
        context.log(f"{folder} has another Cinnamenu file search; leave it as it is")
        return False
    context.log(f"keep the file search of {folder} from freezing the desktop")
    if not context.dry_run:
        composing._write(applet_path, result)
    return True


def run(context: MigrationContext) -> None:
    if not CINNAMENU.is_dir():
        context.log(f"{CINNAMENU} is not installed")
        return
    changed = False
    for folder in sorted(path for path in CINNAMENU.iterdir() if path.is_dir() and not path.is_symlink()):
        changed = patch_folder(context, folder) or changed
    if changed and not context.dry_run and SYSTEMD_RUNTIME.is_dir():
        composing._reload_in_sessions(context)

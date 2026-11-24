"""Tray icons keep their place in Cinnamon's system tray (a follow-up to ticket H-1211).

Cinnamon's tray applet (systray@cinnamon.org/applet.js) put each icon that came in first, at the left of the tray.
The order of the icons was then the order in which their programs made them, and an icon jumped to the front each
time its program made it again. Since H-1211 the Control Center has some icons made again when the theme changes
(caramos-tray-refresh: Update Manager's shield, System Information's mark, Flameshot's flame), so turning Dark mode
on or off shuffled the tray; and at login the order depended on which program started first.

The line that put an icon first is replaced by a marked block that puts it at a fixed place: icons of other programs
at the left, by name, then the ones CaramOS knows, in the order a CaramOS login shows them: System Information
(tray.py), Update Manager (mintupdate.py), CopyQ, the input method (fcitx) and Flameshot, next to the clock.

The block replaces one line of the file, checked first; a file whose line changed is left as it is. A Cinnamon
update puts the original file back: caramos_ota_update.cinnamon_patches makes the change again after each one
(debian/triggers). Cinnamon reads the file when it starts, so the change shows from the next login.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Give the icons of Cinnamon's system tray a fixed order"

SYSTRAY_JS = Path("/usr/share/cinnamon/applets/systray@cinnamon.org/applet.js")
START = "// CARAMOS_TRAY_ORDER_START"
END = "// CARAMOS_TRAY_ORDER_END"
ANCHOR = "            this.button_box.insert_child_at_index(button, 0);\n"
# Left to right, at the right end of the tray next to the clock, by the role Cinnamon gives each icon (its program's
# window class, lower case): the order of a CaramOS login. Any other program's icon goes before these.
ORDER = ("tray.py", "mintupdate.py", "copyq", "fcitx", "fcitx5", "flameshot")
BLOCK = f"""            {START} (ticket H-1211): each new icon used to go first, so the order was the order
            // in which programs made their icons, and an icon jumped to the front when its program made it again (a
            // theme change, a restart). Other programs' icons come first, by name; then these, next to the clock.
            const caramosOrder = {json.dumps(list(ORDER))};
            const caramosKey = (name) => [caramosOrder.indexOf(name), name];
            button._caramosRole = String(role).toLowerCase();
            const [caramosRank, caramosName] = caramosKey(button._caramosRole);
            let caramosIndex = 0;
            for (const other of this.button_box.get_children()) {{
                const [rank, name] = caramosKey(other._caramosRole || "");
                if (rank > caramosRank || (rank === caramosRank && name > caramosName))
                    break;
                caramosIndex++;
            }}
            this.button_box.insert_child_at_index(button, caramosIndex);
            {END}
"""


def patched(source: str) -> str:
    """applet.js with the block; the same text when it is there already, "" when the line it replaces is not there
    exactly once."""

    if source.count(START) == 1 and source.count(END) == 1:
        return source
    if START in source or END in source or source.count(ANCHOR) != 1:
        return ""
    return source.replace(ANCHOR, BLOCK, 1)


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


def restore(context: MigrationContext, path: Path = SYSTRAY_JS) -> None:
    """Puts the block into Cinnamon's tray applet, when the file is the one it knows."""

    if path.is_symlink() or not path.is_file():
        context.log(f"no Cinnamon tray applet at {path}; nothing to change")
        return
    source = path.read_text(encoding="utf-8")
    new = patched(source)
    if not new:
        context.log(f"warning: {path} is not as expected; the tray keeps Cinnamon's order")
        return
    if new == source:
        context.log("the tray icons have their fixed order already")
        return
    context.log(f"give the tray icons a fixed order: {path}")
    if not context.dry_run:
        _write(path, new)


def run(context: MigrationContext) -> None:
    restore(context)

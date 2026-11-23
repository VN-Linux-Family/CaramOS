"""The middle island of the taskbar in the middle of the screen or next to the menu (ticket H-1181).

The Control Center gets a Taskbar tile with two choices, Centre and Left, as Windows 11 has (the code is in the
package: the Cinnamon applet moves Cinnamon's window list between the middle and the left zone of the panel; the
Xfce Control Center moves the dock into the menu's panel).

On Cinnamon the middle island was painted on the middle zone of the panel (migration 20260803120000). A window list
moved into the left zone would have no island, and the empty middle zone would still paint one. The island is now
the window list's own box, in the CaramOS light theme (here, /usr/share/themes/Cinnamon-Delight, which the ISO
installs) and in the dark theme (Cinnamon-Delight-Dark, in the package): it goes wherever the window list goes, and
looks the same as before. The Control Center reloads the theme when someone picks a place, so the change shows
without logging in again.

The Xfce edition needs nothing here; its Control Center tile comes with the package.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Paint the middle island of the Cinnamon taskbar on the window list, so it can sit next to the menu"

THEME_CSS = Path("/usr/share/themes/Cinnamon-Delight/cinnamon/cinnamon.css")
START = "/* CARAMOS_20260803120000_PANEL_DOCKS_START */"
END = "/* CARAMOS_20260803120000_PANEL_DOCKS_END */"

_CENTRE_ZONE = re.compile(
    r"\.panelCenter \{\n  background-color: (?P<fill>[^;]+);\n  border-radius: 999px;\n  box-shadow: (?P<ring>[^;]+);\n"
    r"  margin-top: 4px;\n  margin-bottom: 4px;\n  padding-left: 0;\n  padding-right: 0;\n\}\n")
_WINDOW_LIST_RULES = (
    ".panelCenter .grouped-window-list-box {\n  spacing: 0;\n}\n\n"
    ".panelCenter .grouped-window-list-item-box {\n  margin-left: 0;\n}\n\n"
    ".panelCenter .grouped-window-list-item-box:hover,\n.panelCenter .grouped-window-list-item-box:focus {\n"
    "  border-radius: 999px;\n}\n")


def island_on_window_list(block: str) -> str:
    """The CaramOS dock block with the middle island painted on the window list instead of the middle zone.

    "" when the block is not the one of migration 20260803120000 (or its dark copy): changed since, or done already.
    """

    centre = _CENTRE_ZONE.search(block)
    if centre is None or block.count(_WINDOW_LIST_RULES) != 1:
        return ""
    zone = (".panelCenter {\n  background-color: transparent;\n  box-shadow: none;\n  padding-left: 0;\n"
            "  padding-right: 0;\n}\n\n"
            "/* The middle island is the window list's own box: it goes with the window list next to the menu (Control\n"
            "   Center, Taskbar: Left; ticket H-1181), and the empty middle zone then paints nothing. */\n"
            ".grouped-window-list-box {\n"
            f"  background-color: {centre.group('fill')};\n  border-radius: 999px;\n  box-shadow: {centre.group('ring')};\n"
            "  margin-top: 4px;\n  margin-bottom: 4px;\n  spacing: 0;\n}\n")
    window_list = (".grouped-window-list-item-box {\n  margin-left: 0;\n}\n\n"
                   ".grouped-window-list-item-box:hover,\n.grouped-window-list-item-box:focus {\n"
                   "  border-radius: 999px;\n}\n")
    return block.replace(centre.group(0), zone).replace(_WINDOW_LIST_RULES, window_list)


def theme_with_island_on_window_list(css: str) -> str:
    """The whole theme CSS with its dock block changed, or "" when it has no single such block to change."""

    if css.count(START) != 1 or css.count(END) != 1 or css.index(START) > css.index(END):
        return ""
    start, end = css.index(START), css.index(END)
    block = island_on_window_list(css[start:end])
    return css[:start] + block + css[end:] if block else ""


def run(context: MigrationContext, theme_css: Path = THEME_CSS) -> None:
    if theme_css.is_symlink() or not theme_css.is_file():
        context.log(f"no {theme_css}; nothing to change")
        return
    new = theme_with_island_on_window_list(theme_css.read_text(encoding="utf-8"))
    if not new:
        context.log(f"{theme_css}: no CaramOS middle island painted on the zone; left alone")
        return
    context.log(f"paint the middle island on the window list: {theme_css}")
    if context.dry_run:
        return
    # Replaced in one step, with the file's mode, as migration 20260803120000 writes it.
    fd, staging = tempfile.mkstemp(prefix=".caramos-taskbar-", dir=theme_css.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(new)
        shutil.copymode(theme_css, staging)
        os.replace(staging, theme_css)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise

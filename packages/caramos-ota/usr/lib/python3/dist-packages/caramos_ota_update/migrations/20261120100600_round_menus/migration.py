"""Round menus on both editions, like the islands of the taskbar and the Control Center (users asked for it after
1.4.0; the CaramOS menu of the Xfce edition is migration 20261120100500).

- Right-click menus of GTK 3 programs (Nemo, Thunar, the Xfce desktop and panel): caramos-ota's
  /usr/share/caramos-ota/gtk/round-menus.css, which the CaramOS light theme (/usr/share/themes/Cinnamon-Delight, which
  the ISO installs) now imports at the end of its gtk-3.0/gtk.css. The dark theme, in the package, imports it itself.
- Cinnamon's own menus (the Start menu, the calendar, the panel's and the applets' menus): CINNAMON_BLOCK at the end of
  the light theme's cinnamon/cinnamon.css; the dark theme has the same block. Every menu gets round corners, the Start
  menu (Cinnamenu) rounder, like the Xfce edition's, and the item under the pointer is round, a little in from the
  sides. The Control Center keeps its own card (its applet's stylesheet).

The block is replaced when a later version changes it. A file whose block is cut in half is left alone. Both changes
show from the next login.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Round corners for the menus of both editions"

THEME = Path("/usr/share/themes/Cinnamon-Delight")
GTK_CSS = "gtk-3.0/gtk.css"
CINNAMON_CSS = "cinnamon/cinnamon.css"
GTK_IMPORT = ('/* CaramOS: round right-click menus, on both editions (caramos-ota). */\n'
              '@import url("file:///usr/share/caramos-ota/gtk/round-menus.css");\n')
START = "/* CARAMOS_20261120100600_ROUND_MENUS_START */"
END = "/* CARAMOS_20261120100600_ROUND_MENUS_END */"
CINNAMON_BLOCK = f"""{START}
/* CaramOS: menus with round corners, like the islands and the Control Center (users asked for it after 1.4.0). The
   same block ends the light and the dark theme (migration 20261120100600). */
.menu,
.menu.top,
.menu.bottom,
.menu.left,
.menu.right {{
  border-radius: 12px;
}}

.popup-menu-boxpointer {{
  -arrow-border-radius: 12px;
}}

/* The Start menu (Cinnamenu), as round as the CaramOS menu of the Xfce edition, with round buttons and search box. */
.menu.menu-background,
.menu.menu-background.top,
.menu.menu-background.bottom,
.menu.menu-background.left,
.menu.menu-background.right {{
  border-radius: 20px;
}}

.menu-background .menu-category-button,
.menu-background .menu-category-button-selected,
.menu-background .menu-category-button-hover,
.menu-background .menu-category-button-greyed,
.menu-background .menu-application-button,
.menu-background .menu-application-button-selected,
.menu-background .menu-favorites-button {{
  border-radius: 10px;
}}

.menu-background #menu-search-entry {{
  border-radius: 999px;
}}

/* The item under the pointer is round too, a little in from the menu's sides. */
.popup-menu-item,
.popup-menu .popup-menu-item {{
  border-radius: 8px;
  margin-left: 6px;
  margin-right: 6px;
}}
{END}
"""


def gtk_with_import(css: str) -> str:
    """The theme's gtk.css importing round-menus.css at its end, after the theme's own menu rules."""

    if "/usr/share/caramos-ota/gtk/round-menus.css" in css:
        return css
    return css.rstrip("\n") + "\n\n" + GTK_IMPORT


def cinnamon_with_block(css: str) -> str:
    """The theme's cinnamon.css ending with this version's block; "" when a block is there only in part."""

    has_start, has_end = START in css, END in css
    if has_start and has_end:
        begin, finish = css.index(START), css.index(END) + len(END)
        if finish < begin:
            return ""
        rest = css[finish:]
        return css[:begin] + CINNAMON_BLOCK.rstrip("\n") + (rest if rest.startswith("\n") else "\n" + rest)
    if has_start or has_end:
        return ""
    return css.rstrip("\n") + "\n\n" + CINNAMON_BLOCK


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


def restore(context: MigrationContext, theme: Path = THEME) -> None:
    for name, change in ((GTK_CSS, gtk_with_import), (CINNAMON_CSS, cinnamon_with_block)):
        path = theme / name
        if path.is_symlink() or not path.is_file():
            context.log(f"no {path}; nothing to change")
            continue
        try:
            current = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            context.log(f"warning: {path} could not be read ({exc}); left alone")
            continue
        new = change(current)
        if not new:
            context.log(f"warning: {path} has part of a CaramOS block; left alone")
        elif new == current:
            context.log(f"{path}: the menus are round already")
        else:
            context.log(f"round menus: {path}")
            if not context.dry_run:
                _write(path, new)


def run(context: MigrationContext) -> None:
    restore(context)

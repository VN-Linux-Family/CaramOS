"""Lotus's V in the tray follows the light and the dark theme without logging out (ticket H-1211).

Lotus (fcitx5-lotus) picks its tray icon by colour: fcitx-lotus-default-black, a black V, when it finds the session
light, and fcitx-lotus-default, a white V, when it finds it dark (the same for its -off and -emoji icons). It looks
again only when Fcitx asks for the icon, when a text field gets the focus, and not more than every 5 seconds. Right
after the Dark mode tile, the tray still had the name of the old mode, and drew it again in the new icon theme with
the same picture: a black V on the dark island, until a text field took the focus or the next login.

Here each of CaramOS's two icon themes gets the other name too, with the picture that suits it: Tela-circle-dark gives
the white V for fcitx-lotus-default-black, Tela-circle-light the black V for fcitx-lotus-default. Whatever name Lotus
gave last, the icon has the colour of the icon theme in use, and the tray draws it again when the icon theme changes:
the Xfce panel and Fcitx's own tray icon (Cinnamon) both do. They are links to Lotus's own pictures, in each theme's
symbolic/status folder, the one folder of its own that is scalable (its 16/panel and the like are links into Tela-circle
or shared ones). The theme's icon cache is then made again; Fcitx and GTK skip an out-of-date one.

A name a theme already has is left as it is, and nothing is linked when Lotus's pictures are not there. The ISO build
runs this migration after it installed Tela and Lotus.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Lotus's tray icon follows the light and the dark theme"

ICONS = Path("/usr/share/icons")
LOTUS_ICONS = ICONS / "hicolor/scalable/status"
FOLDER = "symbolic/status"
BASES = ("fcitx-lotus", "fcitx-lotus-off", "fcitx-lotus-emoji")
# Icon theme: (the name that gets a picture, Lotus's picture it shows).
LINKS = {
    "Tela-circle-dark": ("{}-default-black", "{}-default"),
    "Tela-circle-light": ("{}-default", "{}-default-black"),
}


def planned_links() -> dict[Path, list[tuple[Path, Path]]]:
    """For each icon theme: the (link, picture) pairs to make."""

    plan: dict[Path, list[tuple[Path, Path]]] = {}
    for theme, (name, picture) in LINKS.items():
        root = ICONS / theme
        folder = root / FOLDER
        if not (root / "index.theme").is_file() or not folder.is_dir() or folder.is_symlink() or root.is_symlink():
            continue
        for base in BASES:
            link = folder / f"{name.format(base)}.svg"
            target = LOTUS_ICONS / f"{picture.format(base)}.svg"
            if target.is_file() and not link.exists() and not link.is_symlink():
                plan.setdefault(root, []).append((link, target))
    return plan


def run(context: MigrationContext) -> None:
    plan = planned_links()
    if not plan:
        context.log("Lotus's tray icons: nothing to link (no Tela-circle-light/-dark, no Lotus, or done before)")
        return
    for root, links in plan.items():
        for link, target in links:
            context.log(f"link {link} -> {target}")
            if not context.dry_run:
                link.symlink_to(target)
        if shutil.which("gtk-update-icon-cache"):
            context.run_command(["gtk-update-icon-cache", "--force", "--quiet", str(root)], allow_fail=True)

"""Which desktop this CaramOS runs: the Cinnamon edition or the Xfce edition (the light one, for 2 GB computers).

Migrations that change only Cinnamon (its panel, applets, Start Menu, keyboard shortcuts, Backgrounds) say so in
their manifest ("desktops": ["cinnamon"]); the runner skips them elsewhere and records them as done, so the Xfce
edition's ISO build and updates never touch Cinnamon files it does not have. A migration without the field runs
on every edition.
"""

from __future__ import annotations

import os
from pathlib import Path

CINNAMON = "cinnamon"
XFCE = "xfce"
KNOWN = (CINNAMON, XFCE)
# The session binary of each desktop, as installed by Linux Mint's editions (also inside the ISO build's chroot).
MARKERS = ((CINNAMON, Path("/usr/bin/cinnamon")), (XFCE, Path("/usr/bin/xfce4-session")))


def current_desktop(root: Path = Path("/")) -> str:
    """"cinnamon", "xfce" or "other". CARAMOS_OTA_DESKTOP overrides it (tests, special builds)."""

    forced = os.environ.get("CARAMOS_OTA_DESKTOP", "").strip()
    if forced:
        return forced
    for name, marker in MARKERS:
        if (root / marker.relative_to("/")).exists():
            return name
    return "other"


def applies(desktops, desktop: str | None = None) -> bool:
    """Whether a migration for these desktops (empty: all) applies here.

    Only a desktop known to be another edition skips it: an unknown one ("other": a package build, a chroot without
    a session) keeps the behaviour from before desktops existed, so nothing changes for CaramOS Cinnamon.
    """

    if not desktops:
        return True
    desktop = current_desktop() if desktop is None else desktop
    return desktop not in KNOWN or desktop in desktops

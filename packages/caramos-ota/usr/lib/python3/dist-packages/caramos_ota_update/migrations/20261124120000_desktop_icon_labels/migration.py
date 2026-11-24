"""The names under the desktop icons of the Cinnamon edition read on light wallpapers too: a dark shadow on every side
of the letters, the same as the Xfce edition's desktop names (ticket H-1187, in xfce/panel-islands.css there).

Cinnamon's desktop is nemo-desktop. It styles these names in Nemo's own CSS (nemo-style-application.css), which Nemo
loads at application priority, above any GTK theme, so the CaramOS themes cannot change them: their
.nemo-desktop.nemo-canvas-item rules never show, and the names keep Nemo's faint 1 px shadow.

The package does the work: /usr/share/caramos-ota/nemo-menu/caramos-nemo-menu writes Nemo's CSS from the installed
library with only that shadow made stronger, to /var/lib/caramos-ota/nemo-menu/nemo-style-application.css (run by
postinst, again after every Nemo update, and here, which also covers the ISO build), and
/etc/X11/Xsession.d/85caramos-nemo-desktop-labels points Nemo at it through G_RESOURCE_OVERLAYS. The running
session's nemo-desktop keeps its CSS, so the change shows from the next login; nothing on the screen changes now. A
failure is logged and does not stop the update; Nemo then keeps its own CSS.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "A stronger shadow under the names of the desktop icons"

GENERATOR = Path("/usr/share/caramos-ota/nemo-menu/caramos-nemo-menu")


def run(context: MigrationContext, generator: Path = GENERATOR) -> None:
    if context.dry_run:
        context.log(f"run {generator}")
        return
    if not generator.exists():
        context.log(f"{generator} is missing; the desktop icons keep Nemo's own shadow")
        return
    result = subprocess.run([str(generator)], check=False, capture_output=True, text=True)
    output = "\n".join(line for line in (result.stdout + result.stderr).splitlines() if line.strip())
    context.log(output[:600] or f"{generator} exited {result.returncode}")

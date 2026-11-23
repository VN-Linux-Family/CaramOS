"""The Windows migration kit's tools: Chuyển dữ liệu từ Windows, Chuyển mã sang Unicode, and Driver Check's report.

The package brings the programs: caramos-windows-transfer (with its menu entry) copies an old Windows computer's
documents, pictures, browser bookmarks, Outlook mail and fonts, and sets the typing method; caramos-unicode, with its
right-click action in Files (/usr/share/nemo/actions/caramos-unicode.nemo_action), turns old TCVN3 and VNI text into
Unicode in a new file; Driver Check saves what it found as a web page. The menu and Files pick them up at once.

Outlook keeps mail in .pst files, which readpst (package pst-utils, about 0.2 MB to download with libpst) turns into
mbox files Thunderbird reads. It is installed where it is missing, as the ISO does from config/packages.txt; without
it the transfer copies the .pst files as they are and says so. A failure is logged and does not stop the update.
"""

from __future__ import annotations

from caramos_ota_update.context import MigrationContext, MigrationContextError

DESCRIPTION = "Install readpst for the Windows data transfer; announce the Windows migration tools"

PACKAGE = "pst-utils"


def installed(context: MigrationContext, package: str) -> bool:
    result = context.run_command(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", package], allow_fail=True)
    return result is not None and result.returncode == 0 and result.stdout.startswith("ii")


def run(context: MigrationContext) -> None:
    if installed(context, PACKAGE):
        context.log(f"{PACKAGE} is installed")
        return
    try:
        context.apt_install([PACKAGE], recommends=False)
    except MigrationContextError as exc:
        context.log(f"could not install {PACKAGE} ({exc}); the transfer copies Outlook's .pst files as they are")

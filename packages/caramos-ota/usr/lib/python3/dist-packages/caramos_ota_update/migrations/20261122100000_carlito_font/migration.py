"""Carlito, the font with Calibri's sizes, on both editions (the Windows migration kit).

Calibri has been the default font of Word, Excel and PowerPoint since Office 2007. A computer without it shows
another font in its place, whose letters have other widths: lines break elsewhere, a table grows a column and a
one-page form runs onto a second page. Carlito has the same width for every letter (it is "metric-compatible"),
covers Vietnamese, and is free; fontconfig's metric aliases and LibreOffice use it wherever a document asks for
Calibri. The ISO installs it from config/packages.txt; this installs it where it is missing (about 0.8 MB to
download). Times New Roman and Arial stay in the App Center's "Microsoft Core Fonts" (recipe ms-fonts), whose
licence the user accepts there; Microsoft's fonts are never shipped by CaramOS. Caladea, the same kind of
replacement for Cambria, has no Vietnamese letters, so it is not installed.
"""

from __future__ import annotations

from caramos_ota_update.context import MigrationContext, MigrationContextError

DESCRIPTION = "Install Carlito, the free font with the sizes of Calibri"

PACKAGE = "fonts-crosextra-carlito"


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
        context.log(f"could not install {PACKAGE} ({exc}); documents in Calibri keep another font until it is")

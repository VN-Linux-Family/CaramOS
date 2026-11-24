"""fastfetch with the CaramOS logo, on both editions (ticket H-1203).

neofetch, which CaramOS has from Linux Mint's image, is no longer developed: its repository was archived in April
2024. fastfetch shows the same details of the computer, is maintained, and starts about ten times faster. Ubuntu 24.04
has no fastfetch, so the CaramOS PPA has a backport (packages/fastfetch, about 0.7 MB to download, needs only libc6)
whose /etc/xdg/fastfetch/config.jsonc shows the CaramOS logo; without it fastfetch draws the Ubuntu logo. This
installs it where it is missing.

New installs get it from this migration too: the ISO build runs every migration after the PPA is in the image
(scripts/ota_bootstrap.sh), and stops when fastfetch is missing afterwards (scripts/customize.sh).
config/packages.txt is installed before the PPA is there, so fastfetch is not listed in it.

neofetch stays, with the CaramOS wrapper of hook 0200-caramos-debrand, for anyone who types it out of habit.
"""

from __future__ import annotations

from caramos_ota_update.context import MigrationContext, MigrationContextError

DESCRIPTION = "Install fastfetch, which shows the details of the computer next to the CaramOS logo"

PACKAGE = "fastfetch"


def installed(context: MigrationContext, package: str) -> bool:
    result = context.run_command(["dpkg-query", "-W", "-f=${db:Status-Abbrev}", package], allow_fail=True)
    return result is not None and result.returncode == 0 and result.stdout.startswith("ii")


def run(context: MigrationContext) -> None:
    # A fastfetch the user installed from elsewhere (GitHub, another PPA) stays as it is.
    if installed(context, PACKAGE):
        context.log(f"{PACKAGE} is installed")
        return
    try:
        context.apt_install([PACKAGE], recommends=False)
    except MigrationContextError as exc:
        context.log(f"could not install {PACKAGE} ({exc}); neofetch still shows the details of the computer")

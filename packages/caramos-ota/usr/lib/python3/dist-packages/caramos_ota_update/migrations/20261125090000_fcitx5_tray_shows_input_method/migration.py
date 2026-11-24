"""The input method's V shows in Cinnamon's tray from the login on, with fcitx5 from the CaramOS PPA.

Fcitx5 5.1.7 drew its X11 tray icon, the one Cinnamon's tray shows, for the input context that has the focus, and
the plain keyboard, an "A", while none had it: right after a login, or with the focus on the desktop or the panel.
Lotus was on all the same, and clicking the A to turn Vietnamese on turned it off. The CaramOS PPA has fcitx5
5.1.7-1build3+caramos1, Ubuntu's 5.1.7-1build3 with a patch (packages/fcitx5): the tray draws the input method in
use, and draws again when it changes while nothing has the focus.

This brings the fcitx5 packages installed here up to that version; it installs no package that is not there, and
the packages keep their "installed automatically" marks. Cinnamon only: the Xfce panel shows fcitx's icon its own
way. A computer whose fcitx5 is newer already (a later Ubuntu update) keeps it. New installs get it from the ISO
build, which runs every migration after the PPA is in the image and stops when the version is older afterwards
(scripts/customize.sh). The running fcitx5 keeps the old code until the next login.
"""

from __future__ import annotations

from caramos_ota_update.context import MigrationContext, MigrationContextError

DESCRIPTION = "Upgrade fcitx5 from the CaramOS PPA, so that the tray shows the input method in use from the login on"

# The binary packages of the fcitx5 source that CaramOS has; fcitx5-modules holds the tray (libclassicui.so).
PACKAGES = ("fcitx5", "fcitx5-data", "fcitx5-modules", "libfcitx5config6", "libfcitx5core7", "libfcitx5utils2")
TRAY_PACKAGE = "fcitx5-modules"
FIXED_VERSION = "5.1.7-1build3+caramos1"


def installed_version(context: MigrationContext, package: str) -> str | None:
    """The installed version of a package; None when it is not installed (or in a dry run)."""

    result = context.run_command(["dpkg-query", "-W", "-f=${db:Status-Abbrev}${Version}", package], allow_fail=True)
    if result is None or result.returncode != 0 or not result.stdout.startswith("ii "):
        return None
    return result.stdout[3:].strip() or None


def older(context: MigrationContext, version: str, than: str) -> bool:
    result = context.run_command(["dpkg", "--compare-versions", version, "lt", than], allow_fail=True)
    return result is not None and result.returncode == 0


def automatic(context: MigrationContext, packages: list[str]) -> list[str]:
    """Those of the packages that APT marks as installed automatically."""

    result = context.run_command(["apt-mark", "showauto", *packages], allow_fail=True)
    if result is None or result.returncode != 0:
        return []
    marked = set(result.stdout.split())
    return [package for package in packages if package in marked]


def run(context: MigrationContext) -> None:
    present = [package for package in PACKAGES if installed_version(context, package)]
    tray = installed_version(context, TRAY_PACKAGE)
    if tray is None:
        context.log(f"{TRAY_PACKAGE} is not installed; nothing to change")
        return
    if not older(context, tray, FIXED_VERSION):
        context.log(f"{TRAY_PACKAGE} {tray} draws the input method in use already")
        return
    auto = automatic(context, present)
    try:
        context.apt_install(present, recommends=False, only_upgrade=True)
    except MigrationContextError as exc:
        context.log(f"could not upgrade fcitx5 ({exc}); the tray shows an A until a text box has the focus")
        return
    finally:
        # apt-get install marks the packages it is given as installed by hand; give back the automatic marks.
        if auto:
            context.run_command(["apt-mark", "auto", *auto], allow_fail=True)
    now = installed_version(context, TRAY_PACKAGE)
    if now and not older(context, now, FIXED_VERSION):
        context.log(f"{TRAY_PACKAGE} {now}: the tray shows the input method in use from the next login")
    else:
        context.log(f"warning: {TRAY_PACKAGE} is {now}, older than {FIXED_VERSION}; the CaramOS PPA may not have it yet")

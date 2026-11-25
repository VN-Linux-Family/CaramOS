"""Veyon's Lock and full-screen Demo show on the students' computers, with Veyon from the CaramOS PPA.

Veyon 4.7.5 of Ubuntu 24.04 (4.7.5+repack1-1ubuntu5) shows its lock screen full screen and then raises it with
Qt::WindowStaysOnTopHint; changing the flags of a shown window makes Qt 5 hide it. So Lock emptied the students'
keyboards while their screens stayed as they were, and Demo in full screen showed nothing; only Demo in a window
worked (checked in a VM lab on 2026-11-25: the lock window stays unmapped). Upstream fixed it in Veyon 4.8.0 (issue
#824). Its server also did not start again after it exited (an orange computer in Veyon Master).

The CaramOS PPA has 4.7.5+repack1-1ubuntu5+caramos1 (packages/veyon): Ubuntu's package with upstream's lock fix,
upstream's restart of a crashed server and a backport of upstream's fix for a server lost when a lock screen's
session closes. This brings the Veyon packages installed here up to that version; it installs no package that is not
there (only computers set up by Phòng máy have Veyon), and the packages keep their "installed automatically" marks.
A computer whose Veyon is newer already keeps it. Upgrading restarts veyon.service (the package's postinst): Veyon
Master reconnects within seconds, a lock or a demo in progress ends and can be started again. That happens once, on a
lab computer only, so the migration says "anytime": waiting until nobody is logged in would hold back the automatic
update of every CaramOS computer whose desktop stays open.
"""

from __future__ import annotations

from caramos_ota_update.context import MigrationContext, MigrationContextError

DESCRIPTION = "Upgrade Veyon from the CaramOS PPA, so that its Lock and full-screen Demo show on students' computers"

# The binary packages of the veyon source; libveyon-core has the lock window, veyon-plugins the service's platform code.
PACKAGES = ("libveyon-core", "veyon-plugins", "veyon-service", "veyon-master", "veyon-configurator")
CORE_PACKAGE = "libveyon-core"
FIXED_VERSION = "4.7.5+repack1-1ubuntu5+caramos1"


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
    core = installed_version(context, CORE_PACKAGE)
    if core is None:
        context.log(f"{CORE_PACKAGE} is not installed (no Veyon here); nothing to change")
        return
    if not older(context, core, FIXED_VERSION):
        context.log(f"{CORE_PACKAGE} {core} shows the lock screen already")
        return
    present = [package for package in PACKAGES if installed_version(context, package)]
    auto = automatic(context, present)
    try:
        context.apt_install(present, recommends=False, only_upgrade=True)
    except MigrationContextError as exc:
        context.log(f"could not upgrade Veyon ({exc}); its Lock and full-screen Demo stay hidden on students' screens")
        return
    finally:
        # apt-get install marks the packages it is given as installed by hand; give back the automatic marks.
        if auto:
            context.run_command(["apt-mark", "auto", *auto], allow_fail=True)
    now = installed_version(context, CORE_PACKAGE)
    if now and not older(context, now, FIXED_VERSION):
        context.log(f"{CORE_PACKAGE} {now}: Lock and full-screen Demo show on the students' computers")
    else:
        context.log(f"warning: {CORE_PACKAGE} is {now}, older than {FIXED_VERSION}; "
                    "the CaramOS PPA may not have it yet")

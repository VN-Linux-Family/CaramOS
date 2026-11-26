"""Phòng máy (computer lab): Veyon 4.11.5, the newest Veyon, from the CaramOS PPA in place of 4.7.5.

The owner asked for the newest Veyon in the computer lab (2026-11-26). Up to now the CaramOS PPA had Ubuntu 24.04's
Veyon 4.7.5 with three upstream fixes (20261125120100_veyon_lock_and_demo_show). Upstream's Veyon 4.11.5 (2026-11-20)
has those fixes itself. packages/veyon/4.11 builds it for Ubuntu 24.04 from Debian's packaging, with Qt 6, under the
same five package names; Phòng máy sets it up as before (the same veyon-cli commands, keys, rooms, configuration keys
and veyon.service), and the keys and rooms a lab made with 4.7.5 keep working.

This brings the Veyon packages installed here up to 4.11.5: only on computers that have Veyon (only Phòng máy installs
it), only the Veyon packages that are there, and they keep their "installed automatically" marks. The Qt 6 libraries
Veyon now needs come with it. Upgrading restarts veyon.service once: Veyon Master reconnects within seconds, and a lock
or a demo in progress ends and can be started again. "anytime", as 20261125120100: waiting until nobody is logged in
would hold back the automatic update of every CaramOS computer whose desktop stays open, for a change that only
touches lab computers.
"""

from __future__ import annotations

import importlib

from caramos_ota_update.context import MigrationContext, MigrationContextError

DESCRIPTION = "Computer lab: upgrade Veyon to 4.11.5 from the CaramOS PPA"

veyon_fix = importlib.import_module("caramos_ota_update.migrations.20261125120100_veyon_lock_and_demo_show.migration")

PACKAGES = veyon_fix.PACKAGES
CORE_PACKAGE = veyon_fix.CORE_PACKAGE
VERSION = "4.11.5+repack1-0caramos1"


def run(context: MigrationContext) -> None:
    core = veyon_fix.installed_version(context, CORE_PACKAGE)
    if core is None:
        context.log(f"{CORE_PACKAGE} is not installed (no Veyon here); nothing to change")
        return
    if not veyon_fix.older(context, core, VERSION):
        context.log(f"{CORE_PACKAGE} {core} is Veyon 4.11.5 or newer already")
        return
    present = [package for package in PACKAGES if veyon_fix.installed_version(context, package)]
    auto = veyon_fix.automatic(context, present)
    try:
        context.apt_install(present, recommends=False, only_upgrade=True)
    except MigrationContextError as exc:
        context.log(f"could not upgrade Veyon ({exc}); Veyon {core} stays and keeps working")
        return
    finally:
        # apt-get install marks the packages it is given as installed by hand; give back the automatic marks.
        if auto:
            context.run_command(["apt-mark", "auto", *auto], allow_fail=True)
    now = veyon_fix.installed_version(context, CORE_PACKAGE)
    if now and not veyon_fix.older(context, now, VERSION):
        context.log(f"{CORE_PACKAGE} {now}: Veyon 4.11.5")
    else:
        context.log(f"warning: {CORE_PACKAGE} is {now}, older than {VERSION}; the CaramOS PPA may not have it yet")

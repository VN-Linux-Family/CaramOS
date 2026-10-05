"""Give the GRUB menu of installed systems the CaramOS look.

CaramOS sets GRUB_DISTRIBUTOR="CaramOS", so /etc/grub.d/05_debian_theme falls back to the Debian
cyan-on-blue menu. Users only see that menu on dual-boot machines or when they hold Shift/Esc, which
is also where a broken-looking boot screen hurts most. This migration installs a GRUB theme under
/boot/grub (always readable by GRUB, even with an encrypted root and a separate /boot) and points
GRUB_THEME at it from a grub.d drop-in that leaves a user's own GRUB_THEME alone.

The ISO build runs this in the rootfs, where /boot/grub/grub.cfg does not exist yet: the files land
in the image and the installer's update-grub picks them up. On installed systems update-grub runs
here. If it fails, the old grub.cfg stays in place (grub-mkconfig only replaces it on success) and
the next kernel update regenerates it, so the failure is logged instead of blocking later updates.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Install the CaramOS GRUB theme for the boot menu of installed systems"

PAYLOAD_DIR = Path(__file__).resolve().parent / "payload"
THEME_DIR = Path("/boot/grub/themes/caramos")
THEME_FILES = ("theme.txt", "background.png")
DEFAULTS_FILE = Path("/etc/default/grub.d/60_caramos-theme.cfg")
GRUB_CFG = Path("/boot/grub/grub.cfg")
UPDATE_GRUB = "update-grub"

# Sourced by grub-mkconfig after /etc/default/grub, so ${GRUB_THEME-...} keeps a theme the user set
# there, and GRUB_THEME="" in /etc/default/grub turns the theme off.
DEFAULTS_CONTENT = f"""\
# CaramOS GRUB theme (installed by caramos-ota).
# Set GRUB_THEME in /etc/default/grub to use another theme, or GRUB_THEME="" to turn it off,
# then run: sudo update-grub
GRUB_THEME="${{GRUB_THEME-{THEME_DIR / 'theme.txt'}}}"
"""


def _same_content(source: Path, target: Path) -> bool:
    return target.is_file() and target.read_bytes() == source.read_bytes()


def _atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, staging = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(fd)
    try:
        shutil.copyfile(source, staging)
        os.chmod(staging, 0o644)
        os.replace(staging, target)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise


def _install_theme(context: MigrationContext) -> bool:
    changed = False
    for name in THEME_FILES:
        source = PAYLOAD_DIR / name
        if not source.is_file() or source.stat().st_size == 0:
            raise RuntimeError(f"GRUB theme payload is missing or empty: {source}")
        target = THEME_DIR / name
        if _same_content(source, target):
            context.log(f"file unchanged: {target}")
            continue
        changed = True
        context.log(f"install {target}")
        if not context.dry_run:
            _atomic_copy(source, target)
    return changed


def _install_defaults(context: MigrationContext) -> bool:
    if DEFAULTS_FILE.is_file() and DEFAULTS_FILE.read_text(encoding="utf-8") == DEFAULTS_CONTENT:
        context.log(f"file unchanged: {DEFAULTS_FILE}")
        return False
    context.write_file_if_changed(DEFAULTS_FILE, DEFAULTS_CONTENT)
    return True


def run(context: MigrationContext) -> None:
    theme_changed = _install_theme(context)
    defaults_changed = _install_defaults(context)
    if not (theme_changed or defaults_changed):
        context.log("CaramOS GRUB theme already installed")
        return

    if not GRUB_CFG.is_file():
        context.log(f"skip update-grub: no {GRUB_CFG} (ISO build); the installer's update-grub applies the theme")
        return
    if shutil.which(UPDATE_GRUB) is None:
        context.log(f"skip update-grub: {UPDATE_GRUB} not found; the next GRUB update applies the theme")
        return

    result = context.run_command([UPDATE_GRUB], allow_fail=True)
    if result is not None and result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()[-1:] or ["no output"]
        context.log(
            f"warning: update-grub exited with {result.returncode} ({detail[0]}); "
            "the boot menu keeps its old look until the next successful update-grub"
        )

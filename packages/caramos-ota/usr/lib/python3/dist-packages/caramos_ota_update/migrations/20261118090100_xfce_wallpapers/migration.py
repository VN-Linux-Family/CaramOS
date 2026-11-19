"""CaramOS Xfce: the five CaramOS wallpapers, with Sage Mist as the default, as on CaramOS Cinnamon.

Migration 20260804223346 installs them on Cinnamon together with changes to Cinnamon's Backgrounds settings, which
Xfce does not have, so it is for Cinnamon only. This one copies just the files, into a folder of their own,
/usr/share/backgrounds/CaramOS: Xfce's Desktop settings show the pictures of one folder, and
/usr/share/backgrounds/caramos also holds the boot splash pictures and old wallpapers. New users start on Sage Mist
in that folder (/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-desktop.xml), so the settings open on
the five wallpapers. /usr/share/backgrounds/caramos/default.png, the login screen's background, points at Sage Mist.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Install the CaramOS wallpapers on the Xfce edition, with Sage Mist as the default"

PAYLOAD = Path(__file__).resolve().parents[1] / "20260804223346_change_default_wallpaper" / "payload"
WALLPAPER_DIR = Path("/usr/share/backgrounds/CaramOS")
LOGIN_DEFAULT = Path("/usr/share/backgrounds/caramos/default.png")
DEFAULT_NAME = "03-sage-mist-2k.jpg"


def install(context: MigrationContext, payload: Path = PAYLOAD, wallpapers: Path = WALLPAPER_DIR,
            login_default: Path = LOGIN_DEFAULT) -> None:
    pictures = sorted(payload.glob("*.jpg"))
    if not any(picture.name == DEFAULT_NAME for picture in pictures):
        context.log(f"{payload} has no {DEFAULT_NAME}; wallpapers left as they are")
        return
    wallpapers.mkdir(parents=True, exist_ok=True)
    for picture in pictures:
        target = wallpapers / picture.name
        if target.exists() and target.stat().st_size == picture.stat().st_size:
            continue
        shutil.copyfile(picture, target)
        os.chmod(target, 0o644)
        context.log(f"installed {target}")
    link = os.path.relpath(wallpapers / DEFAULT_NAME, login_default.parent)
    if login_default.is_symlink() and os.readlink(login_default) == link:
        return
    login_default.parent.mkdir(parents=True, exist_ok=True)
    temporary = login_default.with_name(f".{login_default.name}.caramos")
    temporary.unlink(missing_ok=True)
    os.symlink(link, temporary)
    os.replace(temporary, login_default)
    context.log(f"{login_default} -> {link}")


def run(context: MigrationContext) -> None:
    if context.dry_run:
        context.log(f"copy the CaramOS wallpapers to {WALLPAPER_DIR}; {LOGIN_DEFAULT} -> {DEFAULT_NAME}")
        return
    install(context)

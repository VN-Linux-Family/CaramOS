"""Apps keep their sign-in on computers that log in by themselves.

Zalo, Lark, Chrome and other Electron and Chromium apps keep the key of their saved sign-in in the system keyring
(gnome-keyring). LightDM's automatic login has no password to open it: the first app that saved a secret asked to
"Choose password for new keyring", and a password typed there left that keyring locked after every automatic login,
so apps asked for it again, or lost their sign-in when the question was closed.

From this version the login step of the package (/etc/X11/Xsession.d/96caramos-login-actions, caramos_ota_update/
autologin_keyring.py) gives a user LightDM logs in automatically a keyring with an empty password, which gnome-keyring
keeps unencrypted and never locks, as the default keyring, at each automatic login before the desktop starts, when the
default one is missing or locked. A keyring with a password that apps open by themselves (the default one, the login
one) is moved first to ~/.local/share/keyrings/locked-by-password, so apps stop asking for its password at every login;
nothing is deleted, and README.txt there says how to get its secrets back. An app whose key was in it signs in once
more. Logins with a password are never touched. New installs get it at their first automatic login.

This migration changes nothing itself: it says which accounts LightDM logs in automatically, and its notes tell the
users. Nothing changes on an open desktop.
"""

from __future__ import annotations

import glob
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "A keyring that opens by itself after an automatic login, so that apps keep their sign-in"

ROOT = Path("/")
LIGHTDM_FILES = ("usr/share/lightdm/lightdm.conf.d/*.conf", "etc/lightdm/lightdm.conf.d/*.conf",
                 "etc/lightdm/lightdm.conf")


def autologin_user(root: Path = ROOT) -> str:
    """The account LightDM logs in automatically ("" for none); LightDM's later files win."""

    user = ""
    for pattern in LIGHTDM_FILES:
        for name in sorted(glob.glob(str(root / pattern))):
            section = ""
            try:
                lines = Path(name).read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for raw in lines:
                line = raw.strip()
                if line.startswith("[") and line.endswith("]"):
                    section = line
                elif section in ("[Seat:*]", "[SeatDefaults]") and line.startswith("autologin-user="):
                    user = line.split("=", 1)[1].strip()
    return user


def run(context: MigrationContext, root: Path = ROOT) -> None:
    user = autologin_user(root)
    if user:
        context.log(f"LightDM logs {user} in automatically: a keyring that opens by itself from the next automatic "
                    "login")
    else:
        context.log("LightDM logs nobody in automatically: nothing changes")

"""Migration for 1.0.9: restore stable Fcitx5 Lotus defaults."""

from __future__ import annotations

import os
import pwd
from pathlib import Path

from caramos_ota_update.context import MigrationContext

FROM_VERSION = "1.0.8"
TO_VERSION = "1.0.9"
DESCRIPTION = "Restore stable Fcitx5 Lotus defaults"

LIVE_USERS = (("caram", 1000), ("mint", 999))

SKEL_FCITX_DIR = Path("/etc/skel/.config/fcitx5")
SKEL_ENV_DIR = Path("/etc/skel/.config/environment.d")
SKEL_CONFIG = SKEL_FCITX_DIR / "config"
SKEL_PROFILE = SKEL_FCITX_DIR / "profile"
SKEL_LOTUS_CONFIG = SKEL_FCITX_DIR / "conf" / "lotus.conf"
SKEL_ENV_CONFIG = SKEL_ENV_DIR / "90-fcitx5-lotus.conf"
PROFILE_ENV_CONFIG = Path("/etc/profile.d/caramos-fcitx5.sh")
LOGIN_HELPER = Path("/usr/local/bin/caramos-fcitx5-lotus-enable")

# Files left by earlier 1.0.9 experiments. They must not remain installed.
EXPERIMENTAL_FILES = (
    Path("/usr/local/bin/caramos-fcitx5-switch"),
    Path("/usr/local/bin/caramos-fcitx5-state-sync"),
    Path("/etc/xdg/autostart/caramos-fcitx5-state-sync.desktop"),
    Path("/usr/local/bin/caramos-fcitx5-debug"),
)

ENVIRONMENT_CONFIG = """GTK_IM_MODULE=fcitx
QT_IM_MODULE=fcitx
XMODIFIERS=@im=fcitx
SDL_IM_MODULE=fcitx
GLFW_IM_MODULE=ibus
CLUTTER_IM_MODULE=fcitx
"""

PROFILE_CONFIG = """#!/bin/sh
export GTK_IM_MODULE=fcitx
export QT_IM_MODULE=fcitx
export XMODIFIERS=@im=fcitx
export INPUT_METHOD=fcitx
export SDL_IM_MODULE=fcitx
# Lotus upstream notes GLFW should keep ibus for compatibility.
export GLFW_IM_MODULE=ibus
# Cinnamon menu/search is Clutter-based; route it through Fcitx as well.
export CLUTTER_IM_MODULE=fcitx
"""

FCITX5_PROFILE_CONFIG = """[Groups/0]
Name=Default
Default Layout=us
DefaultIM=lotus

[Groups/0/Items/0]
Name=lotus
Layout=

[Groups/0/Items/1]
Name=keyboard-us
Layout=

[GroupOrder]
0=Default
"""

FCITX5_CONFIG = """[Hotkey]
EnumerateWithTriggerKeys=True
ActivateKeys=
DeactivateKeys=
AltTriggerKeys=
EnumerateForwardKeys=
EnumerateBackwardKeys=
EnumerateSkipFirst=False
ModifierOnlyKeyTimeout=500

[Hotkey/TriggerKeys]
0=Control+Shift_L
1=Control+Shift_R

[Hotkey/EnumerateGroupForwardKeys]

[Hotkey/EnumerateGroupBackwardKeys]

[Hotkey/PrevPage]

[Hotkey/NextPage]

[Hotkey/PrevCandidate]

[Hotkey/NextCandidate]

[Hotkey/TogglePreedit]

[Behavior]
ActiveByDefault=True
resetStateWhenFocusIn=No
ShareInputState=All
PreeditEnabledByDefault=True
ShowInputMethodInformation=True
showInputMethodInformationWhenFocusIn=False
CompactInputMethodInformation=True
ShowFirstInputMethodInformation=True
DefaultPageSize=5
OverrideXkbOption=False
CustomXkbOption=
EnabledAddons=
DisabledAddons=
PreloadInputMethod=True
AllowInputMethodForPassword=False
ShowPreeditForPassword=False
AutoSavePeriod=30
"""

LOTUS_CONFIG = """# CaramOS defaults for Lotus.
# Values match the Lotus settings UI labels.
InputMethod="Telex"
Mode="Preedit"
OutputCharset="Unicode"
ModeMenuKey="grave"
ShowModePreedit=True
"""

LOGIN_HELPER_SCRIPT = r'''#!/bin/sh
set -eu

USER_NAME="${USER:-$(id -un)}"

if command -v systemctl >/dev/null 2>&1; then
    systemctl enable --now "fcitx5-lotus-server@${USER_NAME}.service" >/dev/null 2>&1 || {
        systemd-sysusers >/dev/null 2>&1 || true
        systemctl enable --now "fcitx5-lotus-server@${USER_NAME}.service" >/dev/null 2>&1 || true
    }
fi

# Avoid competing input method daemons.
killall ibus-daemon >/dev/null 2>&1 || ibus exit >/dev/null 2>&1 || true

mkdir -p "${HOME}/.config/fcitx5/conf" "${HOME}/.config/environment.d"

# Always restore the stable CaramOS defaults on login.
cp -f /etc/skel/.config/fcitx5/config "${HOME}/.config/fcitx5/config"
cp -f /etc/skel/.config/fcitx5/profile "${HOME}/.config/fcitx5/profile"
cp -f /etc/skel/.config/fcitx5/conf/lotus.conf "${HOME}/.config/fcitx5/conf/lotus.conf"
cp -f /etc/skel/.config/environment.d/90-fcitx5-lotus.conf "${HOME}/.config/environment.d/90-fcitx5-lotus.conf"

# Remove earlier shortcut/state experiments from this user's Cinnamon settings.
if command -v gsettings >/dev/null 2>&1; then
    gsettings reset-recursively org.cinnamon.desktop.keybindings.custom-keybinding:/org/cinnamon/desktop/keybindings/custom-keybindings/custom0/ >/dev/null 2>&1 || true
fi

# Restart Fcitx after writing config so the running daemon uses these defaults.
if command -v fcitx5 >/dev/null 2>&1; then
    fcitx5 -d --replace >/dev/null 2>&1 || true
fi
'''


def _write_file(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def _chown_tree(path: Path, uid: int, gid: int) -> None:
    if not path.exists():
        return
    os.chown(path, uid, gid)
    if path.is_dir():
        for child in path.rglob("*"):
            os.chown(child, uid, gid)


def _apply_to_user(context: MigrationContext, uid: int) -> None:
    try:
        user_info = pwd.getpwuid(uid)
    except KeyError:
        return

    home = Path(user_info.pw_dir)
    fcitx_dir = home / ".config" / "fcitx5"
    env_dir = home / ".config" / "environment.d"

    _write_file(fcitx_dir / "config", FCITX5_CONFIG)
    _write_file(fcitx_dir / "profile", FCITX5_PROFILE_CONFIG)
    _write_file(fcitx_dir / "conf" / "lotus.conf", LOTUS_CONFIG)
    _write_file(env_dir / "90-fcitx5-lotus.conf", ENVIRONMENT_CONFIG)

    _chown_tree(fcitx_dir, user_info.pw_uid, user_info.pw_gid)
    _chown_tree(env_dir, user_info.pw_uid, user_info.pw_gid)
    context.log(f"updated Fcitx5 Lotus defaults for user: {user_info.pw_name}")


def run(context: MigrationContext) -> None:
    """Apply stable Ctrl+Shift Lotus configuration."""

    if context.dry_run:
        context.log("[dry-run] restore stable Fcitx5 Lotus defaults")
        return

    _write_file(SKEL_CONFIG, FCITX5_CONFIG)
    _write_file(SKEL_PROFILE, FCITX5_PROFILE_CONFIG)
    _write_file(SKEL_LOTUS_CONFIG, LOTUS_CONFIG)
    _write_file(SKEL_ENV_CONFIG, ENVIRONMENT_CONFIG)
    _write_file(PROFILE_ENV_CONFIG, PROFILE_CONFIG)
    _write_file(LOGIN_HELPER, LOGIN_HELPER_SCRIPT, mode=0o755)
    context.log("installed stable Fcitx5 Lotus defaults")

    for path in EXPERIMENTAL_FILES:
        path.unlink(missing_ok=True)
    context.log("removed Fcitx5 experimental helpers")

    for _, uid in LIVE_USERS:
        _apply_to_user(context, uid)

    context.log("logout/login is required for all Fcitx environment changes")

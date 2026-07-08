"""Migration for 1.0.12: move Lotus system service enablement out of login."""

from __future__ import annotations

import subprocess
from pathlib import Path

from caramos_ota_update.context import MigrationContext

FROM_VERSION = "1.0.11"
TO_VERSION = "1.0.12"
DESCRIPTION = "Stop Fcitx5 Lotus login-time systemd authentication prompts"

LOGIN_HELPER = Path("/usr/local/bin/caramos-fcitx5-lotus-enable")
SYSTEM_ENABLE_HELPER = Path("/usr/local/sbin/caramos-fcitx5-lotus-system-enable")
SYSTEM_ENABLE_SERVICE = Path("/etc/systemd/system/caramos-fcitx5-lotus-system-enable.service")
SYSTEM_ENABLE_WANTS = Path("/etc/systemd/system/multi-user.target.wants/caramos-fcitx5-lotus-system-enable.service")

LOGIN_HELPER_SCRIPT = r'''#!/bin/sh
set -eu

# Avoid competing input method daemons.
killall ibus-daemon >/dev/null 2>&1 || ibus exit >/dev/null 2>&1 || true

mkdir -p "${HOME}/.config/fcitx5/conf" "${HOME}/.config/environment.d"

if [ -f /etc/skel/.config/fcitx5/config ]; then
    cp -f /etc/skel/.config/fcitx5/config "${HOME}/.config/fcitx5/config"
fi
if [ -f /etc/skel/.config/fcitx5/profile ]; then
    cp -f /etc/skel/.config/fcitx5/profile "${HOME}/.config/fcitx5/profile"
fi
if [ -f /etc/skel/.config/fcitx5/conf/lotus.conf ]; then
    cp -f /etc/skel/.config/fcitx5/conf/lotus.conf "${HOME}/.config/fcitx5/conf/lotus.conf"
fi
if [ -f /etc/skel/.config/environment.d/90-fcitx5-lotus.conf ]; then
    cp -f /etc/skel/.config/environment.d/90-fcitx5-lotus.conf "${HOME}/.config/environment.d/90-fcitx5-lotus.conf"
fi

# Remove earlier shortcut/state experiments from this user's Cinnamon settings.
if command -v gsettings >/dev/null 2>&1; then
    gsettings reset-recursively org.cinnamon.desktop.keybindings.custom-keybinding:/org/cinnamon/desktop/keybindings/custom-keybindings/custom0/ >/dev/null 2>&1 || true
fi

# Restart Fcitx after writing config so the running daemon uses these defaults.
if command -v fcitx5 >/dev/null 2>&1; then
    fcitx5 -d --replace >/dev/null 2>&1 || true
fi
'''

SYSTEM_ENABLE_HELPER_SCRIPT = r'''#!/bin/sh
set -eu

TEMPLATE_UNIT="/lib/systemd/system/fcitx5-lotus-server@.service"

[ -f "$TEMPLATE_UNIT" ] || [ -f "/etc/systemd/system/fcitx5-lotus-server@.service" ] || exit 0
command -v systemctl >/dev/null 2>&1 || exit 0

while IFS=: read -r user _ uid _ _ home shell; do
    [ "$uid" -ge 1000 ] 2>/dev/null || continue
    [ "$uid" -lt 60000 ] 2>/dev/null || continue
    [ -d "$home" ] || continue
    case "$home" in
        /home/*) ;;
        *) continue ;;
    esac
    case "$shell" in
        */nologin|*/false) continue ;;
    esac

    if ! systemctl enable --now "fcitx5-lotus-server@${user}.service" >/dev/null 2>&1; then
        echo "caramos-fcitx5-lotus-system-enable: failed to enable service for ${user}" >&2
    fi
done < /etc/passwd
'''

SYSTEM_ENABLE_SERVICE_CONFIG = """[Unit]
Description=Enable Fcitx5 Lotus server for CaramOS desktop users
After=systemd-user-sessions.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/caramos-fcitx5-lotus-system-enable

[Install]
WantedBy=multi-user.target
"""


def _write_file(path: Path, content: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(mode)


def _enable_system_helper(context: MigrationContext) -> None:
    SYSTEM_ENABLE_WANTS.parent.mkdir(parents=True, exist_ok=True)
    if SYSTEM_ENABLE_WANTS.exists() or SYSTEM_ENABLE_WANTS.is_symlink():
        SYSTEM_ENABLE_WANTS.unlink()
    SYSTEM_ENABLE_WANTS.symlink_to(Path("../caramos-fcitx5-lotus-system-enable.service"))
    context.log(f"enabled system service: {SYSTEM_ENABLE_SERVICE.name}")

    if Path("/usr/bin/systemctl").exists() or Path("/bin/systemctl").exists():
        subprocess.run(["systemctl", "daemon-reload"], check=False)
    subprocess.run([str(SYSTEM_ENABLE_HELPER)], check=False)


def run(context: MigrationContext) -> None:
    """Apply Fcitx5 Lotus auth prompt fix."""

    if context.dry_run:
        context.log("[dry-run] replace Fcitx5 Lotus login helper with user-only setup")
        context.log("[dry-run] install root oneshot service for Lotus system unit enablement")
        return

    _write_file(LOGIN_HELPER, LOGIN_HELPER_SCRIPT, mode=0o755)
    context.log(f"updated login helper without system-level systemctl: {LOGIN_HELPER}")

    _write_file(SYSTEM_ENABLE_HELPER, SYSTEM_ENABLE_HELPER_SCRIPT, mode=0o755)
    _write_file(SYSTEM_ENABLE_SERVICE, SYSTEM_ENABLE_SERVICE_CONFIG)
    _enable_system_helper(context)

    context.log("Fcitx5 Lotus system service enablement moved out of desktop login")

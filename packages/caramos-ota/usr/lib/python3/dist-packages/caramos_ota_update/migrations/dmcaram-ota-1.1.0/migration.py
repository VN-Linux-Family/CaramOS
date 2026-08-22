"""Migration for 1.0.17: apply CaramOS branding, themes, and desktop defaults from ISO customization hook."""

from __future__ import annotations

import os
import pwd
import subprocess
from pathlib import Path

from caramos_ota_update.context import MigrationContext

FROM_VERSION = "1.0.16.1"
TO_VERSION = "dmcaram-1.1.0"
DESCRIPTION = "Apply CaramOS branding, Cinnamon Delight theme, Vietnamese locale, and desktop defaults"

OS_RELEASE_PATH = Path("/usr/lib/os-release")
LSB_RELEASE_PATH = Path("/etc/lsb-release")
LINUXMINT_INFO_PATH = Path("/etc/linuxmint/info")
DCONF_LOCAL_DIR = Path("/etc/dconf/db/local.d")
DCONF_PROFILE_USER = Path("/etc/dconf/profile/user")
DCONF_THEME_FILE = DCONF_LOCAL_DIR / "00-caramos-theme"
UBIQUITY_DESKTOP = Path("/usr/share/applications/ubiquity.desktop")
LIGHTDM_GTK_CONF = Path("/etc/lightdm/lightdm-gtk-greeter.conf.d/99_linuxmint.conf")
MINT_ARTWORK_OVERRIDE = Path("/usr/share/glib-2.0/schemas/mint-artwork.gschema.override")
LOCALE_FILE = Path("/etc/default/locale")
HOSTNAME_FILE = Path("/etc/hostname")
HOSTS_FILE = Path("/etc/hosts")
TIMEZONE_FILE = Path("/etc/timezone")
ISSUE_FILE = Path("/etc/issue")
ISSUE_NET_FILE = Path("/etc/issue.net")

CARAMOS_VERSION = "1.0.17"
CARAMOS_EDITION = "Cinnamon"
CARAMOS_PRETTY_NAME = f"CaramOS {CARAMOS_VERSION} {CARAMOS_EDITION}"

THEME_NAME = "Cinnamon-Delight"
ICON_THEME_NAME = "Tela-circle-light"
CURSOR_THEME_NAME = "Bibata-Modern-Classic"
FONT_NAME = "Be Vietnam Pro 10"
BACKGROUND_PATH = "/usr/share/backgrounds/caramos/default.png"

OS_RELEASE_CONTENT = f"""PRETTY_NAME="{CARAMOS_PRETTY_NAME}"
NAME="CaramOS"
VERSION_ID="{CARAMOS_VERSION}"
VERSION="{CARAMOS_VERSION}"
VERSION_CODENAME=caram
ID=caramos
ID_LIKE="ubuntu debian linuxmint"
HOME_URL="https://caramos.org/"
SUPPORT_URL="https://caramos.org/"
BUG_REPORT_URL="https://caramos.org/"
PRIVACY_POLICY_URL="https://caramos.org/"
UBUNTU_CODENAME=noble
"""

LSB_RELEASE_CONTENT = f"""DISTRIB_ID=CaramOS
DISTRIB_RELEASE={CARAMOS_VERSION}
DISTRIB_CODENAME=caram
DISTRIB_DESCRIPTION="{CARAMOS_PRETTY_NAME}"
"""

LINUXMINT_INFO_CONTENT = f"""RELEASE={CARAMOS_VERSION}
CODENAME=caram
EDITION="{CARAMOS_EDITION}"
DESCRIPTION="{CARAMOS_PRETTY_NAME}"
DESKTOP=Gnome
TOOLKIT=GTK
NEW_FEATURES_URL=https://caramos.org/
RELEASE_NOTES_URL=https://caramos.org/
USER_GUIDE_URL=https://caramos.org/
GRUB_TITLE={CARAMOS_PRETTY_NAME}
"""

DCONF_PROFILE_USER_CONTENT = """user-db:user
system-db:local
"""

DCONF_THEME_CONTENT = f"""[org/cinnamon]
app-menu-icon-name='caramos-logo-symbolic'
system-icon='caramos-logo-symbolic'

[org/cinnamon/theme]
name='{THEME_NAME}'

[org/cinnamon/desktop/interface]
gtk-theme='{THEME_NAME}'
icon-theme='{ICON_THEME_NAME}'
cursor-theme='{CURSOR_THEME_NAME}'
font-name='{FONT_NAME}'
clock-show-date=true
clock-use-24h=true

[org/cinnamon/desktop/wm/preferences]
theme='{THEME_NAME}'

[org/gnome/desktop/interface]
gtk-theme='{THEME_NAME}'
icon-theme='{ICON_THEME_NAME}'
cursor-theme='{CURSOR_THEME_NAME}'
font-name='{FONT_NAME}'

[org/gnome/desktop/wm/preferences]
theme='{THEME_NAME}'
"""

UBIQUITY_DESKTOP_CONTENT = """[Desktop Entry]
Type=Application
Version=1.0
Name=Install CaramOS
Name[vi]=Cài đặt CaramOS
Comment=Install CaramOS permanently to your disk
Comment[vi]=Cài đặt CaramOS vào ổ đĩa
Keywords=ubiquity;installer;caramos;
Exec=sudo --preserve-env=DBUS_SESSION_BUS_ADDRESS,XDG_DATA_DIRS,XDG_RUNTIME_DIR,GTK_THEME sh -c 'WEBKIT_DISABLE_COMPOSITING_MODE=1 ubiquity gtk_ui'
Icon=caramos-logo
Terminal=false
Categories=GTK;System;Settings;
X-Ayatana-Appmenu-Show-Stubs=False
"""

OLD_THEME_MAPPINGS = {
    "Mint-Y-Dark-Aqua": THEME_NAME,
    "Mint-Y-Dark": THEME_NAME,
    "Mint-Y-Aqua": THEME_NAME,
    "Mint-Y-Sand": THEME_NAME,
}

OLD_BACKGROUND_MAPPINGS = {
    "/usr/share/backgrounds/linuxmint/default_background.jpg": BACKGROUND_PATH,
}

OLD_ICON_MAPPINGS = {
    "linuxmint-logo-ring-symbolic": "caramos-logo-symbolic",
}


def _write_file(path: Path, content: str, context: MigrationContext) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    old_content = path.read_text(encoding="utf-8") if path.exists() else ""

    if old_content == content:
        return False

    path.write_text(content, encoding="utf-8")
    context.log(f"updated {path}")
    return True


def _replace_in_file(
    path: Path,
    replacements: dict[str, str],
    context: MigrationContext,
) -> bool:
    if not path.exists():
        return False

    text = path.read_text(encoding="utf-8")
    updated = text
    for old, new in replacements.items():
        updated = updated.replace(old, new)

    if updated == text:
        return False

    path.write_text(updated, encoding="utf-8")
    context.log(f"updated {path}")
    return True


def _update_os_identity(context: MigrationContext) -> None:
    changed = False

    if _write_file(OS_RELEASE_PATH, OS_RELEASE_CONTENT, context):
        changed = True
    if _write_file(LSB_RELEASE_PATH, LSB_RELEASE_CONTENT, context):
        changed = True
    if _write_file(LINUXMINT_INFO_PATH, LINUXMINT_INFO_CONTENT, context):
        changed = True

    if _write_file(ISSUE_FILE, f"CaramOS {CARAMOS_VERSION} \\n \\l\n", context):
        changed = True
    if _write_file(ISSUE_NET_FILE, f"CaramOS {CARAMOS_VERSION}\n", context):
        changed = True

    if changed:
        context.log("updated OS identity files to CaramOS branding")


def _update_locale_and_timezone(context: MigrationContext) -> None:
    changed = False

    locale_content = """LANG=vi_VN.UTF-8
LANGUAGE=vi_VN:vi
LC_ALL=vi_VN.UTF-8
"""

    if _write_file(LOCALE_FILE, locale_content, context):
        changed = True

    if _write_file(TIMEZONE_FILE, "Asia/Ho_Chi_Minh\n", context):
        changed = True

    if _write_file(HOSTNAME_FILE, "caram\n", context):
        changed = True

    if HOSTS_FILE.exists():
        hosts_text = HOSTS_FILE.read_text(encoding="utf-8")
        updated_hosts = hosts_text.replace("mint", "caram")
        if updated_hosts != hosts_text:
            HOSTS_FILE.write_text(updated_hosts, encoding="utf-8")
            context.log(f"updated {HOSTS_FILE}")
            changed = True

    if changed:
        context.log("updated locale, timezone, and hostname to Vietnamese defaults")


def _update_theme_configs(context: MigrationContext) -> None:
    changed = False

    if _write_file(DCONF_PROFILE_USER, DCONF_PROFILE_USER_CONTENT, context):
        changed = True

    if _write_file(DCONF_THEME_FILE, DCONF_THEME_CONTENT, context):
        changed = True

    if _write_file(UBIQUITY_DESKTOP, UBIQUITY_DESKTOP_CONTENT, context):
        changed = True

    if _replace_in_file(MINT_ARTWORK_OVERRIDE, OLD_THEME_MAPPINGS | OLD_BACKGROUND_MAPPINGS | OLD_ICON_MAPPINGS, context):
        changed = True

    if _replace_in_file(LIGHTDM_GTK_CONF, OLD_THEME_MAPPINGS | OLD_BACKGROUND_MAPPINGS, context):
        changed = True

    if changed:
        subprocess.run(["dconf", "update"], check=False)
        subprocess.run(
            ["glib-compile-schemas", "/usr/share/glib-2.0/schemas/"],
            check=False,
        )
        context.log("updated theme, icon, cursor, and desktop branding defaults")


def _session_environment(uid: int) -> dict[str, str] | None:
    runtime_dir = Path(f"/run/user/{uid}")
    if not runtime_dir.exists():
        return None

    env = os.environ.copy()
    env.update(
        {
            "DISPLAY": os.environ.get("DISPLAY", ":0"),
            "XDG_RUNTIME_DIR": str(runtime_dir),
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime_dir}/bus",
        }
    )
    return env


def _live_desktop_users() -> list[tuple[str, int]]:
    users: list[tuple[str, int]] = []
    runtime_root = Path("/run/user")
    if not runtime_root.exists():
        return users

    for runtime_dir in runtime_root.iterdir():
        if not runtime_dir.is_dir() or not runtime_dir.name.isdigit():
            continue
        uid = int(runtime_dir.name)
        try:
            user_info = pwd.getpwuid(uid)
        except KeyError:
            continue
        if uid < 1000 or user_info.pw_dir in ("", "/nonexistent"):
            continue
        users.append((user_info.pw_name, uid))

    return users


def _run_gsettings(user: str, env: dict[str, str], args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["runuser", "-u", user, "--", "gsettings", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _apply_live_user_theme(context: MigrationContext, username: str, uid: int) -> None:
    env = _session_environment(uid)
    if env is None:
        return

    settings = [
        ("org.cinnamon.theme", "name", THEME_NAME),
        ("org.cinnamon.desktop.interface", "gtk-theme", THEME_NAME),
        ("org.cinnamon.desktop.interface", "icon-theme", ICON_THEME_NAME),
        ("org.cinnamon.desktop.interface", "cursor-theme", CURSOR_THEME_NAME),
        ("org.cinnamon.desktop.interface", "font-name", FONT_NAME),
        ("org.cinnamon.desktop.wm.preferences", "theme", THEME_NAME),
        ("org.gnome.desktop.interface", "gtk-theme", THEME_NAME),
        ("org.gnome.desktop.interface", "icon-theme", ICON_THEME_NAME),
        ("org.gnome.desktop.interface", "cursor-theme", CURSOR_THEME_NAME),
        ("org.gnome.desktop.interface", "font-name", FONT_NAME),
        ("org.gnome.desktop.wm.preferences", "theme", THEME_NAME),
        ("org.cinnamon.desktop.interface", "clock-show-date", "true"),
        ("org.cinnamon.desktop.interface", "clock-use-24h", "true"),
    ]

    updated_count = 0
    for schema, key, value in settings:
        current = _run_gsettings(username, env, ["get", schema, key])
        if current.returncode != 0:
            continue

        current_value = current.stdout.strip().strip("'")
        if current_value == value:
            continue

        result = _run_gsettings(username, env, ["set", schema, key, value])
        if result.returncode == 0:
            updated_count += 1

    if updated_count > 0:
        context.log(f"updated {updated_count} theme settings for user: {username}")
    else:
        context.log(f"theme settings already current for user: {username}")


def run(context: MigrationContext) -> None:
    """Apply CaramOS branding, themes, and desktop defaults from ISO customization."""

    if context.dry_run:
        context.log(f"[dry-run] apply CaramOS branding and desktop defaults to version {CARAMOS_VERSION}")
        context.log("[dry-run] update OS identity, locale, timezone, theme, and desktop configs")
        context.log("[dry-run] apply live-user theme settings when session is available")
        return

    _update_os_identity(context)
    _update_locale_and_timezone(context)
    _update_theme_configs(context)

    for username, uid in _live_desktop_users():
        _apply_live_user_theme(context, username, uid)

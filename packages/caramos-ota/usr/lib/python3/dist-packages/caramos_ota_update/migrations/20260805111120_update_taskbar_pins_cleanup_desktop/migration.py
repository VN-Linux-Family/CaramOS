"""Timestamp migration for CaramOS 1.0.16: update taskbar pins and clean Desktop."""

from __future__ import annotations

import ast
import json
import os
import pwd
import shutil
import subprocess
import tempfile
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Pin Zalo and Software Manager and remove stock Desktop shortcuts"

GROUPED_WINDOW_LIST_UUID = "grouped-window-list@cinnamon.org"
APPLICATION_DIRS = (Path("/usr/share/applications"), Path("/usr/local/share/applications"))
DCONF_FILES = (
    Path("/etc/dconf/db/local.d/00-caramos-theme"),
    Path("/etc/dconf/db/local.d/01-caramos-task17-panel"),
)
RUNTIME_ROOT = Path("/run/user")
SKEL_DESKTOP = Path("/etc/skel/Desktop")
TARGET_PINNED_APPS = (
    "google-chrome.desktop",
    "wps-office-prometheus.desktop",
    "zalo.desktop",
    "mintinstall.desktop",
    "cinnamon-settings.desktop",
)
REQUIRED_NEW_PINS = ("zalo.desktop", "mintinstall.desktop")
KNOWN_STOCK_PIN_LISTS = {
    (
        "google-chrome.desktop",
        "wps-office-prometheus.desktop",
        "cinnamon-settings.desktop",
    ),
    (
        "cinnamon-settings.desktop",
        "wps-office-prometheus.desktop",
        "google-chrome.desktop",
        "mintinstall.desktop",
    ),
    (
        "google-chrome.desktop",
        "wps-office-prometheus.desktop",
        "cinnamon-settings.desktop",
        "mintinstall.desktop",
    ),
    TARGET_PINNED_APPS,
}
DESKTOP_SHORTCUT_FINGERPRINTS = {
    "wps-office-prometheus.desktop": (
        "Name=WPS Office",
        "Exec=/usr/bin/wps %F",
        "StartupWMClass=wpsoffice",
    ),
    "zalo.desktop": (
        "Name=Zalo",
        "Exec=/usr/local/bin/Zalo.AppImage",
        "Icon=/usr/share/pixmaps/zalo.png",
    ),
    "mintinstall.desktop": (
        "Exec=mintinstall",
        "Icon=mintinstall",
        "Type=Application",
    ),
}


def _desktop_file_exists(desktop_id: str) -> bool:
    return any((directory / desktop_id).is_file() for directory in APPLICATION_DIRS)


def _effective_stock_pins(context: MigrationContext) -> list[str]:
    apps = [desktop_id for desktop_id in TARGET_PINNED_APPS if _desktop_file_exists(desktop_id)]
    missing = [desktop_id for desktop_id in TARGET_PINNED_APPS if desktop_id not in apps]
    if missing:
        context.log("skipped missing pinned app desktop files: " + ", ".join(missing))
    return apps


def _merge_pins(current: list[str], target: list[str]) -> list[str]:
    if tuple(current) in KNOWN_STOCK_PIN_LISTS:
        return list(target)
    updated = list(current)
    for desktop_id in REQUIRED_NEW_PINS:
        if desktop_id in target and desktop_id not in updated:
            updated.append(desktop_id)
    return updated


def _parse_pin_value(value: object) -> list[str] | None:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    if not isinstance(value, str):
        return None
    try:
        parsed = ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        return None
    return list(parsed)


def _pinned_apps_dconf(apps: list[str]) -> str:
    return "['" + "','".join(apps) + "']"


def _updated_dconf_text(text: str, apps: list[str]) -> str:
    replacement = f"pinned-apps={_pinned_apps_dconf(apps)}"
    lines = text.splitlines()
    output: list[str] = []
    in_group = False
    group_found = False
    key_written = False

    for line in lines:
        if line.startswith("[") and line.endswith("]"):
            if in_group and not key_written:
                output.append(replacement)
            in_group = line == "[org/cinnamon/applets/grouped-window-list]"
            if in_group:
                group_found = True
                key_written = False
            output.append(line)
            continue
        if in_group and line.startswith("pinned-apps="):
            if not key_written:
                output.append(replacement)
                key_written = True
            continue
        output.append(line)

    if in_group and not key_written:
        output.append(replacement)
    if not group_found:
        if output and output[-1] != "":
            output.append("")
        output.extend(["[org/cinnamon/applets/grouped-window-list]", replacement])
    return "\n".join(output) + "\n"


def _atomic_write_text(path: Path, content: str, mode: int) -> None:
    descriptor, staging_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(descriptor)
    staging = Path(staging_name)
    try:
        staging.write_text(content, encoding="utf-8")
        staging.chmod(mode)
        os.replace(staging, path)
    finally:
        staging.unlink(missing_ok=True)


def _update_dconf_defaults(context: MigrationContext, apps: list[str]) -> bool:
    changed_files: list[str] = []
    for path in DCONF_FILES:
        if path.is_symlink() or not path.is_file():
            context.log(f"warning: skipped non-regular dconf defaults file: {path}")
            continue
        current = path.read_text(encoding="utf-8")
        updated = _updated_dconf_text(current, apps)
        if updated == current:
            continue
        changed_files.append(str(path))
        if not context.dry_run:
            _atomic_write_text(path, updated, path.stat().st_mode & 0o777)
    if not changed_files:
        context.log("pinned app defaults already up to date")
        return False
    context.log("update pinned app defaults: " + ", ".join(changed_files))
    if not context.dry_run:
        context.run_command(["dconf", "update"], allow_fail=True)
    return True


def _all_desktop_users() -> list[tuple[str, int, Path]]:
    users: list[tuple[str, int, Path]] = []
    for info in pwd.getpwall():
        if info.pw_uid < 1000 or info.pw_dir in ("", "/nonexistent"):
            continue
        home = Path(info.pw_dir)
        if not home.is_dir():
            continue
        users.append((info.pw_name, info.pw_uid, home))
    return sorted(users, key=lambda item: item[1])


def _live_desktop_users() -> list[tuple[str, int, Path]]:
    users: list[tuple[str, int, Path]] = []
    if not RUNTIME_ROOT.is_dir():
        return users
    for runtime_dir in sorted(RUNTIME_ROOT.iterdir(), key=lambda path: path.name):
        if not runtime_dir.is_dir() or not runtime_dir.name.isdigit():
            continue
        uid = int(runtime_dir.name)
        if uid < 1000:
            continue
        try:
            info = pwd.getpwuid(uid)
        except KeyError:
            continue
        if info.pw_dir in ("", "/nonexistent"):
            continue
        users.append((info.pw_name, uid, Path(info.pw_dir)))
    return users


def _session_environment(uid: int, home: Path) -> dict[str, str] | None:
    runtime_dir = RUNTIME_ROOT / str(uid)
    if not runtime_dir.is_dir() or not (runtime_dir / "bus").exists():
        return None
    env = os.environ.copy()
    env.update(
        {
            "DISPLAY": os.environ.get("DISPLAY", ":0"),
            "XAUTHORITY": str(home / ".Xauthority"),
            "XDG_RUNTIME_DIR": str(runtime_dir),
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime_dir}/bus",
        }
    )
    return env


def _run_as_user(user: str, env: dict[str, str], args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["runuser", "-u", user, "--", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _grouped_window_list_instances(user: str, env: dict[str, str]) -> list[str]:
    result = _run_as_user(user, env, ["gsettings", "get", "org.cinnamon", "enabled-applets"])
    if result.returncode != 0:
        return ["1"]
    try:
        entries = ast.literal_eval(result.stdout.strip())
    except (SyntaxError, ValueError):
        return ["1"]
    if not isinstance(entries, list):
        return ["1"]
    instances: list[str] = []
    for entry in entries:
        if not isinstance(entry, str):
            continue
        parts = entry.split(":", 4)
        if len(parts) == 5 and parts[3] == GROUPED_WINDOW_LIST_UUID:
            instances.append(parts[4])
    return instances or ["1"]


def _update_spice_config(
    context: MigrationContext,
    user: str,
    uid: int,
    home: Path,
    instance: str,
    target: list[str],
) -> bool:
    config_dir = home / ".config" / "cinnamon" / "spices" / GROUPED_WINDOW_LIST_UUID
    path = config_dir / f"{instance}.json"
    data: dict[str, object] = {}
    if path.is_symlink() or (path.exists() and not path.is_file()):
        context.log(f"warning: skipped non-regular grouped-window-list config: {path}")
        return False
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            context.log(f"warning: malformed grouped-window-list config kept unchanged: {path}")
            return False
        if not isinstance(loaded, dict):
            context.log(f"warning: unexpected grouped-window-list config kept unchanged: {path}")
            return False
        data = loaded
    current = _parse_pin_value(data.get("pinned-apps", []))
    if current is None:
        context.log(f"warning: malformed pinned apps kept unchanged for live user: {user}")
        return False
    updated = _merge_pins(current, target)
    if updated == current:
        return False
    context.log(f"update grouped-window-list pinned apps for live user: {user}, instance {instance}")
    if context.dry_run:
        return True
    config_dir.mkdir(parents=True, exist_ok=True)
    data["pinned-apps"] = {"value": updated}
    _atomic_write_text(path, json.dumps(data, indent=4, ensure_ascii=False) + "\n", 0o644)
    shutil.chown(config_dir, user=user, group=user)
    shutil.chown(path, user=user, group=user)
    return True


def _reload_cinnamon_applets(context: MigrationContext, user: str, env: dict[str, str]) -> None:
    current = _run_as_user(user, env, ["gsettings", "get", "org.cinnamon", "enabled-applets"])
    if current.returncode != 0 or not current.stdout.strip():
        context.log(f"warning: could not reload Cinnamon applets for {user}")
        return
    result = _run_as_user(
        user,
        env,
        ["gsettings", "set", "org.cinnamon", "enabled-applets", current.stdout.strip()],
    )
    if result.returncode != 0:
        context.log(f"warning: could not reload Cinnamon applets for {user}: {result.stderr.strip()}")


def _apply_live_user(
    context: MigrationContext,
    user: str,
    uid: int,
    home: Path,
    target: list[str],
) -> None:
    env = _session_environment(uid, home)
    if env is None:
        context.log(f"warning: desktop session bus unavailable for live user: {user}")
        return
    changed = False
    for instance in _grouped_window_list_instances(user, env):
        changed = _update_spice_config(context, user, uid, home, instance, target) or changed
    if changed and not context.dry_run:
        _reload_cinnamon_applets(context, user, env)


def _is_stock_desktop_shortcut(path: Path) -> bool:
    required = DESKTOP_SHORTCUT_FINGERPRINTS.get(path.name)
    if required is None:
        return False
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return all(marker in content for marker in required)


def _remove_stock_desktop_shortcut(context: MigrationContext, path: Path) -> bool:
    if path.is_symlink():
        context.log(f"kept symlink desktop launcher: {path}")
        return False
    if not path.exists():
        return False
    if not path.is_file():
        context.log(f"kept non-regular desktop launcher: {path}")
        return False
    if not _is_stock_desktop_shortcut(path):
        context.log(f"kept custom desktop launcher: {path}")
        return False
    context.log(f"remove stock desktop launcher: {path}")
    if not context.dry_run:
        path.unlink()
    return True


def _cleanup_desktops(context: MigrationContext) -> None:
    desktop_dirs = [SKEL_DESKTOP]
    desktop_dirs.extend(home / "Desktop" for _, _, home in _all_desktop_users())
    for desktop_dir in desktop_dirs:
        for filename in DESKTOP_SHORTCUT_FINGERPRINTS:
            _remove_stock_desktop_shortcut(context, desktop_dir / filename)


def run(context: MigrationContext) -> None:
    """Pin installed apps and remove only stock CaramOS Desktop shortcuts."""
    target = _effective_stock_pins(context)
    _update_dconf_defaults(context, target)
    _cleanup_desktops(context)
    for user, uid, home in _live_desktop_users():
        _apply_live_user(context, user, uid, home, target)

"""Migration for 1.0.8: pin Software Manager to the panel and desktop."""

from __future__ import annotations

import json
import os
import pwd
import shutil
import subprocess
from pathlib import Path

from caramos_ota_update.context import MigrationContext

FROM_VERSION = "1.0.7"
TO_VERSION = "1.0.8"
DESCRIPTION = "Pin Software Manager to Cinnamon panel and desktop"

DESIRED_PINNED_APPS = [
    "cinnamon-settings.desktop",
    "wps-office-prometheus.desktop",
    "google-chrome.desktop",
    "mintinstall.desktop",
]
APPLICATION_DIRS = (
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
)
DCONF_FILES = (
    Path("/etc/dconf/db/local.d/00-caramos-theme"),
    Path("/etc/dconf/db/local.d/01-caramos-task17-panel"),
)
MINTINSTALL_DESKTOP = Path("/usr/share/applications/mintinstall.desktop")
GROUPED_WINDOW_LIST_UUID = "grouped-window-list@cinnamon.org"


def _session_environment(user: str, uid: int) -> dict[str, str] | None:
    runtime_dir = Path(f"/run/user/{uid}")
    if not runtime_dir.exists():
        return None
    env = os.environ.copy()
    env.update(
        {
            "DISPLAY": os.environ.get("DISPLAY", ":0"),
            "XAUTHORITY": f"/home/{user}/.Xauthority",
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


def _reload_cinnamon_applets(context: MigrationContext, user: str, env: dict[str, str]) -> None:
    """Ask Cinnamon to reload applets without replacing the whole desktop session."""

    current = _run_as_user(user, env, ["gsettings", "get", "org.cinnamon", "enabled-applets"])
    if current.returncode != 0:
        context.log(f"warning: could not read enabled applets for {user}: {current.stderr.strip()}")
        return
    enabled_applets = current.stdout.strip()
    if not enabled_applets:
        context.log(f"warning: enabled applets is empty for {user}; skip applet reload")
        return

    result = _run_as_user(user, env, ["gsettings", "set", "org.cinnamon", "enabled-applets", enabled_applets])
    if result.returncode == 0:
        context.log(f"requested Cinnamon applet reload for live user: {user}")
    else:
        context.log(f"warning: could not reload Cinnamon applets for {user}: {result.stderr.strip()}")


def _restore_nemo_desktop(context: MigrationContext, user: str, env: dict[str, str]) -> None:
    """Keep live-session desktop icons visible after Cinnamon applet reloads."""

    if Path("/usr/bin/gsettings").exists():
        _run_as_user(user, env, ["gsettings", "set", "org.nemo.desktop", "show-desktop-icons", "true"])
    if not Path("/usr/bin/nemo-desktop").exists():
        context.log("warning: nemo-desktop command not found; skip desktop icon restore")
        return
    try:
        subprocess.Popen(
            ["runuser", "-u", user, "--", "nemo-desktop"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        context.log(f"ensured Nemo desktop icons are running for live user: {user}")
    except Exception as exc:
        context.log(f"warning: could not restore Nemo desktop icons for {user}: {exc}")

def _desktop_file_exists(desktop_id: str) -> bool:
    return any((directory / desktop_id).exists() for directory in APPLICATION_DIRS)


def _available_pinned_apps(context: MigrationContext) -> list[str]:
    apps = [desktop_id for desktop_id in DESIRED_PINNED_APPS if _desktop_file_exists(desktop_id)]
    missing = [desktop_id for desktop_id in DESIRED_PINNED_APPS if desktop_id not in apps]
    if missing:
        context.log("skipped missing pinned app desktop files: " + ", ".join(missing))
    return apps


def _pinned_apps_dconf(apps: list[str]) -> str:
    return "['" + "','".join(apps) + "']"


def _replace_or_add_pinned_apps(path: Path, apps: list[str]) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    pinned_apps_dconf = _pinned_apps_dconf(apps)
    lines = text.splitlines()
    changed = False
    in_group = False
    group_found = False
    key_written = False
    output: list[str] = []

    for line in lines:
        if line.startswith("[") and line.endswith("]"):
            if in_group and not key_written:
                output.append(f"pinned-apps={pinned_apps_dconf}")
                changed = True
            in_group = line == "[org/cinnamon/applets/grouped-window-list]"
            group_found = group_found or in_group
            key_written = False if in_group else key_written
            output.append(line)
            continue
        if in_group and line.startswith("pinned-apps="):
            replacement = f"pinned-apps={pinned_apps_dconf}"
            output.append(replacement)
            key_written = True
            changed = changed or line != replacement
            continue
        output.append(line)

    if in_group and not key_written:
        output.append(f"pinned-apps={pinned_apps_dconf}")
        changed = True
    if not group_found:
        if output and output[-1] != "":
            output.append("")
        output.extend(["[org/cinnamon/applets/grouped-window-list]", f"pinned-apps={pinned_apps_dconf}"])
        changed = True

    if changed:
        path.write_text("\n".join(output) + "\n", encoding="utf-8")
    return changed


def _update_dconf_defaults(context: MigrationContext, apps: list[str]) -> None:
    changed_files = []
    for path in DCONF_FILES:
        if _replace_or_add_pinned_apps(path, apps):
            changed_files.append(str(path))
    subprocess.run(["dconf", "update"], check=False)
    if changed_files:
        context.log("updated pinned app defaults: " + ", ".join(changed_files))
    else:
        context.log("pinned app defaults already up to date")


def _copy_desktop_launcher(target_dir: Path) -> bool:
    if not MINTINSTALL_DESKTOP.exists():
        return False
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "mintinstall.desktop"
    shutil.copy2(MINTINSTALL_DESKTOP, target)
    target.chmod(0o755)
    return True


def _find_grouped_window_list_instances(env: dict[str, str]) -> list[str]:
    result = subprocess.run(
        ["gsettings", "get", "org.cinnamon", "enabled-applets"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    instances: list[str] = []
    if result.returncode != 0:
        return ["1"]
    for item in result.stdout.replace("[", "").replace("]", "").split(","):
        value = item.strip().strip("'").strip('"')
        parts = value.split(":")
        if len(parts) >= 5 and parts[3] == GROUPED_WINDOW_LIST_UUID:
            instances.append(parts[4])
    return instances or ["1"]


def _write_spice_config(user: str, uid: int, env: dict[str, str], apps: list[str]) -> None:
    home = Path(pwd.getpwuid(uid).pw_dir)
    config_dir = home / ".config" / "cinnamon" / "spices" / GROUPED_WINDOW_LIST_UUID
    config_dir.mkdir(parents=True, exist_ok=True)

    for instance in _find_grouped_window_list_instances(env):
        path = config_dir / f"{instance}.json"
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                data = {}
        data["pinned-apps"] = {"value": apps}
        path.write_text(json.dumps(data, indent=4, ensure_ascii=False) + "\n", encoding="utf-8")
        shutil.chown(path, user=user, group=user)

    shutil.chown(config_dir, user=user, group=user)


def _pin_for_live_user(context: MigrationContext, user: str, uid: int, apps: list[str]) -> None:
    env = _session_environment(user, uid)
    if env is None:
        return

    _write_spice_config(user, uid, env, apps)
    context.log(f"updated grouped-window-list pinned apps for live user: {user}")

    desktop_dir = Path(f"/home/{user}/Desktop")
    if _copy_desktop_launcher(desktop_dir):
        shutil.chown(desktop_dir / "mintinstall.desktop", user=user, group=user)
        _run_as_user(user, env, ["gio", "set", str(desktop_dir / "mintinstall.desktop"), "metadata::trusted", "true"])
        context.log(f"pinned Software Manager to desktop for live user: {user}")

    _reload_cinnamon_applets(context, user, env)
    _restore_nemo_desktop(context, user, env)


def run(context: MigrationContext) -> None:
    """Apply PR #54 Software Manager pins."""

    if context.dry_run:
        context.log("[dry-run] update grouped-window-list pinned apps")
        context.log("[dry-run] copy mintinstall.desktop to /etc/skel/Desktop and live user desktop")
        context.log("[dry-run] reload Cinnamon applets without replacing the session")
        context.log("[dry-run] ensure Nemo desktop icons stay visible")
        return

    apps = _available_pinned_apps(context)
    _update_dconf_defaults(context, apps)
    if _copy_desktop_launcher(Path("/etc/skel/Desktop")):
        context.log("pinned Software Manager to default desktop skeleton")
    else:
        context.log("warning: /usr/share/applications/mintinstall.desktop not found")

    for user, uid in (("caram", 1000), ("mint", 999)):
        _pin_for_live_user(context, user, uid, apps)

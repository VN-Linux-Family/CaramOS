"""Migration for 1.0.10: apply Cinnamon panel icon sizing from PR #62."""

from __future__ import annotations

import os
import pwd
import subprocess
from pathlib import Path

from caramos_ota_update.context import MigrationContext

FROM_VERSION = "1.0.9"
TO_VERSION = "1.0.10"
DESCRIPTION = "Apply Cinnamon right panel icon size defaults"

PANEL_ICON_SIZES = '[{"panelId": 1, "right": 18}]'
DCONF_FILES = (
    Path("/etc/dconf/db/local.d/00-caramos-theme"),
    Path("/etc/dconf/db/local.d/01-caramos-task17-panel"),
)
THEME_APPLY = Path("/usr/bin/caramos-theme-apply")
LIVE_USERS = (("caram", 1000), ("mint", 999))

OLD_DCONF_VALUES = (
    'panel-zone-icon-sizes=\'[{"panelId": 1, "maxSize": 18}]\'',
    'panel-zone-icon-sizes=\'[{"panelId": 1, "left": 20, "center": 20, "right": 20}]\'',
)
NEW_DCONF_VALUE = f"panel-zone-icon-sizes='{PANEL_ICON_SIZES}'"
OLD_THEME_APPLY_LINE = (
    "gsettings set org.cinnamon panel-zone-icon-sizes "
    "'[{\"panelId\": 1, \"maxSize\": 24}]' 2>/dev/null || true"
)
NEW_THEME_APPLY_LINE = (
    "gsettings set org.cinnamon panel-zone-icon-sizes "
    "'[{\"panelId\": 1, \"right\": 18}]' 2>/dev/null || true"
)
CARAMOS_OLD_USER_VALUES = {
    '[{"panelId": 1, "maxSize": 18}]',
    '[{"panelId": 1, "maxSize": 24}]',
    '[{"panelId": 1, "left": 20, "center": 20, "right": 20}]',
}


def _replace_line(path: Path, old_values: tuple[str, ...], new_value: str) -> bool:
    if not path.exists():
        return False

    text = path.read_text(encoding="utf-8")
    updated = text
    for old_value in old_values:
        updated = updated.replace(old_value, new_value)

    if updated == text:
        return False

    path.write_text(updated, encoding="utf-8")
    return True


def _update_dconf_defaults(context: MigrationContext) -> None:
    changed = False
    for path in DCONF_FILES:
        if _replace_line(path, OLD_DCONF_VALUES, NEW_DCONF_VALUE):
            context.log(f"updated Cinnamon panel icon default: {path}")
            changed = True

    if changed:
        subprocess.run(["dconf", "update"], check=False)


def _update_theme_apply(context: MigrationContext) -> None:
    if _replace_line(THEME_APPLY, (OLD_THEME_APPLY_LINE,), NEW_THEME_APPLY_LINE):
        context.log(f"updated theme apply panel icon default: {THEME_APPLY}")


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


def _run_gsettings(user: str, env: dict[str, str], args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["runuser", "-u", user, "--", "gsettings", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _apply_to_live_user(context: MigrationContext, username: str, uid: int) -> None:
    try:
        pwd.getpwnam(username)
    except KeyError:
        return

    env = _session_environment(uid)
    if env is None:
        return

    current = _run_gsettings(username, env, ["get", "org.cinnamon", "panel-zone-icon-sizes"])
    if current.returncode != 0:
        context.log(f"warning: could not read Cinnamon icon sizes for {username}: {current.stderr.strip()}")
        return

    current_value = current.stdout.strip().strip("'")
    if current_value not in CARAMOS_OLD_USER_VALUES:
        context.log(f"kept custom Cinnamon icon sizes for user: {username}")
        return

    result = _run_gsettings(username, env, ["set", "org.cinnamon", "panel-zone-icon-sizes", PANEL_ICON_SIZES])
    if result.returncode == 0:
        context.log(f"updated Cinnamon right panel icon size for user: {username}")
    else:
        context.log(f"warning: could not update Cinnamon icon sizes for {username}: {result.stderr.strip()}")


def run(context: MigrationContext) -> None:
    """Apply PR #62 Cinnamon right panel icon size defaults."""

    if context.dry_run:
        context.log("[dry-run] update Cinnamon panel icon size defaults from PR #62")
        context.log("[dry-run] apply live-user setting only when it still matches old CaramOS defaults")
        return

    _update_dconf_defaults(context)
    _update_theme_apply(context)

    for username, uid in LIVE_USERS:
        _apply_to_live_user(context, username, uid)

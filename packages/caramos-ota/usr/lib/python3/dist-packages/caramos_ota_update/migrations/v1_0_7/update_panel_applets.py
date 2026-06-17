"""Migration for 1.0.7: apply Cinnamon panel applet layout from PR #53."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from caramos_ota_update.context import MigrationContext

FROM_VERSION = "1.0.6"
TO_VERSION = "1.0.7"
DESCRIPTION = "Apply Cinnamon panel layout with systray, network and sound applets"

DCONF_FILE = Path("/etc/dconf/db/local.d/01-caramos-task17-panel")
ENABLED_APPLETS = (
    "['panel1:left:0:Cinnamenu@json:0', "
    "'panel1:left:1:grouped-window-list@cinnamon.org:1', "
    "'panel1:right:0:systray@cinnamon.org:2', "
    "'panel1:right:1:network@cinnamon.org:3', "
    "'panel1:right:2:sound@cinnamon.org:4', "
    "'panel1:right:3:notifications@cinnamon.org:5', "
    "'panel1:right:4:power@cinnamon.org:6', "
    "'panel1:right:5:calendar@cinnamon.org:7']"
)
DCONF_CONTENT = f"""[org/cinnamon]
enabled-applets={ENABLED_APPLETS}
panels-height=['1:32']
panel-scale-text-icons=false
panel-zone-icon-sizes='[{{\"panelId\": 1, \"maxSize\": 18}}]'
panel-zone-symbolic-icon-sizes='[{{\"panelId\": 1, \"left\": 20, \"center\": 20, \"right\": 16}}]'
panel-zone-text-sizes='[{{\"panelId\": 1, \"left\":0.0, \"center\":0.0, \"right\":0.0}}]'
favorite-apps=@as []

[org/cinnamon/applets/grouped-window-list]
pinned-apps=['google-chrome.desktop','wps-office-prometheus.desktop','cinnamon-settings.desktop']
title-display=1
number-display=false
group-apps=true
"""


def _write_panel_defaults() -> None:
    """Write Cinnamon panel defaults for new users and system default profile."""

    DCONF_FILE.parent.mkdir(parents=True, exist_ok=True)
    DCONF_FILE.write_text(DCONF_CONTENT, encoding="utf-8")
    subprocess.run(["dconf", "update"], check=False)


def _session_environment(user: str, uid: int) -> dict[str, str] | None:
    """Return a minimal environment for talking to the user's desktop session."""

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
    """Run a desktop command as the live user."""

    return subprocess.run(
        ["runuser", "-u", user, "--", *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def _reload_cinnamon(context: MigrationContext, user: str, env: dict[str, str]) -> None:
    """Reload Cinnamon so panel applet changes appear immediately."""

    if not Path("/usr/bin/cinnamon").exists():
        context.log("warning: cinnamon command not found; skip Cinnamon reload")
        return
    command = ["nohup", "cinnamon", "--replace"]
    try:
        subprocess.Popen(
            ["runuser", "-u", user, "--", *command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        context.log(f"requested Cinnamon reload for live user: {user}")
    except Exception as exc:
        context.log(f"warning: could not reload Cinnamon for {user}: {exc}")


def _update_live_user(context: MigrationContext) -> None:
    """Apply the panel layout to the current live user when possible."""

    for user, uid in (("caram", 1000), ("mint", 999)):
        env = _session_environment(user, uid)
        if env is None:
            continue
        result = _run_as_user(
            user,
            env,
            ["gsettings", "set", "org.cinnamon", "enabled-applets", ENABLED_APPLETS],
        )
        if result.returncode == 0:
            context.log(f"updated Cinnamon panel layout for live user: {user}")
            _reload_cinnamon(context, user, env)
        else:
            context.log(f"warning: could not update Cinnamon panel for {user}: {result.stderr.strip()}")


def run(context: MigrationContext) -> None:
    """Apply PR #53 Cinnamon panel layout."""

    if context.dry_run:
        context.log(f"[dry-run] write Cinnamon panel defaults: {DCONF_FILE}")
        context.log("[dry-run] set enabled-applets for live user when a session is available")
        context.log("[dry-run] reload Cinnamon for the live user")
        return

    _write_panel_defaults()
    context.log(f"updated Cinnamon panel defaults: {DCONF_FILE}")
    _update_live_user(context)

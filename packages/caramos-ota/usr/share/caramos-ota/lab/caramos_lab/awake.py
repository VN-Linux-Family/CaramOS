"""A computer lab student's computer stays awake for Veyon: no screensaver, automatic lock, screen sleep or suspend.

Veyon shows and controls the session on screen, and the desktop's own idle lock gets in its way:
- Xfce's light-locker locks by switching to a LightDM greeter session. Veyon then serves the greeter, refuses Lock
  and Demo there ("not running in a user session"), and Veyon 4.7.5 can lose its server for the student's session
  on the way back: an orange computer in Veyon Master until a restart (seen in a VM lab, 2026-11-25).
- Cinnamon's screensaver covers Veyon's lock and demo windows, and its lock asks students for a password.
- A computer that sleeps is gone from Veyon Master until someone wakes it; on Xfce it comes back locked as well.
- The screens stay on during the lesson (Veyon itself turns screen sleep off only while it locks or shows a demo).
While the computer is a lab student each account turns these off; after it left the lab each account gets back what
it had before. Runs as the user: from the Phòng máy window when the computer joins or leaves the lab, and at every
login (caramos-lab --session, /etc/xdg/autostart/caramos-lab-session.desktop), so that every account gets it, also
one that was not logged in then.

What an account had is kept in ~/.local/state/caramos-lab/desktop-settings.json: the account's own value of each
setting, or null when it had none (the setting then goes back to the system's default).
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

CINNAMON = "cinnamon"
XFCE = "xfce"
STATE_NAME = "caramos-lab/desktop-settings.json"


@dataclass(frozen=True)
class GSetting:
    """A GSettings key and its value in the lab, as GVariant text (`gsettings set` takes it as is)."""

    schema: str
    key: str
    value: str

    @property
    def name(self) -> str:
        return f"gsettings {self.schema} {self.key}"

    @property
    def path(self) -> str:
        """The key's dconf path: these schemas live at the path of their id."""

        return "/" + self.schema.replace(".", "/") + "/" + self.key


@dataclass(frozen=True)
class XfconfProperty:
    """An xfconf property, its type (for a property the account does not have yet) and its value in the lab."""

    channel: str
    prop: str
    kind: str
    value: str

    @property
    def name(self) -> str:
        return f"xfconf {self.channel} {self.prop}"


CINNAMON_SETTINGS = (
    GSetting("org.cinnamon.desktop.session", "idle-delay", "uint32 0"),  # no screensaver when idle
    GSetting("org.cinnamon.desktop.screensaver", "lock-enabled", "false"),  # nor a lock after it
    GSetting("org.cinnamon.settings-daemon.plugins.power", "lock-on-suspend", "false"),
    GSetting("org.cinnamon.settings-daemon.plugins.power", "sleep-display-ac", "0"),
    GSetting("org.cinnamon.settings-daemon.plugins.power", "sleep-display-battery", "0"),
    GSetting("org.cinnamon.settings-daemon.plugins.power", "sleep-inactive-ac-timeout", "0"),
    GSetting("org.cinnamon.settings-daemon.plugins.power", "sleep-inactive-battery-timeout", "0"),
)
XFCE_SETTINGS = (
    # light-locker: 0 seconds after the screensaver = never lock (its schema's description).
    GSetting("apps.light-locker", "lock-after-screensaver", "uint32 0"),
    GSetting("apps.light-locker", "lock-on-suspend", "false"),
    GSetting("apps.light-locker", "late-locking", "false"),
    # xfce4-power-manager: the X screensaver (blanking) light-locker locks after, screen sleep, computer sleep
    # (14 minutes is its "Never"), and the lock before a suspend.
    XfconfProperty("xfce4-power-manager", "/xfce4-power-manager/blank-on-ac", "int", "0"),
    XfconfProperty("xfce4-power-manager", "/xfce4-power-manager/blank-on-battery", "int", "0"),
    XfconfProperty("xfce4-power-manager", "/xfce4-power-manager/dpms-enabled", "bool", "false"),
    XfconfProperty("xfce4-power-manager", "/xfce4-power-manager/inactivity-on-ac", "uint", "14"),
    XfconfProperty("xfce4-power-manager", "/xfce4-power-manager/inactivity-on-battery", "uint", "14"),
    XfconfProperty("xfce4-power-manager", "/xfce4-power-manager/lock-screen-suspend-hibernate", "bool", "false"),
)
SETTINGS = {CINNAMON: CINNAMON_SETTINGS, XFCE: XFCE_SETTINGS}

Runner = Callable[[list[str]], subprocess.CompletedProcess]


def run_command(command: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(command, capture_output=True, text=True, check=False, timeout=20)
    except (OSError, subprocess.SubprocessError) as error:
        return subprocess.CompletedProcess(command, 127, "", str(error))


def current_desktop(environ=os.environ) -> str:
    """The session's desktop: from XDG_CURRENT_DESKTOP, else from the installed session (caramos_ota_update)."""

    names = environ.get("XDG_CURRENT_DESKTOP", "").upper().split(":")
    if "X-CINNAMON" in names or "CINNAMON" in names:
        return CINNAMON
    if "XFCE" in names:
        return XFCE
    try:
        from caramos_ota_update.desktop import current_desktop as installed_desktop
    except ImportError:
        return "other"
    return installed_desktop()


def state_path(environ=os.environ) -> Path:
    base = environ.get("XDG_STATE_HOME") or str(Path(environ.get("HOME") or Path.home()) / ".local/state")
    return Path(base) / STATE_NAME


# ---- reading and writing one setting --------------------------------------------------------------------------


def own_value(setting, run: Runner) -> tuple[bool, str | None]:
    """(whether the setting exists here, the account's own value or None)."""

    if isinstance(setting, GSetting):
        if run(["gsettings", "get", setting.schema, setting.key]).returncode != 0:
            return False, None  # schema not installed (another edition, light-locker removed...)
        result = run(["dconf", "read", setting.path])
        value = result.stdout.strip() if result.returncode == 0 else ""
        return True, value or None
    if run(["xfconf-query", "-c", setting.channel, "-l"]).returncode != 0:
        return False, None  # no xfconf (not an Xfce session)
    result = run(["xfconf-query", "-c", setting.channel, "-p", setting.prop])
    return True, result.stdout.strip() if result.returncode == 0 else None


def set_value(setting, value: str, run: Runner) -> bool:
    if isinstance(setting, GSetting):
        return run(["gsettings", "set", setting.schema, setting.key, value]).returncode == 0
    return run(["xfconf-query", "-c", setting.channel, "-p", setting.prop, "-n", "-t", setting.kind,
                "-s", value]).returncode == 0


def reset_value(setting, run: Runner) -> bool:
    if isinstance(setting, GSetting):
        return run(["gsettings", "reset", setting.schema, setting.key]).returncode == 0
    return run(["xfconf-query", "-c", setting.channel, "-p", setting.prop, "-r"]).returncode == 0


# ---- the account's settings -----------------------------------------------------------------------------------


def read_saved(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get("settings"), dict) else None


def write_saved(path: Path, saved: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(saved, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def apply(desktop: str | None = None, run: Runner = run_command, path: Path | None = None) -> list[str]:
    """Turn off this account's screensaver, automatic lock, screen sleep and suspend; the names of the settings changed.

    The account's own values are kept the first time only: applying again (every login) keeps what it had before the
    lab, and puts back the lab's values if someone changed them meanwhile.
    """

    desktop = current_desktop() if desktop is None else desktop
    path = state_path() if path is None else path
    saved = read_saved(path) or {"desktop": desktop, "settings": {}}
    changed = []
    for setting in SETTINGS.get(desktop, ()):
        exists, value = own_value(setting, run)
        if not exists:
            continue
        saved["settings"].setdefault(setting.name, value)
        if value != setting.value and set_value(setting, setting.value, run):
            changed.append(setting.name)
    if saved["settings"]:
        write_saved(path, saved)
    return changed


def restore(run: Runner = run_command, path: Path | None = None) -> list[str]:
    """Give the account back the settings it had before the lab; the names of the settings put back."""

    path = state_path() if path is None else path
    saved = read_saved(path)
    if saved is None:
        return []
    known = {setting.name: setting for settings in SETTINGS.values() for setting in settings}
    restored, left = [], {}
    for name, value in saved["settings"].items():
        setting = known.get(name)
        if setting is None:
            continue
        done = reset_value(setting, run) if value is None else set_value(setting, value, run)
        if done:
            restored.append(name)
        else:
            left[name] = value  # tried again at the next login (no session bus now, say)
    if left:
        write_saved(path, {**saved, "settings": left})
    else:
        path.unlink(missing_ok=True)
    return restored


def at_login(role: str | None, run: Runner = run_command, path: Path | None = None) -> str:
    """caramos-lab --session: a lab student's account stays awake; an account that was, gets its settings back."""

    from . import STUDENT

    if role == STUDENT:
        changed = apply(run=run, path=path)
        return "awake: " + (", ".join(changed) if changed else "nothing to change")
    restored = restore(run=run, path=path)
    return "restored: " + ", ".join(restored) if restored else "not a lab student"

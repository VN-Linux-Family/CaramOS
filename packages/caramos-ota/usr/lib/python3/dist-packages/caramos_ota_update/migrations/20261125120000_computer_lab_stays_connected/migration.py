"""Phòng máy (computer lab): students' computers stay in Veyon Master, with their screens, all lesson long.

A teacher piloting CaramOS in a lab of 18 computers saw some students' computers as an orange screen in Veyon Master
("Veyon Server unreachable or not running") until the student's or the teacher's computer restarted. Reproduced in a
VM lab (teacher Cinnamon; students Cinnamon and Xfce; Veyon 4.7.5 from Ubuntu):
- a student's Xfce locks itself when idle (light-locker): it switches to the login screen's session, Veyon Server
  follows it there, and on the way back Veyon 4.7.5 can lose its server for the student's session (3 of 7 lock and
  unlock rounds) and never starts it again;
- Veyon 4.7.5 does not start its server again after it exits for any other reason either;
- while a student's screen is locked (Xfce's login screen, Cinnamon's lock screen) Veyon's Lock and Demo cannot reach
  the student, who needs the account's password to get back.

On a computer the Phòng máy helper set up:
- with Veyon, a teacher's or a student's: caramos-lab-veyon-check.timer is enabled. Every 30 seconds it starts Veyon
  Server again when it stayed gone for a few seconds (caramos_lab/watchdog.py). New setups get it from the helper.
- a student's: the screensaver, automatic lock, screen sleep and suspend of every logged-in account are turned off
  now (`caramos-lab --session` as that account, caramos_lab/awake.py); every account gets the same at its next login
  (/etc/xdg/autostart/caramos-lab-session.desktop), and its own settings back after the computer left the lab.
A computer that left the lab with Phòng máy up to 1.5.1 still started Veyon Server at every boot: saving Veyon's
configuration (`veyon-cli config set`, the last step of leaving) enabled veyon.service again. Where Phòng máy set the
computer up (its folder /var/lib/caramos-ota/lab is there) but it is no longer in a lab (no state.json), and Veyon has
neither the lab's key nor key-file authentication (what leaving leaves behind), veyon.service is stopped and disabled.
Anything else, such as a Veyon an administrator set up with keys of their own, is left alone. The helper now disables
veyon.service last when a computer leaves.
A computer that Phòng máy never set up: nothing changes.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Computer lab: Veyon Server comes back by itself, and students' computers no longer lock or sleep"

help_applet = importlib.import_module("caramos_ota_update.migrations.20261012180000_add_help_applet.migration")

LAB_STATE = Path("/var/lib/caramos-ota/lab/state.json")
VEYON_KEYS = Path("/etc/veyon/keys")
KEY_NAME = "giaovien"  # caramos_lab.helper.KEY_NAME
CHECK_TIMER = "caramos-lab-veyon-check.timer"
LAB_COMMAND = "/usr/bin/caramos-lab"
RUNTIME_ROOT = Path("/run/user")


def read_state(path: Path = LAB_STATE) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def stop_veyon_after_leaving(context: MigrationContext, state_path: Path = LAB_STATE,
                             keys: Path = VEYON_KEYS) -> None:
    """veyon.service off on a computer that left the lab with Phòng máy up to 1.5.1 (see above)."""

    if state_path.exists() or not state_path.parent.is_dir():
        context.log("not a computer of a Phòng máy lab: nothing to change")
        return
    enabled = context.run_command(["systemctl", "is-enabled", "veyon.service"], allow_fail=True)
    if enabled is None or enabled.stdout.strip() != "enabled":
        context.log("this computer left the lab and Veyon does not start by itself: nothing to change")
        return
    if any((keys / kind / KEY_NAME / "key").exists() for kind in ("public", "private")):
        context.log("the lab's Veyon key is still here: veyon.service left as it is")
        return
    method = context.run_command(["veyon-cli", "config", "get", "Authentication/Method"], allow_fail=True)
    answer = method.stdout.strip() if method is not None and method.returncode == 0 else ""
    if answer not in ("", "0"):
        context.log(f"Veyon uses authentication method {answer[:40]} here (set up by someone else): left as it is")
        return
    result = context.run_command(["systemctl", "disable", "--now", "veyon.service"], allow_fail=True)
    if result is not None and result.returncode == 0:
        context.log("this computer left the lab: Veyon Server no longer starts at boot")
    else:
        context.log(f"warning: could not disable veyon.service: "
                    f"{result.stderr.strip()[:200] if result is not None else 'not run'}")


def keep_students_awake(context: MigrationContext, users: list[tuple[str, int, Path]],
                        runtime_root: Path = RUNTIME_ROOT) -> None:
    """caramos-lab --session as each logged-in account, on its session bus (gsettings, xfconf)."""

    for username, uid, home in users:
        runtime = runtime_root / str(uid)
        if not (runtime / "bus").exists():
            context.log(f"{username} is not logged in: their screen stops locking and sleeping from their next login")
            continue
        env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "HOME": str(home), "USER": username, "LOGNAME": username,
               "XDG_RUNTIME_DIR": str(runtime), "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime}/bus"}
        result = context.run_command(["runuser", "-u", username, "--", LAB_COMMAND, "--session"], allow_fail=True,
                                     env=env)
        if result is not None and result.returncode == 0:
            context.log(f"{username}: {result.stdout.strip() or 'done'}")
        else:
            error = result.stderr.strip()[:200] if result is not None else "not run"
            context.log(f"warning: could not change the screen lock of {username} ({error}); it changes from their "
                        "next login")


def run(context: MigrationContext, state_path: Path = LAB_STATE, users=None,
        runtime_root: Path = RUNTIME_ROOT, keys: Path = VEYON_KEYS) -> None:
    state = read_state(state_path)
    role, backend = state.get("role"), state.get("backend")
    if not role:
        stop_veyon_after_leaving(context, state_path, keys)
        return
    if backend == "veyon":
        result = context.run_command(["systemctl", "enable", "--now", CHECK_TIMER], allow_fail=True)
        if context.dry_run:
            context.log(f"would enable {CHECK_TIMER}")
        elif result is not None and result.returncode == 0:
            context.log(f"{CHECK_TIMER} enabled: Veyon Server starts again by itself when it is gone")
        else:
            context.log(f"warning: could not enable {CHECK_TIMER}: "
                        f"{result.stderr.strip()[:200] if result is not None else 'not run'}")
    if role != "student":
        context.log(f"the {role}'s computer keeps its screen lock")
        return
    if context.dry_run:
        context.log("would turn off the screen lock and sleep of every logged-in account")
        return
    keep_students_awake(context, help_applet._desktop_users() if users is None else users, runtime_root)

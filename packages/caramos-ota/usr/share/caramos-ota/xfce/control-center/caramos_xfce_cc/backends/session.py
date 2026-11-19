"""Suspend, restart, shut down, log out and switch user, with Xfce's session tools.

What the computer can do comes from logind, as for Cinnamon. Restart, shut down and log out end the session, so the
popup asks once more before running them (Cinnamon's session dialog does that there).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from gi.repository import Gio, GLib

from ..util import command_exists, spawn

LOG = logging.getLogger("caramos-control-center")

ACTIONS = {
    "suspend": ("xfce4-session-logout", "--suspend"),
    "hibernate": ("xfce4-session-logout", "--hibernate"),
    "restart": ("xfce4-session-logout", "--reboot"),
    "shutdown": ("xfce4-session-logout", "--halt"),
    "logout": ("xfce4-session-logout", "--logout"),
    "switchUser": ("dm-tool", "switch-to-greeter"),
}
# Actions that end the session: the popup asks before running them.
CONFIRM = ("restart", "shutdown", "logout")


@dataclass
class SessionState:
    available: bool = True
    can_suspend: bool = False
    can_hibernate: bool = False
    can_restart: bool = True
    can_shutdown: bool = True
    can_logout: bool = True
    can_switch_user: bool = False


def logind_can(answer: str) -> bool:
    return answer in ("yes", "challenge")


def read_state() -> SessionState:
    state = SessionState(available=command_exists("xfce4-session-logout"),
                         can_switch_user=command_exists("dm-tool"))
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
        for method, attr in (("CanSuspend", "can_suspend"), ("CanHibernate", "can_hibernate"),
                             ("CanReboot", "can_restart"), ("CanPowerOff", "can_shutdown")):
            reply = bus.call_sync("org.freedesktop.login1", "/org/freedesktop/login1",
                                  "org.freedesktop.login1.Manager", method, None, GLib.VariantType("(s)"),
                                  Gio.DBusCallFlags.NONE, 2000, None)
            setattr(state, attr, logind_can(reply.unpack()[0]))
    except GLib.Error as exc:
        LOG.info("logind: %s", exc.message)
    return state


def run(action: str) -> bool:
    argv = ACTIONS.get(action)
    return bool(argv) and spawn(argv)

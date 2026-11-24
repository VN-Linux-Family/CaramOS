"""Small helpers: the Xfce programs the Control Center opens, and commands run without blocking the popup."""

from __future__ import annotations

import logging
import shutil
import subprocess
from collections.abc import Callable, Sequence

from gi.repository import Gio, GLib

LOG = logging.getLogger("caramos-control-center")

ACCENT_PICKER = "/usr/share/caramos-ota/control-center/caramos-accent-picker"
# The sound keys' command (an Xfce keyboard shortcut): while the popup holds the keyboard, the popup runs it.
SOUND_KEYS = "/usr/share/caramos-ota/xfce/caramos-volume"

# What the Cinnamon applet runs with cinnamon-settings and cinnamon-session-quit, in Xfce.
COMMANDS: dict[str, Sequence[str]] = {
    "settings": ("xfce4-settings-manager",),
    "soundSettings": ("pavucontrol",),
    "networkSettings": ("nm-connection-editor",),
    "bluetoothSettings": ("blueman-manager",),
    "powerSettings": ("xfce4-power-manager-settings",),
    "lock": ("xflock4",),
    "switchUser": ("dm-tool", "switch-to-greeter"),
    "screenshot": ("flameshot", "gui"),
    "accentPicker": (ACCENT_PICKER,),
}


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None or name.startswith("/") and GLib.file_test(name, GLib.FileTest.IS_EXECUTABLE)


def spawn(argv: Sequence[str]) -> bool:
    """Start a program and forget it (its own session, so closing the popup or the panel does not stop it)."""

    try:
        subprocess.Popen(list(argv), start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError as exc:
        LOG.warning("could not start %s: %s", argv[0], exc)
        return False


def spawn_named(command: str) -> bool:
    argv = COMMANDS.get(command)
    return bool(argv) and spawn(argv)


def run_async(argv: Sequence[str], on_done: Callable[[bool, str, str], None]) -> None:
    """Run a command and call on_done(succeeded, stdout, stderr) in the main loop when it ends."""

    try:
        process = Gio.Subprocess.new(list(argv), Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
    except GLib.Error as exc:
        on_done(False, "", exc.message)
        return

    def finished(proc: Gio.Subprocess, result: Gio.AsyncResult) -> None:
        try:
            _ok, stdout, stderr = proc.communicate_utf8_finish(result)
        except GLib.Error as exc:
            on_done(False, "", exc.message)
            return
        on_done(proc.get_successful(), stdout or "", stderr or "")

    process.communicate_utf8_async(None, None, finished)


def first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def notify(app_name: str, summary: str, body: str, icon: str, transient: bool = False) -> None:
    """A desktop notification (org.freedesktop.Notifications), sent without waiting for an answer."""

    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as exc:
        LOG.warning("notification: %s", exc.message)
        return
    hints = {"transient": GLib.Variant("b", True)} if transient else {}
    bus.call("org.freedesktop.Notifications", "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
             "Notify", GLib.Variant("(susssasa{sv}i)", (app_name, 0, icon, summary, body, [], hints, -1)),
             None, Gio.DBusCallFlags.NONE, -1, None, None)

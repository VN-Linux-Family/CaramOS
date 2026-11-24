"""Remote help from the admin's side (PROTOCOL.md part 2, "Help requests and remote help", and part 3, "Remote help:
per-session key and a closed viewer port").

The helper first makes the session's key, starts stunnel on port 5501 with it (a transient unit) and closes the
viewer's port 5500 to the network. Then the viewer listens (TigerVNC's vncviewer -listen, as the admin user, reachable
only from this machine), and the remote_help command, with the key sealed for the machine, tells the employee's
machine where to connect. The employee is asked first; a window here waits for the answer, shows when the session
runs, and stops the viewer and stunnel at the end."""

from __future__ import annotations

import os
import pwd
import shutil
import time
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import REMOTE_HELP_PORT, VIEWER_PORT, client, summaries  # noqa: E402
from ..i18n import _  # noqa: E402
from . import common  # noqa: E402

ANSWER_SECONDS = 120  # the employee has 60 s to accept; the command waits up to 3 minutes for the machine


def admin_name() -> str:
    """How the employee sees the admin: their full name, else their login name."""

    try:
        entry = pwd.getpwuid(os.getuid())
    except KeyError:
        return ""
    full = entry.pw_gecos.split(",", 1)[0].strip()
    return (full or entry.pw_name)[:64]


def tcp_established(port: int, tables: tuple[str, ...] = ("/proc/net/tcp", "/proc/net/tcp6")) -> bool:
    """Whether a TCP connection to a local port is established (a VNC server reached the listening viewer)."""

    wanted = f":{port:04X}"
    for table in tables:
        try:
            lines = Path(table).read_text(encoding="ascii").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) > 3 and fields[1].endswith(wanted) and fields[3] == "01":
                return True
    return False


def ask_remote_help(ctx: Any, machine_id: str, help_id: str | None = None) -> None:
    """Asks how to help (see or control), then starts."""

    if machine_id not in ctx.machines:
        ctx.toast(_("This machine is no longer in the company."))
        return
    if not shutil.which("vncviewer"):
        ctx.toast(_("Remote help needs the tigervnc-viewer package on this machine."), 6)
        return
    name = ctx.machine_name(machine_id)
    dialog = Adw.AlertDialog(heading=_("Remote help on %s") % name,
                             body=_("The person at the machine is asked first, and sees a small window while you "
                                    "help, with a button to stop."))
    group = Adw.PreferencesGroup()
    choice = {"mode": "control"}
    first = None
    for mode, title, subtitle in (("control", _("See and control"), _("Use their mouse and keyboard.")),
                                  ("view", _("Only see"), _("Watch their screen and guide them by phone."))):
        check = Gtk.CheckButton(active=mode == "control", valign=Gtk.Align.CENTER)
        if first is None:
            first = check
        else:
            check.set_group(first)
        row = common.row(title, subtitle)
        row.add_prefix(check)
        row.set_activatable_widget(check)
        check.connect("toggled", lambda button, value=mode: button.get_active() and choice.__setitem__("mode", value))
        group.add(row)
    dialog.set_extra_child(group)
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("ok", _("Connect"))
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _d, answer: answer == "ok" and RemoteHelp(ctx, machine_id, choice["mode"],
                                                                                help_id).start())
    dialog.present(ctx.window)


class RemoteHelp:
    def __init__(self, ctx: Any, machine_id: str, mode: str, help_id: str | None = None) -> None:
        self.ctx = ctx
        self.machine_id = machine_id
        self.mode = mode
        self.help_id = help_id
        self.name = ctx.machine_name(machine_id)
        self.viewer: Gio.Subprocess | None = None
        self.command_id: str | None = None
        self.connected = False
        self.stopping = False
        self.timer = 0
        self.started = time.monotonic()

    # - the window -

    def show(self) -> None:
        self.dialog = Adw.Dialog(title=_("Remote help"), content_width=420, can_close=False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=24,
                      margin_start=24, margin_end=24)
        self.heading = common.label(_("Waiting for the employee to accept…"), "title-3")
        self.detail = common.label(_("%s shows them a question; they have a minute to answer.") % self.name,
                                   "paragraph")
        self.spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.START)
        self.button = common.button(_("Stop"), self.pressed, "destructive-action")
        self.button.set_halign(Gtk.Align.END)
        for widget in (self.heading, self.detail, self.spinner, self.button):
            box.append(widget)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar(show_end_title_buttons=False))
        view.set_content(box)
        self.dialog.set_child(view)
        self.dialog.present(self.ctx.window)

    def finish(self, heading: str, detail: str) -> None:
        self.heading.set_label(heading)
        self.detail.set_label(detail)
        self.spinner.set_spinning(False)
        self.spinner.set_visible(False)
        self.button.set_label(_("Close"))
        self.button.remove_css_class("destructive-action")

    def pressed(self) -> None:
        """Stop while it runs; Close once it ended."""

        if self.stopping:
            self.dialog.force_close()
        else:
            self.stop()

    # - the session -

    def start(self) -> None:
        self.show()
        # The tunnel, the key and the firewall rule first: the viewer listens on every interface (part 3).
        self.ctx.helper(["remote-help", "start"], self.tunnel_started)

    def tunnel_started(self, ok: bool, answer: dict[str, Any]) -> None:
        if self.stopping:
            return
        if not ok:
            self.stop(_("Remote help could not start"), answer.get("error", ""))
            return
        try:
            self.viewer = Gio.Subprocess.new(["vncviewer", "-listen", str(VIEWER_PORT)],
                                             Gio.SubprocessFlags.STDOUT_SILENCE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error as exc:
            self.stop(_("Remote help could not start"), exc.message)
            return
        self.viewer.wait_async(None, self.viewer_exited)
        machine = (self.ctx.machines.get(self.machine_id) or {}).get("machine") or {}
        try:
            host = client.route_toward(machine.get("ip", ""))[0]
        except OSError:
            host = ""
        if not host:
            self.stop(_("Remote help could not start"), _("This machine has no address toward %s.") % self.name)
            return
        self.ctx.command({"machines": [self.machine_id]}, "remote_help",
                         {"admin_host": host, "port": REMOTE_HELP_PORT, "mode": self.mode, "admin_name": admin_name()},
                         done=self.sent, help_id=self.help_id)

    def sent(self, command_id: str | None) -> None:
        if command_id is None:
            self.stop(_("Remote help could not start"), _("The request could not be sent."))
            return
        self.command_id = command_id
        self.started = time.monotonic()
        self.timer = GLib.timeout_add_seconds(1, self.poll)

    def poll(self) -> bool:
        if self.stopping:
            return False
        self.ctx.reload()
        result = self.ctx.command_results(self.command_id or "").get(self.machine_id)
        if tcp_established(VIEWER_PORT) and not self.connected:
            self.connected = True
            self.spinner.set_visible(False)
            self.heading.set_label(_("Helping %s") % self.name)
            self.detail.set_label(_("Their screen is in the viewer window. They see that you are helping and can stop "
                                    "it; so can you."))
        if result:
            state = result.get("state")
            detail = result.get("detail") or ""
            if state == "refused" and "psk" in detail:  # the agent's refusal (PROTOCOL.md part 3), not the employee's
                self.stop(_("Remote help did not start"), detail)
            elif state == "refused":
                self.stop(_("The employee refused"), _("Call them, or try again later."))
            elif state == "done":
                self.stop(_("Remote help ended"), summaries.result_detail("remote_help", result.get("detail") or ""))
            else:
                self.stop(_("Remote help did not start"), result.get("detail") or state or "")
            return False
        if not self.connected and time.monotonic() - self.started > ANSWER_SECONDS:
            self.stop(_("No answer"), _("%s did not answer: it may be off, or nobody is at it.") % self.name)
            return False
        return True

    def viewer_exited(self, process: Gio.Subprocess, result: Gio.AsyncResult) -> None:
        try:
            process.wait_finish(result)
        except GLib.Error:
            pass
        self.viewer = None
        if not self.stopping:
            if self.connected:
                self.stop(_("Remote help ended"), _("The viewer was closed."))
            else:
                self.stop(_("Remote help could not start"), _("The viewer stopped. Is port 5500 taken by another "
                                                              "viewer?"))

    def stop(self, heading: str | None = None, detail: str = "") -> None:
        if self.stopping:
            return
        self.stopping = True
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        if self.viewer is not None:
            self.viewer.force_exit()
        self.ctx.helper(["remote-help", "stop"], lambda _ok, _answer: None)
        if heading is None:
            self.dialog.force_close()
        else:
            self.finish(heading, detail)

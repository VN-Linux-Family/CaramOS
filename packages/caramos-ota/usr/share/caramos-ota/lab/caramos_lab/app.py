"""The Phòng máy window (GTK 4 + libadwaita): set up the teacher's or a student's computer and pair them.

    caramos-lab              open the window
    caramos-lab --status     print this computer's lab state as JSON

Root work goes through pkexec to caramos-lab-helper (helper.py), which reports JSON lines; the pairing over the
LAN (pairing.py) runs as the user, in threads, with results handed back to the main loop.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from caramos_ota.i18n import _

from . import EPOPTES, STUDENT, TEACHER, VEYON
from . import pairing, system

APP_ID = "net.vietnamlinuxfamily.CaramOSLab"
HELPER = "/usr/share/caramos-ota/lab/caramos-lab-helper"
DEFAULT_ROOM = "Phòng máy 1"


def backend_name(backend: str) -> str:
    return "Veyon" if backend == VEYON else "Epoptes"


def open_console(backend: str) -> None:
    """Veyon Master, or Epoptes with the epoptes group the teacher joined before their next login."""

    if backend == VEYON:
        subprocess.Popen(["veyon-master"], start_new_session=True)
    elif shutil.which("sg"):
        subprocess.Popen(["sg", "epoptes", "-c", "epoptes"], start_new_session=True)
    else:
        subprocess.Popen(["epoptes"], start_new_session=True)


def build_window(app):
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib, Gtk, Pango

    def text(content: str, *classes: str, xalign: float = 0.0, selectable: bool = False) -> Gtk.Label:
        widget = Gtk.Label(label=content, xalign=xalign, wrap=True, selectable=selectable)
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        for name in classes:
            widget.add_css_class(name)
        return widget

    def page_box() -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=24, margin_bottom=24,
                      margin_start=24, margin_end=24)
        return box

    def scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
        clamp = Adw.Clamp(maximum_size=640, child=child)
        return Gtk.ScrolledWindow(child=clamp, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)

    def pill(label: str, suggested: bool = False) -> Gtk.Button:
        button = Gtk.Button(label=label, halign=Gtk.Align.CENTER)
        button.add_css_class("pill")
        if suggested:
            button.add_css_class("suggested-action")
        return button

    class Window(Adw.ApplicationWindow):
        def __init__(self) -> None:
            super().__init__(application=app, title=_("Computer Lab"), default_width=620, default_height=640)
            self.toasts = Adw.ToastOverlay()
            self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
            self.back = Gtk.Button(icon_name="go-previous-symbolic", visible=False, tooltip_text=_("Back"))
            self.back.connect("clicked", lambda *_a: self.show_home())
            header = Adw.HeaderBar()
            header.pack_start(self.back)
            view = Adw.ToolbarView(content=self.stack)
            view.add_top_bar(header)
            self.toasts.set_child(view)
            self.set_content(self.toasts)
            self.server: pairing.TeacherServer | None = None
            self.adder: Gio.Subprocess | None = None
            self.connect("close-request", self.on_close)
            self.show_home()

        # ---- navigation -------------------------------------------------------------------------------------

        def show(self, name: str, widget: Gtk.Widget, back: bool = True) -> None:
            old = self.stack.get_child_by_name(name)
            if old is not None:
                self.stack.remove(old)
            self.stack.add_named(widget, name)
            self.stack.set_visible_child_name(name)
            self.back.set_visible(back)

        def toast(self, message: str) -> None:
            self.toasts.add_toast(Adw.Toast(title=message, timeout=5))

        def show_home(self) -> None:
            self.stop_pairing()
            state = system.read_state()
            box = page_box()
            box.append(text(_("Computer Lab"), "title-1"))
            role = state.get("role")
            if role == TEACHER:
                self.home_teacher(box, state)
            elif role == STUDENT:
                self.home_student(box, state)
            else:
                self.home_new(box)
            self.show("home", scrolled(box), back=False)

        def home_new(self, box: Gtk.Box) -> None:
            box.append(text(_("Classroom management in a few clicks: the teacher's computer sees every student's "
                              "screen, shows its own screen to the class, locks the screens, sends files and turns "
                              "the computers off.")))
            group = Adw.PreferencesGroup()
            for title, subtitle, handler in (
                    (_("Teacher's computer"), _("Installs Veyon and shows a code for pairing the students' computers."),
                     self.teacher_setup),
                    (_("Student's computer"), _("Finds the teacher's computer on the network and pairs with its code."),
                     self.student_find)):
                row = Adw.ActionRow(title=title, subtitle=subtitle, activatable=True)
                row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
                row.connect("activated", lambda *_a, h=handler: h())
                group.add(row)
            box.append(group)
            box.append(text(_("All the computers must be on the same network: the school's cable or Wi-Fi."), "dim-label"))

        def home_teacher(self, box: Gtk.Box, state: dict) -> None:
            backend = state.get("backend", VEYON)
            box.append(text(_("This is the teacher's computer of “{room}” ({backend}).").format(
                room=state.get("room", ""), backend=backend_name(backend))))
            pair = pill(_("Pair students' computers"), suggested=True)
            pair.connect("clicked", lambda *_a: self.start_pairing(state))
            box.append(pair)
            console = pill(_("Open Veyon Master") if backend == VEYON else _("Open Epoptes"))
            console.connect("clicked", lambda *_a: open_console(backend))
            box.append(console)
            self.leave_button(box, _("Stop being the teacher's computer"))

        def home_student(self, box: Gtk.Box, state: dict) -> None:
            teacher = state.get("teacher") or {}
            box.append(text(_("This is a student's computer of “{room}”, paired with the teacher's computer {name} "
                              "({host}).").format(room=state.get("room", ""), name=teacher.get("name", ""),
                                                  host=teacher.get("host", ""))))
            again = pill(_("Pair again"))
            again.connect("clicked", lambda *_a: self.student_find())
            box.append(again)
            self.leave_button(box, _("Leave the computer lab"))

        def leave_button(self, box: Gtk.Box, label: str) -> None:
            button = pill(label)

            def confirm(*_args) -> None:
                dialog = Adw.MessageDialog(transient_for=self, heading=label,
                                           body=_("Veyon or Epoptes stops on this computer and it leaves the room. "
                                                  "You can set it up again later."))
                dialog.add_response("cancel", _("Cancel"))
                dialog.add_response("leave", label)
                dialog.set_response_appearance("leave", Adw.ResponseAppearance.DESTRUCTIVE)
                dialog.connect("response", lambda _d, response: response == "leave" and self.run_helper(
                    ["leave"], _("Leaving the computer lab"), lambda _event: self.show_home()))
                dialog.present()

            button.connect("clicked", confirm)
            box.append(button)

        # ---- root helper ------------------------------------------------------------------------------------

        def run_helper(self, args: list[str], title: str, on_done, stdin: bool = False) -> None:
            box = page_box()
            box.append(text(title, "title-2"))
            spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32, halign=Gtk.Align.CENTER)
            box.append(spinner)
            step = text(_("Waiting for the password…"), "dim-label", xalign=0.5)
            box.append(step)
            log = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR, vexpand=True)
            expander = Gtk.Expander(label=_("Details"), child=Gtk.ScrolledWindow(child=log, min_content_height=160))
            box.append(expander)
            self.show("progress", scrolled(box), back=False)
            steps = {"install": _("Installing the software (it may take a few minutes)…"),
                     "apt-update": _("Updating the list of software…"),
                     "configure": _("Setting up…")}
            process = Gio.Subprocess.new(["pkexec", HELPER, *args],
                                         Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
            stream = Gio.DataInputStream.new(process.get_stdout_pipe())
            result: dict = {}

            def append(line: str) -> None:
                buffer = log.get_buffer()
                buffer.insert(buffer.get_end_iter(), line + "\n")

            def read(_stream, task) -> None:
                line, _length = stream.read_line_finish_utf8(task)
                if line is None:
                    process.wait_async(None, finished)
                    return
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    append(line)
                else:
                    kind = event.get("event")
                    if kind == "step":
                        step.set_label(steps.get(event.get("text"), event.get("text", "")))
                    elif kind == "log":
                        append(event.get("text", ""))
                    elif kind in ("done", "error"):
                        result.update(event)
                        if kind == "error":
                            append(event.get("text", ""))
                stream.read_line_async(GLib.PRIORITY_DEFAULT, None, read)

            def finished(proc, task) -> None:
                proc.wait_finish(task)
                status = proc.get_exit_status() if proc.get_if_exited() else 1
                if result.get("event") == "done":
                    on_done(result)
                    return
                spinner.set_spinning(False)
                if status in (126, 127):
                    step.set_label(_("Cancelled: the password window was closed."))
                else:
                    step.set_label(_("Something went wrong. The details below say what."))
                    expander.set_expanded(True)
                self.back.set_visible(True)

            stream.read_line_async(GLib.PRIORITY_DEFAULT, None, read)

        # ---- teacher ----------------------------------------------------------------------------------------

        def teacher_setup(self) -> None:
            box = page_box()
            box.append(text(_("Teacher's computer"), "title-2"))
            group = Adw.PreferencesGroup()
            room = Adw.EntryRow(title=_("Room name"), text=DEFAULT_ROOM)
            group.add(room)
            box.append(group)
            choices = Adw.PreferencesGroup(title=_("Software"))
            veyon = Gtk.CheckButton(active=True)
            epoptes = Gtk.CheckButton(group=veyon)
            for check, title, subtitle in (
                    (veyon, _("Veyon (recommended)"),
                     _("See and control the students' screens, show the teacher's screen, lock screens, send files, "
                       "turn computers off. Works with Veyon on Windows too.")),
                    (epoptes, _("Epoptes (lighter)"),
                     _("For computers with 2 GB of memory. The students' computers connect to the teacher's by "
                       "themselves."))):
                row = Adw.ActionRow(title=title, subtitle=subtitle, activatable_widget=check)
                row.add_prefix(check)
                choices.add(row)
            box.append(choices)
            error = text("", "error")
            box.append(error)
            go = pill(_("Set up this computer"), suggested=True)
            box.append(go)

            def start(*_args) -> None:
                name = room.get_text().strip()
                if not pairing.valid_room(name):
                    error.set_label(_("Use letters, digits, spaces or dashes for the room name (up to 40)."))
                    return
                backend = VEYON if veyon.get_active() else EPOPTES
                self.run_helper(["teacher", "--backend", backend, "--room", name],
                                _("Setting up the teacher's computer"),
                                lambda _event: self.start_pairing(system.read_state()))

            go.connect("clicked", start)
            self.show("teacher-setup", scrolled(box))

        def start_pairing(self, state: dict) -> None:
            backend, room = state.get("backend", VEYON), state.get("room", DEFAULT_ROOM)
            key = system.teacher_key(backend)
            if key is None:
                self.toast(_("The teacher's key is missing: set this computer up again."))
                return
            box = page_box()
            box.append(text(_("Pairing code"), "title-4", xalign=0.5))
            code = text(pairing.spaced(pairing.pairing_code(key)), "title-1", xalign=0.5, selectable=True)
            code.add_css_class("caramos-lab-code")
            box.append(code)
            address = system.local_ip() or "?"
            box.append(text(_("On each student's computer open Computer Lab > Student's computer, choose “{room}” "
                              "(teacher's computer {name}, {address}) and type this code.").format(
                room=room, name=system.hostname(), address=address), xalign=0.5))
            group = Adw.PreferencesGroup(title=_("Paired computers"))
            box.append(group)
            empty = Adw.ActionRow(title=_("None yet. Keep this page open while you pair."))
            group.add(empty)
            buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
            console = pill(_("Open Veyon Master") if backend == VEYON else _("Open Epoptes"), suggested=True)
            console.connect("clicked", lambda *_a: open_console(backend))
            done = pill(_("Done"))
            done.connect("clicked", lambda *_a: self.show_home())
            buttons.append(console)
            buttons.append(done)
            box.append(buttons)
            self.show("pairing", scrolled(box))
            rows: dict[str, Adw.ActionRow] = {}

            def show_student(student: pairing.Student, added: bool) -> None:
                if empty.get_parent() is not None:
                    group.remove(empty)
                row = rows.get(student.mac)
                if row is None:
                    row = Adw.ActionRow(title=student.name)
                    rows[student.mac] = row
                    group.add(row)
                row.set_subtitle(f"{student.ip} · " + (_("added to the room") if added else _("adding…")))

            if backend == VEYON:
                # One root process for the whole page: each student is added to Veyon's room as it pairs.
                self.adder = Gio.Subprocess.new(["pkexec", HELPER, "add-computers", "--room", room],
                                                Gio.SubprocessFlags.STDIN_PIPE | Gio.SubprocessFlags.STDOUT_PIPE)
                stream = Gio.DataInputStream.new(self.adder.get_stdout_pipe())

                def read(_stream, task) -> None:
                    try:
                        line, _length = stream.read_line_finish_utf8(task)
                    except GLib.Error:
                        return
                    if line is None:
                        return
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        event = {}
                    if event.get("event") == "added":
                        show_student(pairing.Student(event["name"], event["ip"], event["mac"]), True)
                    stream.read_line_async(GLib.PRIORITY_DEFAULT, None, read)

                stream.read_line_async(GLib.PRIORITY_DEFAULT, None, read)

            def registered(student: pairing.Student) -> bool:
                show_student(student, backend != VEYON)
                if self.adder is not None:
                    line = json.dumps(student.as_json()) + "\n"
                    self.adder.get_stdin_pipe().write_bytes(GLib.Bytes.new(line.encode("utf-8")), None)
                return False

            try:
                self.server = pairing.TeacherServer(system.hostname(), room, backend, key,
                                                    lambda student: GLib.idle_add(registered, student)).start()
            except OSError as error:
                self.toast(_("Pairing cannot start: {error}").format(error=error))

        def stop_pairing(self) -> None:
            if self.server is not None:
                self.server.stop()
                self.server = None
            if self.adder is not None:
                try:
                    self.adder.get_stdin_pipe().close(None)
                except GLib.Error:
                    pass
                self.adder = None

        def on_close(self, *_args) -> bool:
            self.stop_pairing()
            return False

        # ---- student ----------------------------------------------------------------------------------------

        def student_find(self) -> None:
            box = page_box()
            box.append(text(_("Student's computer"), "title-2"))
            status = text(_("Looking for the teacher's computer on the network…"), xalign=0.5)
            box.append(status)
            spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER, width_request=32, height_request=32)
            box.append(spinner)
            group = Adw.PreferencesGroup()
            box.append(group)
            again = pill(_("Search again"))
            again.set_visible(False)
            again.connect("clicked", lambda *_a: self.student_find())
            box.append(again)
            self.show("student-find", scrolled(box))

            def found(teachers: list[pairing.Teacher]) -> bool:
                spinner.set_spinning(False)
                spinner.set_visible(False)
                again.set_visible(True)
                if not teachers:
                    status.set_label(_("No teacher's computer found. On the teacher's computer open Computer Lab and "
                                       "keep its pairing page open, then search again."))
                    return False
                status.set_label(_("Choose the teacher's computer of your room:"))
                for teacher in teachers:
                    row = Adw.ActionRow(title=teacher.room, activatable=True,
                                        subtitle=f"{teacher.name} · {teacher.host} · {backend_name(teacher.backend)}")
                    row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
                    row.connect("activated", lambda *_a, t=teacher: self.student_code(t))
                    group.add(row)
                return False

            threading.Thread(target=lambda: GLib.idle_add(found, pairing.discover()), daemon=True).start()

        def student_code(self, teacher: pairing.Teacher) -> None:
            box = page_box()
            box.append(text(_("Pair with “{room}”").format(room=teacher.room), "title-2"))
            box.append(text(_("Type the 6-digit code shown on the teacher's computer.")))
            group = Adw.PreferencesGroup()
            entry = Adw.EntryRow(title=_("Pairing code"))
            entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
            group.add(entry)
            box.append(group)
            error = text("", "error")
            box.append(error)
            go = pill(_("Pair"), suggested=True)
            box.append(go)

            def fetched(key: bytes | None, problem: str | None) -> bool:
                go.set_sensitive(True)
                if key is None:
                    error.set_label(problem or "")
                    return False
                if not pairing.check_code(key, entry.get_text()):
                    error.set_label(_("The code does not match. Check the code on the teacher's computer."))
                    return False
                handle, path = tempfile.mkstemp(prefix="caramos-lab-key-", suffix=".pem")
                with os.fdopen(handle, "wb") as stream:
                    stream.write(key)
                os.chmod(path, 0o644)
                self.run_helper(["student", "--backend", teacher.backend, "--room", teacher.room,
                                 "--teacher-host", teacher.host, "--teacher-name", teacher.name, "--key", path],
                                _("Setting up the student's computer"),
                                lambda _event: (os.unlink(path), self.student_register(teacher)))
                return False

            def start(*_args) -> None:
                if len(pairing.clean_code(entry.get_text())) != 6:
                    error.set_label(_("The code has 6 digits."))
                    return
                go.set_sensitive(False)
                error.set_label("")

                def work() -> None:
                    try:
                        key = pairing.fetch_key(teacher)
                    except pairing.PairingError:
                        GLib.idle_add(fetched, None, _("The teacher's computer does not answer. Keep its pairing page "
                                                       "open and try again."))
                        return
                    GLib.idle_add(fetched, key, None)

                threading.Thread(target=work, daemon=True).start()

            go.connect("clicked", start)
            entry.connect("entry-activated", start)
            self.show("student-code", scrolled(box))

        def student_register(self, teacher: pairing.Teacher) -> None:
            def work() -> None:
                ip = system.local_ip(teacher.host)
                mac = system.mac_of(ip) if ip else None
                try:
                    if not (ip and mac):
                        raise pairing.PairingError("no address")
                    pairing.register(teacher, pairing.Student(system.hostname(), ip, mac))
                    GLib.idle_add(done, True)
                except pairing.PairingError:
                    GLib.idle_add(done, False)

            def done(ok: bool) -> bool:
                box = page_box()
                box.append(Gtk.Image(icon_name="emblem-ok-symbolic", pixel_size=64))
                box.append(text(_("This computer is in “{room}”.").format(room=teacher.room), "title-2", xalign=0.5))
                if ok or teacher.backend == EPOPTES:
                    box.append(text(_("The teacher can see it now in {software}.").format(
                        software=backend_name(teacher.backend)), xalign=0.5))
                else:
                    box.append(text(_("The teacher's computer did not add it to the room's list: keep the pairing "
                                      "page open on the teacher's computer and pair again."), xalign=0.5))
                close = pill(_("Done"), suggested=True)
                close.connect("clicked", lambda *_a: self.show_home())
                box.append(close)
                self.show("student-done", scrolled(box), back=False)
                return False

            threading.Thread(target=work, daemon=True).start()

    return Window()


def open_window() -> int:
    from caramos_ota import gtk_renderer

    gtk_renderer.apply()  # cairo where OpenGL would run on the CPU
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GLib, Gtk

    GLib.set_prgname("caramos-lab")
    GLib.set_application_name(_("Computer Lab"))
    application = Adw.Application(application_id=APP_ID)

    def activate(app) -> None:
        window = app.get_active_window()
        if window is None:
            css = Gtk.CssProvider()
            css.load_from_string(".caramos-lab-code { font-size: 44pt; font-weight: 800; letter-spacing: 6px; }")
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            window = build_window(app)
        window.present()

    application.connect("activate", activate)
    return application.run([sys.argv[0]])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caramos-lab", description=_("Computer Lab"))
    parser.add_argument("--status", action="store_true", help="print this computer's lab state as JSON")
    args = parser.parse_args(argv)
    if args.status:
        print(json.dumps(system.read_state(), ensure_ascii=False, indent=1))
        return 0
    return open_window()

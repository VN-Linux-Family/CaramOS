"""The Phòng máy window (GTK 4 + libadwaita): set up the teacher's or a student's computer and pair them.

    caramos-lab              open the window
    caramos-lab --status     print this computer's lab state as JSON
    caramos-lab --session    at login (autostart): a student's account stops locking and sleeping (awake.py)

Root work goes through pkexec to caramos-lab-helper (helper.py), which reports JSON lines; the pairing over the
LAN (pairing.py) runs as the user, in threads, with results handed back to the main loop.

The look follows DESIGN.md in the CaramOS repository, like Chuyển dữ liệu từ Windows: libadwaita's navigation pages,
boxed lists and status pages, the forest green accent and two font weights (caramos_ota.adw_style); the main action
of a page is the right-most button of the bar at the bottom; round "pill" buttons only on status pages (done, error,
nothing found); details as sentences, not joined with dots.
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

from caramos_ota.i18n import _, ngettext

from . import EPOPTES, STUDENT, TEACHER, VEYON
from . import awake, pairing, system

APP_ID = "net.vietnamlinuxfamily.CaramOSLab"
HELPER = "/usr/share/caramos-ota/lab/caramos-lab-helper"
LOGO = Path("/usr/share/pixmaps/caramos-logo.png")
# The six digits of the pairing code: the one thing on its page to read from across the room (DESIGN.md's two weights).
CSS = ".caramos-lab-code { font-size: 3.2em; font-weight: 600; letter-spacing: 0.12em; font-feature-settings: 'tnum'; }"


def backend_name(backend: str) -> str:
    return "Veyon" if backend == VEYON else "Epoptes"


def default_room() -> str:
    return _("Computer lab 1")


def console_name(backend: str) -> str:
    return "Veyon Master" if backend == VEYON else "Epoptes"


def open_console(backend: str) -> None:
    """Veyon Master, or Epoptes with the epoptes group the teacher joined before their next login."""

    if backend == VEYON:
        subprocess.Popen(["veyon-master"], start_new_session=True)
    elif shutil.which("sg"):
        subprocess.Popen(["sg", "epoptes", "-c", "epoptes"], start_new_session=True)
    else:
        subprocess.Popen(["epoptes"], start_new_session=True)


def teacher_line(teacher: pairing.Teacher) -> str:
    """A teacher's computer found on the network, as a sentence."""

    return _("Teacher's computer {name}, at {address}, with {software}.").format(
        name=teacher.name, address=teacher.host, software=backend_name(teacher.backend))


def student_line(student: pairing.Student, added: bool) -> str:
    """A paired student's computer on the teacher's pairing page, as a sentence."""

    if added:
        return _("At {address}, in the room.").format(address=student.ip)
    return _("At {address}, being added to the room…").format(address=student.ip)


def build_window(app):
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib, Gtk, Pango

    def label(content: str, *classes: str, xalign: float = 0.0, visible: bool = True) -> Gtk.Label:
        widget = Gtk.Label(label=content, xalign=xalign, wrap=True, visible=visible)
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        for name in classes:
            widget.add_css_class(name)
        return widget

    def content_box() -> Gtk.Box:
        return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=24, margin_bottom=24,
                       margin_start=24, margin_end=24)

    def section(box: Gtk.Box, title: str) -> None:
        heading = label(title, "section-title")
        heading.set_margin_top(16)
        box.append(heading)

    def intro(box: Gtk.Box, sentence: str) -> None:
        """The first page's introduction: the logo, the app's name and one sentence (DESIGN.md)."""

        row = Gtk.Box(spacing=16)
        if LOGO.exists():
            logo = Gtk.Image.new_from_file(str(LOGO))
            logo.set_pixel_size(48)
            logo.set_valign(Gtk.Align.START)
            row.append(logo)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        texts.append(label(_("Computer Lab"), "page-title"))
        texts.append(label(sentence))
        row.append(texts)
        box.append(row)

    def scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
        return Gtk.ScrolledWindow(child=Adw.Clamp(maximum_size=640, child=child), vexpand=True,
                                  hscrollbar_policy=Gtk.PolicyType.NEVER)

    def chevron_row(title: str, subtitle: str, handler) -> Adw.ActionRow:
        row = Adw.ActionRow(title=GLib.markup_escape_text(title), subtitle=GLib.markup_escape_text(subtitle),
                            activatable=True)
        row.set_subtitle_lines(3)
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        row.connect("activated", lambda *_a: handler())
        return row

    def button(text: str, handler, primary: bool = False) -> Gtk.Button:
        widget = Gtk.Button(label=text, valign=Gtk.Align.CENTER)
        if primary:
            widget.add_css_class("suggested-action")
        widget.connect("clicked", lambda *_a: handler())
        return widget

    def status_page(icon: str | None, title: str, description: str, buttons: list[Gtk.Button],
                    child: Gtk.Widget | None = None) -> Adw.StatusPage:
        """Done, error, nothing found, waiting: centred, with round buttons (DESIGN.md)."""

        # A status page's title is plain text, its description Pango markup.
        page = Adw.StatusPage(title=title, description=GLib.markup_escape_text(description))
        if icon:
            page.set_icon_name(icon)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        if child is not None:
            box.append(child)
        if buttons:
            row = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
            for widget in buttons:
                widget.add_css_class("pill")
                row.append(widget)
            box.append(row)
        page.set_child(box)
        return page

    class Window(Adw.ApplicationWindow):
        def __init__(self) -> None:
            super().__init__(application=app, title=_("Computer Lab"), default_width=640, default_height=640)
            self.set_size_request(360, 480)
            self.toasts = Adw.ToastOverlay()
            self.nav = Adw.NavigationView()
            self.nav.connect("popped", self.on_popped)
            self.toasts.set_child(self.nav)
            self.set_content(self.toasts)
            self.server: pairing.TeacherServer | None = None
            self.adder: Gio.Subprocess | None = None
            self.connect("close-request", self.on_close)
            self.show_home()

        # ---- navigation -------------------------------------------------------------------------------------

        def page(self, title: str, content: Gtk.Widget, tag: str, bar: Gtk.Widget | None = None,
                 can_pop: bool = True) -> Adw.NavigationPage:
            view = Adw.ToolbarView(content=content)
            view.add_top_bar(Adw.HeaderBar())
            if bar is not None:
                view.add_bottom_bar(bar)
            page = Adw.NavigationPage(child=view, title=title, tag=tag)
            page.set_can_pop(can_pop)
            return page

        def push(self, page: Adw.NavigationPage) -> None:
            """Show a page; one with the same tag in the stack (a search to search again, a wait that has an answer)
            goes, with the pages above it, without an animation."""

            stack = list(self.nav.get_navigation_stack())
            tags = [item.get_tag() for item in stack]
            if page.get_tag() in tags:
                self.nav.replace(stack[:tags.index(page.get_tag())] + [page])
            else:
                self.nav.push(page)

        def on_popped(self, _nav, page: Adw.NavigationPage) -> None:
            if page.get_tag() == "pairing":
                self.stop_pairing()
            # Its tag is free at once, while it slides away: going back and on again quickly shows the new page.
            page.set_tag(None)

        def bar(self, hint: Gtk.Label, buttons: list[Gtk.Button]) -> Gtk.Widget:
            """The bar at the bottom: a hint at the left, the buttons at the right, the main one right-most."""

            box = Gtk.Box(spacing=12)
            box.add_css_class("action-bar")
            hint.set_hexpand(True)
            hint.set_valign(Gtk.Align.CENTER)
            box.append(hint)
            for widget in buttons:
                box.append(widget)
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            outer.append(Gtk.Separator())
            outer.append(box)
            return outer

        def toast(self, message: str) -> None:
            self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(message), timeout=6))

        def show_home(self) -> None:
            self.stop_pairing()
            self.nav.replace([self.home_page()])

        def home_page(self) -> Adw.NavigationPage:
            state = system.read_state()
            role = state.get("role")
            if role == TEACHER:
                return self.home_teacher(state)
            if role == STUDENT:
                return self.home_student(state)
            return self.home_new()

        # ---- the first page ---------------------------------------------------------------------------------

        def home_new(self) -> Adw.NavigationPage:
            box = content_box()
            intro(box, _("The teacher's computer sees every student's screen, shows its own screen to the class, "
                         "locks the screens, sends files and turns the computers off."))
            section(box, _("Which computer is this?"))
            group = Adw.PreferencesGroup()
            group.add(chevron_row(_("Teacher's computer"),
                                  _("Installs Veyon and shows a code for pairing the students' computers."),
                                  self.teacher_setup))
            group.add(chevron_row(_("Student's computer"),
                                  _("Finds the teacher's computer on the network and pairs with its code."),
                                  self.student_find))
            box.append(group)
            hint = label(_("All the computers must be on the same network: the school's cable or Wi-Fi."),
                         "dim-label")
            hint.set_margin_top(8)
            box.append(hint)
            return self.page(_("Computer Lab"), scrolled(box), "home")

        def home_teacher(self, state: dict) -> Adw.NavigationPage:
            backend = state.get("backend", VEYON)
            software = backend_name(backend)
            box = content_box()
            intro(box, _("This is the teacher's computer of “{room}”, with {software}.").format(
                room=state.get("room", ""), software=software))
            section(box, _("Students' computers"))
            group = Adw.PreferencesGroup()
            group.add(chevron_row(_("Pair students' computers"),
                                  _("Shows the code that adds a student's computer to the room."),
                                  lambda: self.start_pairing(state)))
            box.append(group)
            section(box, _("This computer"))
            leave = Adw.PreferencesGroup()
            leave.add(chevron_row(_("Stop being the teacher's computer"),
                                  _("{software} stops on this computer. You can set it up again later.").format(
                                      software=software),
                                  lambda: self.confirm_leave(state)))
            box.append(leave)
            hint = label(_("{console} shows the students' screens, locks them and shows yours.").format(
                console=console_name(backend)), "dim-label")
            console = button(_("Open Veyon Master") if backend == VEYON else _("Open Epoptes"),
                             lambda: open_console(backend), primary=True)
            return self.page(_("Computer Lab"), scrolled(box), "home", bar=self.bar(hint, [console]))

        def home_student(self, state: dict) -> Adw.NavigationPage:
            teacher = state.get("teacher") or {}
            software = backend_name(state.get("backend", VEYON))
            box = content_box()
            intro(box, _("This is a student's computer of “{room}”, paired with the teacher's computer {name} "
                         "({host}).").format(room=state.get("room", ""), name=teacher.get("name", ""),
                                             host=teacher.get("host", "")))
            note = label(_("While it is in the lab, this computer does not lock, sleep or turn its screen off by "
                           "itself, so that the teacher always sees it."), "dim-label")
            note.set_margin_top(8)
            box.append(note)
            section(box, _("This computer"))
            group = Adw.PreferencesGroup()
            group.add(chevron_row(_("Pair again"), _("When the teacher's computer changed or was set up again."),
                                  self.student_find))
            group.add(chevron_row(_("Leave the computer lab"),
                                  _("{software} stops on this computer, and it locks and sleeps by itself as "
                                    "before.").format(software=software),
                                  lambda: self.confirm_leave(state)))
            box.append(group)
            return self.page(_("Computer Lab"), scrolled(box), "home")

        # ---- leaving ----------------------------------------------------------------------------------------

        def confirm_leave(self, state: dict) -> None:
            backend = state.get("backend", VEYON)
            software = backend_name(backend)
            if state.get("role") == TEACHER:
                heading = _("Stop being the teacher's computer?")
                body = (_("{software} stops on this computer and its key is deleted: if you set it up again, the "
                          "students' computers have to pair again.") if backend == VEYON else
                        _("{software} stops on this computer. You can set it up again later.")).format(
                    software=software)
                action = _("Stop being the teacher's computer")
            else:
                heading = _("Leave the computer lab?")
                body = _("{software} stops on this computer and it leaves “{room}”. You can pair it again "
                         "later.").format(software=software, room=state.get("room", ""))
                action = _("Leave the computer lab")
            dialog = Adw.MessageDialog(transient_for=self, heading=heading, body=body)
            dialog.add_response("cancel", _("Cancel"))
            dialog.add_response("leave", action)
            dialog.set_response_appearance("leave", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")
            dialog.connect("response", lambda _d, response: response == "leave" and self.run_helper(
                ["leave"], _("Leaving the computer lab"), lambda _event: self.left_lab(state)))
            dialog.present()

        def left_lab(self, state: dict) -> None:
            # This account's screen lock and sleep come back as they were; other accounts get theirs at their next
            # login (caramos-lab --session).
            threading.Thread(target=awake.restore, daemon=True).start()
            software = backend_name(state.get("backend", VEYON))
            if state.get("role") == STUDENT:
                description = _("{software} no longer runs on this computer, and it locks and sleeps by itself as "
                                "before.").format(software=software)
            else:
                description = _("{software} no longer runs on this computer. You can set it up again at any "
                                "time.").format(software=software)
            status = status_page("emblem-ok-symbolic", _("This computer left the computer lab"), description,
                                 [button(_("Done"), self.show_home, primary=True)])
            self.nav.replace([self.page(_("Computer Lab"), status, "left", can_pop=False)])

        # ---- root helper ------------------------------------------------------------------------------------

        def run_helper(self, args: list[str], title: str, on_done, stdin: bool = False) -> None:
            spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32, halign=Gtk.Align.CENTER)
            log = Gtk.TextView(editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                               top_margin=8, bottom_margin=8, left_margin=8, right_margin=8)
            log.add_css_class("caramos-log")
            expander = Gtk.Expander(label=_("Details"), child=Gtk.ScrolledWindow(
                child=log, min_content_height=160, hscrollbar_policy=Gtk.PolicyType.NEVER))
            details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
            details.append(spinner)
            details.append(Adw.Clamp(maximum_size=560, child=expander))
            status = status_page(None, title, _("Waiting for the password…"), [], child=details)
            progress = self.page(title, status, "progress", can_pop=False)
            self.push(progress)
            steps = {"install": _("Installing the software. It may take a few minutes."),
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
                        status.set_description(GLib.markup_escape_text(steps.get(event.get("text"),
                                                                                 event.get("text", ""))))
                    elif kind == "log":
                        append(event.get("text", ""))
                    elif kind in ("done", "error"):
                        result.update(event)
                        if kind == "error":
                            append(event.get("text", ""))
                stream.read_line_async(GLib.PRIORITY_DEFAULT, None, read)

            def finished(proc, task) -> None:
                proc.wait_finish(task)
                exit_status = proc.get_exit_status() if proc.get_if_exited() else 1
                if result.get("event") == "done":
                    on_done(result)
                    return
                spinner.set_visible(False)
                progress.set_can_pop(True)
                back = button(_("Back"), self.nav.pop)
                back.add_css_class("pill")
                if exit_status in (126, 127):
                    status.set_icon_name("dialog-information-symbolic")
                    status.set_title(_("Cancelled"))
                    status.set_description(GLib.markup_escape_text(_("The password window was closed, so nothing "
                                                                      "was changed.")))
                    expander.set_visible(False)
                else:
                    status.set_icon_name("dialog-error-symbolic")
                    status.set_title(_("The setup did not finish"))
                    status.set_description(GLib.markup_escape_text(_("Something went wrong. The details below say "
                                                                     "what.")))
                    expander.set_expanded(True)
                details.append(back)
                back.set_halign(Gtk.Align.CENTER)

            stream.read_line_async(GLib.PRIORITY_DEFAULT, None, read)

        # ---- teacher ----------------------------------------------------------------------------------------

        def teacher_setup(self) -> None:
            box = content_box()
            box.append(label(_("Teacher's computer"), "page-title"))
            box.append(label(_("The students' computers find this computer by the room's name.")))
            name = Adw.PreferencesGroup(margin_top=16)
            room = Adw.EntryRow(title=_("Room name"), text=default_room())
            name.add(room)
            box.append(name)
            wrong = label("", "error", visible=False)
            box.append(wrong)
            room.connect("changed", lambda *_a: (room.remove_css_class("error"), wrong.set_visible(False)))
            section(box, _("Software"))
            choices = Adw.PreferencesGroup()
            veyon = Gtk.CheckButton(active=True, valign=Gtk.Align.CENTER)
            epoptes = Gtk.CheckButton(group=veyon, valign=Gtk.Align.CENTER)
            for check, title, subtitle in (
                    (veyon, "Veyon",
                     _("See and control the students' screens, show the teacher's screen, lock screens, send files, "
                       "turn computers off. Works with Veyon on Windows too. Recommended for most labs.")),
                    (epoptes, "Epoptes",
                     _("Lighter, for computers with 2 GB of memory. The students' computers connect to the "
                       "teacher's by themselves."))):
                row = Adw.ActionRow(title=title, subtitle=GLib.markup_escape_text(subtitle),
                                    activatable_widget=check)
                row.set_subtitle_lines(4)
                row.add_prefix(check)
                choices.add(row)
            box.append(choices)
            hint = label(_("Setting up takes a few minutes and needs the administrator's password."), "dim-label")

            def start(*_args) -> None:
                name_text = room.get_text().strip()
                if not pairing.valid_room(name_text):
                    wrong.set_label(_("Use letters, digits, spaces or dashes for the room name (up to 40)."))
                    wrong.set_visible(True)
                    room.add_css_class("error")
                    return
                backend = VEYON if veyon.get_active() else EPOPTES
                self.run_helper(["teacher", "--backend", backend, "--room", name_text],
                                _("Setting up the teacher's computer"),
                                lambda _event: self.teacher_ready())

            room.connect("entry-activated", start)
            go = button(_("Set up this computer"), start, primary=True)
            self.push(self.page(_("Teacher's computer"), scrolled(box), "teacher-setup", bar=self.bar(hint, [go])))

        def teacher_ready(self) -> None:
            state = system.read_state()
            self.nav.replace([self.home_page()])
            self.start_pairing(state)

        def start_pairing(self, state: dict) -> None:
            backend, room = state.get("backend", VEYON), state.get("room", default_room())
            key = system.teacher_key(backend)
            if key is None:
                self.toast(_("The teacher's key is missing: set this computer up again."))
                return
            box = content_box()
            box.append(label(_("Pair students' computers"), "page-title"))
            box.append(label(_("On each student's computer open Computer Lab, choose Student's computer, then "
                               "“{room}”, and type this code.").format(room=room)))
            code = label(pairing.spaced(pairing.pairing_code(key)), "caramos-lab-code")
            code.set_margin_top(8)
            box.append(code)
            box.append(label(_("This computer is {name}, at {address}.").format(
                name=system.hostname(), address=system.local_ip() or "?"), "dim-label"))
            section(box, _("Paired computers"))
            group = Adw.PreferencesGroup()
            box.append(group)
            empty = Adw.ActionRow(title=_("No computer yet."))
            empty.add_css_class("dim-label")
            group.add(empty)
            count = label(_("Keep this page open while the students pair."), "dim-label")
            console = button(_("Open Veyon Master") if backend == VEYON else _("Open Epoptes"),
                             lambda: open_console(backend), primary=True)
            done = button(_("Done"), lambda: self.nav.pop())
            self.push(self.page(_("Pair students' computers"), scrolled(box), "pairing",
                                bar=self.bar(count, [done, console])))
            rows: dict[str, Adw.ActionRow] = {}

            def show_student(student: pairing.Student, added: bool) -> None:
                if empty.get_parent() is not None:
                    group.remove(empty)
                row = rows.get(student.mac)
                if row is None:
                    row = Adw.ActionRow(title=GLib.markup_escape_text(student.name))
                    rows[student.mac] = row
                    group.add(row)
                row.set_subtitle(GLib.markup_escape_text(student_line(student, added)))
                count.set_label(ngettext("{count} computer paired.", "{count} computers paired.",
                                         len(rows)).format(count=len(rows)))

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
            spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32, halign=Gtk.Align.CENTER)
            status = status_page(None, _("Looking for the teacher's computer on the network…"), "", [],
                                 child=spinner)
            searching = self.page(_("Student's computer"), status, "student-find")
            stack = list(self.nav.get_navigation_stack())
            if len(stack) > 1 and stack[-1].get_tag() not in ("home", "student-find"):
                # Pair again after a code or a result page: back to a fresh search above the first page.
                self.nav.replace([stack[0], searching])
            else:
                self.push(searching)

            def found(teachers: list[pairing.Teacher]) -> bool:
                if not teachers:
                    page = status_page("system-search-symbolic", _("No teacher's computer found"),
                                       _("On the teacher's computer open Computer Lab and keep its pairing page "
                                         "open. All the computers must be on the same network."),
                                       [button(_("Search again"), self.student_find, primary=True)])
                    self.push(self.page(_("Student's computer"), page, "student-find"))
                    return False
                box = content_box()
                box.append(label(_("Choose your room"), "page-title"))
                box.append(label(_("These teachers' computers have their pairing page open.")))
                group = Adw.PreferencesGroup(margin_top=16)
                for teacher in teachers:
                    group.add(chevron_row(teacher.room, teacher_line(teacher), lambda t=teacher: self.student_code(t)))
                box.append(group)
                hint = label(_("Not in the list? Open the pairing page on the teacher's computer."), "dim-label")
                again = button(_("Search again"), self.student_find)
                self.push(self.page(_("Student's computer"), scrolled(box), "student-find",
                                    bar=self.bar(hint, [again])))
                return False

            threading.Thread(target=lambda: GLib.idle_add(found, pairing.discover()), daemon=True).start()

        def student_code(self, teacher: pairing.Teacher) -> None:
            box = content_box()
            box.append(label(_("Pair with “{room}”").format(room=teacher.room), "page-title"))
            box.append(label(_("Type the 6-digit code shown on the teacher's computer.")))
            group = Adw.PreferencesGroup(margin_top=16)
            entry = Adw.EntryRow(title=_("Pairing code"))
            entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
            group.add(entry)
            box.append(group)
            wrong = label("", "error", visible=False)
            box.append(wrong)
            entry.connect("changed", lambda *_a: (entry.remove_css_class("error"), wrong.set_visible(False)))
            hint = label(_("Setting up takes a few minutes and needs the administrator's password."), "dim-label")

            def problem(text: str) -> None:
                wrong.set_label(text)
                wrong.set_visible(True)
                entry.add_css_class("error")

            def fetched(key: bytes | None, error_text: str | None) -> bool:
                go.set_sensitive(True)
                if key is None:
                    problem(error_text or "")
                    return False
                if not pairing.check_code(key, entry.get_text()):
                    problem(_("The code does not match. Check the code on the teacher's computer."))
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
                    problem(_("The code has 6 digits."))
                    return
                go.set_sensitive(False)

                def work() -> None:
                    try:
                        key = pairing.fetch_key(teacher)
                    except pairing.PairingError:
                        GLib.idle_add(fetched, None, _("The teacher's computer does not answer. Keep its pairing page "
                                                       "open and try again."))
                        return
                    GLib.idle_add(fetched, key, None)

                threading.Thread(target=work, daemon=True).start()

            go = button(_("Pair"), start, primary=True)
            entry.connect("entry-activated", start)
            self.push(self.page(_("Pairing code"), scrolled(box), "student-code", bar=self.bar(hint, [go])))

        def student_register(self, teacher: pairing.Teacher) -> None:
            def work() -> None:
                # Veyon sees and controls the session on screen: no screensaver, lock or sleep in its way (awake.py).
                awake.apply()
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
                software = backend_name(teacher.backend)
                if ok or teacher.backend == EPOPTES:
                    status = status_page("emblem-ok-symbolic", _("This computer is in “{room}”").format(
                        room=teacher.room),
                        _("The teacher can see it now in {software}. While it is in the lab, it does not lock, sleep "
                          "or turn its screen off by itself.").format(software=software),
                        [button(_("Done"), self.show_home, primary=True)])
                else:
                    status = status_page("dialog-warning-symbolic", _("Not in the room's list yet"),
                                         _("The teacher's computer did not add it to the room's list: keep the "
                                           "pairing page open on the teacher's computer and pair again."),
                                         [button(_("Done"), self.show_home),
                                          button(_("Pair again"), self.student_find, primary=True)])
                self.nav.replace([self.home_page(), self.page(_("Student's computer"), status, "student-done",
                                                              can_pop=False)])
                return False

            threading.Thread(target=work, daemon=True).start()

    return Window()


def open_window() -> int:
    from caramos_ota import adw_style, gtk_renderer

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
            adw_style.apply()
            css = Gtk.CssProvider()
            css.load_from_string(CSS)
            Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), css,
                                                      Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            window = build_window(app)
        window.present()

    application.connect("activate", activate)
    return application.run([sys.argv[0]])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caramos-lab", description=_("Computer Lab"))
    parser.add_argument("--status", action="store_true", help="print this computer's lab state as JSON")
    parser.add_argument("--session", action="store_true",
                        help="at login: keep a lab student's account from locking or sleeping, or give it back its "
                             "settings after the computer left the lab")
    args = parser.parse_args(argv)
    if args.status:
        print(json.dumps(system.read_state(), ensure_ascii=False, indent=1))
        return 0
    if args.session:
        print(awake.at_login(system.read_state().get("role")))
        return 0
    return open_window()

"""The employee machine's window: pairing with the admin's code or with an enrolment file (found on a USB drive or
picked); the states of a machine waiting for approval, enrolling at its first boot, or removed by the company. Once
paired, the connection's state, "Nhờ IT hỗ trợ" and "Yêu cầu của bạn", the page "Máy này do công ty quản lý" (only
the features in effect for this machine, and what the company never sees), preparing a disk image, and leaving."""

from __future__ import annotations

import datetime
import json
import os
import re
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import AGENT_BOX_KEY, AGENT_STATE, ENROLL_ON_BOOT, OS_MACHINE_ID, client, protocol, role, text, \
    transparency  # noqa: E402
from ..i18n import _  # noqa: E402
from . import common  # noqa: E402
from .helper import in_thread, run_helper  # noqa: E402

REFRESH_SECONDS = 5
ENROLL_FILE = "caramos-business-enroll.json"
MEDIA = Path("/media")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def when_text(value: Any) -> tuple[str, str]:
    """("HH:MM", "D/M") of an ISO time, for the removal notice."""

    try:
        then = datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return "", ""
    then = then.astimezone() if then.tzinfo else then
    return f"{then:%H:%M}", f"{then.day}/{then.month}"


def found_enrolment_files(user: str | None = None) -> list[Path]:
    """caramos-business-enroll.json one level below each of the user's mounts (USB drives)."""

    user = user or os.environ.get("USER") or ""
    try:
        mounts = sorted((MEDIA / user).iterdir()) if user else []
    except OSError:
        return []
    found = []
    for mount in mounts:
        candidate = mount / ENROLL_FILE
        try:
            if candidate.is_file():
                found.append(candidate)
        except OSError:
            continue
    return found


def read_enrolment_file(path: Path) -> dict[str, Any]:
    """The file, checked as the helper checks it; raises ProtocolError or OSError."""

    if path.stat().st_size > protocol.MAX_BODY:
        raise protocol.ProtocolError(_("This is not an enrolment file."))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise protocol.ProtocolError(_("This is not an enrolment file.")) from exc
    return protocol.validate_enroll_file(data)


def reboot_dialog(window: Any, heading: str, body: str, action: str, command: list[str]) -> None:
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("later", _("Later"))
    dialog.add_response("now", action)
    dialog.set_response_appearance("now", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("now")
    dialog.set_close_response("later")
    dialog.connect("response", lambda _dialog, answer: answer == "now" and Gio.Subprocess.new(
        command, Gio.SubprocessFlags.NONE))
    dialog.present(window)


class EmployeeView(Adw.Bin):
    def __init__(self, window: Any) -> None:
        super().__init__()
        self.window = window
        self.paired = read_json(AGENT_STATE / "admin.json")
        self.nav = Adw.NavigationView()
        self.timers: list[int] = []
        self.connect("unrealize", lambda _view: [GLib.source_remove(timer) for timer in self.timers])
        if isinstance(self.paired, dict) and client.cloned(self.paired, OS_MACHINE_ID, AGENT_STATE / "clone.json"):
            root = self.clone_page()
        elif client.paired_by_older_version(self.paired, AGENT_BOX_KEY):
            root = self.pair_again_page(_("This machine needs pairing again"),
                                        _("It was paired by an older version of CaramOS Business. Pair it again to "
                                          "keep taking the company's settings."))
        elif isinstance(self.paired, dict):
            root = self.status_page()
        elif ENROLL_ON_BOOT.exists() and not client.os_machine_id(OS_MACHINE_ID):
            root = self.ready_page()  # the prepared model machine itself, before its disk is copied
        elif ENROLL_ON_BOOT.exists():
            root = self.enrolling_page()
        else:
            root = self.pairing_page()
        self.nav.add(Adw.NavigationPage(title=_("CaramOS Business"), child=common.toolbar(root)))
        self.set_child(self.nav)

    def every(self, seconds: int, work: Any) -> None:
        self.timers.append(GLib.timeout_add_seconds(seconds, lambda: work() or True))

    # - a cloned disk -

    def clone_page(self) -> Gtk.Widget:
        """This disk was cloned from a paired machine: it does nothing for the company until it is paired again."""

        return self.pair_again_page(
            _("This machine is a copy of a paired machine"),
            _("Its disk was cloned from another employee machine, so it does nothing for the company until it is paired "
              "again as a machine of its own."))

    def pair_again_page(self, title: str, description: str) -> Gtk.Widget:
        again = Gtk.Button(label=_("Pair it again"))
        again.add_css_class("suggested-action")
        again.connect("clicked", lambda _button: self.pair_again())
        return common.status_page("dialog-warning-symbolic", title, description, again)

    def pair_again(self) -> None:
        run_helper(["leave"], lambda ok, result: self.window.show_page() if ok else
                   self.window.toast(result.get("error", "")))

    # - a prepared model machine, and enrolling at the first boot of a copied disk -

    def ready_page(self) -> Gtk.Widget:
        shut = Gtk.Button(label=_("Shut down"))
        shut.add_css_class("suggested-action")
        shut.connect("clicked", lambda _button: Gio.Subprocess.new(["systemctl", "poweroff"],
                                                                   Gio.SubprocessFlags.NONE))
        return common.status_page("drive-harddisk-symbolic", _("Ready for its disk to be copied"),
                                  _("Shut this machine down and copy its disk. Do not start it again before: started "
                                    "once, it would join the company itself."), shut)

    def enrolling_page(self) -> Gtk.Widget:
        page = common.status_page("network-transmit-receive-symbolic", _("Waiting for the admin machine to join "
                                                                           "by itself"),
                                  _("This copy of a prepared disk joins the company as soon as the admin machine "
                                    "answers. Keep it on the company's network; nothing else is needed."))
        spinner = Gtk.Spinner(spinning=True, width_request=32, height_request=32, halign=Gtk.Align.CENTER)
        page.set_child(spinner)

        def check() -> None:
            if (AGENT_STATE / "admin.json").exists() or not ENROLL_ON_BOOT.exists():
                self.window.show_page()

        self.every(REFRESH_SECONDS, check)
        return page

    # - paired -

    def status_page(self) -> Gtk.Widget:
        body = common.page_box()
        admin_name = self.paired.get("admin_name", "?")
        self.approval = read_json(AGENT_STATE / "approval.json") or {}
        pending = self.approval.get("state") == "pending"
        if pending:
            waiting = common.group()
            row = common.row(_("Waiting for the admin machine to approve this machine"),
                             _("The company approves each new machine. Until then this machine takes nothing from "
                               "it."))
            row.add_prefix(Gtk.Spinner(spinning=True, valign=Gtk.Align.CENTER))
            waiting.add(row)
            body.append(waiting)
        connection = common.group(_("Connected to %s") % admin_name,
                                  _("This machine takes the company's settings from that admin machine."))
        self.status_rows = common.Rows(connection)
        self.connection = connection
        body.append(connection)
        managed = common.group()
        row = common.row(_("This machine is managed by the company"),
                         _("What the company has turned on here, and what it never sees."), activatable=True)
        row.connect("activated", lambda _row: self.show_managed())
        managed.add(row)
        body.append(managed)
        if not pending:
            help_group = common.group(_("Ask IT for help"), _("Send a short note to the company's IT. They see it with "
                                                              "this machine's name and contact you."))
            requests = common.row(_("Your requests"), _("What you asked IT, and their answers."), activatable=True)
            requests.connect("activated", lambda _row: self.show_requests())
            help_group.add(requests)
            ask = common.button(_("Ask IT for help…"), self.ask_help, "suggested-action")
            ask.set_halign(Gtk.Align.START)
            ask.set_margin_top(12)
            help_group.add(ask)
            body.append(help_group)
        body.append(self.image_group())
        leave_group = common.group(_("Leave the admin machine"))
        leave_group.add(common.row(_("The company's settings are taken off this machine. Files on the server stay "
                                     "there.")))
        leave = common.button(_("Leave the company's admin machine…"), self.leave, "destructive-action")
        leave.set_halign(Gtk.Align.START)
        leave.set_margin_top(12)
        leave_group.add(leave)
        body.append(leave_group)
        self.update_status()

        def tick() -> None:
            state = (read_json(AGENT_STATE / "approval.json") or {}).get("state")
            paired = (AGENT_STATE / "admin.json").exists()
            if state != self.approval.get("state") or not paired:
                self.window.show_page()  # approved, or removed by the company
                return
            self.update_status()

        self.every(REFRESH_SECONDS, tick)
        return common.scrolled(common.clamp(body))

    def update_status(self) -> None:
        self.status_rows.clear()
        policy = read_json(AGENT_STATE / "policy.json") or {}
        settings, _admin = transparency.stored_settings()
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        status = read_json(runtime / "caramos-business" / "status.json") or {}
        serial = policy.get("serial") if isinstance(policy, dict) else None
        self.status_rows.add(common.property_row(_("Settings received"), _("version %d") % serial if serial else
                                                 _("not yet")))
        if settings.get("wallpaper"):
            self.status_rows.add(common.property_row(_("Wallpaper"), {
                "applied": _("the company's"), "failed": _("could not be set"),
                "off": _("your own")}.get(status.get("wallpaper"), _("not yet"))))
        if settings.get("folders"):
            self.status_rows.add(common.property_row(_("Desktop and Documents"), {
                "server": _("on the server"), "local": _("on this machine for now"),
                "failed": _("could not reach the server"), "off": _("on this machine")}.get(status.get("folders"),
                                                                                          _("not yet"))))
        freezing = freeze_text(bool((settings.get("shared") or {}).get("freeze")), frozen_now())
        if freezing:
            self.status_rows.add(common.property_row(_("Freezing"), freezing))
        if status.get("detail"):
            self.status_rows.add(common.property_row(_("Detail"), str(status["detail"])))

    def show_managed(self) -> None:
        settings, admin_name = transparency.stored_settings()
        body = common.page_box()
        body.append(common.label(_("Your company manages this machine with CaramOS Business, from the machine %s. "
                                   "Only what is listed here is on.") % (admin_name or "?"), "paragraph"))
        doing = common.group(_("What the company does here"))
        for title, sentence in transparency.always_items() + transparency.managed_items(settings):
            doing.add(common.row(title, sentence))
        body.append(doing)
        never = common.group(_("What the company cannot see"))
        for item in transparency.never_items():
            never.add(common.row(item))
        body.append(never)
        body.append(common.secondary(_("Personal Data Protection Law 91/2025/QH15, article 25: staff must know the "
                                       "measures used on their machines. Ask your company if something is unclear."),
                                     "paragraph"))
        page = Adw.NavigationPage(title=_("Managed by the company"),
                                  child=common.toolbar(common.scrolled(common.clamp(body)),
                                                       _("Managed by the company")))
        self.nav.push(page)

    def show_requests(self) -> None:
        page = RequestsPage(self)
        self.nav.push(page.navigation_page)

    def ask_help(self) -> None:
        from .prompts import HelpRequest

        def finished(sent: bool) -> None:
            if sent:
                self.window.toast(_("Sent to IT."))

        HelpRequest(self.window.get_application(), self.window, finished)

    def leave(self) -> None:
        def done(ok: bool, result: dict[str, Any]) -> None:
            if not ok:
                self.window.toast(result.get("error", ""))
                return
            self.window.show_page()
            if result.get("reboot"):
                reboot_dialog(self.window, _("Restart to finish"),
                              _("The machine needs a restart to remove the company's settings for good."),
                              _("Restart"), ["systemctl", "reboot"])

        def go() -> None:
            run_helper(["leave"], done)

        common.confirm(self.window, _("Leave the admin machine?"),
                       _("What the company set is taken off: Desktop and Documents come back to this machine within "
                         "half a minute, the wallpaper stays as it is. Files on the server stay there."),
                       _("Leave"), go, destructive=True)

    # - preparing a disk image -

    def image_group(self) -> Adw.PreferencesGroup:
        target = common.group(_("A model machine for a computer lab"))
        row = common.row(_("Prepare a disk image…"),
                         _("Before copying this machine's disk to others: it forgets who it is, and each copy joins the "
                           "company by itself."), activatable=True)
        row.connect("activated", lambda _row: self.prepare_image())
        target.add(row)
        return target

    def prepare_image(self) -> None:
        choice: dict[str, Path | None] = {"file": None}
        found = found_enrolment_files()
        if found:
            choice["file"] = found[0]
        file_row = common.row(_("Enrolment file"), str(choice["file"]) if choice["file"] else
                              _("None: each copy will be paired with a code"), activatable=True)

        def pick() -> None:
            self.pick_file(lambda path: (choice.__setitem__("file", path), file_row.set_subtitle(str(path))))

        file_row.connect("activated", lambda _row: pick())

        def go() -> None:
            def done(ok: bool, result: dict[str, Any]) -> None:
                if not ok:
                    self.window.toast(result.get("error", _("Could not prepare this machine.")))
                    return
                self.window.show_page()
                reboot_dialog(self.window, _("Shut it down now and copy its disk"),
                              _("Do not start this machine again before its disk is copied: started once, it would "
                                "join the company itself, and its copies would share its place.") if result.get(
                                  "enroll") else _("Do not start this machine again before its disk is copied."),
                              _("Shut down"), ["systemctl", "poweroff"])

            stdin = json.dumps({"enroll_file": str(choice["file"]) if choice["file"] else None})
            run_helper(["prepare-image"], done, stdin)

        details = Adw.ExpanderRow(title=_("Details"), use_markup=False)
        details.add_row(common.row(_("What this machine forgets"),
                                   _("Its pairing, its machine id (/etc/machine-id) and its SSH host keys. The "
                                     "enrolment file is kept for the copies' first start.")))
        common.form_dialog(self.window, _("Prepare a disk image"),
                           _("This machine leaves the company and forgets who it is. With an enrolment file, each copy "
                             "of its disk joins the company at its first start. Afterwards, shut it down and copy its "
                             "disk."), [file_row, details], _("Prepare"), go)

    def pick_file(self, chosen: Any) -> None:
        filters = Gio.ListStore.new(Gtk.FileFilter)
        enrolment = Gtk.FileFilter(name=_("Enrolment files"))
        enrolment.add_pattern("*.json")
        filters.append(enrolment)
        dialog = Gtk.FileDialog(title=_("Choose the enrolment file"), filters=filters)

        def opened(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                path = Path(source.open_finish(result).get_path())
            except (GLib.Error, TypeError):
                return
            chosen(path)

        dialog.open(self.window, None, opened)

    # - pairing -

    def pairing_page(self) -> Gtk.Widget:
        body = common.page_box()
        removed = read_json(AGENT_STATE / "removed.json") if role() else None
        failed = read_json(AGENT_STATE / "enroll-failed.json")
        if isinstance(removed, dict):
            hour, day = when_text(removed.get("time"))
            notice = common.group()
            values = {"admin": removed.get("admin_name") or "?", "hour": hour, "day": day}
            if (AGENT_STATE / "leave-pending.json").exists():
                # A frozen machine: the disk still holds the company's settings until the next restart (PROTOCOL.md
                # part 3, "Leaving and removal of a frozen machine").
                text = _("The company removed this machine from the admin machine %(admin)s at %(hour)s on %(day)s. "
                         "Restart the machine to take the company's settings off it for good.") % values
                notice.set_header_suffix(common.button(_("Restart"), lambda: reboot_dialog(
                    self.window, _("Restart to finish"),
                    _("The machine needs a restart to remove the company's settings for good."), _("Restart"),
                    ["systemctl", "reboot"])))
            else:
                text = _("The company removed this machine from the admin machine %(admin)s at %(hour)s on %(day)s. "
                         "The company's settings have been taken off this machine.") % values
            notice.add(common.row(_("The company removed this machine"), text, icon="dialog-information-symbolic"))
            body.append(notice)
        elif isinstance(failed, dict):
            notice = common.group()
            notice.add(common.row(_("The enrolment file did not work"),
                                  _("It has expired or been used up: pair this machine with a code."),
                                  icon="dialog-warning-symbolic"))
            body.append(notice)
        self.file_group = common.group(_("Enrolment file"), _("If IT gave you a USB drive with an enrolment file, plug "
                                                              "it in: it is found by itself."))
        self.file_group.set_header_suffix(common.button(_("Choose a file…"), lambda: self.pick_file(self.confirm_file)))
        self.file_rows = common.Rows(self.file_group)
        self.found_group = common.group(_("Find the admin machine"),
                                        _("On the admin machine, press Add machines: it shows a code. Both machines "
                                          "must be on the company's network."))
        self.found_group.set_header_suffix(common.button(_("Search again"), self.search))
        self.found_rows = common.Rows(self.found_group)
        code_group = common.group()
        self.code = common.entry_row(_("The 6-digit code on the admin machine"), activates=self.pair)
        code_group.add(self.code)
        self.connect_button = common.button(_("Connect"), self.pair, "suggested-action")
        self.connect_button.set_sensitive(False)
        self.connect_button.set_halign(Gtk.Align.END)
        # The usual way first: the code. An enrolment file found on a USB drive goes above it.
        parts = [self.found_group, code_group, self.connect_button, self.file_group]
        if found_enrolment_files():
            parts = [self.file_group] + parts[:-1]
        for part in parts:
            body.append(part)
        body.append(self.image_group())
        self.choice: dict[str, Any] | None = None
        self.search()
        self.scan_files()
        self.monitor = Gio.VolumeMonitor.get()
        self.monitor_handler = self.monitor.connect("mount-added", lambda *_args: GLib.timeout_add_seconds(
            1, lambda: self.scan_files() and False))
        self.connect("unrealize", lambda _view: self.monitor.disconnect(self.monitor_handler))
        return common.scrolled(common.clamp(body))

    def scan_files(self) -> None:
        self.file_rows.clear()
        found = found_enrolment_files()
        if not found:
            self.file_rows.add(common.row(_("No enrolment file found")))
            return
        for path in found:
            try:
                data = read_enrolment_file(path)
            except (OSError, protocol.ProtocolError) as exc:
                self.file_rows.add(common.row(path.parent.name, str(exc)))
                continue
            row = common.row(_("From %s") % data["admin_name"], enrolment_sentence(data))
            row.add_suffix(common.button(_("Join with this file…"), lambda item=path: self.confirm_file(item),
                                         "suggested-action"))
            self.file_rows.add(row)

    def confirm_file(self, path: Path) -> None:
        try:
            data = read_enrolment_file(path)
        except (OSError, protocol.ProtocolError) as exc:
            self.window.toast(str(exc))
            return
        details = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        details.add_css_class("boxed-list")
        details.append(common.property_row(_("Admin machine"), data["admin_name"]))
        details.append(common.property_row(_("Department"), data.get("department_name") or _("none")))
        details.append(common.property_row(_("Works until"), text.vn_date(data["expires"][:10])))
        expander = Adw.ExpanderRow(title=_("Details"), use_markup=False)
        expander.add_row(common.property_row(_("Admin machine's fingerprint"), " ".join(
            re.findall(".{4}", data["fingerprint"]))))
        expander.add_row(common.property_row(_("Address"), data["admin_url"]))
        details.append(expander)
        dialog = Adw.AlertDialog(heading=_("Join the company with this file?"),
                                 body=_("This machine will take the settings of the company's admin machine. Check "
                                        "that the name below is your company's."))
        dialog.set_extra_child(details)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("ok", _("Join"))
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_close_response("cancel")

        def response(_dialog: Adw.AlertDialog, answer: str) -> None:
            if answer != "ok":
                return

            def done(ok: bool, result: dict[str, Any]) -> None:
                if ok:
                    self.window.show_page()
                    self.window.toast(_("Connected: the company's settings come within a minute.") if
                                      result.get("state") != "pending" else
                                      _("Connected: waiting for the admin machine to approve this machine."))
                else:
                    self.window.toast(result.get("error", _("Could not connect.")))

            run_helper(["pair-file", str(path)], done)

        dialog.connect("response", response)
        dialog.present(self.window)

    def search(self) -> None:
        self.found_rows.clear()
        self.found_rows.add(common.row(_("Searching…")))

        def done(found: list[dict[str, Any]] | None, error: Exception | None) -> None:
            self.found_rows.clear()
            if not found:
                self.found_rows.add(common.row(_("No admin machine answered"),
                                               _("Check that it is on, on the same network, and press Search again.")))
                return
            first = None
            for info in found:
                check = Gtk.CheckButton(group=first, valign=Gtk.Align.CENTER)
                first = first or check
                status = _("adding machines now") if info["pairing"] else _("not adding machines now")
                row = common.row(info["name"], f"{info['ip']}, {status}")
                row.add_prefix(check)
                row.set_activatable_widget(check)
                check.connect("toggled", lambda button, item=info: button.get_active() and self.choose(item))
                self.found_rows.add(row)
            first.set_active(True)

        in_thread(lambda: client.discover(2.0), done)

    def choose(self, info: dict[str, Any]) -> None:
        self.choice = info
        self.connect_button.set_sensitive(True)

    def pair(self) -> None:
        if not self.choice:
            return
        code = re.sub(r"\D", "", self.code.get_text())
        if len(code) != 6:
            self.window.toast(_("The code has 6 digits."))
            return
        self.connect_button.set_sensitive(False)

        def done(ok: bool, answer: dict[str, Any]) -> None:
            self.connect_button.set_sensitive(True)
            if ok:
                self.window.show_page()
                self.window.toast(_("Connected: the company's settings come within a minute.") if
                                  answer.get("state") != "pending" else
                                  _("Connected: waiting for the admin machine to approve this machine."))
            else:
                self.window.toast(answer.get("error", _("Could not connect.")))

        # The code is checked with SPAKE2 by the helper: it never travels, and a wrong one is refused there.
        run_helper(["pair", self.choice["ip"], code], done)


def private_group(uid: int) -> bool:
    """Whether the user's primary group is their own (PROTOCOL.md part 3, "Helpdesk tickets"): it has the user's name,
    lists no members, and no other account has it as its primary group. Only then does the agent write their files."""

    import grp
    import pwd

    try:
        user = pwd.getpwuid(uid)
        group = grp.getgrgid(user.pw_gid)
    except KeyError:
        return False
    if group.gr_name != user.pw_name or group.gr_mem:
        return False
    return not any(other.pw_gid == user.pw_gid and other.pw_uid != uid for other in pwd.getpwall())


def read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def frozen_now(mounts: Path = Path("/proc/mounts")) -> bool:
    """Whether / is overlayroot in this boot (the machine is frozen now)."""

    return any(line.split()[1:3] == ["/", "overlay"] for line in read_lines(mounts))


def freeze_text(wanted: bool, frozen: bool) -> str | None:
    """The "Đóng băng" row: on, from the next restart, or still on after the company turned freezing off, since the
    machine stays frozen until it restarts (PROTOCOL.md part 3, "Freeze": the window says so; 0.3.1 dropped the row
    then). None when the machine neither is nor will be frozen."""

    if wanted:
        return _("on: changes are undone at restart") if frozen else _("from the next restart")
    if frozen:
        return _("the company turned it off; the machine stays frozen until the next restart")
    return None


def enrolment_sentence(data: dict[str, Any]) -> str:
    parts = [_("department %s") % data["department_name"] if data.get("department_name") else _("no department"),
             _("works until %s") % text.vn_date(data["expires"][:10])]
    return text.sentence(parts)


class RequestsPage:
    """"Yêu cầu của bạn": this user's tickets, from the file the agent writes for them."""

    def __init__(self, view: EmployeeView) -> None:
        self.view = view
        self.body = common.page_box()
        self.navigation_page = Adw.NavigationPage(title=_("Your requests"), child=common.toolbar(
            common.scrolled(common.clamp(self.body)), _("Your requests")))
        self.shown: Any = None
        self.refresh()
        timer = GLib.timeout_add_seconds(REFRESH_SECONDS, lambda: self.refresh() or True)
        self.navigation_page.connect("hidden", lambda _page: GLib.source_remove(timer))

    def path(self) -> Path:
        return AGENT_STATE / "tickets" / f"{os.getuid()}.json"

    def refresh(self) -> None:
        data = read_json(self.path()) or {}
        tickets = sorted((item for item in data.get("tickets") or [] if isinstance(item, dict)),
                         key=lambda item: item.get("created", ""), reverse=True)
        if tickets == self.shown:
            return
        self.shown = tickets
        child = self.body.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.body.remove(child)
            child = following
        if not tickets and not self.path().exists() and not private_group(os.getuid()):
            self.body.append(common.status_page(
                "help-browser-symbolic", _("Your requests cannot be shown on this machine"),
                _("Your account has no group of its own, so this machine cannot keep your requests where only you can "
                  "read them. IT still gets what you send with Ask IT for help; ask them to answer by phone, or to give "
                  "your account a group of its own.")))
            return
        if not tickets:
            ask = Gtk.Button(label=_("Ask IT for help…"))
            ask.add_css_class("suggested-action")
            ask.connect("clicked", lambda _button: self.view.ask_help())
            self.body.append(common.status_page("help-browser-symbolic", _("No request yet"),
                                                _("When you ask IT for help, your request and their answers show here, "
                                                  "a few minutes after you send it."), ask))
            return
        target = common.group(_("Your requests"), _("Newest first. IT's answers come here by themselves."))
        for item in tickets:
            status = {"new": _("New"), "working": _("Being handled"), "waiting": _("Waiting for your answer"),
                      "done": _("Finished")}.get(item.get("status"), "")
            expander = Adw.ExpanderRow(title=item.get("note") or _("No note."), use_markup=False,
                                       subtitle=text.sentence([item.get("id", ""),
                                                               _("sent %s") % text.clock(item.get("created", "")),
                                                               status]))
            updates = item.get("updates") or []
            if not updates:
                expander.add_row(common.row(_("No answer yet")))
            for update in updates:
                words = update.get("text") or {"new": _("New"), "working": _("Being handled"),
                                               "waiting": _("Waiting for your answer"),
                                               "done": _("Finished")}.get(update.get("status"), "")
                expander.add_row(common.row(words, text.clock(update.get("time", ""))))
            target.add(expander)
        self.body.append(target)

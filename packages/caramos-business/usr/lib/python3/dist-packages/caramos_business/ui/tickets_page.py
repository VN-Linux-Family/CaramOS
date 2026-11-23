"""Phiếu hỗ trợ (PROTOCOL.md part 3, "Helpdesk tickets"): the tickets the employees' "Nhờ IT hỗ trợ" makes, by status;
each ticket with its machine, notes (public ones reach the employee, internal ones stay here), assignee and status;
remote help from a ticket; and the month's tickets as an XLSX."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import protocol, reports, text, tickets  # noqa: E402
from ..i18n import _, ngettext  # noqa: E402
from . import common  # noqa: E402
from .admin_window import Context, Page  # noqa: E402

FILTERS = ("open", "new", "working", "waiting", "done", "all")


def filter_titles() -> list[str]:
    return [_("Not done yet"), _("New"), _("Being handled"), _("Waiting for the employee"), _("Finished"),
            _("All tickets")]


def status_titles() -> list[str]:
    return [_("New"), _("Being handled"), _("Waiting for the employee"), _("Finished")]


def status_title(status: str) -> str:
    return dict(zip(protocol.TICKET_STATES, status_titles())).get(status, status)


class TicketsPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx, _("Help tickets"), "tickets")
        self.filter = "open"
        self.header.pack_end(common.button(_("Month report…"), self.month_report))
        self.built = False

    def build(self) -> None:
        self.clear()
        self.body.append(common.label(_("Each “Ask IT for help” from an employee becomes a ticket. Answer it here: the "
                                        "employee sees the status and your public notes under “Your requests”."),
                                      "paragraph"))
        drop = Gtk.DropDown.new_from_strings(filter_titles())
        drop.set_halign(Gtk.Align.START)
        drop.connect("notify::selected", lambda widget, _p: self.filtered(FILTERS[widget.get_selected()]))
        self.body.append(drop)
        self.list_group = common.group()
        self.list_rows = common.Rows(self.list_group)
        self.body.append(self.list_group)
        self.built = True

    def refresh(self, force: bool = False) -> None:
        if not self.built:
            self.build()
        if force:
            self.forget_signatures()
        items = sorted(self.ctx.tickets["tickets"], key=lambda item: item.get("created", ""), reverse=True)
        shown = []
        for item in items:
            status = item.get("status", "new")
            if self.filter == "open" and status == "done" or self.filter not in ("open", "all") and \
                    status != self.filter:
                continue
            machine = self.ctx.machine_name(item.get("machine_id", ""))
            who = _("%(user)s on %(machine)s") % {"user": item["user"], "machine": machine} if item.get("user") \
                else machine
            subtitle = text.sentence([item.get("id", ""), who, text.ago(item.get("created", "")),
                                      status_title(status), item.get("assignee") and
                                      _("handled by %s") % item["assignee"]])
            shown.append((item.get("id", ""), item.get("note") or _("No note."), subtitle, status == "new"))
        if not self.differs("list", shown):
            return
        self.list_rows.clear()
        if not shown:
            self.list_rows.add(common.row(_("No ticket here"), _("When an employee asks for help, it shows here and "
                                                                 "on the Overview.")))
        for ticket_id, note, subtitle, _new in shown:
            row = common.row(note, subtitle, activatable=True)
            row.connect("activated", lambda _row, key=ticket_id: self.open_ticket(key))
            self.list_rows.add(row)
        total = len(items)
        self.list_group.set_description(ngettext("%d ticket in all.", "%d tickets in all.", total) % total
                                        if total else "")

    def filtered(self, value: str) -> None:
        self.filter = value
        self.refresh(force=True)

    def open_ticket(self, ticket_id: str) -> None:
        if not self.built:
            self.build()
        detail = TicketDetail(self.ctx, ticket_id)
        detail.refresh(force=True)
        self.ctx.view.push(detail.navigation_page)

    def month_report(self) -> None:
        today = datetime.date.today()
        months = [(today.year, today.month)]
        for _index in range(11):
            year, month = months[-1]
            months.append((year - 1, 12) if month == 1 else (year, month - 1))
        choice = Adw.ComboRow(title=_("Month"), use_markup=False, model=Gtk.StringList.new(
            [_("%(month)d/%(year)d") % {"month": month, "year": year} for year, month in months]))

        def chosen() -> None:
            year, month = months[choice.get_selected()]
            self.save_month(year, month)

        common.form_dialog(self.ctx.window, _("Month report"),
                           _("The number of tickets by status, the median time to the first answer, and the list, "
                             "as an Excel workbook."), [choice], _("Choose where to save…"), chosen)

    def save_month(self, year: int, month: int) -> None:
        dialog = Gtk.FileDialog(title=_("Save the month report"), initial_name=f"phieu-ho-tro-{year}-{month:02d}.xlsx")

        def saved(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                path = Path(source.save_finish(result).get_path())
            except (GLib.Error, TypeError):
                return
            if path.suffix.lower() != ".xlsx":
                path = path.with_suffix(".xlsx")
            report = tickets.month_report(self.ctx.tickets, year, month)
            names = {key: self.ctx.machine_name(key) for key in {item.get("machine_id", "")
                                                                  for item in report["tickets"]}}
            try:
                reports.write_tickets_xlsx(report, names, year, month, path, self.ctx.now())
            except ImportError:
                self.ctx.toast(_("python3-openpyxl is missing: install it to make Excel files."), 8)
                return
            except OSError as exc:
                self.ctx.toast(_("Could not write %(file)s: %(error)s") % {"file": path.name, "error": exc.strerror}, 8)
                return
            self.ctx.toast(_("Saved %s.") % path.name)

        dialog.save(self.ctx.window, None, saved)


class TicketDetail(Page):
    def __init__(self, ctx: Context, ticket_id: str) -> None:
        super().__init__(ctx, ticket_id, f"ticket-{ticket_id}")
        self.ticket_id = ticket_id

    def ticket(self) -> dict[str, Any] | None:
        return tickets.find(self.ctx.tickets, self.ticket_id)

    def refresh(self, force: bool = False) -> None:
        ticket = self.ticket()
        if force:
            self.forget_signatures()
        if not self.differs("ticket", ticket):
            return
        self.clear()
        if ticket is None:
            self.body.append(common.status_page("help-browser-symbolic", _("This ticket is no longer listed")))
            return
        machine_id = ticket.get("machine_id", "")
        machine = self.ctx.machine_name(machine_id)
        self.body.append(common.label(ticket.get("note") or _("No note."), "section-title"))
        facts = common.group()
        who = ticket.get("user") or _("someone not logged in")
        facts.add(common.property_row(_("Asked by"), _("%(user)s on %(machine)s") % {"user": who, "machine": machine}))
        facts.add(common.property_row(_("Sent"), text.sentence([text.clock(ticket.get("created", "")),
                                                                text.ago(ticket.get("created", ""))])))
        if ticket.get("first_response"):
            facts.add(common.property_row(_("First answer"), text.clock(ticket["first_response"])))
        status = Adw.ComboRow(title=_("Status"), use_markup=False, model=Gtk.StringList.new(status_titles()))
        status.set_selected(protocol.TICKET_STATES.index(ticket.get("status", "new")))
        status.connect("notify::selected", lambda row, _p: self.change(
            {"status": protocol.TICKET_STATES[row.get_selected()]}) if protocol.TICKET_STATES[row.get_selected()]
            != (self.ticket() or {}).get("status") else None)
        facts.add(status)
        assignee = common.entry_row(_("Handled by"), ticket.get("assignee", ""))
        assignee.set_show_apply_button(True)
        assignee.connect("apply", lambda row: self.change({"assignee": row.get_text().strip()[:60]}))
        facts.add(assignee)
        self.body.append(facts)
        actions = Gtk.Box(spacing=8)
        if machine_id in self.ctx.machines:
            actions.append(common.button(_("Remote help…"), self.remote_help, "suggested-action"))
            actions.append(common.button(_("Open the machine"), self.open_machine))
        self.body.append(actions)
        notes = common.group(_("Notes"), _("Public notes reach the employee on their machine; internal ones stay "
                                           "here."))
        for note in ticket.get("notes") or []:
            parts = [text.clock(note.get("time", "")), note.get("by", "")]
            if note.get("status"):
                parts.append(_("status: %s") % status_title(note["status"]))
            parts.append(_("the employee sees it") if note.get("public") else _("internal"))
            notes.add(common.row(note.get("text") or status_title(note.get("status", "")), text.sentence(parts)))
        if not ticket.get("notes"):
            notes.add(common.row(_("No note yet")))
        self.body.append(notes)
        add = common.group(_("Add a note"))
        self.note_view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8, left_margin=10,
                                      right_margin=10)
        self.note_view.update_property([Gtk.AccessibleProperty.LABEL], [_("Note")])
        frame = Gtk.Frame()
        frame.set_child(self.note_view)
        frame.set_size_request(-1, 90)
        add.add(frame)
        listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, margin_top=12)
        listing.add_css_class("boxed-list")
        self.public = Adw.SwitchRow(title=_("The employee sees this note"), use_markup=False, active=True)
        listing.append(self.public)
        add.add(listing)
        send = common.button(_("Add the note"), self.add_note)
        send.set_halign(Gtk.Align.END)
        send.set_margin_top(12)
        add.add(send)
        self.body.append(add)
        snapshot = ticket.get("snapshot") or {}
        details = common.group()
        expander = Adw.ExpanderRow(title=_("Details"), use_markup=False,
                                   subtitle=_("The machine as it was when the ticket was sent"))
        summary = snapshot.get("inventory_summary") or {}
        for title, value in ((_("Model"), summary.get("model", "")), (_("Processor"), summary.get("cpu", "")),
                             (_("Memory"), f"{round(summary['memory_mb'] / 1024)} GB" if summary.get("memory_mb")
                              else ""), (_("CaramOS"), summary.get("caramos", "")),
                             (_("Disks"), ", ".join(text.join_sentence([disk.get("model", ""),
                                                                        text.size_gb(disk.get("size_gb"))])
                                                    for disk in summary.get("disks") or []))):
            if value:
                expander.add_row(common.property_row(title, value))
        health = snapshot.get("health") or {}
        if health:
            expander.add_row(common.property_row(_("Health"), health_sentence(health)))
        details.add(expander)
        self.body.append(details)

    def change(self, change: dict[str, Any]) -> None:
        def done(ok: bool, answer: dict[str, Any]) -> None:
            if ok:
                self.ctx.reload()
                self.refresh(force=True)
            else:
                self.ctx.toast(answer.get("error", _("Could not change it.")), 8)

        self.ctx.helper(["ticket"], done, json.dumps(dict(change, id=self.ticket_id), ensure_ascii=False))

    def add_note(self) -> None:
        buffer = self.note_view.get_buffer()
        note = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip()
        if not note:
            return
        if len(note) > tickets.MAX_TEXT:
            self.ctx.toast(_("A note has 1 to 500 characters."))
            return
        self.change({"note": {"text": note, "public": self.public.get_active()}})

    def remote_help(self) -> None:
        from .remote import ask_remote_help

        ticket = self.ticket() or {}
        ask_remote_help(self.ctx, ticket.get("machine_id", ""), help_id=self.ticket_id)

    def open_machine(self) -> None:
        ticket = self.ticket() or {}
        self.ctx.view.show_page("machines")
        self.ctx.view.page("machines").open_machine(ticket.get("machine_id", ""))


def health_sentence(health: dict[str, Any]) -> str:
    """A machine's health at the time of a ticket, in a sentence."""

    parts = []
    if isinstance(health.get("disk_free_pct"), int):
        parts.append(_("%d%% of the disk free") % health["disk_free_pct"])
    security = (health.get("updates") or {}).get("security")
    if isinstance(security, int):
        parts.append(ngettext("%d security update waiting", "%d security updates waiting", security) % security)
    if health.get("reboot_required"):
        parts.append(_("needs a restart"))
    if health.get("firewall") in ("on", "off"):
        parts.append(_("firewall on") if health["firewall"] == "on" else _("firewall off"))
    if isinstance(health.get("uptime_hours"), int):
        parts.append(ngettext("on for %d hour", "on for %d hours", health["uptime_hours"]) % health["uptime_hours"])
    return text.sentence(parts)

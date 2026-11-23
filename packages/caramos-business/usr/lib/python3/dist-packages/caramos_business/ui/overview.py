"""Tổng quan: how many machines are on, off and need a look, machines waiting for approval, new help tickets, the most
important problems, warranties ending and assets in repair, and which features are on for the whole company."""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import assets, health, protocol, summaries, text  # noqa: E402
from ..draft import COMPANY  # noqa: E402
from ..i18n import _, ngettext  # noqa: E402
from . import common  # noqa: E402
from .admin_window import Context, Page  # noqa: E402

MOST_PROBLEMS = 8


class OverviewPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx, _("Overview"), "overview")

    def refresh(self, force: bool = False) -> None:
        ctx = self.ctx
        new = ctx.new_tickets()
        state = (sorted((key, ctx.online(key), [problem.text for problem in ctx.problems(key)])
                        for key in ctx.machines), sorted(ctx.pending), new, ctx.saved_policy.get("serial"),
                 [text.ago(item.get("created", "")) for item in new], ctx.assets)
        if force:
            self.forget_signatures()
        if not self.differs("overview", state):
            return
        self.clear()
        machines = ctx.machines
        intro = Gtk.Box(spacing=16)
        intro.add_css_class("intro")
        intro.append(common.logo(48))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
        texts.append(common.label(_("CaramOS Business"), "page-title"))
        texts.append(common.label(ngettext("This machine manages %d employee machine.",
                                           "This machine manages %d employee machines.", len(machines)) % len(machines)
                                  if machines else _("No employee machine yet: add the first ones."), "paragraph"))
        intro.append(texts)
        self.body.append(intro)
        if not machines:
            start = common.group()
            row = common.row(_("Add employee machines"), _("With a code typed on each machine, or with an enrolment "
                                                           "file for many at once."), activatable=True)
            row.connect("activated", lambda _row: self.add_machines())
            start.add(row)
            self.body.append(start)
        else:
            self.body.append(self.counts())
        for part in (self.waiting(), self.tickets(), self.problems(), self.assets()):
            if part is not None:
                self.body.append(part)
        self.body.append(self.features())

    def add_machines(self) -> None:
        self.ctx.view.show_page("machines")
        self.ctx.view.page("machines").open_add_machines()

    def counts(self) -> Adw.PreferencesGroup:
        ctx = self.ctx
        online = [key for key in ctx.machines if ctx.online(key)]
        trouble = [key for key in ctx.machines if ctx.problems(key)]
        target = common.group(_("Employee machines"))
        for value, title, subtitle, filter_key in (
                (len(online), _("On"), _("Reported in the last 10 minutes"), "online"),
                (len(ctx.machines) - len(online), _("Not on"), _("Turned off, or away from the network"), "offline"),
                (len(trouble), _("Need a look"), _("A full disk, waiting updates, a setting that failed…"),
                 "problems")):
            row = common.row(title, subtitle, activatable=True)
            count = common.label(str(value), "count", wrap=False)
            if filter_key == "problems" and value:
                count.add_css_class("problem")
            count.set_valign(Gtk.Align.CENTER)
            row.add_suffix(count)
            row.connect("activated", lambda _row, key=filter_key: self.show_machines(key))
            target.add(row)
        return target

    def show_machines(self, filter_key: str) -> None:
        page = self.ctx.view.page("machines")
        page.show_filter(filter_key)
        self.ctx.view.show_page("machines")

    def waiting(self) -> Adw.PreferencesGroup | None:
        """Machines that asked to join while each new machine needs approval."""

        if not self.ctx.pending:
            return None
        target = common.group(_("Waiting for approval"))
        count = len(self.ctx.pending)
        row = common.row(ngettext("%d machine asks to join the company", "%d machines ask to join the company",
                                  count) % count,
                         ", ".join(sorted(self.ctx.machine_name(key) for key in self.ctx.pending)), activatable=True)
        row.connect("activated", lambda _row: self.ctx.view.show_page("machines"))
        target.add(row)
        return target

    def tickets(self) -> Adw.PreferencesGroup | None:
        new = self.ctx.new_tickets()
        if not new:
            return None
        target = common.group(_("Asking for help"))
        for item in new[:MOST_PROBLEMS]:
            machine_id = item.get("machine_id", "")
            name = self.ctx.machine_name(machine_id)
            who = _("%(user)s on %(machine)s") % {"user": item["user"], "machine": name} if item.get("user") else name
            note = item.get("note") or _("No note.")
            # The note as the employee wrote it, with or without a full stop, then the ticket and when: on lines of
            # their own.
            row = common.row(who, f"{note}\n{text.sentence([item.get('id', ''), text.ago(item.get('created', ''))])}",
                             activatable=True)
            row.add_suffix(common.button(_("Help"), lambda ticket=item: self.answer(ticket)))
            row.connect("activated", lambda _row, ticket=item: self.open_ticket(ticket))
            target.add(row)
        if len(new) > MOST_PROBLEMS:
            more = common.row(ngettext("%d more new ticket", "%d more new tickets", len(new) - MOST_PROBLEMS)
                              % (len(new) - MOST_PROBLEMS), activatable=True)
            more.connect("activated", lambda _row: self.ctx.view.show_page("tickets"))
            target.add(more)
        return target

    def answer(self, ticket: dict[str, Any]) -> None:
        from .remote import ask_remote_help

        ask_remote_help(self.ctx, ticket.get("machine_id", ""), help_id=ticket.get("id"))

    def open_ticket(self, ticket: dict[str, Any]) -> None:
        self.ctx.view.show_page("tickets")
        self.ctx.view.page("tickets").open_ticket(ticket.get("id", ""))

    def assets(self) -> Adw.PreferencesGroup | None:
        """Warranties ending within 30 days, and assets in repair."""

        stored = self.ctx.assets
        ending = assets.warranty_ending(stored, self.ctx.now().date())
        repair = assets.in_repair(stored)
        if not ending and not repair:
            return None
        target = common.group(_("Assets"))
        for asset_id in ending:
            entry = stored.get(asset_id) or {}
            row = common.row(assets.asset_name(asset_id, entry, self.ctx.machines),
                             _("The warranty ends on %s.") % text.vn_date(entry.get("warranty_until", "")),
                             activatable=True)
            row.connect("activated", lambda _row, key=asset_id: self.open_asset(key))
            target.add(row)
        for asset_id in repair:
            entry = stored.get(asset_id) or {}
            row = common.row(assets.asset_name(asset_id, entry, self.ctx.machines), _("In repair."), activatable=True)
            row.connect("activated", lambda _row, key=asset_id: self.open_asset(key))
            target.add(row)
        return target

    def open_asset(self, asset_id: str) -> None:
        self.ctx.view.show_page("assets")
        self.ctx.view.page("assets").open_asset(asset_id)

    def problems(self) -> Adw.PreferencesGroup | None:
        found: list[tuple[health.Problem, str]] = []
        for machine_id in self.ctx.machines:
            found += [(problem, machine_id) for problem in self.ctx.problems(machine_id)]
        if not found:
            return None
        found.sort(key=lambda item: (item[0].severity, -(item[0].since.timestamp() if item[0].since else 0)))
        target = common.group(_("Needs a look"))
        for problem, machine_id in found[:MOST_PROBLEMS]:
            row = common.row(self.ctx.machine_name(machine_id), problem.text, activatable=True)
            row.connect("activated", lambda _row, key=machine_id: self.open_machine(key))
            target.add(row)
        if len(found) > MOST_PROBLEMS:
            more = common.row(ngettext("%d more problem", "%d more problems", len(found) - MOST_PROBLEMS)
                              % (len(found) - MOST_PROBLEMS), activatable=True)
            more.connect("activated", lambda _row: self.show_machines("problems"))
            target.add(more)
        return target

    def open_machine(self, machine_id: str) -> None:
        self.ctx.view.show_page("machines")
        self.ctx.view.page("machines").open_machine(machine_id)

    def features(self) -> Adw.PreferencesGroup:
        """What is on for the whole company: everything is off until the admin turns it on."""

        settings = self.ctx.saved_policy.get("settings") or {}
        target = common.group(_("On for the whole company"))
        on = [section for section in protocol.SECTIONS if settings.get(section) is not None]
        if not on:
            target.set_description(_("Nothing yet: every machine stays as it is. Turn features on in the pages on the "
                                     "left, for the company or for a department."))
            return target
        from .admin_window import page_of_section

        for section in on:
            row = common.row(health.section_title(section), summaries.summary(section, settings[section]),
                             activatable=True)

            def open_page(_row: Adw.ActionRow, item: str = section) -> None:
                self.ctx.set_scope(COMPANY)
                self.ctx.view.show_page(page_of_section(item) or "overview")

            row.connect("activated", open_page)
            target.add(row)
        departments = self.ctx.saved_policy.get("departments") or {}
        own = [value.get("name", key) for key, value in departments.items() if value.get("settings")]
        if own:
            target.set_description(_("Departments with settings of their own: %s.") % ", ".join(own))
        return target


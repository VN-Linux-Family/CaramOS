"""The employee machines: the ones waiting for approval, the automatic inventory switch, the list with filters,
actions for many machines, the asset export, and each machine's page (its inventory, asset details and history,
problems, settings in effect, recent actions and the actions themselves). Adding machines is its own page
(adding.py)."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import GUIDE, admin, export, health, protocol, summaries, text  # noqa: E402
from ..draft import COMPANY, INHERIT, OFF, OWN  # noqa: E402
from ..i18n import _, ngettext  # noqa: E402
from . import common, sections  # noqa: E402
from .admin_window import Context, Page  # noqa: E402

FILTERS = ("all", "online", "offline", "problems")


def filter_titles() -> list[str]:
    return [_("All machines"), _("On"), _("Not on"), _("Need a look")]


def machine_sentence(ctx: Context, machine_id: str) -> str:
    entry = ctx.machines.get(machine_id) or {}
    users = ", ".join(user.get("user", "") for user in entry.get("users") or [])
    parts = [ctx.department_name(machine_id), _("%s is using it") % users if users else "",
             _("seen %s") % text.ago(entry.get("last_seen", ""))]
    return text.sentence(parts)


def state_text(state: str, detail: str, action: str, steps: list[dict[str, Any]] | None = None) -> str:
    detail = summaries.result_detail(action, detail, steps)
    if state == "done":
        return _("Done: %s") % detail if detail else _("Done.")
    if state == "failed":
        return _("Could not do it: %s") % detail if detail else _("Could not do it.")
    if state == "refused":
        return _("The employee refused.") if action == "remote_help" else (_("Refused: %s") % detail if detail else
                                                                           _("Refused."))
    if state == "expired":
        if detail == text.BEFORE_THIS_BOOT:
            return _("It was sent while the machine was off or restarting, so it was not done.")
        return _("It came too late and was not done.")
    if state == "ignored":
        return _("Not done: %s") % detail if detail else _("Not done.")
    return ""


def action_title(action: str, args: dict[str, Any]) -> str:
    titles = {"sync": _("Sync now"), "inventory": _("Take inventory again"), "lock": _("Lock"),
              "logout": _("Log out"), "restart": _("Restart"), "shutdown": _("Shut down"), "cancel": _("Cancel"),
              "update": _("Update"), "remote_help": _("Remote help"), "usb_unlock": _("Allow USB for a while")}
    if action == "message":
        return _("Message “%s”") % args.get("title", "")
    if action == "usb_unlock":
        return ngettext("Allow USB for %d minute", "Allow USB for %d minutes", args.get("minutes", 0)) % args.get(
            "minutes", 0)
    return titles.get(action, action)


class MachinesPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx, _("Employee machines"), "machines")
        self.filter = "all"
        self.department = ""  # "" every department, "-" none, else the department's id
        self.query = ""
        self.pairing_button = common.button(_("Add machines"), self.open_add_machines, "suggested-action")
        self.header.pack_end(self.pairing_button)
        self.built = False

    # - building -

    def build(self) -> None:
        self.clear()
        self.pending_group = common.group(_("Waiting for approval"), _(
            "These machines asked to join. Approve the ones you know; a machine turned away gets nothing."))
        self.pending_rows = common.Rows(self.pending_group)
        self.body.append(self.pending_group)
        self.inventory_group = common.group()
        self.inventory_rows = common.Rows(self.inventory_group)
        self.body.append(self.inventory_group)
        controls = Gtk.Box(spacing=8)
        search = Gtk.SearchEntry(placeholder_text=_("Search machines or people"), hexpand=True)
        search.connect("search-changed", lambda entry: self.searched(entry.get_text()))
        controls.append(search)
        self.state_drop = Gtk.DropDown.new_from_strings(filter_titles())
        self.state_drop.set_selected(FILTERS.index(self.filter))
        self.state_drop.connect("notify::selected", lambda drop, _p: self.filtered(FILTERS[drop.get_selected()]))
        controls.append(self.state_drop)
        self.department_drop = Gtk.DropDown()
        self.department_drop.connect("notify::selected", lambda drop, _p: self.department_chosen(drop.get_selected()))
        controls.append(self.department_drop)
        self.body.append(controls)
        self.list_group = common.group(_("Machines"))
        actions = Gtk.Box(spacing=6)
        actions.append(common.button(_("Actions…"), self.bulk_actions,
                                     tooltip=_("An action for every machine, or for a department")))
        actions.append(common.button(_("Export the asset list…"), self.export))
        self.list_group.set_header_suffix(actions)
        self.list_rows = common.Rows(self.list_group)
        self.body.append(self.list_group)
        note = common.link_label(_("Tell your staff in writing which features the company uses on their machines, for "
                                   "example in the internal labour rules (Law 91/2025/QH15, article 25)."),
                                 _("Read the guide"), GUIDE.as_uri(), "dim-label", "secondary")
        self.body.append(note)
        self.department_ids: list[str] = []
        self.built = True

    def refresh(self, force: bool = False) -> None:
        if not self.built:
            self.build()
        if force:
            self.forget_signatures()
        self.refresh_pending()
        if force:
            self.refresh_inventory()
        self.refresh_departments()
        self.refresh_list()

    def refresh_pending(self) -> None:
        from .adding import pending_rows

        shown = sorted((key, entry.get("paired", "")) for key, entry in self.ctx.pending.items())
        if not self.differs("pending", shown):
            return
        self.pending_rows.clear()
        self.pending_group.set_visible(bool(shown))
        pending_rows(self.ctx, self.pending_rows, lambda: self.refresh())

    def refresh_inventory(self) -> None:
        """The inventory switch: for the company, and how each department takes it."""

        self.inventory_rows.clear()
        draft = self.ctx.draft
        mode = draft.mode(COMPANY, "inventory")
        switch = Adw.SwitchRow(title=sections.feature_title("inventory"), use_markup=False, active=mode == OWN)
        switch.set_subtitle(_("Machines send their hardware and list of apps, for the asset list. Never files or "
                              "what employees do.") if mode == OWN else
                            _("Not on: machines send only their name, user and health. Turn it on for the "
                              "asset list."))

        def switched(row: Adw.SwitchRow, _param: Any) -> None:
            draft.switch(COMPANY, "inventory", OWN if row.get_active() else OFF)
            self.ctx.changed()
            GLib.idle_add(lambda: self.refresh_inventory() and False)

        switch.connect("notify::active", switched)
        self.inventory_rows.add(switch)
        departments = draft.departments()
        if departments:
            expander = Adw.ExpanderRow(title=_("By department"), use_markup=False)
            changed = [key for key in departments if draft.mode(f"department:{key}", "inventory") != INHERIT]
            expander.set_subtitle(ngettext("%d department with its own choice", "%d departments with their own choice",
                                           len(changed)) % len(changed) if changed else
                                  _("Every department follows the company."))
            for key in self.ctx.department_ids():
                scope = f"department:{key}"
                combo = Adw.ComboRow(title=departments[key].get("name", key), use_markup=False,
                                     model=Gtk.StringList.new([_("As the company"), _("On"), _("Off")]))
                combo.set_selected((INHERIT, OWN, OFF).index(draft.mode(scope, "inventory")))

                def chosen(row: Adw.ComboRow, _param: Any, target: str = scope) -> None:
                    draft.switch(target, "inventory", (INHERIT, OWN, OFF)[row.get_selected()])
                    self.ctx.changed()

                combo.connect("notify::selected", chosen)
                expander.add_row(combo)
            self.inventory_rows.add(expander)

    def refresh_departments(self) -> None:
        departments = self.ctx.draft.departments()
        ids = self.ctx.department_ids()
        if ids == self.department_ids and self.department_drop.get_model() is not None:
            return
        self.department_ids = ids
        titles = [_("Every department"), _("In no department")] + [departments[key].get("name", key) for key in ids]
        self.department_drop.set_model(Gtk.StringList.new(titles))
        current = 0 if not self.department else 1 if self.department == "-" else (
            ids.index(self.department) + 2 if self.department in ids else 0)
        self.department_drop.set_selected(current)
        self.department_drop.set_visible(bool(ids))

    def searched(self, query: str) -> None:
        self.query = text.fold(query.strip())
        self.refresh_list()

    def filtered(self, value: str) -> None:
        self.filter = value
        self.refresh_list()

    def department_chosen(self, index: int) -> None:
        self.department = "" if index == 0 else "-" if index == 1 else self.department_ids[index - 2] \
            if index - 2 < len(self.department_ids) else ""
        self.refresh_list()

    def show_filter(self, value: str) -> None:
        self.filter = value
        if self.built:
            self.state_drop.set_selected(FILTERS.index(value))

    def matches(self, machine_id: str, entry: dict[str, Any], problems: list[health.Problem]) -> bool:
        online = self.ctx.online(machine_id)
        if self.filter == "online" and not online or self.filter == "offline" and online:
            return False
        if self.filter == "problems" and not problems:
            return False
        department = self.ctx.draft.department_of(machine_id)
        if self.department == "-" and department or self.department not in ("", "-") and department != self.department:
            return False
        if self.query:
            haystack = text.fold(" ".join([(entry.get("machine") or {}).get("name", ""),
                                           (entry.get("machine") or {}).get("ip", ""),
                                           self.ctx.department_name(machine_id),
                                           " ".join(user.get("user", "") for user in entry.get("users") or []),
                                           (self.ctx.assets.get(machine_id) or {}).get("holder", ""),
                                           (self.ctx.assets.get(machine_id) or {}).get("asset_code", "")]))
            return all(word in haystack for word in self.query.split())
        return True

    def refresh_list(self) -> None:
        machines = self.ctx.machines
        shown_rows = []
        for machine_id, entry in sorted(machines.items(),
                                        key=lambda item: (item[1].get("machine") or {}).get("name", "")):
            problems = self.ctx.problems(machine_id)
            if not self.matches(machine_id, entry, problems):
                continue
            name = (entry.get("machine") or {}).get("name", "?")
            if not entry.get("box_key"):
                shown_rows.append((machine_id, name, _("Needs pairing again: it was added by an older version."),
                                   _("Pair again"), True, ""))
            elif problems:
                shown_rows.append((machine_id, name, machine_sentence(self.ctx, machine_id), _("Needs a look"), True,
                                   "\n".join(problem.text for problem in problems)))
            else:
                shown_rows.append((machine_id, name, machine_sentence(self.ctx, machine_id),
                                   _("On") if self.ctx.online(machine_id) else _("Not on"), False, ""))
        if not self.differs("list", shown_rows):
            return
        self.list_rows.clear()
        shown = len(shown_rows)
        for machine_id, name, subtitle, state_label, problem, tooltip in shown_rows:
            row = common.row(name, subtitle, activatable=True)
            state = common.label(state_label, "problem", wrap=False) if problem else \
                common.secondary(state_label, wrap=False)
            if tooltip:
                row.set_tooltip_text(tooltip)
            state.set_valign(Gtk.Align.CENTER)
            row.add_suffix(state)
            row.connect("activated", lambda _row, key=machine_id: self.open_machine(key))
            self.list_rows.add(row)
        total = len(machines)
        if not total:
            self.list_group.set_description(_("No machine yet: press Add machines at the top."))
            if not shown:
                self.list_rows.add(common.row(_("Add the first machines"), _(
                    "With a code typed on each machine, or with an enrolment file for many at once."),
                    activatable=True))
                self.list_rows.items[-1].connect("activated", lambda _row: self.open_add_machines())
        elif shown == total:
            self.list_group.set_description(ngettext("%d machine.", "%d machines.", total) % total)
        else:
            self.list_group.set_description(_("%(shown)d of %(total)d machines.") % {"shown": shown, "total": total})
            if not shown:
                self.list_rows.add(common.row(_("No machine matches.")))

    def open_machine(self, machine_id: str) -> None:
        detail = MachineDetail(self.ctx, machine_id)
        detail.refresh(force=True)
        self.ctx.view.push(detail.navigation_page)

    # - adding -

    def open_add_machines(self) -> None:
        from .adding import AddMachinesPage

        page = AddMachinesPage(self.ctx)
        self.ctx.view.push(page.navigation_page)

    # - many machines -

    def bulk_actions(self) -> None:
        if not self.ctx.machines:
            self.ctx.toast(_("No machine yet."))
            return
        departments = self.ctx.draft.departments()
        ids = self.ctx.department_ids()
        target = Adw.ComboRow(title=_("For"), use_markup=False, model=Gtk.StringList.new(
            [_("All machines")] + [departments[key].get("name", key) for key in ids]))
        action = Adw.ComboRow(title=_("Action"), use_markup=False, model=Gtk.StringList.new(
            [_("Lock"), _("Send a message"), _("Restart"), _("Shut down"), _("Update"), _("Take inventory again"),
             _("Sync now")]))
        keys = ("lock", "message", "restart", "shutdown", "update", "inventory", "sync")

        def targets() -> dict[str, Any]:
            index = target.get_selected()
            return {"all": True} if index == 0 else {"departments": [ids[index - 1]]}

        def go() -> None:
            chosen = keys[action.get_selected()]
            # Inside sentences ("Đã yêu cầu mọi máy …"): not the drop-down's "Mọi máy".
            where = summaries.targets_text(targets(), lambda key: departments.get(key, {}).get("name", key), [])
            Actions(self.ctx, targets(), where).run(chosen)

        common.form_dialog(self.ctx.window, _("An action for many machines"),
                           _("Machines that are on do it within seconds; the others when they start, if it is still "
                             "valid then."), [target, action], _("Next…"), go)

    # - export -

    def export(self) -> None:
        lacking = [machine_id for machine_id in self.ctx.machines if self.ctx.inventory(machine_id) is None]
        if lacking and not any(self.ctx.effective(machine_id).get("inventory") for machine_id in self.ctx.machines):
            dialog = Adw.AlertDialog(heading=_("The automatic inventory is not on"), body=_(
                "The list then has only what you typed for each machine: no configuration, serial number or disks. "
                "Turn the automatic inventory on, save, and export again in a few minutes."))
            dialog.add_response("cancel", _("Cancel"))
            dialog.add_response("export", _("Export anyway"))
            dialog.add_response("turn-on", _("Turn on the inventory"))
            dialog.set_response_appearance("turn-on", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_close_response("cancel")

            def response(_dialog: Adw.AlertDialog, answer: str) -> None:
                if answer == "export":
                    self.choose_file()
                elif answer == "turn-on":
                    self.ctx.draft.switch(COMPANY, "inventory", OWN)
                    self.ctx.changed()
                    self.refresh_inventory()

            dialog.connect("response", response)
            dialog.present(self.ctx.window)
            return
        self.choose_file()

    def choose_file(self) -> None:
        filters = Gio.ListStore.new(Gtk.FileFilter)
        xlsx = Gtk.FileFilter(name=_("Excel workbook (.xlsx)"))
        xlsx.add_suffix("xlsx")
        csv = Gtk.FileFilter(name=_("CSV, for any spreadsheet (.csv)"))
        csv.add_suffix("csv")
        filters.append(xlsx)
        filters.append(csv)
        dialog = Gtk.FileDialog(title=_("Export the asset list"), filters=filters, default_filter=xlsx,
                                initial_name=f"kiem-ke-may-tinh-{datetime.date.today():%Y-%m-%d}.xlsx")

        def saved(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                path = Path(source.save_finish(result).get_path())
            except (GLib.Error, TypeError):
                return
            now = self.ctx.now()
            inventories = {machine_id: self.ctx.inventory(machine_id) for machine_id in self.ctx.machines}
            table = export.rows(self.ctx.machines, self.ctx.assets, {k: v for k, v in inventories.items() if v},
                                self.ctx.saved_policy, self.ctx.records, now)
            try:
                if path.suffix.lower() == ".csv":
                    export.write_csv(table, path)
                else:
                    if path.suffix.lower() != ".xlsx":
                        path = path.with_suffix(".xlsx")
                    export.write_xlsx(table, path, now)
            except ImportError:
                path = path.with_suffix(".csv")
                export.write_csv(table, path)
                self.ctx.toast(_("python3-openpyxl is missing: saved as CSV instead."), 6)
                return
            except OSError as exc:
                self.ctx.toast(_("Could not write %(file)s: %(error)s") % {"file": path.name, "error": exc.strerror}, 8)
                return
            self.ctx.toast(_("Saved %s.") % path.name)

        dialog.save(self.ctx.window, None, saved)


class Actions:
    """The instant actions, with their questions: for one machine, a department or all. `where` names them inside a
    sentence: a machine's name, "phòng Kế toán", "mọi máy" (summaries.targets_text)."""

    def __init__(self, ctx: Context, targets: dict[str, Any], where: str) -> None:
        self.ctx = ctx
        self.targets = targets
        self.where = where

    def run(self, action: str) -> None:
        getattr(self, f"do_{action}")()

    def send(self, action: str, args: dict[str, Any] | None = None, sent: str | None = None,
             minutes: int | None = None) -> None:
        self.ctx.command(self.targets, action, args or {}, sent=sent or _("Sent to %s.") % self.where, minutes=minutes)

    def do_lock(self) -> None:
        self.send("lock", sent=_("Locking %s.") % self.where)

    def do_sync(self) -> None:
        self.send("sync")

    def do_inventory(self) -> None:
        self.send("inventory", sent=_("Asked %s to take inventory again.") % self.where)

    def do_update(self) -> None:
        common.confirm(self.ctx.window, _("Update %s now?") % self.where,
                       _("The CaramOS update runs as the daily check would, then the security updates. People can "
                         "keep working; a restart may be asked for afterwards."), _("Update"),
                       lambda: self.send("update", sent=_("Updating %s.") % self.where))

    def countdown(self, action: str) -> None:
        heading = {"restart": _("Restart %s?"), "shutdown": _("Shut down %s?")}[action] % self.where
        warn = Adw.ComboRow(title=_("Warn people first"), use_markup=False, model=Gtk.StringList.new(
            [_("1 minute"), _("5 minutes"), _("10 minutes"), _("15 minutes"), _("No warning")]))
        warn.set_selected(1)
        seconds = (60, 300, 600, 900, 0)
        dialog = Adw.AlertDialog(heading=heading, body=_(
            "Whoever is using a machine sees a countdown, without a way to postpone. Unsaved work is lost."))
        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")
        listbox.append(warn)
        dialog.set_extra_child(listbox)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("ok", _("Restart") if action == "restart" else _("Shut down"))
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, answer: answer == "ok" and self.send(
            action, {"warn_seconds": seconds[warn.get_selected()]},
            sent=(_("Restarting %s.") if action == "restart" else _("Shutting down %s.")) % self.where))
        dialog.present(self.ctx.window)

    def do_restart(self) -> None:
        self.countdown("restart")

    def do_shutdown(self) -> None:
        self.countdown("shutdown")

    def do_message(self) -> None:
        title = common.entry_row(_("Title, such as Họp lúc 15:00"))
        body = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=8, bottom_margin=8, left_margin=10,
                            right_margin=10)
        body.update_property([Gtk.AccessibleProperty.LABEL], [_("Message")])
        frame = Gtk.Frame()
        frame.set_child(body)
        frame.set_size_request(-1, 100)
        ack = Adw.SwitchRow(title=_("Ask them to press “I have read it”"), active=True)
        extra = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        extra.append(frame)
        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")
        listbox.append(ack)
        extra.append(listbox)

        def content() -> str:
            buffer = body.get_buffer()
            return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False).strip()

        def valid() -> bool:
            return 0 < len(title.get_text().strip()) <= 80 and len(content()) <= 1000

        def send() -> None:
            self.send("message", {"title": title.get_text().strip(), "body": content(), "ack": ack.get_active()},
                      sent=_("Message sent to %s.") % self.where)

        common.form_dialog(self.ctx.window, _("Send a message to %s") % self.where,
                           _("Everyone logged in sees it in a small window."), [title], _("Send"), send, valid,
                           extra=extra)

    def do_usb_unlock(self) -> None:
        minutes = Adw.SpinRow.new_with_range(1, 240, 5)
        minutes.set_title(_("Minutes"))
        minutes.set_value(30)
        common.form_dialog(self.ctx.window, _("Allow USB on %s for a while") % self.where,
                           _("USB drives work as usual until then, whatever the USB setting says."), [minutes],
                           _("Allow"), lambda: self.send("usb_unlock", {"minutes": int(minutes.get_value())},
                                                         sent=_("USB allowed on %s.") % self.where))


class MachineDetail(Page):
    """One machine: what it is, what it has, what is wrong, and what can be done."""

    def __init__(self, ctx: Context, machine_id: str) -> None:
        name = ctx.machine_name(machine_id)
        super().__init__(ctx, name, f"machine-{machine_id}")
        self.machine_id = machine_id
        self.built = False

    def build(self) -> None:
        self.clear()
        ctx, machine_id = self.ctx, self.machine_id
        self.sentence = common.label("", "paragraph")
        self.body.append(self.sentence)
        actions = common.group(_("Actions"))
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, column_spacing=8, row_spacing=8,
                           max_children_per_line=5, homogeneous=False)
        self.actions = Actions(ctx, {"machines": [machine_id]}, ctx.machine_name(machine_id))
        buttons = [(_("Lock"), lambda: self.actions.run("lock")),
                   (_("Send a message…"), lambda: self.actions.run("message")),
                   (_("Remote help…"), self.remote_help),
                   (_("Restart…"), lambda: self.actions.run("restart")),
                   (_("Shut down…"), lambda: self.actions.run("shutdown")),
                   (_("Update…"), lambda: self.actions.run("update")),
                   (_("Allow USB for a while…"), lambda: self.actions.run("usb_unlock")),
                   (_("Take inventory again"), self.take_inventory)]
        for title, callback in buttons:
            flow.append(common.button(title, callback))
        actions.add(flow)
        self.body.append(actions)
        self.recent_group = common.group(_("Recent actions"))
        self.recent_rows = common.Rows(self.recent_group)
        self.body.append(self.recent_group)
        self.problems_group = common.group(_("Needs a look"))
        self.problem_rows = common.Rows(self.problems_group)
        self.body.append(self.problems_group)
        department = common.group(_("Department"))
        departments = ctx.draft.departments()
        self.department_ids = [""] + ctx.department_ids()
        combo = Adw.ComboRow(title=_("Department"), use_markup=False, model=Gtk.StringList.new(
            [_("In no department")] + [departments[key].get("name", key) for key in self.department_ids[1:]]))
        current = ctx.draft.department_of(machine_id) or ""
        combo.set_selected(self.department_ids.index(current) if current in self.department_ids else 0)
        combo.set_subtitle(_("Changing it takes effect when you save.") if departments else
                           _("Add departments on the Departments page."))
        combo.set_sensitive(bool(departments))

        def department_chosen(row: Adw.ComboRow, _param: Any) -> None:
            ctx.draft.set_department(machine_id, self.department_ids[row.get_selected()] or None)
            ctx.changed()
            self.refresh_settings()

        combo.connect("notify::selected", department_chosen)
        department.add(combo)
        self.body.append(department)
        self.settings_group = common.group(_("Settings in effect"), _("What this machine has from the last save, and "
                                                                      "where it comes from. Open one to give this "
                                                                      "machine its own."))
        self.settings_rows = common.Rows(self.settings_group)
        self.body.append(self.settings_group)
        # Its own box, built again after each save: the history and the leaver steps show what was just saved.
        self.asset_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.body.append(self.asset_box)
        self.build_asset_form()
        self.inventory_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.body.append(self.inventory_box)
        leave = common.group(_("Take it out of the company"))
        leave.add(common.row(_("The machine is told that the company removed it: it puts back everything as it was "
                               "before pairing, the firewall too, and stops taking the company's settings. To add it "
                               "again, pair it again.")))
        remove = common.button(_("Take out of the company…"), self.forget, "destructive-action")
        remove.set_halign(Gtk.Align.START)
        remove.set_margin_top(12)
        leave.add(remove)
        self.body.append(leave)
        self.built = True

    def build_asset_form(self) -> None:
        from .assets_page import AssetForm

        # The page stays where it was: ticking the leaver steps one after another must not move it, and an open
        # history stays open (0.3.1 closed it at the first tick, and the steps jumped up by its height).
        restore = common.keep_place(self.asset_box)
        previous = getattr(self, "asset_form", None)
        history_open = previous.history_open() if previous is not None else False
        while (child := self.asset_box.get_first_child()) is not None:
            self.asset_box.remove(child)
        self.asset_form = AssetForm(self.ctx, self.machine_id, saved=self.build_asset_form, history_open=history_open)
        for widget in self.asset_form.groups():
            self.asset_box.append(widget)
        restore()

    def refresh(self, force: bool = False) -> None:
        if self.machine_id not in self.ctx.machines:
            self.clear()
            self.body.append(common.status_page("computer-symbolic", _("This machine is no longer in the company")))
            self.built = False
            return
        if not self.built or force:
            self.forget_signatures()
            self.build()
            self.refresh_inventory()
        self.refresh_header()
        self.refresh_recent()
        self.refresh_problems()
        self.refresh_settings()

    def refresh_header(self) -> None:
        entry = self.ctx.machines.get(self.machine_id) or {}
        machine = entry.get("machine") or {}
        version = f"CaramOS {machine['version']}" if machine.get("version") else ""
        what = " ".join(part for part in (version, text.edition_text(machine.get("edition", ""))) if part)
        self.sentence.set_label(text.sentence([what, machine.get("ip", ""), machine_sentence(self.ctx, self.machine_id)
                                               .rstrip(".")]))

    def refresh_recent(self) -> None:
        department = self.ctx.draft.department_of(self.machine_id)
        mine = [command for command in self.ctx.commands
                if protocol.targets_machine(command, self.machine_id, department)][-8:]
        now = self.ctx.now()
        shown = []
        for command in reversed(mine):
            result = self.ctx.command_results(command["id"]).get(self.machine_id)
            if result:
                status = state_text(result.get("state", ""), result.get("detail", ""), command["action"],
                                    result.get("steps"))
            else:
                expires = admin.parse_iso(command.get("expires"))
                status = _("The machine did not take it in time.") if expires and expires < now else \
                    _("Waiting for the machine…")
            shown.append((action_title(command["action"], command.get("args") or {}),
                          f"{text.clock(command.get('issued', ''))}. {status}",
                          bool(result and result.get("state") in ("failed", "refused"))))
        if not self.differs("recent", shown):
            return
        self.recent_rows.clear()
        self.recent_group.set_visible(bool(shown))
        for title, subtitle, problem in shown:
            row = common.row(title, subtitle)
            if problem:
                row.add_css_class("problem")
            self.recent_rows.add(row)

    def refresh_problems(self) -> None:
        problems = [(problem.text, _("Since %s.") % text.clock(problem.since.isoformat()) if problem.since else "")
                    for problem in self.ctx.problems(self.machine_id)]
        if not self.differs("problems", problems):
            return
        self.problem_rows.clear()
        self.problems_group.set_visible(bool(problems))
        for title, since in problems:
            self.problem_rows.add(common.row(title, since))

    def refresh_settings(self) -> None:
        effective = self.ctx.effective(self.machine_id)
        sources = protocol.setting_sources(self.ctx.saved_policy, self.machine_id)
        if not self.differs("settings", (effective, sources)):
            return
        self.settings_rows.clear()
        from .admin_window import page_of_section

        for section in protocol.SECTIONS:
            title = health.section_title(section)
            if section not in effective:
                subtitle = _("Not on.")
            else:
                source = sources.get(section, COMPANY)
                origin = _("From the company.") if source == COMPANY else _("This machine's own.") \
                    if source.startswith("machine:") else _("From department %s.") % self.ctx.scope_title(source)
                subtitle = f"{summaries.summary(section, effective[section])} {origin}"
            row = common.row(title, subtitle, activatable=True)
            if section not in effective:
                row.add_css_class("dim-label")

            def open_section(_row: Adw.ActionRow, item: str = section) -> None:
                page = page_of_section(item)
                if page == "machines":
                    self.ctx.view.show_page("machines")
                    return
                self.ctx.set_scope(f"machine:{self.machine_id}")
                self.ctx.view.show_page(page)

            row.connect("activated", open_section)
            self.settings_rows.add(row)

    # - inventory -

    def refresh_inventory(self) -> None:
        child = self.inventory_box.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.inventory_box.remove(child)
            child = following
        inventory = self.ctx.inventory(self.machine_id)
        enabled = bool(self.ctx.effective(self.machine_id).get("inventory"))
        if inventory is None:
            target = common.group(_("Inventory"))
            if enabled:
                target.add(common.row(_("The machine has not sent its inventory yet"),
                                      _("It sends it when it starts. Press Take inventory again to ask now.")))
            else:
                row = common.row(_("No inventory: the automatic inventory is not on for this machine"),
                                 _("Turn it on to see its hardware, serial number, disks and apps here and in the "
                                   "asset list."))
                target.add(row)
                turn_on = common.button(_("Turn on the inventory…"), lambda: self.ctx.view.show_page("machines"))
                turn_on.set_halign(Gtk.Align.START)
                turn_on.set_margin_top(12)
                target.add(turn_on)
            self.inventory_box.append(target)
            return
        for group_widget in inventory_groups(inventory):
            self.inventory_box.append(group_widget)

    def take_inventory(self) -> None:
        if not self.ctx.effective(self.machine_id).get("inventory"):
            self.ctx.toast(_("The automatic inventory is not on for this machine: turn it on first."), 6)
            return
        self.actions.run("inventory")

    def remote_help(self) -> None:
        from .remote import ask_remote_help

        ask_remote_help(self.ctx, self.machine_id)

    def forget(self) -> None:
        name = self.ctx.machine_name(self.machine_id)

        def go() -> None:
            def done(ok: bool, answer: dict[str, Any]) -> None:
                if ok:
                    self.ctx.reload()
                    self.ctx.view.nav.pop()
                    self.ctx.toast(_("%s was taken out of the company.") % name)
                else:
                    self.ctx.toast(answer.get("error", _("Could not change it.")), 8)

            self.ctx.helper(["forget-machine", self.machine_id], done)

        common.confirm(self.ctx.window, _("Take %s out of the company?") % name,
                       _("It is told that the company removed it, puts back everything as it was, the firewall too, "
                         "and stops reporting and taking actions. To add it again, pair it again."),
                       _("Take out"), go, destructive=True)


def inventory_groups(inventory: dict[str, Any]) -> list[Adw.PreferencesGroup]:
    """The inventory as readable sections."""

    system, memory = inventory.get("system") or {}, inventory.get("memory") or {}
    groups = []
    machine = common.group(_("Machine"), _("Sent %s.") % text.ago(inventory.get("received") or
                                                                  inventory.get("collected", "")))
    chassis = {"desktop": _("Desktop"), "laptop": _("Laptop"), "other": _("Other")}.get(system.get("chassis") or "", "")
    for title, value in ((_("Maker and model"), text.model_text(inventory)), (_("Serial number"), system.get("serial")),
                         (_("Kind"), chassis), (_("BIOS"), system.get("bios"))):
        if value:
            machine.add(common.property_row(title, value))
    groups.append(machine)
    parts = common.group(_("Processor and memory"))
    parts.add(common.property_row(_("Processor"), text.cpu_text(inventory)))
    parts.add(common.property_row(_("Memory"), text.memory_text(inventory)))
    for module in memory.get("modules") or []:
        size = f"{round((module.get('size_mb') or 0) / 1024)} GB" if module.get("size_mb") else ""
        detail = text.join_sentence([size,
                                     module.get("type") or "",
                                     f"{module['speed_mts']} MT/s" if module.get("speed_mts") else ""])
        parts.add(common.property_row(module.get("slot") or _("Memory module"), detail))
    groups.append(parts)
    disks = inventory.get("disks") or []
    if disks:
        target = common.group(_("Disks"))
        for disk in disks:
            state = {"ok": _("healthy"), "failing": _("failing"), "unknown": _("health unknown")}.get(
                disk.get("health") or "unknown", "")
            row = common.property_row(disk.get("model") or disk.get("name") or _("Disk"), text.join_sentence(
                [text.size_gb(disk.get("size_gb")), text.disk_kind(disk), state,
                 _("serial %s") % disk["serial"] if disk.get("serial") else ""]))
            if disk.get("health") == "failing":
                row.add_css_class("problem")
            target.add(row)
        groups.append(target)
    batteries = inventory.get("batteries") or []
    if batteries:
        target = common.group(_("Battery"))
        for battery in batteries:
            parts_text = []
            if battery.get("health_pct") is not None:
                parts_text.append(_("holds %d%% of its first charge") % round(battery["health_pct"]))
            if battery.get("cycles") is not None:
                cycles = battery["cycles"]
                parts_text.append(ngettext("%d charge cycle", "%d charge cycles", cycles) % cycles)
            target.add(common.property_row(battery.get("name") or _("Battery"), text.join_sentence(parts_text)))
        groups.append(target)
    monitors = inventory.get("monitors") or []
    if monitors:
        target = common.group(_("Screens"))
        for monitor in monitors:
            target.add(common.property_row(monitor.get("connector") or _("Screen"), text.join_sentence(
                [monitor.get("name") or "", _("serial %s") % monitor["serial"] if monitor.get("serial") else ""])))
        groups.append(target)
    network = inventory.get("network") or []
    if network:
        target = common.group(_("Network"))
        for card in network:
            target.add(common.property_row(card.get("name") or _("Network card"), text.join_sentence(
                [_("wired") if card.get("wired") else _("wireless"), card.get("ipv4") or "", card.get("mac") or ""])))
        groups.append(target)
    system_group = common.group(_("System"))
    os_info = inventory.get("os") or {}
    system_group.add(common.property_row(_("CaramOS"), " ".join(
        part for part in (os_info.get("caramos") or "", text.edition_text(os_info.get("edition") or "")) if part)))
    system_group.add(common.property_row(_("Kernel"), os_info.get("kernel") or ""))
    groups.append(system_group)
    apps = inventory.get("apps") or []
    if apps:
        target = common.group()
        expander = Adw.ExpanderRow(title=_("Apps"), use_markup=False,
                                   subtitle=ngettext("%d app", "%d apps", len(apps)) % len(apps))
        for app in sorted(apps, key=lambda item: text.fold(item.get("name") or item.get("id") or "")):
            source = {"deb": "deb", "flatpak": "Flatpak"}.get(app.get("source") or "", "")
            row = Adw.ActionRow(title=app.get("name") or app.get("id") or "", use_markup=False,
                                subtitle=text.join_sentence([app.get("version") or "", source]))
            expander.add_row(row)
        target.add(expander)
        groups.append(target)
    return groups

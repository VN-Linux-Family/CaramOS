"""Phòng ban: the departments, which machines are in each, and what each sets on its own. A machine is in one
department at most; a department's setting of a section replaces the company's for its machines."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

from .. import health, protocol, text  # noqa: E402
from ..i18n import _, ngettext  # noqa: E402
from . import common  # noqa: E402
from .admin_window import Context, Page  # noqa: E402


class DepartmentsPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx, _("Departments"), "departments")

    def refresh(self, force: bool = False) -> None:
        if not force:
            return
        self.clear()
        draft = self.ctx.draft
        self.body.append(common.label(_("Each machine is in one department at most. A department can use the "
                                        "company's settings, have its own, or turn a feature off, on every settings "
                                        "page. Changes take effect when you save."), "paragraph"))
        target = common.group(_("Departments"))
        target.set_header_suffix(common.button(_("Add a department…"), self.add))
        departments = draft.departments()
        if not departments:
            target.add(common.row(_("No department yet."), _("For example Kế toán, Kinh doanh, Kho.")))
        members = draft.data.get("members", {})
        for key in self.ctx.department_ids():
            department = departments[key]
            count = sum(1 for machine, value in members.items() if value == key and machine in self.ctx.machines)
            own = [health.section_title(section) for section in protocol.SECTIONS
                   if section in (department.get("settings") or {})]
            subtitle = ngettext("%d machine.", "%d machines.", count) % count
            subtitle += " " + (_("Own settings: %s.") % ", ".join(own) if own else _("Uses the company's settings."))
            row = common.row(department.get("name", key), subtitle)
            row.add_suffix(common.button(_("Machines…"), lambda item=key: self.choose_machines(item)))
            row.add_suffix(common.icon_button("document-edit-symbolic", _("Rename"),
                                              lambda item=key: self.rename(item)))
            row.add_suffix(common.icon_button("user-trash-symbolic", _("Remove"), lambda item=key: self.remove(item)))
            target.add(row)
        self.body.append(target)
        loose = [machine_id for machine_id in self.ctx.machines if not draft.department_of(machine_id)]
        if departments and loose:
            outside = common.group(_("In no department"), _("They take the company's settings."))
            for machine_id in sorted(loose, key=lambda item: text.fold(self.ctx.machine_name(item))):
                outside.add(common.row(self.ctx.machine_name(machine_id)))
            self.body.append(outside)

    def changed(self) -> None:
        self.ctx.changed()
        self.refresh(force=True)

    def add(self) -> None:
        name = common.entry_row(_("Name, such as Kế toán"))

        def go() -> None:
            try:
                self.ctx.draft.add_department(name.get_text())
            except protocol.ProtocolError as exc:
                self.ctx.toast(str(exc))
                return
            self.changed()

        common.form_dialog(self.ctx.window, _("Add a department"), "", [name], _("Add"), go,
                           lambda: 0 < len(name.get_text().strip()) <= protocol.MAX_NAME)

    def rename(self, key: str) -> None:
        name = common.entry_row(_("Name"), self.ctx.draft.departments()[key].get("name", ""))

        def go() -> None:
            try:
                self.ctx.draft.rename_department(key, name.get_text())
            except protocol.ProtocolError as exc:
                self.ctx.toast(str(exc))
                return
            self.changed()

        common.form_dialog(self.ctx.window, _("Rename the department"), "", [name], _("Rename"), go,
                           lambda: 0 < len(name.get_text().strip()) <= protocol.MAX_NAME)

    def remove(self, key: str) -> None:
        name = self.ctx.draft.departments()[key].get("name", key)

        def go() -> None:
            self.ctx.draft.remove_department(key)
            if self.ctx.scope == f"department:{key}":
                self.ctx.set_scope("company")
            self.changed()

        common.confirm(self.ctx.window, _("Remove the department %s?") % name,
                       _("Its machines take the company's settings again, and its own settings go."), _("Remove"), go,
                       destructive=True)

    def choose_machines(self, key: str) -> None:
        draft = self.ctx.draft
        name = draft.departments()[key].get("name", key)
        dialog = Adw.AlertDialog(heading=_("Machines of %s") % name,
                                 body=_("A machine in another department moves here."))
        listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listing.add_css_class("boxed-list")
        checks: dict[str, Gtk.CheckButton] = {}
        for machine_id in sorted(self.ctx.machines, key=self.ctx.machine_name):
            current = draft.department_of(machine_id)
            check = Gtk.CheckButton(active=current == key, valign=Gtk.Align.CENTER)
            other = draft.departments().get(current, {}).get("name") if current and current != key else ""
            row = common.row(self.ctx.machine_name(machine_id), _("Now in %s") % other if other else "")
            row.add_prefix(check)
            row.set_activatable_widget(check)
            checks[machine_id] = check
            listing.append(row)
        if not checks:
            listing.append(common.row(_("No machine yet.")))
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, propagate_natural_height=True,
                                      max_content_height=360)
        scroller.set_child(listing)
        dialog.set_extra_child(scroller)
        dialog.add_response("cancel", _("Cancel"))
        dialog.add_response("ok", _("Done"))
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_close_response("cancel")

        def response(_dialog: Adw.AlertDialog, answer: str) -> None:
            if answer != "ok":
                return
            for machine_id, check in checks.items():
                current = draft.department_of(machine_id)
                if check.get_active():
                    draft.set_department(machine_id, key)
                elif current == key:
                    draft.set_department(machine_id, None)
            self.changed()

        dialog.connect("response", response)
        dialog.present(self.ctx.window)


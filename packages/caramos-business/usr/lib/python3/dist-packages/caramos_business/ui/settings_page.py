"""A settings page: who it applies to at the top ("Cả công ty", a department or one machine), then each of its
sections with its switch and, when on, its editor.

Every section is opt-in: for the whole company a section is off ("Chưa bật") until the admin switches it on. A
department or machine uses what applies above it, has its own settings, or turns the section off."""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from .. import health, summaries  # noqa: E402
from ..draft import COMPANY, INHERIT, OFF, OWN, scope_kind, scope_key  # noqa: E402
from ..i18n import _  # noqa: E402
from . import common, sections  # noqa: E402
from .admin_window import Context, Page  # noqa: E402

PICK_MACHINE = "pick-machine"


def intro(key: str) -> str:
    return {
        "wallpaper": _("One wallpaper for every machine, pictures for holidays, and whether employees may change it."),
        "folders": _("Each employee's Desktop and Documents in their own folder on the company's server or NAS."),
        "shares": _("The company's shared folders, ready in every employee's file manager."),
        "browser": _("Home page, bookmarks, websites blocked during working hours and safe search, for Firefox, "
                     "Chrome, Cốc Cốc, Edge and Brave."),
        "printers": _("Network printers set up on the machines."),
        "wifi": _("Machines join the company's Wi-Fi by themselves. The password is sealed for each machine."),
        "apps": _("Apps from App Center's list that must be installed, or must not be."),
        "power": _("Shut machines down at the end of the day and turn them on in the morning."),
        "security": _("USB storage, locking the screen, and the firewall."),
        "shared": _("For machines many people use, in a computer lab, a meeting room or at the front desk: a guest "
                    "session, and freezing, which undoes every change when the machine restarts."),
        "snapshots": _("Machines take snapshots of their system with Timeshift, to go back when an update breaks "
                       "something."),
    }[key]


class SettingsPage(Page):
    def __init__(self, ctx: Context, key: str, title: str, section_names: tuple[str, ...]) -> None:
        super().__init__(ctx, title, key)
        self.key = key
        self.section_names = section_names
        self.editors = sections.Editors(self)
        self.pending = 0

    def refresh(self, force: bool = False) -> None:
        if force:  # editing stays undisturbed by the timer: settings pages rebuild when shown or changed
            self.rebuild()

    def changed(self, rebuild: bool = False) -> None:
        self.ctx.changed()
        if rebuild:
            self.schedule_rebuild()

    def schedule_rebuild(self) -> None:
        """Rebuilds after the signal that asked for it is over (its widget goes away in the rebuild)."""

        if not self.pending:
            self.pending = GLib.idle_add(self._rebuild_idle)

    def _rebuild_idle(self) -> bool:
        self.pending = 0
        self.rebuild()
        return False

    def rebuild(self) -> None:
        adjustment = self.view.get_content().get_vadjustment() if hasattr(self.view.get_content(), "get_vadjustment") \
            else None
        position = adjustment.get_value() if adjustment else 0
        self.clear()
        self.body.append(common.label(intro(self.key), "paragraph"))
        self.body.append(self.scope_group())
        for name in self.section_names:
            for widget in self.section(name):
                self.body.append(widget)
        if adjustment:
            GLib.idle_add(lambda: adjustment.set_value(position) and False)

    # - who it applies to -

    def scope_group(self) -> Adw.PreferencesGroup:
        target = common.group()
        scopes = self.ctx.scopes()
        titles = [self.ctx.scope_title(scope) for scope in scopes]
        machines = bool(self.ctx.machines)
        if machines:
            titles.append(_("One machine…"))
        combo = Adw.ComboRow(title=_("Applies to"), model=Gtk.StringList.new(titles), use_markup=False)
        combo.set_selected(scopes.index(self.ctx.scope))
        if len(scopes) == 1 and not self.ctx.draft.departments():
            combo.set_subtitle(_("Add departments to give them settings of their own."))

        def selected(row: Adw.ComboRow, _param: Any) -> None:
            index = row.get_selected()
            if index >= len(scopes):
                row.set_selected(scopes.index(self.ctx.scope))
                self.pick_machine()
                return
            if scopes[index] != self.ctx.scope:
                self.ctx.set_scope(scopes[index])
                self.schedule_rebuild()

        combo.connect("notify::selected", selected)
        target.add(combo)
        return target

    def pick_machine(self) -> None:
        dialog = Adw.Dialog(title=_("Settings for one machine"), content_width=460, content_height=480)
        listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listing.add_css_class("boxed-list")
        for machine_id, entry in sorted(self.ctx.machines.items(),
                                        key=lambda item: (item[1].get("machine") or {}).get("name", "")):
            department = self.ctx.department_name(machine_id)
            row = common.row((entry.get("machine") or {}).get("name", machine_id[:8]),
                             department or _("In no department"), activatable=True)

            def chosen(_row: Adw.ActionRow, key: str = machine_id) -> None:
                dialog.close()
                self.ctx.set_scope(f"machine:{key}")
                self.schedule_rebuild()

            row.connect("activated", chosen)
            listing.append(row)
        box = common.page_box()
        box.append(common.label(_("A machine's own settings win over its department's and the company's. Use them "
                                  "for exceptions, such as the director's laptop."), "paragraph"))
        box.append(listing)
        dialog.set_child(common.toolbar(common.scrolled(box)))
        dialog.present(self.ctx.window)

    # - one section -

    def section(self, name: str) -> list[Gtk.Widget]:
        draft = self.ctx.draft
        scope = self.ctx.scope
        mode = draft.mode(scope, name)
        title = health.section_title(name) if len(self.section_names) > 1 else ""
        target = common.group(title)
        if scope == COMPANY:
            switch = Adw.SwitchRow(title=sections.feature_title(name), use_markup=False, active=mode == OWN)
            switch.set_subtitle(_("On for the whole company.") if mode == OWN else
                                _("Not on: employee machines stay as they are."))

            def switched(row: Adw.SwitchRow, _param: Any) -> None:
                draft.switch(COMPANY, name, OWN if row.get_active() else OFF)
                self.changed(rebuild=True)

            switch.connect("notify::active", switched)
            target.add(switch)
        else:
            above, source = draft.above(scope, name)
            machine = scope_kind(scope) == "machine"
            if source is None:
                inherited = _("The company has not turned this on.")
            elif source == COMPANY:
                inherited = summaries.summary(name, above)
            else:
                inherited = _("From %(department)s: %(summary)s") % {
                    "department": self.ctx.scope_title(source), "summary": summaries.summary(name, above)}
            choices = [
                (INHERIT, _("Use the shared settings") if machine else _("Use the company's settings"), inherited),
                (OWN, _("Own settings for this machine") if machine else _("Own settings for this department"), ""),
                (OFF, _("Off for this machine") if machine else _("Off for this department"),
                 _("This machine stays as it is.") if machine else
                 _("Machines of this department stay as they are.")),
            ]

            def chosen(choice: str) -> None:
                if choice != draft.mode(scope, name):
                    draft.switch(scope, name, choice)
                    self.changed(rebuild=True)

            sections.radio_rows(target, choices, mode, chosen)
            if machine and scope_key(scope) not in self.ctx.machines:
                target.set_description(_("This machine is no longer in the company."))
        widgets: list[Gtk.Widget] = [target]
        if mode == OWN:
            widgets += self.editors.build(name, draft.get(scope, name))
        return widgets

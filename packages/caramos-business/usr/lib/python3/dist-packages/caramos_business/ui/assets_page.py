"""Tài sản (PROTOCOL.md part 3, "Asset lifecycle and handover"): every asset, machines and things without a machine,
with their status and holder; each asset's details and history; the handover document; and the steps when an
employee leaves. The machine page uses the same form for its machine."""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import assets, handover, protocol, reports, text  # noqa: E402
from ..i18n import _  # noqa: E402
from . import common  # noqa: E402
from .admin_window import Context, Page  # noqa: E402
from .helper import in_thread  # noqa: E402

FILTERS = ("all",) + assets.STATES


def kind_titles() -> list[str]:
    return [_("Desktop computer"), _("Laptop"), _("Screen"), _("Printer"), _("Other")]


def state_titles() -> list[str]:
    return [_("In stock"), _("In use"), _("In repair"), _("Disposed of")]


def state_title(state: str) -> str:
    return dict(zip(assets.STATES, state_titles())).get(state, state)


def event_text(item: dict[str, Any]) -> str:
    event, note = item.get("event", ""), item.get("note", "")
    words = {"received": _("Received"), "assigned": _("Given to %s") % note if note else _("Given out"),
             "returned": _("Returned"), "repair": _("Sent for repair"), "disposed": _("Disposed of"),
             "handover": _("Handover document printed"), "note": note}.get(event, event)
    if event in ("received", "returned", "repair", "disposed", "handover") and note:
        words = f"{words}: {note}"
    return words


def leaver_titles() -> list[tuple[str, str]]:
    return [("returned", _("The machine is back")), ("archived", _("Their folder on the server is archived")),
            ("department", _("They are out of the department")), ("in_stock", _("The machine is in stock"))]


class AssetForm:
    """The details of one asset, its history, the handover and, for a machine, the steps when its employee leaves."""

    def __init__(self, ctx: Context, asset_id: str, saved: Any = None, history_open: bool = False) -> None:
        self.ctx = ctx
        self.asset_id = asset_id
        self.machine = not asset_id.startswith("asset-")
        self.saved = saved
        self.entry = dict(ctx.assets.get(asset_id) or {})
        self.opened = history_open
        self.expander: Adw.ExpanderRow | None = None

    def history_open(self) -> bool:
        """Whether the history is open, for the form built again after a save."""

        return self.expander.get_expanded() if self.expander is not None else self.opened

    def groups(self) -> list[Gtk.Widget]:
        entry = self.entry
        target = common.group(_("Asset details"), _("Typed by you, for the asset list. Dates as day/month/year."))
        self.rows: dict[str, Any] = {}
        if not self.machine:
            self.rows["name"] = common.entry_row(_("Name"), entry.get("name", ""))
            target.add(self.rows["name"])
        self.kind = Adw.ComboRow(title=_("Kind"), use_markup=False, model=Gtk.StringList.new(kind_titles()))
        self.kind.set_selected(assets.KINDS.index(entry.get("kind", "computer")))
        target.add(self.kind)
        self.state = Adw.ComboRow(title=_("Status"), use_markup=False, model=Gtk.StringList.new(state_titles()))
        self.state.set_selected(assets.STATES.index(entry.get("status", "in_use" if self.machine else "in_stock")))
        target.add(self.state)
        for key, title, value in (
                ("asset_code", _("Asset code"), entry.get("asset_code", "")),
                ("holder", _("Used by"), entry.get("holder", "")),
                ("holder_since", _("Used since"), text.vn_date(entry.get("holder_since", ""))),
                ("location", _("Location"), entry.get("location", "")),
                ("purchase_date", _("Bought on"), text.vn_date(entry.get("purchase_date", ""))),
                ("price_vnd", _("Price (đồng)"), text.money(entry.get("price_vnd")).replace(" đ", "")),
                ("warranty_until", _("Warranty until"), text.vn_date(entry.get("warranty_until", ""))),
                ("note", _("Note"), entry.get("note", ""))):
            self.rows[key] = common.entry_row(title, value)
            target.add(self.rows[key])
        buttons = Gtk.Box(spacing=8, margin_top=12)
        buttons.append(common.button(_("Save the asset details"), self.save))
        buttons.append(common.button(_("Print a handover document…"),
                                     lambda: handover_dialog(self.ctx, [self.asset_id])))
        target.add(buttons)
        widgets: list[Gtk.Widget] = [target]
        history = [item for item in entry.get("history") or [] if isinstance(item, dict)]
        log = common.group(_("History"))
        if history:
            expander = Adw.ExpanderRow(title=_("What happened to it"), use_markup=False, expanded=self.opened,
                                       subtitle=text.sentence([event_text(history[-1]),
                                                               text.clock(history[-1].get("time", ""))]))
            self.expander = expander
            for item in reversed(history):
                expander.add_row(common.row(event_text(item), text.sentence([
                    text.clock(item.get("time", "")), _("by %s") % item["by"] if item.get("by") else ""])))
            log.add(expander)
        else:
            log.add(common.row(_("Nothing yet"), _("Changes of status and holder are written here.")))
        note = common.entry_row(_("Add a note to the history"))
        note.connect("entry-activated", lambda row: self.add_note(row))
        log.add(note)
        widgets.append(log)
        if self.machine:
            widgets.append(self.leaver_group())
        return widgets

    def leaver_group(self) -> Adw.PreferencesGroup:
        """"Nhân viên nghỉ việc": the steps, kept with the asset."""

        done = set(self.entry.get("leaver") or [])
        target = common.group(_("An employee leaves"), _("The steps when the person using this machine leaves the "
                                                         "company. Tick each one when it is done."))
        for key, title in leaver_titles():
            check = Gtk.CheckButton(active=key in done, valign=Gtk.Align.CENTER)
            row = common.row(title)
            row.add_prefix(check)
            row.set_activatable_widget(check)
            check.connect("toggled", lambda button, step=key: self.step(step, button.get_active()))
            target.add(row)
        return target

    def values(self) -> dict[str, Any] | None:
        """The form as the helper takes it, or None (after saying what is wrong)."""

        values: dict[str, Any] = {key: row.get_text().strip() for key, row in self.rows.items()}
        for key in ("purchase_date", "warranty_until", "holder_since"):
            date = text.iso_date(values[key])
            if date is None:
                self.rows[key].add_css_class("error")
                self.ctx.toast(_("Write dates as day/month/year, such as 15/3/2024."))
                return None
            self.rows[key].remove_css_class("error")
            values[key] = date
        try:
            values["price_vnd"] = text.parse_money(values["price_vnd"])
        except ValueError:
            self.rows["price_vnd"].add_css_class("error")
            self.ctx.toast(_("The price is a whole number of đồng."))
            return None
        self.rows["price_vnd"].remove_css_class("error")
        values["kind"] = assets.KINDS[self.kind.get_selected()]
        values["status"] = assets.STATES[self.state.get_selected()]
        if self.entry.get("leaver"):
            values["leaver"] = list(self.entry["leaver"])
        try:
            assets.validate(values, machine_id=self.asset_id if self.machine else None)
        except protocol.ProtocolError as exc:
            self.ctx.toast(str(exc))
            return None
        return values

    def send(self, values: dict[str, Any], message: str) -> None:
        def done(ok: bool, answer: dict[str, Any]) -> None:
            if ok:
                self.ctx.reload()
                self.entry = dict(self.ctx.assets.get(self.asset_id) or {})
                self.ctx.toast(message)
                if self.saved:
                    self.saved()
            else:
                self.ctx.toast(answer.get("error", _("Could not save.")), 8)

        self.ctx.helper(["asset", self.asset_id], done, json.dumps(values, ensure_ascii=False))

    def save(self) -> None:
        values = self.values()
        if values is not None:
            self.send(values, _("Asset details saved."))

    def add_note(self, row: Adw.EntryRow) -> None:
        note = row.get_text().strip()
        values = self.values()
        if not note or values is None:
            return
        values["add_event"] = {"event": "note", "note": note[:300]}
        row.set_text("")
        self.send(values, _("Note added."))

    def step(self, key: str, on: bool) -> None:
        steps = [item for item in self.entry.get("leaver") or [] if item != key] + ([key] if on else [])
        self.entry["leaver"] = steps
        values = self.values()
        if values is None:
            return
        values["leaver"] = steps
        if on:
            title = dict(leaver_titles())[key]
            if key == "in_stock" and values["status"] != "in_stock":
                # The machine is back in stock: its status says so, and the history has the change with the step.
                values["status"] = "in_stock"
                values["add_event"] = {"event": "returned", "note": title}
            else:
                values["add_event"] = {"event": "note", "note": title}
        self.send(values, _("Saved."))


class AssetsPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx, _("Assets"), "assets")
        self.filter = "all"
        self.chosen: set[str] = set()
        self.header.pack_end(common.button(_("Add an asset…"), self.add_asset))
        self.built = False

    def build(self) -> None:
        self.clear()
        self.body.append(common.label(_("Every machine of the company, and the things without one: screens, printers, "
                                        "machines not paired. Tick several to print one handover document."),
                                      "paragraph"))
        controls = Gtk.Box(spacing=8)
        search = Gtk.SearchEntry(placeholder_text=_("Search assets or people"), hexpand=True)
        search.connect("search-changed", lambda entry: self.searched(entry.get_text()))
        controls.append(search)
        drop = Gtk.DropDown.new_from_strings([_("Every status")] + state_titles())
        drop.connect("notify::selected", lambda widget, _p: self.filtered(FILTERS[widget.get_selected()]))
        controls.append(drop)
        self.body.append(controls)
        self.list_group = common.group(_("Assets"))
        self.handover_button = common.button(_("Print a handover document…"), self.print_chosen)
        self.list_group.set_header_suffix(self.handover_button)
        self.list_rows = common.Rows(self.list_group)
        self.body.append(self.list_group)
        self.query = ""
        self.built = True

    def refresh(self, force: bool = False) -> None:
        if not self.built:
            self.build()
        if force:
            self.forget_signatures()
        self.refresh_list()

    def searched(self, query: str) -> None:
        self.query = text.fold(query.strip())
        self.refresh_list()

    def filtered(self, value: str) -> None:
        self.filter = value
        self.refresh_list()

    def refresh_list(self) -> None:
        listed = assets.rows(self.ctx.machines, self.ctx.assets)
        shown = []
        for item in listed:
            entry = item["entry"]
            if self.filter != "all" and entry.get("status") != self.filter:
                continue
            if self.query and not all(word in text.fold(" ".join([item["name"], entry.get("holder", ""),
                                                                    entry.get("asset_code", ""),
                                                                    entry.get("location", "")]))
                                      for word in self.query.split()):
                continue
            parts = [state_title(entry.get("status", "")), entry.get("holder", "") and
                     _("used by %s") % entry["holder"], entry.get("asset_code", ""), entry.get("location", "")]
            shown.append((item["id"], item["name"], text.sentence(parts)))
        self.handover_button.set_sensitive(bool(self.chosen))
        if not self.differs("list", (shown, sorted(self.chosen))):
            return
        self.list_rows.clear()
        if not shown:
            self.list_rows.add(common.row(_("No asset matches.") if listed else _("No asset yet"),
                                          "" if listed else _("Machines appear when they are paired; add other things "
                                                              "with Add an asset.")))
        for asset_id, name, sentence in shown:
            row = common.row(name, sentence, activatable=True)
            check = Gtk.CheckButton(active=asset_id in self.chosen, valign=Gtk.Align.CENTER)
            check.update_property([Gtk.AccessibleProperty.LABEL], [_("Choose %s") % name])
            check.connect("toggled", lambda button, key=asset_id: self.choose(key, button.get_active()))
            row.add_prefix(check)
            row.connect("activated", lambda _row, key=asset_id: self.open_asset(key))
            self.list_rows.add(row)
        self.list_group.set_description(_("%d chosen.") % len(self.chosen) if self.chosen else "")

    def choose(self, asset_id: str, on: bool) -> None:
        if on:
            self.chosen.add(asset_id)
        else:
            self.chosen.discard(asset_id)
        self.handover_button.set_sensitive(bool(self.chosen))
        self.list_group.set_description(_("%d chosen.") % len(self.chosen) if self.chosen else "")

    def print_chosen(self) -> None:
        handover_dialog(self.ctx, sorted(self.chosen))

    def open_asset(self, asset_id: str) -> None:
        if not self.built:
            self.build()
        if not asset_id.startswith("asset-") and asset_id in self.ctx.machines:
            self.ctx.view.show_page("machines")
            self.ctx.view.page("machines").open_machine(asset_id)
            return
        detail = AssetDetail(self.ctx, asset_id)
        detail.refresh(force=True)
        self.ctx.view.push(detail.navigation_page)

    def add_asset(self) -> None:
        name = common.entry_row(_("Name, such as Màn hình Dell 24 inch"))
        kind = Adw.ComboRow(title=_("Kind"), use_markup=False, model=Gtk.StringList.new(kind_titles()))
        kind.set_selected(assets.KINDS.index("monitor"))
        code = common.entry_row(_("Asset code"))
        location = common.entry_row(_("Location"))

        def add() -> None:
            values = {"name": name.get_text().strip(), "kind": assets.KINDS[kind.get_selected()],
                      "asset_code": code.get_text().strip(), "location": location.get_text().strip(),
                      "status": "in_stock", "holder": "", "purchase_date": "", "price_vnd": None,
                      "warranty_until": "", "note": ""}

            def done(ok: bool, answer: dict[str, Any]) -> None:
                if ok:
                    self.ctx.reload()
                    self.refresh(force=True)
                    self.open_asset(answer.get("id", ""))
                else:
                    self.ctx.toast(answer.get("error", _("Could not save.")), 8)

            self.ctx.helper(["asset-new"], done, json.dumps(values, ensure_ascii=False))

        common.form_dialog(self.ctx.window, _("Add an asset"), _("Something the company owns that has no paired "
                                                                 "machine. Its other details come next."),
                           [name, kind, code, location], _("Add"), add,
                           lambda: 0 < len(name.get_text().strip()) <= 100)


class AssetDetail(Page):
    def __init__(self, ctx: Context, asset_id: str) -> None:
        entry = ctx.assets.get(asset_id) or {}
        super().__init__(ctx, assets.asset_name(asset_id, entry, ctx.machines), f"asset-{asset_id}")
        self.asset_id = asset_id

    def refresh(self, force: bool = False) -> None:
        if not force:
            return
        restore = common.keep_place(self.body)  # as on a machine's page: a save does not move the page
        history_open = self.form.history_open() if getattr(self, "form", None) is not None else False
        self.clear()
        if self.asset_id not in self.ctx.assets:
            self.body.append(common.status_page("drive-multidisk-symbolic", _("This asset is no longer listed")))
            return
        self.form = AssetForm(self.ctx, self.asset_id, saved=lambda: self.refresh(force=True), history_open=history_open)
        for widget in self.form.groups():
            self.body.append(widget)
        restore()


# -- the handover document ---------------------------------------------------------------------------------------------

def handover_dialog(ctx: Context, asset_ids: list[str]) -> None:
    """Asks for the names, titles and reason, then saves the filled handover document (and a PDF when it can)."""

    if not asset_ids:
        return
    fields = [("TEN_CONG_TY", _("Company name")), ("SO", _("Number, such as 12/BB-TS")),
              ("DIA_DIEM", _("Place, such as Hà Nội")), ("BEN_GIAO", _("Handed over by (name)")),
              ("CHUC_VU_GIAO", _("Position of who hands over")), ("BEN_NHAN", _("Received by (name)")),
              ("CHUC_VU_NHAN", _("Position of who receives")), ("LY_DO", _("Reason, such as Nhân viên mới"))]
    rows = {key: common.entry_row(title) for key, title in fields}
    first = ctx.assets.get(asset_ids[0]) or {}
    if first.get("holder"):
        rows["BEN_NHAN"].set_text(first["holder"])
    pdf = Adw.SwitchRow(title=_("Save a PDF too"), use_markup=False)
    can_pdf = reports.soffice() is not None
    pdf.set_active(can_pdf)
    pdf.set_sensitive(can_pdf)
    pdf.set_subtitle("" if can_pdf else _("Needs LibreOffice: install it from App Center."))
    names = [assets.asset_name(key, ctx.assets.get(key), ctx.machines) for key in asset_ids]

    def chosen() -> None:
        values = {key: row.get_text().strip() for key, row in rows.items()}
        values.update(handover.date_values(datetime.date.today()))
        save_handover(ctx, asset_ids, values, pdf.get_active())

    common.form_dialog(ctx.window, _("Print a handover document"),
                       _("For %s. Empty fields are left as dotted lines, to fill in by hand.") % ", ".join(names),
                       list(rows.values()) + [pdf], _("Choose where to save…"), chosen)


def save_handover(ctx: Context, asset_ids: list[str], values: dict[str, str], with_pdf: bool) -> None:
    rows = [handover.asset_row(index, assets.asset_name(key, ctx.assets.get(key), ctx.machines),
                               ctx.assets.get(key) or {"kind": "computer"},
                               ctx.inventory(key) if not key.startswith("asset-") else None)
            for index, key in enumerate(asset_ids, start=1)]
    try:
        data = handover.fill(values, rows)
    except handover.HandoverError as exc:
        ctx.toast(str(exc), 8)
        return
    dialog = Gtk.FileDialog(title=_("Save the handover document"),
                            initial_name=f"bien-ban-ban-giao-{datetime.date.today():%Y-%m-%d}.docx")

    def saved(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            path = Path(source.save_finish(result).get_path())
        except (GLib.Error, TypeError):
            return
        if path.suffix.lower() != ".docx":
            path = path.with_suffix(".docx")
        try:
            path.write_bytes(data)
        except OSError as exc:
            ctx.toast(_("Could not write %(file)s: %(error)s") % {"file": path.name, "error": exc.strerror}, 8)
            return
        record_handover(ctx, asset_ids, values.get("BEN_NHAN", ""))
        if not with_pdf:
            ctx.toast(_("Saved %s.") % path.name)
            return
        ctx.toast(_("Saved %s. Making the PDF…") % path.name)

        def converted(made: Path | None, error: Exception | None) -> None:
            ctx.toast(str(error) if error else _("Saved %s.") % made.name, 8 if error else 4)

        in_thread(lambda: reports.to_pdf(path, path.with_suffix(".pdf")), converted)

    dialog.save(ctx.window, None, saved)


def record_handover(ctx: Context, asset_ids: list[str], receiver: str) -> None:
    """The handover goes into each asset's history (one helper run per asset, in turn)."""

    queue = list(asset_ids)

    def next_one(*_answer: Any) -> None:
        if not queue:
            ctx.reload()
            return
        asset_id = queue.pop(0)
        entry = dict(ctx.assets.get(asset_id) or {})
        if not asset_id.startswith("asset-"):
            entry.setdefault("kind", "computer")
            entry.setdefault("status", "in_use")
        entry["add_event"] = {"event": "handover", "note": _("to %s") % receiver if receiver else ""}
        ctx.helper(["asset", asset_id], next_one, json.dumps(entry, ensure_ascii=False))

    next_one()

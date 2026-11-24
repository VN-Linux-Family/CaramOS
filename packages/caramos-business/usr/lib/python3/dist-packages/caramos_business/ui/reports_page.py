"""The two report pages of 0.3 (PROTOCOL.md part 3): Bản quyền phần mềm, the apps on the machines by kind of licence
against the licences the company bought; and Báo cáo an toàn, each machine's security as it last reported, company
totals, the activity log of a period and the paragraph for the internal labour rules. Both export to Excel and PDF;
the exported files are Vietnamese documents (reports.py)."""

from __future__ import annotations

import datetime
import json
import tempfile
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .. import admin, health, licences, reports, security, summaries, text  # noqa: E402
from ..i18n import _, ngettext  # noqa: E402
from . import common  # noqa: E402
from .admin_window import Context, Page  # noqa: E402
from .helper import in_thread  # noqa: E402


def class_title(name: str) -> str:
    return {"free": _("Free software"), "freeware": _("Free of charge"), "commercial": _("Commercial"),
            "unknown": _("Not known")}[name]


def class_sentence(name: str) -> str:
    return {"free": _("Open source under a free licence: companies may use it."),
            "freeware": _("Free of charge but closed, under its maker's terms."),
            "commercial": _("Companies need a bought licence."),
            "unknown": _("Its licence could not be told: check it with its maker.")}[name]


def export_buttons(page: Page, xlsx: Any, pdf: Any) -> None:
    """"Xuất Excel" and "Xuất PDF" in the header bar."""

    page.header.pack_end(common.button(_("Export PDF…"), pdf))
    page.header.pack_end(common.button(_("Export Excel…"), xlsx))


def save_dialog(ctx: Context, title: str, name: str, write: Any, pdf: bool) -> None:
    """Asks where to save; write(path) makes the XLSX. For a PDF the XLSX is made aside and converted."""

    if pdf and reports.soffice() is None:
        ctx.toast(_("Making a PDF needs LibreOffice: install it from App Center, or export to Excel and print it to "
                    "PDF from LibreOffice."), 8)
        return
    suffix = ".pdf" if pdf else ".xlsx"
    dialog = Gtk.FileDialog(title=title, initial_name=name + suffix)

    def saved(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            path = Path(source.save_finish(result).get_path())
        except (GLib.Error, TypeError):
            return
        if path.suffix.lower() != suffix:
            path = path.with_suffix(suffix)
        try:
            if not pdf:
                write(path)
                ctx.toast(_("Saved %s.") % path.name)
                return
            folder = Path(tempfile.mkdtemp(prefix="caramos-business-"))
            source_file = folder / (path.stem + ".xlsx")
            write(source_file)
        except ImportError:
            ctx.toast(_("python3-openpyxl is missing: install it to make Excel files."), 8)
            return
        except OSError as exc:
            ctx.toast(_("Could not write %(file)s: %(error)s") % {"file": path.name, "error": exc.strerror}, 8)
            return
        ctx.toast(_("Making the PDF…"))

        def converted(made: Path | None, error: Exception | None) -> None:
            source_file.unlink(missing_ok=True)
            folder.rmdir()
            ctx.toast(str(error) if error else _("Saved %s.") % made.name, 8 if error else 4)

        in_thread(lambda: reports.to_pdf(source_file, path), converted)

    dialog.save(ctx.window, None, saved)


# -- Bản quyền phần mềm ------------------------------------------------------------------------------------------------

class LicencePage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx, _("Software licences"), "licences")
        export_buttons(self, lambda: self.export(False), lambda: self.export(True))

    def report(self) -> dict[str, Any]:
        inventories = {machine_id: self.ctx.inventory(machine_id) for machine_id in self.ctx.machines}
        return licences.report(self.ctx.machines, inventories, licences.catalog_index(), self.ctx.licence_register)

    def names(self) -> dict[str, str]:
        return {machine_id: self.ctx.machine_name(machine_id) for machine_id in self.ctx.machines}

    def refresh(self, force: bool = False) -> None:
        if not force:  # every inventory is read: only when the page is shown or changed
            return
        report = self.report()
        self.forget_signatures()
        if not self.differs("report", json.dumps(report, sort_keys=True, default=str)):
            return
        self.clear()
        self.body.append(common.label(_("The apps found on the machines, by kind of licence, against the licences the "
                                        "company bought."), "paragraph"))
        self.body.append(common.secondary(licences.DISCLAIMER, "paragraph"))
        totals = common.group(_("Summary"))
        for name in ("unknown", "commercial", "freeware", "free"):
            row = common.row(class_title(name), class_sentence(name))
            count = common.label(str(report["totals"][name]), "count", wrap=False)
            count.set_valign(Gtk.Align.CENTER)
            row.add_suffix(count)
            totals.add(row)
        if report["without_inventory"]:
            names = ", ".join(sorted(self.ctx.machine_name(key) for key in report["without_inventory"]))
            totals.set_description(ngettext(
                "%(names)s sends no list of apps: the automatic inventory is not on for it.",
                "%(names)s send no list of apps: the automatic inventory is not on for them.",
                len(report["without_inventory"])) % {"names": names})
        self.body.append(totals)
        self.body.append(self.apps_group(report))
        self.body.append(self.register_group(report))

    def apps_group(self, report: dict[str, Any]) -> Adw.PreferencesGroup:
        target = common.group(_("Apps on the machines"))
        free = [app for app in report["apps"] if app["class"] == "free"]
        others = [app for app in report["apps"] if app["class"] != "free"]
        if not report["apps"]:
            target.add(common.row(_("No app listed yet"), _("Machines list their apps when the automatic inventory is "
                                                            "on, a few minutes after they start.")))
        for app in others:
            target.add(self.app_row(app))
        if free:
            expander = Adw.ExpanderRow(title=class_title("free"), use_markup=False,
                                       subtitle=ngettext("%d app", "%d apps", len(free)) % len(free))
            for app in free:
                expander.add_row(self.app_row(app))
            target.add(expander)
        return target

    def app_row(self, app: dict[str, Any]) -> Adw.ActionRow:
        machines = sorted(self.ctx.machine_name(key) for key in app["machines"])
        parts = [class_title(app["class"]),
                 ngettext("on %(count)d machine: %(names)s", "on %(count)d machines: %(names)s", len(machines))
                 % {"count": len(machines), "names": ", ".join(machines[:6]) + ("…" if len(machines) > 6 else "")}]
        licence = app.get("licence") or ""
        if licence and licence != "unknown" and not licence.startswith("LicenseRef-"):
            parts.append(_("licence %s") % licence)
        if app.get("origin"):
            origin = reports.origin_text(app["origin"])
            if origin.startswith(("Tệp", "Bên")):  # mid-sentence; the names of distributions keep their capital
                origin = origin[0].lower() + origin[1:]
            parts.append(_("from %s") % origin)
        return common.row(app["name"], text.sentence(parts))

    def register_group(self, report: dict[str, Any]) -> Adw.PreferencesGroup:
        target = common.group(_("Licences the company bought"), _("Typed by you. Each one is compared with the number "
                                                                  "of machines that have its app."))
        target.set_header_suffix(common.button(_("Add a licence…"), lambda: self.edit_licence(None, report)))
        if not report["register"]:
            target.add(common.row(_("None yet"), _("Add the licences on your invoices, such as office suites or "
                                                   "accounting software.")))
        for entry in report["register"]:
            parts = [ngettext("for %d machine", "for %d machines", entry["seats"]) % entry["seats"],
                     ngettext("found on %d machine", "found on %d machines", entry["used"]) % entry["used"]]
            if entry["used"] > entry["seats"]:
                parts.append(ngettext("%d licence short", "%d licences short", entry["used"] - entry["seats"])
                             % (entry["used"] - entry["seats"]))
            if entry.get("expires"):
                parts.append(_("ends on %s") % text.vn_date(entry["expires"]))
            if entry.get("invoice"):
                parts.append(_("invoice %s") % entry["invoice"])
            row = common.row(entry["product"], text.sentence(parts), activatable=True)
            if entry["used"] > entry["seats"]:
                row.add_css_class("problem")
            row.add_suffix(common.icon_button("user-trash-symbolic", _("Remove"),
                                              lambda key=entry["id"]: self.remove_licence(key)))
            row.connect("activated", lambda _row, item=entry: self.edit_licence(item, report))
            target.add(row)
        return target

    def save_register(self, entries: list[dict[str, Any]]) -> None:
        def done(ok: bool, answer: dict[str, Any]) -> None:
            if ok:
                self.ctx.reload()
                self.refresh(force=True)
            else:
                self.ctx.toast(answer.get("error", _("Could not save.")), 8)

        clean = [{key: entry[key] for key in ("id", "product", "seats", "expires", "invoice", "note", "match")}
                 for entry in entries]
        self.ctx.helper(["licences"], done, json.dumps(clean, ensure_ascii=False))

    def remove_licence(self, entry_id: str) -> None:
        self.save_register([entry for entry in self.ctx.licence_register if entry.get("id") != entry_id])

    def edit_licence(self, entry: dict[str, Any] | None, report: dict[str, Any]) -> None:
        entry = entry or {}
        product = common.entry_row(_("Product, such as Microsoft Office 2021"), entry.get("product", ""))
        seats = Adw.SpinRow.new_with_range(0, 100000, 1)
        seats.set_title(_("Machines it covers"))
        seats.set_value(entry.get("seats", 1))
        expires = common.entry_row(_("Ends on (empty if it does not end)"), text.vn_date(entry.get("expires", "")))
        invoice = common.entry_row(_("Invoice"), entry.get("invoice", ""))
        apps = [(app["key"], app["name"]) for app in report["apps"]]
        app_drop = Adw.ComboRow(title=_("App on the machines"), use_markup=False, model=Gtk.StringList.new(
            [_("None")] + [name for _key, name in apps]))
        matched = (entry.get("match") or [None])[0]
        keys = [key for key, _name in apps]
        app_drop.set_selected(keys.index(matched) + 1 if matched in keys else 0)

        def valid() -> bool:
            return bool(product.get_text().strip()) and text.iso_date(expires.get_text().strip()) is not None

        def save() -> None:
            index = app_drop.get_selected()
            match = [keys[index - 1]] if index else list(entry.get("match") or [])[1:]
            new = {"id": entry.get("id") or licence_id(product.get_text(), self.ctx.licence_register),
                   "product": product.get_text().strip()[:100], "seats": int(seats.get_value()),
                   "expires": text.iso_date(expires.get_text().strip()) or "",
                   "invoice": invoice.get_text().strip()[:100], "note": entry.get("note", ""), "match": match}
            entries = [item for item in self.ctx.licence_register if item.get("id") != new["id"]] + [new]
            self.save_register(entries)

        common.form_dialog(self.ctx.window, _("Edit the licence") if entry else _("Add a licence"),
                           _("The report compares the machines it covers with the machines that have its app."),
                           [product, seats, expires, invoice, app_drop], _("Save"), save, valid)

    def export(self, pdf: bool) -> None:
        report, names = self.report(), self.names()
        save_dialog(self.ctx, _("Export the licence report"), f"bao-cao-ban-quyen-{datetime.date.today():%Y-%m-%d}",
                    lambda path: reports.write_licence_xlsx(report, names, path, self.ctx.now()), pdf)


def licence_id(product: str, register: list[dict[str, Any]]) -> str:
    base = text.fold(product).replace(" ", "-")
    base = "".join(char for char in base if char.isalnum() or char == "-").strip("-")[:30] or "ban-quyen"
    taken = {entry.get("id") for entry in register}
    candidate, number = base, 2
    while candidate in taken:
        candidate = f"{base}-{number}"
        number += 1
    return candidate


# -- Báo cáo an toàn ---------------------------------------------------------------------------------------------------

def periods() -> list[tuple[str, Any]]:
    return [(_("The last 7 days"), 7), (_("The last 30 days"), 30), (_("This month"), "month"),
            (_("Last month"), "last-month")]


def period_dates(choice: Any, today: datetime.date) -> tuple[datetime.date, datetime.date]:
    if choice == "month":
        return today.replace(day=1), today
    if choice == "last-month":
        end = today.replace(day=1) - datetime.timedelta(days=1)
        return end.replace(day=1), end
    return today - datetime.timedelta(days=choice - 1), today


class SecurityReportPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx, _("Security report"), "security_report")
        self.period = 0
        export_buttons(self, lambda: self.export(False), lambda: self.export(True))

    def table(self) -> list[dict[str, Any]]:
        return security.rows(self.ctx.machines, self.ctx.saved_policy, self.ctx.records, self.ctx.now())

    def refresh(self, force: bool = False) -> None:
        table = self.table()
        if force:
            self.forget_signatures()
        if not self.differs("report", (json.dumps(table, sort_keys=True, default=str), self.period)):
            return
        self.clear()
        self.body.append(common.label(_("Each machine's firewall, updates, screen lock, USB storage, disk encryption, "
                                        "freezing and snapshots, as it last reported."), "paragraph"))
        self.body.append(common.secondary(security.DISCLAIMER, "paragraph"))
        self.body.append(self.totals_group(table))
        self.body.append(self.machines_group(table))
        self.body.append(self.audit_group())
        self.body.append(self.rules_group())

    def totals_group(self, table: list[dict[str, Any]]) -> Adw.PreferencesGroup:
        counted = security.totals(table)
        total = counted["machines"]
        target = common.group(_("The whole company"))
        if not total:
            target.add(common.row(_("No machine yet")))
            return target
        lines = [
            (_("Firewall on"), counted["firewall_on"]),
            (_("Security updates waiting"), counted["security_waiting"]),
            (_("Security updates waiting for more than 7 days"), counted["security_late"]),
            (_("Need a restart"), counted["reboot"]),
            (_("Screen lock on"), counted["screen_lock"]),
            (_("USB storage blocked or read only"), counted["usb_limited"]),
            (_("Disk encrypted"), counted["encrypted"]),
            (_("Frozen"), counted["frozen"]),
            (_("Need a look"), counted["with_problems"]),
        ]
        for title, value in lines:
            row = common.row(title)
            count = common.label(_("%(count)d of %(total)d") % {"count": value, "total": total}, "count", wrap=False)
            count.set_valign(Gtk.Align.CENTER)
            row.add_suffix(count)
            target.add(row)
        reported = counted["reported"]
        if reported < total:
            target.set_description(ngettext("%d machine has not reported its state yet.",
                                            "%d machines have not reported their state yet.", total - reported)
                                   % (total - reported))
        return target

    def machines_group(self, table: list[dict[str, Any]]) -> Adw.PreferencesGroup:
        target = common.group(_("Each machine"))
        for item in table:
            entry = self.ctx.machines.get(item["machine_id"]) or {}
            values = entry.get("health") or {}
            problems = self.ctx.problems(item["machine_id"])
            expander = Adw.ExpanderRow(title=item["name"], use_markup=False,
                                       subtitle=problems[0].text if problems else _("Nothing to look at."))
            if problems:
                expander.add_css_class("problem")
            for title, value in machine_facts(self.ctx, item["machine_id"], values):
                expander.add_row(common.property_row(title, value))
            target.add(expander)
        return target

    def audit_lines(self) -> tuple[list[dict[str, Any]], datetime.date, datetime.date]:
        start, end = period_dates(periods()[self.period][1], self.ctx.now().date())
        return security.audit_extract(admin.read_audit(limit=5000), start, end), start, end

    def audit_group(self) -> Adw.PreferencesGroup:
        lines, start, end = self.audit_lines()
        target = common.group(_("Activity log"), _("What was done on this machine in the period: it goes into the "
                                                   "exported report."))
        combo = Adw.ComboRow(title=_("Period"), use_markup=False, model=Gtk.StringList.new(
            [title for title, _value in periods()]))
        combo.set_selected(self.period)
        combo.set_subtitle(ngettext("%(count)d entry, from %(start)s to %(end)s",
                                    "%(count)d entries, from %(start)s to %(end)s", len(lines)) % {
            "count": len(lines), "start": text.vn_date(start.isoformat()), "end": text.vn_date(end.isoformat())})

        def chosen(row: Adw.ComboRow, _param: Any) -> None:
            self.period = row.get_selected()
            GLib.idle_add(lambda: self.refresh(force=True) and False)

        combo.connect("notify::selected", chosen)
        target.add(combo)
        return target

    def rules_group(self) -> Adw.PreferencesGroup:
        paragraph = security.labour_rules_paragraph(self.ctx.saved_policy)
        target = common.group(_("For the internal labour rules"), _(
            "Staff must know the technical measures used on their machines (Law 91/2025/QH15, article 25). This "
            "paragraph lists the ones you turned on: paste it into the internal labour rules."))
        target.set_header_suffix(common.button(_("Copy"), lambda: self.copy(paragraph)))
        label = common.label(paragraph, "paragraph", selectable=True)
        label.set_margin_top(6)
        target.add(label)
        return target

    def copy(self, paragraph: str) -> None:
        display = Gdk.Display.get_default()
        if display is not None:
            display.get_clipboard().set(paragraph)
            self.ctx.toast(_("Copied."))

    def export(self, pdf: bool) -> None:
        table = self.table()
        lines, start, end = self.audit_lines()
        words = [summaries.audit_text(line, self.department_name, self.ctx.machine_name) for line in lines]
        paragraph = security.labour_rules_paragraph(self.ctx.saved_policy)
        save_dialog(self.ctx, _("Export the security report"), f"bao-cao-an-toan-{datetime.date.today():%Y-%m-%d}",
                    lambda path: reports.write_security_xlsx(table, lines, words, paragraph, start, end, path,
                                                             self.ctx.now()), pdf)

    def department_name(self, key: str) -> str:
        return (self.ctx.saved_policy.get("departments") or {}).get(key, {}).get("name", key)


def machine_facts(ctx: Context, machine_id: str, values: dict[str, Any]) -> list[tuple[str, str]]:
    """A machine's security facts in the reader's language."""

    effective = ctx.effective(machine_id)
    record = ctx.records.get(machine_id) or {}
    unknown = _("not known yet")
    facts = [(_("Firewall"), {"on": _("on"), "off": _("off")}.get(values.get("firewall"), unknown))]
    security_count = (values.get("updates") or {}).get("security")
    since = health._parse(record.get("security_since"))  # noqa: SLF001
    if security_count:
        waiting = ngettext("%d waiting", "%d waiting", security_count) % security_count
        if since:
            waiting = _("%(waiting)s, since %(day)s") % {"waiting": waiting, "day": text.vn_date(since.date().isoformat())}
    else:
        waiting = _("none waiting") if values else unknown
    facts.append((_("Security updates"), waiting))
    facts.append((_("Restart"), _("needed") if values.get("reboot_required") else _("not needed") if values else
                  unknown))
    lock = values.get("screen_lock_on")
    facts.append((_("Screen lock"), _("on") if lock is True else _("off") if lock is False else unknown))
    facts.append((_("USB storage"), {"allow": _("allowed"), "read-only": _("read only"), "block": _("blocked"),
                                      "unlocked": _("allowed for a while")}.get(values.get("usb_storage") or
                                                                                ("allow" if values else ""), unknown)))
    facts.append((_("Disk encryption"), {"luks": _("encrypted"), "none": _("not encrypted")}.get(
        values.get("encryption"), unknown)))
    if values.get("frozen"):
        frozen = _("frozen")
    elif values.get("freeze_configured"):
        frozen = _("frozen from the next restart")
    elif health.freezing(effective):
        frozen = _("not frozen yet")
    else:
        frozen = _("not frozen")
    facts.append((_("Freezing"), frozen))
    if health.freezing(effective) or values.get("last_maintenance"):
        result = summaries.maintenance_text(values.get("maintenance_result", ""), values.get("maintenance_steps"))
        facts.append((_("Last maintenance"), text.sentence([text.clock(values.get("last_maintenance") or ""), result])
                      or _("none yet")))
    if effective.get("snapshots") or values.get("last_snapshot"):
        facts.append((_("Last system snapshot"), text.join_sentence([
            text.clock(values.get("last_snapshot") or "") or _("none yet"),
            security.snapshot_space(values.get("snapshot_space_mb"))])))
    facts.append((_("Last seen"), text.ago((ctx.machines.get(machine_id) or {}).get("last_seen", ""))))
    return facts

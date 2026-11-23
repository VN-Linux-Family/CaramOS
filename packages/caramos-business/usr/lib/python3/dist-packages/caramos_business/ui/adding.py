"""Thêm máy (PROTOCOL.md part 3): the pairing code of an open pairing window, "Duyệt từng máy", the enrolment files
with their uses and "Thu hồi", and how to prepare a disk image for a computer lab. Also the machines waiting for
approval, which the machines page lists first."""

from __future__ import annotations

import datetime
import json
import time
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import GUIDE, PAIRING, pairing, protocol, text  # noqa: E402
from ..i18n import _, ngettext  # noqa: E402
from . import common  # noqa: E402
from .admin_window import Context, Page  # noqa: E402

RECENT_DAYS = 7  # tokens that ended this recently stay in the list, without "Thu hồi"


def read_window(remembered: dict[str, Any] | None) -> dict[str, Any] | None:
    """The open pairing window: pairing.json (root:sudo 0640), or the helper's last answer when it cannot be read."""

    window = pairing.read_pairing(PAIRING)
    if window is None and remembered and remembered.get("until", 0) > time.time() and PAIRING.exists():
        return remembered
    return window


def code_text(code: str) -> str:
    return f"{code[:3]} {code[3:]}"


def token_sentence(record: dict[str, Any], now: datetime.datetime) -> tuple[str, bool]:
    """(what the token is now, whether it can still add machines)."""

    usable = pairing.token_usable(record, now)
    uses = _("%(used)d of %(total)d machines added") % {"used": record.get("uses", 0),
                                                         "total": record.get("max_uses", 0)}
    expires = text.vn_date((record.get("expires") or "")[:10])
    if record.get("revoked"):
        state = _("withdrawn on %s") % text.vn_date(record["revoked"][:10])
    elif usable:
        state = _("works until %s") % expires
    elif record.get("uses", 0) >= record.get("max_uses", 0):
        state = _("used up")
    else:
        state = _("expired on %s") % expires
    parts = [_("made %s") % text.clock(record.get("created", "")), uses, state]
    if record.get("hostname_prefix"):
        parts.append(_("names start with %s") % record["hostname_prefix"])
    return text.sentence(parts), usable


def pending_rows(ctx: Context, target: common.Rows, refresh: Any) -> None:
    """A row per machine waiting for approval, with "Từ chối" and "Duyệt"."""

    for machine_id, entry in sorted(ctx.pending.items(), key=lambda item: item[1].get("paired", "")):
        machine = entry.get("machine") or {}
        via = entry.get("via", "code")
        how = _("with the pairing code") if via == "code" else _("with an enrolment file")
        subtitle = text.sentence([machine.get("ip", ""), machine.get("mac", ""),
                                  _("asked at %s") % text.clock(entry.get("paired", "")), how])
        row = common.row(machine.get("name", machine_id[:8]), subtitle)
        reject = common.button(_("Turn away"), lambda key=machine_id: decide(ctx, key, "reject", refresh))
        approve = common.button(_("Approve"), lambda key=machine_id: decide(ctx, key, "approve", refresh),
                                "suggested-action")
        row.add_suffix(reject)
        row.add_suffix(approve)
        target.add(row)


def decide(ctx: Context, machine_id: str, action: str, refresh: Any) -> None:
    name = ctx.machine_name(machine_id)

    def go() -> None:
        def done(ok: bool, answer: dict[str, Any]) -> None:
            if ok:
                ctx.reload()
                ctx.toast(_("%s joined the company.") % name if action == "approve" else
                          _("%s was turned away.") % name)
            else:
                ctx.toast(answer.get("error", _("Could not change it.")), 8)
            refresh()

        ctx.helper([action, machine_id], done)

    if action == "approve":
        go()
    else:
        common.confirm(ctx.window, _("Turn %s away?") % name,
                       _("It gets nothing from the company. To add it later, pair it again."), _("Turn away"), go,
                       destructive=True)


class AddMachinesPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx, _("Add machines"), "add-machines")
        self.remembered: dict[str, Any] | None = None
        self.timer = GLib.timeout_add_seconds(1, self.tick)
        self.navigation_page.connect("hidden", lambda _page: self.stop_timer())
        self.build()

    def stop_timer(self) -> None:
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0

    def tick(self) -> bool:
        self.refresh_code()
        return True

    def build(self) -> None:
        self.clear()
        self.code_group = common.group(_("Pairing code"), _(
            "On each employee machine, open CaramOS Business, choose Employee machine and type this code. The code is "
            "new each time, works for 10 minutes, and after 20 wrong tries adding stops by itself."))
        self.code_label = common.label("", "pairing-code", selectable=True, xalign=0.5)
        self.code_hint = common.secondary("", xalign=0.5)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=12, margin_bottom=12)
        box.append(self.code_label)
        box.append(self.code_hint)
        self.code_box = box
        self.code_group.add(box)
        self.code_button = common.button(_("Show a pairing code"), self.toggle, "suggested-action")
        self.code_button.set_halign(Gtk.Align.START)
        self.code_group.add(self.code_button)
        self.body.append(self.code_group)
        approval = common.group()
        self.approve_switch = Adw.SwitchRow(title=_("Approve each new machine"), use_markup=False,
                                            active=self.ctx.options["approve_machines"])
        self.approve_switch.set_subtitle(_("A new machine waits until you press Approve, and gets nothing from the "
                                           "company before."))
        self.approve_handler = self.approve_switch.connect("notify::active", self.approval_switched)
        approval.add(self.approve_switch)
        self.body.append(approval)
        self.files_group = common.group(_("Enrolment files"), _(
            "Add many machines without typing a code: copy the file onto a USB drive and plug it into each machine, "
            "or put it into a computer lab's disk image. Whoever holds the file can add machines until it expires or "
            "its uses run out: keep it like a key."))
        self.files_group.set_header_suffix(common.button(_("Make an enrolment file…"), self.make_file))
        self.file_rows = common.Rows(self.files_group)
        self.body.append(self.files_group)
        lab = common.group(_("Computer labs and disk images"))
        lab.add(common.row(_("Prepare one machine, then copy its disk"),
                           _("Set up one machine as you want it. On it, open CaramOS Business and choose Prepare a disk "
                             "image, with an enrolment file. Shut it down and copy its disk to the others, for example "
                             "with Clonezilla. Each copy joins the company by itself when it first starts.")))
        self.body.append(lab)
        self.body.append(common.link_label(_("Each step is in the guide."), _("Read the guide"),
                                           GUIDE.as_uri(), "dim-label", "secondary"))
        self.refresh_code()
        self.refresh_files()

    def refresh(self, force: bool = False) -> None:
        if force:
            self.forget_signatures()
        self.refresh_code()
        self.refresh_files()
        wanted = self.ctx.options["approve_machines"]
        if self.approve_switch.get_active() != wanted:
            with GObjectBlock(self.approve_switch, self.approve_handler):
                self.approve_switch.set_active(wanted)

    def refresh_code(self) -> None:
        window = read_window(self.remembered)
        self.code_box.set_visible(window is not None)
        if window is None:
            self.code_button.set_label(_("Show a pairing code"))
            self.code_button.add_css_class("suggested-action")
            return
        self.code_button.set_label(_("Stop adding"))
        self.code_button.remove_css_class("suggested-action")
        self.code_label.set_label(code_text(window["code"]))
        minutes = max(1, int((window["until"] - time.time()) // 60) + 1)
        self.code_hint.set_label(ngettext("Works for %d more minute", "Works for %d more minutes", minutes) % minutes)

    def toggle(self) -> None:
        action = "close" if read_window(self.remembered) is not None else "open"

        def done(ok: bool, answer: dict[str, Any]) -> None:
            if not ok:
                self.ctx.toast(answer.get("error", _("Could not change it.")))
            elif action == "open":
                self.remembered = {"code": answer.get("code", ""), "until": answer.get("until", 0)}
            else:
                self.remembered = None
            self.refresh_code()

        self.ctx.helper(["pairing", action], done)

    def approval_switched(self, row: Adw.SwitchRow, _param: Any) -> None:
        wanted = row.get_active()

        def done(ok: bool, answer: dict[str, Any]) -> None:
            if ok:
                self.ctx.reload()
                self.ctx.toast(_("Each new machine now waits for approval.") if wanted else
                               _("New machines join without approval."))
            else:
                self.ctx.toast(answer.get("error", _("Could not change it.")), 8)
                with GObjectBlock(row, self.approve_handler):
                    row.set_active(not wanted)

        self.ctx.helper(["options"], done, json.dumps({"approve_machines": wanted}))

    # - enrolment files -

    def refresh_files(self) -> None:
        now = self.ctx.now()
        departments = self.ctx.saved_policy.get("departments") or {}
        shown = []
        for token_id, record in sorted(self.ctx.tokens.items(), key=lambda item: item[1].get("created", ""),
                                       reverse=True):
            sentence, usable = token_sentence(record, now)
            ended = record.get("revoked") or record.get("expires", "")
            if not usable and (admin_parse(ended) or now) < now - datetime.timedelta(days=RECENT_DAYS):
                continue
            department = (departments.get(record.get("department")) or {}).get("name") if record.get("department") \
                else ""
            title = _("For %s") % department if department else _("In no department")
            shown.append((token_id, title, sentence, usable))
        if not self.differs("files", shown):
            return
        self.file_rows.clear()
        if not shown:
            self.file_rows.add(common.row(_("No enrolment file yet")))
        for token_id, title, sentence, usable in shown:
            row = common.row(title, sentence)
            if usable:
                row.add_suffix(common.button(_("Withdraw"), lambda key=token_id: self.withdraw(key)))
            else:
                row.add_css_class("dim-label")
            self.file_rows.add(row)

    def withdraw(self, token_id: str) -> None:
        def go() -> None:
            def done(ok: bool, answer: dict[str, Any]) -> None:
                if ok:
                    self.ctx.reload()
                    self.refresh_files()
                    self.ctx.toast(_("The enrolment file no longer works."))
                else:
                    self.ctx.toast(answer.get("error", _("Could not change it.")), 8)

            self.ctx.helper(["enroll-token", "revoke", token_id], done)

        common.confirm(self.ctx.window, _("Withdraw this enrolment file?"),
                       _("It stops adding machines at once, wherever its copies are. Machines it added stay."),
                       _("Withdraw"), go, destructive=True)

    def make_file(self) -> None:
        departments = self.ctx.saved_policy.get("departments") or {}
        ids = sorted(departments, key=lambda key: text.fold(departments[key].get("name", key)))
        department = Adw.ComboRow(title=_("Department"), use_markup=False, model=Gtk.StringList.new(
            [_("In no department")] + [departments[key].get("name", key) for key in ids]))
        days = Adw.SpinRow.new_with_range(1, pairing.MAX_TOKEN_DAYS, 1)
        days.set_title(_("Works for (days)"))
        days.set_value(7)
        uses = Adw.SpinRow.new_with_range(1, pairing.MAX_TOKEN_USES, 1)
        uses.set_title(_("Machines it can add"))
        uses.set_value(30)
        prefix = common.entry_row(_("Machine names start with (for disk images, optional)"))

        def valid() -> bool:
            value = prefix.get_text().strip()
            good = not value or protocol.HOSTNAME_PREFIX.match(value) is not None
            if good:
                prefix.remove_css_class("error")
            else:
                prefix.add_css_class("error")
            return good

        def chosen() -> None:
            index = department.get_selected()
            options = {"department": ids[index - 1] if index else None, "days": int(days.get_value()),
                       "max_uses": int(uses.get_value()), "hostname_prefix": prefix.get_text().strip() or None}
            self.save_file(options)

        common.form_dialog(self.ctx.window, _("Make an enrolment file"),
                           _("Whoever holds this file can add machines to the company until it expires or its uses "
                             "run out. With a name prefix, each copy of a disk image gets its own name, such as "
                             "phong-may-3f2a1c."), [department, days, uses, prefix], _("Choose where to save…"),
                           chosen, valid)

    def save_file(self, options: dict[str, Any]) -> None:
        dialog = Gtk.FileDialog(title=_("Save the enrolment file"), initial_name="caramos-business-enroll.json")

        def saved(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                path = Path(source.save_finish(result).get_path())
            except (GLib.Error, TypeError):
                return

            def done(ok: bool, answer: dict[str, Any]) -> None:
                if ok:
                    self.ctx.reload()
                    self.refresh_files()
                    self.ctx.toast(_("Saved %s.") % path.name)
                else:
                    self.ctx.toast(answer.get("error", _("Could not save.")), 8)

            self.ctx.helper(["enroll-token", "create", str(path)], done, json.dumps(options))

        dialog.save(self.ctx.window, None, saved)


def admin_parse(value: Any) -> datetime.datetime | None:
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.astimezone()


class GObjectBlock:
    """Blocks a signal handler while a value is set from the program."""

    def __init__(self, widget: Any, handler: int) -> None:
        self.widget, self.handler = widget, handler

    def __enter__(self) -> None:
        self.widget.handler_block(self.handler)

    def __exit__(self, *_exc: Any) -> None:
        self.widget.handler_unblock(self.handler)

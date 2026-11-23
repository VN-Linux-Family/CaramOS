"""Nhật ký (the newest 500 lines of the audit log) and Sao lưu (a backup another machine can restore)."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import admin, backup, summaries, text  # noqa: E402
from ..i18n import _  # noqa: E402
from . import common  # noqa: E402
from .admin_window import Context, Page  # noqa: E402

AUDIT_LINES = 500


class AuditPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx, _("Activity log"), "audit")
        self.shown: list[Any] | None = None

    def refresh(self, force: bool = False) -> None:
        lines = admin.read_audit(limit=AUDIT_LINES)
        if not force and lines == self.shown:
            return
        self.shown = lines
        self.clear()
        self.body.append(common.label(_("Every change made here, newest first: who made it and when. Registrations "
                                        "of new machines are written by the machine itself."), "paragraph"))
        target = common.group(_("Changes"))
        if not lines:
            target.add(common.row(_("Nothing yet.")))
        departments = self.ctx.draft.departments()
        for line in lines:
            who = line.get("user") or _("automatic")
            summary = summaries.audit_text(line, lambda key: departments.get(key, {}).get("name", key),
                                           self.ctx.machine_name)
            target.add(common.row(summary, f"{text.clock(line.get('time', ''))}, {who}"))
        if len(lines) >= AUDIT_LINES:
            target.set_description(_("The newest 500 changes."))
        self.body.append(target)


class BackupPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__(ctx, _("Backup"), "backup")

    def refresh(self, force: bool = False) -> None:
        if not force:
            return
        self.clear()
        self.body.append(common.label(_("A backup holds this machine's keys and every setting, the machine list, the "
                                        "asset details and the activity log. If this machine breaks, install CaramOS "
                                        "Business on another one and choose Restore from a backup: the employee "
                                        "machines find the new one by themselves, without pairing again."),
                                      "paragraph"))
        target = common.group(_("Make a backup"))
        target.add(common.row(_("Keep the file and its passphrase in a safe place"),
                              _("For example on a USB drive in a locked drawer. Whoever has both can manage the "
                                "employee machines. Without the passphrase the backup cannot be opened.")))
        make = common.button(_("Make a backup…"), self.make, "suggested-action")
        make.set_halign(Gtk.Align.START)
        make.set_margin_top(12)
        target.add(make)
        self.body.append(target)
        lines = [line for line in admin.read_audit(limit=200) if line.get("action") == "backup"]
        if lines:
            last = common.group(_("Last backup"))
            last.add(common.row(summaries.audit_text(lines[0], lambda key: key, self.ctx.machine_name),
                                text.clock(lines[0].get("time", ""))))
            self.body.append(last)

    def make(self) -> None:
        first = Adw.PasswordEntryRow(title=_("Passphrase"))
        second = Adw.PasswordEntryRow(title=_("The passphrase again"))

        def valid() -> bool:
            return len(first.get_text()) >= backup.MIN_PASSPHRASE and first.get_text() == second.get_text()

        common.form_dialog(self.ctx.window, _("Make a backup"),
                           _("At least 8 characters. Write it down: it cannot be found again."), [first, second],
                           _("Choose where…"), lambda: self.choose_file(first.get_text()), valid)

    def choose_file(self, passphrase: str) -> None:
        dialog = Gtk.FileDialog(title=_("Save the backup"),
                                initial_name=f"caramos-doanh-nghiep-{datetime.date.today():%Y-%m-%d}.cbkp")

        def saved(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                path = Path(source.save_finish(result).get_path())
            except (GLib.Error, TypeError):
                return

            def done(ok: bool, answer: dict[str, Any]) -> None:
                if ok:
                    self.ctx.toast(_("Backup saved: %s.") % path.name, 6)
                    self.refresh(force=True)
                else:
                    self.ctx.toast(answer.get("error", _("Could not make the backup.")), 8)

            self.ctx.helper(["backup", str(path)], done, passphrase + "\n")

        dialog.save(self.ctx.window, None, saved)

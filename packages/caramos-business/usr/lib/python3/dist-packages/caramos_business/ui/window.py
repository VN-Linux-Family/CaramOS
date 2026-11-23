"""The window of CaramOS Doanh nghiệp.

A machine without a role first chooses one: the admin machine (máy quản lý), an employee machine (máy nhân viên), or
taking over as the admin machine from a backup. Then the admin sees the management pages (admin_window.py) and an
employee the connection's state (employee.py).

Everything that needs root goes through caramos-business-helper (ui/helper.py)."""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import ADMIN, AGENT_STATE, EMPLOYEE, backup, role  # noqa: E402
from ..i18n import _  # noqa: E402
from . import common  # noqa: E402
from .helper import run_helper  # noqa: E402


class Window(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title=_("CaramOS Business"))
        self.set_size_request(360, 420)  # the narrowest the pages work at (the breakpoints need a minimum)
        self.toasts = Adw.ToastOverlay()
        self.set_content(self.toasts)
        self.show_page()

    def toast(self, text: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=4))

    def show_page(self) -> None:
        current = role()
        if current == ADMIN:
            from .admin_window import AdminView

            self.set_default_size(1120, 780)
            page: Gtk.Widget = AdminView(self)
        elif current == EMPLOYEE or (AGENT_STATE / "admin.json").exists():
            from .employee import EmployeeView

            self.set_default_size(720, 640)
            page = EmployeeView(self)
        else:
            self.set_default_size(720, 600)
            page = RolePage(self)
        self.toasts.set_child(page)


class RolePage(Adw.Bin):
    def __init__(self, window: Window) -> None:
        super().__init__()
        self.window = window
        body = common.page_box()
        intro = Gtk.Box(spacing=16)
        intro.append(common.logo(48))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
        texts.append(common.label(_("CaramOS Business"), "page-title"))
        texts.append(common.label(_("The company's admin machine manages the employee machines on the network: "
                                    "wallpaper, folders, browsers, printers, Wi-Fi, apps, the power schedule, USB and "
                                    "more. Every feature is off until the admin turns it on."), "paragraph"))
        intro.append(texts)
        body.append(intro)
        choices = common.group(_("Which one is this machine?"))
        for icon, title, subtitle, handler in (
                ("computer-symbolic", _("Admin machine"),
                 _("The machine of the person in charge: one per company, on during working hours"), self.choose_admin),
                ("system-users-symbolic", _("Employee machine"),
                 _("Takes the company's settings from the admin machine"), self.choose_employee),
                ("document-revert-symbolic", _("Restore the admin machine from a backup"),
                 _("When the old admin machine broke: the employee machines find this one by themselves"),
                 self.restore)):
            row = common.row(title, subtitle, activatable=True, icon=icon)
            row.connect("activated", lambda _row, run=handler: run())
            choices.add(row)
        body.append(choices)
        self.set_child(common.toolbar(common.scrolled(common.clamp(body))))

    def choose_admin(self) -> None:
        def done(ok: bool, answer: dict[str, Any]) -> None:
            if ok:
                self.window.show_page()
            else:
                self.window.toast(answer.get("error", _("Could not make this the admin machine.")))

        run_helper(["role", "admin"], done)

    def choose_employee(self) -> None:
        from .employee import EmployeeView

        self.window.toasts.set_child(EmployeeView(self.window))

    def restore(self) -> None:
        filters = Gio.ListStore.new(Gtk.FileFilter)
        backups = Gtk.FileFilter(name=_("CaramOS Business backups (.cbkp)"))
        backups.add_suffix("cbkp")
        everything = Gtk.FileFilter(name=_("All files"))
        everything.add_pattern("*")
        filters.append(backups)
        filters.append(everything)
        dialog = Gtk.FileDialog(title=_("Choose the backup"), filters=filters)

        def opened(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                path = source.open_finish(result).get_path()
            except (GLib.Error, TypeError):
                return
            passphrase = Adw.PasswordEntryRow(title=_("Passphrase"))

            def go() -> None:
                def done(ok: bool, answer: dict[str, Any]) -> None:
                    if ok:
                        self.window.show_page()
                        self.window.toast(_("This machine is the admin machine now."))
                    else:
                        self.window.toast(answer.get("error", _("Could not restore.")))

                run_helper(["restore", path], done, passphrase.get_text() + "\n")

            common.form_dialog(self.window, _("Restore from a backup"),
                               _("The passphrase chosen when the backup was made."), [passphrase], _("Restore"), go,
                               lambda: len(passphrase.get_text()) >= backup.MIN_PASSPHRASE)

        dialog.open(self.window, None, opened)

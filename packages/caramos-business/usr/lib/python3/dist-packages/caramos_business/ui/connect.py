"""caramos-business --connect URL: signing in to the company's shared folder, for the agent's session part.

The agent opens it when the share asks for a password. GTK's own mount dialog was not used: it starts on "Anonymous",
which a company share refuses, and with "Remember forever" GVfs stores the password in the default keyring before it
finishes the mount; on a machine whose keyring does not open (seen on a CaramOS 1.3.10 VM), the mount then waits
forever. Here the employee types only their account and password, and "remember" keeps the password in the keyring
only when the default keyring is open now, otherwise until logout.

The window quits once the share is mounted, or when the employee chooses Later; the agent sees which.
"""

from __future__ import annotations

import re

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import protocol  # noqa: E402
from ..i18n import _  # noqa: E402

SECRETS = "org.freedesktop.secrets"


def keyring_open(bus: Gio.DBusConnection | None = None) -> bool:
    """Whether the session's default keyring can keep a password without asking anything now."""

    try:
        bus = bus or Gio.bus_get_sync(Gio.BusType.SESSION)
        alias = bus.call_sync(SECRETS, "/org/freedesktop/secrets", "org.freedesktop.Secret.Service", "ReadAlias",
                              GLib.Variant("(s)", ("default",)), GLib.VariantType("(o)"),
                              Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
        if alias == "/":
            return False
        locked = bus.call_sync(SECRETS, alias, "org.freedesktop.DBus.Properties", "Get",
                               GLib.Variant("(ss)", ("org.freedesktop.Secret.Collection", "Locked")),
                               GLib.VariantType("(v)"), Gio.DBusCallFlags.NONE, 3000, None).unpack()[0]
    except GLib.Error:
        return False
    return locked is False


def split_account(text: str, default_domain: str) -> tuple[str, str]:
    """'DOMAIN\\user' or 'user' as (user, domain)."""

    text = text.strip()
    if "\\" in text:
        domain, user = text.split("\\", 1)
        return user.strip(), domain.strip()
    return text, default_domain


def password_save(remember: bool, keyring: bool) -> Gio.PasswordSave:
    if not remember:
        return Gio.PasswordSave.NEVER
    return Gio.PasswordSave.PERMANENTLY if keyring else Gio.PasswordSave.FOR_SESSION


class ConnectWindow(Adw.ApplicationWindow):
    def __init__(self, application: Adw.Application, root: Gio.File, host: str, share: str) -> None:
        super().__init__(application=application, title=_("The company's shared folder"), default_width=460,
                         resizable=False)
        self.root = root
        self.answers = 0
        self.cancellable: Gio.Cancellable | None = None
        self.toasts = Adw.ToastOverlay()
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            title=_("Sign in to the company's server"),
            # Both the folders (Desktop and Documents on the server) and the shared drives sign in here.
            description=_("To open the company's folder “%(share)s” on the server %(host)s, sign in with the account "
                          "the company gave you.") % {"share": share, "host": host})
        self.account = Adw.EntryRow(title=_("Account"))
        self.account.set_text(GLib.get_user_name())
        self.password = Adw.PasswordEntryRow(title=_("Password"))
        self.password.connect("entry-activated", lambda _row: self.connect_now())
        self.remember = Adw.SwitchRow(title=_("Remember the password on this computer"), active=True)
        for row in (self.account, self.password, self.remember):
            group.add(row)
        page.add(group)
        buttons = Gtk.Box(spacing=12, halign=Gtk.Align.END, margin_top=6)
        later = Gtk.Button(label=_("Later"))
        later.connect("clicked", lambda _b: self.close())
        self.connect_button = Gtk.Button(label=_("Connect"))
        self.connect_button.add_css_class("suggested-action")
        self.connect_button.connect("clicked", lambda _b: self.connect_now())
        buttons.append(later)
        buttons.append(self.connect_button)
        actions = Adw.PreferencesGroup()
        actions.add(buttons)
        page.add(actions)
        view.set_content(page)
        self.toasts.set_child(view)
        self.set_content(self.toasts)
        self.password.grab_focus()

    def connect_now(self) -> None:
        if not self.password.get_text():
            self.password.grab_focus()
            return
        self.connect_button.set_sensitive(False)
        self.answers = 0
        operation = Gio.MountOperation()
        operation.connect("ask-password", self.on_ask_password)
        operation.connect("ask-question", lambda op, *_args: op.reply(Gio.MountOperationResult.ABORTED))
        self.cancellable = Gio.Cancellable()
        self.root.mount_enclosing_volume(Gio.MountMountFlags.NONE, operation, self.cancellable, self.mounted)

    def on_ask_password(self, operation: Gio.MountOperation, _message: str, default_user: str, default_domain: str,
                        flags: Gio.AskPasswordFlags) -> None:
        self.answers += 1
        if self.answers > 1:  # asked again: the server refused this account or password
            operation.reply(Gio.MountOperationResult.ABORTED)
            return
        user, domain = split_account(self.account.get_text() or default_user, default_domain)
        operation.set_anonymous(False)
        operation.set_username(user)
        operation.set_domain(domain)
        operation.set_password(self.password.get_text())
        operation.set_password_save(password_save(self.remember.get_active(), keyring_open()))
        operation.reply(Gio.MountOperationResult.HANDLED)

    def mounted(self, source: Gio.File, result: Gio.AsyncResult) -> None:
        try:
            source.mount_enclosing_volume_finish(result)
        except GLib.Error as exc:
            if not exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.ALREADY_MOUNTED):
                self.connect_button.set_sensitive(True)
                self.password.set_text("")
                self.password.grab_focus()
                refused = self.answers > 1 or exc.matches(Gio.io_error_quark(), Gio.IOErrorEnum.PERMISSION_DENIED)
                self.toasts.add_toast(Adw.Toast(
                    title=_("Wrong account or password.") if refused else
                    _("Could not connect to the server: %s") % exc.message, timeout=6))
                return
        self.close()


def connect_share(application: Adw.Application, url: str) -> None:
    match = re.match(r"^smb://([^/]+)/([^/]+)", url)
    if not match or not protocol.valid_share(url):
        application.quit()
        return
    root = Gio.File.new_for_uri(f"smb://{match.group(1)}/{match.group(2)}/")
    ConnectWindow(application, root, match.group(1), match.group(2)).present()

"""The admin machine's window: a sidebar of pages (Adw.NavigationSplitView) and, under every page, the bar that saves
the settings when they changed.

The settings of all pages are one draft (caramos_business.draft); saving sends it to the helper, which signs it as the
next policy. The machines' side (machines.json, health, inventories, commands, tickets, assets) is read from the state
folder every few seconds."""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import ADMIN_STATE, admin, health, licences, pairing, protocol, text, tickets  # noqa: E402
from ..draft import COMPANY, Draft, scope_kind  # noqa: E402
from ..i18n import _  # noqa: E402
from . import common  # noqa: E402
from .helper import run_helper  # noqa: E402

REFRESH_SECONDS = 5
# The sidebar: (key, title, icons to try). Settings pages list their sections.
SECTION_PAGES = {"wallpaper": ("wallpaper",), "folders": ("folders",), "shares": ("shares",), "browser": ("browser",),
                 "printers": ("printers",), "wifi": ("wifi",), "apps": ("apps",), "power": ("power",),
                 "security": ("usb", "screen_lock", "firewall"), "shared": ("shared",), "snapshots": ("snapshots",)}
# The sidebar's groups, with a line between them: the machines and the people, the settings, the reports.
GROUP_STARTS = ("wallpaper", "security_report")


def page_list() -> list[tuple[str, str, tuple[str, ...]]]:
    return [
        ("overview", _("Overview"), ("go-home-symbolic",)),
        ("machines", _("Employee machines"), ("computer-symbolic",)),
        ("departments", _("Departments"), ("system-users-symbolic",)),
        ("tickets", _("Help tickets"), ("help-browser-symbolic", "dialog-question-symbolic")),
        ("assets", _("Assets"), ("drive-multidisk-symbolic", "computer-symbolic")),
        ("wallpaper", _("Wallpaper"), ("preferences-desktop-wallpaper-symbolic", "image-x-generic-symbolic")),
        ("folders", _("Folders"), ("folder-documents-symbolic", "folder-symbolic")),
        ("shares", _("Shared drives"), ("folder-remote-symbolic", "network-server-symbolic")),
        ("browser", _("Browser"), ("web-browser-symbolic", "applications-internet-symbolic")),
        ("printers", _("Printers"), ("printer-symbolic",)),
        ("wifi", _("Wi-Fi"), ("network-wireless-symbolic",)),
        ("apps", _("Apps"), ("view-app-grid-symbolic", "application-x-addon-symbolic")),
        ("power", _("Power schedule"), ("system-shutdown-symbolic",)),
        ("security", _("Security"), ("security-high-symbolic", "channel-secure-symbolic")),
        ("shared", _("Shared machines"), ("system-lock-screen-symbolic", "changes-prevent-symbolic")),
        ("snapshots", _("System snapshots"), ("document-revert-symbolic", "edit-undo-symbolic")),
        ("security_report", _("Security report"), ("security-medium-symbolic", "x-office-document-symbolic")),
        ("licences", _("Software licences"), ("emblem-documents-symbolic", "x-office-document-symbolic")),
        ("audit", _("Activity log"), ("document-open-recent-symbolic",)),
        ("backup", _("Backup"), ("document-save-symbolic", "drive-harddisk-symbolic")),
    ]


def page_of_section(section: str) -> str | None:
    if section == "inventory":
        return "machines"
    for key, sections in SECTION_PAGES.items():
        if section in sections:
            return key
    return None


class Context:
    """What the pages share: the draft, the machines' state, and the ways to change things."""

    def __init__(self, view: AdminView) -> None:
        self.view = view
        self.window = view.window
        self.saved_policy = admin.read_policy()
        self.draft = Draft(self.saved_policy)
        self.scope = COMPANY
        self.extra_scopes: list[str] = []
        self.seen_tickets: set[str] | None = None
        self.reload()

    # - reading -

    def reload(self) -> None:
        everything = admin.read_machines()
        # Machines waiting for "Duyệt" are listed apart: they get nothing, so they are in no count or report.
        self.machines = {key: entry for key, entry in everything.items() if admin.approved(entry)}
        self.pending = {key: entry for key, entry in everything.items() if not admin.approved(entry)}
        self.records = admin.read_health()
        self.assets = admin.read_assets()
        self.tickets = tickets.read(ADMIN_STATE)
        self.options = admin.read_options()
        self.tokens = pairing.read_tokens(ADMIN_STATE)
        self.licence_register = licences.read_register(ADMIN_STATE)
        self.results = admin.read_results()
        self.commands = [command for command in (admin.command_of(item) for item in admin.read_commands()["commands"])
                         if command]
        policy = admin.read_policy()
        if policy.get("serial") != self.saved_policy.get("serial"):
            self.saved_policy = policy
            if not self.draft.dirty:
                self.draft.load(policy)

    def now(self) -> datetime.datetime:
        return datetime.datetime.now().astimezone()

    def inventory(self, machine_id: str) -> dict[str, Any] | None:
        return admin.read_inventory(machine_id)

    def effective(self, machine_id: str) -> dict[str, Any]:
        """What a machine has in effect: the saved policy, not the draft."""

        return protocol.effective_settings(self.saved_policy, machine_id)

    def problems(self, machine_id: str) -> list[health.Problem]:
        entry = self.machines.get(machine_id) or {}
        return health.problems(entry, self.records.get(machine_id), self.effective(machine_id), self.now())

    def online(self, machine_id: str) -> bool:
        return health.online(self.machines.get(machine_id) or {}, self.now())

    def machine_name(self, machine_id: str) -> str:
        return admin.machine_name(self.machines, machine_id) if machine_id in self.machines else \
            admin.machine_name(self.pending, machine_id)

    def new_tickets(self) -> list[dict[str, Any]]:
        """The tickets nobody has answered yet, newest first."""

        return sorted((ticket for ticket in self.tickets["tickets"] if ticket.get("status") == "new"),
                      key=lambda ticket: ticket.get("created", ""), reverse=True)

    def department_name(self, machine_id: str) -> str:
        department = self.draft.department_of(machine_id)
        return self.draft.departments().get(department, {}).get("name", "") if department else ""

    def scopes(self) -> list[str]:
        """The scopes the settings pages offer: the company, the departments, machines with settings of their own
        and any machine picked since."""

        found = [COMPANY] + [f"department:{key}" for key in self.department_ids()]
        for scope in self.draft.machine_scopes() + self.extra_scopes:
            if scope not in found and scope.split(":", 1)[1] in self.machines:
                found.append(scope)
        if self.scope not in found:
            self.scope = COMPANY
        return found

    def department_ids(self) -> list[str]:
        """The departments in Vietnamese alphabetical order (accents folded: Kế toán before Kho)."""

        departments = self.draft.departments()
        return sorted(departments, key=lambda key: text.fold(departments[key].get("name", key)))

    def scope_title(self, scope: str) -> str:
        return self.draft.scope_title(scope, self.machines)

    # - changing -

    def toast(self, text: str, timeout: int = 4) -> None:
        self.window.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=timeout))

    def changed(self) -> None:
        """The draft changed: the save bar follows."""

        self.view.update_save_bar()

    def set_scope(self, scope: str) -> None:
        if scope_kind(scope) == "machine" and scope not in self.extra_scopes:
            self.extra_scopes.append(scope)
        self.scope = scope

    def helper(self, args: list[str], done: Callable[[bool, dict[str, Any]], None], stdin: str | None = None) -> None:
        run_helper(args, done, stdin)

    def save(self) -> None:
        try:
            self.draft.validate()
        except protocol.ProtocolError as exc:
            self.show_error(exc)
            return
        self.view.saving(True)

        def done(ok: bool, answer: dict[str, Any]) -> None:
            self.view.saving(False)
            if not ok:
                error = protocol.ProtocolError(answer.get("error", _("Could not save.")), answer.get("section"),
                                               answer.get("scope"))
                self.show_error(error)
                return
            self.saved_policy = admin.read_policy()
            self.draft.load(self.saved_policy)
            self.view.update_save_bar()
            self.view.refresh_current()
            self.toast(_("Sent. Machines that are on take it within seconds; the others when they start."), 6)

        self.helper(["policy"], done, json.dumps(self.draft.payload(), ensure_ascii=False))

    def show_error(self, error: protocol.ProtocolError) -> None:
        where = []
        if error.section:
            where.append(health.section_title(error.section))
        if error.scope:
            where.append(self.scope_title(error.scope) if not error.scope.startswith("department:")
                         or error.scope.split(":", 1)[1] in self.draft.departments() else error.scope)
        self.toast(f"{', '.join(where)}: {error}" if where else str(error), 8)
        page = page_of_section(error.section) if error.section else None
        if page:
            if error.scope and error.scope != self.scope and page != "machines":
                self.set_scope(error.scope)
            self.view.show_page(page)

    def revert(self) -> None:
        self.draft.revert()
        self.view.update_save_bar()
        self.view.refresh_current(force=True)

    def command(self, targets: dict[str, Any], action: str, args: dict[str, Any] | None = None,
                done: Callable[[str | None], None] | None = None, help_id: str | None = None,
                minutes: int | None = None, sent: str | None = None) -> None:
        """Signs and queues an instant action (through the helper); done(command id or None)."""

        request: dict[str, Any] = {"targets": targets, "action": action, "args": args or {}}
        if help_id:
            request["help_id"] = help_id
        if minutes:
            request["minutes"] = minutes

        def finished(ok: bool, answer: dict[str, Any]) -> None:
            if ok:
                self.reload()
                if sent:
                    self.toast(sent)
            else:
                self.toast(answer.get("error", _("Could not send it.")), 8)
            if done:
                done(answer.get("id") if ok else None)

        self.helper(["command"], finished, json.dumps(request, ensure_ascii=False))

    def command_results(self, command_id: str) -> dict[str, Any]:
        return self.results.get(command_id, {})


class AdminView(Adw.Bin):
    def __init__(self, window: Any) -> None:
        super().__init__()
        self.window = window
        if not self.readable():
            self.set_child(common.toolbar(common.status_page(
                "dialog-password-symbolic", _("Only this machine's administrators can open this"),
                _("The company's settings on this machine are kept for the users who can install software on it. "
                  "Log in with such an account."))))
            return
        self.ctx = Context(self)
        self.pages: dict[str, Any] = {}
        self.current = ""
        self.split = Adw.NavigationSplitView(min_sidebar_width=220, max_sidebar_width=300, sidebar_width_fraction=0.24)
        self.split.set_sidebar(self.sidebar())
        self.nav = Adw.NavigationView()
        self.nav.connect("popped", lambda _nav, _page: self.refresh_current())
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.nav.set_vexpand(True)
        content.append(self.nav)
        content.append(self.save_bar())
        self.content_page = Adw.NavigationPage(title=_("Overview"), child=content)
        self.split.set_content(self.content_page)
        self.set_child(self.split)
        breakpoint_ = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 760sp"))
        breakpoint_.add_setter(self.split, "collapsed", True)
        window.add_breakpoint(breakpoint_)
        self.show_page("overview")
        self.timer = GLib.timeout_add_seconds(REFRESH_SECONDS, self.tick)
        self.connect("unrealize", lambda _view: GLib.source_remove(self.timer) if self.timer else None)
        self.notify_tickets(first=True)

    @staticmethod
    def readable() -> bool:
        try:
            (ADMIN_STATE / admin.MACHINES).exists()
            list(ADMIN_STATE.iterdir())
        except PermissionError:
            return False
        except OSError:
            return True
        return True

    # - sidebar -

    def sidebar(self) -> Adw.NavigationPage:
        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.listbox.add_css_class("navigation-sidebar")
        self.rows: dict[str, Gtk.ListBoxRow] = {}
        for key, title, icons in page_list():
            row = Gtk.ListBoxRow()
            box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=6, margin_end=6)
            image = Gtk.Image.new_from_gicon(Gio.ThemedIcon.new_from_names(list(icons)))
            box.append(image)
            box.append(common.label(title, wrap=False, lines=1))
            row.set_child(box)
            row.key = key
            self.rows[key] = row
            self.listbox.append(row)
        self.listbox.set_header_func(self.sidebar_header)
        self.listbox.connect("row-activated", lambda _list, row: self.show_page(row.key))
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=_("CaramOS Business")))
        return Adw.NavigationPage(title=_("CaramOS Business"), child=common.toolbar(common.scrolled(self.listbox),
                                                                                     header=header))

    @staticmethod
    def sidebar_header(row: Gtk.ListBoxRow, before: Gtk.ListBoxRow | None) -> None:
        """A line above the first page of each group."""

        if before is not None and getattr(row, "key", "") in GROUP_STARTS:
            if row.get_header() is None:
                row.set_header(Gtk.Separator(margin_top=6, margin_bottom=6, margin_start=6, margin_end=6))
        else:
            row.set_header(None)

    # - pages -

    def page(self, key: str) -> Any:
        if key not in self.pages:
            from . import assets_page, departments, logbook, machines, overview, reports_page, settings_page, \
                tickets_page

            if key == "overview":
                self.pages[key] = overview.OverviewPage(self.ctx)
            elif key == "machines":
                self.pages[key] = machines.MachinesPage(self.ctx)
            elif key == "departments":
                self.pages[key] = departments.DepartmentsPage(self.ctx)
            elif key == "tickets":
                self.pages[key] = tickets_page.TicketsPage(self.ctx)
            elif key == "assets":
                self.pages[key] = assets_page.AssetsPage(self.ctx)
            elif key == "security_report":
                self.pages[key] = reports_page.SecurityReportPage(self.ctx)
            elif key == "licences":
                self.pages[key] = reports_page.LicencePage(self.ctx)
            elif key == "audit":
                self.pages[key] = logbook.AuditPage(self.ctx)
            elif key == "backup":
                self.pages[key] = logbook.BackupPage(self.ctx)
            else:
                title = dict((item[0], item[1]) for item in page_list())[key]
                self.pages[key] = settings_page.SettingsPage(self.ctx, key, title, SECTION_PAGES[key])
        return self.pages[key]

    def show_page(self, key: str) -> None:
        page = self.page(key)
        self.current = key
        row = self.rows.get(key)
        if row is not None and self.listbox.get_selected_row() is not row:
            self.listbox.select_row(row)
        page.refresh(force=True)
        self.nav.replace([page.navigation_page])
        self.content_page.set_title(page.navigation_page.get_title())
        self.split.set_show_content(True)

    def push(self, navigation_page: Adw.NavigationPage) -> None:
        self.nav.push(navigation_page)

    def refresh_current(self, force: bool = False) -> None:
        visible = self.nav.get_visible_page()
        target = getattr(visible, "owner", None)
        if target is not None and hasattr(target, "refresh"):
            target.refresh(force=force)

    def tick(self) -> bool:
        self.ctx.reload()
        self.notify_tickets()
        self.refresh_current()
        return True

    def notify_tickets(self, first: bool = False) -> None:
        """A desktop notification for each new ticket while the window is open."""

        new = self.ctx.new_tickets()
        ids = {item.get("id") for item in new}
        if self.ctx.seen_tickets is None or first:
            self.ctx.seen_tickets = ids
            return
        for item in new:
            if item.get("id") not in self.ctx.seen_tickets:
                name = self.ctx.machine_name(item.get("machine_id", ""))
                who = item.get("user") or name
                common.notify(self.window.get_application(), f"ticket-{item.get('id')}",
                              _("%(user)s asks for help on %(machine)s") % {"user": who, "machine": name},
                              item.get("note") or _("No note."))
        self.ctx.seen_tickets = ids

    # - the save bar -

    def save_bar(self) -> Gtk.Revealer:
        self.revealer = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_UP)
        bar = Gtk.Box(spacing=12)
        bar.add_css_class("save-bar")
        self.save_hint = common.label(_("The settings have changes that are not sent yet."))
        self.save_hint.set_hexpand(True)
        self.save_hint.set_valign(Gtk.Align.CENTER)
        bar.append(self.save_hint)
        self.revert_button = common.button(_("Undo"), lambda: self.ctx.revert())
        self.save_button = common.button(_("Save and send"), lambda: self.ctx.save(), "suggested-action")
        bar.append(self.revert_button)
        bar.append(self.save_button)
        self.revealer.set_child(bar)
        return self.revealer

    def update_save_bar(self) -> None:
        dirty = self.ctx.draft.dirty
        self.revealer.set_reveal_child(dirty)
        # Toasts go up above the bar while it shows: a refused save's toast covered "Hoàn tác" for 8 seconds.
        (self.window.toasts.add_css_class if dirty else self.window.toasts.remove_css_class)("above-save-bar")

    def saving(self, busy: bool) -> None:
        self.save_button.set_sensitive(not busy)
        self.revert_button.set_sensitive(not busy)
        self.save_hint.set_label(_("Saving…") if busy else _("The settings have changes that are not sent yet."))


class Page:
    """A page of the window: a navigation page with a header bar and scrolled content; refresh() fills it."""

    def __init__(self, ctx: Context, title: str, tag: str) -> None:
        self.ctx = ctx
        self.header = Adw.HeaderBar()
        self.body = common.page_box()
        self.view = common.toolbar(common.scrolled(common.clamp(self.body)), title, header=self.header)
        self.navigation_page = Adw.NavigationPage(title=title, tag=tag, child=self.view)
        self.navigation_page.owner = self

    def differs(self, key: str, value: Any) -> bool:
        """Whether what a part of the page shows changed since it was last built: the timer rebuilds only then, so
        that a click never lands on a row that is being replaced."""

        signatures = self.__dict__.setdefault("_signatures", {})
        if signatures.get(key) == value:
            return False
        signatures[key] = value
        return True

    def forget_signatures(self) -> None:
        self.__dict__.pop("_signatures", None)

    def clear(self) -> None:
        child = self.body.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.body.remove(child)
            child = following

    def refresh(self, force: bool = False) -> None:  # noqa: ARG002 - pages that only fill on demand ignore it
        raise NotImplementedError

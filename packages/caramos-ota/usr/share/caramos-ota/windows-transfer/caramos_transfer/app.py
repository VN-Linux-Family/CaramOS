"""The Chuyển dữ liệu từ Windows window (GTK 4 + libadwaita): where the data is, which account, what to copy, the
typing method, the copy with its progress, and what was done.

    caramos-windows-transfer          open the window
    caramos-windows-transfer FOLDER   open the window on a folder: an old disk's drive, its Users folder or an account
    caramos-windows-transfer --scan   print the Windows disks of this computer as JSON

The pages follow DESIGN.md: a navigation view with libadwaita's header bars, boxed lists for choices, the bar at the
bottom with a hint at the left and the main button at the right, and a status page at the end.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import threading
from pathlib import Path

from caramos_ota.i18n import _, ngettext, prefers_vietnamese

from . import input_method, sources, transfer

APP_ID = "net.vietnamlinuxfamily.CaramOSWindowsTransfer"
LOGO = Path("/usr/share/pixmaps/caramos-logo.png")
SPACE_MARGIN = 512 * 1024 ** 2


def human_size(size: int) -> str:
    """"2,3 GB" in Vietnamese, "2.3 GB" in English."""

    value, unit = float(size), "B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            break
        value /= 1024
    text = f"{value:.0f}" if unit in ("B", "KB") or value >= 100 else f"{value:.1f}"
    if prefers_vietnamese():
        text = text.replace(".", ",")
    return f"{text} {unit}"


def count_text(files: int) -> str:
    number = f"{files:,}".replace(",", "." if prefers_vietnamese() else ",")
    return ngettext("{count} file", "{count} files", files).format(count=number)


def item_title(key: str) -> str:
    return {
        sources.DESKTOP: _("Desktop"), sources.DOCUMENTS: _("Documents"), sources.PICTURES: _("Pictures"),
        sources.DOWNLOADS: _("Downloads"), sources.MUSIC: _("Music"), sources.VIDEOS: _("Videos"),
        sources.ZALO: _("Files received in Zalo"), sources.BOOKMARKS: _("Browser bookmarks"),
        sources.OUTLOOK: _("Outlook mail"), sources.FONTS: _("Fonts you installed"),
    }[key]


def item_subtitle(key: str, item: sources.Item, profile: sources.Profile) -> str:
    size = item.size
    if size is None:
        return _("Working out the size…")
    amount = _("{files}, {size}").format(files=count_text(size.files), size=human_size(size.bytes))
    if key in sources.FOLDER_ITEMS:
        return _("{amount}, into the folder {folder}.").format(amount=amount, folder=transfer.user_dir(key).name)
    if key == sources.ZALO:
        return _("{amount}. The folder “Zalo Received Files” goes into Documents.").format(amount=amount)
    if key == sources.BOOKMARKS:
        browsers = sorted({browser for browser, _profile, _path in sources.bookmark_files(profile)})
        return _("From {browsers}, into one file in Documents for Firefox.").format(browsers=", ".join(browsers))
    if key == sources.OUTLOOK:
        if transfer.readpst():
            return _("{amount}. Turned into mail files for Thunderbird, in Documents.").format(amount=amount)
        return _("{amount}. This computer has no pst-utils, so the .pst files are copied as they are.").format(
            amount=amount)
    if key == sources.FONTS:
        return _("{amount}. Microsoft's own fonts are left out.").format(amount=amount)
    return amount


def locked_text() -> str:
    """What the page of a Windows disk BitLocker locks says; its header names the disk."""

    return _("BitLocker, the disk encryption of Windows, locks this disk: CaramOS cannot read it. Start Windows, turn "
             "off BitLocker for this disk (Settings > Privacy & security > Device encryption, or Control Panel > "
             "BitLocker Drive Encryption > Turn off BitLocker) and wait until Windows says the disk is decrypted. Then "
             "start CaramOS and open this window again.\n\nOr copy your files to a USB disk from Windows, and choose "
             "“A folder” here.")


def build_window(app, folder: Path | None = None):
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, GLib, Gtk, Pango

    def label(text: str, *classes: str, xalign: float = 0.0, wrap: bool = True) -> Gtk.Label:
        widget = Gtk.Label(label=text, xalign=xalign, wrap=wrap)
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        for name in classes:
            widget.add_css_class(name)
        return widget

    def content_box() -> Gtk.Box:
        return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=24, margin_bottom=24,
                       margin_start=24, margin_end=24)

    def section(box: Gtk.Box, title: str) -> None:
        heading = label(title, "section-title")
        heading.set_margin_top(16)
        box.append(heading)

    def scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
        return Gtk.ScrolledWindow(child=Adw.Clamp(maximum_size=640, child=child), vexpand=True,
                                  hscrollbar_policy=Gtk.PolicyType.NEVER)

    def chevron_row(title: str, subtitle: str, handler) -> Adw.ActionRow:
        row = Adw.ActionRow(title=GLib.markup_escape_text(title), subtitle=GLib.markup_escape_text(subtitle),
                            activatable=True)
        row.set_subtitle_lines(3)
        row.add_suffix(Gtk.Image(icon_name="go-next-symbolic"))
        row.connect("activated", lambda *_a: handler())
        return row

    class Window(Adw.ApplicationWindow):
        def __init__(self) -> None:
            super().__init__(application=app, title=_("Windows Data Transfer"), default_width=700, default_height=680)
            self.set_size_request(360, 480)
            self.toasts = Adw.ToastOverlay()
            self.nav = Adw.NavigationView()
            self.toasts.set_child(self.nav)
            self.set_content(self.toasts)
            self.partition: sources.Partition | None = None
            self.mounted = False
            self.profile: sources.Profile | None = None
            self.items: dict[str, sources.Item] = {}
            self.checks: dict[str, Gtk.CheckButton] = {}
            self.copier: transfer.Copier | None = None
            self.measuring = threading.Event()
            self.method = input_method.current() or input_method.TELEX
            self.pending_progress: tuple | None = None
            self.connect("close-request", self.on_close)
            self.nav.add(self.start_page())
            if folder is not None:
                GLib.idle_add(lambda: self.opened(folder, None, False))

        # ---- helpers -------------------------------------------------------------------------------------

        def page(self, title: str, content: Gtk.Widget, tag: str, bar: Gtk.Widget | None = None,
                 can_pop: bool = True) -> Adw.NavigationPage:
            view = Adw.ToolbarView(content=content)
            header = Adw.HeaderBar()
            view.add_top_bar(header)
            if bar is not None:
                view.add_bottom_bar(bar)
            page = Adw.NavigationPage(child=view, title=title, tag=tag)
            page.set_can_pop(can_pop)
            return page

        def push(self, page: Adw.NavigationPage) -> None:
            existing = self.nav.find_page(page.get_tag())
            if existing is not None and existing in self.nav.get_navigation_stack():
                self.nav.pop_to_page(existing)
                self.nav.pop()
            self.nav.push(page)

        def bar(self, hint: Gtk.Label, buttons: list[Gtk.Button]) -> Gtk.Widget:
            box = Gtk.Box(spacing=12)
            box.add_css_class("action-bar")
            hint.set_hexpand(True)
            hint.set_valign(Gtk.Align.CENTER)
            box.append(hint)
            for button in buttons:
                box.append(button)
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            outer.append(Gtk.Separator())
            outer.append(box)
            return outer

        def toast(self, text: str) -> None:
            self.toasts.add_toast(Adw.Toast(title=text, timeout=6))

        # ---- 1. where the data is --------------------------------------------------------------------------

        def start_page(self) -> Adw.NavigationPage:
            box = content_box()
            intro = Gtk.Box(spacing=16)
            if LOGO.exists():
                logo = Gtk.Image.new_from_file(str(LOGO))
                logo.set_pixel_size(48)
                logo.set_valign(Gtk.Align.START)
                intro.append(logo)
            texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
            texts.append(label(_("Windows Data Transfer"), "page-title"))
            texts.append(label(_("Copy documents, pictures, browser bookmarks, Outlook mail and fonts from your old "
                                 "Windows computer to this one. Nothing on the Windows side is changed.")))
            intro.append(texts)
            box.append(intro)
            section(box, _("Where is the data?"))
            group = Adw.PreferencesGroup()
            for partition in sources.windows_partitions():
                if partition.locked:
                    subtitle = _("On this computer, {size}. Locked with BitLocker: Windows has to unlock it "
                                 "first.").format(size=human_size(partition.size))
                    group.add(chevron_row(partition.title(), subtitle,
                                          lambda p=partition: self.push(self.locked_page(p))))
                    continue
                subtitle = _("On this computer, {size}. Read only: nothing is written to it.").format(
                    size=human_size(partition.size))
                group.add(chevron_row(partition.title(), subtitle, lambda p=partition: self.open_partition(p)))
            group.add(chevron_row(_("A folder"), _("The old computer's disk on a USB adapter, or a folder copied "
                                                   "from it."), self.choose_folder))
            group.add(chevron_row(_("A shared folder on the network"), _("The C:\\Users folder of the old computer, "
                                                                          "shared on the office network."),
                                  self.share_page))
            box.append(group)
            return self.page(_("Windows Data Transfer"), scrolled(box), "start")

        def locked_page(self, partition: sources.Partition) -> Adw.NavigationPage:
            """A Windows disk BitLocker locks: what that means and how to go on."""

            # The description is markup: "Privacy & security" and the ">" of the menu paths are escaped.
            status = Adw.StatusPage(icon_name="channel-secure-symbolic", title=_("This Windows disk is locked"),
                                    description=GLib.markup_escape_text(locked_text()))
            back = Gtk.Button(label=_("Back"), halign=Gtk.Align.CENTER)
            back.add_css_class("pill")
            back.connect("clicked", lambda *_a: self.nav.pop())
            status.set_child(back)
            return self.page(partition.title(), status, "locked")

        def open_partition(self, partition: sources.Partition) -> None:
            self.busy(_("Opening the Windows disk…"))

            def work() -> None:
                try:
                    root, mounted = sources.mount_read_only(partition)
                    GLib.idle_add(self.opened, root, partition, mounted)
                except sources.MountError as error:
                    GLib.idle_add(self.failed, str(error))

            threading.Thread(target=work, daemon=True).start()

        def busy(self, text: str) -> None:
            status = Adw.StatusPage(title=text)
            status.set_child(Gtk.Spinner(spinning=True, width_request=32, height_request=32, halign=Gtk.Align.CENTER))
            self.push(self.page(text, status, "busy", can_pop=False))

        def failed(self, text: str) -> bool:
            if self.nav.get_visible_page() and self.nav.get_visible_page().get_tag() == "busy":
                self.nav.pop()
            self.toast(text)
            return False

        def opened(self, root: Path, partition: sources.Partition | None, mounted: bool) -> bool:
            self.partition, self.mounted = partition, mounted
            try:
                profiles = sources.find_profiles(root)
            except sources.MountError as error:
                return self.failed(str(error))
            if self.nav.get_visible_page() and self.nav.get_visible_page().get_tag() == "busy":
                self.nav.pop()
            if not profiles:
                self.toast(_("No Windows account was found there. Choose the disk of the old computer, its Users "
                             "folder or an account's folder."))
                return False
            if len(profiles) == 1:
                self.choose_profile(profiles[0])
            else:
                self.push(self.profiles_page(profiles))
            return False

        def choose_folder(self) -> None:
            dialog = Gtk.FileDialog(title=_("Choose the old computer's disk or folder"), modal=True)

            def done(_dialog, result) -> None:
                try:
                    folder = dialog.select_folder_finish(result)
                except GLib.Error:
                    return
                if folder is not None and folder.get_path():
                    self.opened(Path(folder.get_path()), None, False)

            dialog.select_folder(self, None, done)

        def share_page(self) -> None:
            box = content_box()
            box.append(label(_("A shared folder on the network"), "page-title"))
            box.append(label(_("On the old Windows computer, right-click the folder C:\\Users, choose Properties, "
                               "Sharing, Share…, and note the computer's name. Both computers must be on the same "
                               "network.")))
            group = Adw.PreferencesGroup(margin_top=16)
            entry = Adw.EntryRow(title=_("Address, such as \\\\OLD-PC\\Users"))
            group.add(entry)
            box.append(group)
            error = label("", "error")
            box.append(error)
            connect = Gtk.Button(label=_("Connect"))
            connect.add_css_class("suggested-action")

            def go(*_args) -> None:
                uri = sources.smb_uri(entry.get_text())
                if uri is None:
                    error.set_label(_("Type the computer's name and the shared folder, such as \\\\OLD-PC\\Users."))
                    return
                error.set_label("")
                self.mount_share(uri, error)

            connect.connect("clicked", go)
            entry.connect("entry-activated", go)
            hint = label(_("A password window may ask for the Windows account."), "dim-label")
            self.push(self.page(_("Shared folder"), scrolled(box), "share", self.bar(hint, [connect])))

        def mount_share(self, uri: str, error: Gtk.Label) -> None:
            location = Gio.File.new_for_uri(uri)
            operation = Gtk.MountOperation(parent=self)

            def mounted(_file, result) -> None:
                try:
                    location.mount_enclosing_volume_finish(result)
                except GLib.Error as problem:
                    if problem.matches(Gio.io_error_quark(), Gio.IOErrorEnum.FAILED_HANDLED):
                        return                  # the user closed the password window
                    if not problem.matches(Gio.io_error_quark(), Gio.IOErrorEnum.ALREADY_MOUNTED):
                        error.set_label(_("The shared folder could not be opened: {error}").format(
                            error=problem.message))
                        return
                path = location.get_path()
                if not path:
                    error.set_label(_("The shared folder could not be opened."))
                    return
                self.opened(Path(path), None, False)

            location.mount_enclosing_volume(Gio.MountMountFlags.NONE, operation, None, mounted)

        # ---- 2. which account -----------------------------------------------------------------------------

        def profiles_page(self, profiles: list[sources.Profile]) -> Adw.NavigationPage:
            box = content_box()
            box.append(label(_("Choose the Windows account"), "page-title"))
            box.append(label(_("Each person who used the old computer has an account of their own.")))
            group = Adw.PreferencesGroup(margin_top=16)
            for profile in profiles:
                if profile.last_used:
                    subtitle = _("Last used on {date}.").format(date=profile.last_used.strftime("%d/%m/%Y"))
                else:
                    subtitle = _("Folders: {folders}.").format(folders=", ".join(
                        item_title(key) for key in profile.folders))
                group.add(chevron_row(profile.name, subtitle, lambda p=profile: self.choose_profile(p)))
            box.append(group)
            return self.page(_("Account"), scrolled(box), "profiles")

        def choose_profile(self, profile: sources.Profile) -> None:
            self.profile = profile
            self.items = sources.items_of(profile)
            self.push(self.items_page())

        # ---- 3. what to copy ------------------------------------------------------------------------------

        def items_page(self) -> Adw.NavigationPage:
            profile = self.profile
            box = content_box()
            box.append(label(_("Choose what to copy"), "page-title"))
            box.append(label(_("From the account “{name}”. Files that are here already stay; a copy with the same "
                               "name gets “(2)” in its name.").format(name=profile.name)))
            group = Adw.PreferencesGroup(margin_top=16)
            self.checks = {}
            self.rows: dict[str, Adw.ActionRow] = {}
            order = [*sources.FOLDER_ITEMS, sources.ZALO, sources.BOOKMARKS, sources.OUTLOOK, sources.FONTS]
            for key in order:
                item = self.items.get(key)
                if item is None:
                    continue
                check = Gtk.CheckButton(active=True, valign=Gtk.Align.CENTER)
                row = Adw.ActionRow(title=item_title(key), subtitle=item_subtitle(key, item, profile),
                                    activatable_widget=check)
                row.set_subtitle_lines(3)
                row.add_suffix(check)
                check.connect("toggled", lambda *_a: self.update_total())
                group.add(row)
                self.checks[key], self.rows[key] = check, row
            box.append(group)
            self.total_hint = label(_("Working out the size…"), "dim-label")
            self.next_button = Gtk.Button(label=_("Continue"), sensitive=False)
            self.next_button.add_css_class("suggested-action")
            self.next_button.connect("clicked", lambda *_a: self.push(self.typing_page()))
            self.measure()
            return self.page(_("What to copy"), scrolled(box), "items", self.bar(self.total_hint, [self.next_button]))

        def measure(self) -> None:
            self.measuring.clear()
            items = dict(self.items)

            def work() -> None:
                for key, item in items.items():
                    if self.measuring.is_set():
                        return
                    if key in sources.FOLDER_ITEMS or key == sources.ZALO:
                        item.size = sources.measure(item.sources[0], skip=transfer.skipped,
                                                    stop=self.measuring.is_set)
                    else:
                        size = sources.Size()
                        for path in item.sources:
                            try:
                                size.files += 1
                                size.bytes += path.stat().st_size
                            except OSError:
                                size.unreadable += 1
                        item.size = size
                    GLib.idle_add(self.measured, key)
                GLib.idle_add(self.update_total)

            threading.Thread(target=work, daemon=True).start()

        def measured(self, key: str) -> bool:
            row = self.rows.get(key)
            if row is None:
                return False
            item = self.items[key]
            if item.size is not None and item.size.files == 0 and key in sources.FOLDER_ITEMS:
                self.checks[key].set_active(False)      # nothing to copy from an empty folder
                self.checks[key].set_sensitive(False)
                row.set_subtitle(GLib.markup_escape_text(_("This folder is empty.")))
            else:
                row.set_subtitle(GLib.markup_escape_text(item_subtitle(key, item, self.profile)))
            return False

        def chosen(self) -> list[str]:
            return [key for key, check in self.checks.items() if check.get_active()]

        def update_total(self) -> bool:
            if any(item.size is None for item in self.items.values()):
                return False
            plan = transfer.Plan(self.profile, self.items, self.chosen())
            zalo = self.rows.get(sources.ZALO)
            if zalo is not None:
                inside = self.zalo_parent(plan)
                if inside:
                    self.checks[sources.ZALO].set_active(True)
                self.checks[sources.ZALO].set_sensitive(inside is None)
                zalo.set_subtitle(GLib.markup_escape_text(
                    _("Copied with {folder}: the folder “Zalo Received Files” is in it.").format(
                        folder=item_title(inside)) if inside else
                    item_subtitle(sources.ZALO, self.items[sources.ZALO], self.profile)))
            needed = plan.total_bytes()
            free = shutil.disk_usage(Path.home()).free
            self.total_hint.remove_css_class("error")
            if not plan.effective():
                self.total_hint.set_label(_("Choose at least one thing to copy."))
                self.next_button.set_sensitive(False)
            elif needed + SPACE_MARGIN > free:
                self.total_hint.set_label(_("Not enough free space: this needs {needed}, the computer has {free} "
                                            "free.").format(needed=human_size(needed), free=human_size(free)))
                self.total_hint.add_css_class("error")
                self.next_button.set_sensitive(False)
            else:
                self.total_hint.set_label(_("About {needed} to copy; {free} free on this computer.").format(
                    needed=human_size(needed), free=human_size(free)))
                self.next_button.set_sensitive(True)
            return False

        def zalo_parent(self, plan: transfer.Plan) -> str | None:
            """The chosen folder that holds Zalo's folder (copied with it), if any."""

            zalo = self.items.get(sources.ZALO)
            if zalo is None:
                return None
            for key in sources.FOLDER_ITEMS:
                folder = self.profile.folders.get(key)
                if key in plan.chosen and folder is not None and folder in zalo.sources[0].parents:
                    return key
            return None

        # ---- 4. typing ------------------------------------------------------------------------------------

        def typing_page(self) -> Adw.NavigationPage:
            box = content_box()
            box.append(label(_("How do you type Vietnamese?"), "page-title"))
            box.append(label(_("This computer will type the way you did on Windows with Unikey or EVKey.")))
            group = Adw.PreferencesGroup(margin_top=16)
            first = None
            choices = ((input_method.TELEX, "Telex", _("aa gives â, dd gives đ, s adds the acute accent: "
                                                       "“Vieejt Nam” becomes “Việt Nam”.")),
                       (input_method.VNI, "VNI", _("a6 gives â, d9 gives đ, 1 adds the acute accent: "
                                                   "“Vie65t Nam” becomes “Việt Nam”.")))
            self.method_checks: dict[str, Gtk.CheckButton] = {}
            for method, title, subtitle in choices:
                check = Gtk.CheckButton(group=first, valign=Gtk.Align.CENTER, active=method == self.method)
                first = first or check
                row = Adw.ActionRow(title=title, subtitle=GLib.markup_escape_text(subtitle), activatable_widget=check)
                row.set_subtitle_lines(2)
                row.add_suffix(check)
                group.add(row)
                self.method_checks[method] = check
            box.append(group)
            start = Gtk.Button(label=_("Start copying"))
            start.add_css_class("suggested-action")
            start.connect("clicked", lambda *_a: self.start_copy())
            hint = label(_("The typing method can be changed later in the input method's settings."), "dim-label")
            return self.page(_("Typing"), scrolled(box), "typing", self.bar(hint, [start]))

        # ---- 5. copying -----------------------------------------------------------------------------------

        def start_copy(self) -> None:
            self.method = next(method for method, check in self.method_checks.items() if check.get_active())
            plan = transfer.Plan(self.profile, self.items, self.chosen())
            box = content_box()
            box.set_valign(Gtk.Align.CENTER)
            box.append(label(_("Copying…"), "page-title"))
            self.progress = Gtk.ProgressBar(margin_top=16)
            box.append(self.progress)
            self.now = label("", "dim-label")
            self.now.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
            self.now.set_wrap(False)
            box.append(self.now)
            self.amount = label("")
            box.append(self.amount)
            stop = Gtk.Button(label=_("Stop"))
            stop.connect("clicked", lambda *_a: self.copier and self.copier.stop.set())
            hint = label(_("Do not turn a computer off or unplug a disk until it finishes."), "dim-label")
            self.push(self.page(_("Copying"), scrolled(box), "copying", self.bar(hint, [stop]), can_pop=False))
            self.copier = transfer.Copier(plan.total_bytes(), self.on_progress)
            self.method_result = input_method.set_method(self.method)

            def work() -> None:
                reports = transfer.run_plan(plan, self.copier)
                GLib.idle_add(self.copied, reports, self.copier.stop.is_set())

            threading.Thread(target=work, daemon=True).start()

        def on_progress(self, done: int, total: int, item: str, name: str) -> None:
            """From the copy thread: the window shows the newest values, ten times a second at most."""

            first = self.pending_progress is None
            self.pending_progress = (done, total, item, name)
            if first:
                GLib.timeout_add(100, self.show_progress)

        def show_progress(self) -> bool:
            if self.pending_progress is None:
                return False
            done, total, item, name = self.pending_progress
            self.pending_progress = None
            self.progress.set_fraction(done / total if total else 0)
            self.now.set_label(f"{item_title(item)}: {name}")
            self.amount.set_label(_("{done} of {total} copied").format(done=human_size(done), total=human_size(total)))
            return False

        # ---- 6. done --------------------------------------------------------------------------------------

        def copied(self, reports: list[transfer.Report], stopped: bool) -> bool:
            self.copier = None
            self.release()
            if stopped:
                title, icon = _("Copying stopped"), "process-stop-symbolic"
                description = _("What was copied before you stopped is kept. Nothing on the Windows side was "
                                "changed.")
            else:
                title, icon = _("Everything is copied"), "emblem-ok-symbolic"
                description = _("Nothing on the Windows side was changed.")
            status = Adw.StatusPage(title=title, description=description, icon_name=icon)
            content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
            group = Adw.PreferencesGroup()
            failed: list[str] = []
            for report in reports:
                failed += report.failed
                row = Adw.ActionRow(title=item_title(report.key),
                                    subtitle=GLib.markup_escape_text(self.summary(report)))
                row.set_subtitle_lines(6)
                group.add(row)
            method_row = Adw.ActionRow(title=_("Typing"), subtitle=GLib.markup_escape_text(
                _("{method}. Press Ctrl+Shift to switch between Vietnamese and English.").format(method=self.method)))
            group.add(method_row)
            if failed:
                expander = Adw.ExpanderRow(title=ngettext("{count} file could not be copied",
                                                          "{count} files could not be copied", len(failed)).format(
                    count=len(failed)), subtitle=_("They cannot be read, often because they are only on OneDrive."))
                for path in failed[:200]:
                    line = Adw.ActionRow(title=GLib.markup_escape_text(path))
                    line.set_title_lines(2)
                    expander.add_row(line)
                group.add(expander)
            content.append(Adw.Clamp(maximum_size=560, child=group))
            buttons = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
            documents = Gtk.Button(label=_("Open Documents"))
            documents.add_css_class("pill")
            documents.connect("clicked", lambda *_a: Gtk.FileLauncher.new(Gio.File.new_for_path(
                str(transfer.user_dir(sources.DOCUMENTS)))).launch(self, None, None, None))
            done = Gtk.Button(label=_("Done"))
            done.add_css_class("pill")
            done.add_css_class("suggested-action")
            done.connect("clicked", lambda *_a: self.close())
            buttons.append(documents)
            buttons.append(done)
            content.append(buttons)
            status.set_child(content)
            self.nav.replace([self.page(title, status, "done", can_pop=False)])
            return False

        @staticmethod
        def summary(report: transfer.Report) -> str:
            folder = report.target.name if report.target else ""
            if report.key in sources.FOLDER_ITEMS or report.key == sources.ZALO:
                text = _("{files}, {size}, in the folder {folder}.").format(
                    files=count_text(report.files), size=human_size(report.bytes), folder=folder)
            elif report.key == sources.BOOKMARKS:
                text = ngettext("{count} bookmark in the file “{file}” in Documents. In Firefox, press Ctrl+Shift+O, "
                                "then choose Import and Backup, Import Bookmarks from HTML.",
                                "{count} bookmarks in the file “{file}” in Documents. In Firefox, press Ctrl+Shift+O, "
                                "then choose Import and Backup, Import Bookmarks from HTML.", report.extra).format(
                    count=report.extra, file=folder)
            elif report.key == sources.OUTLOOK:
                if report.note == "copied":
                    text = _("The .pst files are in the folder “{folder}” in Documents. Install pst-utils to turn "
                             "them into mail for Thunderbird.").format(folder=folder)
                else:
                    text = _("Mail files (.mbox) in the folder “{folder}” in Documents. To read them in Thunderbird "
                             "(App Center), add its ImportExportTools NG extension and import the .mbox files.").format(
                        folder=folder)
            elif report.key == sources.FONTS:
                if report.files or not report.same:
                    text = ngettext("{count} font installed for your account.",
                                    "{count} fonts installed for your account.", report.files)
                    text = text.format(count=report.files)
                else:
                    text = _("These fonts were on this computer already.")
                if report.extra:
                    left_out = ngettext("{count} font of Microsoft left out.",
                                        "{count} fonts of Microsoft left out.", report.extra)
                    text += " " + left_out.format(count=report.extra)
            else:
                text = ""
            if report.note == "stopped":
                text += " " + _("Stopped here.")
            return text

        # ---- leaving --------------------------------------------------------------------------------------

        def release(self) -> None:
            if self.partition is not None and self.mounted:
                partition = self.partition
                threading.Thread(target=lambda: sources.unmount(partition), daemon=True).start()
                self.mounted = False

        def on_close(self, *_args) -> bool:
            if self.copier is not None:
                dialog = Adw.MessageDialog(transient_for=self, heading=_("Stop copying?"),
                                           body=_("What is copied so far is kept."))
                dialog.add_response("continue", _("Keep copying"))
                dialog.add_response("stop", _("Stop"))
                dialog.set_response_appearance("stop", Adw.ResponseAppearance.DESTRUCTIVE)

                def answered(_dialog, response: str) -> None:
                    if response == "stop" and self.copier is not None:
                        self.copier.stop.set()

                dialog.connect("response", answered)
                dialog.present()
                return True
            self.measuring.set()
            self.release()
            return False

    return Window()


def open_window(folder: Path | None = None) -> int:
    from caramos_ota import adw_style, gtk_renderer

    gtk_renderer.apply()  # cairo where OpenGL would run on the CPU
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib

    GLib.set_prgname("caramos-windows-transfer")
    GLib.set_application_name(_("Windows Data Transfer"))
    application = Adw.Application(application_id=APP_ID)

    def activate(app) -> None:
        window = app.get_active_window()
        if window is None:
            adw_style.apply()
            window = build_window(app, folder)
        window.present()

    application.connect("activate", activate)
    return application.run([sys.argv[0]])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caramos-windows-transfer", description=_("Windows Data Transfer"))
    parser.add_argument("folder", nargs="?", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--scan", action="store_true", help="print the Windows disks of this computer as JSON")
    args = parser.parse_args(argv)
    if args.scan:
        print(json.dumps([partition.__dict__ for partition in sources.windows_partitions()], ensure_ascii=False,
                         indent=1))
        return 0
    return open_window(args.folder.expanduser().absolute() if args.folder else None)

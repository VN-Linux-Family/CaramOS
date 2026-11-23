"""The editors of the settings sections: each builds the groups of one section's value, for one scope, and changes
that value in place (the draft holds it). A change to a field updates the save bar; adding or removing an item
rebuilds the page."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from .. import ADMIN_STATE, admin, catalog, draft, presets, printers, protocol, text  # noqa: E402
from ..i18n import _, ngettext  # noqa: E402
from . import common  # noqa: E402
from .helper import in_thread  # noqa: E402

SHARE_EXAMPLE = "smb://may-chu/nhanvien/%u"
BOOKMARK_SUGGESTIONS = (("Thuế điện tử", "https://thuedientu.gdt.gov.vn"),
                        ("Hóa đơn điện tử", "https://hoadondientu.gdt.gov.vn"),
                        ("Bảo hiểm xã hội", "https://dichvucong.baohiemxahoi.gov.vn"),
                        ("Dịch vụ công quốc gia", "https://dichvucong.gov.vn"))


def feature_title(section: str) -> str:
    """The company's switch of a section."""

    return {"wallpaper": _("Set the machines' wallpaper"), "folders": _("Desktop and Documents on the server"),
            "shares": _("Shared drives in the file manager"), "browser": _("Manage the browsers"),
            "printers": _("Set up printers"), "power": _("Turn machines off and on by a schedule"),
            "apps": _("Manage apps"), "usb": _("Manage USB storage"), "screen_lock": _("Lock the screen by itself"),
            "firewall": _("Turn on the firewall"), "inventory": _("Automatic inventory"),
            "wifi": _("The company's Wi-Fi"), "shared": _("Shared machines"),
            "snapshots": _("Take system snapshots")}[section]


THUMBNAILS: dict[tuple[str, float], Gdk.Texture | None] = {}


def _decode(path: str) -> GdkPixbuf.Pixbuf | None:
    """A picture decoded at thumbnail size (JPEG decoders scale while decoding): a wallpaper can be 8K, and a full
    texture scaled at every frame makes the window crawl with the CPU renderer."""

    try:
        return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 192, 108, True)
    except GLib.Error:
        return None


def thumbnail(ctx: Any, sha: str | None) -> Gtk.Widget:
    """The picture of a wallpaper, decoded in a thread the first time (an 8K picture takes a while)."""

    path = ctx.draft.pictures.get(sha or "") or (str(ADMIN_STATE / admin.FILES / sha) if sha else "")
    try:
        key = (path, Path(path).stat().st_mtime) if path else None
    except OSError:
        key = None
    if key is None:
        picture: Gtk.Widget = Gtk.Image.new_from_icon_name("image-missing-symbolic")
    else:
        picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER, overflow=Gtk.Overflow.HIDDEN)
        picture.add_css_class("thumbnail")
        if key in THUMBNAILS:
            picture.set_paintable(THUMBNAILS[key])
        else:
            def done(pixbuf: GdkPixbuf.Pixbuf | None, _error: Exception | None) -> None:
                THUMBNAILS[key] = Gdk.Texture.new_for_pixbuf(pixbuf) if pixbuf is not None else None
                picture.set_paintable(THUMBNAILS[key])

            in_thread(lambda: _decode(path), done)
    picture.set_size_request(96, 54)
    picture.set_valign(Gtk.Align.CENTER)
    return picture


def radio_rows(target: Adw.PreferencesGroup, choices: list[tuple[str, str, str]], current: str,
               chosen: Callable[[str], Any]) -> None:
    """Rows with round check buttons: (value, title, subtitle)."""

    first: Gtk.CheckButton | None = None
    for value, title, subtitle in choices:
        check = Gtk.CheckButton(active=value == current, valign=Gtk.Align.CENTER)
        if first is None:
            first = check
        else:
            check.set_group(first)
        row = common.row(title, subtitle)
        row.add_prefix(check)
        row.set_activatable_widget(check)
        check.connect("toggled", lambda button, item=value: button.get_active() and chosen(item))
        target.add(row)


def remove_button(tooltip: str, callback: Callable[[], Any]) -> Gtk.Button:
    return common.icon_button("user-trash-symbolic", tooltip, callback)


class Editors:
    """The editors of one settings page; page.changed(rebuild) after every change."""

    def __init__(self, page: Any) -> None:
        self.page = page
        self.ctx = page.ctx
        self.window = page.ctx.window
        self._catalog: list[catalog.App] | None = None

    def changed(self, rebuild: bool = False) -> None:
        self.page.changed(rebuild)

    def build(self, section: str, value: Any) -> list[Gtk.Widget]:
        return getattr(self, section)(value)

    # - wallpaper -

    def pick_picture(self, chosen: Callable[[str], Any]) -> None:
        filters = Gio.ListStore.new(Gtk.FileFilter)
        pictures = Gtk.FileFilter(name=_("Pictures"))
        for mime in ("image/jpeg", "image/png", "image/webp"):
            pictures.add_mime_type(mime)
        filters.append(pictures)
        dialog = Gtk.FileDialog(title=_("Choose a picture"), filters=filters)

        def opened(source: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
            try:
                path = source.open_finish(result).get_path()
            except GLib.Error:
                return
            try:
                with open(path, "rb") as handle:
                    head = handle.read(16)
                size = Path(path).stat().st_size
            except (OSError, TypeError):
                head, size = b"", 0
            if size > protocol.MAX_FILE:
                self.ctx.toast(_("A picture must be at most 20 MB."))
            elif admin.image_type(head) is None:
                self.ctx.toast(_("Not a JPEG, PNG or WebP picture."))
            else:  # copied in by the helper when the settings are saved (one password for all)
                chosen(self.ctx.draft.new_picture(path))

        dialog.open(self.window, None, opened)

    def wallpaper(self, value: dict[str, Any]) -> list[Gtk.Widget]:
        every = common.group(_("Every day"), _("The wallpaper of every machine, except on the special days below."))
        default = value.get("default")
        row = common.row(_("Picture") if default else _("No picture: each person keeps their own"))
        row.add_prefix(thumbnail(self.ctx, default))

        def set_default(name: str | None) -> None:
            value["default"] = name
            self.changed(rebuild=True)

        row.add_suffix(common.button(_("Choose…"), lambda: self.pick_picture(set_default)))
        if default:
            row.add_suffix(common.icon_button("edit-clear-symbolic", _("No picture"), lambda: set_default(None)))
        every.add(row)
        special = common.group(_("Special days"), _("A picture for holidays and company events, every year. The "
                                                    "Lunar New Year moves: change its days each year."))
        special.set_header_suffix(common.button(_("Add…"), lambda: self.add_period(value)))
        periods = value.setdefault("periods", [])
        if not periods:
            special.add(common.row(_("No special days yet.")))
        for index, period in enumerate(periods):
            item = common.row(period.get("name") or _("Special days"),
                              f"{text.day_month(period['from'])} – {text.day_month(period['to'])}")
            item.add_prefix(thumbnail(self.ctx, period.get("image")))

            def remove(position: int = index) -> None:
                del periods[position]
                self.changed(rebuild=True)

            item.add_suffix(remove_button(_("Remove"), remove))
            special.add(item)
        lock_group = common.group()
        lock = Adw.SwitchRow(title=_("Employees cannot change the wallpaper"),
                             subtitle=_("A wallpaper changed by hand comes back within half a minute"),
                             active=bool(value.get("lock")))

        def locked(row_: Adw.SwitchRow, _param: Any) -> None:
            value["lock"] = row_.get_active()
            self.changed()

        lock.connect("notify::active", locked)
        lock_group.add(lock)
        return [every, special, lock_group]

    def add_period(self, value: dict[str, Any]) -> None:
        name = common.entry_row(_("Name, such as Tết or the company's birthday"))
        start = common.entry_row(_("From (day/month)"))
        end = common.entry_row(_("To (day/month)"))
        picked: dict[str, str] = {}
        picture = Gtk.Button(label=_("Choose the picture…"), halign=Gtk.Align.START)
        dialog: Adw.AlertDialog | None = None

        def chosen(sha: str) -> None:
            picked["sha"] = sha
            picture.set_label(_("Picture chosen"))
            if dialog is not None:
                dialog.set_response_enabled("ok", valid())

        picture.connect("clicked", lambda _button: self.pick_picture(chosen))

        def valid() -> bool:
            return bool(text.month_day(start.get_text()) and text.month_day(end.get_text()) and "sha" in picked)

        def add() -> None:
            value.setdefault("periods", []).append({
                "name": name.get_text().strip()[:protocol.MAX_NAME] or _("Special days"),
                "from": text.month_day(start.get_text()), "to": text.month_day(end.get_text()),
                "image": picked["sha"]})
            self.changed(rebuild=True)

        dialog = common.form_dialog(self.window, _("Special days"), _("Write the days as day/month, such as 25/1."),
                                    [name, start, end], _("Add"), add, valid, extra=picture)

    # - folders and shares -

    def folders(self, value: dict[str, Any]) -> list[Gtk.Widget]:
        target = common.group("", _("Each employee's Desktop and Documents become their folder on the company's "
                                    "server or NAS. Each employee signs in to the server with their own account the "
                                    "first time."))
        share = common.entry_row(_("Shared folder, such as %s") % SHARE_EXAMPLE, value.get("share", ""))

        def edited(row_: Adw.EntryRow) -> None:
            value["share"] = row_.get_text().strip()
            if protocol.valid_share(value["share"]):
                row_.remove_css_class("error")
            else:
                row_.add_css_class("error")
            self.changed()

        share.connect("changed", edited)
        if value.get("share") and not protocol.valid_share(value["share"]):
            share.add_css_class("error")
        target.add(share)
        hint = common.row(_("%u stands for the employee's login name: each one gets a folder of their own."))
        hint.add_css_class("dim-label")
        target.add(hint)
        tidy = Adw.SwitchRow(title=_("Tidy the machines"),
                             subtitle=_("Files left on a machine move to “Chưa sắp xếp” on the server. Nothing is "
                                        "deleted."), active=bool(value.get("tidy", True)))

        def tidied(row_: Adw.SwitchRow, _param: Any) -> None:
            value["tidy"] = row_.get_active()
            self.changed()

        tidy.connect("notify::active", tidied)
        target.add(tidy)
        return [target]

    def shares(self, value: list[dict[str, Any]]) -> list[Gtk.Widget]:
        target = common.group(_("Shared drives"), _("They show in the side bar of Files (Nemo, Thunar). Each employee "
                                                    "signs in with their own account the first time."))
        target.set_header_suffix(common.button(_("Add…"), lambda: self.add_share(value)))
        if not value:
            target.add(common.row(_("No shared drive yet.")))
        for index, share in enumerate(value):
            row = common.row(share.get("name", ""), share.get("url", ""))

            def remove(position: int = index) -> None:
                del value[position]
                self.changed(rebuild=True)

            row.add_suffix(remove_button(_("Remove"), remove))
            target.add(row)
        return [target]

    def add_share(self, value: list[dict[str, Any]]) -> None:
        name = common.entry_row(_("Name, such as Kế toán"))
        url = common.entry_row(_("Address, such as smb://nas/ketoan"))

        def valid() -> bool:
            address = url.get_text().strip()
            return (0 < len(name.get_text().strip()) <= protocol.MAX_NAME and protocol.valid_share(address)
                    and "%" not in address and all(share.get("url") != address for share in value)
                    and len(value) < 20)

        def add() -> None:
            value.append({"name": name.get_text().strip(), "url": url.get_text().strip()})
            self.changed(rebuild=True)

        common.form_dialog(self.window, _("Add a shared drive"), _("An address like smb://server/folder, without a "
                                                                  "password."), [name, url], _("Add"), add, valid)

    # - browser -

    def browser(self, value: dict[str, Any]) -> list[Gtk.Widget]:
        home = common.group(_("Home page and bookmarks"), _("For Firefox, Chrome, Chromium, Cốc Cốc, Edge and Brave."))
        homepage = common.entry_row(_("Home page, such as https://amis.misa.vn"), value.get("homepage") or "")

        def home_edited(row_: Adw.EntryRow) -> None:
            address = row_.get_text().strip()
            if not address:
                value["homepage"] = None
                row_.remove_css_class("error")
            elif protocol.valid_web_url(address):
                value["homepage"] = address
                row_.remove_css_class("error")
            else:
                row_.add_css_class("error")
                return
            self.changed()

        homepage.connect("changed", home_edited)
        home.add(homepage)
        bookmarks = value.setdefault("bookmarks", [])
        for index, bookmark in enumerate(bookmarks):
            row = common.row(bookmark.get("name", ""), bookmark.get("url", ""))

            def remove(position: int = index) -> None:
                del bookmarks[position]
                self.changed(rebuild=True)

            row.add_suffix(remove_button(_("Remove"), remove))
            home.add(row)
        add = common.row(_("Add a bookmark…"), activatable=True)
        add.connect("activated", lambda _row: self.add_bookmark(bookmarks))
        home.add(add)

        block = value.setdefault("block", [])
        chosen, extra = presets.chosen(block)
        blocked = common.group(_("Blocked websites"), _("Each website is blocked with its www. and m. addresses. Zalo "
                                                        "is never in these lists."))

        def update(new_chosen: list[str], new_extra: list[str], rebuild: bool = False) -> None:
            value["block"] = presets.expand(new_chosen, new_extra)
            self.changed(rebuild)

        for preset in presets.ORDER:
            domains = presets.PRESETS[preset]
            check = Gtk.CheckButton(active=preset in chosen, valign=Gtk.Align.CENTER)
            row = common.row(presets.title(preset),
                             ngettext("%(first)s and %(count)d other site", "%(first)s and %(count)d other sites",
                                      len(domains) - 3) % {"first": ", ".join(domains[:3]), "count": len(domains) - 3})
            row.add_prefix(check)
            row.set_activatable_widget(check)

            def toggled(button: Gtk.CheckButton, item: str = preset) -> None:
                current, others = presets.chosen(value.get("block") or [])
                current = [name for name in current if name != item] + ([item] if button.get_active() else [])
                update(current, others)

            check.connect("toggled", toggled)
            blocked.add(row)
        for domain in extra:
            row = common.row(domain)

            def remove_domain(name: str = domain) -> None:
                current, others = presets.chosen(value.get("block") or [])
                update(current, [item for item in others if item != name], rebuild=True)

            row.add_suffix(remove_button(_("Remove"), remove_domain))
            blocked.add(row)
        typed = Adw.EntryRow(title=_("Add a website, such as vnexpress.net"), use_markup=False, show_apply_button=True)

        def apply(row_: Adw.EntryRow) -> None:
            domain = presets.normalize_domain(row_.get_text())
            if domain is None:
                self.ctx.toast(_("“%s” is not a website name such as facebook.com.") % row_.get_text().strip())
                return
            current, others = presets.chosen(value.get("block") or [])
            if domain in presets.expand(current, others):
                self.ctx.toast(_("%s is blocked already.") % domain)
                return
            if len(presets.expand(current, others)) >= 500:
                self.ctx.toast(_("At most 500 blocked websites."))
                return
            update(current, others + [domain], rebuild=True)

        typed.connect("apply", apply)
        typed.connect("entry-activated", apply)
        blocked.add(typed)

        when = common.group(_("When to block"))
        hours = value.get("block_hours")

        def set_hours(choice: str) -> None:
            if choice == "always" and value.get("block_hours") is not None:
                value["block_hours"] = None
                self.changed(rebuild=True)
            elif choice == "hours" and value.get("block_hours") is None:
                value["block_hours"] = {"days": list(presets.OFFICE_HOURS["days"]),
                                        "ranges": [list(item) for item in presets.OFFICE_HOURS["ranges"]]}
                self.changed(rebuild=True)

        radio_rows(when, [("hours", _("Only during working hours"), _("The websites open at lunch time and after "
                                                                      "work.")),
                          ("always", _("All the time"), "")], "hours" if hours else "always", set_hours)
        widgets: list[Gtk.Widget] = [home, blocked, when]
        if hours:
            schedule = common.group(_("Working hours"), _("Blocked inside these hours on the days chosen; a range "
                                                          "ends on the day it starts."))
            days_row = common.row(_("Days"))

            def days_changed(days: list[int]) -> None:
                hours["days"] = days
                self.changed()

            days_row.add_suffix(common.days_toggles(hours.get("days") or [], days_changed))
            schedule.add(days_row)
            ranges = hours.setdefault("ranges", [])
            for index, pair in enumerate(ranges):
                row = common.row(_("Range %d") % (index + 1))
                box = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)

                def set_time(item: str, position: int, side: int) -> None:
                    ranges[position][side] = item
                    self.changed()

                box.append(common.time_entry(pair[0], lambda item, position=index: set_time(item, position, 0)))
                box.append(common.label("–", wrap=False))
                box.append(common.time_entry(pair[1], lambda item, position=index: set_time(item, position, 1)))
                row.add_suffix(box)
                if len(ranges) > 1:
                    def remove_range(position: int = index) -> None:
                        del ranges[position]
                        self.changed(rebuild=True)

                    row.add_suffix(remove_button(_("Remove"), remove_range))
                schedule.add(row)
            buttons = Gtk.Box(spacing=12, margin_top=12)
            if len(ranges) < 6:
                buttons.append(common.button(_("Add a range"), lambda: (ranges.append(["18:00", "20:00"]),
                                                                       self.changed(rebuild=True))))

            def office() -> None:
                hours["days"] = list(presets.OFFICE_HOURS["days"])
                hours["ranges"] = [list(item) for item in presets.OFFICE_HOURS["ranges"]]
                self.changed(rebuild=True)

            buttons.append(common.button(_("Office hours"), office,
                                         tooltip=_("8:00 to 12:00 and 13:30 to 17:30, Monday to Saturday")))
            schedule.add(buttons)
            widgets.append(schedule)
        safe = common.group()
        switch = Adw.SwitchRow(title=_("Safe search"), subtitle=_("Google, Bing and YouTube hide adult content."),
                               active=bool(value.get("safe_search")))

        def safe_changed(row_: Adw.SwitchRow, _param: Any) -> None:
            value["safe_search"] = row_.get_active()
            self.changed()

        switch.connect("notify::active", safe_changed)
        safe.add(switch)
        widgets.append(safe)
        return widgets

    def add_bookmark(self, bookmarks: list[dict[str, Any]]) -> None:
        name = common.entry_row(_("Name"))
        url = common.entry_row(_("Address, such as https://thuedientu.gdt.gov.vn"))
        suggestions = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=2,
                                  column_spacing=6, row_spacing=6)
        for title, address in BOOKMARK_SUGGESTIONS:
            if any(item.get("url") == address for item in bookmarks):
                continue
            chip = Gtk.Button(label=title)
            chip.connect("clicked", lambda _button, t=title, a=address: (name.set_text(t), url.set_text(a)))
            suggestions.append(chip)
        extra = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        if suggestions.get_first_child() is not None:
            extra.append(common.secondary(_("Often used:")))
            extra.append(suggestions)

        def valid() -> bool:
            return (0 < len(name.get_text().strip()) <= protocol.MAX_NAME
                    and protocol.valid_web_url(url.get_text().strip())
                    and len(bookmarks) < 50)

        def add() -> None:
            bookmarks.append({"name": name.get_text().strip(), "url": url.get_text().strip()})
            self.changed(rebuild=True)

        common.form_dialog(self.window, _("Add a bookmark"), "", [name, url], _("Add"), add, valid, extra=extra)

    # - printers -

    def printers(self, value: list[dict[str, Any]]) -> list[Gtk.Widget]:
        target = common.group(_("Printers"), _("Added on every machine. A printer that does not answer stays in the "
                                               "list."))
        buttons = Gtk.Box(spacing=6)
        buttons.append(common.button(_("Find on the network"), lambda: self.find_printers(value)))
        buttons.append(common.button(_("Add…"), lambda: self.add_printer(value)))
        target.set_header_suffix(buttons)
        if not value:
            target.add(common.row(_("No printer yet.")))
        for index, printer in enumerate(value):
            subtitle = text.join_sentence([printer.get("uri", ""), printer.get("location", "")])
            row = common.row(printer.get("name", ""), subtitle)

            def remove(position: int = index) -> None:
                del value[position]
                self.changed(rebuild=True)

            row.add_suffix(remove_button(_("Remove"), remove))
            target.add(row)
        widgets: list[Gtk.Widget] = [target]
        if value:
            default_group = common.group()
            names = [_("None")] + [printer.get("name", "") for printer in value]
            combo = Adw.ComboRow(title=_("Default printer"), model=Gtk.StringList.new(names), use_markup=False)
            current = next((index + 1 for index, printer in enumerate(value) if printer.get("default")), 0)
            combo.set_selected(current)

            def default_changed(row_: Adw.ComboRow, _param: Any) -> None:
                for index, printer in enumerate(value):
                    printer["default"] = index + 1 == row_.get_selected()
                self.changed()

            combo.connect("notify::selected", default_changed)
            default_group.add(combo)
            widgets.append(default_group)
        return widgets

    def add_printer(self, value: list[dict[str, Any]], found: printers.Found | None = None) -> None:
        address = common.entry_row(_("IP address or name, such as 192.168.1.50"))
        uri = common.entry_row(_("Or the full address, such as ipp://192.168.1.50/ipp/print"),
                               found.uri if found else "")
        name = common.entry_row(_("Name, such as Máy in tầng 2"), found.name if found else "")
        location = common.entry_row(_("Where it is (optional)"), found.location if found else "")

        def chosen_uri() -> str | None:
            typed = uri.get_text().strip()
            if typed:
                return typed if protocol.valid_printer_uri(typed) else None
            return printers.uri_for_address(address.get_text())

        def valid() -> bool:
            names = {printer.get("name") for printer in value}
            title = name.get_text().strip()
            return bool(chosen_uri() and 0 < len(title) <= protocol.MAX_NAME and title not in names
                        and len(location.get_text().strip()) <= protocol.MAX_NAME and len(value) < 20)

        def add() -> None:
            value.append({"name": name.get_text().strip(), "uri": chosen_uri(),
                          "location": location.get_text().strip(), "default": not value})
            self.changed(rebuild=True)

        rows = [uri, name, location] if found else [address, uri, name, location]
        common.form_dialog(self.window, _("Add a printer"),
                           _("Most network printers take IPP Everywhere: the IP address is enough."), rows, _("Add"),
                           add, valid)

    def find_printers(self, value: list[dict[str, Any]]) -> None:
        self.ctx.toast(_("Looking for printers on the network…"), 3)

        def done(found: list[printers.Found] | None, error: Exception | None) -> None:
            if error is not None or not found:
                self.ctx.toast(_("No printer answered. Add it by its IP address."), 6)
                return
            dialog = Adw.Dialog(title=_("Printers on the network"), content_width=520, content_height=420)
            listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
            listing.add_css_class("boxed-list")
            known = {printer.get("uri") for printer in value}
            for item in found:
                row = common.row(item.name, text.join_sentence([item.uri, item.location]))
                if item.uri in known:
                    row.add_suffix(common.secondary(_("Added")))
                else:
                    def pick(choice: printers.Found = item) -> None:
                        dialog.close()
                        self.add_printer(value, choice)

                    row.add_suffix(common.button(_("Add…"), pick))
                listing.append(row)
            box = common.page_box()
            box.append(listing)
            dialog.set_child(common.toolbar(common.scrolled(box)))
            dialog.present(self.window)

        in_thread(printers.find, done)

    # - Wi-Fi -

    def wifi(self, value: list[dict[str, Any]]) -> list[Gtk.Widget]:
        target = common.group(_("Wi-Fi networks"), _("Laptops connect by themselves. The password is sealed for each "
                                                     "machine and never shown again."))
        target.set_header_suffix(common.button(_("Add…"), lambda: self.add_network(value)))
        if not value:
            target.add(common.row(_("No network yet.")))
        for index, network in enumerate(value):
            ssid = network.get("ssid", "")
            state = self.ctx.draft.password_state(ssid)
            subtitle = {"open": _("Open network, no password."), "saved": _("Password: saved."),
                        "new": _("Password: new, sent with the next save."),
                        "missing": _("Password: missing. Type it.")}[state]
            if network.get("hidden"):
                subtitle += " " + _("Hidden network.")
            row = common.row(ssid, subtitle)
            if state == "missing":
                row.add_css_class("problem")
            if network.get("security") == "wpa-psk":
                row.add_suffix(common.button(_("Change password…") if state != "missing" else _("Type password…"),
                                             lambda name=ssid: self.change_password(name)))

            def remove(position: int = index) -> None:
                del value[position]
                self.changed(rebuild=True)

            row.add_suffix(remove_button(_("Remove"), remove))
            target.add(row)
        return [target]

    def add_network(self, value: list[dict[str, Any]]) -> None:
        ssid = common.entry_row(_("Network name (SSID)"))
        security = Adw.ComboRow(title=_("Security"), use_markup=False,
                                model=Gtk.StringList.new([_("Password (WPA/WPA2 personal)"), _("Open, no password")]))
        hidden = Adw.SwitchRow(title=_("Hidden network"))
        password = Adw.PasswordEntryRow(title=_("Password"))
        security.connect("notify::selected", lambda row_, _param: password.set_visible(row_.get_selected() == 0))

        def valid() -> bool:
            name = ssid.get_text()
            if not 1 <= len(name.encode("utf-8")) <= 32 or any(item.get("ssid") == name for item in value):
                return False
            return len(value) < 10 and (security.get_selected() == 1 or protocol.valid_passphrase(password.get_text()))

        def add() -> None:
            name = ssid.get_text()
            wpa = security.get_selected() == 0
            value.append({"ssid": name, "security": "wpa-psk" if wpa else "open", "hidden": hidden.get_active()})
            if wpa:
                self.ctx.draft.passphrases[name] = password.get_text()
            self.changed(rebuild=True)

        common.form_dialog(self.window, _("Add a Wi-Fi network"),
                           _("The password has 8 to 63 letters, digits or signs, without Vietnamese accents."),
                           [ssid, security, hidden, password], _("Add"), add, valid)

    def change_password(self, ssid: str) -> None:
        password = Adw.PasswordEntryRow(title=_("New password"))

        def add() -> None:
            self.ctx.draft.passphrases[ssid] = password.get_text()
            self.changed(rebuild=True)

        common.form_dialog(self.window, _("Password of %s") % ssid,
                           _("The password has 8 to 63 letters, digits or signs, without Vietnamese accents."),
                           [password], _("Change"), add, lambda: protocol.valid_passphrase(password.get_text()))

    # - apps -

    def catalogue(self) -> list[catalog.App]:
        if self._catalog is None:
            self._catalog = [app for app in catalog.load() if app.id != "caramos-business"]
        return self._catalog

    def app_icon(self, app: catalog.App | None, size: int = 32) -> Gtk.Image:
        if app and app.icon_path and app.icon_path.is_file():
            image = Gtk.Image.new_from_file(str(app.icon_path))
        else:
            image = Gtk.Image.new_from_icon_name(app.icon_name if app and app.icon_name else "application-x-executable")
        image.set_pixel_size(size)
        return image

    def apps(self, value: dict[str, Any]) -> list[Gtk.Widget]:
        apps = {app.id: app for app in self.catalogue()}
        widgets: list[Gtk.Widget] = []
        if not apps:
            missing = common.group()
            missing.add(common.row(_("App Center is not installed on this machine"),
                                   _("Install App Center to choose apps from its list.")))
            widgets.append(missing)
        for key, title, description in (
                ("required", _("Required"), _("Installed on machines that do not have them.")),
                ("forbidden", _("Not allowed"), _("Removed from machines that have them."))):
            target = common.group(title, description)
            ids = value.setdefault(key, [])
            if apps:
                target.set_header_suffix(common.button(_("Add…"), lambda list_key=key: self.pick_app(value, list_key)))
            if not ids:
                target.add(common.row(_("None.")))
            for index, app_id in enumerate(ids):
                app = apps.get(app_id)
                row = common.row(app.name if app else app_id, app.summary if app else _("Not in App Center's list."))
                row.add_prefix(self.app_icon(app))

                def remove(position: int = index, list_ids: list[str] = ids) -> None:
                    del list_ids[position]
                    self.changed(rebuild=True)

                row.add_suffix(remove_button(_("Remove"), remove))
                target.add(row)
            widgets.append(target)
        return widgets

    def pick_app(self, value: dict[str, Any], key: str) -> None:
        taken = set(value.get("required") or []) | set(value.get("forbidden") or [])
        dialog = Adw.Dialog(title=_("Required apps") if key == "required" else _("Apps not allowed"),
                            content_width=480, content_height=560)
        search = Gtk.SearchEntry(placeholder_text=_("Search"), hexpand=True)
        listing = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listing.add_css_class("boxed-list")
        rows = []
        for app in self.catalogue():
            if app.id in taken:
                continue
            row = common.row(app.name, app.summary, activatable=True)
            row.add_prefix(self.app_icon(app))
            row.search_text = text.fold(f"{app.name} {app.summary} {app.id}")

            def chosen(_row: Adw.ActionRow, item: catalog.App = app) -> None:
                if len(value.setdefault(key, [])) >= 50:
                    self.ctx.toast(_("At most 50 apps in each list."))
                    return
                value[key].append(item.id)
                dialog.close()
                self.changed(rebuild=True)

            row.connect("activated", chosen)
            rows.append(row)
            listing.append(row)

        def filtered(entry: Gtk.SearchEntry) -> None:
            words = text.fold(entry.get_text()).split()
            for item in rows:
                item.set_visible(all(word in item.search_text for word in words))

        search.connect("search-changed", filtered)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=24,
                      margin_start=24, margin_end=24)
        box.append(search)
        box.append(listing)
        dialog.set_child(common.toolbar(common.scrolled(box)))
        dialog.present(self.window)
        search.grab_focus()

    # - power -

    def power(self, value: dict[str, Any]) -> list[Gtk.Widget]:
        off = common.group(_("Shut down by a schedule"))
        shutdown = value.get("shutdown")
        switch = Adw.SwitchRow(title=_("Shut the machines down at a set time"), active=shutdown is not None)

        def shutdown_switched(row_: Adw.SwitchRow, _param: Any) -> None:
            value["shutdown"] = draft.shutdown_defaults() if row_.get_active() else None
            self.changed(rebuild=True)

        switch.connect("notify::active", shutdown_switched)
        off.add(switch)
        widgets: list[Gtk.Widget] = [off]
        if shutdown:
            explain = common.secondary("", "paragraph")

            def explained() -> None:
                explain.set_label(power_text(value))
                self.changed()

            days = common.row(_("Days"))
            days.add_suffix(common.days_toggles(shutdown["days"], lambda chosen: (shutdown.__setitem__("days", chosen),
                                                                                  explained())))
            off.add(days)
            time_row = common.row(_("Time"))
            time_row.add_suffix(common.time_entry(shutdown["time"], lambda item: (shutdown.__setitem__("time", item),
                                                                                   explained())))
            off.add(time_row)
            for key, title, low, high, step in (("warn_minutes", _("Warn before (minutes)"), 1, 30, 1),
                                                ("postpone_minutes", _("Each postponement (minutes)"), 5, 120, 5),
                                                ("max_postpones", _("Postponements allowed"), 0, 5, 1)):
                spin = Adw.SpinRow.new_with_range(low, high, step)
                spin.set_title(title)
                spin.set_value(shutdown.get(key, low))

                def spun(row_: Adw.SpinRow, _param: Any, item: str = key) -> None:
                    shutdown[item] = int(row_.get_value())
                    explained()

                spin.connect("notify::value", spun)
                off.add(spin)
            laptops = Adw.ComboRow(title=_("Laptops"), use_markup=False, model=Gtk.StringList.new(
                [_("Leave them on"), _("Put them to sleep"), _("Shut them down too")]))
            laptops.set_selected(protocol.LAPTOP_CHOICES.index(shutdown.get("laptops", "skip")))

            def laptops_changed(row_: Adw.ComboRow, _param: Any) -> None:
                shutdown["laptops"] = protocol.LAPTOP_CHOICES[row_.get_selected()]
                explained()

            laptops.connect("notify::selected", laptops_changed)
            off.add(laptops)
            explain.set_label(power_text(value))
            explain.set_margin_top(12)
            off.add(explain)
        on = common.group(_("Turn on by a schedule"))
        wake = value.get("wake")
        wake_switch = Adw.SwitchRow(title=_("Turn the machines on at a set time"), active=wake is not None)

        def wake_switched(row_: Adw.SwitchRow, _param: Any) -> None:
            value["wake"] = draft.wake_defaults() if row_.get_active() else None
            self.changed(rebuild=True)

        wake_switch.connect("notify::active", wake_switched)
        on.add(wake_switch)
        if wake:
            days = common.row(_("Days"))
            days.add_suffix(common.days_toggles(wake["days"], lambda chosen: (wake.__setitem__("days", chosen),
                                                                              self.changed())))
            on.add(days)
            time_row = common.row(_("Time"))
            time_row.add_suffix(common.time_entry(wake["time"], lambda item: (wake.__setitem__("time", item),
                                                                               self.changed())))
            on.add(time_row)
            note = common.secondary(_("A machine turns on by itself if it can: before each scheduled shutdown it sets "
                                      "its own wake-up time, and this machine sends a Wake-on-LAN signal over the "
                                      "network cable at that time, so it must be on. Some machines need Wake-on-LAN "
                                      "turned on in their BIOS."), "paragraph")
            note.set_margin_top(12)
            on.add(note)
        widgets.append(on)
        return widgets

    # - security -

    def usb(self, value: dict[str, Any]) -> list[Gtk.Widget]:
        target = common.group()

        def chosen(item: str) -> None:
            value["storage"] = item
            self.changed()

        radio_rows(target, [("allow", _("Allowed"), _("USB drives work as usual.")),
                            ("read-only", _("Read only"), _("Employees can open files on USB drives but cannot copy "
                                                            "files onto them.")),
                            ("block", _("Blocked"), _("USB drives do not open."))],
                   value.get("storage", "read-only"), chosen)
        note = common.secondary(_("Keyboards, mice, printers and digital signature tokens keep working. To let one "
                                  "machine use USB for a while, open the machine's page."), "paragraph")
        note.set_margin_top(12)
        target.add(note)
        return [target]

    def screen_lock(self, value: dict[str, Any]) -> list[Gtk.Widget]:
        target = common.group()
        spin = Adw.SpinRow.new_with_range(1, 120, 1)
        spin.set_title(_("Lock after (minutes without use)"))
        spin.set_value(value.get("idle_minutes", 10))

        def spun(row_: Adw.SpinRow, _param: Any) -> None:
            value["idle_minutes"] = int(row_.get_value())
            self.changed()

        spin.connect("notify::value", spun)
        target.add(spin)
        suspend = Adw.SwitchRow(title=_("Lock when the machine goes to sleep"),
                                active=bool(value.get("on_suspend", True)))

        def suspended(row_: Adw.SwitchRow, _param: Any) -> None:
            value["on_suspend"] = row_.get_active()
            self.changed()

        suspend.connect("notify::active", suspended)
        target.add(suspend)
        return [target]

    def firewall(self, value: dict[str, Any]) -> list[Gtk.Widget]:
        return [common.secondary(_("Other machines cannot connect to employee machines. Going online, printing and the "
                                   "shared folders work as usual. The firewall can only be turned on from here."),
                                 "paragraph")]

    def inventory(self, value: dict[str, Any]) -> list[Gtk.Widget]:
        return [common.secondary(_("Machines send their hardware, disks, battery, screens and list of apps, for the "
                                   "asset list. Never files, browsing or anything employees do."), "paragraph")]

    # - shared machines -

    def shared(self, value: dict[str, Any]) -> list[Gtk.Widget]:
        guest_group = common.group(_("Guest session"))
        guest = Adw.SwitchRow(title=_("A guest session on the login screen"), active=bool(value.get("guest")),
                              use_markup=False)
        guest.set_subtitle(_("Anyone can log in without an account. The guest's files are deleted when they log "
                             "out."))

        def guest_switched(row_: Adw.SwitchRow, _param: Any) -> None:
            value["guest"] = row_.get_active()
            self.changed()

        guest.connect("notify::active", guest_switched)
        guest_group.add(guest)
        freeze_group = common.group(_("Freezing"))
        freeze = Adw.SwitchRow(title=_("Freeze the machines"), active=bool(value.get("freeze")), use_markup=False)
        freeze.set_subtitle(_("Every change on a machine is undone when it restarts: files, settings and installed "
                              "apps. It takes effect at the next restart."))

        def freeze_switched(row_: Adw.SwitchRow, _param: Any) -> None:
            value["freeze"] = row_.get_active()
            if value["freeze"] and not value.get("maintenance"):
                value["maintenance"] = draft.maintenance_defaults()
            self.changed(rebuild=True)

        freeze.connect("notify::active", freeze_switched)
        freeze_group.add(freeze)
        widgets: list[Gtk.Widget] = [guest_group, freeze_group]
        if not value.get("freeze"):
            return widgets
        maintenance = value.setdefault("maintenance", draft.maintenance_defaults())
        window = common.group(_("Maintenance time"), _("A frozen machine takes its updates only then."))
        explain = common.secondary("", "paragraph")

        def explained() -> None:
            explain.set_label(maintenance_text(maintenance))
            self.changed()

        days = common.row(_("Days"))
        days.add_suffix(common.days_toggles(maintenance["days"], lambda chosen: (maintenance.__setitem__("days", chosen),
                                                                                  explained())))
        window.add(days)
        time_row = common.row(_("Time"))
        time_row.add_suffix(common.time_entry(maintenance["time"], lambda item: (maintenance.__setitem__("time", item),
                                                                                  explained())))
        window.add(time_row)
        spin = Adw.SpinRow.new_with_range(15, 240, 15)
        spin.set_title(_("Longest maintenance (minutes)"))
        spin.set_value(maintenance.get("max_minutes", 60))

        def spun(row_: Adw.SpinRow, _param: Any) -> None:
            maintenance["max_minutes"] = int(row_.get_value())
            explained()

        spin.connect("notify::value", spun)
        window.add(spin)
        explain.set_label(maintenance_text(maintenance))
        explain.set_margin_top(12)
        window.add(explain)
        widgets.append(window)
        small = self.low_memory_machines()
        memory = common.group(_("Machines with little memory"))
        if small:
            memory.set_description(ngettext(
                "%(names)s has less than 3 GB of memory: frozen, it keeps every change in memory and may slow "
                "down.", "%(names)s have less than 3 GB of memory: frozen, they keep every change in memory and may "
                "slow down.", len(small)) % {"names": ", ".join(small)})
        allow = Adw.SwitchRow(title=_("Freeze machines with less than 3 GB of memory too"), use_markup=False,
                              active=bool(value.get("low_memory_ok")))
        allow.set_subtitle(_("Without this, such machines are not frozen and say why."))

        def allowed(row_: Adw.SwitchRow, _param: Any) -> None:
            value["low_memory_ok"] = row_.get_active()
            self.changed()

        allow.connect("notify::active", allowed)
        memory.add(allow)
        widgets.append(memory)
        note = common.secondary(_("Freezing cannot be on together with system snapshots, or with tidying Desktop and "
                                  "Documents onto the server: saving refuses it. Remind people to keep their files on "
                                  "the shared drive or a USB drive."), "paragraph")
        widgets.append(note)
        return widgets

    def low_memory_machines(self) -> list[str]:
        """The machines of the page's scope with less than 3 GiB, from their last check-in."""

        scope = self.ctx.scope
        found = []
        for machine_id, entry in self.ctx.machines.items():
            memory = (entry.get("health") or {}).get("memory_mb")
            if not isinstance(memory, int) or memory >= 3072:
                continue
            kind, _sep, key = scope.partition(":")
            if kind == "department" and self.ctx.draft.department_of(machine_id) != key or \
                    kind == "machine" and machine_id != key:
                continue
            found.append(self.ctx.machine_name(machine_id))
        return sorted(found)

    # - snapshots -

    def snapshots(self, value: dict[str, Any]) -> list[Gtk.Widget]:
        target = common.group()
        schedule = Adw.ComboRow(title=_("Take a snapshot"), use_markup=False, model=Gtk.StringList.new(
            [_("Every day"), _("Every week"), _("Every month")]))
        schedule.set_selected(protocol.SNAPSHOT_SCHEDULES.index(value.get("schedule", "weekly")))

        def scheduled(row_: Adw.ComboRow, _param: Any) -> None:
            value["schedule"] = protocol.SNAPSHOT_SCHEDULES[row_.get_selected()]
            self.changed()

        schedule.connect("notify::selected", scheduled)
        target.add(schedule)
        keep = Adw.SpinRow.new_with_range(1, 20, 1)
        keep.set_title(_("Snapshots to keep"))
        keep.set_value(value.get("keep", 3))

        def kept(row_: Adw.SpinRow, _param: Any) -> None:
            value["keep"] = int(row_.get_value())
            self.changed()

        keep.connect("notify::value", kept)
        target.add(keep)
        before = Adw.SwitchRow(title=_("One more snapshot before each update"), use_markup=False,
                               active=bool(value.get("before_update", True)))

        def before_switched(row_: Adw.SwitchRow, _param: Any) -> None:
            value["before_update"] = row_.get_active()
            self.changed()

        before.connect("notify::active", before_switched)
        target.add(before)
        note = common.group(_("Not a backup"))
        note.add(common.row(_("Snapshots are on the same disk as the system"),
                            _("If the disk breaks, the snapshots are lost with it. They hold the system, not people's "
                              "files: keep files on the server, and back them up elsewhere.")))
        note.add(common.row(_("Going back to a snapshot"),
                            _("On the machine itself, open the Timeshift app and choose a snapshot. The guide "
                              "explains each step.")))
        note.add(common.row(_("Disk space"),
                            _("The first snapshot takes about as much space as the system; later ones only what "
                              "changed. The Security report shows how much each machine uses.")))
        return [target, note]


def maintenance_text(maintenance: dict[str, Any]) -> str:
    """What happens at the maintenance time, in plain words."""

    return _("At %(time)s on %(days)s this machine wakes the frozen machines; each one restarts unfrozen, takes its "
             "updates and the company's apps, then restarts frozen again. When someone is using a machine, it tries "
             "again every 15 minutes for up to %(minutes)d minutes, then skips the day.") % {
        "time": maintenance.get("time", ""), "days": text.days_text(maintenance.get("days") or []) or _("no day"),
        "minutes": maintenance.get("max_minutes", 60)}


def power_text(value: dict[str, Any]) -> str:
    """What employees see with this schedule, in plain words."""

    shutdown = value.get("shutdown")
    if not shutdown:
        return ""
    parts = [_("At %(time)s on %(days)s the machines shut down.") % {
        "time": shutdown["time"], "days": text.days_text(shutdown["days"]) or _("no day")}]
    warn, postpone, times = shutdown.get("warn_minutes", 10), shutdown.get("postpone_minutes", 30), \
        shutdown.get("max_postpones", 2)
    if times:
        parts.append(ngettext("%(warn)d minutes before, whoever is using a machine sees a countdown and can postpone "
                              "by %(postpone)d minutes, once.",
                              "%(warn)d minutes before, whoever is using a machine sees a countdown and can postpone "
                              "by %(postpone)d minutes, up to %(times)d times.", times)
                     % {"warn": warn, "postpone": postpone, "times": times})
    else:
        parts.append(_("%d minutes before, whoever is using a machine sees a countdown.") % warn)
    parts.append(_("A machine nobody is logged in to shuts down at once."))
    laptops = shutdown.get("laptops", "skip")
    parts.append({"skip": _("Laptops stay on."), "suspend": _("Laptops go to sleep instead."),
                  "same": _("Laptops shut down too.")}[laptops])
    return " ".join(parts)

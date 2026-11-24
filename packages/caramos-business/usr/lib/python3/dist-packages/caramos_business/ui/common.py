"""Widget helpers shared by the pages of CaramOS Doanh nghiệp.

The look follows CaramOS's design rules (DESIGN.md in the CaramOS repository): libadwaita's header bars, surfaces and
boxed lists, the forest green accent as the only colour, two font weights, sentences instead of chips. Rows show
user data as plain text, never as markup."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Graphene", "1.0")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Graphene, Gtk, Pango  # noqa: E402

from .. import DATA  # noqa: E402
from ..i18n import _  # noqa: E402

LOGO = Path("/usr/share/pixmaps/caramos-logo.png")
APP_ID = "net.vietnamlinuxfamily.caramos.Business"


def data_dir() -> Path:
    """The stylesheets: installed, or next to the package in the source tree."""

    if (DATA / "style.css").is_file():
        return DATA
    return Path(__file__).resolve().parents[6] / "usr/share/caramos-business"


def load_css() -> None:
    display = Gdk.Display.get_default()
    if display is None:
        return
    base = Gtk.CssProvider()
    base.load_from_path(str(data_dir() / "style.css"))
    Gtk.StyleContext.add_provider_for_display(display, base, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    dark = Gtk.CssProvider()
    dark.load_from_path(str(data_dir() / "style-dark.css"))
    manager = Adw.StyleManager.get_default()

    def apply(*_args: Any) -> None:
        if manager.get_dark():
            Gtk.StyleContext.add_provider_for_display(display, dark, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        else:
            Gtk.StyleContext.remove_provider_for_display(display, dark)

    manager.connect("notify::dark", apply)
    apply()


def label(text: str, *classes: str, wrap: bool = True, xalign: float = 0.0, lines: int = 0,
          selectable: bool = False) -> Gtk.Label:
    widget = Gtk.Label(label=text, xalign=xalign, selectable=selectable)
    if lines:
        widget.set_lines(lines)
        widget.set_ellipsize(Pango.EllipsizeMode.END)
        widget.set_wrap(lines > 1)
    else:
        widget.set_wrap(wrap)
    widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    for css_class in classes:
        widget.add_css_class(css_class)
    return widget


def secondary(text: str, *classes: str, **kwargs: Any) -> Gtk.Label:
    return label(text, "dim-label", "secondary", *classes, **kwargs)


class Row(Adw.ActionRow):
    """An ActionRow whose "go on" arrow stays the last suffix, after whatever is added later."""

    def __init__(self, chevron: bool, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.chevron = Gtk.Image.new_from_icon_name("go-next-symbolic") if chevron else None
        if self.chevron is not None:
            super().add_suffix(self.chevron)

    def add_suffix(self, widget: Gtk.Widget) -> None:
        if self.chevron is not None:
            self.remove(self.chevron)
        super().add_suffix(widget)
        if self.chevron is not None:
            super().add_suffix(self.chevron)


def row(title: str, subtitle: str = "", *, activatable: bool = False, icon: str | None = None) -> Adw.ActionRow:
    """A row with plain text (titles and subtitles are not markup); an activatable one ends with an arrow."""

    widget = Row(activatable, title=title, subtitle=subtitle, use_markup=False, activatable=activatable)
    widget.set_title_lines(0)
    widget.set_subtitle_lines(0)
    if icon:
        widget.add_prefix(Gtk.Image.new_from_icon_name(icon))
    return widget


def property_row(title: str, value: str) -> Adw.ActionRow:
    """A fact: the value in the row's main text, its name above it."""

    widget = Adw.ActionRow(title=title, subtitle=value or "—", use_markup=False)
    widget.add_css_class("property")
    widget.set_subtitle_selectable(True)
    widget.set_subtitle_lines(0)
    return widget


def button(text: str, callback: Callable[[], Any], *classes: str, tooltip: str = "",
           icon: str | None = None) -> Gtk.Button:
    widget = Gtk.Button(valign=Gtk.Align.CENTER)
    if icon and not text:
        widget.set_icon_name(icon)
    else:
        widget.set_label(text)
    if tooltip:
        widget.set_tooltip_text(tooltip)
    for css_class in classes:
        widget.add_css_class(css_class)
    widget.connect("clicked", lambda _button: callback())
    return widget


def icon_button(icon: str, tooltip: str, callback: Callable[[], Any]) -> Gtk.Button:
    widget = button("", callback, "flat", tooltip=tooltip, icon=icon)
    widget.update_property([Gtk.AccessibleProperty.LABEL], [tooltip])
    return widget


def group(title: str = "", description: str = "") -> Adw.PreferencesGroup:
    return Adw.PreferencesGroup(title=GLib.markup_escape_text(title), description=GLib.markup_escape_text(description))


class Rows:
    """The rows a page adds to a group, so that they can be replaced together."""

    def __init__(self, target: Adw.PreferencesGroup) -> None:
        self.target = target
        self.items: list[Gtk.Widget] = []

    def add(self, widget: Gtk.Widget) -> Gtk.Widget:
        self.target.add(widget)
        self.items.append(widget)
        return widget

    def clear(self) -> None:
        for widget in self.items:
            self.target.remove(widget)
        self.items.clear()


def toolbar(content: Gtk.Widget, title: str = "", header: Adw.HeaderBar | None = None) -> Adw.ToolbarView:
    view = Adw.ToolbarView()
    bar = header or Adw.HeaderBar()
    if title:
        bar.set_title_widget(Adw.WindowTitle(title=title))
    view.add_top_bar(bar)
    view.set_content(content)
    return view


def status_page(icon: str, title: str, description: str = "", *buttons: Gtk.Widget) -> Adw.StatusPage:
    page = Adw.StatusPage(icon_name=icon, title=title, description=GLib.markup_escape_text(description))
    if buttons:
        box = Gtk.Box(spacing=12, halign=Gtk.Align.CENTER)
        for widget in buttons:
            widget.add_css_class("pill")
            box.append(widget)
        page.set_child(box)
    return page


def logo(size: int) -> Gtk.Image:
    image = Gtk.Image.new_from_file(str(LOGO)) if LOGO.is_file() else Gtk.Image.new_from_icon_name("network-server")
    image.set_pixel_size(size)
    image.set_valign(Gtk.Align.START)
    return image


def open_uri(widget: Gtk.Widget, uri: str) -> None:
    root = widget.get_root()
    Gtk.UriLauncher.new(uri).launch(root if isinstance(root, Gtk.Window) else None, None, None, None)


def link_label(text: str, link_text: str, uri: str, *classes: str) -> Gtk.Label:
    widget = label("", *classes)
    widget.set_markup(f"{GLib.markup_escape_text(text)} <a href=\"{GLib.markup_escape_text(uri)}\">"
                      f"{GLib.markup_escape_text(link_text)}</a>")

    def activate(widget_: Gtk.Label, target: str) -> bool:
        open_uri(widget_, target)
        return True

    widget.connect("activate-link", activate)
    return widget


def confirm(parent: Gtk.Widget, heading: str, body: str, action: str, callback: Callable[[], Any],
            destructive: bool = False) -> None:
    dialog = Adw.AlertDialog(heading=heading, body=body)
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("ok", action)
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.DESTRUCTIVE if destructive else
                                   Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("cancel" if destructive else "ok")
    dialog.set_close_response("cancel")
    dialog.connect("response", lambda _dialog, answer: callback() if answer == "ok" else None)
    dialog.present(parent)


def form_dialog(parent: Gtk.Widget, heading: str, body: str, rows: list[Gtk.Widget], action: str,
                callback: Callable[[], Any], valid: Callable[[], bool] | None = None,
                extra: Gtk.Widget | None = None) -> Adw.AlertDialog:
    """A dialog with a boxed list of fields. valid() is checked after every change and enables the action.

    In a dialog of fields only (no `extra`, such as a message's text), Enter in a text field presses the action button
    once it is enabled. It goes by the field's "entry-activated", which comes after an input method (Vietnamese
    typing) has committed what was typed. libadwaita 1.5 does not pass an AdwDialog's default widget to the window it
    is shown in, so "activates-default" would do nothing."""

    dialog = Adw.AlertDialog(heading=heading, body=body)
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    if rows:
        listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        listbox.add_css_class("boxed-list")
        for item in rows:
            listbox.append(item)
        box.append(listbox)
    if extra is not None:
        box.append(extra)
    dialog.set_extra_child(box)
    dialog.add_response("cancel", _("Cancel"))
    dialog.add_response("ok", action)
    dialog.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("ok")
    dialog.set_close_response("cancel")

    def check(*_args: Any) -> None:
        dialog.set_response_enabled("ok", valid() if valid else True)

    def submit(_row: Adw.EntryRow) -> None:
        button = dialog.get_default_widget()  # the button of the default response, "ok"
        if isinstance(button, Gtk.Button) and dialog.get_response_enabled("ok"):
            button.emit("clicked")

    for item in rows:
        for signal in ("changed", "notify::selected", "notify::active"):
            if GObject_has_signal(item, signal):
                item.connect(signal, check)
        if extra is None and isinstance(item, Adw.EntryRow):
            item.connect("entry-activated", submit)
    check()
    dialog.connect("response", lambda _dialog, answer: callback() if answer == "ok" else None)
    dialog.present(parent)
    return dialog


def GObject_has_signal(widget: Gtk.Widget, signal: str) -> bool:  # noqa: N802 - reads as the GObject call it wraps
    name = signal.split("::", 1)
    if name[0] == "notify":
        return widget.find_property(name[1]) is not None
    return GObject.signal_lookup(signal, type(widget)) != 0


def entry_row(title: str, text: str = "", activates: Callable[[], Any] | None = None) -> Adw.EntryRow:
    widget = Adw.EntryRow(title=title, use_markup=False)
    widget.set_text(text)
    if activates is not None:
        widget.connect("entry-activated", lambda _row: activates())
    return widget


def days_toggles(days: list[int], changed: Callable[[list[int]], Any]) -> Gtk.Box:
    """Seven toggles, Monday first."""

    from ..text import weekday_names

    box = Gtk.Box(spacing=4, valign=Gtk.Align.CENTER)
    box.add_css_class("linked")
    toggles: list[Gtk.ToggleButton] = []

    def toggled(_button: Gtk.ToggleButton) -> None:
        chosen = [number for number, toggle in enumerate(toggles, start=1) if toggle.get_active()]
        changed(chosen)

    for number, name in enumerate(weekday_names(), start=1):
        toggle = Gtk.ToggleButton(label=name, active=number in days)
        toggle.add_css_class("day-toggle")
        toggle.connect("toggled", toggled)
        toggles.append(toggle)
        box.append(toggle)
    return box


def time_entry(value: str, changed: Callable[[str], Any]) -> Gtk.Entry:
    """HH:MM: the value goes out only when it is a time; the entry shows an error otherwise."""

    from .. import protocol

    widget = Gtk.Entry(text=value, max_length=5, width_chars=5, max_width_chars=5, valign=Gtk.Align.CENTER,
                       xalign=0.5)
    widget.set_input_purpose(Gtk.InputPurpose.DIGITS)

    def on_change(entry: Gtk.Entry) -> None:
        text = entry.get_text().strip()
        if len(text) == 4 and text[1] == ":":
            text = "0" + text
        if protocol.valid_time(text):
            entry.remove_css_class("error")
            changed(text)
        else:
            entry.add_css_class("error")

    widget.connect("changed", on_change)
    return widget


def notify(application: Gio.Application | None, key: str, title: str, body: str) -> None:
    if application is None:
        return
    notification = Gio.Notification.new(title)
    notification.set_body(body)
    notification.set_priority(Gio.NotificationPriority.HIGH)
    application.send_notification(key, notification)


def scrolled(child: Gtk.Widget) -> Gtk.ScrolledWindow:
    window = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    window.set_child(child)
    return window


def clamp(child: Gtk.Widget, width: int = 760) -> Adw.Clamp:
    widget = Adw.Clamp(maximum_size=width, tightening_threshold=width - 120)
    widget.set_child(child)
    return widget


def page_box() -> Gtk.Box:
    """The column of a page: 24 px around it and between its sections (DESIGN.md)."""

    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24, margin_top=24, margin_bottom=24,
                   margin_start=24, margin_end=24)


def children(widget: Gtk.Widget) -> list[Gtk.Widget]:
    found = []
    child = widget.get_first_child()
    while child is not None:
        found.append(child)
        child = child.get_next_sibling()
    return found


def top_in(widget: Gtk.Widget, ancestor: Gtk.Widget) -> float | None:
    """Where the top of widget is in ancestor's coordinates, once laid out."""

    ok, point = widget.compute_point(ancestor, Graphene.Point().init(0, 0))
    return point.y if ok else None


def keep_place(box: Gtk.Widget) -> Callable[[], None]:
    """Called before the children of box (in a scrolled page) are built again; returns what to call once they are, so
    that the page does not move: the child that holds the focus (the group of a leaver step just ticked, of a note
    just added) shows where it showed; without one, the scroll position stays. 0.3.1 kept only the scroll position,
    and the page jumped when a group above the one in use changed height.

    Places are taken in the content's own coordinates (what the scrolled window moves as a whole) and the scroll
    position from the adjustment, so neither depends on when the view last moved; the new place is read after the
    layout that follows the rebuild (the adjustment changes then), or after a moment when nothing changed size."""

    scrolled = box.get_ancestor(Gtk.ScrolledWindow)
    if scrolled is None:
        return lambda: None
    adjustment = scrolled.get_vadjustment()
    viewport = scrolled.get_child()
    content = viewport.get_child() if isinstance(viewport, Gtk.Viewport) else viewport
    value = adjustment.get_value()
    root = box.get_root()
    focus = root.get_focus() if root is not None else None
    anchor: tuple[int, float] | None = None
    for index, child in enumerate(children(box)):
        if focus is not None and (focus is child or focus.is_ancestor(child)):
            top = top_in(child, content) if content is not None else None
            if top is not None:
                anchor = (index, top - value)  # where it shows: its top, less the part scrolled away
            break

    def restore() -> None:
        state = {"done": False, "handler": 0, "tries": 0}

        def apply() -> bool:
            if state["done"]:
                return GLib.SOURCE_REMOVE
            found = children(box)
            target = found[anchor[0]] if anchor is not None and anchor[0] < len(found) else None
            if target is not None and target.get_height() == 0 and state["tries"] < 30:
                state["tries"] += 1
                return GLib.SOURCE_CONTINUE  # not laid out yet: the timer looks again
            state["done"] = True
            if state["handler"]:
                adjustment.disconnect(state["handler"])
            top = top_in(target, content) if target is not None and content is not None else None
            adjustment.set_value(top - anchor[1] if top is not None and anchor is not None else value)
            return GLib.SOURCE_REMOVE

        # The layout of the new children changes the adjustment (the page's height); the places are final once that
        # layout is over, at the next idle moment. Without a change of height, the timer does it.
        state["handler"] = adjustment.connect("changed", lambda _adjustment: GLib.idle_add(lambda: apply() and False))
        GLib.timeout_add(100, apply)

    return restore

"""The building blocks of the popup, as in the Cinnamon applet: round buttons, the battery pill, slider rows, simple
and split tiles (a pill with an arrow on its right end), list rows and the inline card."""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk, Pango  # noqa: E402

from .i18n import _  # noqa: E402

TILE_WIDTH = 130
TILE_HEIGHT = 44


def icon(name: str | list[str], size: int, css_class: str) -> Gtk.Image:
    image = Gtk.Image()
    set_icon(image, name)
    image.set_pixel_size(size)
    image.get_style_context().add_class(css_class)
    return image


def set_icon(image: Gtk.Image, name: str | list[str]) -> None:
    """A themed icon, or the first of several names the icon theme has (e.g. dark-mode-symbolic is missing from
    some themes)."""

    names = [name] if isinstance(name, str) else list(name)
    theme = Gtk.IconTheme.get_default()
    chosen = next((n for n in names if theme.has_icon(n)), names[0])
    image.set_from_icon_name(chosen, Gtk.IconSize.MENU)


def label(text: str, css_class: str, ellipsize: bool = True) -> Gtk.Label:
    """A label; an ellipsized one asks for no width of its own, so long text is cut and the popup keeps the width of
    Cinnamon's (the label must be packed to expand)."""

    widget = Gtk.Label(label=text, xalign=0)
    widget.get_style_context().add_class(css_class)
    if ellipsize:
        widget.set_ellipsize(Pango.EllipsizeMode.END)
        widget.set_max_width_chars(1)
    return widget


def styled(widget: Gtk.Widget, *classes: str) -> Gtk.Widget:
    for css_class in classes:
        widget.get_style_context().add_class(css_class)
    return widget


def set_class(widget: Gtk.Widget, css_class: str, on: bool) -> None:
    context = widget.get_style_context()
    if on:
        context.add_class(css_class)
    else:
        context.remove_class(css_class)


def round_button(icon_name: str, tooltip: str, on_click: Callable[[], None]) -> Gtk.Button:
    button = styled(Gtk.Button(), "caramos-cc-round-button")
    button.add(icon(icon_name, 15, "caramos-cc-round-icon"))
    button.set_tooltip_text(tooltip)
    button.get_accessible().set_name(tooltip)
    button.connect("clicked", lambda *_: on_click())
    return button


class Pill(Gtk.Button):
    """The battery pill of the header: icon and percentage."""

    def __init__(self, on_click: Callable[[], None]) -> None:
        super().__init__()
        styled(self, "caramos-cc-battery-pill")
        box = Gtk.Box(spacing=6)
        self.image = icon("battery-full-symbolic", 14, "caramos-cc-pill-icon")
        self.text = label("--%", "caramos-cc-pill-label", ellipsize=False)
        box.pack_start(self.image, False, False, 0)
        box.pack_start(self.text, False, False, 0)
        self.add(box)
        self.connect("clicked", lambda *_: on_click())


class SliderRow(Gtk.Box):
    """Icon (click to mute), slider, and an arrow for the device list. set_value() does not call on_change."""

    def __init__(self, icon_name: str, name: str, on_change: Callable[[float], None],
                 on_icon: Callable[[], None] | None = None, on_details: Callable[[], None] | None = None) -> None:
        super().__init__(spacing=6)
        styled(self, "caramos-cc-slider-row")
        self.on_change = on_change
        self.dragging = False
        self.icon_button = styled(Gtk.Button(), "caramos-cc-slider-icon-button")
        self.icon_button.set_valign(Gtk.Align.CENTER)
        self.image = icon(icon_name, 16, "caramos-cc-slider-icon")
        self.icon_button.add(self.image)
        self.icon_button.set_tooltip_text(_("Mute or unmute %s") % name)
        if on_icon:
            self.icon_button.connect("clicked", lambda *_: on_icon())
        else:
            self.icon_button.set_sensitive(False)
        self.pack_start(self.icon_button, False, False, 0)

        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 1, 0.01)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.get_accessible().set_name(name)
        self._handler = self.scale.connect("value-changed", self._changed)
        self.scale.connect("button-press-event", self._press)
        self.scale.connect("button-release-event", self._release)
        self.pack_start(self.scale, True, True, 0)

        self.details_button = None
        if on_details:
            self.details_button = styled(Gtk.Button(), "caramos-cc-audio-disclosure")
            self.details_button.set_valign(Gtk.Align.CENTER)
            self.details_button.add(icon("pan-end-symbolic", 14, "caramos-cc-arrow-icon"))
            self.details_button.set_tooltip_text(_("Open details for %s") % name)
            self.details_button.connect("clicked", lambda *_: on_details())
            self.pack_start(self.details_button, False, False, 0)

    def _press(self, *_args: object) -> bool:
        self.dragging = True
        return False

    def _release(self, *_args: object) -> bool:
        GLib.timeout_add(250, self._drag_over)
        return False

    def _drag_over(self) -> bool:
        self.dragging = False
        return False

    def _changed(self, scale: Gtk.Scale) -> None:
        self.on_change(scale.get_value())

    def set_value(self, value: float) -> None:
        if self.dragging:
            return
        with self.scale.handler_block(self._handler):
            self.scale.set_value(max(0.0, min(value, 1.0)))

    def set_icon_name(self, name: str) -> None:
        set_icon(self.image, name)

    def set_enabled(self, enabled: bool) -> None:
        self.scale.set_sensitive(enabled)
        self.icon_button.set_sensitive(enabled)
        if self.details_button is not None:
            self.details_button.set_sensitive(enabled)
        set_class(self, "caramos-cc-disabled", not enabled)


class Tile(Gtk.Box):
    """A pill tile: icon, title and subtitle; a split tile also has an arrow on its right end for details."""

    def __init__(self, icon_name: str | list[str], title: str, subtitle: str, on_click: Callable[[], None],
                 on_details: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.title_text = title
        self.split = on_details is not None
        self.main = Gtk.Button()
        content = Gtk.Box()
        slot = Gtk.Box()
        slot.set_size_request(22, 22)
        self.image = icon(icon_name, 16, "caramos-cc-tile-icon")
        slot.pack_start(self.image, False, False, 0)
        content.pack_start(slot, False, False, 0)
        content.set_spacing(6)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        labels.set_valign(Gtk.Align.CENTER)
        self.title = label(title, "caramos-cc-tile-title")
        self.subtitle = label(subtitle, "caramos-cc-tile-subtitle")
        labels.pack_start(self.title, False, False, 0)
        labels.pack_start(self.subtitle, False, False, 0)
        content.pack_start(labels, True, True, 0)
        self.main.add(content)
        self.main.connect("clicked", lambda *_: on_click())
        if self.split:
            styled(self, "caramos-cc-split-tile")
            styled(self.main, "caramos-cc-split-main")
            self.pack_start(self.main, True, True, 0)
            self.arrow = styled(Gtk.Button(), "caramos-cc-split-arrow")
            self.arrow.add(icon("pan-end-symbolic", 14, "caramos-cc-arrow-icon"))
            self.arrow.set_tooltip_text(_("Open details for %s") % title)
            self.arrow.connect("clicked", lambda *_: on_details())
            self.pack_start(self.arrow, False, False, 0)
            self.target = self
        else:
            styled(self.main, "caramos-cc-simple-tile")
            self.pack_start(self.main, True, True, 0)
            self.arrow = None
            self.target = self.main
        self.set_size_request(TILE_WIDTH, TILE_HEIGHT)
        self.set_hexpand(True)
        self._update_accessible()

    def _update_accessible(self) -> None:
        self.main.get_accessible().set_name(_("%s: %s") % (self.title_text, self.subtitle.get_text()))

    def set_subtitle(self, text: str) -> None:
        if self.subtitle.get_text() != text:
            self.subtitle.set_text(text)
            self._update_accessible()

    def set_active(self, active: bool) -> None:
        set_class(self.target, "caramos-cc-tile-active", active)

    def set_loading(self, loading: bool) -> None:
        set_class(self.target, "caramos-cc-loading", loading)

    def set_enabled(self, enabled: bool) -> None:
        self.main.set_sensitive(enabled)
        if self.arrow is not None:
            self.arrow.set_sensitive(enabled)
        set_class(self.target, "caramos-cc-disabled", not enabled)

    def set_icon_name(self, name: str | list[str]) -> None:
        set_icon(self.image, name)


def list_row(lead_icon: str | None, text: str, trail_icon: str | None, on_click: Callable[[], None] | None,
             ) -> Gtk.Button:
    button = styled(Gtk.Button(), "caramos-cc-list-row")
    box = Gtk.Box(spacing=0)
    if lead_icon:
        lead = icon(lead_icon, 15, "caramos-cc-row-lead-icon")
        lead.set_size_request(22, -1)
        lead.set_margin_end(6)
        lead.set_halign(Gtk.Align.START)
        box.pack_start(lead, False, False, 0)
    box.pack_start(label(text, "caramos-cc-list-label"), True, True, 0)
    if trail_icon:
        box.pack_end(icon(trail_icon, 12, "caramos-cc-row-trail-icon"), False, False, 0)
    button.add(box)
    button.get_accessible().set_name(text)
    if on_click:
        button.connect("clicked", lambda *_: on_click())
    return button


def step_chooser(text: str, steps: tuple[int, ...], current: int, on_pick: Callable[[int], None]) -> Gtk.Box:
    """A label and one small button per step ("2%"), the current one marked: the volume step."""

    row = styled(Gtk.Box(spacing=6), "caramos-cc-step-row")
    row.pack_start(label(text, "caramos-cc-list-label"), True, True, 0)
    for step in steps:
        button = styled(Gtk.Button(label=f"{step}%"), "caramos-cc-step")
        if step == current:
            styled(button, "selected")
        button.get_accessible().set_name(f"{text}: {step}%")
        button.connect("clicked", lambda _b, s=step: on_pick(s))
        row.pack_start(button, False, False, 0)
    return row


def empty_text(text: str) -> Gtk.Label:
    widget = label(text, "caramos-cc-expand-empty", ellipsize=False)
    widget.set_line_wrap(True)
    widget.set_max_width_chars(34)
    return widget


def separator() -> Gtk.Widget:
    return styled(Gtk.Box(), "caramos-cc-expand-separator")


class InlineCard(Gtk.Box):
    """The card that opens under a row: a heading with a close button, then a body the caller fills."""

    def __init__(self, on_close: Callable[[], None]) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        styled(self, "caramos-cc-inline-card")
        head = Gtk.Box(spacing=8)
        self.head_icon = icon("emblem-system-symbolic", 16, "caramos-cc-inline-head-icon")
        self.head_title = label("", "caramos-cc-inline-title")
        close = styled(Gtk.Button(), "caramos-cc-inline-close")
        close.add(icon("window-close-symbolic", 10, "caramos-cc-inline-close-icon"))
        close.connect("clicked", lambda *_: on_close())
        self.close_button = close
        head.pack_start(self.head_icon, False, False, 0)
        head.pack_start(self.head_title, True, True, 0)
        head.pack_end(close, False, False, 0)
        self.pack_start(head, False, False, 0)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        self.pack_start(self.body, False, False, 0)
        self.kind = ""

    def set_heading(self, icon_name: str, title: str) -> None:
        set_icon(self.head_icon, icon_name)
        self.head_title.set_text(title)
        self.close_button.set_tooltip_text(_("Close %s") % title)

    def clear(self) -> None:
        for child in self.body.get_children():
            child.destroy()

    def append(self, widget: Gtk.Widget) -> None:
        self.body.pack_start(widget, False, False, 0)
        widget.show_all()

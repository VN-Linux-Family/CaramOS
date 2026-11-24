"""caramos-control-center: the CaramOS Control Center on Xfce.

  caramos-control-center --plug ID   run inside the taskbar (the CaramOS panel plugin starts this with its socket):
                                     the clock, with its calendar (clock.py), and the Control Center's button
  caramos-control-center --toggle    open or close the popup (another way in, e.g. a keyboard shortcut)

One process per session (a GApplication): a second call hands its arguments to the running one and ends. Its "osd"
action (D-Bus org.gtk.Actions, parameter "output" or "input") shows the sound level, for the sound keys
(caramos-volume).
"""

from __future__ import annotations

import logging
import os
import sys

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

APP_ID = "net.vietnamlinuxfamily.caramos.ControlCenter"
STYLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "style.css")
RESET = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reset.css")
PLUG_CSS = b"window.caramos-cc-plug { background-color: transparent; }"
OSD_FOLLOW_US = 1_000_000  # after a sound key, the level shown follows the sound server for this long

LOG = logging.getLogger("caramos-control-center")


class App(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.add_main_option("plug", 0, GLib.OptionFlags.NONE, GLib.OptionArg.INT64,
                             "Embed the panel button in this XEmbed socket", "ID")
        self.add_main_option("toggle", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE, "Open or close the popup", None)
        self.backends = None
        self.popup = None
        self.calendar = None
        self.plug = None
        self.panel_box = None
        self.clock = None
        self.indicator = None
        self.osd = None
        self.copied_files = None
        self.event_sounds = None
        self.tray_icons = None
        self._osd_kind = ""
        self._osd_until = 0
        self.provider = Gtk.CssProvider()

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        from .popup import Backends, Popup

        screen = Gdk.Screen.get_default()
        Gtk.StyleContext.add_provider_for_screen(screen, self.provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        reset = Gtk.CssProvider()
        try:
            reset.load_from_path(RESET)
        except GLib.Error as exc:
            LOG.error("style: %s", exc.message)
        Gtk.StyleContext.add_provider_for_screen(screen, reset, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION - 1)
        plug_provider = Gtk.CssProvider()
        plug_provider.load_from_data(PLUG_CSS)
        Gtk.StyleContext.add_provider_for_screen(screen, plug_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.backends = Backends()
        self.backends.appearance.connect("changed", lambda *_: self.load_style())
        self.load_style()
        self.popup = Popup(self.backends)
        self.popup.set_application(self)
        osd = Gio.SimpleAction.new("osd", GLib.VariantType.new("s"))
        osd.connect("activate", self._on_osd)
        self.add_action(osd)
        self.backends.audio.connect("changed", lambda *_: self._follow_osd())
        self.backends.night_light.apply()
        screen.connect("monitors-changed", lambda *_: self.backends.night_light.apply())
        # Files copied on the Desktop (xfdesktop) paste in Files (Nemo): backends/copied_files.py, ticket H-1204.
        try:
            from .backends.copied_files import CopiedFilesFix

            self.copied_files = CopiedFilesFix()
        except Exception:  # never at the cost of the Control Center
            LOG.exception("copied files: not watched")
        # Appearance's "Enable event sounds" loads GTK's sound module, as on Cinnamon: backends/event_sounds.py.
        try:
            from .backends.event_sounds import EventSounds

            self.event_sounds = EventSounds()
        except Exception:  # never at the cost of the Control Center
            LOG.exception("event sounds: not watched")
        # Tray icons that their programs drew in the old theme's colours follow a new one: tray_icons.py, H-1211.
        try:
            from .tray_icons import TrayIcons, widget_colour

            self.tray_icons = TrayIcons(lambda: widget_colour(self.indicator.volume if self.indicator else None))
        except Exception:  # never at the cost of the Control Center
            LOG.exception("tray icons: not watched")
        self.hold()  # stay for the session, with or without the popup open

    def load_style(self) -> None:
        from .backends.appearance import mix

        accent = self.backends.appearance.accent_color()
        try:
            with open(STYLE, encoding="utf-8") as handle:
                css = handle.read()
        except OSError as exc:
            LOG.error("style: %s", exc)
            css = ""
        header = f"@define-color cc_accent {accent};\n@define-color cc_accent_hover {mix(accent, '#ffffff', 0.15)};\n"
        try:
            self.provider.load_from_data((header + css).encode())
        except GLib.Error as exc:
            LOG.error("style: %s", exc.message)

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        options = command_line.get_options_dict().end().unpack()
        LOG.info("command line: %s", options)
        if "plug" in options:
            self.embed(int(options["plug"]))
        if options.get("toggle"):
            self._hide_calendar()
            self.popup.toggle(self.indicator.anchor() if self.indicator else None)
        return 0

    def _panel_box(self) -> Gtk.Box:
        """What the taskbar shows in the right island, between the tray and Feedback & Help: the clock, which opens
        the calendar, then the Control Center's button, as on Cinnamon."""

        from .clock import Clock
        from .indicator import Indicator

        box = Gtk.Box()
        self.clock = Clock(self.backends.panel_clock, self.on_clock)
        self.indicator = Indicator(self.backends, self.on_indicator)
        box.pack_start(self.clock, False, False, 0)
        box.pack_start(self.indicator, False, False, 0)
        return box

    def embed(self, socket_id: int) -> None:
        old, self.plug = self.plug, None
        if self.panel_box is None:
            self.panel_box = self._panel_box()
        elif self.panel_box.get_parent() is not None:
            self.panel_box.get_parent().remove(self.panel_box)  # before the old plug goes, which would take it along
        if old is not None:
            old.destroy()
        plug = Gtk.Plug.new(socket_id)
        plug.get_style_context().add_class("caramos-cc-plug")
        visual = plug.get_screen().get_rgba_visual()
        if visual is not None:
            plug.set_visual(visual)
        plug.add(self.panel_box)
        # The panel went away (it restarts, or the plugin was removed): so does this process.
        plug.connect("destroy", self._on_plug_destroyed)
        plug.connect("notify::embedded", self._on_embedded)
        plug.show_all()
        self.plug = plug
        LOG.info("embedded in socket %s: %s", socket_id, plug.get_embedded())

    def _on_embedded(self, plug: Gtk.Plug, _spec: object) -> None:
        LOG.info("embedded: %s", plug.get_embedded())
        if plug is self.plug and not plug.get_embedded():
            self.quit()

    def _on_plug_destroyed(self, plug: Gtk.Plug) -> None:
        if plug is self.plug:
            LOG.info("the panel button's socket went away")
            self.quit()

    def on_indicator(self, indicator: object, event_time: int) -> None:
        self._hide_calendar()
        self.popup.toggle(indicator.anchor(), event_time)

    def on_clock(self, clock: object, event_time: int) -> None:
        """The calendar, never together with the Control Center's popup."""

        self.popup.hide_popup()
        if self.calendar is None:
            from .calendar_popup import CalendarPopup

            self.calendar = CalendarPopup(self.backends.appearance)
            self.calendar.set_application(self)
            self.calendar.connect("show", lambda *_: clock.set_open(True))
            self.calendar.connect("hide", lambda *_: clock.set_open(False))
        self.calendar.toggle(clock.anchor(), event_time)

    def _hide_calendar(self) -> None:
        if self.calendar is not None:
            self.calendar.hide_popup()

    def _on_osd(self, _action: Gio.SimpleAction, parameter: GLib.Variant | None) -> None:
        """A sound key was pressed (it already changed the sound): show the level once the sound server has it."""

        kind = parameter.get_string() if parameter is not None else ""
        self._osd_kind = kind if kind in ("output", "input") else "output"
        self._osd_until = GLib.get_monotonic_time() + OSD_FOLLOW_US
        self.backends.audio.refresh()

    def _follow_osd(self) -> None:
        if not self._osd_kind or GLib.get_monotonic_time() > self._osd_until:
            return
        from .backends.audio import volume_icon
        from .osd import Osd

        device = self.backends.audio.state.device(self._osd_kind)
        if device is None:
            return
        if self.osd is None:
            self.osd = Osd()
        microphone = self._osd_kind == "input"
        self.osd.show_level(volume_icon(device.volume, device.muted, microphone), device.volume, device.muted,
                            self.backends.appearance.is_dark())


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="caramos-control-center: %(message)s")
    return App().run(sys.argv if argv is None else argv)

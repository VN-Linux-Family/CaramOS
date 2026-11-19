"""Dark mode and the accent colour, for Xfce.

Cinnamon switches its theme set from Cinnamon's styles.d; the Xfce edition reads the same CaramOS style (light and dark
GTK theme, icons, cursor) and writes it where Xfce keeps it: xsettings for GTK, icons and cursor, xfwm4 for the window
borders. Like Cinnamon it also tells applications through org.x.apps.portal (GTK4, Chrome, Electron), and the default
wallpaper follows the mode: Sage Mist by day, Indigo Night in dark mode.

The accent colour is the same setting on both editions (net.vietnamlinuxfamily.caramos.control-center).
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

from gi.repository import Gio, GLib, GObject

LOG = logging.getLogger("caramos-control-center")

STYLES_FILE = "/usr/share/cinnamon/styles.d/30_caramos.styles"
THEMES_DIRS = ("/usr/share/themes", os.path.expanduser("~/.themes"), os.path.expanduser("~/.local/share/themes"))
PORTAL_SCHEMA = "org.x.apps.portal"
WALLPAPERS = "/usr/share/backgrounds/CaramOS"
LIGHT_WALLPAPERS = (f"{WALLPAPERS}/03-sage-mist-2k.jpg", "/usr/share/backgrounds/caramos/default.png",
                    "/usr/share/backgrounds/caramos/03-sage-mist-2k.jpg")
DARK_WALLPAPER = f"{WALLPAPERS}/02-indigo-night-2k.jpg"

ACCENT_SCHEMA = "net.vietnamlinuxfamily.caramos.control-center"
ACCENTS = (("orange", "#f59f22"), ("blue", "#3584e4"), ("teal", "#1a9aa0"), ("green", "#2e9e57"),
           ("purple", "#8c5dd8"), ("pink", "#d9488b"), ("red", "#e0353b"), ("graphite", "#66707c"))
ACCENT_WORDS = (("aqua", "blue"), ("blue", "blue"), ("teal", "teal"), ("green", "green"), ("purple", "purple"),
                ("magenta", "purple"), ("pink", "pink"), ("red", "red"), ("grey", "graphite"), ("gray", "graphite"),
                ("orange", "orange"), ("yellow", "orange"), ("sand", "orange"), ("brown", "orange"))


@dataclass
class Variant:
    name: str
    gtk: str
    icons: str
    cursor: str


def load_styles(path: str = STYLES_FILE) -> tuple[Variant | None, Variant | None]:
    """The CaramOS light and dark variants (the default of each mode)."""

    try:
        with open(path, encoding="utf-8") as handle:
            styles = json.load(handle).get("styles", [])
    except (OSError, ValueError):
        return None, None

    def pick(entries: list) -> Variant | None:
        entries = [entry for entry in entries if isinstance(entry, dict) and entry.get("gtk")]
        entry = next((e for e in entries if str(e.get("default")) == "true"), entries[0] if entries else None)
        if entry is None:
            return None
        return Variant(name=entry.get("name", ""), gtk=entry["gtk"], icons=entry.get("icons", ""),
                       cursor=entry.get("cursor", ""))

    style = next((s for s in styles if isinstance(s, dict) and s.get("name") == "CaramOS"), styles[0] if styles else {})
    return pick(style.get("light", [])), pick(style.get("dark", []))


def theme_is_dark(gtk_theme: str, dark: Variant | None) -> bool:
    return bool(gtk_theme) and (dark is not None and gtk_theme == dark.gtk or "-dark" in gtk_theme.lower())


def has_xfwm4_theme(name: str) -> bool:
    return any(os.path.isdir(os.path.join(directory, name, "xfwm4")) for directory in THEMES_DIRS)


def wallpaper_for(current: str, dark: bool) -> str | None:
    """The default wallpaper of the other mode, or None to leave a wallpaper the user chose."""

    if dark and current in LIGHT_WALLPAPERS:
        return DARK_WALLPAPER
    if not dark and current == DARK_WALLPAPER:
        return LIGHT_WALLPAPERS[0]
    return None


def mix(color: str, other: str, amount: float) -> str:
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def accent_for_theme(gtk_theme: str) -> str:
    """The accent "Follow the theme" gives, as the Cinnamon applet decides it: CaramOS's own theme is orange, a
    colour word in the theme name gives that colour, Mint without one is green and Adwaita blue."""

    name = gtk_theme.lower()
    if name.startswith("cinnamon-delight"):
        key = "orange"
    else:
        key = next((key for word, key in ACCENT_WORDS if word in name), "")
        if not key:
            key = "green" if re.match(r"^mint-[xyl](-dark(er)?)?$", name) else "blue" if name.startswith("adwaita") \
                else "orange"
    return dict(ACCENTS)[key]


class Appearance(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self) -> None:
        super().__init__()
        self.light, self.dark = load_styles()
        try:
            import gi

            gi.require_version("Xfconf", "0")
            from gi.repository import Xfconf

            Xfconf.init()
            self.xsettings = Xfconf.Channel.get("xsettings")
            self.xfwm4 = Xfconf.Channel.get("xfwm4")
            self.desktop = Xfconf.Channel.get("xfce4-desktop")
            self.xsettings.connect("property-changed", self._on_xsettings)
        except (GLib.Error, ImportError, ValueError) as exc:
            LOG.warning("xfconf: %s", exc)
            self.xsettings = self.xfwm4 = self.desktop = None
        source = Gio.SettingsSchemaSource.get_default()
        self.portal = Gio.Settings.new(PORTAL_SCHEMA) if source and source.lookup(PORTAL_SCHEMA, True) else None
        self.accent_settings = Gio.Settings.new(ACCENT_SCHEMA) if source and source.lookup(ACCENT_SCHEMA, True) else None
        if self.accent_settings is not None:
            self.accent_settings.connect("changed", lambda *_: self.emit("changed"))

    def _on_xsettings(self, _channel: object, prop: str, _value: object) -> None:
        if prop in ("/Net/ThemeName", "/Net/IconThemeName"):
            self.emit("changed")

    @property
    def available(self) -> bool:
        return self.xsettings is not None and self.light is not None and self.dark is not None

    def gtk_theme(self) -> str:
        return self.xsettings.get_string("/Net/ThemeName", "") if self.xsettings else ""

    def is_dark(self) -> bool:
        return theme_is_dark(self.gtk_theme(), self.dark)

    def set_dark(self, dark: bool) -> None:
        variant = self.dark if dark else self.light
        if not self.available or variant is None:
            return
        if self.portal is not None:
            self.portal.set_string("color-scheme", "prefer-dark" if dark else "default")
        self.xsettings.set_string("/Net/ThemeName", variant.gtk)
        if variant.icons:
            self.xsettings.set_string("/Net/IconThemeName", variant.icons)
        if variant.cursor:
            self.xsettings.set_string("/Gtk/CursorThemeName", variant.cursor)
        if has_xfwm4_theme(variant.gtk):
            self.xfwm4.set_string("/general/theme", variant.gtk)
        self._switch_wallpaper(dark)

    def _switch_wallpaper(self, dark: bool) -> None:
        if self.desktop is None:
            return
        for prop in (self.desktop.get_properties("/backdrop") or {}):
            if prop.endswith("/last-image"):
                target = wallpaper_for(self.desktop.get_string(prop, ""), dark)
                if target and os.path.exists(target):
                    self.desktop.set_string(prop, target)

    # -- accent ----------------------------------------------------------------------------------------------------

    def accent_choice(self) -> str:
        return self.accent_settings.get_string("accent-color") if self.accent_settings else "orange"

    def accent_color(self) -> str:
        choice = self.accent_choice()
        if choice == "custom" and self.accent_settings is not None:
            custom = self.accent_settings.get_string("custom-accent")
            if len(custom) == 7 and custom.startswith("#"):
                return custom
        if choice in dict(ACCENTS):
            return dict(ACCENTS)[choice]
        return self.accent_for_mode()

    def accent_for_mode(self) -> str:
        """The accent of the CaramOS theme set in use ("Follow the theme")."""

        return accent_for_theme(self.gtk_theme())

    def set_accent(self, choice: str) -> None:
        if self.accent_settings is not None:
            self.accent_settings.set_string("accent-color", choice)

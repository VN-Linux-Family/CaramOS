"""Tray icons in the colours of a new theme, without logging out (ticket H-1211).

After the Dark mode tile (or Appearance) changed the theme or the icon theme, some icons of the tray in the right
island kept the colours of the old one until the next login: Update Manager's shield, CopyQ's scissors. This watches
the theme and the icon theme the session's programs get (XSETTINGS), and once a change has settled it runs the
Control Centers' caramos-tray-refresh with the island's text colour, the colour of this button's own icons, which the
tray also uses for symbolic icons: see that script for what it does. Lotus's V follows by itself (migration
20261124170000_tray_icons_follow_theme).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .util import spawn  # noqa: E402

LOG = logging.getLogger("caramos-control-center")

TRAY_REFRESH = "/usr/share/caramos-ota/control-center/caramos-tray-refresh"
# The tile writes the theme, the icon theme and the cursor one after the other, and GTK restyles at the next frame.
SETTLE_MS = 1500


def to_hex(red: float, green: float, blue: float) -> str:
    """#rrggbb of a GdkRGBA's channels (0.0 to 1.0)."""

    return "#" + "".join(f"{round(max(0.0, min(1.0, value)) * 255):02x}" for value in (red, green, blue))


def refresh_args(before: tuple[str, str], after: tuple[str, str], colour: str | None) -> list[str] | None:
    """caramos-tray-refresh's arguments for a change of (theme, icon theme), or None when nothing changed."""

    flags = [flag for flag, changed in (("--theme", before[0] != after[0]), ("--icons", before[1] != after[1]))
             if changed]
    if not flags:
        return None
    return (["--tray-colour", colour] if colour else []) + flags


def widget_colour(widget: Gtk.Widget | None) -> str | None:
    """The text colour of a widget as its theme draws it normally (not pointed at), #rrggbb."""

    if widget is None:
        return None
    context = widget.get_style_context()
    context.save()
    context.set_state(Gtk.StateFlags.NORMAL)
    colour = context.get_color(Gtk.StateFlags.NORMAL)
    context.restore()
    return to_hex(colour.red, colour.green, colour.blue)


class TrayIcons:
    """Runs caramos-tray-refresh after the theme or the icon theme changed."""

    def __init__(self, colour: Callable[[], str | None], run: Callable[[list[str]], bool] = spawn) -> None:
        self.colour = colour
        self.run = run
        self.settings = Gtk.Settings.get_default()
        self.seen = self.themes()
        self.timeout = 0
        for prop in ("gtk-theme-name", "gtk-icon-theme-name"):
            self.settings.connect(f"notify::{prop}", self._on_changed)

    def themes(self) -> tuple[str, str]:
        return (self.settings.props.gtk_theme_name or "", self.settings.props.gtk_icon_theme_name or "")

    def _on_changed(self, *_args: object) -> None:
        if self.timeout:
            GLib.source_remove(self.timeout)
        self.timeout = GLib.timeout_add(SETTLE_MS, self._settled)

    def _settled(self) -> bool:
        self.timeout = 0
        now = self.themes()
        args = refresh_args(self.seen, now, self.colour())
        self.seen = now
        if args:
            LOG.info("theme %s, icons %s: tray icons drawn again", *now)
            self.run([TRAY_REFRESH, *args])
        return False

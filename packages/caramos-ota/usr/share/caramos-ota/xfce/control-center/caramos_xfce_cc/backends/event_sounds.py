"""Event sounds on Xfce (ticket H-1206): Settings Manager > Appearance > Settings > Enable event sounds.

GTK applications play event sounds (a dialog's warning, a question...) only through canberra-gtk-module
(libcanberra-gtk3-module), and they load it from the Gtk/Modules XSETTING. GNOME and Cinnamon list it there while event
sounds are on; Xfce's xfsettingsd does not, so the switch in Appearance did nothing on CaramOS Xfce. This does what
they do: while "Enable event sounds" or "Enable input feedback sounds" is on, /Gtk/Modules of the xsettings channel
lists canberra-gtk-module, and running applications load it at once; while both are off, it leaves the list, and
applications started later do without it (about 0.5 MB each). Both are off by default (school labs). The sounds are
the freedesktop sound theme's (sound-theme-freedesktop).
"""

from __future__ import annotations

import logging

from gi.repository import GLib

LOG = logging.getLogger("caramos-control-center")

MODULE = "canberra-gtk-module"
MODULES = "/Gtk/Modules"
SWITCHES = ("/Net/EnableEventSounds", "/Net/EnableInputFeedbackSounds")


def modules_for(modules: str, sounds: bool) -> str:
    """The Gtk/Modules value ("a:b") with canberra-gtk-module while sounds are on, without it otherwise."""

    names = [name for name in modules.split(":") if name and name != MODULE]
    return ":".join([*names, MODULE] if sounds else names)


class EventSounds:
    def __init__(self) -> None:
        try:
            import gi

            gi.require_version("Xfconf", "0")
            from gi.repository import Xfconf

            Xfconf.init()
            self.channel = Xfconf.Channel.get("xsettings")
            self.channel.connect("property-changed", self._on_changed)
        except (GLib.Error, ImportError, ValueError) as exc:
            LOG.warning("xfconf xsettings: %s", exc)
            self.channel = None
            return
        self.apply()

    def _on_changed(self, _channel: object, prop: str, _value: object) -> None:
        if prop in SWITCHES:
            self.apply()

    def apply(self) -> None:
        sounds = any(self.channel.get_bool(switch, False) for switch in SWITCHES)
        current = self.channel.get_string(MODULES, "")
        wanted = modules_for(current, sounds)
        if wanted == current:
            return
        LOG.info("event sounds %s: Gtk/Modules %r", "on" if sounds else "off", wanted)
        if wanted:
            self.channel.set_string(MODULES, wanted)
        else:
            self.channel.reset_property(MODULES, False)

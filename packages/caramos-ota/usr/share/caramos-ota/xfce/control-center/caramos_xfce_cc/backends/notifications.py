"""Do not disturb for Xfce: xfce4-notifyd's own switch, /do-not-disturb in its xfconf channel.

While it is on, xfce4-notifyd keeps notifications in its log without showing them (ticket H-1179). The notification
plugin of the panel shows the same switch; CaramOS does not put that plugin on the panel, so the Control Center
tile is the way to reach it.
"""

from __future__ import annotations

import logging

from gi.repository import GLib, GObject

LOG = logging.getLogger("caramos-control-center")

CHANNEL = "xfce4-notifyd"
PROPERTY = "/do-not-disturb"


class Notifications(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self) -> None:
        super().__init__()
        try:
            import gi

            gi.require_version("Xfconf", "0")
            from gi.repository import Xfconf

            Xfconf.init()
            self.channel = Xfconf.Channel.get(CHANNEL)
            self.channel.connect("property-changed", self._on_changed)
        except (GLib.Error, ImportError, ValueError) as exc:
            LOG.warning("xfconf %s: %s", CHANNEL, exc)
            self.channel = None

    def _on_changed(self, _channel: object, prop: str, _value: object) -> None:
        if prop == PROPERTY:
            self.emit("changed")

    @property
    def available(self) -> bool:
        return self.channel is not None

    @property
    def quiet(self) -> bool:
        return bool(self.channel.get_bool(PROPERTY, False)) if self.channel else False

    def set_quiet(self, quiet: bool) -> None:
        if self.channel is not None:
            self.channel.set_bool(PROPERTY, quiet)

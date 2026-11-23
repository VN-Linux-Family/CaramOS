"""Whether Xfce's own clock is on the taskbar. On CaramOS Xfce the clock is the Control Center's, beside its button,
with the lunar calendar (ticket H-1178). It shows only where no panel holds Xfce's clock plugin, so that there are
never two clocks: not before migration 20261120100400 took Xfce's clock out of the right island, and not when
someone adds it again.

A panel reads which plugins it holds only when it starts. So the Control Center hides its clock as soon as Xfce's is
added, but shows it again only when it starts again (the next login, or the panel's restart): a clock taken out of
the settings while the panel runs, as the migration does, is still on the taskbar until then."""

from __future__ import annotations

import logging
import re

from gi.repository import GLib, GObject

LOG = logging.getLogger("caramos-control-center")

CHANNEL = "xfce4-panel"
CLOCK = "clock"
WATCHED = re.compile(r"/panels|/panels/panel-\d+/plugin-ids|/plugins/plugin-\d+")


def xfce_clock_shown(panels: list[int], plugin_ids: dict[int, list[int]], names: dict[int, str]) -> bool:
    """True when one of the panels in use holds Xfce's clock plugin."""

    return any(names.get(plugin) == CLOCK for panel in panels for plugin in plugin_ids.get(panel, []))


class PanelClock(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self) -> None:
        super().__init__()
        try:
            import gi

            gi.require_version("Xfconf", "0")
            from gi.repository import Xfconf

            Xfconf.init()
            self.channel = Xfconf.Channel.get(CHANNEL)
            self.channel.connect("property-changed", self._on_property_changed)
        except (GLib.Error, ImportError, ValueError) as exc:
            LOG.warning("xfconf %s: %s", CHANNEL, exc)
            self.channel = None
        self.xfce_clock = self._read()

    def _ints(self, prop: str) -> list[int]:
        values = self.channel.get_arrayv(prop) if self.channel is not None else None
        return [int(value) for value in values or [] if isinstance(value, int)]

    def _read(self) -> bool:
        if self.channel is None:
            return False
        panels = self._ints("/panels")
        plugin_ids = {panel: self._ints(f"/panels/panel-{panel}/plugin-ids") for panel in panels}
        names = {plugin: self.channel.get_string(f"/plugins/plugin-{plugin}", "")
                 for ids in plugin_ids.values() for plugin in ids}
        return xfce_clock_shown(panels, plugin_ids, names)

    def _on_property_changed(self, _channel: object, prop: str, _value: object) -> None:
        if self.xfce_clock or not WATCHED.fullmatch(prop):
            return
        if self._read():
            self.xfce_clock = True
            self.emit("changed")

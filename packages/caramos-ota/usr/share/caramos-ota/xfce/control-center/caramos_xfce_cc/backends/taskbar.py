"""Where the taskbar's middle island sits on CaramOS Xfce (ticket H-1181): in the middle of the screen, or next to
the menu, as Windows 11's taskbar alignment.

The islands are three panels of xfce4-panel (CaramOS's xfce4-panel.xml): panel-1 at the bottom left holds the menu,
panel-2 at the bottom centre the dock, panel-3 at the bottom right the tray and the clock. A panel is placed by its
middle, so a dock panel that grows as apps open could not keep its left end next to the menu. Left moves the dock
into the menu's panel, after the menu, and leaves panel-2 out of the list of panels (its settings stay, for Centre);
Centre puts the dock back. Every island is drawn by its own widgets (panel-islands.css), so the dock keeps its island
next to the menu's circle. xfce4-panel reads which plugins a panel holds only when it starts, so it restarts: the
taskbar is gone for a second or two, and this popup with it.
"""

from __future__ import annotations

import logging
import subprocess

from gi.repository import GLib, GObject

LOG = logging.getLogger("caramos-control-center")

CHANNEL = "xfce4-panel"
MENU_PANEL = 1
DOCK_PANEL = 2
MENU = "whiskermenu"
DOCK = "docklike"
CENTER = "center"
LEFT = "left"


def _ids(panel: int) -> str:
    return f"/panels/panel-{panel}/plugin-ids"


def alignment(panels: list[int], plugin_ids: dict[int, list[int]], names: dict[int, str]) -> str | None:
    """CENTER or LEFT for CaramOS's panels, None when they are laid out some other way."""

    menu_ids = plugin_ids.get(MENU_PANEL, [])
    if MENU_PANEL not in panels or not any(names.get(plugin) == MENU for plugin in menu_ids):
        return None
    docks_left = [plugin for plugin in menu_ids if names.get(plugin) == DOCK]
    docks_centre = [plugin for plugin in plugin_ids.get(DOCK_PANEL, []) if names.get(plugin) == DOCK]
    if DOCK_PANEL in panels and docks_centre and not docks_left:
        return CENTER
    if DOCK_PANEL not in panels and len(docks_left) == 1:
        return LEFT
    return None


def plan(panels: list[int], plugin_ids: dict[int, list[int]], names: dict[int, str],
         wanted: str) -> dict[str, list[int]] | None:
    """The xfce4-panel values that put the dock `wanted`: {property: list of ints}. {} when it is there already, None
    when the panels are not CaramOS's."""

    current = alignment(panels, plugin_ids, names)
    if current is None or wanted not in (CENTER, LEFT):
        return None
    if current == wanted:
        return {}
    menu_ids = plugin_ids[MENU_PANEL]
    if wanted == LEFT:
        dock = next(plugin for plugin in plugin_ids[DOCK_PANEL] if names.get(plugin) == DOCK)
        return {"/panels": [panel for panel in panels if panel != DOCK_PANEL],
                _ids(MENU_PANEL): [plugin for plugin in menu_ids if plugin != dock] + [dock]}
    dock = next(plugin for plugin in menu_ids if names.get(plugin) == DOCK)
    # panel-2 goes back to its place in the list: right after the menu's panel.
    after = panels.index(MENU_PANEL) + 1
    return {"/panels": panels[:after] + [DOCK_PANEL] + panels[after:],
            _ids(MENU_PANEL): [plugin for plugin in menu_ids if plugin != dock],
            _ids(DOCK_PANEL): [dock]}


class Taskbar(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self) -> None:
        super().__init__()
        try:
            import gi

            gi.require_version("Xfconf", "0")
            from gi.repository import Xfconf

            Xfconf.init()
            self.channel = Xfconf.Channel.get(CHANNEL)
        except (GLib.Error, ImportError, ValueError) as exc:
            LOG.warning("xfconf %s: %s", CHANNEL, exc)
            self.channel = None

    def _ints(self, prop: str) -> list[int]:
        values = self.channel.get_arrayv(prop) if self.channel is not None else None
        return [int(value) for value in values or [] if isinstance(value, int)]

    def _read(self) -> tuple[list[int], dict[int, list[int]], dict[int, str]]:
        panels = self._ints("/panels")
        plugin_ids = {panel: self._ints(_ids(panel)) for panel in (MENU_PANEL, DOCK_PANEL)}
        names = {plugin: self.channel.get_string(f"/plugins/plugin-{plugin}", "")
                 for ids in plugin_ids.values() for plugin in ids}
        return panels, plugin_ids, names

    @property
    def alignment(self) -> str | None:
        if self.channel is None:
            return None
        return alignment(*self._read())

    def set_alignment(self, wanted: str) -> bool:
        """Moves the dock and restarts xfce4-panel; False when the panels are not CaramOS's."""

        if self.channel is None:
            return False
        values = plan(*self._read(), wanted)
        if values is None:
            return False
        if not values:
            return True
        for prop, ints in values.items():
            if not self.channel.set_arrayv(prop, [GObject.Value(GObject.TYPE_INT, value) for value in ints]):
                LOG.warning("xfconf %s: could not write %s", CHANNEL, prop)
                return False
        self.emit("changed")
        try:
            subprocess.Popen(["xfce4-panel", "--restart"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            LOG.warning("xfce4-panel --restart: %s", exc)
        return True

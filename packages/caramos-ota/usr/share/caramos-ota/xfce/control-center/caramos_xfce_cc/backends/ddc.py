"""Brightness of external monitors through DDC/CI (ticket H-1183), with caramos-ddc, which the Cinnamon applet uses
too: a slider for each monitor that answers, under the laptop's; none when no monitor does."""

from __future__ import annotations

import json
import os
from collections.abc import Callable

from ..util import run_async

HELPER = "/usr/share/caramos-ota/control-center/caramos-ddc"


def displays(output: str) -> list[dict[str, object]]:
    """The monitors of `caramos-ddc list` that a slider can show: [{"bus", "name", "fraction", "max"}]."""

    try:
        found = json.loads(output or "[]")
    except ValueError:
        return []
    shown = []
    for display in found if isinstance(found, list) else []:
        if not isinstance(display, dict):
            continue
        bus, level, top = display.get("bus"), display.get("brightness"), display.get("max")
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in (bus, level, top)):
            continue
        if bus < 0 or top <= 0 or not 0 <= level <= top:
            continue
        name = display.get("name")
        shown.append({"bus": bus, "name": name if isinstance(name, str) else "", "fraction": level / top, "max": top})
    return shown


class Ddc:
    def __init__(self, helper: str = HELPER) -> None:
        self.helper = helper
        self.listing = False
        self.writes: dict[int, dict[str, object]] = {}

    @property
    def available(self) -> bool:
        return os.access(self.helper, os.X_OK)

    def busy(self, bus: int) -> bool:
        write = self.writes.get(bus)
        return bool(write and (write["busy"] or write["pending"] is not None))

    def read(self, on_done: Callable[[list[dict[str, object]]], None]) -> None:
        """Finding the monitors can take seconds the first time; on_done gets them in the main loop."""

        if self.listing or not self.available:
            return
        self.listing = True

        def got(ok: bool, out: str, _err: str) -> None:
            self.listing = False
            on_done(displays(out) if ok else [])

        run_async([self.helper, "list"], got)

    def set(self, display: dict[str, object], fraction: float) -> None:
        """DDC is slow: one write at a time for each monitor, and the last value wins."""

        bus = int(display["bus"])
        write = self.writes.setdefault(bus, {"busy": False, "pending": None})
        write["pending"] = max(0, min(100, round(fraction * 100)))
        if write["busy"]:
            return

        def send(*_result: object) -> None:
            if write["pending"] is None:
                write["busy"] = False
                return
            percent, write["pending"] = write["pending"], None
            write["busy"] = True
            run_async([self.helper, "set", str(bus), str(percent), str(display["max"])], send)

        send()

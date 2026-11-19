"""Screen brightness on laptops, through xfce4-power-manager's backlight helper (the slider of its panel plugin
does the same). Reading needs no rights; setting runs the helper with pkexec, which Xfce's polkit rule allows the
active session without a password. Desktops have no backlight: the slider stays hidden there.
"""

from __future__ import annotations

import os

from ..util import first_line, run_async

HELPER = "/usr/sbin/xfpm-power-backlight-helper"


class Brightness:
    def __init__(self) -> None:
        self.maximum = 0
        self.level = 0
        self._busy = False
        self._pending: int | None = None

    @property
    def available(self) -> bool:
        return self.maximum > 0

    def read(self, on_done) -> None:
        """Read the maximum and the level, then call on_done(fraction or None)."""

        if not os.access(HELPER, os.X_OK) or not os.path.isdir("/sys/class/backlight") \
                or not os.listdir("/sys/class/backlight"):
            on_done(None)
            return

        def got_max(ok: bool, out: str, _err: str) -> None:
            self.maximum = int(first_line(out)) if ok and first_line(out).isdigit() else 0
            if not self.maximum:
                on_done(None)
                return

            def got_level(ok2: bool, out2: str, _err2: str) -> None:
                self.level = int(first_line(out2)) if ok2 and first_line(out2).isdigit() else 0
                on_done(self.level / self.maximum)

            run_async([HELPER, "--get-brightness"], got_level)

        run_async([HELPER, "--get-max-brightness"], got_max)

    def set(self, fraction: float) -> None:
        if not self.available:
            return
        # Never all the way down to black: the user could not see the slider any more.
        self._pending = max(1, round(max(0.05, min(fraction, 1.0)) * self.maximum))
        if not self._busy:
            self._send()

    def _send(self) -> None:
        level, self._pending = self._pending, None
        self._busy = True

        def done(_ok: bool, _out: str, _err: str) -> None:
            self._busy = False
            self.level = level
            if self._pending is not None:
                self._send()

        run_async(["pkexec", HELPER, "--set-brightness", str(level)], done)

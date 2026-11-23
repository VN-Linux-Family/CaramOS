"""Driver Check's notifications show their button once, on Cinnamon and on Xfce (xfce4-notifyd)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "usr/share/caramos-ota/driver-check"))
sys.path.insert(0, str(ROOT / "usr/lib/python3/dist-packages"))

from caramos_driver_check import notify  # noqa: E402


class FakeNotify:
    def __init__(self, info):
        self.info = info

    def get_server_info(self):
        if isinstance(self.info, Exception):
            raise self.info
        return self.info


class DefaultActionTests(unittest.TestCase):
    def test_xfce4_notifyd_draws_it(self) -> None:
        self.assertTrue(notify.draws_default_action(FakeNotify((True, "Xfce Notify Daemon", "Xfce", "0.8.2", "1.2"))))

    def test_cinnamon_opens_it_on_a_click(self) -> None:
        self.assertFalse(notify.draws_default_action(FakeNotify((True, "cinnamon", "GNOME", "6.4", "1.2"))))

    def test_no_server_is_the_cinnamon_way(self) -> None:
        self.assertFalse(notify.draws_default_action(FakeNotify(RuntimeError("no server"))))


if __name__ == "__main__":
    unittest.main()

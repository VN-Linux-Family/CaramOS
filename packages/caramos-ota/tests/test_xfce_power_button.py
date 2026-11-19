"""CaramOS Xfce: the power button asks what to do, as on CaramOS Cinnamon (Xfce's own default does nothing)."""

from __future__ import annotations

import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

REPO_CONFIG = Path(__file__).resolve().parents[3] / "config"
SETTINGS = REPO_CONFIG / "includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml"


@unittest.skipUnless(REPO_CONFIG.is_dir(), "the source package has no config/")
class PowerButtonTests(unittest.TestCase):
    def test_power_button_asks(self) -> None:
        channel = ElementTree.parse(SETTINGS / "xfce4-power-manager.xml").getroot()
        self.assertEqual("xfce4-power-manager", channel.get("name"))
        button = channel.find("./property[@name='xfce4-power-manager']/property[@name='power-button-action']")
        self.assertEqual(("uint", "3"), (button.get("type"), button.get("value")))  # 3: ask (xfpm's XFPM_ASK)


if __name__ == "__main__":
    unittest.main()

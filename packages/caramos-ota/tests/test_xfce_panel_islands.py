"""CaramOS Xfce: the taskbar is the three islands of CaramOS Cinnamon, one Xfce panel each.

The look lives in CSS that the themes import (usr/share/caramos-ota/xfce), and it depends on the panel layout in the
ISO (config/includes.chroot.xfce): the three panels are clear and 48 px high, every island is drawn by the plugins in
it, and the CSS names those plugins by their ids. In the right island, the CaramOS Control Center (the
xfce4-caramos-plugin package, a socket for caramos-ota's Control Center) shows the clock, the network, the sound and
the battery, as on Cinnamon: no clock, sound or battery plugin, and nm-applet keeps running without its icon. The
clock is the Control Center's because its calendar shows lunar dates, which GTK's calendar in Xfce's clock cannot."""

from __future__ import annotations

import os
import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
XFCE_SHARE = ROOT / "usr/share/caramos-ota/xfce"
LIGHT = XFCE_SHARE / "panel-islands.css"
DARK = XFCE_SHARE / "panel-islands-dark.css"
HELP = XFCE_SHARE / "caramos-help-panel.desktop"
CONTROL_CENTER = XFCE_SHARE / "caramos-control-center"
CLOCK = XFCE_SHARE / "control-center/caramos_xfce_cc/clock.py"
DARK_THEME = ROOT / "usr/share/themes/Cinnamon-Delight-Dark/gtk-3.0/gtk.css"
XFCE = REPO / "config/includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4"
PANEL_XML = XFCE / "xfconf/xfce-perchannel-xml/xfce4-panel.xml"
DOCKLIKE_RC = XFCE / "panel/docklike.rc"
HOOK = REPO / "config/hooks/live/0170-cinnamon-task17-spices.hook.chroot"
BOOTSTRAP = REPO / "scripts/ota_bootstrap.sh"
PLUGIN = REPO / "packages/xfce4-caramos-plugin"
NM_APPLET = REPO / "config/includes.chroot.xfce/etc/dconf/db/local.d/03-caramos-xfce-nm-applet"


def rules(css: str) -> str:
    """The CSS without its leading comment and colour definitions: what light and dark must share."""
    body = css[css.index("*/") + 2:]
    return "\n".join(line for line in body.splitlines() if not line.startswith("@define-color"))


def desktop_entry(path: Path) -> dict[str, str]:
    entry = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            entry[key] = value
    return entry


class CssTests(unittest.TestCase):
    def test_dark_is_the_light_file_with_other_colours(self) -> None:
        light, dark = LIGHT.read_text(encoding="utf-8"), DARK.read_text(encoding="utf-8")
        self.assertEqual(rules(light), rules(dark))
        names = lambda css: re.findall(r"^@define-color (\w+) ", css, re.M)
        self.assertEqual(names(light), names(dark))
        self.assertNotEqual(re.findall(r"^@define-color .*$", light, re.M), re.findall(r"^@define-color .*$", dark, re.M))

    def test_the_dark_theme_imports_the_dark_islands(self) -> None:
        theme = DARK_THEME.read_text(encoding="utf-8")
        self.assertIn('@import url("file:///usr/share/caramos-ota/xfce/panel-islands-dark.css");', theme)

    def test_installed_by_the_package(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8").splitlines()
        self.assertIn("usr/share/caramos-ota/xfce usr/share/caramos-ota/", install)
        self.assertFalse([line for line in install if "battery-icon" in line], "the Control Center shows the battery")

    def test_the_islands_have_round_ends_of_their_height(self) -> None:
        css = LIGHT.read_text(encoding="utf-8")
        # 40 px islands in 48 px panels: 4 px margins, and the tray's painted end is a circle of radius 20 at 24 px.
        self.assertIn("margin: 4px;", css)
        self.assertGreaterEqual(css.count("margin: 4px 0;"), 2)
        self.assertIn("circle 20px at 20px 24px", css)
        self.assertIn("border-radius: 0 20px 20px 0;", css)


class HelpButtonTests(unittest.TestCase):
    def test_the_panel_icon_of_cinnamon(self) -> None:
        entry = desktop_entry(HELP)
        app = desktop_entry(ROOT / "usr/share/applications/caramos-help.desktop")
        self.assertEqual("dialog-question-symbolic", entry["Icon"])
        self.assertEqual("true", entry["NoDisplay"])
        for key in ("Exec", "Name", "Name[vi]", "Comment", "Comment[vi]", "StartupWMClass"):
            self.assertEqual(app[key], entry[key], key)


@unittest.skipUnless((REPO / "config").is_dir(), "the source package has no config/")
class PanelLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        root = ET.parse(PANEL_XML).getroot()
        self.panels = root.find("property[@name='panels']")
        self.plugins = {prop.get("name"): prop for prop in root.find("property[@name='plugins']")}
        self.css = LIGHT.read_text(encoding="utf-8")

    def panel(self, number: int) -> dict:
        node = self.panels.find(f"property[@name='panel-{number}']")
        values = {prop.get("name"): prop for prop in node}
        ids = [int(value.get("value")) for value in values["plugin-ids"]]
        return {"node": values, "ids": ids, "position": values["position"].get("value"),
                "style": int(values["background-style"].get("value")), "size": int(values["size"].get("value"))}

    def plugin(self, plugin_id: int) -> str:
        return self.plugins[f"plugin-{plugin_id}"].get("value")

    def setting(self, plugin_id: int, name: str) -> ET.Element | None:
        return self.plugins[f"plugin-{plugin_id}"].find(f"property[@name='{name}']")

    def test_three_clear_panels_at_the_bottom(self) -> None:
        self.assertEqual(["1", "2", "3"], [value.get("value") for value in self.panels.findall("value")])
        self.assertEqual("false", self.panels.find("property[@name='dark-mode']").get("value"))
        panels = [self.panel(number) for number in (1, 2, 3)]
        # Snap positions: 8 bottom left, 10 bottom centre, 4 bottom right.
        self.assertEqual(["p=8", "p=10", "p=4"], [panel["position"].split(";")[0] for panel in panels])
        for panel in panels:
            self.assertEqual(48, panel["size"], "the CSS draws 40 px islands 4 px inside a 48 px panel")
            rgba = panel["node"].get("background-rgba")
            self.assertEqual(1, panel["style"], "the plugins draw the islands, so the panels stay clear")
            self.assertEqual(0.0, float(rgba[3].get("value")))

    def test_left_island_is_the_menu(self) -> None:
        left = self.panel(1)
        self.assertEqual(["whiskermenu"], [self.plugin(plugin_id) for plugin_id in left["ids"]])
        self.assertIn(f"#whiskermenu-{left['ids'][0]} button", self.css)

    def test_middle_island_is_the_dock(self) -> None:
        middle = self.panel(2)
        self.assertEqual(["docklike"], [self.plugin(plugin_id) for plugin_id in middle["ids"]])
        self.assertIn("#docklike-plugin", self.css)
        pinned = re.search(r"^pinned=(.*)$", DOCKLIKE_RC.read_text(encoding="utf-8"), re.M).group(1)
        self.assertEqual(["firefox", "nemo", "caramos-app-center", "xfce-settings-manager"], pinned.rstrip(";").split(";"))

    def test_right_island_in_the_order_of_cinnamon(self) -> None:
        right = self.panel(3)
        tray, _control_center, help_id, strip = right["ids"]
        names = [self.plugin(i) for i in right["ids"]]
        # Feedback & Help ends the island; Show desktop's strip is after it, at the edge of the screen.
        self.assertEqual(["systray", "caramos-control-center", "launcher", "caramos-show-desktop"], names)
        self.assertGreater(strip, 14, "Linux Mint's own panel defaults number their plugins up to 14")
        used = [self.plugin(i) for number in (1, 2, 3) for i in self.panel(number)["ids"]]
        for gone in ("clock", "pulseaudio", "power-manager-plugin"):
            self.assertNotIn(gone, used, "the Control Center shows the clock, the sound and the battery")
        # The CSS draws the island's pieces on these plugins by id, and on the Control Center's clock and button by
        # their names: the clock has the name of Xfce's clock, so either is drawn the same.
        self.assertIn(f"#systray-{tray} > box", self.css)
        self.assertIn(f"#launcher-{help_id} button", self.css)
        self.assertIn("#clock-button {", self.css)
        self.assertIn('self.set_name("clock-button")', CLOCK.read_text(encoding="utf-8"))
        self.assertIn("#caramos-cc-indicator {", self.css)
        self.assertNotIn("#pulseaudio", self.css)
        items = [value.get("value") for value in self.setting(help_id, "items")]
        self.assertEqual(["/usr/share/caramos-ota/xfce/caramos-help-panel.desktop"], items)
        self.assertTrue((ROOT / items[0].lstrip("/")).is_file())

    def test_tray_icons_are_16_px_in_20_px_cells(self) -> None:
        tray = self.panel(3)["ids"][0]
        self.assertEqual("20", self.setting(tray, "icon-size").get("value"))
        self.assertEqual("false", self.setting(tray, "square-icons").get("value"))
        self.assertEqual("true", self.setting(tray, "single-row").get("value"))
        # The StatusNotifier icons are drawn as large as the cell: the CSS scales them to 16 px.
        self.assertIn("-gtk-icon-transform: scale(0.8);", self.css)
        self.assertEqual("16", self.panel(3)["node"]["icon-size"].get("value"), "the help icon")

    def test_every_plugin_belongs_to_a_panel(self) -> None:
        used = [plugin_id for number in (1, 2, 3) for plugin_id in self.panel(number)["ids"]]
        self.assertEqual(sorted(used), sorted(int(name.split("-")[1]) for name in self.plugins))
        self.assertEqual(len(used), len(set(used)))

    def test_no_window_manager_shadow_under_the_panels(self) -> None:
        # xfwm4 draws a dock's shadow around its whole rectangle: around the clear panels it darkened a band of the
        # wallpaper next to each island.
        xfwm4 = ET.parse(XFCE / "xfconf/xfce-perchannel-xml/xfwm4.xml").getroot()
        shadow = xfwm4.find("property[@name='general']/property[@name='show_dock_shadow']")
        self.assertEqual("false", shadow.get("value"))

    def test_the_light_theme_imports_the_islands_on_xfce(self) -> None:
        hook = HOOK.read_text(encoding="utf-8")
        self.assertIn('@import url("file:///usr/share/caramos-ota/xfce/panel-islands.css");', hook)

    def test_the_iso_installs_the_control_center_plugin(self) -> None:
        bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn("for name in xfce4-docklike-plugin xfce4-caramos-plugin; do", bootstrap)
        self.assertIn("/usr/share/xfce4/panel/plugins/caramos-control-center.desktop", bootstrap)
        self.assertFalse((REPO / "packages/xfce4-pulseaudio-plugin").exists(), "the sound button is the Control Center")

    def test_the_plugin_starts_caramos_ota_control_center(self) -> None:
        entry = desktop_entry(PLUGIN / "src/caramos-control-center.desktop")
        control_center_id = self.panel(3)["ids"][1]
        self.assertEqual(self.plugin(control_center_id), entry["X-XFCE-Module"])
        self.assertEqual("true", entry["X-XFCE-Unique"])
        self.assertEqual("false", entry["X-XFCE-Internal"], "an external plugin: the panel survives its crashes")
        source = (PLUGIN / "src/caramos-control-center.c").read_text(encoding="utf-8")
        self.assertIn(f'#define CONTROL_CENTER "/{CONTROL_CENTER.relative_to(ROOT)}"', source)
        self.assertIn('"--plug"', source)
        self.assertTrue(os.access(CONTROL_CENTER, os.X_OK))
        control = (PLUGIN / "debian/control").read_text(encoding="utf-8")
        self.assertRegex(control, r"Depends: .*caramos-ota, xfce4-panel")

    def test_nm_applet_runs_without_its_icon(self) -> None:
        # The network is in the Control Center's button; nm-applet still asks for the Wi-Fi and VPN passwords.
        text = NM_APPLET.read_text(encoding="utf-8")
        self.assertIn("[org/gnome/nm-applet]\nshow-applet=false\n", text)


if __name__ == "__main__":
    unittest.main()

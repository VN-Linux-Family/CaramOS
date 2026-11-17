"""The Control Center's accent colour (ticket H-1113): orange, a colour the user picks, or the theme's colour."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import re
import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

ROOT = Path(__file__).parents[1]
APPLET = ROOT / "usr/share/caramos-ota/applets/caramos-control-center@caramos"
APPLET_JS = APPLET / "applet.js"
STYLESHEET = APPLET / "stylesheet.css"
SCHEMA = ROOT / "usr/share/glib-2.0/schemas/net.vietnamlinuxfamily.caramos.control-center.gschema.xml"
STYLES_FILE = ROOT / "usr/share/cinnamon/styles.d/30_caramos.styles"
VI_PO = ROOT / "po/caramos-control-center/vi.po"
PICKER = ROOT / "usr/share/caramos-ota/control-center/caramos-accent-picker"

PURE_FUNCTIONS = ("appearanceVariant", "parseAppearanceStyles", "findActiveAppearance", "accentFromAppearance",
                  "accentKeyFor", "accentColor")

# Trimmed from Linux Mint 22.3's 22_mint-artwork.styles.
MINT_STYLES = {
    "styles": [
        {
            "name": "Mint-Y",
            "default": "mixed",
            "mixed": [
                {"name": "blue", "color": "#0c75de", "themes": "Mint-Y-Blue", "cinnamon": "Mint-Y-Dark-Blue",
                 "cursor": "Bibata-Modern-Classic"},
                {"name": "purple", "color": "#8c5dd8", "themes": "Mint-Y-Purple", "cinnamon": "Mint-Y-Dark-Purple",
                 "cursor": "Bibata-Modern-Classic"},
            ],
            "dark": [
                {"name": "teal", "color": "#199ca8", "themes": "Mint-Y-Dark-Teal", "icons": "Mint-Y-Teal",
                 "cursor": "Bibata-Modern-Classic"},
            ],
        },
    ]
}
CARAMOS_LIGHT = {"gtk": "Cinnamon-Delight", "icons": "Tela-circle-light", "cinnamon": "Cinnamon-Delight",
                 "cursor": "Bibata-Modern-Classic"}


def extract(source: str, pattern: str) -> str:
    match = re.search(pattern, source, re.S | re.M)
    if not match:
        raise AssertionError(f"{pattern} not found in applet.js")
    return match.group(0)


def applet_accents() -> list[tuple[str, str]]:
    block = extract(APPLET_JS.read_text(encoding="utf-8"), r"^const ACCENTS = \[.*?^\];\n")
    return re.findall(r"\{ key: '([a-z]+)', color: '(#[0-9a-f]{6})' \}", block)


class AccentLogicTests(unittest.TestCase):
    """Runs the applet's accent functions under node with CaramOS's and Mint's style data."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        source = APPLET_JS.read_text(encoding="utf-8")
        constants = [extract(source, rf"^const {name} = .*?;\n")
                     for name in ("APPEARANCE_MODES", "ACCENTS", "ACCENT_WORDS")]
        functions = [extract(source, rf"^function {name}\(.*?^\}}\n") for name in PURE_FUNCTIONS]
        cls.program = "".join(constants) + "".join(functions)

    def accent(self, choice: str, current: dict, documents: list[dict] | None = None) -> str:
        if not self.node:
            self.skipTest("node is unavailable")
        if documents is None:
            documents = [json.loads(STYLES_FILE.read_text(encoding="utf-8")), MINT_STYLES]
        script = (self.program
                  + f"const styles = parseAppearanceStyles({json.dumps(documents)}, () => true);\n"
                  + f"process.stdout.write(JSON.stringify(accentKeyFor({json.dumps(choice)}, styles, "
                  + f"{json.dumps(current)})));\n")
        return json.loads(subprocess.run([self.node, "-e", script], check=True, capture_output=True,
                                         text=True).stdout)

    def test_caramos_look_stays_orange(self) -> None:
        # CaramOS's style calls its sets "aqua" for Cinnamon Settings; the popup keeps the CaramOS orange.
        self.assertEqual("orange", self.accent("auto", CARAMOS_LIGHT))
        dark = {"gtk": "Cinnamon-Delight-Dark", "icons": "Tela-circle-dark", "cinnamon": "Cinnamon-Delight-Dark",
                "cursor": "Bibata-Modern-Classic"}
        self.assertEqual("orange", self.accent("auto", dark))

    def test_auto_follows_the_theme_colour(self) -> None:
        blue = {"gtk": "Mint-Y-Blue", "icons": "Mint-Y-Blue", "cinnamon": "Mint-Y-Dark-Blue",
                "cursor": "Bibata-Modern-Classic"}
        self.assertEqual("blue", self.accent("auto", blue))
        purple = {"gtk": "Mint-Y-Purple", "icons": "Mint-Y-Purple", "cinnamon": "Mint-Y-Dark-Purple",
                  "cursor": "Bibata-Modern-Classic"}
        self.assertEqual("purple", self.accent("auto", purple))
        teal = {"gtk": "Mint-Y-Dark-Teal", "icons": "Mint-Y-Teal", "cinnamon": "Mint-Y-Dark-Teal",
                "cursor": "Bibata-Modern-Classic"}
        self.assertEqual("teal", self.accent("auto", teal))

    def test_auto_reads_the_theme_name_of_a_custom_set(self) -> None:
        custom = {"icons": "Papirus", "cinnamon": "Adapta", "cursor": "DMZ-White"}
        self.assertEqual("red", self.accent("auto", {**custom, "gtk": "Yaru-red-dark"}))
        self.assertEqual("graphite", self.accent("auto", {**custom, "gtk": "Mint-L-Grey"}))
        self.assertEqual("green", self.accent("auto", {**custom, "gtk": "Mint-Y"}))
        self.assertEqual("blue", self.accent("auto", {**custom, "gtk": "Adwaita-dark"}))
        self.assertEqual("orange", self.accent("auto", {**custom, "gtk": "Arc"}))
        self.assertEqual("orange", self.accent("auto", {}, documents=[]))

    def test_a_chosen_colour_wins_and_unknown_choices_follow_the_theme(self) -> None:
        self.assertEqual("pink", self.accent("pink", CARAMOS_LIGHT))
        self.assertEqual("orange", self.accent("violet", CARAMOS_LIGHT))


class CustomColourTests(unittest.TestCase):
    """The stylesheet of a colour picked with the colour chooser, computed under node."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        source = APPLET_JS.read_text(encoding="utf-8")
        cls.program = "".join(extract(source, rf"^function {name}\(.*?^\}}\n")
                              for name in ("parseHexColor", "hexColor", "mixColor", "isLightColor", "customAccentClass",
                                           "customAccentCss"))

    def js(self, expression: str) -> object:
        if not self.node:
            self.skipTest("node is unavailable")
        script = self.program + f"process.stdout.write(JSON.stringify({expression}));\n"
        return json.loads(subprocess.run([self.node, "-e", script], check=True, capture_output=True, text=True).stdout)

    def test_colour_helpers(self) -> None:
        self.assertEqual([245, 159, 34], self.js("parseHexColor('#F59F22')"))
        self.assertIsNone(self.js("parseHexColor('orange')"))
        self.assertEqual("#ffffff", self.js("mixColor('#000000', '#ffffff', 1)"))
        self.assertEqual("#808080", self.js("mixColor('#000000', '#ffffff', 0.5)"))
        self.assertEqual([True, True, False, False, False], self.js(
            "['#ffeb3b', '#ffffff', '#f59f22', '#3584e4', '#000000'].map(isLightColor)"))

    def test_stylesheet_of_a_dark_and_a_light_colour(self) -> None:
        dark = self.js("customAccentCss('#123456')")
        for part in (".caramos-cc-accent-custom-123456 .caramos-cc-tile-active", ".caramos-cc-slider-item .popup-slider-menu-item",
                     ".caramos-cc-popup.caramos-cc-dark.caramos-cc-accent-custom-123456 .caramos-cc-simple-tile.caramos-cc-tile-active",
                     ".caramos-cc-inline-head-icon", ".caramos-cc-dialog-btn-primary:hover"):
            self.assertIn(part, dark)
        self.assertIn("background-color: #123456;", dark)
        self.assertIn("color: #ffffff;", dark)
        light = self.js("customAccentCss('#ffeb3b')")
        self.assertIn("color: #1f2a22;", light, "dark text on a light colour")
        self.assertNotIn("color: #ffffff;", light)
        self.assertEqual(light.count("{"), light.count("}"))
        self.assertIn(".caramos-cc-accent-custom-ffeb3b ", light, "each colour has its own class")
        self.assertEqual("caramos-cc-accent-custom-abcdef", self.js("customAccentClass('#ABCDEF')"))

    def test_the_picker(self) -> None:
        source = PICKER.read_text(encoding="utf-8")
        self.assertTrue(PICKER.stat().st_mode & 0o111, "executable")
        presets = re.search(r"^PRESETS = \((.*?)\)$", source, re.M).group(1)
        self.assertEqual([color for _name, color in applet_accents()], re.findall(r"#[0-9a-f]{6}", presets))
        for text in ('"custom-accent"', '"accent-color", "custom"', "ColorChooserDialog", "Gtk.ResponseType.OK"):
            self.assertIn(text, source)
        loader = importlib.machinery.SourceFileLoader("caramos_accent_picker_test", str(PICKER))
        module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(module)
        self.assertEqual("#ff8000", module.to_hex(1.0, 0.5019, 0.0))
        self.assertEqual("#000000", module.to_hex(-0.2, 0.0, 0.0))
        applet = APPLET_JS.read_text(encoding="utf-8")
        self.assertIn("accentPicker: ACCENT_PICKER", applet)
        self.assertIn(f"const ACCENT_PICKER = '/{PICKER.relative_to(ROOT)}';", applet)
        self.assertIn("usr/share/caramos-ota/control-center usr/share/caramos-ota/",
                      (ROOT / "debian/install").read_text(encoding="utf-8"))


class AccentAssetsTests(unittest.TestCase):
    def test_accents_are_the_schema_choices(self) -> None:
        key = ElementTree.parse(SCHEMA).getroot().find("schema/key[@name='accent-color']")
        choices = [choice.get("value") for choice in key.find("choices")]
        self.assertEqual(["auto"] + [name for name, _color in applet_accents()] + ["custom"], choices)
        self.assertEqual("'auto'", key.findtext("default"))
        custom = ElementTree.parse(SCHEMA).getroot().find("schema/key[@name='custom-accent']")
        self.assertEqual("'#f59f22'", custom.findtext("default"))
        self.assertIn("net.vietnamlinuxfamily.caramos.control-center",
                      APPLET_JS.read_text(encoding="utf-8"))
        self.assertIn("usr/share/glib-2.0/schemas/net.vietnamlinuxfamily.caramos.control-center.gschema.xml",
                      (ROOT / "debian/install").read_text(encoding="utf-8"))

    def test_each_colour_but_orange_has_its_style_block(self) -> None:
        css = STYLESHEET.read_text(encoding="utf-8")
        accents = dict(applet_accents())
        self.assertEqual("#f59f22", accents["orange"], "orange is the base style")
        self.assertIn("#f59f22", extract(css, r"^\.caramos-cc-tile-active \{.*?\}"))
        for name, color in accents.items():
            if name == "orange":
                self.assertNotIn(".caramos-cc-accent-orange", css)
                continue
            block = re.findall(rf"^[^{{}}]*\.caramos-cc-accent-{name}[^{{}}]*\{{[^}}]*\}}", css, re.M)
            selectors = " ".join(rule.split("{")[0] for rule in block)
            for part in (".caramos-cc-tile-active", ".caramos-cc-slider-item .popup-slider-menu-item", ".caramos-cc-inline-head-icon",
                         ".caramos-cc-dialog-btn-primary", ".caramos-cc-popup.caramos-cc-dark"):
                self.assertIn(part, selectors, f"{name}: {part}")
            self.assertIn(color, "".join(block), name)

    def test_the_tile_sits_next_to_power_mode_and_the_strings_are_translated(self) -> None:
        source = APPLET_JS.read_text(encoding="utf-8")
        self.assertIn("this._powerRow.add_child(this._accentTile.actor)", source)
        self.assertIn("this._applyAccentClass(actor);", extract(source, r"^    _updateThemeClasses\(\) \{.*?^    \}\n"))
        po = VI_PO.read_text(encoding="utf-8")
        for english, vietnamese in (("Accent colour", "Màu nhấn"), ("Follow the theme", "Theo chủ đề hệ thống"),
                                    ("Orange", "Cam"), ("Blue", "Xanh dương"), ("Graphite", "Xám"),
                                    ("Other colour…", "Màu khác…"), ("Custom colour", "Màu tự chọn")):
            self.assertRegex(po, rf'msgid "{re.escape(english)}"\nmsgstr "{re.escape(vietnamese)}"')


if __name__ == "__main__":
    unittest.main()

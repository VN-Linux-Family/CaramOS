"""Tests for the Control Center light/dark mode switch and the assets it relies on."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
APPLET_JS = ROOT / "usr/share/caramos-ota/applets/caramos-control-center@caramos/applet.js"
STYLESHEET = ROOT / "usr/share/caramos-ota/applets/caramos-control-center@caramos/stylesheet.css"
STYLES_FILE = ROOT / "usr/share/cinnamon/styles.d/30_caramos.styles"
DARK_THEME = ROOT / "usr/share/themes/Cinnamon-Delight-Dark"
GENERATOR = ROOT / "tools/build-delight-dark-theme.py"
DOCK_START = "/* CARAMOS_20260803120000_PANEL_DOCKS_START */"
DOCK_END = "/* CARAMOS_20260803120000_PANEL_DOCKS_END */"

PURE_FUNCTIONS = (
    "appearanceVariant",
    "parseAppearanceStyles",
    "findActiveAppearance",
    "appearanceIsDark",
    "planAppearanceSwitch",
)

# Trimmed from the styles shipped by Linux Mint 22.3 (22_mint-artwork.styles).
MINT_STYLES = {
    "styles": [
        {
            "name": "Mint-X",
            "light": [{"name": "green", "color": "#9ab87c", "themes": "Mint-X", "cursor": "Bibata-Modern-Classic"}],
        },
        {
            "name": "Mint-Y",
            "default": "mixed",
            "mixed": [
                {"name": "blue", "color": "#0c75de", "themes": "Mint-Y-Blue", "cinnamon": "Mint-Y-Dark-Blue", "cursor": "Bibata-Modern-Classic"},
                {"name": "aqua", "color": "#1f9ede", "themes": "Mint-Y-Aqua", "cinnamon": "Mint-Y-Dark-Aqua", "cursor": "Bibata-Modern-Classic", "default": "true"},
            ],
            "dark": [
                {"name": "blue", "color": "#0c75de", "themes": "Mint-Y-Dark-Blue", "icons": "Mint-Y-Blue", "cursor": "Bibata-Modern-Classic"},
                {"name": "aqua", "color": "#1f9ede", "themes": "Mint-Y-Dark-Aqua", "icons": "Mint-Y-Aqua", "cursor": "Bibata-Modern-Classic"},
            ],
            "light": [
                {"name": "aqua", "color": "#1f9ede", "themes": "Mint-Y-Aqua", "cursor": "Bibata-Modern-Classic"},
            ],
        },
    ]
}

CARAMOS_LIGHT = {"gtk": "Cinnamon-Delight", "icons": "Tela-circle-light", "cinnamon": "Cinnamon-Delight", "cursor": "Bibata-Modern-Classic"}
CARAMOS_DARK = {"gtk": "Cinnamon-Delight-Dark", "icons": "Tela-circle-dark", "cinnamon": "Cinnamon-Delight-Dark", "cursor": "Bibata-Modern-Classic"}


def extract_function(source: str, name: str) -> str:
    match = re.search(rf"^function {name}\(.*?^\}}\n", source, re.S | re.M)
    if not match:
        raise AssertionError(f"function {name} not found in applet.js")
    return match.group(0)


class AppearanceLogicTests(unittest.TestCase):
    """Runs the applet's pure appearance functions under node with realistic style data."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        source = APPLET_JS.read_text(encoding="utf-8")
        constants = [
            re.search(rf"^const {name} = .*?;\n", source, re.S | re.M).group(0)
            for name in ("APPEARANCE_MODES", "APPEARANCE_COLOR_SCHEMES")
        ]
        cls.program = "".join(constants) + "".join(extract_function(source, name) for name in PURE_FUNCTIONS)

    def run_js(self, scenario: str, documents: list[dict], installed: set[str] | None = None) -> object:
        if not self.node:
            self.skipTest("node is unavailable")
        installed_js = "null" if installed is None else json.dumps(sorted(installed))
        script = (
            self.program
            + f"const installed = {installed_js};\n"
            + "const isInstalled = v => installed === null || [v.gtk, v.icons, v.cinnamon, v.cursor].every(n => installed.includes(n));\n"
            + f"const styles = parseAppearanceStyles({json.dumps(documents)}, isInstalled);\n"
            + f"const result = (() => {{ {scenario} }})();\n"
            + "process.stdout.write(JSON.stringify(result));\n"
        )
        completed = subprocess.run([self.node, "-e", script], check=True, capture_output=True, text=True)
        return json.loads(completed.stdout)

    def caramos_styles(self) -> list[dict]:
        return [json.loads(STYLES_FILE.read_text(encoding="utf-8"))]

    def plan(self, documents, current, want_dark, installed=None):
        return self.run_js(
            f"return planAppearanceSwitch(styles, {json.dumps(current)}, {json.dumps(want_dark)});",
            documents,
            installed,
        )

    def is_dark(self, documents, current, installed=None):
        return self.run_js(f"return appearanceIsDark(styles, {json.dumps(current)});", documents, installed)

    def test_caramos_light_switches_to_the_dark_theme_set(self) -> None:
        current = {**CARAMOS_LIGHT, "colorScheme": "default"}

        self.assertFalse(self.is_dark(self.caramos_styles(), current))
        plan = self.plan(self.caramos_styles(), current, True)

        self.assertEqual("prefer-dark", plan["colorScheme"])
        self.assertEqual({"name": "aqua", **CARAMOS_DARK}, plan["variant"])

    def test_caramos_dark_switches_back_to_light(self) -> None:
        current = {**CARAMOS_DARK, "colorScheme": "prefer-dark"}

        self.assertTrue(self.is_dark(self.caramos_styles(), current))
        plan = self.plan(self.caramos_styles(), current, False)

        self.assertEqual("prefer-light", plan["colorScheme"])
        self.assertEqual({"name": "aqua", **CARAMOS_LIGHT}, plan["variant"])

    def test_mint_y_keeps_the_accent_colour_and_returns_to_light(self) -> None:
        mixed_aqua = {"gtk": "Mint-Y-Aqua", "icons": "Mint-Y-Aqua", "cinnamon": "Mint-Y-Dark-Aqua", "cursor": "Bibata-Modern-Classic", "colorScheme": "default"}

        self.assertFalse(self.is_dark([MINT_STYLES], mixed_aqua))
        to_dark = self.plan([MINT_STYLES], mixed_aqua, True)
        self.assertEqual(("prefer-dark", "Mint-Y-Dark-Aqua", "Mint-Y-Aqua"), (to_dark["colorScheme"], to_dark["variant"]["gtk"], to_dark["variant"]["icons"]))

        dark_aqua = {**{k: to_dark["variant"][k] for k in ("gtk", "icons", "cinnamon", "cursor")}, "colorScheme": "prefer-dark"}
        to_light = self.plan([MINT_STYLES], dark_aqua, False)
        self.assertEqual(("prefer-light", "Mint-Y-Aqua", "Mint-Y-Aqua"), (to_light["colorScheme"], to_light["variant"]["gtk"], to_light["variant"]["cinnamon"]))

    def test_style_without_dark_mode_only_changes_the_color_scheme(self) -> None:
        mint_x = {"gtk": "Mint-X", "icons": "Mint-X", "cinnamon": "Mint-X", "cursor": "Bibata-Modern-Classic", "colorScheme": "default"}

        plan = self.plan([MINT_STYLES], mint_x, True)

        self.assertEqual({"mode": "dark", "colorScheme": "prefer-dark", "variant": None}, plan)

    def test_custom_theme_set_is_never_replaced(self) -> None:
        custom = {"gtk": "Orchis", "icons": "Papirus", "cinnamon": "Orchis", "cursor": "Bibata-Modern-Classic", "colorScheme": "default"}
        documents = [MINT_STYLES, *self.caramos_styles()]

        self.assertEqual({"mode": "dark", "colorScheme": "prefer-dark", "variant": None}, self.plan(documents, custom, True))
        self.assertTrue(self.is_dark(documents, {**custom, "colorScheme": "prefer-dark"}))
        self.assertFalse(self.is_dark(documents, {**custom, "colorScheme": "prefer-light"}))

    def test_missing_dark_theme_falls_back_to_color_scheme_only(self) -> None:
        installed = {"Cinnamon-Delight", "Tela-circle-light", "Bibata-Modern-Classic"}
        current = {**CARAMOS_LIGHT, "colorScheme": "default"}

        plan = self.plan(self.caramos_styles(), current, True, installed)

        self.assertEqual({"mode": "dark", "colorScheme": "prefer-dark", "variant": None}, plan)

    def test_default_variant_follows_cinnamon_rules(self) -> None:
        documents = [{"styles": [{"name": "S", "dark": [
            {"name": "first", "color": "#000", "themes": "A"},
            {"name": "marked", "color": "#000", "themes": "B", "default": "true"},
        ], "light": [{"name": "other", "color": "#000", "themes": "C"}]}]}]
        current = {"gtk": "C", "icons": "C", "cinnamon": "C", "cursor": "C", "colorScheme": "prefer-light"}

        plan = self.plan(documents, current, True)

        self.assertEqual("marked", plan["variant"]["name"])

    def test_malformed_styles_are_ignored(self) -> None:
        documents = [{"styles": [None, {"name": 3}, {"name": "Broken", "dark": [{"color": "#000"}]}]}, {}]

        self.assertEqual([], self.run_js("return styles;", documents))


SAGE = "file:///usr/share/backgrounds/caramos/03-sage-mist-2k.jpg"
DEFAULT_PNG = "file:///usr/share/backgrounds/caramos/default.png"
INDIGO = "file:///usr/share/backgrounds/caramos/02-indigo-night-2k.jpg"
PAPER = "file:///usr/share/backgrounds/caramos/01-paper-dawn-2k.jpg"


class WallpaperFollowsModeTests(unittest.TestCase):
    """Sage Mist (the default) becomes Indigo Night in dark mode and comes back in light mode."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        source = APPLET_JS.read_text(encoding="utf-8")
        constants = [
            re.search(rf"^const {name} = .*?;\n", source, re.S | re.M).group(0)
            for name in ("LIGHT_DEFAULT_WALLPAPERS", "DARK_DEFAULT_WALLPAPER")
        ]
        cls.program = "".join(constants) + extract_function(source, "planWallpaperSwitch")

    def plan(self, to_dark: bool, **state) -> dict:
        if not self.node:
            self.skipTest("node is unavailable")
        state = {"uri": "", "savedUri": "", "slideshow": False, "darkAvailable": True, **state}
        script = self.program + f"process.stdout.write(JSON.stringify(planWallpaperSwitch({json.dumps(to_dark)}, {json.dumps(state)})));"
        return json.loads(subprocess.run([self.node, "-e", script], check=True, capture_output=True, text=True).stdout)

    def test_default_wallpaper_turns_indigo_and_is_remembered(self) -> None:
        self.assertEqual({"uri": INDIGO, "saved": DEFAULT_PNG}, self.plan(True, uri=DEFAULT_PNG))
        self.assertEqual({"uri": INDIGO, "saved": SAGE}, self.plan(True, uri=SAGE))

    def test_light_mode_restores_the_remembered_default(self) -> None:
        self.assertEqual({"uri": DEFAULT_PNG, "saved": None}, self.plan(False, uri=INDIGO, savedUri=DEFAULT_PNG))
        self.assertEqual({"uri": SAGE, "saved": None}, self.plan(False, uri=INDIGO, savedUri=SAGE))

    def test_user_choices_are_never_replaced(self) -> None:
        # A custom wallpaper stays in dark mode.
        self.assertEqual({"uri": None, "saved": None}, self.plan(True, uri=PAPER))
        # Indigo Night picked by the user (nothing remembered) stays in light mode.
        self.assertEqual({"uri": None, "saved": None}, self.plan(False, uri=INDIGO))
        # The user changed the wallpaper while dark: keep it and forget the remembered one.
        self.assertEqual({"uri": None, "saved": None}, self.plan(False, uri=PAPER, savedUri=DEFAULT_PNG))

    def test_slideshow_and_missing_indigo_are_left_alone(self) -> None:
        self.assertEqual({"uri": None, "saved": None}, self.plan(True, uri=DEFAULT_PNG, slideshow=True))
        self.assertEqual({"uri": None, "saved": None}, self.plan(True, uri=DEFAULT_PNG, darkAvailable=False))
        self.assertEqual({"uri": None, "saved": None}, self.plan(False, uri=INDIGO, savedUri=DEFAULT_PNG, slideshow=True))

    def test_applet_follows_mode_changes_from_any_source(self) -> None:
        source = APPLET_JS.read_text(encoding="utf-8")
        changed = re.search(r"\n    _onAppearanceChanged\(\) \{([\s\S]*?)\n    \}\n", source).group(1)
        self.assertIn("this._scheduleWallpaperForMode();", changed)
        schedule = re.search(r"\n    _scheduleWallpaperForMode\(\) \{([\s\S]*?)\n    \}\n", source).group(1)
        self.assertIn("Mainloop.timeout_add(WALLPAPER_MODE_SETTLE_MS", schedule)
        self.assertIn("dark !== this._lastAppearanceDark", schedule)
        # The login state is the baseline: no wallpaper change at startup.
        self.assertIn("this._lastAppearanceDark = appearanceIsDark(this._appearanceStyles, this._currentAppearance());", source)
        self.assertIn("if (this._wallpaperModeId) Mainloop.source_remove(this._wallpaperModeId);", source)
        self.assertIn("this._backgroundSettings = optionalSettings(BACKGROUND_SCHEMA);", source)
        self.assertIn("GLib.get_user_state_dir(), 'caramos-control-center', 'wallpaper-before-dark'", source)


class DarkModeAssetsTests(unittest.TestCase):
    def test_package_installs_dark_theme_and_style(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8").splitlines()
        self.assertIn("usr/share/themes/Cinnamon-Delight-Dark usr/share/themes/", install)
        self.assertFalse(any("Mint-Relaxed" in line for line in install))
        self.assertIn("usr/share/cinnamon/styles.d/30_caramos.styles usr/share/cinnamon/styles.d/", install)

    def test_style_pairs_the_caramos_light_and_dark_theme_sets(self) -> None:
        style = json.loads(STYLES_FILE.read_text(encoding="utf-8"))["styles"][0]
        self.assertEqual("CaramOS", style["name"])
        self.assertEqual("light", style["default"])
        for mode, expected in (("light", CARAMOS_LIGHT), ("dark", CARAMOS_DARK)):
            (variant,) = style[mode]
            self.assertEqual(expected, {key: variant[key] for key in ("gtk", "icons", "cinnamon", "cursor")})
        self.assertEqual(style["light"][0]["name"], style["dark"][0]["name"])

    def test_dark_theme_is_complete_and_keeps_its_license_notice(self) -> None:
        for part in ("index.theme", "gtk-2.0/gtkrc", "gtk-3.0/gtk.css", "gtk-4.0/gtk.css", "cinnamon/cinnamon.css"):
            self.assertTrue((DARK_THEME / part).is_file(), part)
        self.assertIn("Name=Cinnamon-Delight-Dark", (DARK_THEME / "index.theme").read_text(encoding="utf-8"))
        readme = (DARK_THEME / "README.md").read_text(encoding="utf-8")
        self.assertIn("DrMcC0y", readme)
        self.assertIn("General Public License v3.0", readme)
        self.assertIn("GPL-3.0", (DARK_THEME / "README.Mint-Relaxed.md").read_text(encoding="utf-8"))

    def test_dark_theme_has_exactly_one_dark_three_dock_block(self) -> None:
        css = (DARK_THEME / "cinnamon/cinnamon.css").read_text(encoding="utf-8")
        self.assertEqual(1, css.count(DOCK_START))
        self.assertEqual(1, css.count(DOCK_END))
        block = css[css.index(DOCK_START):css.index(DOCK_END)]
        # Same restriction as the three-dock migration: paint only, no layout or font changes.
        self.assertNotIn("border:", block)
        self.assertNotIn("font-size", block)
        self.assertNotIn("247, 243, 233", block, "light dock colour leaked into the dark theme")
        for selector in ("#panel", ".panelLeft .applet-box", ".panelCenter", ".panelRight", ".caramos-running-dot"):
            self.assertIn(selector, block)


def css_rules(css: str) -> list[tuple[list[str], str]]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [
        ([part.strip() for part in selectors.split(",")], body)
        for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css)
    ]


def dark_ink(body: str) -> bool:
    """True when a rule paints text/icons in a dark grey that disappears on a dark background."""

    match = re.search(r"(?:^|;)\s*color:\s*rgba?\((\d+),\s*(\d+),\s*(\d+)", body)
    return bool(match) and all(int(channel) < 110 for channel in match.groups())


class DarkModeStylesheetTests(unittest.TestCase):
    """Every light-mode dark ink used by the applet needs a dark-mode colour (the 1.0.16 popup had none)."""

    def test_every_dark_ink_class_has_a_dark_mode_colour(self) -> None:
        applet = APPLET_JS.read_text(encoding="utf-8")
        rules = css_rules(STYLESHEET.read_text(encoding="utf-8"))
        needs_dark: set[str] = set()
        has_dark: set[str] = set()
        for selectors, body in rules:
            for selector in selectors:
                classes = [name for name in re.findall(r"\.(caramos-cc-[a-z0-9-]+)", selector) if name != "caramos-cc-dark"]
                if not classes:
                    continue
                target = classes[-1]
                if "caramos-cc-dark" in selector:
                    if re.search(r"(?:^|;)\s*color:", body):
                        has_dark.add(target)
                elif "high-contrast" not in selector and dark_ink(body) and re.search(rf"(?<![a-z0-9-]){target}(?![a-z0-9-])", applet):
                    needs_dark.add(target)
        self.assertTrue(needs_dark, "parser found no light-mode ink rules")
        self.assertEqual(set(), needs_dark - has_dark)

    def test_active_tiles_keep_the_accent_in_dark_mode(self) -> None:
        rules = css_rules(STYLESHEET.read_text(encoding="utf-8"))
        for tile in ("caramos-cc-split-tile", "caramos-cc-simple-tile"):
            selector = f".caramos-cc-popup.caramos-cc-dark .{tile}.caramos-cc-tile-active"
            bodies = [body for selectors, body in rules if selector in selectors]
            self.assertTrue(any("#f59f22" in body for body in bodies), selector)


def load_generator():
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_delight_dark_theme_test", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DelightDarkGeneratorTests(unittest.TestCase):
    """The dark theme must look like Cinnamon-Delight, not like Mint-Relaxed's navy greys."""

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.gen = load_generator()
        except SystemExit:
            raise unittest.SkipTest("Pillow is unavailable")

    def test_greys_take_delights_hue_at_the_same_lightness(self) -> None:
        navy_bg = (0x19, 0x1D, 0x23)  # Mint-Relaxed theme_bg_color
        lightness, _chroma, hue = self.gen.rgb_to_oklch(*navy_bg)
        new_lightness, _new_chroma, new_hue = self.gen.rgb_to_oklch(*self.gen.retint(*navy_bg))
        self.assertGreater(hue, 240)
        self.assertAlmostEqual(lightness, new_lightness, delta=0.01)
        self.assertAlmostEqual(self.gen.DELIGHT_HUE, new_hue, delta=8)

    def test_accents_black_and_white_are_kept(self) -> None:
        for colour in ((0x1F, 0x9E, 0xDE), (0xE3, 0x00, 0x1B), (0x73, 0xD2, 0x16), (0, 0, 0), (255, 255, 255)):
            self.assertEqual(colour, self.gen.retint(*colour))

    def test_selectors_are_never_recoloured(self) -> None:
        css = "#panel { color: #191d23; }\n@define-color fg #dadada;\n.a #add { background: url(#abc); }"
        out = self.gen.retint_css(css)
        self.assertTrue(out.startswith("#panel { color: #"))
        self.assertNotIn("#191d23", out)
        self.assertIn(".a #add {", out)
        self.assertIn("url(#abc)", out)

    def test_generated_theme_has_no_navy_greys_left(self) -> None:
        offenders = set()
        for path in list(DARK_THEME.rglob("*.css")) + list(DARK_THEME.rglob("*.svg")) + list(DARK_THEME.rglob("gtkrc")):
            text = path.read_text(encoding="utf-8")
            for digits in re.findall(r"(?<![\w(])#([0-9a-fA-F]{6})\b", text):
                r, g, b = (int(digits[i:i + 2], 16) for i in (0, 2, 4))
                lightness, chroma, hue = self.gen.rgb_to_oklch(r, g, b)
                if 0.12 < lightness < 0.92 and 0.008 < chroma < self.gen.NEUTRAL_MAX_CHROMA and not (300 <= hue or hue <= 30):
                    offenders.add(f"{path.relative_to(DARK_THEME)}: #{digits}")
        self.assertEqual(set(), offenders)

    def test_surface_roles_keep_delights_lightness_order(self) -> None:
        css = (DARK_THEME / "gtk-3.0/gtk.css").read_text(encoding="utf-8")
        lightness = {}
        for name in self.gen.ROLE_LIGHTNESS:
            digits = re.search(rf"^@define-color {name} #([0-9a-f]{{6}});", css, re.M).group(1)
            lightness[name] = self.gen.rgb_to_oklch(*(int(digits[i:i + 2], 16) for i in (0, 2, 4)))[0]
        # Delight: file area brightest, then window bg, sidebar, toolbar band (light); mirrored in dark.
        self.assertLess(lightness["theme_bg_color"], lightness["theme_base_color_lighter"])
        self.assertLess(lightness["theme_base_color_lighter"], lightness["theme_base_color"])
        self.assertLess(lightness["theme_base_color"], lightness["dark_gray_main"])
        self.assertLess(lightness["dark_gray_main"], lightness["pathbar_color"])


class DarkDockCssSyncTests(unittest.TestCase):
    """The dark dock block is a recoloured copy of DOCK_CSS from migration 20260803120000."""

    def test_dark_dock_css_has_the_same_rules_as_the_light_one(self) -> None:
        import importlib.util

        path = ROOT / (
            "usr/lib/python3/dist-packages/caramos_ota_update/migrations/"
            "20260803120000_apply_three_dock_taskbar/migration.py"
        )
        spec = importlib.util.spec_from_file_location("three_dock_migration_for_dark_test", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        css = (DARK_THEME / "cinnamon/cinnamon.css").read_text(encoding="utf-8")
        dark_block = css[css.index(DOCK_START):css.index(DOCK_END) + len(DOCK_END)]
        self.assertIn(DOCK_START, (ROOT / "tools/delight-dark-dock.css").read_text(encoding="utf-8"))

        def shape(block: str) -> list[tuple[str, list[str]]]:
            return [
                (" ".join(selectors.split()), sorted(decl.split(":")[0].strip() for decl in body.split(";") if decl.strip()))
                for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", block, flags=re.S))
            ]

        self.assertEqual(shape(module.DOCK_CSS), shape(dark_block))


class DarkModeAppletContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APPLET_JS.read_text(encoding="utf-8")

    def method(self, name: str) -> str:
        match = re.search(rf"\n    {name}\([^)]*\) \{{([\s\S]*?)\n    \}}\n", self.source)
        self.assertIsNotNone(match, name)
        return match.group(1)

    def test_tile_toggles_and_has_icon_fallback(self) -> None:
        self.assertIn("createSimpleTile('dark-mode-symbolic', _('Chế độ tối')", self.source)
        self.assertIn("Gio.ThemedIcon.new_from_names(['dark-mode-symbolic', 'weather-clear-night-symbolic'])", self.source)
        self.assertIn("() => this._toggleDarkMode()", self.source)

    def test_switch_writes_like_cinnamon_settings(self) -> None:
        body = self.method("_toggleDarkMode")
        order = [
            "this._portalSettings.set_string('color-scheme', plan.colorScheme)",
            "this._themeSettings.set_string('gtk-theme', plan.variant.gtk)",
            "this._themeSettings.set_string('icon-theme', plan.variant.icons)",
            "this._cinnamonThemeSettings.set_string('name', plan.variant.cinnamon)",
            "this._themeSettings.set_string('cursor-theme', plan.variant.cursor)",
        ]
        positions = [body.index(statement) for statement in order]
        self.assertEqual(sorted(positions), positions)
        self.assertIn("if (plan.variant)", body)
        self.assertIn("this._appearancePending !== null) return;", body)

    def test_optional_schemas_cannot_abort_the_shell(self) -> None:
        self.assertIn("this._portalSettings = optionalSettings(PORTAL_SCHEMA)", self.source)
        self.assertIn("this._cinnamonThemeSettings = optionalSettings(CINNAMON_THEME_SCHEMA)", self.source)
        self.assertIn("source.lookup(schemaId, true)", self.source)
        self.assertNotIn("Gio.Settings.new(PORTAL_SCHEMA)", self.source)

    def test_external_changes_update_tile_and_popup(self) -> None:
        self.assertIn("connect('changed::color-scheme', () => this._onAppearanceChanged())", self.source)
        self.assertIn("connect('changed::name', () => this._onAppearanceChanged())", self.source)
        changed = self.method("_onAppearanceChanged")
        self.assertIn("this._updateThemeClasses();", changed)
        self.assertIn("this._refreshAppearanceTile();", changed)
        self.assertIn("appearanceIsDark(this._appearanceStyles, this._currentAppearance())", self.method("_updateThemeClasses"))

    def test_signals_are_disconnected_on_removal(self) -> None:
        for settings, signal in (("_portalSettings", "_portalSignalId"), ("_cinnamonThemeSettings", "_cinnamonThemeSignalId")):
            self.assertRegex(self.source, rf"if \(this\.{settings} && this\.{signal}\) \{{[\s\S]*?this\.{settings}\.disconnect\(this\.{signal}\)")


if __name__ == "__main__":
    unittest.main()

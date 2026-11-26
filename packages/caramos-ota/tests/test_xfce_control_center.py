"""The CaramOS Control Center of the Xfce edition (usr/share/caramos-ota/xfce/control-center), and the sound keys.

It is its own program, beside the Cinnamon applet, which it does not use or change: the same popup in GTK 3, from
Xfce's, NetworkManager's, BlueZ's, UPower's and PipeWire's interfaces. The tests of its logic need PyGObject; the ISO
build's test run has none and skips them.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
import unittest.mock
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
XFCE_SHARE = ROOT / "usr/share/caramos-ota/xfce"
CC_DIR = XFCE_SHARE / "control-center"
PACKAGE = CC_DIR / "caramos_xfce_cc"
LAUNCHER = XFCE_SHARE / "caramos-control-center"
VOLUME = XFCE_SHARE / "caramos-volume"
SHORTCUTS = REPO / "config/includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/" \
    "xfce4-keyboard-shortcuts.xml"
CINNAMON_APPLET = ROOT / "usr/share/caramos-ota/applets/caramos-control-center@caramos"
STYLES = ROOT / "usr/share/cinnamon/styles.d/30_caramos.styles"

HAVE_GI = importlib.util.find_spec("gi") is not None
if HAVE_GI:
    os.environ.setdefault("CARAMOS_CC_LOCALEDIR", "/nonexistent")  # the English strings, whatever the test's locale
    sys.path.insert(0, str(CC_DIR))


def code_strings(path: Path) -> list[str]:
    """The string constants of a Python file, without its docstrings."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    return [node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings]


def app_id() -> str:
    return re.search(r'^APP_ID = "([^"]+)"$', (PACKAGE / "app.py").read_text(encoding="utf-8"), re.M).group(1)


class LauncherTests(unittest.TestCase):
    def test_the_launcher_runs_the_package(self) -> None:
        self.assertTrue(os.access(LAUNCHER, os.X_OK))
        text = LAUNCHER.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("#!/usr/bin/python3"), "the system Python, which has PyGObject")
        self.assertIn(f'sys.path.insert(0, "/{CC_DIR.relative_to(ROOT)}")', text)
        self.assertIn("from caramos_xfce_cc.app import main", text)

    def test_installed_by_the_package(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8").splitlines()
        self.assertIn("usr/share/caramos-ota/xfce usr/share/caramos-ota/", install)

    def test_the_cinnamon_applet_is_left_alone(self) -> None:
        # The Xfce Control Center is a separate program: nothing of the applet is shared but its translations and
        # the accent colour setting (one schema, so both editions keep the user's choice the same way).
        sources = "\n".join(path.read_text(encoding="utf-8") for path in PACKAGE.rglob("*.py"))
        strings = [value for path in PACKAGE.rglob("*.py") for value in code_strings(path)]
        self.assertFalse([s for s in strings if "applets/caramos-control-center@caramos" in s or "org.cinnamon" in s])
        self.assertNotRegex(sources, r"require_version\(\"(Cvc|St|Cinnamon|Meta|Clutter)\"")
        self.assertIn('ACCENT_SCHEMA = "net.vietnamlinuxfamily.caramos.control-center"', sources)
        schema = (ROOT / "usr/share/glib-2.0/schemas/net.vietnamlinuxfamily.caramos.control-center.gschema.xml")
        self.assertIn('id="net.vietnamlinuxfamily.caramos.control-center"', schema.read_text(encoding="utf-8"))
        self.assertTrue((CINNAMON_APPLET / "applet.js").is_file())


class StyleTests(unittest.TestCase):
    # Classes that get their look elsewhere: the plug from app.py, the panel icons from panel-islands.css by the
    # button's name, an accent dot from its own colour.
    UNSTYLED = {"caramos-cc-plug", "caramos-cc-panel-icon", "caramos-cc-accent-dot"}

    def test_every_style_rule_has_its_widget(self) -> None:
        used = set()
        for path in PACKAGE.rglob("*.py"):
            used |= set(re.findall(r'["\'](caramos-cc-[a-z0-9-]+)["\']', path.read_text(encoding="utf-8")))
        css = "".join((PACKAGE / name).read_text(encoding="utf-8") for name in ("style.css", "reset.css"))
        css += (XFCE_SHARE / "panel-islands.css").read_text(encoding="utf-8")
        defined = set(re.findall(r"[.#](caramos-cc-[a-z0-9-]+)", css))
        self.assertEqual(set(), defined - used, "rules for widgets that are gone")
        self.assertEqual(self.UNSTYLED, used - defined, "widgets without a rule")

    def test_the_sizes_of_the_cinnamon_applet(self) -> None:
        # Measured on Cinnamon (1.3.11): a 362 px card with 12 px sides, sliders 48 px apart (40 px rows, 8 px
        # spacing), 44 px tiles, the slider's handle 13 px in the text colour, no line inside a split tile.
        css = (PACKAGE / "style.css").read_text(encoding="utf-8")
        popup = (PACKAGE / "popup.py").read_text(encoding="utf-8")
        widgets = (PACKAGE / "widgets.py").read_text(encoding="utf-8")
        self.assertIn("CARD_WIDTH = 362", popup)
        self.assertIn("padding: 10px 12px;", css)
        self.assertRegex(css, r"\.caramos-cc-slider-row \{\n  min-height: 40px;")
        self.assertIn("TILE_HEIGHT = 44", widgets)
        self.assertRegex(css, r"scale slider \{\n  min-width: 13px;\n  min-height: 13px;")
        self.assertNotRegex(css, r"split-arrow[^}]*border-left")
        self.assertIsNone(re.search(r"^\s*opacity\s*:", css, re.M), "Cinnamon draws no CSS opacity")

    def test_no_shadow_as_on_cinnamon(self) -> None:
        # Cinnamon draws no shadow around its popup or its OSD. A shadow drawn in these windows was cut off at the
        # window's edges: a grey band with square ends over the right island, a grey square around the sound level.
        css = (PACKAGE / "style.css").read_text(encoding="utf-8")
        self.assertEqual({"none"}, set(re.findall(r"box-shadow:\s*([^;]+);", css)))
        for selector in (".caramos-cc-card {", ".caramos-cc-osd {"):
            rule = css[css.index(selector):]
            self.assertNotIn("margin", rule[:rule.index("}")], selector)

    def test_dark_mode_restyles_the_card_and_the_osd(self) -> None:
        css = (PACKAGE / "style.css").read_text(encoding="utf-8")
        for selector in (".dark .caramos-cc-card {", ".dark .caramos-cc-osd {", ".dark .caramos-cc-osd-icon {"):
            self.assertIn(selector, css)
        # The accent colours come from the program, which defines them before the file.
        self.assertIn("@cc_accent", css)
        self.assertNotIn("@define-color cc_accent", css)

    @unittest.skipUnless(HAVE_GI, "PyGObject is unavailable")
    def test_the_stylesheets_parse(self) -> None:
        # In a process of its own: other tests load GTK 4, and a process has one GTK.
        check = textwrap.dedent('''\
            import sys
            import gi
            try:
                gi.require_version("Gtk", "3.0")
                from gi.repository import GLib, Gtk
            except (ImportError, ValueError):
                sys.exit(77)  # PyGObject without GTK 3, like GitHub's runners that build the ISO
            header = "@define-color cc_accent #f59f22;\\n@define-color cc_accent_hover #f7ad43;\\n"
            for path in sys.argv[1:]:
                errors = []
                provider = Gtk.CssProvider()
                provider.connect("parsing-error", lambda _p, _s, error: errors.append(error.message))
                try:
                    provider.load_from_data((header + open(path, encoding="utf-8").read()).encode())
                except GLib.Error as exc:
                    errors.append(exc.message)
                for error in errors:
                    print(path, error)
            ''')
        paths = [str(PACKAGE / "style.css"), str(PACKAGE / "reset.css"), str(XFCE_SHARE / "panel-islands.css"),
                 str(XFCE_SHARE / "panel-islands-dark.css")]
        result = subprocess.run([sys.executable, "-c", check, *paths], text=True, capture_output=True, timeout=60)
        if result.returncode == 77:
            self.skipTest("GTK 3 is unavailable")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("", result.stdout)


class SoundKeyTests(unittest.TestCase):
    """caramos-volume, with wpctl and gdbus replaced by fakes that write down how they were called."""

    def run_volume(self, *args: str, gdbus_fails: bool = False,
                   step: str | None = None) -> tuple[subprocess.CompletedProcess, list[list[str]]]:
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            calls = Path(tmp) / "calls.jsonl"
            # gsettings answers the volume step, or fails like a system without the schema.
            (bin_dir / "gsettings").write_text(
                "#!/bin/sh\n" + (f"echo '{step}'\n" if step is not None else "exit 1\n"), encoding="utf-8")
            (bin_dir / "gsettings").chmod(0o755)
            for tool in ("wpctl", "gdbus"):
                status = 1 if tool == "gdbus" and gdbus_fails else 0
                (bin_dir / tool).write_text(
                    "#!/usr/bin/env python3\nimport json, os, sys\n"
                    "open(os.environ['CALLS'], 'a').write(json.dumps([os.path.basename(sys.argv[0])] + sys.argv[1:]) + '\\n')\n"
                    f"sys.exit({status})\n", encoding="utf-8")
                (bin_dir / tool).chmod(0o755)
            env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", CALLS=str(calls))
            result = subprocess.run(["sh", str(VOLUME), *args], env=env, text=True, capture_output=True, timeout=30)
            lines = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
            return result, [json.loads(line) for line in lines]

    def osd_call(self, kind: str) -> list[str]:
        name = app_id()
        return ["gdbus", "call", "--session", "--timeout", "2", "--dest", name,
                "--object-path", "/" + name.replace(".", "/"), "--method", "org.gtk.Actions.Activate",
                "'osd'", f"[<'{kind}'>]", "{}"]

    def test_each_key(self) -> None:
        cases = {
            "up": ([["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"],
                    ["wpctl", "set-volume", "-l", "1", "@DEFAULT_AUDIO_SINK@", "5%+"]], "output"),
            "down": ([["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"]], "output"),
            "mute": ([["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"]], "output"),
            "mic-mute": ([["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"]], "input"),
        }
        for arg, (wpctl, kind) in cases.items():
            with self.subTest(arg):
                result, calls = self.run_volume(arg)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual(wpctl + [self.osd_call(kind)], calls, "the sound first, then the level shown")

    def test_the_volume_step_comes_from_the_control_center(self) -> None:
        for step, expected in (("2", "2%"), ("10", "10%"), ("abc", "5%"), ("50", "5%"), ("", "5%")):
            with self.subTest(step):
                _result, calls = self.run_volume("up", step=step)
                self.assertEqual(["wpctl", "set-volume", "-l", "1", "@DEFAULT_AUDIO_SINK@", expected + "+"], calls[1])
                _result, calls = self.run_volume("down", step=step)
                self.assertEqual(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", expected + "-"], calls[0])

    def test_works_without_the_control_center(self) -> None:
        result, calls = self.run_volume("up", gdbus_fails=True)
        self.assertEqual(0, result.returncode)
        self.assertEqual("wpctl", calls[0][0])

    def test_unknown_argument(self) -> None:
        result, calls = self.run_volume("louder")
        self.assertEqual(2, result.returncode)
        self.assertIn("usage: caramos-volume", result.stderr)
        self.assertEqual([], calls)

    def test_executable(self) -> None:
        self.assertTrue(os.access(VOLUME, os.X_OK))

    def test_the_app_has_the_osd_action(self) -> None:
        app = (PACKAGE / "app.py").read_text(encoding="utf-8")
        self.assertIn('Gio.SimpleAction.new("osd", GLib.VariantType.new("s"))', app)
        self.assertIn('kind if kind in ("output", "input")', app)

    @unittest.skipUnless(SHORTCUTS.is_file(), "the source package has no config/")
    def test_the_xfce_shortcuts_run_it(self) -> None:
        commands = ET.parse(SHORTCUTS).getroot().find("property[@name='commands']/property[@name='default']")
        values = {prop.get("name"): prop.get("value") for prop in commands}
        script = f"/{VOLUME.relative_to(ROOT)}"
        self.assertEqual(f"{script} up", values["XF86AudioRaiseVolume"])
        self.assertEqual(f"{script} down", values["XF86AudioLowerVolume"])
        self.assertEqual(f"{script} mute", values["XF86AudioMute"])
        self.assertEqual(f"{script} mic-mute", values["XF86AudioMicMute"])


@unittest.skipUnless(HAVE_GI, "PyGObject is unavailable")
class AudioTests(unittest.TestCase):
    SINKS = json.dumps([
        {"name": "alsa_output.speakers", "description": "Speakers", "mute": False,
         "volume": {"front-left": {"value": 32768}, "front-right": {"value": 32768}}},
        {"name": "bluez_output.headset", "description": "Headset", "mute": True,
         "volume": {"mono": {"value": 65536}}},
    ])
    SOURCES = json.dumps([
        {"name": "alsa_output.speakers.monitor", "description": "Monitor of Speakers", "monitor_of_sink": "1",
         "mute": False, "volume": {"mono": {"value": 65536}}},
        {"name": "alsa_input.mic", "description": "Microphone", "monitor_of_sink": "n/a", "mute": False,
         "volume": {"mono": {"value": 16384}}},
    ])

    def test_devices_and_the_default(self) -> None:
        from caramos_xfce_cc.backends.audio import AudioState, parse_devices

        outputs = parse_devices(self.SINKS, "bluez_output.headset", inputs=False)
        self.assertEqual(["Speakers", "Headset"], [device.description for device in outputs])
        self.assertAlmostEqual(0.5, outputs[0].volume)
        self.assertEqual([False, True], [device.default for device in outputs])
        self.assertTrue(outputs[1].muted)
        inputs = parse_devices(self.SOURCES, "alsa_input.mic", inputs=True)
        self.assertEqual(["alsa_input.mic"], [device.name for device in inputs], "no monitor of a sound card")
        self.assertAlmostEqual(0.25, inputs[0].volume)
        state = AudioState(available=True, outputs=outputs, inputs=inputs)
        self.assertEqual("bluez_output.headset", state.device("output").name)
        self.assertEqual(outputs[0], AudioState(outputs=[outputs[0]]).device("output"), "the first without a default")
        self.assertIsNone(AudioState().device("input"))
        self.assertEqual([], parse_devices("not json", "", inputs=False))

    def test_pactl_subscribe_ends_with_the_control_center(self) -> None:
        from caramos_xfce_cc.backends.audio import subscribe_argv

        argv = subscribe_argv(("sleep", "60"))
        if argv[0] != "setpriv":
            self.skipTest("no setpriv here")
        self.assertEqual(["setpriv", "--pdeathsig", "TERM", "--", "sleep", "60"], argv)
        # A parent that starts it and is killed, as the taskbar plugin kills the Control Center.
        parent = subprocess.Popen([sys.executable, "-c", "import subprocess, sys, time\n"
                                   "print(subprocess.Popen(sys.argv[1:]).pid, flush=True)\ntime.sleep(60)", *argv],
                                  stdout=subprocess.PIPE, text=True)
        child = int(parent.stdout.readline())
        parent.stdout.close()

        def proc(name: str) -> str:
            # "" once it is gone: FileNotFoundError, or ProcessLookupError when it exits during the read.
            try:
                return Path(f"/proc/{child}/{name}").read_text(encoding="utf-8")
            except OSError:
                return ""

        # Once it runs sleep, setpriv has asked for the signal (killed earlier, the parent would beat it to it).
        deadline = time.monotonic() + 5
        while proc("comm") != "sleep\n" and time.monotonic() < deadline:
            time.sleep(0.01)
        reached_sleep = proc("comm") == "sleep\n"
        parent.kill()
        parent.wait()
        self.assertTrue(reached_sleep, "setpriv did not start the command")

        def alive() -> bool:
            stat = proc("stat")
            return bool(stat) and stat.rsplit(")", 1)[1].split()[0] != "Z"  # a zombie has ended

        deadline = time.monotonic() + 5
        while alive() and time.monotonic() < deadline:
            time.sleep(0.05)
        if alive():
            os.kill(child, signal.SIGKILL)
            self.fail("pactl subscribe outlived the Control Center")

    def test_volume_icons(self) -> None:
        from caramos_xfce_cc.backends.audio import volume_icon

        self.assertEqual("audio-volume-muted-symbolic", volume_icon(0.8, True))
        self.assertEqual("audio-volume-muted-symbolic", volume_icon(0.0, False))
        self.assertEqual("audio-volume-low-symbolic", volume_icon(0.2, False))
        self.assertEqual("audio-volume-medium-symbolic", volume_icon(0.5, False))
        self.assertEqual("audio-volume-high-symbolic", volume_icon(1.0, False))
        self.assertEqual("microphone-sensitivity-muted-symbolic", volume_icon(0.5, True, microphone=True))
        self.assertEqual("microphone-sensitivity-high-symbolic", volume_icon(0.9, False, microphone=True))


@unittest.skipUnless(HAVE_GI, "PyGObject is unavailable")
class NetworkTests(unittest.TestCase):
    def test_states_in_words(self) -> None:
        from caramos_xfce_cc.backends.network import connectivity_text, device_state_text

        self.assertEqual("Connected", device_state_text(100))
        self.assertEqual("Getting network address", device_state_text(70))
        self.assertEqual("Unknown", device_state_text(999))
        self.assertEqual("Network sign-in required", connectivity_text(3))
        self.assertEqual("Unknown", connectivity_text(42))

    def test_wifi_signal_icons(self) -> None:
        from caramos_xfce_cc.backends.network import wifi_signal_icon

        self.assertEqual("network-wireless-signal-excellent-secure-symbolic", wifi_signal_icon(80, True))
        self.assertEqual("network-wireless-signal-good-symbolic", wifi_signal_icon(60, False))
        self.assertEqual("network-wireless-signal-ok-symbolic", wifi_signal_icon(40, False))
        self.assertEqual("network-wireless-signal-weak-symbolic", wifi_signal_icon(10, False))

    def test_vpn_profiles_from_nmcli(self) -> None:
        from caramos_xfce_cc.backends.network import parse_vpn_profiles, split_nmcli

        self.assertEqual(["a:b", "c\\d", ""], split_nmcli("a\\:b:c\\\\d:"))
        saved = "\n".join([
            "11:Office:vpn",
            "22:Home\\: WireGuard:wireguard",
            "33:Wired connection 1:802-3-ethernet",
            ":No uuid:vpn",
        ])
        active = "22:Home\\: WireGuard:wireguard\n33:Wired connection 1:802-3-ethernet"
        profiles = parse_vpn_profiles(saved, active)
        self.assertEqual([("11", "Office", "vpn", False), ("22", "Home: WireGuard", "wireguard", True)],
                         [(p.uuid, p.name, p.kind, p.active) for p in profiles])


@unittest.skipUnless(HAVE_GI, "PyGObject is unavailable")
class PowerTests(unittest.TestCase):
    def test_battery_text(self) -> None:
        from caramos_xfce_cc.backends.power import Battery, battery_text, estimate_text

        self.assertEqual("", estimate_text(30))
        self.assertEqual("45m", estimate_text(45 * 60))
        self.assertEqual("2h 5m", estimate_text(2 * 3600 + 5 * 60))
        self.assertEqual("81%", battery_text(Battery(present=True, percentage=80.6)))
        self.assertEqual("50% · 1h 0m", battery_text(Battery(present=True, percentage=50, seconds=3600)))

    def test_power_modes_in_the_order_of_cinnamon(self) -> None:
        from caramos_xfce_cc.backends.power import PROFILE_ORDER, profile_label

        self.assertEqual(("performance", "balanced", "power-saver"), PROFILE_ORDER)
        self.assertEqual("Power saver", profile_label("power-saver"))


class OsdTests(unittest.TestCase):
    """The sound level of the sound keys (ticket H-1216): a slim bar with the percentage, and every level shows."""

    def osd_function(self, name: str):
        source = (PACKAGE / "osd.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        node = next(item for item in tree.body if isinstance(item, ast.FunctionDef) and item.name == name)
        namespace: dict = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "osd.py", "exec"), namespace)  # noqa: S102
        return namespace[name]

    def test_the_percentage(self) -> None:
        percent_text = self.osd_function("percent_text")
        self.assertEqual("0%", percent_text(0.0))
        self.assertEqual("4%", percent_text(0.04))
        self.assertEqual("45%", percent_text(0.449))
        self.assertEqual("100%", percent_text(1.0))
        self.assertEqual("100%", percent_text(1.3))

    def test_a_slim_bar_icon_level_and_number(self) -> None:
        source = (PACKAGE / "osd.py").read_text(encoding="utf-8")
        self.assertIn("Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL", source)
        order = [source.index(f"self.card.pack_start(self.{name}") for name in ("image", "level", "percent")]
        self.assertEqual(sorted(order), order)
        self.assertIn('w.set_class(self.percent, "muted", muted)', source)

    def test_every_level_shows(self) -> None:
        # Cinnamon-Delight gives a level bar's block a 32 px minimum: every level under about a third looked the same.
        css = (PACKAGE / "style.css").read_text(encoding="utf-8")
        rule = css[css.index(".caramos-cc-osd-level block {"):]
        self.assertIn("min-width: 0;", rule[:rule.index("}")])
        for selector in (".caramos-cc-osd-percent {", ".caramos-cc-osd-percent.muted {",
                         ".dark .caramos-cc-osd-percent {", ".dark .caramos-cc-osd-percent.muted {"):
            self.assertIn(selector, css)


@unittest.skipUnless(HAVE_GI, "PyGObject is unavailable")
class AppearanceTests(unittest.TestCase):
    def test_the_caramos_styles_of_cinnamon(self) -> None:
        from caramos_xfce_cc.backends.appearance import load_styles, theme_is_dark

        light, dark = load_styles(str(STYLES))
        self.assertIsNotNone(light)
        self.assertIsNotNone(dark)
        self.assertFalse(theme_is_dark(light.gtk, dark))
        self.assertTrue(theme_is_dark(dark.gtk, dark))
        self.assertTrue(theme_is_dark("Mint-Y-Dark-Aqua", dark))
        self.assertEqual((None, None), load_styles("/nonexistent"))

    def test_the_wallpaper_follows_the_mode_unless_the_user_chose_one(self) -> None:
        from caramos_xfce_cc.backends.appearance import DARK_WALLPAPER, LIGHT_WALLPAPERS, wallpaper_for

        self.assertEqual(DARK_WALLPAPER, wallpaper_for(LIGHT_WALLPAPERS[0], dark=True))
        self.assertEqual(LIGHT_WALLPAPERS[0], wallpaper_for(DARK_WALLPAPER, dark=False))
        self.assertIsNone(wallpaper_for("/home/user/Pictures/cat.jpg", dark=True))
        self.assertIsNone(wallpaper_for(LIGHT_WALLPAPERS[0], dark=False))

    @unittest.skipUnless(HAVE_GI, "PyGObject is unavailable")
    def test_dark_mode_keeps_icons_the_user_picked(self) -> None:
        from caramos_xfce_cc.backends import appearance

        class Channel:
            def __init__(self, values):
                self.values = dict(values)

            def get_string(self, prop, default):
                return self.values.get(prop, default)

            def set_string(self, prop, value):
                self.values[prop] = value

        def switch(icons, dark):
            backend = appearance.Appearance.__new__(appearance.Appearance)
            backend.light, backend.dark = appearance.load_styles(str(STYLES))
            backend.portal = backend.xfwm4 = backend.desktop = None
            backend.xsettings = Channel({"/Net/ThemeName": "Cinnamon-Delight", "/Net/IconThemeName": icons,
                                         "/Gtk/CursorThemeName": backend.light.cursor})
            with unittest.mock.patch.object(appearance, "has_xfwm4_theme", return_value=False):
                backend.set_dark(dark)
            return backend.xsettings.values

        caramos = switch("Tela-circle-light", True)
        self.assertEqual(("Cinnamon-Delight-Dark", "Tela-circle-dark"),
                         (caramos["/Net/ThemeName"], caramos["/Net/IconThemeName"]))
        square = switch("Mint-Y", True)
        self.assertEqual(("Cinnamon-Delight-Dark", "Mint-Y"), (square["/Net/ThemeName"], square["/Net/IconThemeName"]))

    def test_accent_colours(self) -> None:
        from caramos_xfce_cc.backends.appearance import accent_for_theme, mix

        self.assertEqual("#f59f22", accent_for_theme("Cinnamon-Delight-Dark"))
        self.assertEqual("#2e9e57", accent_for_theme("Mint-Y"))
        self.assertEqual("#3584e4", accent_for_theme("Mint-Y-Dark-Aqua"))
        self.assertEqual("#3584e4", accent_for_theme("Adwaita"))
        self.assertEqual("#ffffff", mix("#000000", "#ffffff", 1.0))
        self.assertEqual("#808080", mix("#000000", "#ffffff", 0.5))


@unittest.skipUnless(HAVE_GI, "PyGObject is unavailable")
class NightLightTests(unittest.TestCase):
    def test_white_point(self) -> None:
        from caramos_xfce_cc.backends.nightlight import TEMPERATURE, white_point

        self.assertEqual((1.0, 1.0, 1.0), tuple(round(c, 3) for c in white_point(6500)))
        red, green, blue = white_point(TEMPERATURE)
        self.assertEqual(1.0, red)
        self.assertTrue(0.8 < green < 0.9 and 0.7 < blue < 0.8, (green, blue))


@unittest.skipUnless(HAVE_GI, "PyGObject is unavailable")
class SessionTests(unittest.TestCase):
    def test_xfce_session_commands(self) -> None:
        from caramos_xfce_cc.backends.session import ACTIONS, CONFIRM, logind_can

        self.assertEqual(("xfce4-session-logout", "--reboot"), ACTIONS["restart"])
        self.assertEqual(("xfce4-session-logout", "--halt"), ACTIONS["shutdown"])
        self.assertEqual(("restart", "shutdown", "logout"), CONFIRM, "asked once more, as Cinnamon's dialog does")
        self.assertTrue(logind_can("challenge"))
        self.assertFalse(logind_can("na"))


if __name__ == "__main__":
    unittest.main()

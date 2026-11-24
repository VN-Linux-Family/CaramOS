"""Tray icons follow the light and the dark theme without logging out (ticket H-1211).

After the Dark mode tile, the right island's tray kept icons in the old theme's colours until the next login: Update
Manager's shield (an XAppStatusIcon shown as a GtkStatusIcon), CopyQ's scissors and Flameshot's flame (pictures their
programs drew at start-up) and Lotus's V (an icon name chosen by colour). caramos-tray-refresh draws the first ones
again, run by the Control Center of each edition once a theme change has settled; migration 20261124170000 makes
Lotus's names follow the icon theme."""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "usr/share/caramos-ota/control-center/caramos-tray-refresh"
CC = ROOT / "usr/share/caramos-ota/xfce/control-center"
APPLET_JS = ROOT / "usr/share/caramos-ota/applets/caramos-control-center@caramos/applet.js"
ISLANDS = (ROOT / "usr/share/caramos-ota/xfce/panel-islands.css",
           ROOT / "usr/share/caramos-ota/xfce/panel-islands-dark.css")
HAVE_GI = importlib.util.find_spec("gi") is not None
MIGRATION_ID = "20261124170000_tray_icons_follow_theme"
migration = importlib.import_module(f"caramos_ota_update.migrations.{MIGRATION_ID}.migration")


def load_helper():  # noqa: ANN201
    loader = importlib.machinery.SourceFileLoader("caramos_tray_refresh_test", str(HELPER))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    sys.modules[loader.name] = module  # its dataclass looks itself up there
    loader.exec_module(module)
    return module


tray = load_helper()


class FakeXlib:
    def __init__(self, manager: int = 0x180000F, colours: list[int] | None = None) -> None:
        self.manager = manager
        self.colours = colours or []
        self.written: list[tuple[int, str, list[int]]] = []
        self.closed = False

    def tray_manager(self) -> int:
        return self.manager

    def cardinals(self, window: int, prop: str) -> list[int]:
        return list(self.colours)

    def set_cardinals(self, window: int, prop: str, values: list[int]) -> None:
        self.written.append((window, prop, values))

    def close(self) -> None:
        self.closed = True


class TrayColourTests(unittest.TestCase):
    def test_the_colours_xfce4_panel_gives(self) -> None:
        # What xfce4-panel's tray had written in the 1.5.0 VM, light island (#3d3833), all four colours the same.
        self.assertEqual([15677, 14392, 13107] * 4, tray.tray_colours("#3d3833"))
        self.assertEqual([60652, 59624, 61680] * 4, tray.tray_colours("#ece8f0"))
        for wrong in ("3d3833", "#3d38", "#xyzxyz", ""):
            with self.assertRaises(ValueError):
                tray.tray_colours(wrong)

    def test_written_only_when_it_changes(self) -> None:
        xlib = FakeXlib(colours=[15677, 14392, 13107] * 4)
        self.assertTrue(tray.set_tray_colour("#ece8f0", lambda: xlib))
        self.assertEqual([(0x180000F, "_NET_SYSTEM_TRAY_COLORS", [60652, 59624, 61680] * 4)], xlib.written)
        self.assertTrue(xlib.closed)
        same = FakeXlib(colours=[60652, 59624, 61680] * 4)
        self.assertFalse(tray.set_tray_colour("#ece8f0", lambda: same))
        self.assertEqual([], same.written)

    def test_no_tray_or_no_display(self) -> None:
        none = FakeXlib(manager=0)
        self.assertFalse(tray.set_tray_colour("#ece8f0", lambda: none))
        self.assertEqual([], none.written)

        def no_display() -> FakeXlib:
            raise OSError("cannot open the X display")

        self.assertFalse(tray.set_tray_colour("#ece8f0", no_display))


class RefreshTests(unittest.TestCase):
    def refresh(self, colour: str | None, theme: bool, icons: bool, colour_changed: bool = True, watcher: bool = True,
                bus: bool = True, flameshot: bool = True, stops: bool = True) -> tuple[dict, list]:
        calls: list = []

        def bus_factory() -> object:
            if not bus:
                raise RuntimeError("no session bus")
            return "bus"

        def stop(name: str, pid: int) -> tray.Restart:
            calls.append(("stop", name))
            return tray.Restart([pid], lambda: calls.append(("start", name)))

        def stop_flameshot(drawn: bool) -> tray.Restart | str:
            calls.append(("flameshot drawn by the panel", drawn))
            return "drawn by the panel" if drawn or not flameshot else stop("flameshot", 2)

        def wait(pids: list, timeout: float) -> bool:
            calls.append(("wait", pids))
            return stops

        with mock.patch.object(tray, "has_owner", lambda _bus, name: watcher and name == tray.SNI_WATCHER):
            done = tray.refresh(
                colour, theme, icons,
                set_colour=lambda c: calls.append(("colour", c)) or colour_changed,
                bus_factory=bus_factory,
                redraw=lambda b: calls.append(("redraw", b)) or True,
                copyq_stop=lambda: stop("copyq", 1),
                flameshot_stop=stop_flameshot,
                wait=wait)
        return done, calls

    def test_xfce_dark_mode(self) -> None:
        # The tile changes the theme and the icon theme; the panel draws Flameshot's icon by name (a watcher).
        done, calls = self.refresh("#ece8f0", True, True)
        self.assertEqual([("colour", "#ece8f0"), ("stop", "copyq"), ("flameshot drawn by the panel", True),
                          ("redraw", "bus"), ("wait", [1]), ("start", "copyq")], calls)
        self.assertEqual({"tray colour": True, "flameshot": "drawn by the panel", "status icons": True,
                          "copyq": "started again"}, done)

    def test_xfce_theme_with_the_same_island_colour(self) -> None:
        _done, calls = self.refresh("#3d3833", True, False, colour_changed=False)
        self.assertEqual([("colour", "#3d3833")], calls, "nothing to draw again")

    def test_cinnamon_dark_mode(self) -> None:
        # No colour given: Cinnamon sets the tray's colours itself; its tray is the old XEmbed one, no watcher. The
        # icons go away together and come back together.
        done, calls = self.refresh(None, True, True, watcher=False)
        self.assertEqual([("stop", "copyq"), ("flameshot drawn by the panel", False), ("stop", "flameshot"),
                          ("redraw", "bus"), ("wait", [1]), ("start", "copyq"), ("wait", [2]),
                          ("start", "flameshot")], calls)
        self.assertEqual("started again", done["flameshot"])

    def test_a_theme_only_draws_mints_icons_again(self) -> None:
        _done, calls = self.refresh(None, True, False, watcher=False)
        self.assertEqual([("redraw", "bus")], calls, "CopyQ and Flameshot draw from the icon theme only")

    def test_icons_only(self) -> None:
        _done, calls = self.refresh(None, False, True, watcher=False, flameshot=False)
        self.assertEqual([("stop", "copyq"), ("flameshot drawn by the panel", False), ("redraw", "bus"),
                          ("wait", [1]), ("start", "copyq")], calls)

    def test_without_a_session_bus(self) -> None:
        _done, calls = self.refresh(None, True, True, bus=False)
        self.assertNotIn(("redraw", "bus"), calls)
        self.assertIn(("start", "copyq"), calls)

    def test_a_program_that_does_not_stop_is_not_started_twice(self) -> None:
        done, calls = self.refresh(None, True, True, watcher=False, stops=False)
        self.assertNotIn(("start", "copyq"), calls)
        self.assertEqual(("did not stop", "did not stop"), (done["copyq"], done["flameshot"]))

    def test_main(self) -> None:
        with mock.patch.object(tray, "refresh", return_value={}) as refresh, \
                mock.patch.object(tray, "lock", return_value=None), mock.patch.object(tray.logging, "basicConfig"):
            self.assertEqual(0, tray.main([]))
            refresh.assert_not_called()
            self.assertEqual(0, tray.main(["--tray-colour", "#ece8f0", "--theme", "--icons"]))
            refresh.assert_called_once_with("#ece8f0", True, True)
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"), mock.patch.object(tray.logging, "basicConfig"):
            tray.main(["--tray-colour", "white", "--theme"])

    def test_the_helper_is_installed_and_runs(self) -> None:
        self.assertTrue(os.access(HELPER, os.X_OK))
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        self.assertIn("usr/share/caramos-ota/control-center usr/share/caramos-ota/", install)
        result = subprocess.run([sys.executable, str(HELPER), "--help"], capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--tray-colour", result.stdout)


class StatusIconTests(unittest.TestCase):
    def test_the_name_is_in_xapps_namespace(self) -> None:
        # libxapp: g_dbus_connection_signal_subscribe (... "NameOwnerChanged", ..., "org.x.StatusIconMonitor",
        # G_DBUS_SIGNAL_FLAGS_MATCH_ARG0_NAMESPACE ...)
        self.assertEqual("org.x.StatusIconMonitor", tray.MONITOR_NAMESPACE)
        self.assertTrue(tray.POKE_NAME.startswith(tray.MONITOR_NAMESPACE + "."))
        self.assertRegex(tray.POKE_NAME, r"^[A-Za-z_][A-Za-z0-9_-]*(\.[A-Za-z_][A-Za-z0-9_-]*)+$")

    def test_owned_and_given_up_at_once(self) -> None:
        calls = []

        def bus_call(_bus, method, args, reply):  # noqa: ANN001, ANN202
            calls.append((method, args))
            return (1,)

        with mock.patch.object(tray, "bus_call", bus_call):
            self.assertTrue(tray.redraw_status_icons("bus"))
        self.assertEqual([("RequestName", ("(su)", (tray.POKE_NAME, 4))), ("ReleaseName", ("(s)", (tray.POKE_NAME,)))],
                         calls)

    def test_not_owned_not_released(self) -> None:
        calls = []

        def bus_call(_bus, method, args, reply):  # noqa: ANN001, ANN202
            calls.append(method)
            return (3,)  # another refresh holds it

        with mock.patch.object(tray, "bus_call", bus_call):
            self.assertFalse(tray.redraw_status_icons("bus"))
        self.assertEqual(["RequestName"], calls)


class CopyQTests(unittest.TestCase):
    def stop(self, running: list, answers: dict) -> tuple[object, list, list]:
        ran: list = []
        started: list = []

        def run(*args: str) -> tuple[bool, str]:
            ran.append(args)
            return answers.get(args, (True, ""))

        result = tray.stop_copyq(lambda name: running if name == "copyq" else [], run, started.append)
        return result, ran, started

    def test_not_running_is_not_started(self) -> None:
        self.assertEqual(("not running", [], []), self.stop([], {}))

    def test_starts_again_after_saving(self) -> None:
        server = [tray.Process(10, ["/usr/bin/copyq", "-s"]), tray.Process(11, ["copyq", "--clipboard-access"])]
        result, ran, started = self.stop(server, {("config", "disable_tray"): (True, "false\n")})
        self.assertEqual([("config", "disable_tray"), ("exit",)], ran)
        self.assertEqual([10, 11], result.pids, "waits for the server and its helpers")
        self.assertEqual([], started)
        result.start()
        self.assertEqual([["copyq", "--start-server"]], started)

    def test_without_tray_icon_nothing_to_draw(self) -> None:
        result, ran, started = self.stop([tray.Process(10, ["copyq"])], {("config", "disable_tray"): (True, "true\n")})
        self.assertEqual(("no tray icon", [("config", "disable_tray")], []), (result, ran, started))

    def test_one_that_cannot_be_stopped_stays(self) -> None:
        self.assertEqual("could not stop", self.stop([tray.Process(10, ["copyq"])], {("exit",): (False, "")})[0])


class FlameshotTests(unittest.TestCase):
    def stop(self, running: list, drawn_by_panel: bool = False) -> tuple[object, list, list]:
        stopped: list = []
        started: list = []
        result = tray.stop_flameshot(
            drawn_by_panel, lambda name: running if name == "flameshot" else [],
            lambda pid: {"QT_XCB_GL_INTEGRATION": "none", "DISPLAY": ":0"}, stopped.append,
            lambda argv, env: started.append((argv, env)))
        return result, stopped, started

    def test_starts_again_as_it_was_started(self) -> None:
        result, stopped, started = self.stop([tray.Process(42, ["/usr/bin/flameshot"])])
        self.assertEqual(([42], [42]), (stopped, result.pids))
        result.start()
        self.assertEqual([(["/usr/bin/flameshot"], {"QT_XCB_GL_INTEGRATION": "none", "DISPLAY": ":0"})], started)

    def test_left_alone(self) -> None:
        self.assertEqual(("drawn by the panel", [], []), self.stop([tray.Process(42, ["flameshot"])], True))
        self.assertEqual(("not running", [], []), self.stop([]))
        self.assertEqual("busy", self.stop([tray.Process(42, ["flameshot", "gui"])])[0], "a capture")
        two = [tray.Process(42, ["flameshot"]), tray.Process(43, ["flameshot", "gui"])]
        self.assertEqual(("busy", [], []), self.stop(two))


class ProcTests(unittest.TestCase):
    def test_own_processes_and_their_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp)
            for pid, comm, cmdline, environ in ((12, "copyq", b"/usr/bin/copyq\0-s\0", b"A=1\0B=x=y\0"),
                                                (13, "flameshot", b"/usr/bin/flameshot\0", b""),
                                                (14, "copyq", b"copyq\0--clipboard-access\0monitorClipboard\0", b"")):
                (proc / str(pid)).mkdir()
                (proc / str(pid) / "comm").write_text(comm + "\n")
                (proc / str(pid) / "cmdline").write_bytes(cmdline)
                (proc / str(pid) / "environ").write_bytes(environ)
            (proc / "self").mkdir()
            found = tray.own_processes("copyq", proc, os.getuid())
            self.assertEqual([12, 14], [process.pid for process in found])
            self.assertEqual(["/usr/bin/copyq", "-s"], found[0].argv)
            self.assertEqual([], tray.own_processes("copyq", proc, os.getuid() + 1), "another user's")
            self.assertEqual({"A": "1", "B": "x=y"}, tray.read_environ(12, proc))
            self.assertIsNone(tray.read_environ(99, proc))


@unittest.skipUnless(HAVE_GI, "PyGObject is unavailable")
class XfceControlCenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(CC))
        try:
            cls.module = importlib.import_module("caramos_xfce_cc.tray_icons")
        except (ImportError, ValueError) as exc:
            # A build machine with PyGObject but without GTK 3's typelib (the ISO build's runner): tray_icons needs
            # Gtk 3.0 when it is imported.
            raise unittest.SkipTest(f"GTK 3 is unavailable: {exc}") from exc

    def test_arguments_for_a_change(self) -> None:
        args = self.module.refresh_args
        light = ("Cinnamon-Delight", "Tela-circle-light")
        dark = ("Cinnamon-Delight-Dark", "Tela-circle-dark")
        self.assertIsNone(args(light, light, "#3d3833"))
        self.assertEqual(["--tray-colour", "#ece8f0", "--theme", "--icons"], args(light, dark, "#ece8f0"))
        self.assertEqual(["--tray-colour", "#ece8f0", "--theme"], args(light, ("Cinnamon-Delight-Dark", light[1]),
                                                                       "#ece8f0"))
        self.assertEqual(["--icons"], args(light, (light[0], "Mint-Y"), None))

    def test_the_helper_runs_once_the_change_settled(self) -> None:
        module = self.module

        class Props:
            gtk_theme_name = "Cinnamon-Delight"
            gtk_icon_theme_name = "Tela-circle-light"

        ran: list = []
        icons = object.__new__(module.TrayIcons)
        icons.settings = mock.Mock(props=Props())
        icons.colour = lambda: "#ece8f0"
        icons.run = ran.append
        icons.seen = icons.themes()
        icons.timeout = 0
        with mock.patch.object(module.GLib, "timeout_add", return_value=7) as timeout_add, \
                mock.patch.object(module.GLib, "source_remove") as source_remove:
            icons._on_changed()
            icons._on_changed()  # the tile writes several keys in a row: one run
            self.assertEqual(2, timeout_add.call_count)
            source_remove.assert_called_once_with(7)
            self.assertEqual(module.SETTLE_MS, timeout_add.call_args[0][0])
        Props.gtk_theme_name, Props.gtk_icon_theme_name = "Cinnamon-Delight-Dark", "Tela-circle-dark"
        self.assertFalse(icons._settled())
        self.assertEqual([[module.TRAY_REFRESH, "--tray-colour", "#ece8f0", "--theme", "--icons"]], ran)
        self.assertFalse(icons._settled())
        self.assertEqual(1, len(ran), "nothing changed since")

    def test_colour_of_the_island(self) -> None:
        class Context:
            def __init__(self) -> None:
                self.calls: list = []

            def save(self) -> None:
                self.calls.append("save")

            def set_state(self, state: object) -> None:
                self.calls.append(state)

            def get_color(self, state: object) -> object:
                return mock.Mock(red=236 / 255, green=232 / 255, blue=240 / 255)

            def restore(self) -> None:
                self.calls.append("restore")

        context = Context()
        widget = mock.Mock(get_style_context=lambda: context)
        self.assertEqual("#ece8f0", self.module.widget_colour(widget))
        self.assertEqual(["save", self.module.Gtk.StateFlags.NORMAL, "restore"], context.calls, "not as pointed at")
        self.assertIsNone(self.module.widget_colour(None))
        self.assertEqual("#3d3833", self.module.to_hex(61 / 255, 56 / 255, 51 / 255))

    def test_the_app_starts_it(self) -> None:
        app = (CC / "caramos_xfce_cc/app.py").read_text(encoding="utf-8")
        self.assertIn("from .tray_icons import TrayIcons, widget_colour", app)
        self.assertIn("TrayIcons(lambda: widget_colour(self.indicator.volume if self.indicator else None))", app)
        self.assertRegex(app, r"try:\n\s+from \.tray_icons import[\s\S]*?except Exception:")
        self.assertEqual("/usr/share/caramos-ota/control-center/caramos-tray-refresh", self.module.TRAY_REFRESH)


class IslandColourTests(unittest.TestCase):
    def test_the_button_and_the_tray_have_the_same_colour(self) -> None:
        # The Xfce Control Center gives the tray the colour of its own icons: in both island stylesheets that is the
        # colour xfce4-panel's tray takes for itself when it starts (#systray-3 *).
        for path in ISLANDS:
            css = path.read_text(encoding="utf-8")
            tray_rule = re.search(r"#systray-3 \*\s*\{([^}]*)\}", css).group(1)
            button_rule = re.search(r"#caramos-cc-indicator image,\s*#caramos-cc-indicator label\s*\{([^}]*)\}",
                                    css).group(1)
            self.assertIn("color: @caramos_island_fg;", tray_rule, path.name)
            self.assertIn("color: @caramos_island_fg;", button_rule, path.name)


class CinnamonAppletTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APPLET_JS.read_text(encoding="utf-8")

    def method(self, name: str) -> str:
        match = re.search(rf"\n    {name}\([^)]*\) \{{([\s\S]*?)\n    \}}\n", self.source)
        self.assertIsNotNone(match, name)
        return match.group(1)

    def test_arguments_for_a_change(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        function = re.search(r"^function trayRefreshArgs\(.*?^\}\n", self.source, re.S | re.M).group(0)
        light = {"gtk": "Cinnamon-Delight", "icons": "Tela-circle-light", "cinnamon": "Cinnamon-Delight",
                 "cursor": "Bibata-Modern-Classic", "colorScheme": "prefer-light"}
        dark = {"gtk": "Cinnamon-Delight-Dark", "icons": "Tela-circle-dark", "cinnamon": "Cinnamon-Delight-Dark",
                "cursor": "Bibata-Modern-Classic", "colorScheme": "prefer-dark"}
        cases = [(light, dark), (light, light), (light, {**light, "cursor": "DMZ-White", "colorScheme": "default"}),
                 (light, {**light, "cinnamon": "Mint-Y-Dark"}), (light, {**light, "icons": "Mint-Y"}), (None, light)]
        script = function + (f"process.stdout.write(JSON.stringify({json.dumps(cases)}"
                             ".map(c => trayRefreshArgs(c[0], c[1]))));")
        result = json.loads(subprocess.run([node, "-e", script], check=True, capture_output=True, text=True).stdout)
        self.assertEqual([["--theme", "--icons"], None, None, ["--theme"], ["--icons"], None], result)

    def test_runs_once_the_keys_settled(self) -> None:
        schedule = self.method("_scheduleWallpaperForMode")
        self.assertIn("Mainloop.timeout_add(WALLPAPER_MODE_SETTLE_MS", schedule)
        self.assertIn("this._refreshTrayIcons();", schedule)
        refresh = self.method("_refreshTrayIcons")
        self.assertIn("trayRefreshArgs(this._trayAppearance, current)", refresh)
        self.assertIn("spawnArgvAsync([TRAY_REFRESH].concat(args))", refresh)
        # The login state is the baseline: nothing runs at startup.
        self.assertIn("this._trayAppearance = this._currentAppearance();", self.source)
        self.assertIn(f"const TRAY_REFRESH = '/{HELPER.relative_to(ROOT)}';", self.source)


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.icons = Path(self.tmp.name) / "icons"
        self.lotus = self.icons / "hicolor/scalable/status"
        self.lotus.mkdir(parents=True)
        for base in migration.BASES:
            (self.lotus / f"{base}-default.svg").write_text("white")
            (self.lotus / f"{base}-default-black.svg").write_text("black")
        for theme in ("Tela-circle-dark", "Tela-circle-light"):
            (self.icons / theme / "symbolic/status").mkdir(parents=True)
            (self.icons / theme / "index.theme").write_text("[Icon Theme]\n")
        patches = [mock.patch.object(migration, "ICONS", self.icons),
                   mock.patch.object(migration, "LOTUS_ICONS", self.lotus)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def run_migration(self, dry_run: bool = False) -> list:
        context = MigrationContext(dry_run=dry_run)
        with mock.patch.object(context, "run_command") as run_command, mock.patch.object(context, "log"), \
                mock.patch.object(migration.shutil, "which", return_value="/usr/bin/gtk-update-icon-cache"):
            migration.run(context)
        return [call.args[0] for call in run_command.call_args_list]

    def picture(self, theme: str, name: str) -> str:
        return (self.icons / theme / "symbolic/status" / f"{name}.svg").read_text()

    def test_each_theme_gets_the_other_name_in_its_colour(self) -> None:
        caches = self.run_migration()
        for base in migration.BASES:
            self.assertEqual("white", self.picture("Tela-circle-dark", f"{base}-default-black"))
            self.assertEqual("black", self.picture("Tela-circle-light", f"{base}-default"))
            link = self.icons / "Tela-circle-dark/symbolic/status" / f"{base}-default-black.svg"
            self.assertTrue(link.is_symlink(), "Lotus's own pictures, which follow its updates")
            self.assertEqual(self.lotus / f"{base}-default.svg", Path(os.readlink(link)))
        self.assertFalse((self.icons / "Tela-circle-dark/symbolic/status/fcitx-lotus-default.svg").exists(),
                         "each theme keeps Lotus's own name for its colour")
        self.assertEqual([["gtk-update-icon-cache", "--force", "--quiet", str(self.icons / theme)]
                          for theme in ("Tela-circle-dark", "Tela-circle-light")], caches)
        self.assertEqual([], self.run_migration(), "once")

    def test_dry_run_changes_nothing(self) -> None:
        self.run_migration(dry_run=True)
        self.assertEqual([], list((self.icons / "Tela-circle-dark/symbolic/status").iterdir()))

    def test_a_name_the_theme_has_stays(self) -> None:
        own = self.icons / "Tela-circle-dark/symbolic/status/fcitx-lotus-default-black.svg"
        own.write_text("Tela's own")
        self.run_migration()
        self.assertEqual("Tela's own", own.read_text())
        other = self.icons / "Tela-circle-dark/symbolic/status/fcitx-lotus-off-default-black.svg"
        self.assertTrue(other.is_symlink())

    def test_without_lotus_or_the_themes(self) -> None:
        for path in self.lotus.iterdir():
            path.unlink()
        self.assertEqual([], self.run_migration())
        self.assertEqual({}, migration.planned_links())

    def test_a_theme_folder_that_is_a_link_is_left_alone(self) -> None:
        # Writing through it would change the shared Tela-circle folder for both variants.
        folder = self.icons / "Tela-circle-light/symbolic/status"
        folder.rmdir()
        shared = Path(self.tmp.name) / "shared"
        shared.mkdir()
        folder.symlink_to(shared)
        self.run_migration()
        self.assertEqual([], list(shared.iterdir()))
        self.assertTrue((self.icons / "Tela-circle-dark/symbolic/status/fcitx-lotus-default-black.svg").is_symlink())

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual("anytime", manifest["unattended"], "links and an icon cache: nothing changes on screen then")
        self.assertNotIn("desktops", manifest, "Lotus and the Tela icons are the same on both editions")
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        for key in ("title", "summary", "size", "title_en", "summary_en", "size_en"):
            self.assertTrue(manifest[key], key)


if __name__ == "__main__":
    unittest.main()

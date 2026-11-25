"""Show desktop at the very end of the taskbar (tickets H-1189 and H-1192), migration 20261124100000: Cinnamon's
corner bar after Feedback & Help, and on Xfce the strip of the CaramOS panel plugin caramos-show-desktop (package
xfce4-caramos-plugin) after the right island. Feedback & Help stays the last icon; the strip shows nothing until the
pointer is on it."""

from __future__ import annotations

import importlib
import json
import re
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest import mock

from caramos_ota_update import deferred
from caramos_ota_update.context import MigrationContext, MigrationContextError

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
DATA = ROOT / "tests/data"
PANEL_1_5_0 = (DATA / "xfce4-panel.xml-1.5.0").read_text(encoding="utf-8")
ISO_PANEL = REPO / "config/includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml"
ISO_CINNAMON = REPO / "config/includes.chroot/etc/dconf/db/local.d/01-caramos-task17-panel"
HOOK = REPO / "config/hooks/live/0170-cinnamon-task17-spices.hook.chroot"
PLUGIN = REPO / "packages/xfce4-caramos-plugin"
HELP_CSS = ROOT / "usr/share/caramos-ota/applets/caramos-help@caramos/stylesheet.css"
ISLANDS = ROOT / "usr/share/caramos-ota/xfce/panel-islands.css"
migration = importlib.import_module("caramos_ota_update.migrations.20261124100000_show_desktop_button.migration")

# Cinnamon's enabled-applets on CaramOS 1.5.0: a fresh install, and the ISO's defaults.
INSTALLED = ("['panel1:left:0:Cinnamenu@json:0', 'panel1:center:0:grouped-window-list@cinnamon.org:1', "
             "'panel1:right:0:systray@cinnamon.org:2', 'panel1:right:3:notifications@cinnamon.org:5', "
             "'panel1:right:5:calendar@cinnamon.org:7', 'panel1:right:6:caramos-control-center@caramos:0', "
             "'panel1:right:7:caramos-help@caramos:8']")
ISO_1_5_0 = ("['panel1:left:0:Cinnamenu@json:0', 'panel1:center:0:grouped-window-list@cinnamon.org:1', "
             "'panel1:right:0:systray@cinnamon.org:2', 'panel1:right:1:notifications@cinnamon.org:5', "
             "'panel1:right:2:calendar@cinnamon.org:7', 'panel1:right:3:caramos-control-center@caramos:0', "
             "'panel1:right:4:caramos-help@caramos:8']")


def without_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->\n?", "", text, flags=re.S)


class CinnamonPanelTests(unittest.TestCase):
    def test_the_corner_bar_follows_feedback_and_help(self) -> None:
        new = migration.add_corner_bar(INSTALLED)
        self.assertEqual(INSTALLED[:-1] + ", 'panel1:right:8:cornerbar@cinnamon.org:9']", new)
        self.assertEqual(new, migration.add_corner_bar(new), "once")
        self.assertEqual(new, migration.add_corner_bar("@as " + new))

    def test_a_panel_that_shows_the_desktop_already(self) -> None:
        for applet in ("cornerbar@cinnamon.org", "show-desktop@cinnamon.org"):
            value = INSTALLED[:-1] + f", 'panel1:left:1:{applet}:12']"
            self.assertEqual(value, migration.add_corner_bar(value))

    def test_no_feedback_and_help_no_corner_bar(self) -> None:
        value = INSTALLED.replace(", 'panel1:right:7:caramos-help@caramos:8'", "")
        self.assertEqual(value, migration.add_corner_bar(value), "a panel changed by hand stays")

    def test_values_it_does_not_know(self) -> None:
        for value in ("", "nonsense", "['a:b']", "[1, 2]"):
            self.assertIsNone(migration.add_corner_bar(value), value)

    def test_the_defaults_file(self) -> None:
        source = f"[org/cinnamon]\nenabled-applets={ISO_1_5_0}\npanels-height=['1:48']\n"
        new = migration.updated_defaults(source)
        self.assertIn("'panel1:right:4:caramos-help@caramos:8', 'panel1:right:5:cornerbar@cinnamon.org:9']", new)
        self.assertTrue(new.endswith("panels-height=['1:48']\n"))
        self.assertIsNone(migration.updated_defaults(f"[org/other]\nenabled-applets={ISO_1_5_0}\n"))

    @unittest.skipUnless(ISO_CINNAMON.is_file(), "the source package has no config/")
    def test_new_installs_have_it(self) -> None:
        expected = migration.add_corner_bar(ISO_1_5_0)
        for path in (ISO_CINNAMON, HOOK):
            with self.subTest(path=path.name):
                self.assertIn(f"enabled-applets={expected}\n", path.read_text(encoding="utf-8"))

    def test_logged_in_users_get_the_new_stylesheet_first(self) -> None:
        calls: list[str] = []

        def gsettings(_user, _env, args):  # noqa: ANN001
            calls.append(args[0])
            return subprocess.CompletedProcess(args, 0, INSTALLED + "\n" if args[0] == "get" else "", "")

        with mock.patch.object(migration.help_applet, "_user_environment",
                               return_value={"DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}), \
                mock.patch.object(migration.help_applet, "_gsettings", side_effect=gsettings), \
                mock.patch.object(migration, "_reload_help",
                                  side_effect=lambda *_a: calls.append("reload") or
                                  subprocess.CompletedProcess([], 0, "", "")) as reload, \
                mock.patch.object(MigrationContext, "log"):
            migration.cinnamon_user(MigrationContext(), "minh", 1000, Path("/home/minh"))
            self.assertEqual(["get", "reload", "set"], calls)
            calls.clear()
            reload.reset_mock()
            migration.cinnamon_user(MigrationContext(unattended=True), "minh", 1000, Path("/home/minh"))
            reload.assert_not_called()
            self.assertEqual(["get", "set"], calls)

    def test_nothing_to_set_when_it_is_there(self) -> None:
        done = migration.add_corner_bar(INSTALLED)
        with mock.patch.object(migration.help_applet, "_user_environment", return_value={}), \
                mock.patch.object(migration.help_applet, "_gsettings",
                                  return_value=subprocess.CompletedProcess([], 0, done + "\n", "")) as gsettings, \
                mock.patch.object(MigrationContext, "log"):
            migration.cinnamon_user(MigrationContext(), "minh", 1000, Path("/home/minh"))
        self.assertEqual(1, gsettings.call_count)

    def test_dconf_update_waits_for_people_logged_in(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "01-caramos-task17-panel"
            path.write_text(f"[org/cinnamon]\nenabled-applets={ISO_1_5_0}\n", encoding="utf-8")
            flag = Path(tmp) / "dconf-update-pending"
            context = MigrationContext()
            with mock.patch.object(context, "run_command") as run, mock.patch.object(context, "log"), \
                    mock.patch.object(migration.help_applet, "_session_bus",
                                      return_value=Path(tmp) / "bus"), \
                    mock.patch.object(deferred, "DCONF_FLAG", flag):
                (Path(tmp) / "bus").touch()
                migration.cinnamon_defaults(context, [("minh", 1000, Path(tmp))], path)
                run.assert_not_called()
                self.assertIn("cornerbar@cinnamon.org", path.read_text(encoding="utf-8"))
                self.assertTrue(flag.is_file(), "dconf update at the next start, before anyone logs in")
                flag.unlink()
                (Path(tmp) / "bus").unlink()
                path.write_text(f"[org/cinnamon]\nenabled-applets={ISO_1_5_0}\n", encoding="utf-8")
                migration.cinnamon_defaults(context, [("minh", 1000, Path(tmp))], path)
                run.assert_called_once_with(["dconf", "update"], allow_fail=True)

    def test_the_strip_keeps_the_room_of_the_island_end(self) -> None:
        css = HELP_CSS.read_text(encoding="utf-8")
        # Feedback & Help keeps 8 px at the island's round end while it is last; the corner bar takes those 8 px.
        self.assertIn("margin-right: 8px;", css)
        rule = re.search(r"\.panel-bottom \.panelRight > \.applet-cornerbar-box \{(.*?)\}", css, re.S).group(1)
        self.assertIn("padding: 12px 4px 12px 3px;", rule)  # 3 + 1 + 4 = 8 px
        line = re.search(r"> \.applet-cornerbar \{(.*?)\}", css, re.S).group(1)
        self.assertIn("width: 1px;", line)
        self.assertIn("background-color: transparent;", line, "nothing shows until the pointer is on it")
        self.assertIn(":hover > .applet-cornerbar", css)


class XfcePanelTests(unittest.TestCase):
    LAYOUT = ([1, 2, 3], {1: [1], 2: [2], 3: [3, 5, 6]},
              {1: "whiskermenu", 2: "docklike", 3: "systray", 5: "caramos-control-center", 6: "launcher",
               7: "separator", 14: "separator"})

    def test_plan(self) -> None:
        self.assertEqual((3, 15, True), migration.plan(*self.LAYOUT))
        panels, ids, names = self.LAYOUT
        self.assertEqual((3, 15, False), migration.plan(panels, ids, {**names, 15: "caramos-show-desktop"}),
                         "a strip the system defaults name already")
        self.assertIsNone(migration.plan(panels, {**ids, 3: [3, 5, 6, 9]}, {**names, 9: "showdesktop"}))
        self.assertIsNone(migration.plan(panels, {**ids, 3: [3, 6]}, names), "no Control Center")
        self.assertEqual((3, 21, True), migration.plan(panels, {**ids, 2: [2, 20]}, {**names, 20: "clock"}))

    def test_1_5_0_becomes_the_iso_of_now(self) -> None:
        new = migration.defaults_with_strip(PANEL_1_5_0)
        self.assertTrue(new)
        self.assertEqual("", migration.defaults_with_strip(new), "once")
        self.assertEqual(PANEL_1_5_0.count("<!--"), new.count("<!--"), "the comments stay")
        root = ElementTree.fromstring(new)
        ids = [int(value.get("value")) for value in
               root.find("property[@name='panels']/property[@name='panel-3']/property[@name='plugin-ids']")]
        self.assertEqual([3, 5, 6, 15], ids)
        if ISO_PANEL.is_file():  # the source package has no config/
            self.assertEqual(without_comments(ISO_PANEL.read_text(encoding="utf-8")), without_comments(new))

    def test_files_not_as_expected_stay(self) -> None:
        self.assertEqual("", migration.defaults_with_strip("not xml"))
        self.assertEqual("", migration.defaults_with_strip('<channel name="xfce4-panel" version="1.0"/>'))
        no_cc = PANEL_1_5_0.replace('value="caramos-control-center"', 'value="clock"')
        self.assertEqual("", migration.defaults_with_strip(no_cc))

    def run_user(self, listing: str, arrays: dict[str, list[int]]) -> list[list[str]]:
        commands: list[list[str]] = []

        def run_command(argv, allow_fail=False, env=None):  # noqa: ANN001
            commands.append(list(argv))
            if argv[-2:] == ["-l", "-v"]:
                return subprocess.CompletedProcess(argv, 0, listing, "")
            if argv[-2] == "-p" and argv[-1] in arrays:
                values = arrays[argv[-1]]
                text = f"Value is an array with {len(values)} items:\n\n" + "".join(f"{v}\n" for v in values)
                return subprocess.CompletedProcess(argv, 0, text, "")
            return subprocess.CompletedProcess(argv, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".config/xfce4/xfconf/xfce-perchannel-xml").mkdir(parents=True)
            (home / ".config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml").touch()
            context = MigrationContext()
            with mock.patch.object(context, "run_command", side_effect=run_command), \
                    mock.patch.object(context, "log"):
                migration.xfce_user(context, "minh", 1000, home, runtime_root=Path(tmp) / "run")
        return [command for command in commands if "-s" in command]

    def test_a_user_gets_the_strip(self) -> None:
        listing = "\n".join(f"/plugins/plugin-{n}   {name}" for n, name in self.LAYOUT[2].items())
        arrays = {"/panels": [1, 2, 3], "/panels/panel-1/plugin-ids": [1], "/panels/panel-2/plugin-ids": [2],
                  "/panels/panel-3/plugin-ids": [3, 5, 6]}
        writes = self.run_user(listing, arrays)
        self.assertEqual(["/plugins/plugin-15", "-n", "-t", "string", "-s", "caramos-show-desktop"], writes[0][-6:])
        self.assertIn("dbus-run-session", writes[0], "nobody logged in: a D-Bus session of its own")
        self.assertEqual(["/panels/panel-3/plugin-ids", "--force-array", "-t", "int", "-s", "3", "-t", "int", "-s",
                          "5", "-t", "int", "-s", "6", "-t", "int", "-s", "15"], writes[1][-18:])

    def test_a_user_with_xfces_show_desktop_keeps_it(self) -> None:
        listing = "\n".join(f"/plugins/plugin-{n}   {name}" for n, name in {**self.LAYOUT[2], 9: "showdesktop"}.items())
        arrays = {"/panels": [1, 2, 3], "/panels/panel-1/plugin-ids": [1], "/panels/panel-2/plugin-ids": [2],
                  "/panels/panel-3/plugin-ids": [3, 5, 6, 9]}
        self.assertEqual([], self.run_user(listing, arrays))

    def test_the_plugin_comes_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugin = Path(tmp) / "caramos-show-desktop.desktop"
            context = MigrationContext()
            with mock.patch.object(context, "log"), \
                    mock.patch.object(migration.clipboard, "_installed", return_value=False):
                self.assertFalse(migration._plugin_ready(context, plugin), "no CaramOS taskbar")
            with mock.patch.object(context, "log"), \
                    mock.patch.object(migration.clipboard, "_installed", return_value=True), \
                    mock.patch.object(context, "apt_install", side_effect=lambda *_a, **_k: plugin.touch()) as apt:
                self.assertTrue(migration._plugin_ready(context, plugin))
                apt.assert_called_once_with(["xfce4-caramos-plugin"], recommends=False)
                self.assertTrue(migration._plugin_ready(context, plugin))
                apt.assert_called_once()
            plugin.unlink()
            with mock.patch.object(context, "log"), \
                    mock.patch.object(migration.clipboard, "_installed", return_value=True), \
                    mock.patch.object(context, "apt_install", side_effect=MigrationContextError("offline")):
                self.assertFalse(migration._plugin_ready(context, plugin), "an older plugin: the panel stays")

    def test_run_by_desktop(self) -> None:
        with mock.patch.object(migration, "run_cinnamon") as cinnamon, \
                mock.patch.object(migration, "run_xfce") as xfce, mock.patch.object(MigrationContext, "log"):
            migration.run(MigrationContext(), "cinnamon")
            migration.run(MigrationContext(), "xfce")
            migration.run(MigrationContext(), "other")
        cinnamon.assert_called_once()
        xfce.assert_called_once()


class StripPluginTests(unittest.TestCase):
    @unittest.skipUnless(PLUGIN.is_dir(), "the source package has no packages/xfce4-caramos-plugin")
    def test_the_strip(self) -> None:
        source = (PLUGIN / "src/caramos-show-desktop.c").read_text(encoding="utf-8")
        self.assertIn("#define STRIP_WIDTH 4", source)
        self.assertIn('gtk_widget_set_name (strip, "caramos-show-desktop")', source)
        self.assertIn("_NET_SHOWING_DESKTOP", source, "the window manager's own Show desktop, as Super+D")
        self.assertIn("xfce_panel_plugin_set_small (plugin, FALSE)", source)
        entry = (PLUGIN / "src/caramos-show-desktop.desktop").read_text(encoding="utf-8")
        self.assertIn("X-XFCE-Module=caramos-show-desktop\n", entry)
        self.assertIn("X-XFCE-Internal=true\n", entry, "no process of its own on 2 GB computers")
        makefile = (PLUGIN / "src/Makefile").read_text(encoding="utf-8")
        self.assertIn("PLUGINS := caramos-control-center caramos-show-desktop", makefile)
        control = (PLUGIN / "debian/control").read_text(encoding="utf-8")
        self.assertIn("libx11-dev", control)
        self.assertTrue((PLUGIN / "debian/changelog").read_text(encoding="utf-8").startswith(
            "xfce4-caramos-plugin (1.1.0)"))

    def test_the_island_keeps_its_place(self) -> None:
        css = ISLANDS.read_text(encoding="utf-8")
        help_rule = re.search(r"\n#launcher-6 button \{\n(.*?)\}", css, re.S).group(1)
        self.assertIn("margin: 4px 0;", help_rule, "the strip takes the 4 px between the island and the edge")
        strip = re.search(r"\n#caramos-show-desktop \{\n(.*?)\}", css, re.S).group(1)
        for line in ("min-width: 0;", "background: none;", "border-style: none;"):
            self.assertIn(line, strip)
        hover = re.search(r"#caramos-show-desktop:hover,\n#caramos-show-desktop:active \{(.*?)\}", css, re.S).group(1)
        # A thin line with a little of the island's colour around it: it shows on any wallpaper.
        self.assertIn("background-size: 2px 16px, 4px 20px;", hover)
        self.assertIn("linear-gradient(@caramos_island, @caramos_island)", hover)

    @unittest.skipUnless((REPO / "scripts").is_dir(), "the source package has no scripts/")
    def test_the_iso_checks_for_the_plugin(self) -> None:
        bootstrap = (REPO / "scripts/ota_bootstrap.sh").read_text(encoding="utf-8")
        self.assertIn("/usr/share/xfce4/panel/plugins/caramos-show-desktop.desktop", bootstrap)


class Session(deferred.Session):
    """A login whose commands answer from a table instead of running."""

    def __init__(self, desktop: str, answer, home: Path = Path("/home/minh")) -> None:
        super().__init__("minh", 1000, home, desktop, environ={})
        self.answer = answer
        self.commands: list[list[str]] = []

    def run(self, args, timeout=deferred.COMMAND_TIMEOUT):  # noqa: ANN001
        self.commands.append(list(args))
        return self.answer(list(args))

    def log(self, message: str) -> None:
        self.messages.append(message)


class AutomaticUpdateTests(unittest.TestCase):
    """While someone works, their panel waits for their next login; every other account changes at once."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.queue = self.root / "login-actions"
        self.runtime = self.root / "run/user"
        (self.runtime / "1000").mkdir(parents=True)
        (self.runtime / "1000/bus").touch()   # minh is logged in, lan is not
        for name, value in (("QUEUE_DIR", self.queue), ("RUNTIME_ROOT", self.runtime),
                            ("DCONF_FLAG", self.root / "dconf-update-pending")):
            patcher = mock.patch.object(deferred, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.users = [("minh", 1000, self.root / "minh"), ("lan", 1001, self.root / "lan")]

    def run_cinnamon(self, unattended: bool) -> list[str]:
        context = MigrationContext(unattended=unattended)
        with mock.patch.object(migration, "CORNER_BAR_DIR", self.root), \
                mock.patch.object(migration.help_applet, "_desktop_users", return_value=self.users), \
                mock.patch.object(migration, "cinnamon_defaults"), \
                mock.patch.object(migration, "cinnamon_user") as user, mock.patch.object(context, "log"):
            (self.root / "applet.js").touch()
            migration.run(context, "cinnamon")
        return [call.args[1] for call in user.call_args_list]

    def queued(self, uid: int = 1000) -> list[str]:
        data = json.loads(deferred.queue_file(uid).read_text(encoding="utf-8"))
        return [f"{entry['migration']}/{entry['action']}" for entry in data["actions"]]

    def test_an_automatic_update_leaves_a_logged_in_panel_for_the_next_login(self) -> None:
        self.assertEqual(["lan"], self.run_cinnamon(unattended=True))
        self.assertEqual([f"{migration.MIGRATION}/corner-bar"], self.queued())
        self.assertFalse(deferred.queue_file(1001).exists())

    def test_the_update_center_changes_every_panel_at_once(self) -> None:
        self.assertEqual(["minh", "lan"], self.run_cinnamon(unattended=False))
        self.assertFalse(self.queue.exists())

    def test_an_xfce_panel_in_use_waits_too(self) -> None:
        home = self.root / "minh"
        (home / ".config/xfce4/xfconf/xfce-perchannel-xml").mkdir(parents=True)
        (home / ".config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml").touch()
        for unattended, queued in ((False, False), (True, True)):
            with self.subTest(unattended=unattended):
                context = MigrationContext(unattended=unattended)
                with mock.patch.object(context, "run_command",
                                       return_value=subprocess.CompletedProcess([], 1, "", "")) as run, \
                        mock.patch.object(context, "log"):
                    migration.xfce_user(context, "minh", 1000, home, runtime_root=self.runtime)
                self.assertEqual(queued, run.call_count == 0, "no xfconf-query on the open panel")
                self.assertEqual(queued, deferred.queue_file(1000).exists())


class NextLoginTests(unittest.TestCase):
    """What a logged-in user's next login runs, before the desktop starts: gsettings and xfconf-query as the user."""

    def test_the_corner_bar_goes_on_the_cinnamon_panel(self) -> None:
        def answer(args):  # noqa: ANN001
            return subprocess.CompletedProcess(args, 0, INSTALLED + "\n" if args[1] == "get" else "", "")

        session = Session("cinnamon", answer)
        migration.LOGIN_ACTIONS["corner-bar"](session)
        self.assertEqual(["gsettings", "get", "org.cinnamon", "enabled-applets"], session.commands[0])
        self.assertEqual(["gsettings", "set", "org.cinnamon", "enabled-applets", migration.add_corner_bar(INSTALLED)],
                         session.commands[1])
        self.assertEqual(2, len(session.commands), "no applet to reload: Cinnamon has not started yet")

    def test_a_panel_that_has_it_already_stays(self) -> None:
        done = migration.add_corner_bar(INSTALLED)
        session = Session("cinnamon", lambda args: subprocess.CompletedProcess(args, 0, done + "\n", ""))
        migration.LOGIN_ACTIONS["corner-bar"](session)
        self.assertEqual(1, len(session.commands))

    def test_the_xfce_strip_goes_through_the_sessions_xfconfd(self) -> None:
        layout = XfcePanelTests.LAYOUT[2]
        listing = "\n".join(f"/plugins/plugin-{n}   {name}" for n, name in layout.items())
        arrays = {"/panels": [1, 2, 3], "/panels/panel-1/plugin-ids": [1], "/panels/panel-2/plugin-ids": [2],
                  "/panels/panel-3/plugin-ids": [3, 5, 6]}

        def answer(args):  # noqa: ANN001
            if args[-2:] == ["-l", "-v"]:
                return subprocess.CompletedProcess(args, 0, listing, "")
            if args[-2] == "-p" and args[-1] in arrays:
                values = arrays[args[-1]]
                text = f"Value is an array with {len(values)} items:\n\n" + "".join(f"{v}\n" for v in values)
                return subprocess.CompletedProcess(args, 0, text, "")
            return subprocess.CompletedProcess(args, 0, "", "")

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".config/xfce4/xfconf/xfce-perchannel-xml").mkdir(parents=True)
            (home / ".config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml").touch()
            session = Session("xfce", answer, home)
            migration.LOGIN_ACTIONS["xfce-strip"](session)
        writes = [command for command in session.commands if "-s" in command]
        self.assertEqual(["xfconf-query", "-c", "xfce4-panel", "-p", "/plugins/plugin-15", "-n", "-t", "string", "-s",
                          "caramos-show-desktop"], writes[0])
        self.assertEqual("/panels/panel-3/plugin-ids", writes[1][4])
        self.assertTrue(all(command[0] == "xfconf-query" for command in session.commands), "as the user: no runuser")
        self.assertIn("Show desktop ends the taskbar of minh", session.messages[-1])

    def test_each_step_only_on_its_desktop(self) -> None:
        session = Session("xfce", lambda args: subprocess.CompletedProcess(args, 0, "", ""))
        migration.LOGIN_ACTIONS["corner-bar"](session)
        session.desktop = "cinnamon"
        migration.LOGIN_ACTIONS["xfce-strip"](session)
        self.assertEqual([], session.commands)


class ManifestTests(unittest.TestCase):
    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("desktops", manifest, "both editions")
        self.assertEqual("anytime", manifest["unattended"],
                         "an automatic update leaves a logged-in user's panel for their next login")
        self.assertIn("lần đăng nhập sau", manifest["release_notes_vi"][-1])
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))


if __name__ == "__main__":
    unittest.main()

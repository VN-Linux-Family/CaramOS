"""The round CaramOS menu on Xfce (users asked for it after 1.4.0): the CSS in panel-islands.css and
panel-islands-dark.css, and migration 20261120100500, which gives the menu (Whisker) the opacity under 100 that its
round corners need. The right-click menus of both editions are tests/test_round_menus.py."""

from __future__ import annotations

import importlib
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).parents[1]
XFCE_SHARE = ROOT / "usr/share/caramos-ota/xfce"
WHISKER_RC = ROOT.parents[1] / "config/includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4/panel/whiskermenu-1.rc"
migration = importlib.import_module("caramos_ota_update.migrations.20261120100500_xfce_round_menus.migration")

# The menu's defaults in CaramOS 1.4.0.
WHISKER_1_4_0 = """button-icon=/usr/share/pixmaps/caramos-logo.png
launcher-show-name=true
launcher-show-description=true
favorites=firefox.desktop,nemo.desktop,caramos-app-center.desktop,caramos-lab.desktop,caramos-update-center.desktop,caramos-driver-check.desktop,xfce4-terminal.desktop,xfce-settings-manager.desktop
hover-switch-category=true
position-search-alternate=true
position-commands-alternate=false
position-categories-alternate=true
command-switchuser=dm-tool switch-to-greeter
item-icon-size=2
view-as-icons=false
"""


def blocks(css: str) -> dict[str, dict[str, str]]:
    """{selector: {property: value}} of the CSS, comments left out."""

    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found: dict[str, dict[str, str]] = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        declarations = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+);", body))
        for selector in selectors.split(","):
            found.setdefault(" ".join(selector.split()), {}).update(declarations)
    return found


class CssTests(unittest.TestCase):
    def setUp(self) -> None:
        self.files = {name: (XFCE_SHARE / name).read_text(encoding="utf-8")
                      for name in ("panel-islands.css", "panel-islands-dark.css")}

    def test_the_menu_is_a_round_card(self) -> None:
        for name, css in self.files.items():
            with self.subTest(name):
                rules = blocks(css)
                window = rules["#whiskermenu-window"]
                self.assertEqual("@caramos_menu", window["background-color"])
                self.assertEqual(window["border-radius"], rules["#whiskermenu-window > frame > border"]["border-radius"])
                self.assertEqual("999px", rules["#whiskermenu-window .search-area entry"]["border-radius"])

    def test_the_menu_is_opaque(self) -> None:
        # Whisker paints its window at 99 %: a background that lets windows show through would add to that.
        for name, css in self.files.items():
            with self.subTest(name):
                colour = re.search(r"^@define-color caramos_menu (.+);$", css, re.M).group(1)
                self.assertRegex(colour, r"^rgb\(\d+, \d+, \d+\)$")

    def test_right_click_menus_are_shared_with_cinnamon(self) -> None:
        # They are ../gtk/round-menus.css, which both editions import (migration 20261120100600).
        for name, css in self.files.items():
            with self.subTest(name):
                self.assertNotIn(".csd menu", css)


class DefaultsTests(unittest.TestCase):
    def test_1_4_0_becomes_the_iso_of_now(self) -> None:
        new = migration.defaults_with_opacity(WHISKER_1_4_0)
        self.assertTrue(new.startswith(WHISKER_1_4_0))
        self.assertIn("\nmenu-opacity=99\n", new)
        self.assertEqual(new, migration.defaults_with_opacity(new), "once")
        if WHISKER_RC.is_file():  # the source package has no config/
            self.assertEqual(WHISKER_RC.read_text(encoding="utf-8"), new)

    def test_an_opacity_under_100_stays(self) -> None:
        self.assertEqual("a=1\nmenu-opacity=80\n", migration.defaults_with_opacity("a=1\nmenu-opacity=80\n"))
        self.assertEqual("a=1\nmenu-opacity=99\nb=2\n", migration.defaults_with_opacity("a=1\nmenu-opacity=100\nb=2\n"))
        self.assertTrue(migration.defaults_with_opacity("a=1").startswith("a=1\n#"))

    def test_written_only_when_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "whiskermenu-1.rc"
            path.write_text(WHISKER_1_4_0, encoding="utf-8")
            logged: list[str] = []
            with mock.patch.object(MigrationContext, "log", side_effect=logged.append):
                migration.xfce_defaults(MigrationContext(), path)
                first = path.read_text(encoding="utf-8")
                migration.xfce_defaults(MigrationContext(), path)
                migration.xfce_defaults(MigrationContext(), Path(tmp) / "missing.rc")
            self.assertEqual(migration.defaults_with_opacity(WHISKER_1_4_0), first)
            self.assertEqual(first, path.read_text(encoding="utf-8"))
            self.assertTrue(any(line.startswith("file unchanged") for line in logged), logged)


class UserTests(unittest.TestCase):
    LISTING = ("/panels                    <<UNSUPPORTED>>\n/plugins/plugin-1          whiskermenu\n"
               "/plugins/plugin-2          docklike\n/plugins/plugin-7          caramos-control-center\n")

    def run_user(self, logged_in: bool, opacity: str | None = None, own_panels: bool = True,
                 write_fails: bool = False) -> tuple[list, list]:
        commands: list[list[str]] = []
        logged: list[str] = []
        listing = self.LISTING + (f"/plugins/plugin-1/menu-opacity {opacity}\n" if opacity else "")

        def run_command(argv, allow_fail=False, env=None):  # noqa: ANN001
            commands.append(list(argv))
            if argv[-2:] == ["-l", "-v"]:
                return subprocess.CompletedProcess(argv, 0, listing, "")
            return subprocess.CompletedProcess(argv, 1 if write_fails else 0, "", "no" if write_fails else "")

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            runtime = Path(tmp) / "run"
            if own_panels:
                (home / migration.USER_PANELS).parent.mkdir(parents=True)
                (home / migration.USER_PANELS).write_text("<channel/>", encoding="utf-8")
            if logged_in:
                (runtime / "1000").mkdir(parents=True)
                (runtime / "1000" / "bus").touch()
            context = MigrationContext()
            with mock.patch.object(context, "run_command", side_effect=run_command), \
                    mock.patch.object(context, "log", side_effect=logged.append):
                migration.xfce_user(context, "minh", 1000, home, runtime_root=runtime)
        return commands, logged

    def test_a_running_menu_takes_99_at_once(self) -> None:
        # It read the old default (100) when the session started.
        commands, logged = self.run_user(logged_in=True)
        self.assertTrue(all("dbus-run-session" not in command for command in commands))
        self.assertEqual(["runuser", "-u", "minh", "--", "xfconf-query", "-c", "xfce4-panel", "-p",
                          "/plugins/plugin-1/menu-opacity", "-n", "-t", "int", "-s", "99"], commands[-1])
        self.assertIn("opacity 99", logged[-1])

    def test_not_logged_in_the_default_is_enough(self) -> None:
        commands, logged = self.run_user(logged_in=False)
        self.assertEqual(1, len(commands), "only read")
        self.assertIn("nothing to change", logged[-1])

    def test_100_set_by_the_user_becomes_99(self) -> None:
        commands, _logged = self.run_user(logged_in=False, opacity="100")
        self.assertTrue(all(command[4:6] == ["dbus-run-session", "--"] for command in commands))
        self.assertEqual(["-s", "99"], commands[-1][-2:])

    def test_an_opacity_chosen_under_100_stays(self) -> None:
        for logged_in in (True, False):
            with self.subTest(logged_in=logged_in):
                commands, _logged = self.run_user(logged_in=logged_in, opacity="85")
                self.assertEqual(1, len(commands), "only read")

    def test_defaults_and_not_logged_in(self) -> None:
        commands, logged = self.run_user(logged_in=False, own_panels=False)
        self.assertEqual([], commands)
        self.assertIn("still the defaults", logged[0])

    def test_a_failed_write_is_logged(self) -> None:
        _commands, logged = self.run_user(logged_in=True, write_fails=True)
        self.assertTrue(logged[-1].startswith("warning:"))

    def test_menus_found_by_type(self) -> None:
        properties = {"/plugins/plugin-1": "launcher", "/plugins/plugin-9": "whiskermenu",
                      "/plugins/plugin-12": "whiskermenu", "/plugins/plugin-12/menu-opacity": "100"}
        self.assertEqual([9, 12], migration.to_set(properties, logged_in=True))
        self.assertEqual([12], migration.to_set(properties, logged_in=False))

    def test_run(self) -> None:
        users = [("minh", 1000, Path("/home/minh")), ("lan", 1001, Path("/home/lan"))]
        with mock.patch.object(migration.clipboard, "_desktop_users", return_value=users), \
                mock.patch.object(migration, "xfce_defaults") as defaults, \
                mock.patch.object(migration, "xfce_user") as user, \
                mock.patch.object(MigrationContext, "log"):
            migration.run(MigrationContext())
            defaults.assert_called_once()
            self.assertEqual(["minh", "lan"], [call.args[1] for call in user.call_args_list])
            user.reset_mock()
            migration.run(MigrationContext(dry_run=True))
            user.assert_not_called()

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(["xfce"], manifest["desktops"])
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertIn("lần đăng nhập sau", manifest["release_notes_vi"][-1])


if __name__ == "__main__":
    unittest.main()

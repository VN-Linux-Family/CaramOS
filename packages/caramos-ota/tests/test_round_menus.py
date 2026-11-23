"""Migration 20261120100600_round_menus: round menus on both editions (users asked for it after 1.4.0). GTK right-click
menus through caramos-ota's gtk/round-menus.css, Cinnamon's own menus through a block at the end of its theme."""

from __future__ import annotations

import importlib
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).parents[1]
ROUND_MENUS = ROOT / "usr/share/caramos-ota/gtk/round-menus.css"
DARK = ROOT / "usr/share/themes/Cinnamon-Delight-Dark"
CONTROL_CENTER_CSS = ROOT / "usr/share/caramos-ota/applets/caramos-control-center@caramos/stylesheet.css"
migration = importlib.import_module("caramos_ota_update.migrations.20261120100600_round_menus.migration")


def blocks(css: str) -> dict[str, dict[str, str]]:
    """{selector: {property: value}} of the CSS, comments left out."""

    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found: dict[str, dict[str, str]] = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        declarations = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+);", body))
        for selector in selectors.split(","):
            found.setdefault(" ".join(selector.split()), {}).update(declarations)
    return found


class GtkTests(unittest.TestCase):
    def test_round_only_on_a_composited_screen(self) -> None:
        # Without a compositor GTK gives menus no .csd class and no transparency: round corners would be black there.
        rules = blocks(ROUND_MENUS.read_text(encoding="utf-8"))
        round_menus = [selector for selector, declarations in rules.items() if "border-radius" in declarations]
        self.assertTrue(round_menus)
        self.assertTrue(all(selector.startswith(".csd") for selector in round_menus), round_menus)
        self.assertEqual(rules[".csd menu"]["border-radius"], rules[".csd.popup decoration"]["border-radius"])

    def test_shapes_only(self) -> None:
        # One file for the light and the dark theme: the colours stay theirs.
        properties = {name for declarations in blocks(ROUND_MENUS.read_text(encoding="utf-8")).values()
                      for name in declarations}
        self.assertFalse({name for name in properties if "color" in name or "background" in name}, properties)

    def test_installed_by_the_package(self) -> None:
        self.assertIn("usr/share/caramos-ota/gtk usr/share/caramos-ota/\n",
                      (ROOT / "debian/install").read_text(encoding="utf-8"))

    def test_the_dark_theme_imports_it_after_its_own_menus(self) -> None:
        css = (DARK / "gtk-3.0/gtk.css").read_text(encoding="utf-8")
        self.assertTrue(css.endswith(migration.GTK_IMPORT))
        self.assertLess(css.rindex(".csd menu"), css.index(migration.GTK_IMPORT))

    def test_the_light_theme_imports_it_once(self) -> None:
        new = migration.gtk_with_import("menu { border-radius: 0; }\n")
        self.assertTrue(new.endswith(migration.GTK_IMPORT))
        self.assertEqual(new, migration.gtk_with_import(new))


class CinnamonTests(unittest.TestCase):
    def test_the_dark_theme_ends_with_the_block(self) -> None:
        css = (DARK / "cinnamon/cinnamon.css").read_text(encoding="utf-8")
        self.assertEqual(1, css.count(migration.START))
        self.assertTrue(css.endswith(migration.CINNAMON_BLOCK))

    def test_the_start_menu_is_rounder(self) -> None:
        rules = blocks(migration.CINNAMON_BLOCK)
        self.assertEqual("12px", rules[".menu.bottom"]["border-radius"])
        self.assertEqual("20px", rules[".menu.menu-background.bottom"]["border-radius"])
        self.assertEqual("999px", rules[".menu-background #menu-search-entry"]["border-radius"])

    def test_the_control_center_keeps_its_card(self) -> None:
        # Its applet's selectors are more specific than the block's, for every side the panel can be on.
        rules = blocks(CONTROL_CENTER_CSS.read_text(encoding="utf-8"))
        for side in ("", ".top", ".bottom", ".left", ".right"):
            with self.subTest(side=side):
                self.assertEqual("28px", rules[f".menu.caramos-cc-popup{side}"]["border-radius"])

    def test_added_once_and_replaced(self) -> None:
        new = migration.cinnamon_with_block(".menu { border-radius: 3px; }\n")
        self.assertTrue(new.endswith(migration.CINNAMON_BLOCK))
        self.assertEqual(new, migration.cinnamon_with_block(new))
        older = f".a {{}}\n{migration.START}\n.menu {{ border-radius: 4px; }}\n{migration.END}\n.b {{}}\n"
        replaced = migration.cinnamon_with_block(older)
        self.assertIn(migration.CINNAMON_BLOCK.rstrip("\n") + "\n.b {}\n", replaced)
        self.assertNotIn("4px", replaced)
        self.assertEqual(replaced, migration.cinnamon_with_block(replaced))

    def test_half_a_block_stays(self) -> None:
        self.assertEqual("", migration.cinnamon_with_block(f".a {{}}\n{migration.START}\n.menu {{}}\n"))
        self.assertEqual("", migration.cinnamon_with_block(f"{migration.END}\n.a {{}}\n{migration.START}\n"))


class RestoreTests(unittest.TestCase):
    def theme(self, cinnamon: str = ".menu { border-radius: 3px; }\n") -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        theme = Path(tmp.name)
        for name, text in ((migration.GTK_CSS, "menu { border-radius: 0; }\n"), (migration.CINNAMON_CSS, cinnamon)):
            (theme / name).parent.mkdir(parents=True)
            (theme / name).write_text(text, encoding="utf-8")
            (theme / name).chmod(0o644)
        return theme

    def restore(self, theme: Path, dry_run: bool = False) -> list[str]:
        logged: list[str] = []
        with mock.patch.object(MigrationContext, "log", side_effect=logged.append):
            migration.restore(MigrationContext(dry_run=dry_run), theme)
        return logged

    def test_both_files(self) -> None:
        theme = self.theme()
        self.restore(theme)
        self.assertTrue((theme / migration.GTK_CSS).read_text(encoding="utf-8").endswith(migration.GTK_IMPORT))
        self.assertTrue((theme / migration.CINNAMON_CSS).read_text(encoding="utf-8").endswith(migration.CINNAMON_BLOCK))
        self.assertEqual(0o644, (theme / migration.CINNAMON_CSS).stat().st_mode & 0o777)
        self.assertTrue(all("round already" in line for line in self.restore(theme)))

    def test_dry_run(self) -> None:
        theme = self.theme()
        self.restore(theme, dry_run=True)
        self.assertEqual(".menu { border-radius: 3px; }\n",
                         (theme / migration.CINNAMON_CSS).read_text(encoding="utf-8"))

    def test_without_the_theme(self) -> None:
        logged = self.restore(Path("/nonexistent/Cinnamon-Delight"))
        self.assertEqual(2, len(logged))
        self.assertTrue(all("nothing to change" in line for line in logged))

    def test_half_a_block_is_left_alone(self) -> None:
        half = f".a {{}}\n{migration.START}\n"
        theme = self.theme(half)
        logged = self.restore(theme)
        self.assertEqual(half, (theme / migration.CINNAMON_CSS).read_text(encoding="utf-8"))
        self.assertTrue(any(line.startswith("warning:") for line in logged), logged)

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("desktops", manifest)
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertIn("lần đăng nhập sau", manifest["release_notes_vi"][-1])


if __name__ == "__main__":
    unittest.main()

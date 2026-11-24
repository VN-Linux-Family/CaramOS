"""The names under the icons of the Cinnamon desktop read on light wallpapers too: a dark shadow on every side of the
letters, the same as the Xfce edition's desktop names (xfce/panel-islands.css, ticket H-1187).

Cinnamon's desktop is nemo-desktop, which styles these names in Nemo's own nemo-style-application.css. Nemo loads that
CSS at application priority, above any GTK theme, so a theme rule for .nemo-desktop.nemo-canvas-item never shows (on
CaramOS 1.5.0 a red colour and a blue shadow added to Cinnamon-Delight's gtk.css changed nothing). caramos-nemo-menu
therefore writes Nemo's CSS from the installed library with only that shadow changed,
/etc/X11/Xsession.d/85caramos-nemo-desktop-labels points Nemo at it through G_RESOURCE_OVERLAYS, and migration
20261124120000_desktop_icon_labels runs the script and tells Cinnamon users."""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).resolve().parents[1]
MENU_SCRIPT = ROOT / "usr/share/caramos-ota/nemo-menu/caramos-nemo-menu"
FIXTURE = ROOT / "tests/data/nemo-6.6.3/nemo-style-application.css"
XFCE_CSS = ROOT / "usr/share/caramos-ota/xfce/panel-islands.css"
XSESSION = ROOT / "etc/X11/Xsession.d/85caramos-nemo-desktop-labels"
MENU_XSESSION = ROOT / "etc/X11/Xsession.d/85caramos-nemo-menu"
MIGRATION_ID = "20261124120000_desktop_icon_labels"
MIGRATION_DIR = ROOT / "usr/lib/python3/dist-packages/caramos_ota_update/migrations" / MIGRATION_ID
LIBRARY = Path("/usr/lib/x86_64-linux-gnu/libnemo-extension.so.1")
NAMES = ".nemo-desktop.nemo-canvas-item"
migration = importlib.import_module(f"caramos_ota_update.migrations.{MIGRATION_ID}.migration")


def load(path: Path, name: str):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


menu = load(MENU_SCRIPT, "caramos_nemo_menu_labels_test")
NEMO_CSS = FIXTURE.read_text(encoding="utf-8")


def blocks(css: str) -> dict[str, dict[str, str]]:
    """{selector: {property: value}} of the CSS, comments left out, whitespace in the values collapsed."""

    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    found: dict[str, dict[str, str]] = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        declarations = {name: " ".join(value.split()) for name, value in re.findall(r"([\w-]+)\s*:\s*([^;]+);", body)}
        for selector in selectors.split(","):
            found.setdefault(" ".join(selector.split()), {}).update(declarations)
    return found


def changed_css() -> str:
    return menu.desktop_labels(NEMO_CSS, LIBRARY)


class CssTests(unittest.TestCase):
    def test_only_the_shadow_of_the_desktop_names_changes(self) -> None:
        nemo, ours = blocks(NEMO_CSS), blocks(changed_css())
        self.assertEqual(set(nemo), set(ours))
        for selector, declarations in nemo.items():
            expected = dict(declarations)
            if selector == NAMES:
                expected["text-shadow"] = ours[NAMES]["text-shadow"]
            self.assertEqual(expected, ours[selector], selector)
        self.assertEqual("1px 1px alpha(black, 0.8)", nemo[NAMES]["text-shadow"])
        self.assertNotEqual(nemo[NAMES]["text-shadow"], ours[NAMES]["text-shadow"])
        # Line for line, only the shadow differs after the header.
        body = changed_css().split("*/\n\n", 1)[1].splitlines()
        different = [(a, b) for a, b in zip(NEMO_CSS.splitlines(), body) if a != b]
        self.assertEqual(len(NEMO_CSS.splitlines()), len(body))
        self.assertEqual([("    text-shadow: 1px 1px alpha(black, 0.8);", "    " + menu.DESKTOP_LABEL_SHADOW)],
                         different)

    def test_the_same_shadow_as_the_xfce_edition(self) -> None:
        xfce = re.search(r"\nXfdesktopIconView\.view\.label \{\n\s*text-shadow: (.*?);",
                         XFCE_CSS.read_text(encoding="utf-8"), re.S)
        self.assertIsNotNone(xfce, "the Xfce edition's rule for its desktop names")
        self.assertEqual(" ".join(xfce.group(1).split()), blocks(changed_css())[NAMES]["text-shadow"])

    def test_a_shadow_on_every_side(self) -> None:
        offsets = re.findall(r"(-?\d+)(?:px)? (-?\d+)(?:px)? \d+px", blocks(changed_css())[NAMES]["text-shadow"])
        self.assertEqual({("0", "1"), ("1", "0"), ("-1", "0"), ("0", "-1"), ("0", "2")}, set(offsets))

    def test_hover_and_selected_keep_their_highlight_without_a_shadow(self) -> None:
        ours = blocks(changed_css())
        for state in (":hover", ":selected"):
            with self.subTest(state=state):
                self.assertEqual("none", ours[NAMES + state]["text-shadow"])
                self.assertIn("background-color", ours[NAMES + state])

    def test_the_file_says_what_it_is(self) -> None:
        header = changed_css().split("*/", 1)[0]
        self.assertTrue(header.startswith("/* CaramOS:"))
        self.assertIn(str(LIBRARY), header)
        self.assertIn("85caramos-nemo-desktop-labels", header)

    def test_refuses_unknown_or_changed_css(self) -> None:
        cases = {
            "changed already": changed_css(),
            "no rule of its own": NEMO_CSS.replace(f"{NAMES} {{", f"{NAMES}, .other {{"),
            "no shadow in it": NEMO_CSS.replace("    text-shadow: 1px 1px alpha(black, 0.8);\n", ""),
            "two rules": NEMO_CSS + f"\n{NAMES} {{\n    color: red;\n}}\n",
            "empty": "",
        }
        for name, css in cases.items():
            with self.subTest(name), self.assertRaises(menu.MenuError):
                menu.desktop_labels(css, LIBRARY)


class UpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.out = self.root / "nemo-menu"
        self.css = self.out / "nemo-style-application.css"

    def update(self, css: str | None, library: Path | None = LIBRARY) -> bool:
        def read_resources(_library: Path, paths: list[str]) -> dict[str, str]:
            if css is None:
                raise menu.MenuError("no CSS")
            return {path: css for path in paths}

        with mock.patch.object(menu, "read_resources", side_effect=read_resources), mock.patch("builtins.print"):
            return menu.update_desktop_labels(library, self.out)

    def test_writes_the_css_next_to_the_menus(self) -> None:
        self.assertTrue(self.update(NEMO_CSS))
        self.assertEqual(changed_css(), self.css.read_text(encoding="utf-8"))
        self.assertEqual(0o644, self.css.stat().st_mode & 0o777)
        self.assertTrue(self.update(NEMO_CSS), "again after a Nemo update")

    def test_a_nemo_it_does_not_know_keeps_its_own_css_and_the_menus(self) -> None:
        self.out.mkdir()
        menus = [self.out / name for name in ("nemo-directory-view-ui.xml", "nemo-tree-sidebar-ui.xml")]
        for path in (*menus, self.css):
            path.write_text("old", encoding="utf-8")
        self.assertFalse(self.update(NEMO_CSS.replace("text-shadow: 1px 1px alpha(black, 0.8);", "")))
        self.assertFalse(self.css.exists())
        self.assertTrue(all(path.exists() for path in menus))
        self.css.write_text("old", encoding="utf-8")
        self.assertFalse(self.update(None))
        self.assertFalse(self.update(NEMO_CSS, library=None))
        self.assertFalse(self.css.exists())

    def test_menus_nemo_changed_leave_the_css(self) -> None:
        self.assertTrue(self.update(NEMO_CSS))
        library = self.root / "libnemo-extension.so.1"
        library.write_bytes(b"\x7fELF" + bytes(64))                 # no menus in it
        with mock.patch("builtins.print"):
            self.assertFalse(menu.update(library, self.out))
        self.assertEqual(changed_css(), self.css.read_text(encoding="utf-8"))

    def test_remove_takes_the_css_too(self) -> None:
        self.assertTrue(self.update(NEMO_CSS))
        menu.remove(self.out)
        self.assertEqual([], list(self.out.iterdir()))

    def test_main_writes_the_menus_and_the_css_from_one_library(self) -> None:
        with mock.patch.object(menu, "update") as menus, mock.patch.object(menu, "update_desktop_labels") as labels:
            self.assertEqual(0, menu.main(["--library", str(self.root / "lib.so"), "--out", str(self.out)]))
        menus.assert_called_once_with(self.root / "lib.so", self.out)
        labels.assert_called_once_with(self.root / "lib.so", self.out)

    @unittest.skipUnless(shutil.which("glib-compile-resources"), "needs glib-compile-resources")
    def test_reads_the_css_compiled_into_the_library(self) -> None:
        try:
            menu.gio()
        except (ImportError, ValueError):
            self.skipTest("needs gi")
        bundle_xml = self.root / "nemo.gresource.xml"
        bundle_xml.write_text('<?xml version="1.0" encoding="UTF-8"?><gresources><gresource prefix="/org/nemo">'
                              "<file>nemo-style-application.css</file></gresource></gresources>", encoding="utf-8")
        bundle = self.root / "nemo.gresource"
        subprocess.run(["glib-compile-resources", f"--sourcedir={FIXTURE.parent}", f"--target={bundle}",
                        str(bundle_xml)], check=True)
        library = self.root / "libnemo-extension.so.1"
        library.write_bytes(b"\x7fELF" + b"GVariant\x00nemo" + bytes(1000) + bundle.read_bytes() + bytes(64))
        with mock.patch("builtins.print"):
            self.assertTrue(menu.update_desktop_labels(library, self.out))
        self.assertEqual(menu.desktop_labels(NEMO_CSS, library), self.css.read_text(encoding="utf-8"))


class XsessionTests(unittest.TestCase):
    def overlays(self, css: bool, snippets: tuple[Path, ...] = (XSESSION,), **environ: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "nemo-menu"
            directory.mkdir()
            names = ["nemo-directory-view-ui.xml", "nemo-tree-sidebar-ui.xml"]
            names += ["nemo-style-application.css"] if css else []
            for name in names:
                (directory / name).write_text("x", encoding="utf-8")
            sourced = []
            for snippet in sorted(snippets, key=lambda path: path.name):    # Xsession(5) sources them in this order
                copy = Path(tmp) / snippet.name
                text = snippet.read_text(encoding="utf-8").replace("/var/lib/caramos-ota/nemo-menu", str(directory))
                copy.write_text(text, encoding="utf-8")
                sourced.append(f'. "{copy}"')
            script = "; ".join(sourced) + '; printf %s "${G_RESOURCE_OVERLAYS-}|${CARAMOS_NEMO_STYLE-unset}"'
            result = subprocess.run(["sh", "-ec", script], env={"PATH": "/usr/bin:/bin", **environ},
                                    capture_output=True, text=True, check=True)
            return result.stdout.replace(str(directory), "DIR")

    def test_every_language_gets_the_css(self) -> None:
        expected = "/org/nemo/nemo-style-application.css=DIR/nemo-style-application.css|unset"
        for lang in ("vi_VN.UTF-8", "en_US.UTF-8", "en_GB.UTF-8", "fr_FR.UTF-8", "C"):
            with self.subTest(lang=lang):
                self.assertEqual(expected, self.overlays(True, LANG=lang))

    def test_without_the_css_nemo_keeps_its_own(self) -> None:
        self.assertEqual("|unset", self.overlays(False, LANG="vi_VN.UTF-8"))

    def test_other_overlays_are_kept(self) -> None:
        self.assertEqual("/org/nemo/nemo-style-application.css=DIR/nemo-style-application.css:/org/x=/tmp/x|unset",
                         self.overlays(True, LANG="vi_VN.UTF-8", G_RESOURCE_OVERLAYS="/org/x=/tmp/x"))

    def test_with_the_menus(self) -> None:
        both = self.overlays(True, (XSESSION, MENU_XSESSION), LANG="vi_VN.UTF-8", LANGUAGE="vi_VN:vi").split("|")[0]
        self.assertEqual(["/org/nemo/nemo-directory-view-ui.xml=DIR/nemo-directory-view-ui.xml",
                          "/org/nemo/nemo-tree-sidebar-ui.xml=DIR/nemo-tree-sidebar-ui.xml",
                          "/org/nemo/nemo-style-application.css=DIR/nemo-style-application.css"], both.split(":"))


class PackagingTests(unittest.TestCase):
    def test_the_package_ships_the_snippet_and_writes_the_css_after_nemo_updates(self) -> None:
        self.assertIn("etc/X11/Xsession.d/85caramos-nemo-desktop-labels etc/X11/Xsession.d/\n",
                      (ROOT / "debian/install").read_text(encoding="utf-8"))
        # caramos-nemo-menu runs on configure and when libnemo-extension changes (tests/test_nemo_new_menu.py).
        self.assertEqual(2, (ROOT / "debian/postinst").read_text(encoding="utf-8")
                         .count("/usr/share/caramos-ota/nemo-menu/caramos-nemo-menu || true"))
        self.assertIn("interest-noawait /usr/lib/x86_64-linux-gnu/libnemo-extension.so.1",
                      (ROOT / "debian/triggers").read_text(encoding="utf-8"))


class MigrationTests(unittest.TestCase):
    def logged(self, context: MigrationContext, **kwargs: Path) -> list[str]:
        lines: list[str] = []
        with mock.patch.object(MigrationContext, "log", side_effect=lines.append):
            migration.run(context, **kwargs)
        return lines

    def test_manifest(self) -> None:
        manifest = json.loads((MIGRATION_DIR / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(["cinnamon"], manifest["desktops"])        # Xfce's desktop names: xfce/panel-islands.css
        self.assertEqual("anytime", manifest["unattended"])         # the screen changes from the next login only
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertIn("lần đăng nhập sau", manifest["release_notes_vi"][-1])
        self.assertIn("next login", manifest["release_notes_en"][-1])
        self.assertIn("Xfce", manifest["summary"])
        self.assertIn("Xfce", manifest["summary_en"])

    def test_runs_the_script_and_logs_what_it_did(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "caramos-nemo-menu"
            script.write_text("#!/bin/sh\necho 'wrote the menus'\necho\necho 'wrote the stronger shadow'\n",
                              encoding="utf-8")
            script.chmod(0o755)
            lines = self.logged(MigrationContext(), generator=script)
        self.assertEqual(["wrote the menus\nwrote the stronger shadow"], lines)

    def test_dry_run_and_a_missing_script_change_nothing(self) -> None:
        with mock.patch.object(migration.subprocess, "run") as run:
            self.assertEqual(1, len(self.logged(MigrationContext(dry_run=True))))
            lines = self.logged(MigrationContext(), generator=Path("/nonexistent/caramos-nemo-menu"))
        run.assert_not_called()
        self.assertIn("missing", lines[0])


if __name__ == "__main__":
    unittest.main()

"""Checks for the Update Center's pages: what they say, how they are built and styled (DESIGN.md)."""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

from caramos_ota_notifier import ui
from caramos_ota_notifier.constants import BUSY, CANCELLED, DONE, FAILED

ROOT = Path(__file__).parents[1]
DIST = ROOT / "usr/lib/python3/dist-packages"
UI = DIST / "caramos_ota_notifier/ui.py"
NOTIFIER = [UI, DIST / "caramos_ota_notifier/app.py", DIST / "caramos_ota_notifier/state.py",
            DIST / "caramos_ota_notifier/auto_update.py"]

UPDATE = {
    "release": "1.4.0",
    "current_version": "1.3.11",
    "channel": "stable",
    "severity": "normal",
    "size": "CopyQ (~3 MB) + Giao diện (dưới 1 MB) + Giao diện (dưới 1 MB)",
    "size_en": "CopyQ (~3 MB) + Look (under 1 MB) + Look (under 1 MB)",
    "packages": [
        {"name": "Bấm Super+V để xem lịch sử clipboard", "name_en": "Press Super+V for the clipboard history",
         "description": "Như Win+V trên Windows.", "description_en": "As Win+V on Windows."},
        {"name": "Các menu bo tròn góc", "name_en": "Round corners for the menus",
         "description": "Menu chuột phải bo tròn góc.", "description_en": "Right-click menus have round corners."},
    ],
}


def builder_source(name: str) -> str:
    source = UI.read_text(encoding="utf-8")
    return source.split(f"def {name}", 1)[1].split("\ndef ", 1)[0]


class UpdatePageTextTests(unittest.TestCase):
    """No compiled catalog in the source tree: the English source strings show."""

    def test_the_headline_is_the_new_version_and_the_sentence_the_installed_one(self) -> None:
        self.assertEqual(("CaramOS 1.4.0", "You are using 1.3.11."), ui.update_intro(UPDATE))
        self.assertEqual(("CaramOS 1.4.0", ""), ui.update_intro(dict(UPDATE, current_version="")))

    def test_changes_that_keep_the_version_name_the_version_they_are_for(self) -> None:
        # Timestamp migrations released without a new version number: 1.4.0 before and after.
        same = dict(UPDATE, current_version="1.4.0")
        self.assertEqual(("An update for CaramOS 1.4.0", "This update has 2 changes for the version you have."),
                         ui.update_intro(same))
        self.assertEqual("Updating CaramOS", ui.progress_title(same))
        self.assertEqual("CaramOS was updated", ui.done_title(same))
        self.assertEqual("Updating to CaramOS 1.4.0", ui.progress_title(UPDATE))
        self.assertEqual("Updated to CaramOS 1.4.0", ui.done_title(UPDATE))
        self.assertEqual("Updating CaramOS", ui.progress_title(None))

    def test_only_a_security_update_says_its_severity(self) -> None:
        self.assertFalse(ui.is_security_update(UPDATE))
        self.assertFalse(ui.is_security_update(dict(UPDATE, severity="important")))
        self.assertTrue(ui.is_security_update(dict(UPDATE, severity="security")))
        page = builder_source("build_update_page")
        self.assertIn('if is_security_update(update_info):', page)
        self.assertIn('"uc-warning"', page)

    def test_sizes_and_the_channel_are_only_under_details(self) -> None:
        self.assertEqual([("Size", "CopyQ (~3 MB)\nLook (under 1 MB)"), ("Update channel", "stable")],
                         ui.update_details(UPDATE))
        version_only = {"channel": "stable", "size_en": "Release metadata",
                        "packages": [{"name": "CaramOS release metadata"}]}
        self.assertEqual([("Update channel", "stable")], ui.update_details(version_only))
        page = builder_source("build_update_page")
        self.assertIn("_details(Gtk, details)", page)
        for removed in ("chip", "Severity", "_(\"Update channel\")", "version-box", "→"):
            self.assertNotIn(removed, page)

    def test_the_list_shows_titles_and_descriptions_without_versions_or_badges(self) -> None:
        page = builder_source("build_update_page")
        self.assertIn("for title, description in change_rows(update_info)", page)
        source = UI.read_text(encoding="utf-8")
        for removed in ('badge = "bắt buộc"', "ver_lbl.set_text", "set_tooltip_text(str(pkg", "Gtk.Paned",
                        "notes_panel", "object-select-symbolic", "eyebrow", "hero"):
            self.assertNotIn(removed, source)

    def test_result_and_empty_pages_say_what_happened_and_what_to_do(self) -> None:
        self.assertEqual(("Updated to CaramOS 1.4.0", "Some changes show after you log in again."),
                         ui.result_texts(DONE, UPDATE, can_ask_for_help=True))
        # What happened, then what to do, one sentence a line.
        self.assertEqual(("Could not update", "The update stopped because of an error.\n"
                                              "Click Ask for help to ask VNLF, with this update's log attached."),
                         ui.result_texts(FAILED, UPDATE, can_ask_for_help=True))
        self.assertNotIn("Ask for help", ui.result_texts(FAILED, UPDATE, can_ask_for_help=False)[1])
        for outcome in (CANCELLED, BUSY):
            text = ui.result_texts(outcome, UPDATE, can_ask_for_help=False)[1]
            self.assertIn("Try again", text.split("\n")[1])
        self.assertEqual("You are using the latest version, 1.4.0.\nThe computer checks for new versions every day.",
                         ui.no_update_text({"current_version": "1.4.0"}))
        self.assertEqual("You are using the latest version.\nThe computer checks for new versions every day.",
                         ui.no_update_text({"current_version": "Unknown"}))

    def test_no_technical_words_outside_details(self) -> None:
        # DESIGN.md: migration, systemd, timer, the stable channel, severity, package, PPA only under "Details".
        details_only = {"The pkexec command was not found."}
        jargon = re.compile(r"migration|systemd|timer|\bstable\b|severity|package|\bPPA\b|sudo|repair", re.I)
        for path in NOTIFIER:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") in {"_", "ngettext"}:
                    text = node.args[0].value
                    if text not in details_only:
                        self.assertIsNone(jargon.search(text), f"{path.name}: {text!r}")


class PageStructureTests(unittest.TestCase):
    def test_every_page_keeps_its_buttons_on_screen(self) -> None:
        # Issue #77: on small screens the update button fell below the window.
        source = UI.read_text(encoding="utf-8")
        self.assertIn("window.set_size_request(380, 360)", source)
        for builder in ("build_update_page", "build_progress_page"):
            body = builder_source(builder)
            self.assertIn("return _page(Gtk", body.replace("page = _page(Gtk", "return _page(Gtk"), builder)
        for builder in ("build_result_page", "build_no_update_page"):
            self.assertIn("return _status_page(Gtk", builder_source(builder), builder)
        # The action bar is packed outside the scrolled body; a status page has its buttons right under its text,
        # above the details, so they show at the smallest window size.
        page = builder_source("_page")
        self.assertLess(page.index("page.pack_start(scroll"), page.index("page.pack_end(bar"))
        status = builder_source("_status_page")
        self.assertLess(status.index("status.pack_start(row"), status.index("_log_details(Gtk, detail"))

    def test_the_window_title_is_the_name_of_the_app(self) -> None:
        window = builder_source("build_update_window")
        self.assertIn('window.set_title(_("Update Center"))', window)
        self.assertNotIn("set_subtitle", window)
        self.assertNotIn("CaramOS - ", UI.read_text(encoding="utf-8"))
        self.assertNotIn("set_title(", (DIST / "caramos_ota_notifier/app.py").read_text(encoding="utf-8"))

    def test_stylesheet_uses_the_design_colours_and_the_system_font(self) -> None:
        light, dark = ui.stylesheet(False), ui.stylesheet(True)
        for value in ("#fafafb", "#ffffff", "rgba(0, 0, 0, 0.09)", "#2b6a44", "rgba(0, 0, 0, 0.82)",
                      "rgba(0, 0, 0, 0.55)", "#9c6e03"):
            self.assertIn(value, light)
        for value in ("#242424", "#2f2f2f", "rgba(255, 255, 255, 0.08)", "#3a855a", "rgba(255, 255, 255, 0.6)",
                      "#f5c04a"):
            self.assertIn(value, dark)
        for css in (light, dark):
            self.assertEqual({"600"}, set(re.findall(r"font-weight:\s*(\w+)", css)))
            self.assertEqual(["monospace"], re.findall(r"font-family:\s*([^;]+);", css))   # the log only
            self.assertNotIn("gradient", css)
            self.assertEqual({"none"}, set(re.findall(r"box-shadow:\s*([^;]+);", css)))
            self.assertIn("border-radius: 12px", css)
            # Scoped to the Update Center: the Audit tool's dialog loads the same stylesheet.
            selectors = [selector.strip() for block in css.split("}") if "{" in block
                         for selector in block.split("{", 1)[0].split(",")]
            self.assertGreater(len(selectors), 20)
            for selector in selectors:
                self.assertTrue(selector.startswith("window.caramos-ota"), selector)


LAYOUT_CHECK = textwrap.dedent(
    """
    import json, sys, time
    from caramos_ota_notifier import ui
    from caramos_ota_notifier.constants import BUSY, CANCELLED, DONE, FAILED
    Gtk, Gdk, GLib = ui.import_gtk()
    if not Gtk.init_check(None)[0]:
        print("SKIP"); sys.exit(0)
    ui.apply_theme(Gtk, Gdk)
    long = "Như Win+V trên Windows: Super+V hiện những gì bạn sao chép gần đây ngay chỗ con trỏ chuột. " * 2
    info = {"release": "1.4.0", "current_version": "1.3.11", "channel": "stable", "severity": "security",
            "size": "CopyQ (~3 MB)", "packages": [{"name": "Thay đổi %d" % n, "description": long} for n in range(8)]}
    noop = lambda: None
    switch = ui.AutoUpdateSwitch(True, lambda wanted, finish: None, "metered")
    pages = {
        "update": ui.build_update_page(info, noop, noop, auto_update=switch),
        "progress": ui.build_progress_page(info)[0],
        "none": ui.build_no_update_page({"current_version": "1.4.0"}, noop, auto_update=switch),
        "auto-updated": ui.build_auto_updated_page({"update": info, "restart": True}, noop, auto_update=switch),
    }
    for outcome in (DONE, FAILED, CANCELLED, BUSY):
        pages[outcome] = ui.build_result_page(outcome, "Error\\n" * 50, noop, noop if outcome == FAILED else None,
                                              noop if outcome in (CANCELLED, BUSY) else None, update_info=info)
    result = {}
    for name, page in pages.items():
        window = Gtk.OffscreenWindow()
        window.get_style_context().add_class("caramos-ota")
        window.add(page)
        window.set_size_request(380, 360 - 46)   # the smallest window, without its header bar
        window.show_all()
        deadline = time.time() + 0.5
        while time.time() < deadline:
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            time.sleep(0.01)
        buttons = []
        def walk(widget):
            if isinstance(widget, Gtk.Button) and widget.get_mapped():
                x, y = widget.translate_coordinates(window, 0, 0)
                buttons.append({"label": widget.get_label(), "x": x, "y": y, "w": widget.get_allocated_width(),
                                "h": widget.get_allocated_height(),
                                "scrolled": widget.get_ancestor(Gtk.ScrolledWindow) is not None})
            if isinstance(widget, Gtk.Container):
                widget.forall(walk)
        walk(page)
        result[name] = {"width": window.get_allocated_width(), "height": window.get_allocated_height(),
                        "buttons": buttons}
        window.destroy()
    print(json.dumps(result))
    """
)


class SmallWindowLayoutTests(unittest.TestCase):
    def test_buttons_are_fully_visible_in_the_smallest_window(self) -> None:
        env = dict(os.environ, PYTHONPATH=str(DIST), NO_AT_BRIDGE="1")
        try:
            run = subprocess.run([sys.executable, "-c", LAYOUT_CHECK], env=env, capture_output=True, text=True,
                                 timeout=60)
        except subprocess.TimeoutExpired:
            self.skipTest("GTK did not answer")
        if "No module named 'gi'" in run.stderr or "Namespace Gtk not available" in run.stderr \
                or run.stdout.strip() == "SKIP" or "cannot open display" in run.stderr.lower():
            self.skipTest("GTK 3 with a display is not available")
        self.assertEqual(0, run.returncode, run.stderr[-2000:])
        pages = json.loads(run.stdout.strip().splitlines()[-1])
        self.assertEqual({"update", "progress", "none", "auto-updated", DONE, FAILED, CANCELLED, BUSY}, set(pages))
        expected = {"update": ["Later", "Update"], "none": ["Close"], "auto-updated": ["Close"], DONE: ["Close"],
                    FAILED: ["Close", "Ask for help"], CANCELLED: ["Close", "Try again"], BUSY: ["Close", "Try again"],
                    "progress": []}
        for name, page in pages.items():
            with self.subTest(page=name):
                self.assertEqual(expected[name], [button["label"] for button in page["buttons"]])
                for button in page["buttons"]:
                    self.assertGreaterEqual(button["x"], 0)
                    self.assertGreaterEqual(button["y"], 0)
                    self.assertLessEqual(button["x"] + button["w"], page["width"])
                    self.assertLessEqual(button["y"] + button["h"], page["height"])
                if name in ("update", "auto-updated"):
                    # In the fixed bar, not in the scrolled list of changes.
                    self.assertFalse(any(button["scrolled"] for button in page["buttons"]))


class GtkImportTests(unittest.TestCase):
    def test_gtk3_imports_even_when_gtk4_typelibs_are_installed(self) -> None:
        code = (
            "import gi\n"
            "from caramos_ota_notifier.ui import import_gtk\n"
            "Gtk, Gdk, _ = import_gtk()\n"
            "print(Gtk.get_major_version(), gi.get_required_version('Gdk'))\n"
        )
        env = dict(os.environ, PYTHONPATH=str(DIST))
        result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)
        if "Namespace Gtk not available" in result.stderr or "No module named 'gi'" in result.stderr:
            self.skipTest("GTK 3 introspection is not installed")
        self.assertEqual("3 3.0", result.stdout.strip(), result.stderr)


if __name__ == "__main__":
    unittest.main()

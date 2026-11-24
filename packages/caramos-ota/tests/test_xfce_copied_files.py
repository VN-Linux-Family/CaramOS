"""Files copied on the Xfce Desktop paste in Files (Nemo), ticket H-1204: the Xfce Control Center's
backends/copied_files.py offers xfdesktop's copied-files list again without its "\\r"."""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CC_DIR = ROOT / "usr/share/caramos-ota/xfce/control-center"
MODULE = CC_DIR / "caramos_xfce_cc/backends/copied_files.py"
APP = CC_DIR / "caramos_xfce_cc/app.py"

try:
    import gi

    gi.require_version("Gdk", "3.0")
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gdk, Gtk  # noqa: F401

    HAVE_GTK = True
except (ImportError, ValueError):
    HAVE_GTK = False

if HAVE_GTK:
    os.environ.setdefault("CARAMOS_CC_LOCALEDIR", "/nonexistent")
    sys.path.insert(0, str(CC_DIR))

# What xfdesktop 4.18.1 offers as x-special/gnome-copied-files (seen in the VM with xclip), and what Nemo makes of it:
# lines split at "\n" only.
XFDESKTOP_ONE = b"copy\nfile:///home/an/Desktop/Test.docx\r\n"
XFDESKTOP_TWO = b"cut\nfile:///home/an/Desktop/B%C3%A1o%20c%C3%A1o%20%232.txt\r\nfile:///home/an/Desktop/Test.docx\r\n"


def nemo_reads(data: bytes) -> tuple[bool, list[str]] | None:
    """nemo_clipboard_get_uri_list_from_selection_data of Nemo 6.6: (cut, items) as Nemo pastes them."""

    lines = data.decode("utf-8").split("\n")
    if lines[0] not in ("copy", "cut"):
        return None
    return lines[0] == "cut", lines[1:]


@unittest.skipUnless(HAVE_GTK, "PyGObject with GTK 3 is unavailable")
class CopiedFilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from caramos_xfce_cc.backends import copied_files

        cls.module = copied_files

    def test_nemo_fails_on_xfdesktop_lists(self) -> None:
        # The bug: the "\r" stays in the file name, and an empty name follows.
        self.assertEqual((False, ["file:///home/an/Desktop/Test.docx\r", ""]), nemo_reads(XFDESKTOP_ONE))

    def test_xfdesktop_lists_are_fixed(self) -> None:
        self.assertEqual(("copy", ["file:///home/an/Desktop/Test.docx"]), self.module.fixed_list(XFDESKTOP_ONE))
        action, uris = self.module.fixed_list(XFDESKTOP_TWO)
        self.assertEqual("cut", action)
        fixed = self.module.copied_files(action, uris)
        self.assertEqual(b"cut\nfile:///home/an/Desktop/B%C3%A1o%20c%C3%A1o%20%232.txt"
                         b"\nfile:///home/an/Desktop/Test.docx", fixed)
        self.assertEqual((True, uris), nemo_reads(fixed))

    def test_other_clipboard_content_is_left_alone(self) -> None:
        for data in (b"copy\nfile:///home/an/Test.docx",  # Nemo's and Thunar's own lists: nothing to fix
                     b"file:///home/an/Test.docx\r\n",     # not a copied-files list
                     b"copy\r\n",                          # no file
                     b"", None, b"\xff\xfe\r\n"):
            with self.subTest(data=data):
                self.assertIsNone(self.module.fixed_list(data))

    def test_text_gets_paths(self) -> None:
        self.assertEqual("/home/an/Desktop/Báo cáo #2.txt\n/home/an/Desktop/Test.docx",
                         self.module.paths(["file:///home/an/Desktop/B%C3%A1o%20c%C3%A1o%20%232.txt",
                                            "file:///home/an/Desktop/Test.docx"]))

    def test_offers_what_file_managers_and_editors_ask_for(self) -> None:
        self.assertEqual("x-special/gnome-copied-files", self.module.TARGETS[0])
        self.assertIn("text/uri-list", self.module.TARGETS)
        self.assertIn("UTF8_STRING", self.module.TARGETS)


class WiringTests(unittest.TestCase):
    def test_the_control_center_watches_from_its_start_and_survives_a_failure(self) -> None:
        source = APP.read_text(encoding="utf-8")
        startup = source[source.index("    def do_startup"):source.index("    def load_style")]
        self.assertRegex(startup, r"(?s)try:\n\s+from \.backends\.copied_files import CopiedFilesFix\n\n"
                                  r"\s+self\.copied_files = CopiedFilesFix\(\)\n\s+except Exception:")
        self.assertLess(startup.index("CopiedFilesFix()"), startup.index("self.hold()"))

    def test_no_gtk_method_that_pygobject_lacks(self) -> None:
        # gtk_selection_add_target and gtk_selection_owner_set are functions, not widget methods, in PyGObject.
        source = MODULE.read_text(encoding="utf-8")
        self.assertNotRegex(source, r"self\.widget\.selection_(add_target|owner_set)\(")
        self.assertIsNone(re.search(r"\bset_with_data\b", source))  # not introspectable


if __name__ == "__main__":
    unittest.main()

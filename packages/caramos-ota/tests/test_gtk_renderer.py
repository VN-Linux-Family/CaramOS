"""caramos_ota.gtk_renderer: cairo for CaramOS's GTK 4 programs where OpenGL would run on the CPU or memory is short."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from caramos_ota import gtk_renderer

ROOT = Path(__file__).parents[1]
SHARE = ROOT / "usr/share/caramos-ota"
GIB = 1024 * 1024


class RendererTests(unittest.TestCase):
    def test_choice(self) -> None:
        cases = [
            ({}, set(), 8 * GIB, "cairo"),                      # no graphics driver (a VM, simpledrm, vesa)
            ({}, {"virtio_gpu"}, 8 * GIB, "cairo"),
            ({}, {"i915"}, 8 * GIB, None),                      # a real card and memory enough: GTK's choice
            ({}, {"i915", "nvidia"}, 16 * GIB, None),
            ({}, {"amdgpu"}, 4 * GIB - 200 * 1024, "cairo"),    # a "4 GB" machine has a little under 4 GiB
            ({}, {"nouveau"}, None, None),
            ({"GSK_RENDERER": "ngl"}, set(), 2 * GIB, None),    # the user's choice stays
        ]
        for environ, drivers, memory, expected in cases:
            with self.subTest(environ=environ, drivers=drivers, memory=memory):
                self.assertEqual(expected, gtk_renderer.renderer(environ, drivers, memory))

    def test_apply(self) -> None:
        environ: dict[str, str] = {}
        with mock.patch.object(gtk_renderer, "gpu_drivers", return_value=set()), \
                mock.patch.object(gtk_renderer, "memory_kib", return_value=8 * GIB):
            self.assertEqual("cairo", gtk_renderer.apply(environ))
            self.assertEqual({"GSK_RENDERER": "cairo"}, environ)
            environ = {"GSK_RENDERER": "vulkan"}
            self.assertIsNone(gtk_renderer.apply(environ))
            self.assertEqual({"GSK_RENDERER": "vulkan"}, environ)

    def test_graphics_drivers_from_sysfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drm = root / "class/drm"
            for card, driver in (("card0", "i915"), ("card1", "virtio_gpu")):
                (root / "bus/drivers" / driver).mkdir(parents=True)
                (root / "devices" / card).mkdir(parents=True)
                (root / "devices" / card / "driver").symlink_to(root / "bus/drivers" / driver)
                (drm / card).mkdir(parents=True)
                (drm / card / "device").symlink_to(root / "devices" / card)
            (drm / "card0-HDMI-A-1").mkdir()        # an output of card0
            (drm / "renderD128").mkdir()
            (drm / "card2").mkdir()                 # no driver bound
            self.assertEqual({"i915", "virtio_gpu"}, gtk_renderer.gpu_drivers(drm))
            self.assertEqual(set(), gtk_renderer.gpu_drivers(root / "missing"))

    def test_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meminfo = Path(tmp) / "meminfo"
            meminfo.write_text("MemTotal:        2015484 kB\nMemFree:          208480 kB\n", encoding="ascii")
            self.assertEqual(2015484, gtk_renderer.memory_kib(meminfo))
            meminfo.write_text("nonsense\n", encoding="ascii")
            self.assertIsNone(gtk_renderer.memory_kib(meminfo))
            self.assertIsNone(gtk_renderer.memory_kib(Path(tmp) / "missing"))


class ProgramsTests(unittest.TestCase):
    """Each program picks its renderer before GTK opens a window: GTK reads GSK_RENDERER once, for the first one."""

    PROGRAMS = (
        ("driver-check/caramos_driver_check/app.py", "def open_window()"),
        ("driver-check/caramos_driver_check/help_app.py", "def main("),
        ("lab/caramos_lab/app.py", "def open_window()"),
        ("unicode/caramos_unicode/app.py", "def open_window("),
        ("windows-transfer/caramos_transfer/app.py", "def open_window("),
    )

    def test_before_gtk(self) -> None:
        for path, function in self.PROGRAMS:
            with self.subTest(path):
                source = (SHARE / path).read_text(encoding="utf-8")
                body = source[source.index(function):]
                body = body[:re.search(r"\n(def |class )", body[1:]).start() + 1] if re.search(r"\n(def |class )", body[1:]) else body
                self.assertIn("gtk_renderer.apply()", body)
                self.assertLess(body.index("gtk_renderer.apply()"), body.index('gi.require_version("Gtk", "4.0")'))

    def test_every_gtk4_program_is_listed(self) -> None:
        listed = {path.split("/")[0] + "/" + path.split("/")[1] for path, _function in self.PROGRAMS}
        using_gtk4 = {str(path.relative_to(SHARE).parent) for path in SHARE.rglob("*.py")
                      if re.search(r'require_version\("Gtk", "4', path.read_text(encoding="utf-8"))}
        for directory in using_gtk4:
            with self.subTest(directory):
                self.assertTrue(any(directory.startswith(program) for program in listed), directory)


if __name__ == "__main__":
    unittest.main()

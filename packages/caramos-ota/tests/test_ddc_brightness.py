"""External monitors' brightness in the Control Center (ticket H-1183): caramos-ddc, the sliders of both editions,
and migration 20261120100300."""

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

from caramos_ota_update.context import MigrationContext, MigrationContextError

ROOT = Path(__file__).parents[1]
HELPER = ROOT / "usr/share/caramos-ota/control-center/caramos-ddc"
APPLET_JS = ROOT / "usr/share/caramos-ota/applets/caramos-control-center@caramos/applet.js"
XFCE_CC = ROOT / "usr/share/caramos-ota/xfce/control-center"

migration = importlib.import_module("caramos_ota_update.migrations.20261120100300_external_monitor_brightness.migration")
sys.path.insert(0, str(XFCE_CC))
# The Xfce Control Center imports PyGObject, which Launchpad's builders do not have.
HAVE_GI = importlib.util.find_spec("gi") is not None
ddc_backend = importlib.import_module("caramos_xfce_cc.backends.ddc") if HAVE_GI else None

# ddcutil 1.4 (Ubuntu 24.04), `ddcutil detect --brief` with a monitor that answers and one that does not.
DETECT = """Display 1
   I2C bus:  /dev/i2c-4
   Monitor:             DEL:DELL U2419H:ABC123

Invalid display
   I2C bus:  /dev/i2c-5
   Monitor:             BOE::

Display 2
   I2C bus:  /dev/i2c-7
   Monitor:             GSM::
"""


def load_helper() -> object:
    loader = importlib.machinery.SourceFileLoader("caramos_ddc", str(HELPER))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader("caramos_ddc", loader))
    loader.exec_module(module)
    return module


class HelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ddc = load_helper()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runtime = Path(self.tmp.name)

    def test_detect(self) -> None:
        self.assertEqual([{"bus": 4, "name": "DELL U2419H"}, {"bus": 7, "name": "GSM"}],
                         self.ddc.parse_detect(DETECT))
        self.assertEqual([], self.ddc.parse_detect("No displays found.\n"))

    def test_brightness(self) -> None:
        self.assertEqual((60, 100), self.ddc.parse_brightness("VCP 10 C 60 100\n"))
        self.assertEqual((35, 70), self.ddc.parse_brightness("VCP 10 C 35 70"))
        for output in ("VCP 10 ERR", "VCP 10 C 60 0", "", "VCP 12 C 1 2", "garbage"):
            with self.subTest(output):
                self.assertIsNone(self.ddc.parse_brightness(output))

    def test_fingerprint_follows_the_plugged_monitors(self) -> None:
        drm = self.runtime / "drm"
        (drm / "card1-HDMI-A-1").mkdir(parents=True)
        (drm / "card1-eDP-1").mkdir()
        (drm / "card1-eDP-1/edid").write_bytes(b"laptop")
        (drm / "card1-HDMI-A-1/edid").write_bytes(b"")
        alone = self.ddc.fingerprint(drm)
        (drm / "card1-HDMI-A-1/edid").write_bytes(b"dell")
        self.assertNotEqual(alone, self.ddc.fingerprint(drm))

    def calls(self, outputs: dict[tuple[str, ...], str | None]) -> tuple[mock.Mock, list[tuple[str, ...]]]:
        made: list[tuple[str, ...]] = []

        def fake(*args: str, timeout: float = 10) -> str | None:
            made.append(args)
            return outputs.get(args)

        return mock.patch.object(self.ddc, "ddcutil", side_effect=fake), made

    def test_list_keeps_the_monitors_until_one_is_plugged(self) -> None:
        outputs = {("detect", "--brief"): DETECT,
                   ("--bus", "4", "getvcp", "10", "--brief"): "VCP 10 C 60 100",
                   ("--bus", "7", "getvcp", "10", "--brief"): None}
        patch, made = self.calls(outputs)
        with patch, mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.runtime)}), \
                mock.patch.object(self.ddc, "fingerprint", return_value="a"):
            self.assertEqual([{"bus": 4, "name": "DELL U2419H", "brightness": 60, "max": 100}],
                             self.ddc.list_displays())
            self.ddc.list_displays()
        self.assertEqual(1, made.count(("detect", "--brief")), "the second list reads the cache")
        with patch, mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.runtime)}), \
                mock.patch.object(self.ddc, "fingerprint", return_value="b"):
            self.ddc.list_displays()
        self.assertEqual(2, made.count(("detect", "--brief")), "another monitor: found again")

    def test_set_scales_to_the_monitors_maximum(self) -> None:
        patch, made = self.calls({("--bus", "4", "getvcp", "10", "--brief"): "VCP 10 C 10 70",
                                  ("--bus", "4", "setvcp", "10", "35", "--noverify"): ""})
        with patch:
            self.assertTrue(self.ddc.set_brightness(4, 50))
            self.assertTrue(self.ddc.set_brightness(4, 50, 70))
        self.assertEqual(1, made.count(("--bus", "4", "getvcp", "10", "--brief")), "the maximum given skips it")
        self.assertEqual(2, made.count(("--bus", "4", "setvcp", "10", "35", "--noverify")))

    def test_command_line(self) -> None:
        with mock.patch.object(self.ddc, "set_brightness", return_value=True) as set_brightness:
            self.assertEqual(0, self.ddc.main(["caramos-ddc", "set", "4", "80", "100"]))
            set_brightness.assert_called_once_with(4, 80, 100)
        for argv in (["caramos-ddc"], ["caramos-ddc", "set", "4"], ["caramos-ddc", "set", "x", "1"]):
            with self.subTest(argv), mock.patch("sys.stderr"):
                self.assertEqual(2, self.ddc.main(argv))

    def test_no_ddcutil(self) -> None:
        with mock.patch.object(self.ddc, "DDCUTIL", "/nonexistent/ddcutil"):
            self.assertIsNone(self.ddc.ddcutil("detect"))

    def test_executable_and_module_at_boot(self) -> None:
        self.assertTrue(os.access(HELPER, os.X_OK))
        self.assertIn("\ni2c-dev\n", (ROOT / "usr/lib/modules-load.d/caramos-ddc.conf").read_text(encoding="utf-8"))
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        self.assertIn("usr/lib/modules-load.d/caramos-ddc.conf usr/lib/modules-load.d/", install)
        self.assertIn("usr/share/caramos-ota/control-center usr/share/caramos-ota/", install)


class CinnamonSliderTests(unittest.TestCase):
    def test_displays(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node is unavailable")
        source = APPLET_JS.read_text(encoding="utf-8")
        function = re.search(r"^function ddcDisplays\(.*?^\}\n", source, re.S | re.M).group(0)
        listing = json.dumps([{"bus": 4, "name": "DELL U2419H", "brightness": 35, "max": 70},
                              {"bus": 5, "name": "bad", "brightness": 90, "max": 70},
                              {"bus": "6", "name": "bad", "brightness": 1, "max": 2}])
        script = function + f"process.stdout.write(JSON.stringify([ddcDisplays({json.dumps(listing)}), " \
                            "ddcDisplays('not json'), ddcDisplays('{}')]));"
        found = json.loads(subprocess.run([node, "-e", script], check=True, capture_output=True, text=True).stdout)
        self.assertEqual([[{"bus": 4, "name": "DELL U2419H", "percent": 50, "max": 70}], [], []], found)

    def test_wiring(self) -> None:
        source = APPLET_JS.read_text(encoding="utf-8")
        self.assertIn("this._refreshVpnState();\n                this._refreshDdc();", source)
        self.assertIn("[DDC_HELPER, 'set', String(display.bus), String(value), String(display.max)]", source)


@unittest.skipUnless(HAVE_GI, "PyGObject is unavailable")
class XfceSliderTests(unittest.TestCase):
    def test_displays(self) -> None:
        listing = json.dumps([{"bus": 4, "name": "DELL U2419H", "brightness": 35, "max": 70},
                              {"bus": True, "name": "", "brightness": 1, "max": 2},
                              {"bus": 5, "brightness": 3, "max": 2}])
        self.assertEqual([{"bus": 4, "name": "DELL U2419H", "fraction": 0.5, "max": 70}],
                         ddc_backend.displays(listing))
        self.assertEqual([], ddc_backend.displays("oops"))

    def test_one_write_at_a_time_and_the_last_wins(self) -> None:
        started: list[tuple[list[str], object]] = []
        with mock.patch.object(ddc_backend, "run_async", side_effect=lambda argv, done: started.append((argv, done))):
            ddc = ddc_backend.Ddc("/bin/true")
            display = {"bus": 4, "name": "DELL", "fraction": 0.5, "max": 70}
            for value in (0.1, 0.2, 0.3):
                ddc.set(display, value)
            self.assertEqual([["/bin/true", "set", "4", "10", "70"]], [argv for argv, _done in started])
            self.assertTrue(ddc.busy(4))
            started[0][1](True, "", "")
            self.assertEqual(["/bin/true", "set", "4", "30", "70"], started[1][0], "0.2 was overtaken")
            started[1][1](True, "", "")
            self.assertEqual(2, len(started))
            self.assertFalse(ddc.busy(4))

    def test_the_popup_has_the_sliders(self) -> None:
        popup = (XFCE_CC / "caramos_xfce_cc/popup.py").read_text(encoding="utf-8")
        self.assertIn("self.b.ddc.read(self._show_ddc)", popup)
        self.assertIn('w.SliderRow("video-display-symbolic", name, lambda value, d=display: self.b.ddc.set(d, value))',
                      popup)


class MigrationTests(unittest.TestCase):
    def run_migration(self, installed: bool, systemd: bool, loaded: bool, apt_fails: bool = False) -> tuple[list, list]:
        context = MigrationContext()
        commands: list[list[str]] = []
        logged: list[str] = []

        def run_command(args, allow_fail=False, env=None):  # noqa: ANN001, ANN202
            commands.append(list(args))
            if args[0] == "dpkg-query":
                return subprocess.CompletedProcess(args, 0 if installed else 1, "ii " if installed else "", "")
            return subprocess.CompletedProcess(args, 0, "", "")

        apt = mock.Mock(side_effect=MigrationContextError("offline") if apt_fails else None)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(context, "run_command", side_effect=run_command), \
                mock.patch.object(context, "apt_install", apt), \
                mock.patch.object(context, "log", side_effect=logged.append):
            runtime, module = Path(tmp) / "systemd", Path(tmp) / "i2c_dev"
            if systemd:
                runtime.mkdir()
            if loaded:
                module.mkdir()
            migration.run(context, runtime, module)
        return commands + [["apt", *call.args[0]] for call in apt.call_args_list], logged

    def test_install_and_load(self) -> None:
        commands, _logged = self.run_migration(installed=False, systemd=True, loaded=False)
        self.assertIn(["apt", "ddcutil"], commands)
        self.assertIn(["modprobe", "i2c-dev"], commands)

    def test_nothing_twice(self) -> None:
        commands, _logged = self.run_migration(installed=True, systemd=True, loaded=True)
        self.assertEqual(["dpkg-query"], [command[0] for command in commands])

    def test_no_module_loading_in_a_chroot(self) -> None:
        commands, logged = self.run_migration(installed=True, systemd=False, loaded=False)
        self.assertNotIn(["modprobe", "i2c-dev"], commands)
        self.assertTrue(any("next boot" in line for line in logged), logged)

    def test_offline_is_no_failure(self) -> None:
        _commands, logged = self.run_migration(installed=False, systemd=True, loaded=False, apt_fails=True)
        self.assertTrue(any("could not install" in line for line in logged), logged)

    def test_manifest_and_iso(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertNotIn("desktops", manifest)
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))

    @unittest.skipUnless((ROOT.parents[1] / "config").is_dir(), "ISO tree is not in the source package")
    def test_iso_installs_ddcutil(self) -> None:
        packages = (ROOT.parents[1] / "config/packages.txt").read_text(encoding="utf-8").split()
        self.assertIn("ddcutil", packages)


if __name__ == "__main__":
    unittest.main()

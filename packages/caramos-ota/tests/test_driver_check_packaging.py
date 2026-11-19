"""Driver Check ships with the OTA package: the app in /usr/share/caramos-ota/driver-check, its command, menu
entry, login check and polkit actions (driver installs, hw-probe)."""

from __future__ import annotations

import configparser
import re
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

ROOT = Path(__file__).parents[1]
APP = ROOT / "usr/share/caramos-ota/driver-check"
HELPER = "/usr/share/caramos-ota/driver-check/caramos-driver-check-helper"
APP_CENTER_FIRST_RUN = ROOT.parent / "caramos-app-center/etc/xdg/autostart/caramos-app-center-first-run.desktop"


def desktop_entry(path: Path) -> configparser.SectionProxy:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    return parser["Desktop Entry"]


class DriverCheckPackagingTests(unittest.TestCase):
    def test_package_installs_every_part(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        for line in (
            "usr/bin/caramos-driver-check usr/bin/",
            "usr/share/caramos-ota/driver-check usr/share/caramos-ota/",
            "usr/share/applications/caramos-driver-check.desktop usr/share/applications/",
            "etc/xdg/autostart/caramos-driver-check.desktop etc/xdg/autostart/",
        ):
            self.assertIn(line + "\n", install)
            self.assertTrue((ROOT / line.split()[0]).exists(), line)
        for executable in ("usr/bin/caramos-driver-check", "usr/share/caramos-ota/driver-check/caramos-driver-check-helper"):
            self.assertTrue((ROOT / executable).stat().st_mode & 0o111, executable)
        for name in ("style.css", "style-dark.css", "caramos_driver_check/app.py", "caramos_driver_check/ui/window.py"):
            self.assertTrue((APP / name).is_file(), name)

    def test_command_and_helper_load_the_app_from_usr_share(self) -> None:
        for path in (ROOT / "usr/bin/caramos-driver-check", APP / "caramos-driver-check-helper"):
            self.assertIn('sys.path.insert(0, "/usr/share/caramos-ota/driver-check")', path.read_text(encoding="utf-8"))
        # The privileged helper ignores PYTHONPATH and the user's site packages.
        self.assertTrue((APP / "caramos-driver-check-helper").read_text(encoding="utf-8").startswith(
            "#!/usr/bin/python3 -I\n"))

    def test_dependencies(self) -> None:
        control = (ROOT / "debian/control").read_text(encoding="utf-8")
        depends = control.split("\nDepends:", 1)[1].split("\nRecommends:", 1)[0]
        recommends = control.split("\nRecommends:", 1)[1].split("\nSuggests:", 1)[0]
        suggests = control.split("\nSuggests:", 1)[1].split("\nDescription:", 1)[0]
        self.assertIn("gir1.2-notify-0.7", depends)
        self.assertIn("gir1.2-gtk-4.0", depends)
        self.assertIn("gir1.2-adw-1", depends)
        self.assertIn("kmod", depends)
        # Pictures and videos of help requests: Pillow (Cinnamon needs it anyway) and ffmpeg, whose
        # libraries Celluloid already brings, so it adds about 2.5 MB.
        self.assertIn("python3-pil", depends)
        self.assertIn("ffmpeg", depends)
        # UbuntuDrivers: the drivers Ubuntu recommends for this hardware (one-click installs).
        self.assertIn("ubuntu-drivers-common", recommends)
        # A recommended hw-probe would bring its own recommends (sysstat and its 10-minute timer) on
        # upgrade; migration 20261012120000_add_driver_check installs it without them.
        self.assertNotIn("hw-probe", recommends)
        self.assertIn("hw-probe", suggests)

    def test_menu_entry(self) -> None:
        entry = desktop_entry(ROOT / "usr/share/applications/caramos-driver-check.desktop")
        self.assertEqual("/usr/bin/caramos-driver-check", entry["Exec"])
        self.assertEqual("Kiểm tra driver", entry["Name[vi]"])
        self.assertEqual("caramos-driver-check", entry["StartupWMClass"])
        self.assertIn("HardwareSettings", entry["Categories"])

    @unittest.skipUnless(APP_CENTER_FIRST_RUN.is_file(), "the App Center is not in the source package")
    def test_login_check_starts_after_the_app_center_picker(self) -> None:
        entry = desktop_entry(ROOT / "etc/xdg/autostart/caramos-driver-check.desktop")
        self.assertEqual("/usr/bin/caramos-driver-check --autostart", entry["Exec"])
        # The Xfce edition (2 GB computers, school labs) checks the drivers at login too.
        self.assertEqual("X-Cinnamon;XFCE;", entry["OnlyShowIn"])
        self.assertEqual("true", entry["NoDisplay"])
        picker = desktop_entry(APP_CENTER_FIRST_RUN)
        # A missing network driver must end up above the picker, which cannot install anything offline.
        self.assertGreater(int(entry["X-GNOME-Autostart-Delay"]), int(picker["X-GNOME-Autostart-Delay"]))

    def test_polkit_actions(self) -> None:
        tree = ElementTree.parse(ROOT / "usr/share/polkit-1/actions/net.vietnamlinuxfamily.caramos-ota.policy")
        actions = {action.get("id"): action for action in tree.getroot().iter("action")}
        expected = {
            "net.vietnamlinuxfamily.caramos-ota.hw-probe": ("/usr/bin/hw-probe", "auth_admin"),
            "net.vietnamlinuxfamily.caramos-ota.driver-install": (HELPER, "auth_admin_keep"),
        }
        for action_id, (path, allow_active) in expected.items():
            with self.subTest(action=action_id):
                action = actions[action_id]
                annotations = {item.get("key"): item.text for item in action.iter("annotate")}
                self.assertEqual(path, annotations["org.freedesktop.policykit.exec.path"])
                self.assertEqual(allow_active, action.find("defaults/allow_active").text)
                self.assertEqual("no", action.find("defaults/allow_any").text)

    def test_the_window_runs_the_helper_from_its_installed_path(self) -> None:
        source = (APP / "caramos_driver_check/install.py").read_text(encoding="utf-8")
        self.assertIn(f'HELPER_PATH = "{HELPER}"', source)

    def test_build_and_smoke_test_compile_the_app(self) -> None:
        testkit = (ROOT / "tools/caramos-ota-testkit.sh").read_text(encoding="utf-8")
        self.assertEqual(2, len(re.findall(r"usr/bin/caramos-driver-check \\", testkit)))
        self.assertEqual(2, len(re.findall(r"usr/share/caramos-ota/driver-check/caramos-driver-check-helper \\",
                                           testkit)))
        self.assertIn("find usr/lib/python3/dist-packages usr/share/caramos-ota/driver-check -name '*.py'", testkit)
        # No bytecode may end up in the .deb.
        self.assertIn("find usr/share/caramos-ota/driver-check -name __pycache__", testkit)


if __name__ == "__main__":
    unittest.main()

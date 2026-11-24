"""Event sounds on the Xfce edition (ticket H-1206): Appearance > Settings > Enable event sounds works, and stays off by
default. The Xfce Control Center loads GTK's sound module while the switch is on (backends/event_sounds.py), and
migration 20261124100300 puts back Xfce's own defaults of the switches, which CaramOS's xsettings.xml had blanked."""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
import subprocess
import sys
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest import mock

from caramos_ota_update.context import MigrationContext, MigrationContextError

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
CC = ROOT / "usr/share/caramos-ota/xfce/control-center"
XSETTINGS_1_5_0 = (ROOT / "tests/data/xsettings.xml-1.5.0").read_text(encoding="utf-8")
ISO = REPO / "config/includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml"
HAVE_GI = importlib.util.find_spec("gi") is not None
migration = importlib.import_module("caramos_ota_update.migrations.20261124100300_xfce_event_sounds.migration")


def net(text: str) -> dict[str, tuple[str, str | None]]:
    node = ElementTree.fromstring(text.encode("utf-8")).find("property[@name='Net']")
    return {item.get("name"): (item.get("type"), item.get("value")) for item in node}


class DefaultsTests(unittest.TestCase):
    def test_xfces_own_defaults_come_back(self) -> None:
        new = migration.defaults_updated(XSETTINGS_1_5_0)
        values = net(new)
        self.assertEqual(("bool", "false"), values["EnableEventSounds"], "off by default: school labs stay quiet")
        self.assertEqual(("bool", "false"), values["EnableInputFeedbackSounds"])
        self.assertEqual(("string", "freedesktop"), values["SoundThemeName"])
        self.assertEqual("", migration.defaults_updated(new), "once")
        self.assertEqual(XSETTINGS_1_5_0.count("\n"), new.count("\n"))

    @unittest.skipUnless(ISO.is_file(), "the source package has no config/")
    def test_new_installs(self) -> None:
        text = ISO.read_text(encoding="utf-8")
        self.assertEqual("", migration.defaults_updated(text))
        self.assertEqual(net(migration.defaults_updated(XSETTINGS_1_5_0)), net(text))
        self.assertNotIn("Modules", re.sub(r"<!--.*?-->", "", text, flags=re.S),
                         "the Control Center adds the module only while sounds are on")

    def test_packages(self) -> None:
        context = MigrationContext()
        status = {"libcanberra-gtk3-module": "ii ", "libcanberra-pulse": "un ", "sound-theme-freedesktop": "ii "}

        def run_command(argv, allow_fail=False, env=None):  # noqa: ANN001
            return subprocess.CompletedProcess(argv, 0, status[argv[-1]], "")

        with mock.patch.object(context, "run_command", side_effect=run_command), \
                mock.patch.object(context, "apt_install") as apt, mock.patch.object(context, "log"), \
                mock.patch.object(migration, "XSETTINGS", Path("/nonexistent")):
            migration.run(context)
            apt.assert_called_once_with(["libcanberra-pulse"], recommends=False)
            apt.side_effect = MigrationContextError("offline")
            migration.run(context)  # logged, the update goes on

    def test_manifest(self) -> None:
        manifest = json.loads((Path(migration.__file__).parent / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(["xfce"], manifest["desktops"])
        self.assertEqual("anytime", manifest["unattended"])
        self.assertEqual(len(manifest["release_notes_vi"]), len(manifest["release_notes_en"]))
        self.assertIn("Settings Manager > Appearance", manifest["release_notes_en"][0])


@unittest.skipUnless(HAVE_GI, "PyGObject is unavailable")
class ControlCenterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        sys.path.insert(0, str(CC))
        cls.module = importlib.import_module("caramos_xfce_cc.backends.event_sounds")

    def test_modules(self) -> None:
        modules_for = self.module.modules_for
        self.assertEqual("canberra-gtk-module", modules_for("", True))
        self.assertEqual("", modules_for("canberra-gtk-module", False))
        self.assertEqual("gail:canberra-gtk-module", modules_for("gail", True))
        self.assertEqual("gail:atk-bridge", modules_for("gail:canberra-gtk-module:atk-bridge", False))
        self.assertEqual("gail:canberra-gtk-module", modules_for("canberra-gtk-module:gail", True), "once, last")

    def test_the_switches(self) -> None:
        class Channel:
            def __init__(self, values: dict) -> None:
                self.values = dict(values)
                self.reset: list[str] = []

            def get_bool(self, prop: str, default: bool) -> bool:
                return self.values.get(prop, default)

            def get_string(self, prop: str, default: str) -> str:
                return self.values.get(prop, default)

            def set_string(self, prop: str, value: str) -> None:
                self.values[prop] = value

            def reset_property(self, prop: str, _recursive: bool) -> None:
                self.values.pop(prop, None)
                self.reset.append(prop)

        sounds = object.__new__(self.module.EventSounds)
        sounds.channel = Channel({"/Net/EnableEventSounds": True})
        sounds.apply()
        self.assertEqual("canberra-gtk-module", sounds.channel.values["/Gtk/Modules"])
        sounds.channel.values["/Net/EnableEventSounds"] = False
        sounds._on_changed(None, "/Net/EnableEventSounds", None)
        self.assertNotIn("/Gtk/Modules", sounds.channel.values)
        sounds.channel = Channel({"/Net/EnableInputFeedbackSounds": True, "/Gtk/Modules": "gail"})
        sounds.apply()
        self.assertEqual("gail:canberra-gtk-module", sounds.channel.values["/Gtk/Modules"])

    def test_the_app_starts_it(self) -> None:
        app = (CC / "caramos_xfce_cc/app.py").read_text(encoding="utf-8")
        self.assertIn("from .backends.event_sounds import EventSounds", app)
        self.assertIn("self.event_sounds = EventSounds()", app)


if __name__ == "__main__":
    unittest.main()

"""CaramOS Xfce: calendar reminders, the Bluetooth applet, System Reports and Flameshot start only when they are
needed (owner, 2026-11-19: the Xfce trial VM used about 800 MB of memory). Then, for school labs ("siêu cơ bản"):
no print queue icon, colour profiles, online accounts, firmware refresh or ModemManager, and xfwm4 without OpenGL."""

from __future__ import annotations

import importlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_ID = "20261119100200_lighten_xfce_session"
FOLDER = ROOT / "usr/lib/python3/dist-packages/caramos_ota_update/migrations" / MIGRATION_ID
migration = importlib.import_module(f"caramos_ota_update.migrations.{MIGRATION_ID}.migration")

ALARM = """[Desktop Entry]
Type=Application
Name=Evolution Alarm Notify
Exec=/usr/libexec/evolution-data-server/evolution-alarm-notify
Icon=appointment-soon
NoDisplay=true
"""
BLUEMAN = """[Desktop Entry]
Name=Blueman Applet
Comment=Blueman Bluetooth Manager
Icon=blueman
Exec=blueman-applet
Terminal=false
Type=Application
Categories=
"""
MINTREPORT = """[Desktop Entry]
Encoding=UTF-8
Name=System Reports
Name[vi]=Báo cáo hệ thống
Comment=Troubleshoot problems
Exec=mintreport-tray
Icon=mintreport
Terminal=false
Type=Application
Categories=
X-GNOME-Autostart-Delay=40
"""
# /etc/skel/.config/autostart/flameshot.desktop of the ISO (config/includes.chroot), copied into every home.
FLAMESHOT = """[Desktop Entry]
Name=Flameshot
Comment=Screenshot tool
# Flameshot paints with QPainter; Qt's OpenGL integration would load Mesa and LLVM (~22 MiB).
Exec=env QT_XCB_GL_INTEGRATION=none /usr/bin/flameshot
Terminal=false
Type=Application
X-GNOME-Autostart-enabled=true
"""
ISO_FLAMESHOT = ROOT.parents[1] / "config/includes.chroot/etc/skel/.config/autostart/flameshot.desktop"
ISO_XFWM4 = ROOT.parents[1] / "config/includes.chroot.xfce/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml"
# /etc/xdg/autostart of Linux Mint 22 Xfce.
PRINT_APPLET = """[Desktop Entry]
Name=Print Queue Applet
Comment=System tray icon for managing print jobs
Exec=system-config-printer-applet
Terminal=false
Type=Application
Icon=printer
NotShowIn=KDE;GNOME;Cinnamon;LXDE;Unity;
StartupNotify=false
X-GNOME-Autostart-Delay=30
X-Ubuntu-Gettext-Domain=system-config-printer
X-Desktop-File-Install-Version=0.27
Categories=System;Monitor;GTK;
"""
XICCD = """[Desktop Entry]
Name=xiccd
GenericName=X color management daemon
Comment=Applies color management profiles to your session
Exec=xiccd
Terminal=false
Type=Application
NotShowIn=GNOME;KDE;
"""
XFWM4 = """<?xml version="1.0" encoding="UTF-8"?>
<!-- a comment -->

<channel name="xfwm4" version="1.0">
  <property name="general" type="empty">
    <property name="theme" type="string" value="Cinnamon-Delight"/>
    <property name="use_compositing" type="bool" value="true"/>
    <property name="workspace_names" type="array">
      <value type="string" value="Workspace 1"/>
    </property>
  </property>
</channel>
"""


class LightenXfceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.system = self.root / "etc/xdg/autostart"
        self.system.mkdir(parents=True)
        self.xfce = self.root / "etc/xdg/caramos-xfce/autostart"
        self.wrappers = self.root / "usr/local/libexec"
        self.units = self.root / "usr/lib/systemd/system"
        self.units.mkdir(parents=True)
        self.goa = self.root / "usr/share/gvfs/remote-volume-monitors/goa.monitor"
        self.xfwm4 = self.root / "etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml"
        self.context = mock.Mock(dry_run=False)

    def tearDown(self) -> None:
        shutil.rmtree(self.root)

    def run_migration(self, homes: list[tuple[Path, int]] | None = None, running: bool = True) -> None:
        # Never the real /etc, /usr, /etc/skel and /home, and no command really runs (the context is a mock).
        migration.run(self.context, self.system, self.xfce, self.wrappers / "caramos-evolution-alarm-notify",
                      self.wrappers / "caramos-blueman-applet", homes=homes or [], unit_dirs=(self.units,),
                      running=running, goa_monitor=self.goa, xfwm4_defaults=self.xfwm4, users=[],
                      runtime_root=self.root / "run/user")

    def commands(self) -> list[list[str]]:
        return [list(call.args[0]) for call in self.context.run_command.call_args_list]

    def home(self, name: str, entry: str | None = FLAMESHOT) -> Path:
        home = self.root / "home" / name
        (home / ".config/autostart").mkdir(parents=True)
        if entry is not None:
            path = home / ".config/autostart/flameshot.desktop"
            path.write_text(entry, encoding="utf-8")
            path.chmod(0o644)
        return home

    def logged(self) -> str:
        return "\n".join(str(call.args[0]) for call in self.context.log.call_args_list)

    def test_only_on_xfce(self) -> None:
        manifest = json.loads((FOLDER / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(["xfce"], manifest["desktops"])

    def test_calendar_reminders_wait_as_on_cinnamon(self) -> None:
        (self.system / "org.gnome.Evolution-alarm-notify.desktop").write_text(ALARM, encoding="utf-8")
        self.run_migration()
        override = (self.xfce / "org.gnome.Evolution-alarm-notify.desktop").read_text(encoding="utf-8")
        self.assertIn(f"Exec={self.wrappers / 'caramos-evolution-alarm-notify'}", override.replace(
            "/usr/local/libexec/caramos-evolution-alarm-notify", str(self.wrappers / "caramos-evolution-alarm-notify")))
        self.assertTrue(os.access(self.wrappers / "caramos-evolution-alarm-notify", os.X_OK))

    def test_bluetooth_applet_only_with_an_adapter(self) -> None:
        (self.system / "blueman.desktop").write_text(BLUEMAN, encoding="utf-8")
        self.run_migration()
        override = (self.xfce / "blueman.desktop").read_text(encoding="utf-8")
        self.assertIn("Exec=/usr/local/libexec/caramos-blueman-applet\n", override)
        self.assertIn("Name=Blueman Applet\n", override)
        wrapper = self.wrappers / "caramos-blueman-applet"
        self.assertTrue(os.access(wrapper, os.X_OK))
        # The wrapper against a fake /sys/class/bluetooth and a fake blueman-applet that leaves a mark.
        sysfs, bin_dir = self.root / "sys-bluetooth", self.root / "bin"
        sysfs.mkdir()
        bin_dir.mkdir()
        mark = self.root / "started"
        applet = bin_dir / "blueman-applet"
        applet.write_text(f"#!/bin/sh\n: > {mark}\n", encoding="utf-8")
        applet.chmod(0o755)
        script = self.root / "wrapper.sh"
        script.write_text(wrapper.read_text(encoding="utf-8").replace("/sys/class/bluetooth", str(sysfs)),
                          encoding="utf-8")

        def start() -> int:
            return subprocess.run(["/bin/sh", str(script)], env={"PATH": str(bin_dir)}, timeout=10).returncode

        self.assertEqual(0, start())
        self.assertFalse(mark.exists(), "no adapter: no applet")
        (sysfs / "hci0").mkdir()
        self.assertEqual(0, start())
        self.assertTrue(mark.exists(), "an adapter: the applet starts")

    def test_unexpected_entries_are_left_alone(self) -> None:
        (self.system / "blueman.desktop").write_text(BLUEMAN.replace("Exec=blueman-applet", "Exec=other"),
                                                    encoding="utf-8")
        self.run_migration()
        self.assertFalse((self.xfce / "blueman.desktop").exists())

    def test_print_queue_icon_and_colour_profiles_off(self) -> None:
        (self.system / "print-applet.desktop").write_text(PRINT_APPLET, encoding="utf-8")
        (self.system / "xiccd.desktop").write_text(XICCD, encoding="utf-8")
        self.run_migration()
        printer = (self.xfce / "print-applet.desktop").read_text(encoding="utf-8")
        self.assertEqual(PRINT_APPLET + "# CaramOS Xfce (caramos-ota): a copy of /etc/xdg/autostart/print-applet.desktop. "
                         "The print queue icon (~21 MiB)\n# does not start at login; Printers in the menu shows the "
                         "queues. Session and Startup can turn it on again.\nHidden=true\n", printer)
        colour = (self.xfce / "xiccd.desktop").read_text(encoding="utf-8")
        self.assertEqual(XICCD + "# CaramOS Xfce (caramos-ota): a copy of /etc/xdg/autostart/xiccd.desktop. Colour "
                         "profiles for calibrated\n# screens (xiccd and colord, ~8 MiB) do not start at login. Session "
                         "and Startup can turn them on again.\nHidden=true\n", colour)
        # Changed by someone: left alone.
        (self.xfce / "xiccd.desktop").unlink()
        (self.system / "xiccd.desktop").write_text(XICCD.replace("Exec=xiccd", "Exec=xiccd -d :0"), encoding="utf-8")
        self.run_migration()
        self.assertFalse((self.xfce / "xiccd.desktop").exists())

    def test_firmware_refresh_and_modem_manager_off(self) -> None:
        for unit in ("fwupd-refresh.timer", "ModemManager.service"):
            (self.units / unit).write_text("[Unit]\n", encoding="utf-8")
        self.run_migration()
        self.assertEqual([mock.call("fwupd-refresh.timer"), mock.call("ModemManager.service")],
                         self.context.ensure_service_disabled.call_args_list)
        # The timer stops at once; ModemManager keeps a 3G/4G connection that is up until the next boot.
        self.assertIn(["systemctl", "stop", "--no-block", "fwupd-refresh.timer"], self.commands())
        self.assertNotIn("ModemManager.service", [part for command in self.commands() for part in command])
        # In the ISO build's chroot (no systemd running), nothing is stopped.
        self.context.reset_mock()
        self.run_migration(running=False)
        self.assertEqual(2, self.context.ensure_service_disabled.call_count)
        self.assertEqual([], [command for command in self.commands() if command[0] == "systemctl"])

    def test_units_that_are_not_installed(self) -> None:
        self.run_migration()
        self.context.ensure_service_disabled.assert_not_called()
        self.assertIn("fwupd-refresh.timer is not installed", self.logged())
        self.assertIn("ModemManager.service is not installed", self.logged())

    def test_online_accounts_monitor_moved_aside(self) -> None:
        self.context.run_command.return_value = subprocess.CompletedProcess([], 0, "", "")
        self.run_migration()
        self.assertEqual([["dpkg-divert", "--list", str(self.goa)],
                          ["dpkg-divert", "--local", "--rename", "--divert", str(self.goa) + ".distrib", "--add",
                           str(self.goa)]], [c for c in self.commands() if c[0] == "dpkg-divert"])
        # gvfs reads only *.monitor files: the diverted name must not be one.
        self.assertFalse((str(self.goa) + ".distrib").endswith(".monitor"))
        self.assertEqual(Path("/usr/share/gvfs/remote-volume-monitors/goa.monitor.distrib"),
                         migration.GOA_MONITOR_DIVERTED)

    def test_online_accounts_monitor_already_diverted(self) -> None:
        self.context.run_command.return_value = subprocess.CompletedProcess(
            [], 0, f"local diversion of {self.goa} to {self.goa}.distrib\n", "")
        self.run_migration()
        self.assertEqual([["dpkg-divert", "--list", str(self.goa)]],
                         [c for c in self.commands() if c[0] == "dpkg-divert"])

    def test_xfwm4_without_opengl(self) -> None:
        self.xfwm4.parent.mkdir(parents=True)
        self.xfwm4.write_text(XFWM4, encoding="utf-8")
        self.run_migration()
        text = self.xfwm4.read_text(encoding="utf-8")
        self.assertEqual(XFWM4.replace('value="true"/>\n', 'value="true"/>\n    <property name="vblank_mode" '
                                       'type="string" value="xpresent"/>\n'), text)
        general = ElementTree.fromstring(text.encode("utf-8")).find("property[@name='general']")
        self.assertEqual("xpresent", general.find("property[@name='vblank_mode']").get("value"))
        self.assertEqual(0o644, self.xfwm4.stat().st_mode & 0o777)
        self.run_migration()
        self.assertEqual(text, self.xfwm4.read_text(encoding="utf-8"))

    def test_xfwm4_vblank_set_by_someone_stays(self) -> None:
        self.xfwm4.parent.mkdir(parents=True)
        for original in (XFWM4.replace("    <property name=\"theme\"", "    <property name=\"vblank_mode\" "
                                       "type=\"string\" value=\"glx\"/>\n    <property name=\"theme\""),
                         XFWM4.replace("use_compositing", "use_compositing_old"), "not xml use_compositing"):
            self.xfwm4.write_text(original, encoding="utf-8")
            self.run_migration()
            self.assertEqual(original, self.xfwm4.read_text(encoding="utf-8"))
        self.xfwm4.unlink()
        self.run_migration()
        self.assertFalse(self.xfwm4.exists())

    def test_users_with_xfwm4s_auto_get_xpresent(self) -> None:
        runtime = self.root / "run/user"
        (runtime / "1001").mkdir(parents=True)
        (runtime / "1001/bus").touch()  # an is logged in; binh is not
        values = {"an": "auto\n", "binh": "auto\n", "chi": "glx\n", "dung": ""}

        def answer(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            value = values[command[2]]
            return subprocess.CompletedProcess(command, 0 if value else 1, value, "" if value else "no property")

        self.context.run_command.side_effect = answer
        migration.users_xfwm4_without_opengl(self.context, [("an", 1001), ("binh", 1002), ("chi", 1003),
                                                            ("dung", 1004)], runtime)
        query = ["xfconf-query", "-c", "xfwm4", "-p", "/general/vblank_mode"]
        through_session = ["runuser", "-u", "an", "--"]
        private_bus = ["runuser", "-u", "binh", "--", "dbus-run-session", "--"]
        self.assertEqual([through_session + query, through_session + query + ["-s", "xpresent"],
                          private_bus + query, private_bus + query + ["-s", "xpresent"],
                          ["runuser", "-u", "chi", "--", "dbus-run-session", "--"] + query,
                          ["runuser", "-u", "dung", "--", "dbus-run-session", "--"] + query], self.commands())
        environments = [call.kwargs["env"] for call in self.context.run_command.call_args_list]
        self.assertEqual(f"unix:path={runtime}/1001/bus", environments[0]["DBUS_SESSION_BUS_ADDRESS"])
        self.assertNotIn("DBUS_SESSION_BUS_ADDRESS", environments[2])
        for env in environments:
            self.assertEqual("/etc/xdg/caramos-xfce:/etc/xdg/xdg-xfce:/etc/xdg", env["XDG_CONFIG_DIRS"])
        self.assertIn("xfwm4 of chi: vblank_mode glx; left alone", self.logged())
        self.assertIn("xfwm4 of dung: vblank_mode not set; left alone", self.logged())

    @unittest.skipUnless(ISO_XFWM4.is_file(), "the repository's config/ (not in the source package)")
    def test_the_iso_already_uses_xpresent(self) -> None:
        text = ISO_XFWM4.read_text(encoding="utf-8")
        general = ElementTree.fromstring(text.encode("utf-8")).find("property[@name='general']")
        self.assertEqual("xpresent", general.find("property[@name='vblank_mode']").get("value"))
        self.assertEqual("", migration.xfwm4_with_xpresent(text))
        # And the migration would have put it where it is.
        line = '    <property name="vblank_mode" type="string" value="xpresent"/>\n'
        self.assertEqual(text, migration.xfwm4_with_xpresent(text.replace(line, "")))

    def test_system_reports_tray_off(self) -> None:
        (self.system / "mintreport.desktop").write_text(MINTREPORT, encoding="utf-8")
        self.run_migration()
        override = self.xfce / "mintreport.desktop"
        text = override.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("X-GNOME-Autostart-Delay=40\n# CaramOS Xfce (caramos-ota): a copy of "
                                      "/etc/xdg/autostart/mintreport.desktop. The System Reports tray icon\n"
                                      "# (~30 MiB) does not start at login; System Reports is in the menu. Session and "
                                      "Startup can turn it on again.\nHidden=true\n"), text)
        # Session and Startup lists it, in Vietnamese too, and can start it again.
        for line in ("Name=System Reports", "Name[vi]=Báo cáo hệ thống", "Exec=mintreport-tray", "Icon=mintreport"):
            self.assertIn(line + "\n", text)
        self.assertEqual(0o644, override.stat().st_mode & 0o777)
        self.run_migration()
        self.assertEqual(text, override.read_text(encoding="utf-8"))

    def test_system_reports_changed_by_someone_is_left_alone(self) -> None:
        (self.system / "mintreport.desktop").write_text(MINTREPORT.replace("Exec=mintreport-tray",
                                                                           "Exec=mintreport-tray --debug"),
                                                        encoding="utf-8")
        self.run_migration()
        self.assertFalse((self.xfce / "mintreport.desktop").exists())

    def test_flameshot_waits_for_print_screen(self) -> None:
        old = FLAMESHOT.replace("Exec=env QT_XCB_GL_INTEGRATION=none /usr/bin/flameshot", "Exec=/usr/bin/flameshot")
        homes = {name: self.home(name, entry) for name, entry in (("an", FLAMESHOT), ("binh", old))}
        self.run_migration([(home, os.getuid()) for home in homes.values()])
        for home in homes.values():
            path = home / ".config/autostart/flameshot.desktop"
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("X-GNOME-Autostart-enabled=true\n# CaramOS Xfce (caramos-ota): Flameshot "
                                          "does not wait in the background from login (~26 MiB). Print Screen\n"
                                          "# starts it when it is needed. Session and Startup can turn this on "
                                          "again.\nHidden=true\n"), text)
            self.assertEqual(0o644, path.stat().st_mode & 0o777)
            self.assertEqual([], [p.name for p in path.parent.iterdir() if p.name != "flameshot.desktop"])
        self.assertIn("Exec=/usr/bin/flameshot\n", (homes["binh"] / ".config/autostart/flameshot.desktop")
                      .read_text(encoding="utf-8"))
        # Again: nothing changes.
        before = (homes["an"] / ".config/autostart/flameshot.desktop").read_text(encoding="utf-8")
        self.context.log.reset_mock()
        self.run_migration([(homes["an"], os.getuid())])
        self.assertEqual(before, (homes["an"] / ".config/autostart/flameshot.desktop").read_text(encoding="utf-8"))
        self.assertIn("already hidden, or changed by its user; left alone", self.logged())

    def test_flameshot_entries_of_the_user_are_left_alone(self) -> None:
        entries = {
            "own-command": FLAMESHOT.replace("/usr/bin/flameshot", "/usr/bin/flameshot --debug"),
            # Turned on again in Session and Startup.
            "turned-on": FLAMESHOT + "Hidden=false\n",
        }
        for name, entry in entries.items():
            home = self.home(name, entry)
            self.run_migration([(home, os.getuid())])
            self.assertEqual(entry, (home / ".config/autostart/flameshot.desktop").read_text(encoding="utf-8"))
        nothing = self.home("nothing", None)
        self.run_migration([(nothing, os.getuid())])
        self.assertEqual([], list((nothing / ".config/autostart").iterdir()))

    def test_flameshot_follows_no_link_and_only_the_users_files(self) -> None:
        elsewhere = self.home("elsewhere")
        linked = self.root / "home" / "linked"
        (linked / ".config").mkdir(parents=True)
        (linked / ".config/autostart").symlink_to(elsewhere / ".config/autostart")
        self.run_migration([(linked, os.getuid()), (self.home("other-user"), os.getuid() + 1)])
        for home in (elsewhere, self.root / "home/other-user"):
            self.assertEqual(FLAMESHOT, (home / ".config/autostart/flameshot.desktop").read_text(encoding="utf-8"))
        self.assertIn("(a symbolic link?)", self.logged())

    def test_dry_run_changes_no_home(self) -> None:
        home = self.home("an")
        self.xfwm4.parent.mkdir(parents=True)
        self.xfwm4.write_text(XFWM4, encoding="utf-8")
        self.context = mock.Mock(dry_run=True)
        self.run_migration([(home, os.getuid())])
        self.assertEqual(FLAMESHOT, (home / ".config/autostart/flameshot.desktop").read_text(encoding="utf-8"))
        self.assertEqual(XFWM4, self.xfwm4.read_text(encoding="utf-8"))

    def test_hidden_goes_into_the_desktop_entry_group(self) -> None:
        entry = "[Desktop Entry]\nName=X\nExec=x\n\n[Desktop Action New]\nName=New\nExec=x --new\n"
        self.assertEqual("[Desktop Entry]\nName=X\nExec=x\n# why\nHidden=true\n\n[Desktop Action New]\n"
                         "Name=New\nExec=x --new\n", migration.hidden(entry, ("Exec=x",), ("why",)))
        self.assertEqual("", migration.hidden("[Desktop Entry]\nExec=y\n", ("Exec=x",), ("why",)))
        self.assertEqual("", migration.hidden("[Desktop Entry]\nExec=x\nHidden = true\n", ("Exec=x",), ("why",)))

    @unittest.skipUnless(ISO_FLAMESHOT.is_file(), "the repository's config/ (not in the source package)")
    def test_the_isos_entry_is_recognised(self) -> None:
        home = self.home("iso", ISO_FLAMESHOT.read_text(encoding="utf-8"))
        self.run_migration([(home, os.getuid())])
        self.assertTrue((home / ".config/autostart/flameshot.desktop").read_text(encoding="utf-8")
                        .endswith("Hidden=true\n"))


if __name__ == "__main__":
    unittest.main()

"""Tests for the migration that lightens the desktop session."""

from __future__ import annotations

import configparser
import importlib.util
import os
import pwd
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from caramos_ota_update.context import MigrationContext

ROOT = Path(__file__).parents[1]
MIGRATION_PATH = (
    ROOT
    / "usr/lib/python3/dist-packages/caramos_ota_update/migrations"
    / "20261010120100_lighten_desktop_session/migration.py"
)
ALARM_NOTIFY = """[Desktop Entry]
Type=Application
Name=Evolution Alarm Notify
Name[vi]=Thông báo báo động Evolution
Exec=/usr/libexec/evolution-data-server/evolution-alarm-notify
NoDisplay=true
X-GNOME-Autostart-Delay=5
"""


def load_migration():
    spec = importlib.util.spec_from_file_location("lighten_desktop_session_test", MIGRATION_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = load_migration()


class LightenDesktopSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.system_autostart = self.root / "etc/xdg/autostart"
        self.system_autostart.mkdir(parents=True)
        (self.system_autostart / migration.ALARM_NOTIFY).write_text(ALARM_NOTIFY, encoding="utf-8")
        (self.system_autostart / migration.PRINT_APPLET).write_text("[Desktop Entry]\nExec=applet.py\n", encoding="utf-8")
        self.units = self.root / "usr/lib/systemd/system"
        self.units.mkdir(parents=True)
        for unit in ("cups-browsed.service", "kerneloops.service", "earlyoom.service"):
            (self.units / unit).write_text("[Service]\n", encoding="utf-8")
        self.runtime = self.root / "run/systemd/system"
        self.users: list[pwd.struct_passwd] = []
        self.system_helper = self.root / "usr/local/sbin/caramos-fcitx5-lotus-system-enable"
        self.login_helper = self.root / "usr/local/bin/caramos-fcitx5-lotus-enable"
        for helper in (self.system_helper, self.login_helper):
            helper.parent.mkdir(parents=True)
            helper.write_text("#!/bin/sh\nsystemctl enable --now x\n", encoding="utf-8")
            helper.chmod(0o755)
        for name, value in {
            "GTK_VISUALS_PRIMER": self.root / "etc/X11/Xsession.d/60caramos-prime-gtk-visuals",
            "FCITX_CLASSICUI": self.root / "etc/xdg/fcitx5/conf/classicui.conf",
            "CINNAMON_AUTOSTART": self.root / "etc/xdg/xdg-cinnamon/autostart",
            "SYSTEM_AUTOSTART": self.system_autostart,
            "EARLYOOM_DROPIN": self.root / "etc/systemd/system/earlyoom.service.d/caramos.conf",
            "UNIT_DIRS": (self.root / "etc/systemd/system", self.units),
            "SYSTEMD_RUNTIME": self.runtime,
            "LOTUS_SYSTEM_HELPER": self.system_helper,
            "LOTUS_LOGIN_HELPER": self.login_helper,
            "ALARM_NOTIFY_WRAPPER": self.root / "usr/local/libexec/caramos-evolution-alarm-notify",
            "SKEL": self.root / "etc/skel",
            "PASSWD_HOME_ROOT": self.root / "home",
            "_desktop_users": lambda: self.users,
        }.items():
            patcher = patch.object(migration, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_migration(self, *, dry_run: bool = False) -> list[list[str]]:
        context = MigrationContext(dry_run=dry_run)
        calls: list[list[str]] = []

        def fake_run(args, **_kwargs):
            calls.append(list(args))
            return subprocess.CompletedProcess(list(args), 0, "", "")

        with patch.object(context, "run_command", side_effect=fake_run):
            migration.run(context)
        return calls

    def read(self, relative: str) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def test_iso_build_writes_the_configuration_and_disables_services(self) -> None:
        calls = self.run_migration()  # no /run/systemd/system: ISO build chroot

        self.assertEqual(migration.GTK_VISUALS_PRIMER_SCRIPT, self.read("etc/X11/Xsession.d/60caramos-prime-gtk-visuals"))
        classicui = self.read("etc/xdg/fcitx5/conf/classicui.conf")
        self.assertIn("UseAccentColor=False\n", classicui)
        self.assertIn("UseDarkTheme=False\n", classicui)
        self.assertIn("Hidden=true\n", self.read("etc/xdg/xdg-cinnamon/autostart/print-applet.desktop"))
        self.assertIn("--avoid ^(init|systemd|Xorg|lightdm|cinnamon-sessio|dbus-)\n",
                      self.read("etc/systemd/system/earlyoom.service.d/caramos.conf"))
        self.assertEqual(
            [["systemctl", "disable", "cups-browsed.service"],
             ["systemctl", "disable", "kerneloops.service"],
             ["systemctl", "enable", "earlyoom.service"]],
            calls,
        )

    def test_alarm_notify_starts_through_the_wrapper(self) -> None:
        self.run_migration()

        override = self.read(f"etc/xdg/xdg-cinnamon/autostart/{migration.ALARM_NOTIFY}")
        lines = override.splitlines()
        self.assertEqual("[Desktop Entry]", lines[0])
        self.assertIn(f"Exec={migration.ALARM_NOTIFY_WRAPPER}", lines)
        for line in ALARM_NOTIFY.splitlines():
            if not line.startswith("Exec="):
                self.assertIn(line, lines)
        self.assertNotIn("Hidden=true", override)
        self.assertNotIn("TryExec", override)
        wrapper = self.root / "usr/local/libexec/caramos-evolution-alarm-notify"
        self.assertEqual(migration.ALARM_NOTIFY_WRAPPER_SCRIPT, wrapper.read_text(encoding="utf-8"))
        self.assertEqual(0o755, wrapper.stat().st_mode & 0o777)

    @unittest.skipUnless(shutil.which("sh") and shutil.which("grep"), "sh and grep are needed")
    def test_wrapper_starts_the_daemon_once_there_is_something_to_remind(self) -> None:
        home = self.root / "home"
        calendar = home / ".local/share/evolution/calendar/system/calendar.ics"
        sources = home / ".config/evolution/sources"
        calendar.parent.mkdir(parents=True)
        sources.mkdir(parents=True)
        calendar.write_text("BEGIN:VCALENDAR\nVERSION:2.0\nEND:VCALENDAR\n", encoding="utf-8")
        (sources / "system-proxy.source").write_text("[Data Source]\n", encoding="utf-8")
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        daemon = self.root / "alarm-notify"
        daemon.write_text("#!/bin/sh\necho started\n", encoding="utf-8")
        daemon.chmod(0o755)
        sleeps = self.root / "sleeps"
        # The fake sleep stands for a minute in which the user adds a first event.
        fake_sleep = bin_dir / "sleep"
        fake_sleep.write_text(
            f"#!/bin/sh\necho \"$1\" >> {sleeps}\n"
            f"printf 'BEGIN:VCALENDAR\\nBEGIN:VEVENT\\nEND:VEVENT\\nEND:VCALENDAR\\n' > {calendar}\n",
            encoding="utf-8")
        fake_sleep.chmod(0o755)
        script = migration.ALARM_NOTIFY_WRAPPER_SCRIPT.replace(
            "/usr/libexec/evolution-data-server/evolution-alarm-notify", str(daemon))
        env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin"}

        def run() -> str:
            return subprocess.run(["sh", "-c", script], env=env, capture_output=True, text=True,
                                  check=True, timeout=10).stdout

        self.assertEqual("started\n", run())
        self.assertEqual("60\n", sleeps.read_text(encoding="utf-8"))

        sleeps.unlink()
        self.assertEqual("started\n", run())  # the event is there now: no waiting
        self.assertFalse(sleeps.exists())

        calendar.write_text("BEGIN:VCALENDAR\nEND:VCALENDAR\n", encoding="utf-8")
        (sources / "1f0c2d.source").write_text("[Data Source]\nDisplayName=Google\n", encoding="utf-8")
        self.assertEqual("started\n", run())  # a calendar account
        self.assertFalse(sleeps.exists())

        (sources / "1f0c2d.source").unlink()
        (bin_dir / "evolution").write_text("#!/bin/sh\n", encoding="utf-8")
        (bin_dir / "evolution").chmod(0o755)
        self.assertEqual("started\n", run())  # Evolution itself
        self.assertFalse(sleeps.exists())

    def test_unexpected_alarm_notify_entry_is_left_alone(self) -> None:
        (self.system_autostart / migration.ALARM_NOTIFY).write_text(
            "[Desktop Entry]\nExec=/opt/other/alarm-notify\n", encoding="utf-8")

        self.run_migration()

        self.assertFalse((self.root / f"etc/xdg/xdg-cinnamon/autostart/{migration.ALARM_NOTIFY}").exists())
        self.assertFalse((self.root / "usr/local/libexec/caramos-evolution-alarm-notify").exists())

    def test_running_system_stops_disabled_services_and_restarts_earlyoom(self) -> None:
        self.runtime.mkdir(parents=True)

        calls = self.run_migration()

        self.assertIn(["systemctl", "stop", "--no-block", "cups-browsed.service"], calls)
        self.assertIn(["systemctl", "stop", "--no-block", "kerneloops.service"], calls)
        self.assertIn(["systemctl", "daemon-reload"], calls)
        self.assertEqual(["systemctl", "restart", "--no-block", "earlyoom.service"], calls[-1])

    def test_lotus_helpers_no_longer_reload_systemd_or_restart_fcitx_at_every_login(self) -> None:
        self.run_migration()

        system_helper = self.system_helper.read_text(encoding="utf-8")
        self.assertEqual(migration.LOTUS_SYSTEM_HELPER_SCRIPT, system_helper)
        self.assertLess(system_helper.index('systemctl is-enabled --quiet "$unit"'),
                        system_helper.index('systemctl enable --now --no-block "$unit"'))
        login_helper = self.login_helper.read_text(encoding="utf-8")
        self.assertEqual(migration.LOTUS_LOGIN_HELPER_SCRIPT, login_helper)
        self.assertNotIn("systemctl", login_helper)
        self.assertNotIn("gsettings", login_helper)
        self.assertIn('if [ "$changed" = 1 ] && command -v fcitx5', login_helper)
        for helper in (self.system_helper, self.login_helper):
            self.assertEqual(0o755, helper.stat().st_mode & 0o777)

    @unittest.skipUnless(shutil.which("sh") and shutil.which("cmp"), "sh and cmp are needed")
    def test_login_helper_restarts_fcitx_only_when_a_default_changed(self) -> None:
        skel = self.root / "skel"
        script = migration.LOTUS_LOGIN_HELPER_SCRIPT.replace("/etc/skel", str(skel))
        (skel / ".config/fcitx5/conf").mkdir(parents=True)
        (skel / ".config/fcitx5/profile").write_text("[Groups/0]\nDefaultIM=lotus\n", encoding="utf-8")
        (skel / ".config/fcitx5/conf/lotus.conf").write_text('InputMethod="Telex"\n', encoding="utf-8")
        home = self.root / "home"
        home.mkdir()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        log = self.root / "fcitx5.log"
        fake = bin_dir / "fcitx5"
        fake.write_text(f'#!/bin/sh\necho "$*" >> {log}\n', encoding="utf-8")
        fake.chmod(0o755)
        env = {"HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin"}

        def login() -> None:
            subprocess.run(["sh", "-c", script], env=env, check=True)

        login()
        self.assertEqual("-d --replace\n", log.read_text(encoding="utf-8"))
        self.assertEqual('InputMethod="Telex"\n', (home / ".config/fcitx5/conf/lotus.conf").read_text(encoding="utf-8"))
        login()
        self.assertEqual("-d --replace\n", log.read_text(encoding="utf-8"))
        (home / ".config/fcitx5/conf/lotus.conf").write_text('InputMethod="VNI"\n', encoding="utf-8")
        login()
        self.assertEqual('InputMethod="Telex"\n', (home / ".config/fcitx5/conf/lotus.conf").read_text(encoding="utf-8"))
        self.assertEqual("-d --replace\n-d --replace\n", log.read_text(encoding="utf-8"))

    def flameshot_entry(self, base: Path, exec_line: str = "Exec=/usr/bin/flameshot") -> Path:
        path = base / ".config/autostart/flameshot.desktop"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"[Desktop Entry]\nName=Flameshot\n{exec_line}\nType=Application\n", encoding="utf-8")
        path.chmod(0o644)
        return path

    def add_user(self, name: str) -> Path:
        home = self.root / "home" / name
        home.mkdir(parents=True)
        self.users.append(pwd.struct_passwd((name, "x", os.getuid(), os.getgid(), name, str(home), "/bin/bash")))
        return home

    def test_flameshot_starts_without_opengl_for_skel_and_users(self) -> None:
        skel = self.flameshot_entry(self.root / "etc/skel")
        an = self.flameshot_entry(self.add_user("an"))
        binh = self.flameshot_entry(self.add_user("binh"), "Exec=/usr/bin/flameshot --tray-icon-hidden")
        self.add_user("chi")  # no autostart entry

        self.run_migration()

        for path in (skel, an):
            self.assertIn("Exec=env QT_XCB_GL_INTEGRATION=none /usr/bin/flameshot\n", path.read_text(encoding="utf-8"))
            self.assertIn("Name=Flameshot\n", path.read_text(encoding="utf-8"))
            self.assertEqual(0o644, path.stat().st_mode & 0o777)
        self.assertIn("Exec=/usr/bin/flameshot --tray-icon-hidden\n", binh.read_text(encoding="utf-8"))
        self.assertFalse((self.root / "home/chi/.config").exists())
        self.assertEqual([], list(an.parent.glob(".flameshot.desktop.*")))

    def test_flameshot_entry_behind_a_symlink_is_left_alone(self) -> None:
        home = self.add_user("an")
        elsewhere = self.root / "elsewhere"
        target = self.flameshot_entry(elsewhere)
        (home / ".config").mkdir()
        (home / ".config/autostart").symlink_to(target.parent, target_is_directory=True)

        self.run_migration()

        self.assertIn("Exec=/usr/bin/flameshot\n", target.read_text(encoding="utf-8"))

    def test_skips_what_is_not_installed(self) -> None:
        self.system_helper.unlink()
        self.login_helper.unlink()
        for path in self.system_autostart.iterdir():
            path.unlink()
        for unit in ("kerneloops.service", "earlyoom.service"):
            (self.units / unit).unlink()

        calls = self.run_migration()

        self.assertFalse((self.root / "etc/xdg/xdg-cinnamon/autostart").exists())
        self.assertFalse((self.root / "etc/systemd/system/earlyoom.service.d").exists())
        self.assertFalse(self.system_helper.exists())
        self.assertFalse(self.login_helper.exists())
        self.assertEqual([["systemctl", "disable", "cups-browsed.service"]], calls)

    def test_dry_run_writes_nothing_and_second_run_rewrites_nothing(self) -> None:
        self.run_migration(dry_run=True)
        self.assertFalse((self.root / "etc/X11").exists())
        self.assertFalse((self.root / "etc/xdg/fcitx5").exists())

        self.run_migration()
        written = {path: path.stat().st_mtime_ns for path in self.root.rglob("*") if path.is_file()}
        self.runtime.mkdir(parents=True)
        calls = self.run_migration()
        self.assertEqual(written, {path: path.stat().st_mtime_ns for path in self.root.rglob("*") if path.is_file()})
        self.assertNotIn(["systemctl", "daemon-reload"], calls)

    @unittest.skipUnless(shutil.which("sh"), "sh is needed")
    def test_scripts_are_valid_sh_and_the_primer_runs_in_the_background(self) -> None:
        for script in (migration.GTK_VISUALS_PRIMER_SCRIPT, migration.LOTUS_SYSTEM_HELPER_SCRIPT,
                       migration.LOTUS_LOGIN_HELPER_SCRIPT, migration.ALARM_NOTIFY_WRAPPER_SCRIPT):
            subprocess.run(["sh", "-n"], input=script, text=True, check=True)
        script = migration.GTK_VISUALS_PRIMER_SCRIPT
        self.assertRegex(script, r"\(.*Gdk\.Display\.open\(None\).*&\)")

    def test_earlyoom_avoid_pattern_matches_session_processes_only(self) -> None:
        pattern = re.search(r"--avoid (\S+)", migration.EARLYOOM_DROPIN_CONFIG).group(1)
        # /proc/PID/comm is cut to 15 characters: cinnamon-session-binary is "cinnamon-sessio".
        for name in ("init", "systemd", "systemd-journal", "Xorg", "lightdm", "cinnamon-sessio", "dbus-daemon"):
            self.assertRegex(name, pattern)
        for name in ("cinnamon", "firefox", "Isolated Web Co", "chrome", "python3", "copyq"):
            self.assertNotRegex(name, pattern)
        # systemd expands $ in ExecStart and splits words at spaces.
        self.assertNotIn("$", pattern)


class SchemaOverrideTests(unittest.TestCase):
    def test_mintreport_tray_scans_processes_once_a_minute(self) -> None:
        override = ROOT / "usr/share/glib-2.0/schemas/60_caramos-ota.gschema.override"
        parser = configparser.ConfigParser()
        parser.read(override, encoding="utf-8")
        self.assertEqual("60", parser["com.linuxmint.report"]["automonitor-seconds"])
        self.assertIn(f"{override.relative_to(ROOT)} usr/share/glib-2.0/schemas/",
                      (ROOT / "debian/install").read_text(encoding="utf-8"))

    def test_nemo_shows_thumbnails_on_phones_and_network_shares(self) -> None:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read(ROOT / "usr/share/glib-2.0/schemas/60_caramos-ota.gschema.override", encoding="utf-8")
        self.assertEqual("'always'", parser["org.nemo.preferences"]["show-image-thumbnails"])
        iso = ROOT.resolve().parents[1] / "config/includes.chroot/usr/share/glib-2.0/schemas/99_caramos.gschema.override"
        if iso.exists():  # the source package has no config/
            self.assertNotIn("show-image-thumbnails", iso.read_text(encoding="utf-8"),
                             "the ISO's 99_ override would win over this 60_ one")


if __name__ == "__main__":
    unittest.main()

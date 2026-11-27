"""Automatic updates, the system's side: the setting, what makes an update wait, the unattended run, the CLI, the
migrations' "unattended" classification and the packaging (caramos_ota.auto_update)."""

from __future__ import annotations

import fcntl
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from xml.etree import ElementTree

from caramos_ota import auto_update, cli
from caramos_ota.diskspace import MIB, Shortage
from caramos_ota_update import cli as update_cli
from caramos_ota_update.registry import (
    ANYTIME,
    NOBODY_LOGGED_IN,
    MigrationRegistryError,
    _descriptor,
    discover_migrations,
)

ROOT = Path(__file__).parents[1]
DIST = ROOT / "usr/lib/python3/dist-packages"
MIGRATIONS = DIST / "caramos_ota_update/migrations"

UPDATE = {"release": "1.4.1", "current_version": "1.4.0", "migration_ids": ["20261123100000_automatic_updates"],
          "packages": [{"name": "CaramOS tự cập nhật", "name_en": "CaramOS updates itself"}]}


# What CaramOS 1.5.1 brought to computers on 1.5.0.
RELEASE_1_5_1 = {
    "20261123120000_hidden_password_typing", "20261123120100_desktop_shortcuts_anywhere",
    "20261124100000_show_desktop_button", "20261124100100_xfce_super_d_super_e",
    "20261124100200_print_screen_to_clipboard", "20261124100300_xfce_event_sounds",
    "20261124120000_desktop_icon_labels", "20261124130000_install_fastfetch", "20261124140000_show_trash_on_desktop",
    "20261124170000_tray_icons_follow_theme", "20261124180000_tray_icons_keep_their_place",
    "20261125090000_fcitx5_tray_shows_input_method",
}


def plan(*migrations) -> SimpleNamespace:
    return SimpleNamespace(migrations=list(migrations), target_version="1.4.1")


def migration(migration_id: str, unattended: str = ANYTIME, desktops: tuple[str, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(migration_id=migration_id, unattended=unattended, desktops=desktops)


class SettingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-r", str(self.tmp)], check=False))
        self.path = self.tmp / "etc/caramos-ota/auto-update.conf"

    def write(self, text: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(text, encoding="utf-8")

    def test_without_the_file_automatic_updates_are_on(self) -> None:
        self.assertIsNone(auto_update.read_setting(self.path))
        self.assertTrue(auto_update.is_enabled(self.path))

    def test_the_file_turns_them_off_or_on(self) -> None:
        for text, expected in (("AUTO_UPDATE=no\n", False), ("AUTO_UPDATE=yes\n", True), ('AUTO_UPDATE="No"\n', False),
                               ("# comment\nAUTO_UPDATE = off\n", False), ("AUTO_UPDATE=1\n", True),
                               ("AUTO_UPDATE=yes\nAUTO_UPDATE=no\n", False)):
            with self.subTest(text=text):
                self.write(text)
                self.assertIs(expected, auto_update.is_enabled(self.path))

    def test_a_value_it_cannot_read_leaves_them_on(self) -> None:
        for text in ("AUTO_UPDATE=maybe\n", "OTHER=no\n", "", "\xff"):
            with self.subTest(text=text):
                self.write(text)
                self.assertTrue(auto_update.is_enabled(self.path))

    def test_set_enabled_writes_a_file_everyone_can_read(self) -> None:
        auto_update.set_enabled(False, self.path)
        self.assertFalse(auto_update.is_enabled(self.path))
        self.assertEqual(0o644, self.path.stat().st_mode & 0o777)
        self.assertIn("AUTO_UPDATE=no\n", self.path.read_text(encoding="utf-8"))
        auto_update.set_enabled(True, self.path)
        self.assertTrue(auto_update.is_enabled(self.path))
        self.assertEqual(["auto-update.conf"], [entry.name for entry in self.path.parent.iterdir()])

    def test_change_setting_says_who_in_the_log(self) -> None:
        with mock.patch.object(auto_update, "log_info") as log:
            auto_update.change_setting(False, "caram (Update Center)", self.path)
        log.assert_called_once_with("Automatic updates turned off by caram (Update Center)")

    def test_the_caller_is_the_account_behind_pkexec_or_sudo(self) -> None:
        name = auto_update.pwd.getpwuid(os.getuid()).pw_name
        self.assertEqual(name, auto_update.caller({"PKEXEC_UID": str(os.getuid())}))
        self.assertEqual(name, auto_update.caller({"SUDO_UID": str(os.getuid())}))
        self.assertEqual("root", auto_update.caller({}))
        self.assertEqual("uid 4000000", auto_update.caller({"PKEXEC_UID": "4000000"}))

    def test_the_helper_takes_on_or_off_from_root_only(self) -> None:
        with mock.patch("builtins.print"):
            self.assertEqual(2, auto_update.helper_main([]))
            self.assertEqual(2, auto_update.helper_main(["maybe"]))
            with mock.patch.object(auto_update.os, "geteuid", return_value=1000):
                self.assertEqual(2, auto_update.helper_main(["off"]))
        with mock.patch.object(auto_update.os, "geteuid", return_value=0), \
                mock.patch("caramos_ota.logging_utils.init_log"), \
                mock.patch.object(auto_update, "SETTINGS_FILE", self.path), \
                mock.patch.dict(os.environ, {"PKEXEC_UID": str(os.getuid())}), \
                mock.patch.object(auto_update, "log_info") as log:
            self.assertEqual(0, auto_update.helper_main(["off"]))
            self.assertFalse(auto_update.is_enabled())
        self.assertFalse(auto_update.is_enabled(self.path))
        self.assertIn("(Update Center)", log.call_args.args[0])


class ConditionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-r", str(self.tmp)], check=False))

    def file(self, name: str, text: str) -> Path:
        path = self.tmp / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_the_live_usb_and_an_overlay_root(self) -> None:
        self.assertTrue(auto_update.live_session(self.file("live", "BOOT_IMAGE=/casper/vmlinuz boot=casper quiet\n")))
        self.assertFalse(auto_update.live_session(self.file("disk", "BOOT_IMAGE=/boot/vmlinuz root=UUID=x ro\n")))
        self.assertFalse(auto_update.live_session(self.tmp / "missing"))
        frozen = "overlayroot / overlay rw,relatime,lowerdir=/media/root-ro 0 0\n/dev/vda1 /media/root-ro ext4 ro 0 0\n"
        self.assertTrue(auto_update.overlay_root(self.file("frozen", frozen)))
        self.assertFalse(auto_update.overlay_root(self.file("normal", "/dev/vda3 / ext4 rw,relatime 0 0\n")))

    def test_a_metered_connection(self) -> None:
        for output, expected in (("u 1\n", True), ("u 3\n", True), ("u 4\n", False), ("u 2\n", False), ("u 0\n", False)):
            with self.subTest(output=output):
                run = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout=output))
                self.assertIs(expected, auto_update.metered(run))
        self.assertFalse(auto_update.metered(mock.Mock(return_value=SimpleNamespace(returncode=1, stdout=""))))
        self.assertFalse(auto_update.metered(mock.Mock(side_effect=OSError)))
        command = mock.Mock(return_value=SimpleNamespace(returncode=0, stdout="u 4\n"))
        auto_update.metered(command)
        self.assertEqual(["busctl", "get-property", "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager",
                          "org.freedesktop.NetworkManager", "Metered"], command.call_args.args[0])

    def supply(self, name: str, **values: str) -> None:
        for key, value in values.items():
            self.file(f"power/{name}/{key}", value + "\n")

    def test_battery_under_half_without_the_charger(self) -> None:
        power = self.tmp / "power"
        self.assertFalse(auto_update.battery_low(power))   # no folder: a desktop computer
        self.supply("BAT0", type="Battery", status="Discharging", capacity="30")
        self.assertTrue(auto_update.battery_low(power))
        self.supply("AC", type="Mains", online="1")
        self.assertFalse(auto_update.battery_low(power))
        self.supply("AC", type="Mains", online="0")
        self.assertTrue(auto_update.battery_low(power))
        self.supply("BAT0", type="Battery", status="Discharging", capacity="60")
        self.assertFalse(auto_update.battery_low(power))
        self.supply("BAT0", type="Battery", status="Charging", capacity="10")
        self.assertFalse(auto_update.battery_low(power))

    def test_a_mouse_battery_does_not_count(self) -> None:
        self.supply("hidpp_battery_0", type="Battery", scope="Device", status="Discharging", capacity="5")
        self.assertFalse(auto_update.battery_low(self.tmp / "power"))
        self.supply("BAT1", type="Battery", status="Discharging", capacity="80")
        self.assertFalse(auto_update.battery_low(self.tmp / "power"))

    def hold(self, path: Path, how: str) -> subprocess.Popen:
        """A process of its own that holds the lock, as APT, dpkg or another caramos-ota does."""

        code = ("import fcntl, os, sys, time\n"
                "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT)\n"
                + ("fcntl.lockf(fd, fcntl.LOCK_EX)\n" if how == "fcntl" else "fcntl.flock(fd, fcntl.LOCK_EX)\n")
                + "print('locked', flush=True)\ntime.sleep(30)\n")
        holder = subprocess.Popen([sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, text=True)
        self.addCleanup(self.stop, holder)
        self.assertEqual("locked", holder.stdout.readline().strip())
        return holder

    @staticmethod
    def stop(holder: subprocess.Popen) -> None:
        holder.kill()
        holder.wait()
        holder.stdout.close()

    def test_apt_and_dpkg_locks(self) -> None:
        lock = self.file("lock-frontend", "")
        self.assertFalse(auto_update.apt_busy((lock, self.tmp / "missing")))
        holder = self.hold(lock, "fcntl")
        self.assertTrue(auto_update.apt_busy((self.tmp / "missing", lock)))
        holder.kill()
        holder.wait()
        self.assertFalse(auto_update.apt_busy((lock,)))
        self.assertFalse(auto_update.apt_busy(()))
        # Asking took nothing: another process can take the lock at once.
        fd = os.open(lock, os.O_RDWR)
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.close(fd)

    def test_the_ota_lock_of_another_run(self) -> None:
        lock = self.file("lock", "")
        self.assertFalse(auto_update.ota_busy(lock))
        self.assertFalse(auto_update.ota_busy(self.tmp / "missing"))
        self.hold(lock, "flock")
        self.assertTrue(auto_update.ota_busy(lock))

    def test_low_disk_uses_the_free_space_check_of_driver_check(self) -> None:
        with mock.patch.object(auto_update, "shortages", return_value=[Shortage("/", 1536 * MIB, 900 * MIB)]) as check:
            self.assertEqual([Shortage("/", 1536 * MIB, 900 * MIB)], auto_update.low_disk(Path("/var/cache/apt/archives")))
        check.assert_called_once_with(auto_update.OTA_NEEDS, "/var/cache/apt/archives", 0)
        with mock.patch.object(auto_update, "shortages", side_effect=OSError):
            self.assertEqual([], auto_update.low_disk())

    def test_open_desktops_are_graphical_sessions_of_users(self) -> None:
        sessions = {
            "c1": "Name=caram\nType=x11\nClass=user\nState=active\n",
            "c2": "Name=lightdm\nType=x11\nClass=greeter\nState=online\n",
            "3": "Name=caram\nType=tty\nClass=user\nState=active\n",
            "c4": "Name=minh\nType=x11\nClass=user\nState=closing\n",
            "c5": "Name=lan\nType=wayland\nClass=user\nState=online\n",
        }

        def run(args, **_kwargs):
            if args[1] == "list-sessions":
                return SimpleNamespace(returncode=0, stdout="".join(f"{sid} 1000 x seat0 tty7 active no -\n"
                                                                    for sid in sessions))
            return SimpleNamespace(returncode=0, stdout=sessions[args[2]])

        self.assertEqual(["caram", "lan"], auto_update.desktop_sessions(run))
        self.assertIsNone(auto_update.desktop_sessions(mock.Mock(return_value=SimpleNamespace(returncode=1, stdout=""))))
        self.assertIsNone(auto_update.desktop_sessions(mock.Mock(side_effect=OSError)))

    def test_changes_to_open_desktops_count_only_this_edition(self) -> None:
        pending = plan(migration("1_files", ANYTIME), migration("2_panel", NOBODY_LOGGED_IN, ("cinnamon",)),
                       migration("3_whisker", NOBODY_LOGGED_IN, ("xfce",)), migration("4_unknown", NOBODY_LOGGED_IN))
        self.assertEqual(["2_panel", "4_unknown"], auto_update.changes_open_desktops(pending, "cinnamon"))
        self.assertEqual(["3_whisker", "4_unknown"], auto_update.changes_open_desktops(pending, "xfce"))

    def test_update_key(self) -> None:
        self.assertEqual("1.4.1:20261123100000_automatic_updates", auto_update.update_key(UPDATE))
        self.assertEqual("?:", auto_update.update_key(None))
        self.assertEqual(auto_update.update_key(UPDATE), auto_update.update_key(dict(UPDATE, detected_at="manual")))

    def test_system_language_and_the_restart_marker(self) -> None:
        self.assertEqual("vi", auto_update.system_language(self.file("vi", 'LANG="vi_VN.UTF-8"\n')))
        self.assertEqual("en", auto_update.system_language(self.file("en", "LANG=en_US.UTF-8\nLC_PAPER=vi_VN.UTF-8\n")))
        self.assertEqual("en", auto_update.system_language(self.tmp / "missing"))
        marker = self.tmp / "reboot-required"
        self.assertIsNone(auto_update.reboot_marker(marker))
        self.file("reboot-required", "*** System restart required ***\n")
        self.assertEqual("", auto_update.reboot_marker(marker))
        self.file("reboot-required.pkgs", "linux-image-6.14.0-40-generic\n")
        self.assertEqual("linux-image-6.14.0-40-generic", auto_update.reboot_marker(marker))


class SkipReasonTests(unittest.TestCase):
    """Each reason, in the order skip_reason() asks; all the checks patched to "fine" first."""

    def setUp(self) -> None:
        self.checks = {"live_session": False, "overlay_root": False, "ota_busy": False, "apt_busy": False,
                       "metered": False, "battery_low": False, "low_disk": [], "desktop_sessions": ["caram"]}
        for name, value in self.checks.items():
            patcher = mock.patch.object(auto_update, name, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        self.plan = plan(migration("20261123100000_automatic_updates"))

    def reason(self, state=None, pending=None):
        result = auto_update.skip_reason(UPDATE, pending or self.plan, state or {})
        return result[0] if result else None

    def test_nothing_stops_an_update_of_anytime_changes_while_someone_works(self) -> None:
        self.assertIsNone(self.reason())
        self.desktop_sessions.assert_not_called()

    def test_each_reason(self) -> None:
        for check, value, reason in (("live_session", True, auto_update.LIVE), ("overlay_root", True, auto_update.OVERLAY),
                                     ("ota_busy", True, auto_update.OTA_BUSY), ("apt_busy", True, auto_update.APT_BUSY),
                                     ("metered", True, auto_update.METERED), ("battery_low", True, auto_update.BATTERY),
                                     ("low_disk", [Shortage("/", 1536 * MIB, 512 * MIB)], auto_update.DISK)):
            with self.subTest(check=check):
                getattr(self, check).return_value = value
                self.assertEqual(reason, self.reason())
                getattr(self, check).return_value = self.checks[check]

    def test_the_disk_detail_says_how_much_is_missing(self) -> None:
        self.low_disk.return_value = [Shortage("/", 1536 * MIB, 512 * MIB)]
        self.assertEqual((auto_update.DISK, "/: 512 MiB free, 1536 MiB needed"),
                         auto_update.skip_reason(UPDATE, self.plan, {}))

    def test_changes_to_open_desktops_wait_until_nobody_is_logged_in(self) -> None:
        pending = plan(migration("20261105120000_keep_lotus_settings", NOBODY_LOGGED_IN))
        self.assertEqual(auto_update.IN_USE, self.reason(pending=pending))
        self.desktop_sessions.return_value = []
        self.assertIsNone(self.reason(pending=pending))
        self.desktop_sessions.return_value = None   # logind cannot tell: wait
        self.assertEqual(auto_update.IN_USE, self.reason(pending=pending))

    def test_a_1_5_0_computer_in_use_takes_1_5_1_by_itself(self) -> None:
        # 1.5.1 had two migrations that waited for nobody to be logged in (Show desktop, the Trash): 1.5.0 computers
        # in use did not update by themselves. They leave the open desktop for each user's next login now
        # (caramos_ota_update.deferred), so the whole update installs while someone works.
        catalog = discover_migrations()
        pending = plan(*[item for item in catalog if item.migration_id in RELEASE_1_5_1])
        self.assertEqual(sorted(RELEASE_1_5_1), [item.migration_id for item in pending.migrations])
        for desktop in ("cinnamon", "xfce"):
            with self.subTest(desktop=desktop), mock.patch.dict(os.environ, {"CARAMOS_OTA_DESKTOP": desktop}):
                self.assertEqual([], auto_update.changes_open_desktops(pending))
                self.assertIsNone(self.reason(pending=pending))
        self.desktop_sessions.assert_not_called()

    def test_the_same_update_is_not_tried_again_after_it_failed(self) -> None:
        failed = {auto_update.STATUS_KEY: {"outcome": auto_update.FAILED, "update": auto_update.update_key(UPDATE)}}
        self.assertEqual(auto_update.FAILED_BEFORE, self.reason(failed))
        other = {auto_update.STATUS_KEY: {"outcome": auto_update.FAILED, "update": "1.4.0:x"}}
        self.assertIsNone(self.reason(other))
        skipped = {auto_update.STATUS_KEY: {"outcome": auto_update.SKIPPED, "update": auto_update.update_key(UPDATE)}}
        self.assertIsNone(self.reason(skipped))


class RunTests(unittest.TestCase):
    """caramos-ota --auto-upgrade with its state, result and the update itself in a temporary folder."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-r", str(self.tmp)], check=False))
        self.state = {"schema": 2, "available_update": dict(UPDATE), "transactions": []}
        self.saved = []
        self.patches = [
            mock.patch.object(auto_update, "is_enabled", return_value=True),
            mock.patch("caramos_ota.state.load_state", side_effect=lambda: json.loads(json.dumps(self.state))),
            mock.patch("caramos_ota.state.save_state", side_effect=self.save),
            mock.patch("caramos_ota.release.detect_caramos",
                       return_value=SimpleNamespace(version="1.4.0", codename="noble", channel="stable")),
            mock.patch("caramos_ota.manifest.resolve_update_plan",
                       return_value=plan(migration("20261123100000_automatic_updates"))),
            mock.patch.object(auto_update, "skip_reason", return_value=None),
            mock.patch.object(auto_update, "RESULT_FILE", self.tmp / "auto-update.json"),
            mock.patch.object(auto_update, "REBOOT_REQUIRED", self.tmp / "reboot-required"),
            mock.patch.object(auto_update, "log_info"),
            mock.patch.object(auto_update, "log_warn"),
            mock.patch.object(auto_update, "log_error"),
            mock.patch("builtins.print"),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def save(self, state) -> None:
        self.state = json.loads(json.dumps(state))
        self.saved.append(self.state)

    def last_try(self) -> dict:
        return self.state[auto_update.STATUS_KEY]

    def test_off_does_nothing(self) -> None:
        auto_update.is_enabled.return_value = False
        with mock.patch.object(auto_update, "run_upgrade") as upgrade:
            self.assertEqual(0, auto_update.run())
        upgrade.assert_not_called()
        self.assertEqual([], self.saved)
        self.assertFalse((self.tmp / "auto-update.json").exists())

    def test_without_a_waiting_update_it_ends(self) -> None:
        self.state["available_update"] = None
        with mock.patch.object(auto_update, "run_upgrade") as upgrade:
            self.assertEqual(0, auto_update.run())
        upgrade.assert_not_called()

    def test_a_reason_to_wait_is_recorded_and_the_update_left_to_the_update_center(self) -> None:
        auto_update.skip_reason.return_value = (auto_update.METERED, "the connection is metered")
        with mock.patch.object(auto_update, "run_upgrade") as upgrade:
            self.assertEqual(0, auto_update.run())
        upgrade.assert_not_called()
        self.assertEqual(auto_update.SKIPPED, self.last_try()["outcome"])
        self.assertEqual(auto_update.METERED, self.last_try()["reason"])
        self.assertEqual(auto_update.update_key(UPDATE), self.last_try()["update"])
        self.assertFalse((self.tmp / "auto-update.json").exists())

    def test_apt_busy_tries_again_later(self) -> None:
        auto_update.skip_reason.return_value = (auto_update.APT_BUSY, "APT or dpkg is busy")
        self.assertEqual(auto_update.EXIT_RETRY, auto_update.run())
        auto_update.skip_reason.return_value = (auto_update.OTA_BUSY, "another run")
        self.assertEqual(auto_update.EXIT_RETRY, auto_update.run())

    def test_an_installed_update_tells_the_users(self) -> None:
        def upgrade():
            (self.tmp / "reboot-required").write_text("*** System restart required ***\n", encoding="utf-8")
            (self.tmp / "reboot-required.pkgs").write_text("linux-image-6.14.0-40-generic\n", encoding="utf-8")
            return 0, "Update complete.\n"

        with mock.patch.object(auto_update, "run_upgrade", side_effect=upgrade):
            self.assertEqual(0, auto_update.run())
        result = json.loads((self.tmp / "auto-update.json").read_text(encoding="utf-8"))
        self.assertEqual(auto_update.DONE, result["outcome"])
        self.assertEqual(("1.4.0", "1.4.1"), (result["from_version"], result["to_version"]))
        self.assertTrue(result["restart"])
        self.assertEqual(UPDATE, result["update"])
        self.assertEqual(auto_update.update_key(UPDATE), result["update_key"])
        self.assertEqual("Update complete.\n", result["output"])
        self.assertTrue(result["id"])
        self.assertEqual(0o644, (self.tmp / "auto-update.json").stat().st_mode & 0o777)
        self.assertEqual([auto_update.RUNNING, auto_update.DONE], [state[auto_update.STATUS_KEY]["outcome"]
                                                                  for state in self.saved])

    def test_a_restart_needed_before_the_update_is_not_its_restart(self) -> None:
        (self.tmp / "reboot-required").write_text("*** System restart required ***\n", encoding="utf-8")
        with mock.patch.object(auto_update, "run_upgrade", return_value=(0, "")):
            auto_update.run()
        self.assertFalse(json.loads((self.tmp / "auto-update.json").read_text(encoding="utf-8"))["restart"])

    def test_a_failed_update_leaves_its_output_for_the_failure_page(self) -> None:
        with mock.patch.object(auto_update, "run_upgrade", return_value=(1, "x" * (auto_update.OUTPUT_LIMIT + 5))):
            self.assertEqual(1, auto_update.run())
        result = json.loads((self.tmp / "auto-update.json").read_text(encoding="utf-8"))
        self.assertEqual(auto_update.FAILED, result["outcome"])
        self.assertEqual(1, result["exit_code"])
        self.assertEqual(auto_update.OUTPUT_LIMIT, len(result["output"]))
        self.assertEqual(auto_update.FAILED, self.last_try()["outcome"])

    def test_a_manual_update_that_took_the_lock_first_means_try_again(self) -> None:
        with mock.patch.object(auto_update, "run_upgrade", return_value=(7, "Another operation")):
            self.assertEqual(auto_update.EXIT_RETRY, auto_update.run())
        self.assertFalse((self.tmp / "auto-update.json").exists())
        self.assertEqual(auto_update.OTA_BUSY, self.last_try()["reason"])

    def test_nothing_left_to_install(self) -> None:
        with mock.patch("caramos_ota.manifest.resolve_update_plan", return_value=SimpleNamespace(migrations=[],
                                                                                                 target_version="1.4.0")), \
                mock.patch.object(auto_update, "run_upgrade") as upgrade:
            self.assertEqual(0, auto_update.run())
        upgrade.assert_not_called()

    def test_status_lines(self) -> None:
        lines = auto_update.status_lines({auto_update.STATUS_KEY: {"at": "2026-11-23T10:00", "outcome": "skipped",
                                                                   "reason": "metered", "release": "1.4.1"}})
        self.assertEqual(["Automatic updates:    on",
                          "Last automatic try:   2026-11-23T10:00 skipped (metered), CaramOS 1.4.1"], lines)


class UnattendedRunTests(unittest.TestCase):
    def test_the_update_runs_without_questions_and_holds_off_shutdown(self) -> None:
        inhibitor = mock.Mock(pid=4242)
        with mock.patch.object(auto_update.subprocess, "Popen", return_value=inhibitor) as popen, \
                mock.patch.object(auto_update.subprocess, "run",
                                  return_value=SimpleNamespace(returncode=0, stdout="Update complete.\n")) as run, \
                mock.patch.object(auto_update.os, "killpg") as killpg:
            self.assertEqual((0, "Update complete.\n"), auto_update.run_upgrade("vi"))
        argv = popen.call_args.args[0]
        self.assertEqual(["systemd-inhibit", "--what=shutdown", "--mode=block", "--who=CaramOS"], argv[:4])
        self.assertIn(f"--why={auto_update.INHIBIT_WHY['vi']}", argv)
        self.assertEqual(["/usr/bin/caramos-ota", "--upgrade", "--yes", "--unattended"], run.call_args.args[0])
        env = run.call_args.kwargs["env"]
        for name, value in auto_update.UNATTENDED_ENV.items():
            self.assertEqual(value, env[name])
        self.assertIs(subprocess.DEVNULL, run.call_args.kwargs["stdin"])
        killpg.assert_called_once_with(4242, auto_update.signal.SIGTERM)

    def test_without_logind_the_update_still_runs(self) -> None:
        with mock.patch.object(auto_update.subprocess, "Popen", side_effect=OSError("no systemd-inhibit")), \
                mock.patch.object(auto_update.subprocess, "run",
                                  return_value=SimpleNamespace(returncode=0, stdout="")), \
                mock.patch.object(auto_update, "log_warn"):
            self.assertEqual((0, ""), auto_update.run_upgrade("en"))

    def test_dpkg_keeps_configuration_files_an_administrator_changed(self) -> None:
        self.assertEqual("noninteractive", auto_update.UNATTENDED_ENV["DEBIAN_FRONTEND"])
        shipped = ROOT / auto_update.APT_CONFIG.lstrip("/")
        text = shipped.read_text(encoding="utf-8")
        self.assertIn('"--force-confdef";', text)
        self.assertIn('"--force-confold";', text)
        if subprocess.run(["which", "apt-config"], capture_output=True).returncode == 0:
            dump = subprocess.run(["apt-config", "dump"], env=dict(os.environ, APT_CONFIG=str(shipped)),
                                  capture_output=True, text=True).stdout
            self.assertIn('DPkg::Options:: "--force-confold";', dump)


class CliTests(unittest.TestCase):
    def test_the_options(self) -> None:
        parser = cli.build_parser()
        self.assertEqual("off", parser.parse_args(["--auto-update", "off"]).auto_update)
        self.assertEqual("auto_update", cli.selected_action(parser.parse_args(["--auto-update", "on"])))
        self.assertEqual("auto_upgrade", cli.selected_action(parser.parse_args(["--auto-upgrade"])))
        self.assertEqual("upgrade", cli.selected_action(parser.parse_args(["--upgrade", "--yes", "--unattended"])))
        with self.assertRaises(SystemExit), mock.patch("sys.stderr"):
            parser.parse_args(["--auto-update", "maybe"])

    def test_auto_update_changes_the_setting_without_the_ota_lock(self) -> None:
        with mock.patch.object(cli, "require_root"), mock.patch.object(cli, "init_log"), \
                mock.patch.object(cli, "acquire_lock") as lock, \
                mock.patch.object(cli.auto_update, "change_setting") as change, mock.patch("builtins.print"):
            self.assertEqual(0, cli.main(["--auto-update", "off"]))
        lock.assert_not_called()
        self.assertIs(False, change.call_args.args[0])

    def test_auto_upgrade_runs_the_automatic_update_without_the_lock(self) -> None:
        with mock.patch.object(cli, "require_root"), mock.patch.object(cli, "init_log"), \
                mock.patch.object(cli, "acquire_lock") as lock, mock.patch.object(cli, "log_info"), \
                mock.patch.object(cli.auto_update, "run", return_value=75):
            self.assertEqual(75, cli.main(["--auto-upgrade"]))
        lock.assert_not_called()

    def test_an_unattended_update_tells_the_migration_runner(self) -> None:
        with mock.patch.object(cli, "current_lock_fd", return_value=9), \
                mock.patch.object(cli.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run, \
                mock.patch.object(cli, "log_info"):
            cli.run_migration_update("1.4.1", dry_run=False, unattended=True)
            self.assertIn("--unattended", run.call_args.args[0])
            cli.run_migration_update("1.4.1", dry_run=False)
            self.assertNotIn("--unattended", run.call_args.args[0])

    def test_the_restart_after_the_self_update_keeps_unattended(self) -> None:
        release = SimpleNamespace(version="1.4.0")
        with mock.patch.object(cli, "require_root"), mock.patch.object(cli, "init_log"), \
                mock.patch.object(cli, "acquire_lock"), mock.patch.object(cli, "log_info"), \
                mock.patch.object(cli, "load_state", return_value={}), mock.patch.object(cli, "save_state"), \
                mock.patch.object(cli, "detect_caramos", return_value=release), mock.patch.object(cli, "banner"), \
                mock.patch.object(cli, "verify_repo"), mock.patch.object(cli, "apt_update"), \
                mock.patch.object(cli.zalo_update, "resume_in_background"), \
                mock.patch.object(cli, "self_update_ota_if_needed") as self_update, \
                mock.patch.object(cli, "detect_updates", return_value=(SimpleNamespace(release="1.4.1"), ["x"])), \
                mock.patch.object(cli, "do_upgrade") as upgrade, mock.patch("builtins.print"):
            cli.main(["--upgrade", "--yes", "--unattended"])
        self.assertEqual(["caramos-ota", "--upgrade", "--yes", "--skip-self-update", "--unattended"],
                         self_update.call_args.kwargs["reexec_args"])
        self.assertTrue(upgrade.call_args.kwargs["unattended"])

    def test_the_migration_runner_passes_it_to_the_migrations(self) -> None:
        contexts = []
        with mock.patch.object(update_cli, "init_log"), mock.patch.object(update_cli, "acquire_lock"), \
                mock.patch.object(update_cli, "log_info"), \
                mock.patch.object(update_cli, "_read_current_version", return_value="1.4.0"), \
                mock.patch.object(update_cli, "_current_release_values", return_value={}), \
                mock.patch.object(update_cli, "MigrationRunner",
                                  side_effect=lambda context: contexts.append(context) or mock.Mock()):
            update_cli.main(["--unattended", "--lock-fd", "9"])
            update_cli.main(["--lock-fd", "9"])
        self.assertEqual([True, False], [context.unattended for context in contexts])


class ClassificationTests(unittest.TestCase):
    """Which migrations an automatic update runs while people work (the manifests' "unattended")."""

    # Each changes what someone sees on an open desktop: see their docstrings and caramos_ota.auto_update.
    WAIT_FOR_NOBODY = {
        "20260715090258_install_control_center",
        "20260803120000_apply_three_dock_taskbar",
        "20260804223346_change_default_wallpaper",
        "20260805111120_update_taskbar_pins_cleanup_desktop",
        "20260808090000_restore_power_profiles_daemon",
        "20261009120000_add_app_center_launcher",
        "20261010120100_lighten_desktop_session",
        "20261012180000_add_help_applet",
        "20261018120000_restore_taskbar_after_cinnamon_update",
        "20261105120000_keep_lotus_settings",
    }

    def test_every_timestamp_migration_says_when_it_may_run(self) -> None:
        for manifest in sorted(MIGRATIONS.glob("2*/manifest.json")):
            with self.subTest(migration=manifest.parent.name):
                raw = json.loads(manifest.read_text(encoding="utf-8"))
                self.assertIn(raw.get("unattended"), (ANYTIME, NOBODY_LOGGED_IN))

    def test_the_migrations_that_change_open_desktops_wait(self) -> None:
        catalog = {item.migration_id: item for item in discover_migrations()}
        waiting = {migration_id for migration_id, item in catalog.items()
                   if not item.legacy and item.unattended == NOBODY_LOGGED_IN}
        self.assertEqual(self.WAIT_FOR_NOBODY, waiting)
        self.assertTrue(all(item.unattended == NOBODY_LOGGED_IN for item in catalog.values() if item.legacy))

    def test_no_new_migration_waits_for_nobody_to_be_logged_in(self) -> None:
        # Closed at 1.3.4: the update at start-up (caramos-ota-boot-update.service) happens once, to computers on 1.3.3
        # or older, and the start-up screen tells users so (owner, 2026-11-27). A new migration leaves what shows for
        # the next login instead (caramos_ota_update.deferred, MIGRATIONS.md).
        last = max(self.WAIT_FOR_NOBODY)
        later = [item.migration_id for item in discover_migrations()
                 if not item.legacy and item.migration_id > last and item.unattended == NOBODY_LOGGED_IN]
        self.assertEqual([], later)
        self.assertEqual("20261105120000_keep_lotus_settings", last)

    def test_a_manifest_without_it_waits_and_a_wrong_value_is_refused(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-r", str(tmp)], check=False))
        folder = tmp / "20991231000000_test"
        folder.mkdir()
        (folder / "migration.py").write_text('DESCRIPTION = "test"\n\ndef run(context):\n    pass\n', encoding="utf-8")
        manifest = {"schema": 2, "codename": "noble", "title": "t", "summary": "s"}
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.assertEqual(NOBODY_LOGGED_IN, _descriptor(folder).unattended)
        (folder / "manifest.json").write_text(json.dumps(dict(manifest, unattended=ANYTIME)), encoding="utf-8")
        self.assertEqual(ANYTIME, _descriptor(folder).unattended)
        (folder / "manifest.json").write_text(json.dumps(dict(manifest, unattended="sometimes")), encoding="utf-8")
        with self.assertRaises(MigrationRegistryError):
            _descriptor(folder)


def load_migration(name: str):
    return importlib.import_module(f"caramos_ota_update.migrations.{name}.migration")


class DeferredSessionStepTests(unittest.TestCase):
    """What "anytime" migrations leave for the next login in an automatic update."""

    def context(self, unattended: bool):
        return SimpleNamespace(dry_run=False, unattended=unattended, log=mock.Mock())

    def test_the_start_menu_is_not_reloaded_under_someone_at_work(self) -> None:
        composing = load_migration("20261105120100_search_menu_while_composing")
        with mock.patch.object(composing.start_fcitx, "_desktop_users") as users, \
                mock.patch.object(composing.subprocess, "run") as run:
            composing._reload_in_sessions(self.context(True))
        users.assert_not_called()
        run.assert_not_called()
        # The two later Start Menu migrations reload through the same function.
        for name in ("20261105120200_start_menu_file_search_without_freeze", "20261111090000_start_menu_ctrl_scroll_icon_size"):
            source = (MIGRATIONS / name / "migration.py").read_text(encoding="utf-8")
            self.assertIn("composing._reload_in_sessions(context)", source)
            self.assertNotIn("ReloadXlet", source)

    def test_the_start_menu_is_reloaded_after_an_update_from_the_update_center(self) -> None:
        composing = load_migration("20261105120100_search_menu_while_composing")
        user = SimpleNamespace(pw_name="caram", pw_uid=1000)
        with mock.patch.object(composing.start_fcitx, "_desktop_users", return_value=[user]), \
                mock.patch.object(composing.start_fcitx, "session_environment", return_value={"DISPLAY": ":0"}), \
                mock.patch.object(composing.subprocess, "run", return_value=SimpleNamespace(returncode=0)) as run, \
                mock.patch.object(composing.time, "sleep"):
            composing._reload_in_sessions(self.context(False))
        self.assertIn("org.Cinnamon.ReloadXlet", run.call_args.args[0])

    def test_fcitx_is_not_started_in_open_sessions(self) -> None:
        start_fcitx = load_migration("20261022120000_start_fcitx_at_login")
        for unattended, calls in ((True, 0), (False, 1)):
            with self.subTest(unattended=unattended), \
                    mock.patch.object(start_fcitx, "_write_helper"), \
                    mock.patch.object(start_fcitx, "SYSTEMD_RUNTIME", ROOT), \
                    mock.patch.object(start_fcitx, "_start_in_sessions") as start:
                start_fcitx.run(self.context(unattended))
            self.assertEqual(calls, start.call_count)


class AutomaticUpdatesMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.migration = load_migration("20261123100000_automatic_updates")
        self.context = SimpleNamespace(dry_run=False, log=mock.Mock())

    def test_the_notification_unit_starts_in_the_open_sessions(self) -> None:
        files = self.migration.files_new_menu
        calls = []
        with mock.patch.object(self.migration, "UNIT_FILE", ROOT / "usr/lib/systemd/user" / self.migration.UNIT), \
                mock.patch.object(files, "_desktop_users", return_value=[("caram", 1000), ("minh", 1001)]), \
                mock.patch.object(files, "_user_manager_running", side_effect=lambda uid: uid == 1000), \
                mock.patch.object(files, "_systemctl",
                                  side_effect=lambda *args: calls.append(args) or SimpleNamespace(returncode=0, stderr="")):
            self.migration.run(self.context)
        self.assertEqual([("caram", 1000, "daemon-reload"),
                          ("caram", 1000, "start", "caramos-ota-auto-update-notify.path")], calls)

    def test_dry_run_and_a_missing_unit_change_nothing(self) -> None:
        files = self.migration.files_new_menu
        with mock.patch.object(files, "_systemctl") as systemctl:
            self.migration.run(SimpleNamespace(dry_run=True, log=mock.Mock()))
            with mock.patch.object(self.migration, "UNIT_FILE", Path("/nonexistent/unit.path")):
                self.migration.run(self.context)
        systemctl.assert_not_called()

    def test_its_notes_say_how_to_turn_it_off(self) -> None:
        raw = json.loads((MIGRATIONS / "20261123100000_automatic_updates/manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(ANYTIME, raw["unattended"])
        self.assertIn("Tự động cập nhật", raw["summary"])
        self.assertIn("Automatic updates", raw["summary_en"])
        self.assertNotIn("desktops", raw)


def unit(path: Path) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), []).append(value.strip())
    return values


class PackagingTests(unittest.TestCase):
    def test_the_daily_check_starts_the_automatic_update(self) -> None:
        check = unit(ROOT / "lib/systemd/system/caramos-ota-check.service")
        self.assertEqual(["caramos-ota-auto-update.service"], check["OnSuccess"])
        self.assertEqual(["true"], check["ProtectHome"])
        self.assertEqual(["/usr/bin/caramos-ota --check"], check["ExecStart"])
        # A shutdown during its install: SIGTERM to caramos-ota alone, which lets dpkg finish (stopping.py).
        self.assertEqual(["mixed"], check["KillMode"])
        self.assertEqual(["15min"], check["TimeoutStopSec"])
        # The upgrade that check runs must not restart the check or its timer: that restart waited for the check's
        # own stop, and the stop for it (debian/rules).
        rules = (ROOT / "debian/rules").read_text(encoding="utf-8")
        self.assertIn("dh_installsystemd --no-start --no-stop-on-upgrade caramos-ota-check.service "
                      "caramos-ota-check.timer\n", rules)
        postinst = (ROOT / "debian/postinst").read_text(encoding="utf-8")
        self.assertIn("systemctl --no-block start caramos-ota-check.timer", postinst)
        self.assertNotRegex(postinst, r"systemctl (re)?start caramos-ota-check")

    def test_the_check_runs_every_day_and_soon_after_each_start(self) -> None:
        # CaramOS 1.5.2.3: a computer that is never on at midnight, or one just installed from an older ISO, checks
        # 10 to 20 minutes after it starts instead of waiting for a midnight or for the next start.
        timer = unit(ROOT / "lib/systemd/system/caramos-ota-check.timer")
        self.assertEqual(["daily"], timer["OnCalendar"])
        self.assertEqual(["10min"], timer["OnBootSec"])
        self.assertEqual(["10min"], timer["RandomizedDelaySec"])
        # The check after a start stands for a missed midnight: a catch-up as well would check twice.
        self.assertNotIn("Persistent", timer)
        self.assertEqual(["timers.target"], timer["WantedBy"])

    def test_the_automatic_update_unit(self) -> None:
        service = unit(ROOT / "lib/systemd/system/caramos-ota-auto-update.service")
        self.assertEqual(["/usr/bin/caramos-ota --auto-upgrade"], service["ExecStart"])
        self.assertEqual(["exec"], service["Type"])   # systemd refuses RestartForceExitStatus for oneshot
        self.assertEqual([str(auto_update.EXIT_RETRY)], service["RestartForceExitStatus"])
        self.assertEqual(["mixed"], service["KillMode"])
        self.assertNotIn("ProtectHome", service)
        self.assertNotIn("SystemCallArchitectures", service)
        self.assertNotIn("WantedBy", service)
        rules = (ROOT / "debian/rules").read_text(encoding="utf-8")
        self.assertNotIn("caramos-ota-auto-update", rules)   # package upgrades neither enable nor start it

    def test_each_users_notification_units(self) -> None:
        path = unit(ROOT / "usr/lib/systemd/user/caramos-ota-auto-update-notify.path")
        self.assertEqual([str(auto_update.RESULT_FILE)], path["PathChanged"])
        self.assertEqual(["default.target"], path["WantedBy"])
        service = unit(ROOT / "usr/lib/systemd/user/caramos-ota-auto-update-notify.service")
        self.assertEqual(["/usr/bin/caramos-ota-notifier --auto-update-result"], service["ExecStart"])
        self.assertEqual(["|DISPLAY", "|WAYLAND_DISPLAY"], service["ConditionEnvironment"])

    def test_debian_install_ships_them(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        for line in ("lib/systemd/system/caramos-ota-auto-update.service lib/systemd/system/",
                     "usr/lib/systemd/user/caramos-ota-auto-update-notify.path usr/lib/systemd/user/",
                     "usr/lib/systemd/user/caramos-ota-auto-update-notify.service usr/lib/systemd/user/",
                     "usr/share/caramos-ota/auto-update usr/share/caramos-ota/"):
            self.assertIn(line + "\n", install)

    def test_only_an_administrator_changes_the_setting(self) -> None:
        tree = ElementTree.parse(ROOT / "usr/share/polkit-1/actions/net.vietnamlinuxfamily.caramos-ota.policy")
        action = next(item for item in tree.getroot() if item.get("id") == "net.vietnamlinuxfamily.caramos-ota.auto-update")
        annotations = {item.get("key"): item.text for item in action.findall("annotate")}
        self.assertEqual(auto_update.HELPER, annotations["org.freedesktop.policykit.exec.path"])
        defaults = {item.tag: item.text for item in action.find("defaults")}
        self.assertEqual({"allow_any": "no", "allow_inactive": "no", "allow_active": "auth_admin_keep"}, defaults)
        helper = ROOT / auto_update.HELPER.lstrip("/")
        self.assertTrue(os.access(helper, os.X_OK))
        source = helper.read_text(encoding="utf-8")
        self.assertTrue(source.startswith("#!/usr/bin/python3 -I\n"))
        self.assertIn("from caramos_ota.auto_update import helper_main", source)

    def test_the_helper_runs(self) -> None:
        helper = ROOT / auto_update.HELPER.lstrip("/")
        env = dict(os.environ, PYTHONPATH=str(DIST))
        result = subprocess.run([sys.executable, str(helper), "maybe"], env=env, capture_output=True, text=True,
                                timeout=60)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("on|off", result.stdout)


if __name__ == "__main__":
    unittest.main()

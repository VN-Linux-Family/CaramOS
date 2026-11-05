"""Migration 20261105120000_keep_lotus_settings: the Lotus login helper no longer copies the CaramOS defaults
over the user's own settings (tickets H-1092, H-1093), and the keyboard layout comes before Lotus in the
Fcitx profile, so every session starts typing Vietnamese instead of English (ticket H-1104)."""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from caramos_ota_update.context import MigrationContext

migration = importlib.import_module("caramos_ota_update.migrations.20261105120000_keep_lotus_settings.migration")
start_fcitx = importlib.import_module("caramos_ota_update.migrations.20261022120000_start_fcitx_at_login.migration")

ROOT = Path(__file__).parents[1]
REPO = ROOT.parents[1]

CARAMOS_PROFILE = """[Groups/0]
Name=Default
Default Layout=us
DefaultIM=lotus

[Groups/0/Items/0]
Name=lotus
Layout=

[Groups/0/Items/1]
Name=keyboard-us
Layout=

[GroupOrder]
0=Default
"""
# What Fcitx 5.1 writes back when it quits, with the English layout active.
FCITX_WRITTEN_PROFILE = """[Groups/0]
# Group Name
Name=Default
# Layout
Default Layout=us
# Default Input Method
DefaultIM=keyboard-us

[Groups/0/Items/0]
# Name
Name=lotus
# Layout
Layout=

[Groups/0/Items/1]
# Name
Name=keyboard-us
# Layout
Layout=

[GroupOrder]
0=Default
"""
NEW_PROFILE = """[Groups/0]
Name=Default
Default Layout=us
DefaultIM=lotus

[Groups/0/Items/0]
Name=keyboard-us
Layout=

[Groups/0/Items/1]
Name=lotus
Layout=

[GroupOrder]
0=Default
"""
FAKE_TOOL = """#!/bin/sh
echo "$(basename "$0") $*" >> "$CALLS"
[ "$(basename "$0")" = pgrep ] && exit "$PGREP_STATUS"
exit 0
"""


class ProfileTests(unittest.TestCase):
    def test_the_caramos_profile_gets_the_keyboard_layout_first(self) -> None:
        self.assertEqual(NEW_PROFILE, migration.reordered_profile(CARAMOS_PROFILE))
        self.assertEqual(NEW_PROFILE, migration.reordered_profile(FCITX_WRITTEN_PROFILE))
        self.assertIsNone(migration.reordered_profile(NEW_PROFILE))   # already done

    def test_a_profile_of_the_users_own_stays(self) -> None:
        unikey = CARAMOS_PROFILE.replace("[GroupOrder]", "[Groups/0/Items/2]\nName=unikey\nLayout=\n\n[GroupOrder]")
        layout = CARAMOS_PROFILE.replace("Name=keyboard-us\nLayout=", "Name=keyboard-us\nLayout=fr")
        second_group = CARAMOS_PROFILE + "\n[Groups/1]\nName=Other\nDefault Layout=us\nDefaultIM=keyboard-us\n"
        for profile in (unikey, layout, second_group, "not a profile", ""):
            self.assertIsNone(migration.reordered_profile(profile), profile[:40])

    def test_the_iso_ships_the_new_order(self) -> None:
        if not (REPO / "config").is_dir():
            self.skipTest("ISO tree is not in the source package")
        shipped = (REPO / "config/includes.chroot/etc/skel/.config/fcitx5/profile").read_text(encoding="utf-8")
        self.assertEqual(NEW_PROFILE, shipped)
        hook = (REPO / "config/hooks/live/0150-fcitx5-lotus.hook.chroot").read_text(encoding="utf-8")
        self.assertIn(NEW_PROFILE, hook)
        self.assertIn(migration.LOGIN_HELPER_SCRIPT, hook)


@unittest.skipUnless(shutil.which("sh") and shutil.which("cp"), "sh and cp are needed")
class HelperScriptTests(unittest.TestCase):
    """The new login helper, with /etc/skel and the tools it calls replaced."""

    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.skel = self.root / "skel"
        self.home = self.root / "home"
        (self.skel / ".config/fcitx5/conf").mkdir(parents=True)
        (self.skel / ".config/environment.d").mkdir(parents=True)
        (self.skel / ".config/fcitx5/config").write_text("[Behavior]\nActiveByDefault=True\n", encoding="utf-8")
        (self.skel / ".config/fcitx5/profile").write_text(NEW_PROFILE, encoding="utf-8")
        (self.skel / ".config/fcitx5/conf/lotus.conf").write_text('InputMethod="Telex"\n', encoding="utf-8")
        (self.skel / ".config/environment.d/90-fcitx5-lotus.conf").write_text("GTK_IM_MODULE=fcitx\n", encoding="utf-8")
        tools = self.root / "bin"
        tools.mkdir()
        for name in ("fcitx5", "pgrep", "killall", "ibus"):
            (tools / name).write_text(FAKE_TOOL, encoding="utf-8")
            (tools / name).chmod(0o755)
        self.script = self.root / "helper"
        self.script.write_text(migration.LOGIN_HELPER_SCRIPT.replace("/etc/skel", str(self.skel)), encoding="utf-8")
        self.script.chmod(0o755)
        self.calls = self.root / "calls"
        self.env = {**os.environ, "HOME": str(self.home), "CALLS": str(self.calls),
                    "PATH": f"{tools}:{os.environ.get('PATH', '/usr/bin:/bin')}"}

    def run_helper(self, pgrep_status: int) -> list[str]:
        self.calls.unlink(missing_ok=True)
        subprocess.run([str(self.script)], check=True, env={**self.env, "PGREP_STATUS": str(pgrep_status)}, timeout=30)
        if not self.calls.exists():
            return []
        return [line for line in self.calls.read_text(encoding="utf-8").splitlines() if line.startswith("fcitx5")]

    def test_a_new_account_gets_the_defaults(self) -> None:
        self.assertEqual(["fcitx5 -d --replace"], self.run_helper(pgrep_status=1))
        self.assertEqual('InputMethod="Telex"\n', (self.home / ".config/fcitx5/conf/lotus.conf").read_text(encoding="utf-8"))
        self.assertEqual(NEW_PROFILE, (self.home / ".config/fcitx5/profile").read_text(encoding="utf-8"))

    def test_the_users_settings_stay(self) -> None:
        self.run_helper(pgrep_status=1)
        lotus = self.home / ".config/fcitx5/conf/lotus.conf"
        lotus.write_text("InputMethod=VNI\nSpellCheck=True\n", encoding="utf-8")
        profile = self.home / ".config/fcitx5/profile"
        profile.write_text(FCITX_WRITTEN_PROFILE, encoding="utf-8")
        # The next login: Fcitx is started when it is not running, and nothing is copied.
        self.assertEqual(["fcitx5 -d"], self.run_helper(pgrep_status=1))
        self.assertEqual([], self.run_helper(pgrep_status=0))
        self.assertEqual("InputMethod=VNI\nSpellCheck=True\n", lotus.read_text(encoding="utf-8"))
        self.assertEqual(FCITX_WRITTEN_PROFILE, profile.read_text(encoding="utf-8"))


class RunTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.home = self.root / "home/minh"
        (self.home / ".config/fcitx5").mkdir(parents=True)
        self.profile = self.home / ".config/fcitx5/profile"
        self.profile.write_text(FCITX_WRITTEN_PROFILE, encoding="utf-8")
        self.user = SimpleNamespace(pw_name="minh", pw_uid=os.getuid(), pw_gid=os.getgid(), pw_dir=str(self.home))
        self.skel = self.root / "skel"
        (self.skel / ".config/fcitx5").mkdir(parents=True)
        (self.skel / ".config/fcitx5/profile").write_text(CARAMOS_PROFILE, encoding="utf-8")
        self.helper = self.root / "caramos-fcitx5-lotus-enable"
        self.helper.write_text(start_fcitx.LOGIN_HELPER_SCRIPT, encoding="utf-8")
        self.helper.chmod(0o755)
        for target, value in ((migration, ("SKEL", self.skel)), (migration, ("LOGIN_HELPER", self.helper)),
                              (migration, ("SYSTEMD_RUNTIME", self.root))):
            patcher = mock.patch.object(target, value[0], value[1])
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(start_fcitx, "_desktop_users", return_value=[self.user])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_skel_helper_and_a_logged_out_user(self) -> None:
        with mock.patch.object(start_fcitx, "session_environment", return_value=None), \
                mock.patch.object(migration, "_fcitx_pids", return_value=[]), \
                mock.patch.object(start_fcitx, "start_in_session") as start:
            migration.run(MigrationContext())
        self.assertEqual(NEW_PROFILE, self.profile.read_text(encoding="utf-8"))
        self.assertEqual(NEW_PROFILE, (self.skel / ".config/fcitx5/profile").read_text(encoding="utf-8"))
        self.assertEqual(migration.LOGIN_HELPER_SCRIPT, self.helper.read_text(encoding="utf-8"))
        start.assert_not_called()

    def test_a_running_fcitx_is_stopped_before_and_started_after(self) -> None:
        session = {"DISPLAY": ":0", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus"}
        order = []

        def stop(pids):
            order.append(("stop", self.profile.read_text(encoding="utf-8")))
            return True

        def start(context, username, environment):
            order.append(("start", self.profile.read_text(encoding="utf-8")))
            return True

        with mock.patch.object(start_fcitx, "session_environment", return_value=session), \
                mock.patch.object(migration, "_fcitx_pids", return_value=[4242]), \
                mock.patch.object(migration, "_stop", side_effect=stop), \
                mock.patch.object(start_fcitx, "start_in_session", side_effect=start) as started:
            migration.run(MigrationContext())
        self.assertEqual([("stop", FCITX_WRITTEN_PROFILE), ("start", NEW_PROFILE)], order)
        self.assertEqual("minh", started.call_args.args[1])

    def test_fcitx_that_does_not_quit_leaves_the_profile_for_later(self) -> None:
        with mock.patch.object(start_fcitx, "session_environment", return_value={"DISPLAY": ":0"}), \
                mock.patch.object(migration, "_fcitx_pids", return_value=[4242]), \
                mock.patch.object(migration, "_stop", return_value=False), \
                mock.patch.object(start_fcitx, "start_in_session") as start:
            migration.run(MigrationContext())
        self.assertEqual(FCITX_WRITTEN_PROFILE, self.profile.read_text(encoding="utf-8"))
        start.assert_not_called()

    def test_a_profile_link_is_not_followed(self) -> None:
        target = self.root / "elsewhere"
        target.write_text(CARAMOS_PROFILE, encoding="utf-8")
        self.profile.unlink()
        self.profile.symlink_to(target)
        with mock.patch.object(start_fcitx, "session_environment", return_value=None), \
                mock.patch.object(migration, "_fcitx_pids", return_value=[]):
            migration.run(MigrationContext())
        self.assertEqual(CARAMOS_PROFILE, target.read_text(encoding="utf-8"))

    def test_dry_run_changes_nothing(self) -> None:
        with mock.patch.object(start_fcitx, "session_environment", return_value=None), \
                mock.patch.object(migration, "_fcitx_pids", return_value=[]):
            migration.run(MigrationContext(dry_run=True))
        self.assertEqual(FCITX_WRITTEN_PROFILE, self.profile.read_text(encoding="utf-8"))
        self.assertEqual(start_fcitx.LOGIN_HELPER_SCRIPT, self.helper.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

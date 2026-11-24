"""The Update Center, opened by hand, asks the CaramOS PPA before it says CaramOS is up to date.

Up to 1.5.0 it only read the updater already installed. CaramOS 1.3.3 computers whose daily check kept failing were
told "CaramOS is up to date, latest version 1.3.3" while 1.5.0 was out (2026-11). Now the window runs the daily
check first (pkexec, no password), shows what it found, or says it could not check and why; a failed daily check
runs again an hour later.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import os
import re
import stat
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from caramos_ota.constants import EXIT_APT, EXIT_LOCK
from caramos_ota_notifier import app, problem, ui
from caramos_ota_notifier.constants import BUSY, CANCELLED, CHECK_HELPER, CHECKED, FAILED, OFFLINE

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / CHECK_HELPER.lstrip("/")
POLICY = ROOT / "usr/share/polkit-1/actions/net.vietnamlinuxfamily.caramos-ota.policy"
CHECK_SERVICE = ROOT / "lib/systemd/system/caramos-ota-check.service"
INSTALL = ROOT / "debian/install"

UNREACHABLE_OUTPUT = """[✓] Repository: ppa:vietnamlinuxfamily/caram-os
[✓] Updating package index...
Error: Could not reach the CaramOS update server (ppa.launchpadcontent.net).
Check the internet connection; on a company network, that address must be allowed.
"""


class FakeStack:
    def __init__(self) -> None:
        self.children = {}
        self.visible = None

    def add_named(self, child, name: str) -> None:
        self.children[name] = child

    def set_visible_child_name(self, name: str) -> None:
        self.visible = name

    def get_child_by_name(self, name: str):
        return self.children.get(name)

    def remove(self, child) -> None:
        self.children = {name: page for name, page in self.children.items() if page is not child}


class FakePage:
    def __init__(self, name: str) -> None:
        self.name = name
        self.shown = False

    def show_all(self) -> None:
        self.shown = True


class FakeThread:
    started: list = []

    def __init__(self, *, target, daemon: bool) -> None:
        self.target = target

    def start(self) -> None:
        FakeThread.started.append(self.target)


class FakeGLib:
    PRIORITY_LOW = 300

    def __init__(self) -> None:
        self.idle = []

    def idle_add(self, callback, *args, priority=None) -> int:
        self.idle.append((callback, args))
        return 1

    def timeout_add(self, _interval, callback) -> int:
        return 2


class CheckOutcomeTests(unittest.TestCase):
    def test_exit_codes_and_output_tell_what_happened(self) -> None:
        self.assertEqual(CHECKED, app.check_outcome(0, "No CaramOS OTA updates are available."))
        self.assertEqual(CANCELLED, app.check_outcome(126, ""))
        self.assertEqual(CANCELLED, app.check_outcome(127, ""))
        self.assertEqual(BUSY, app.check_outcome(EXIT_LOCK, "Another caramos-ota is running"))
        self.assertEqual(OFFLINE, app.check_outcome(EXIT_APT, UNREACHABLE_OUTPUT))
        # What an older updater prints, from apt-get, after the check installed nothing new.
        self.assertEqual(OFFLINE, app.check_outcome(EXIT_APT, "E: Failed to fetch https://ppa.launchpadcontent.net/"
                                                    "vietnamlinuxfamily/caram-os/ubuntu/dists/noble/InRelease  "
                                                    "Temporary failure resolving 'ppa.launchpadcontent.net'"))
        self.assertEqual(FAILED, app.check_outcome(EXIT_APT, "Error: Failed to update caramos-ota before checking"))

    def test_run_check_uses_the_helper_through_pkexec_with_no_arguments(self) -> None:
        process = mock.Mock(returncode=0)
        process.communicate.return_value = ("No CaramOS OTA updates are available.\n", None)
        with mock.patch.object(app.subprocess, "Popen", return_value=process) as popen:
            self.assertEqual((CHECKED, "No CaramOS OTA updates are available."), app.run_check())
        self.assertEqual(["pkexec", CHECK_HELPER], popen.call_args.args[0])

    def test_a_check_that_takes_too_long_is_left_to_finish(self) -> None:
        process = mock.Mock(returncode=None)
        process.communicate.side_effect = subprocess.TimeoutExpired(["pkexec"], 300)
        with mock.patch.object(app.subprocess, "Popen", return_value=process):
            outcome, detail = app.run_check()
        self.assertEqual(FAILED, outcome)
        self.assertIn("took too long", detail)
        process.kill.assert_not_called()   # root's process: stopping it halfway could leave a package half installed

    def test_no_check_on_a_live_usb_or_a_frozen_system_drive(self) -> None:
        auto = app.system_auto_update
        with mock.patch.object(auto, "live_session", return_value=False), \
                mock.patch.object(auto, "overlay_root", return_value=False):
            self.assertTrue(app.check_first())
        with mock.patch.object(auto, "live_session", return_value=True), \
                mock.patch.object(auto, "overlay_root", return_value=False):
            self.assertFalse(app.check_first())
        with mock.patch.object(auto, "live_session", return_value=False), \
                mock.patch.object(auto, "overlay_root", return_value=True):
            self.assertFalse(app.check_first())


class CheckingControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = FakeStack()
        self.window = mock.Mock()
        self.glib = FakeGLib()
        FakeThread.started = []
        patches = [
            mock.patch.object(app, "build_update_window", return_value=(self.window, self.stack)),
            mock.patch.object(app, "build_update_page", side_effect=lambda *a, **k: FakePage("info")),
            mock.patch.object(app, "build_progress_page",
                              side_effect=lambda *a, **k: (FakePage("progress"), mock.Mock(), mock.Mock(), mock.Mock())),
            mock.patch.object(app, "build_no_update_page", side_effect=lambda *a, **k: FakePage("no-update")),
            mock.patch.object(app, "build_checking_page", side_effect=lambda *a, **k: FakePage("checking")),
            mock.patch.object(app, "build_check_failed_page", side_effect=self.failed_page),
            mock.patch.object(app.threading, "Thread", FakeThread),
            mock.patch.object(app.auto_update_ui, "enabled", return_value=True),
            mock.patch.object(app.auto_update_ui, "waiting_reason", return_value=""),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.failed_calls = []

    def failed_page(self, outcome, detail, on_close, on_help=None, on_retry=None):
        self.failed_calls.append((outcome, detail, on_help, on_retry))
        return FakePage("check-failed")

    def controller(self):
        controller = app.UpdateWindowController(mock.Mock(), self.glib, None, {"current_version": "1.3.3"}, check=True)
        controller.show()
        return controller

    def test_opened_by_hand_it_checks_before_saying_anything(self) -> None:
        controller = self.controller()
        self.assertEqual("checking", self.stack.visible)
        self.assertEqual([controller._do_check], FakeThread.started)
        self.assertNotIn("no-update", self.stack.children)

    def test_the_check_runs_in_its_thread_and_reports_on_the_gtk_thread(self) -> None:
        controller = self.controller()
        with mock.patch.object(app, "run_check", return_value=(CHECKED, "")), \
                mock.patch.object(app, "engine_version", side_effect=["1.5.1-0caramos1", "1.5.1-0caramos1"]):
            controller._do_check()
        self.assertEqual([(controller.on_check_done, (CHECKED, "", False))], self.glib.idle)

    def test_nothing_new_after_the_check_says_up_to_date(self) -> None:
        controller = self.controller()
        with mock.patch.object(app, "resolve_available_update_now", return_value=(None, {"current_version": "1.5.1"})):
            controller.on_check_done(CHECKED, "No CaramOS OTA updates are available.")
        self.assertEqual("no-update", self.stack.visible)
        self.assertTrue(self.stack.children["no-update"].shown)
        self.assertFalse(controller.checking)

    def test_an_update_found_by_the_check_is_offered(self) -> None:
        controller = self.controller()
        update = {"release": "1.5.1", "packages": [{"name": "x"}]}
        with mock.patch.object(app, "resolve_available_update_now", return_value=(update, {})):
            controller.on_check_done(CHECKED, "")
        self.assertEqual("info", self.stack.visible)
        self.assertIn("progress", self.stack.children)
        self.assertTrue(self.stack.children["progress"].shown)
        self.assertIs(update, controller.update_info)
        self.assertIsNotNone(controller.progress_bar)

    def test_a_newer_updater_opens_the_window_again_with_its_code(self) -> None:
        controller = self.controller()
        with mock.patch.object(app.os, "execv") as execv:
            with mock.patch.object(app, "resolve_available_update_now", return_value=(None, {})):
                controller.on_check_done(CHECKED, "", engine_updated=True)
        execv.assert_called_once_with(app.NOTIFIER, [app.NOTIFIER, "--after-check"])

    def test_could_not_reach_the_server_says_so_with_try_again_and_help(self) -> None:
        controller = self.controller()
        with mock.patch.object(app.problem, "help_available", return_value=True):
            controller.on_check_done(OFFLINE, UNREACHABLE_OUTPUT)
        self.assertEqual("check-failed", self.stack.visible)
        outcome, detail, on_help, on_retry = self.failed_calls[-1]
        self.assertEqual((OFFLINE, UNREACHABLE_OUTPUT), (outcome, detail))
        self.assertIsNotNone(on_help)
        self.assertEqual(controller.start_check, on_retry)
        self.assertNotIn("no-update", self.stack.children)

    def test_try_again_checks_again_in_the_same_window(self) -> None:
        controller = self.controller()
        controller.on_check_done(BUSY, "")
        self.assertIsNone(self.failed_calls[-1][2])   # a busy updater needs no help from VNLF
        controller.start_check()
        self.assertEqual("checking", self.stack.visible)
        self.assertEqual(2, len(FakeThread.started))

    def test_the_window_can_be_closed_while_it_checks(self) -> None:
        gtk = mock.Mock()
        controller = app.UpdateWindowController(gtk, self.glib, None, {}, check=True)
        self.assertFalse(controller.close())
        gtk.main_quit.assert_called_once()

    def test_ask_for_help_sends_the_check_log(self) -> None:
        with tempfile.TemporaryDirectory() as home, mock.patch.dict(os.environ, {"XDG_CACHE_HOME": home}), \
                mock.patch.object(problem.subprocess, "Popen") as popen:
            self.assertTrue(problem.ask_for_help(UNREACHABLE_OUTPUT, None, checking=True))
            log = Path(home, "caramos-ota", "update-failure.log").read_text(encoding="utf-8")
        self.assertIn("checking for updates failed", log)
        self.assertIn("== Output of caramos-ota --check ==", log)
        self.assertIn("Could not reach the CaramOS update server", log)
        command = popen.call_args.args[0]
        self.assertEqual("The Update Center could not check for updates.", command[command.index("--message") + 1])


class MainTests(unittest.TestCase):
    def run_main(self, argv, *, local_update=None, can_check=True):
        with mock.patch.object(app, "has_display", return_value=True), \
                mock.patch.object(app, "import_gtk", return_value=(mock.Mock(), object(), mock.Mock())), \
                mock.patch.object(app, "read_available_update", return_value=None), \
                mock.patch.object(app, "read_no_update_status", return_value={}), \
                mock.patch.object(app, "resolve_available_update_now", return_value=(local_update, {})), \
                mock.patch.object(app, "check_first", return_value=can_check), \
                mock.patch.object(app.auto_update_ui, "at_login", return_value=None), \
                mock.patch.object(app, "UpdateWindowController") as controller:
            app.main(argv)
        return controller

    def test_opened_by_hand_it_checks(self) -> None:
        controller = self.run_main([])
        self.assertTrue(controller.call_args.kwargs["check"])

    def test_a_change_already_installed_is_shown_at_once(self) -> None:
        update = {"release": "1.5.1", "packages": [{"name": "x"}]}
        controller = self.run_main([], local_update=update)
        self.assertIs(update, controller.call_args.args[2])

    def test_no_second_check_after_the_window_opened_itself_again(self) -> None:
        controller = self.run_main(["--after-check"])
        self.assertFalse(controller.call_args.kwargs["check"])

    def test_no_check_where_an_update_cannot_stay(self) -> None:
        controller = self.run_main([], can_check=False)
        self.assertFalse(controller.call_args.kwargs["check"])

    def test_autostart_never_checks(self) -> None:
        controller = self.run_main(["--autostart"])
        controller.assert_not_called()


class TextTests(unittest.TestCase):
    def test_each_failure_says_what_to_do(self) -> None:
        title, text = ui.check_failed_texts(OFFLINE, can_ask_for_help=True)
        self.assertEqual("Could not check for updates", title)
        self.assertIn("could not reach the CaramOS update server", text)
        self.assertIn("Try again", text)
        self.assertIn("company network", text)
        self.assertIn("Try again", ui.check_failed_texts(BUSY, can_ask_for_help=False)[1])
        self.assertIn("administrator", ui.check_failed_texts(CANCELLED, can_ask_for_help=False)[1])
        self.assertIn("Ask for help", ui.check_failed_texts(FAILED, can_ask_for_help=True)[1])
        self.assertNotIn("Ask for help", ui.check_failed_texts(FAILED, can_ask_for_help=False)[1])
        # Never "up to date" when it could not check.
        for outcome in (OFFLINE, BUSY, CANCELLED, FAILED):
            self.assertNotIn("up to date", " ".join(ui.check_failed_texts(outcome, can_ask_for_help=True)))


class HelperTests(unittest.TestCase):
    def load_helper(self, ota_command: str):
        loader = importlib.machinery.SourceFileLoader("caramos_ota_check_helper", str(HELPER))
        spec = importlib.util.spec_from_loader("caramos_ota_check_helper", loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        module.OTA_COMMAND = ota_command
        return module

    def fake_ota(self, folder: str, script: str) -> str:
        path = Path(folder, "caramos-ota")
        path.write_text("#!/bin/sh\n" + script, encoding="utf-8")
        path.chmod(0o755)
        return str(path)

    def test_it_runs_the_check_and_passes_on_its_output_and_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            helper = self.load_helper(self.fake_ota(folder, 'echo "args: $*"; echo "to stderr" >&2; exit 5\n'))
            with redirect_stdout(io.StringIO()) as out:
                code = helper.main([])
        self.assertEqual(5, code)
        self.assertEqual("args: --check\nto stderr\n", out.getvalue())

    def test_it_takes_no_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            helper = self.load_helper(self.fake_ota(folder, "touch \"$0.ran\"\n"))
            with mock.patch("sys.stderr", io.StringIO()):
                self.assertEqual(2, helper.main(["--upgrade", "--yes"]))
            self.assertFalse(Path(folder, "caramos-ota.ran").exists())

    def test_nothing_reaches_a_closed_window_until_the_check_has_finished(self) -> None:
        # The check's own output goes to a file, never to the pipe of the window: apt-get and dpkg writing to a
        # pipe nobody reads would be killed halfway.
        source = HELPER.read_text(encoding="utf-8")
        self.assertIn("stdout=output", source)
        self.assertIn("TemporaryFile", source)

    def test_the_helper_is_executable_and_installed(self) -> None:
        self.assertTrue(HELPER.stat().st_mode & stat.S_IXUSR)
        self.assertEqual("#!/usr/bin/python3 -I", HELPER.read_text(encoding="utf-8").splitlines()[0])
        self.assertIn("usr/share/caramos-ota/check usr/share/caramos-ota/", INSTALL.read_text(encoding="utf-8").splitlines())


class PolicyAndUnitTests(unittest.TestCase):
    def test_checking_needs_no_password_for_the_person_at_the_computer_only(self) -> None:
        actions = {action.get("id"): action for action in ET.parse(POLICY).getroot().iter("action")}
        action = actions["net.vietnamlinuxfamily.caramos-ota.check"]
        defaults = {child.tag: child.text for child in action.find("defaults")}
        self.assertEqual({"allow_any": "no", "allow_inactive": "no", "allow_active": "yes"}, defaults)
        annotations = {item.get("key"): item.text for item in action.iter("annotate")}
        self.assertEqual(CHECK_HELPER, annotations["org.freedesktop.policykit.exec.path"])
        # Installing the update still needs an administrator.
        upgrade = {child.tag: child.text for child in actions["net.vietnamlinuxfamily.caramos-ota.upgrade"].find("defaults")}
        self.assertEqual("auth_admin", upgrade["allow_active"])

    def test_a_failed_daily_check_runs_again_an_hour_later(self) -> None:
        service = CHECK_SERVICE.read_text(encoding="utf-8")
        self.assertRegex(service, re.compile(r"^Type=oneshot$", re.M))
        self.assertRegex(service, re.compile(r"^Restart=on-failure$", re.M))
        self.assertRegex(service, re.compile(r"^RestartSec=1h$", re.M))
        self.assertRegex(service, re.compile(r"^RestartPreventExitStatus=2 3$", re.M))
        self.assertRegex(service, re.compile(r"^OnSuccess=caramos-ota-auto-update.service$", re.M))


if __name__ == "__main__":
    unittest.main()

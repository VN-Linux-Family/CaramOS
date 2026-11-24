"""Automatic updates, the Update Center's side: the switch, why an update waited, and telling each user how an automatic
update went (caramos_ota_notifier.auto_update, ui, app)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from caramos_ota import auto_update as system
from caramos_ota_notifier import app, ui
from caramos_ota_notifier import auto_update as notifier

ROOT = Path(__file__).parents[1]
DIST = ROOT / "usr/lib/python3/dist-packages"
UI = DIST / "caramos_ota_notifier/ui.py"

UPDATE = {"release": "1.4.1", "current_version": "1.4.0", "migration_ids": ["20261123100000_automatic_updates"],
          "packages": [{"name": "CaramOS tự cập nhật", "name_en": "CaramOS updates itself",
                        "description": "Từ nay bản CaramOS mới tự cài khi có.",
                        "description_en": "From now on new CaramOS versions install by themselves."}]}
NOW = datetime(2026, 11, 23, 12, 0).astimezone()


def result(outcome: str = system.DONE, *, age_days: float = 0, restart: bool = False, **extra) -> dict:
    finished = NOW - timedelta(days=age_days)
    return dict({"schema": 1, "id": "20261123120000-abcd1234", "outcome": outcome, "exit_code": 0 if outcome == system.DONE else 1,
                 "started_at": (finished - timedelta(minutes=2)).isoformat(), "finished_at": finished.isoformat(),
                 "from_version": "1.4.0", "to_version": "1.4.1", "restart": restart, "update": UPDATE,
                 "update_key": system.update_key(UPDATE), "output": "Error: Migration update failed.\n"}, **extra)


def builder_source(name: str) -> str:
    source = UI.read_text(encoding="utf-8")
    return source.split(f"def {name}", 1)[1].split("\ndef ", 1)[0]


class SwitchTests(unittest.TestCase):
    def test_flipping_the_switch_asks_pkexec_and_reads_the_setting_back(self) -> None:
        with mock.patch.object(notifier.subprocess, "run") as run, \
                mock.patch.object(notifier.auto_update, "is_enabled", return_value=False):
            self.assertFalse(notifier.change(False))
        self.assertEqual(["pkexec", system.HELPER, "off"], run.call_args.args[0])
        with mock.patch.object(notifier.subprocess, "run", side_effect=subprocess.TimeoutExpired("pkexec", 300)), \
                mock.patch.object(notifier.auto_update, "is_enabled", return_value=True):
            self.assertTrue(notifier.change(False))   # the window was left open: nothing changed

    def test_why_the_update_waited(self) -> None:
        last = {"outcome": system.SKIPPED, "reason": system.METERED, "update": system.update_key(UPDATE)}
        with mock.patch.object(notifier, "enabled", return_value=True):
            self.assertEqual(system.METERED, notifier.waiting_reason(UPDATE, {system.STATUS_KEY: last}))
            self.assertEqual("", notifier.waiting_reason(dict(UPDATE, release="1.4.2"), {system.STATUS_KEY: last}))
            self.assertEqual("", notifier.waiting_reason(UPDATE, {}))
            self.assertEqual("", notifier.waiting_reason(None, {system.STATUS_KEY: last}))
            failed = dict(last, outcome=system.FAILED, reason="")
            self.assertEqual(system.FAILED_BEFORE, notifier.waiting_reason(UPDATE, {system.STATUS_KEY: failed}))
            unknown = dict(last, reason="cosmic rays")
            self.assertEqual("", notifier.waiting_reason(UPDATE, {system.STATUS_KEY: unknown}))
        with mock.patch.object(notifier, "enabled", return_value=False):
            self.assertEqual("", notifier.waiting_reason(UPDATE, {system.STATUS_KEY: last}))

    def test_every_reason_has_a_sentence(self) -> None:
        for reason in system.REASONS:
            with self.subTest(reason=reason):
                self.assertTrue(ui.waiting_text(reason))
        self.assertEqual("", ui.waiting_text(""))
        self.assertEqual(("Automatic updates",
                          "New versions of CaramOS install by themselves, and you are told when they are done."),
                         ui.auto_update_texts())

    def test_a_running_update_is_not_a_retry_waiting(self) -> None:
        def answer(text):
            return mock.Mock(return_value=SimpleNamespace(stdout=text))

        self.assertTrue(notifier.service_running(answer("ActiveState=active\nSubState=running\n")))
        self.assertFalse(notifier.service_running(answer("ActiveState=activating\nSubState=auto-restart\n")))
        self.assertFalse(notifier.service_running(answer("ActiveState=inactive\nSubState=dead\n")))
        self.assertFalse(notifier.service_running(mock.Mock(side_effect=OSError)))


class PendingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.waiting = {"available_update": UPDATE}

    def test_an_installed_update_is_told_once(self) -> None:
        done = result()
        self.assertEqual(notifier.DONE_NOTIFICATION, notifier.pending(done, {}, {}, at_login=False, now=NOW))
        self.assertEqual(notifier.DONE_NOTIFICATION, notifier.pending(done, {}, {}, at_login=True, now=NOW))
        self.assertIsNone(notifier.pending(done, {}, {"notified": done["id"]}, at_login=True, now=NOW))
        self.assertIsNone(notifier.pending(result(age_days=20), {}, {}, at_login=True, now=NOW))
        self.assertIsNone(notifier.pending(None, {}, {}, at_login=True, now=NOW))

    def test_a_failure_shows_its_page_at_login_until_it_was_opened(self) -> None:
        failed = result(system.FAILED)
        self.assertEqual(notifier.FAILED_NOTIFICATION, notifier.pending(failed, self.waiting, {}, at_login=False, now=NOW))
        self.assertIsNone(notifier.pending(failed, self.waiting, {"notified": failed["id"]}, at_login=False, now=NOW))
        self.assertEqual(notifier.FAILED_PAGE,
                         notifier.pending(failed, self.waiting, {"notified": failed["id"]}, at_login=True, now=NOW))
        self.assertIsNone(notifier.pending(failed, self.waiting, {"opened": failed["id"]}, at_login=True, now=NOW))

    def test_a_failure_is_moot_once_the_update_is_installed(self) -> None:
        failed = result(system.FAILED)
        self.assertIsNone(notifier.pending(failed, {}, {}, at_login=True, now=NOW))
        other = {"available_update": dict(UPDATE, release="1.4.2")}
        self.assertIsNone(notifier.pending(failed, other, {}, at_login=True, now=NOW))

    def test_what_the_user_saw_is_kept_in_their_home(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-r", str(tmp)], check=False))
        self.assertEqual(tmp / "caramos/auto-update.json", notifier.seen_file({"XDG_STATE_HOME": str(tmp)}))
        path = tmp / "caramos/auto-update.json"
        done = result()
        self.assertTrue(notifier.mark(done, "notified", path=path))
        self.assertFalse(notifier.mark(done, "notified", path=path))   # another notifier was first
        self.assertTrue(notifier.mark(done, "notified", "opened", path=path))
        self.assertEqual({"notified": done["id"], "opened": done["id"]}, notifier.load_seen(path))
        self.assertEqual({}, notifier.load_seen(tmp / "missing.json"))


class NotificationTests(unittest.TestCase):
    def test_texts(self) -> None:
        self.assertEqual(("CaramOS updated to 1.4.1", "Some changes show after you log in again.", "See what's new"),
                         notifier.notification_texts(result()))
        self.assertEqual("Restart to finish.", notifier.notification_texts(result(restart=True))[1])
        self.assertEqual("CaramOS was updated", notifier.notification_texts(result(to_version="1.4.0"))[0])
        self.assertEqual(("CaramOS could not update itself",
                          "Open the Update Center to see what went wrong and to ask for help.", "View details"),
                         notifier.notification_texts(result(system.FAILED)))

    def test_the_vietnamese_words_the_owner_asked_for(self) -> None:
        """With the compiled catalog: "CaramOS đã cập nhật lên X.Y.Z", "Xem có gì mới", "Khởi động lại để hoàn tất"."""

        if subprocess.run(["which", "msgfmt"], capture_output=True).returncode != 0:
            self.skipTest("msgfmt is not installed")
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-r", str(tmp)], check=False))
        (tmp / "vi/LC_MESSAGES").mkdir(parents=True)
        subprocess.run(["msgfmt", "-o", str(tmp / "vi/LC_MESSAGES/caramos-ota.mo"), str(ROOT / "po/caramos-ota/vi.po")],
                       check=True)
        code = ("import json\n"
                "from caramos_ota_notifier import auto_update as n, ui\n"
                "done = {'outcome': 'done', 'from_version': '1.4.0', 'to_version': '1.4.1', 'restart': True}\n"
                "print(json.dumps([n.notification_texts(done), ui.auto_update_texts()]))\n")
        env = dict(os.environ, PYTHONPATH=str(DIST), CARAMOS_OTA_LOCALEDIR=str(tmp), LANGUAGE="vi", LANG="vi_VN.UTF-8")
        run = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(0, run.returncode, run.stderr)
        texts, switch = json.loads(run.stdout)
        self.assertEqual(["CaramOS đã cập nhật lên 1.4.1", "Khởi động lại để hoàn tất.", "Xem có gì mới"], texts)
        self.assertEqual("Tự động cập nhật", switch[0])

    def test_the_notification_is_shown_once_and_its_button_opens_the_update_center(self) -> None:
        done = result()
        with mock.patch.object(notifier.auto_update, "read_result", return_value=done), \
                mock.patch.object(notifier, "read_state", return_value={}), \
                mock.patch.object(notifier, "load_seen", return_value={}), \
                mock.patch.object(notifier, "mark", return_value=True) as mark, \
                mock.patch.object(notifier, "show_notification") as show:
            self.assertEqual(0, notifier.notify_result())
        mark.assert_called_once_with(done, "notified")
        title, body, button, on_open = show.call_args.args
        self.assertEqual(("CaramOS updated to 1.4.1", "See what's new"), (title, button))
        self.assertIs(notifier.open_update_center, on_open)
        with mock.patch.object(notifier.auto_update, "read_result", return_value=done), \
                mock.patch.object(notifier, "read_state", return_value={}), \
                mock.patch.object(notifier, "load_seen", return_value={"notified": done["id"]}), \
                mock.patch.object(notifier, "show_notification") as show:
            notifier.notify_result()
        show.assert_not_called()

    def fake_notify(self, server: str):
        """A stand-in for gi.repository.Notify that records the notification."""

        notes = []

        class Note:
            def __init__(self, title, body, icon) -> None:
                self.title, self.body, self.icon = title, body, icon
                self.actions, self.hints, self.image, self.timeout = [], {}, None, None
                notes.append(self)

            def set_image_from_pixbuf(self, image) -> None:
                self.image = image

            def set_hint(self, key, value) -> None:
                self.hints[key] = value

            def set_timeout(self, timeout) -> None:
                self.timeout = timeout

            def add_action(self, action, label, callback) -> None:
                self.actions.append((action, label))

            def connect(self, *_args) -> None:
                pass

            def show(self) -> None:
                pass

        fake = SimpleNamespace(init=lambda _name: True, uninit=lambda: None,
                               get_server_caps=lambda: ["actions", "body"],
                               get_server_info=lambda: (True, server, "vendor", "1.0", "1.2"),
                               Notification=SimpleNamespace(new=Note))
        return fake, notes

    def show_with(self, server: str, image=object()):
        fake, notes = self.fake_notify(server)
        loop = mock.Mock()
        glib = SimpleNamespace(MainLoop=lambda: loop, Variant=lambda kind, value: (kind, value),
                               timeout_add_seconds=lambda *_args: None, Error=Exception)
        repository = SimpleNamespace(Notify=fake, GLib=glib)
        # A stand-in for PyGObject as a whole: Launchpad's builders have none.
        fake_gi = SimpleNamespace(require_version=lambda *_args: None, repository=repository)
        with mock.patch.dict(sys.modules, {"gi": fake_gi, "gi.repository": repository}), \
                mock.patch.object(notifier, "logo_image", return_value=image):
            self.assertTrue(notifier.show_notification("CaramOS updated to 1.4.1", "Restart to finish.",
                                                       "See what's new", lambda: None))
        return notes[0]

    def test_one_button_on_every_desktop(self) -> None:
        cinnamon = self.show_with("cinnamon")
        self.assertEqual([("default", "See what's new"), ("open", "See what's new")], cinnamon.actions)
        xfce = self.show_with("Xfce Notify Daemon")   # shows every action as a button
        self.assertEqual([("open", "See what's new")], xfce.actions)

    def test_the_logo_is_a_small_picture_and_the_popup_stays_long_enough_to_press_it(self) -> None:
        image = object()
        note = self.show_with("Xfce Notify Daemon", image)
        self.assertIs(image, note.image)
        self.assertIsNone(note.icon)   # xfce4-notifyd drew the 512 px themed icon as it is
        self.assertEqual(notifier.POPUP_MS, note.timeout)
        self.assertEqual(("s", "caramos-update-center"), note.hints["desktop-entry"])
        self.assertEqual("caramos-logo", self.show_with("cinnamon", image=None).icon)

    def test_the_logo_picture(self) -> None:
        with mock.patch.object(notifier, "LOGO_FILE", ROOT / "usr/share/pixmaps/caramos-logo.png"):
            image = notifier.logo_image()
        if image is None:
            self.skipTest("GdkPixbuf is not available")
        self.assertEqual((notifier.IMAGE_SIZE, notifier.IMAGE_SIZE), (image.get_width(), image.get_height()))
        with mock.patch.object(notifier, "LOGO_FILE", ROOT / "missing.png"):
            self.assertIsNone(notifier.logo_image())

    def test_the_button_gets_a_scope_of_its_own_under_systemd(self) -> None:
        with mock.patch.dict(os.environ, {"INVOCATION_ID": "x"}), mock.patch.object(notifier.subprocess, "Popen") as popen:
            notifier.open_update_center()
        self.assertEqual(["systemd-run", "--user", "--scope", "--quiet", "--collect", "--",
                          "/usr/bin/caramos-ota-notifier", "--show-auto-update"], popen.call_args.args[0])

    def test_at_login(self) -> None:
        failed = result(system.FAILED)
        with mock.patch.object(notifier.auto_update, "read_result", return_value=failed), \
                mock.patch.object(notifier, "read_state", return_value={"available_update": UPDATE}), \
                mock.patch.object(notifier, "load_seen", return_value={}), \
                mock.patch.object(notifier, "mark") as mark:
            self.assertIs(failed, notifier.at_login())
        mark.assert_called_once_with(failed, "notified", "opened")
        done = result()
        with mock.patch.object(notifier.auto_update, "read_result", return_value=done), \
                mock.patch.object(notifier, "read_state", return_value={}), \
                mock.patch.object(notifier, "load_seen", return_value={}), \
                mock.patch.object(notifier.subprocess, "Popen") as popen:
            self.assertIsNone(notifier.at_login())
        self.assertEqual(["/usr/bin/caramos-ota-notifier", "--auto-update-result"], popen.call_args.args[0])

    def test_the_failure_detail_says_it_was_automatic(self) -> None:
        detail = notifier.failure_detail(result(system.FAILED))
        self.assertTrue(detail.startswith("Automatic update (caramos-ota --auto-upgrade), "))
        self.assertIn("exit code 1", detail.splitlines()[0])
        self.assertTrue(detail.endswith("Error: Migration update failed."))


class PageTests(unittest.TestCase):
    def test_the_pages_have_the_switch(self) -> None:
        self.assertIn("children.append(_auto_update_list(Gtk, auto_update))", builder_source("build_update_page"))
        self.assertIn("_auto_update_list(Gtk, auto_update)", builder_source("build_no_update_page"))
        self.assertIn("extra=extra", builder_source("build_no_update_page"))
        page = builder_source("build_auto_updated_page")
        self.assertIn("children.append(_auto_update_list(Gtk, auto_update))", page)
        self.assertIn("return _page(Gtk, children, [close], hint=hint)", page)
        # The switch is a row of a boxed list: title, description, the control at the right.
        switch = builder_source("_auto_update_list")
        self.assertIn("Gtk.Switch()", switch)
        self.assertIn('switch.connect("state-set", state_set)', switch)
        self.assertIn('"uc-list"', switch)
        self.assertIn('"uc-row"', switch)

    def test_the_page_of_an_automatic_update(self) -> None:
        self.assertEqual(("Updated to CaramOS 1.4.1", "CaramOS installed this update by itself.",
                          "Some changes show after you log in again."), ui.auto_updated_texts(result()))
        self.assertEqual("Restart to finish.", ui.auto_updated_texts(result(restart=True))[2])

    def test_the_switch_is_styled_with_the_accent(self) -> None:
        light, dark = ui.stylesheet(False), ui.stylesheet(True)
        self.assertIn("window.caramos-ota switch:checked { background-color: #2b6a44; }", light)
        self.assertIn("window.caramos-ota switch:checked { background-color: #3a855a; }", dark)


class FakeSwitchStack:
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


class ControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stack = FakeSwitchStack()
        self.window = mock.Mock()
        self.patches = [
            mock.patch.object(app, "build_update_window", return_value=(self.window, self.stack)),
            mock.patch.object(app, "build_update_page", return_value="info"),
            mock.patch.object(app, "build_progress_page", return_value=("progress", mock.Mock(), mock.Mock(), mock.Mock())),
            mock.patch.object(app, "build_no_update_page", return_value="no-update"),
            mock.patch.object(app, "build_auto_updated_page", return_value="auto-updated"),
            mock.patch.object(app, "build_result_page", return_value="result"),
            mock.patch.object(app.auto_update_ui, "enabled", return_value=True),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def controller(self, update_info=None, auto_result=None):
        return app.UpdateWindowController(mock.Mock(), mock.Mock(), update_info, {"current_version": "1.4.0"},
                                          auto_result=auto_result)

    def test_the_update_page_has_the_switch_and_why_it_waited(self) -> None:
        with mock.patch.object(app.auto_update_ui, "waiting_reason", return_value=system.METERED):
            controller = self.controller(UPDATE)
        switch = app.build_update_page.call_args.kwargs["auto_update"]
        self.assertEqual((True, system.METERED), (switch.enabled, switch.note))
        self.assertEqual(controller.toggle_auto_update, switch.on_toggle)

    def test_the_no_update_page_has_the_switch(self) -> None:
        self.controller()
        self.assertTrue(app.build_no_update_page.call_args.kwargs["auto_update"].enabled)
        self.assertEqual("no-update", self.stack.visible)

    def test_what_an_automatic_update_installed(self) -> None:
        done = result()
        self.controller(auto_result=done)
        self.assertEqual("auto-updated", self.stack.visible)
        self.assertIs(done, app.build_auto_updated_page.call_args.args[0])
        self.assertTrue(app.build_auto_updated_page.call_args.kwargs["auto_update"].enabled)

    def test_a_failed_automatic_update_shows_the_failure_page_with_ask_for_help(self) -> None:
        failed = result(system.FAILED)
        with mock.patch.object(app.problem, "help_available", return_value=True), \
                mock.patch.object(app.problem, "ask_for_help") as ask:
            controller = self.controller(auto_result=failed)
            outcome, detail, close, on_help, on_retry = app.build_result_page.call_args.args
            on_help()
        self.assertEqual((app.FAILED, controller.close, None), (outcome, close, on_retry))
        self.assertEqual(UPDATE, app.build_result_page.call_args.kwargs["update_info"])
        self.assertEqual("result", self.stack.visible)
        ask.assert_called_once_with(detail, UPDATE)
        self.assertIn("Error: Migration update failed.", detail)

    def test_flipping_the_switch_changes_the_setting_in_a_thread(self) -> None:
        controller = self.controller()
        finished = []
        with mock.patch.object(app.threading, "Thread") as thread, \
                mock.patch.object(app.auto_update_ui, "change", return_value=False) as change:
            controller.toggle_auto_update(False, finished.append)
            thread.call_args.kwargs["target"]()
        change.assert_called_once_with(False)
        controller.GLib.idle_add.assert_called_once_with(finished.append, False)


class MainTests(unittest.TestCase):
    def run_main(self, argv, **patches):
        defaults = {"has_display": True, "read_available_update": None, "read_no_update_status": {},
                    "resolve_available_update_now": (None, {})}
        defaults.update(patches)
        stack = [mock.patch.object(app, name, return_value=value) for name, value in defaults.items()]
        stack.append(mock.patch.object(app, "import_gtk", return_value=(mock.Mock(), object(), mock.Mock())))
        controller = mock.patch.object(app, "UpdateWindowController")
        for patcher in stack:
            patcher.start()
            self.addCleanup(patcher.stop)
        with controller as built:
            code = app.main(argv)
        return code, built

    def test_the_user_unit_only_notifies(self) -> None:
        with mock.patch.object(app.auto_update_ui, "notify_result", return_value=0) as notify, \
                mock.patch.object(app, "import_gtk") as gtk:
            self.assertEqual(0, app.main(["--auto-update-result"]))
        notify.assert_called_once_with()
        gtk.assert_not_called()

    def test_a_failure_opens_its_page_at_login(self) -> None:
        failed = result(system.FAILED)
        with mock.patch.object(app.auto_update_ui, "at_login", return_value=failed):
            code, built = self.run_main(["--autostart"], read_available_update=UPDATE)
        self.assertEqual(0, code)
        self.assertIs(failed, built.call_args.kwargs["auto_result"])

    def test_no_update_page_at_login_while_the_automatic_update_installs_it(self) -> None:
        with mock.patch.object(app.auto_update_ui, "at_login", return_value=None), \
                mock.patch.object(app.auto_update_ui, "enabled", return_value=True), \
                mock.patch.object(app.auto_update_ui, "service_running", return_value=True):
            code, built = self.run_main(["--autostart"], read_available_update=UPDATE)
        self.assertEqual(0, code)
        built.assert_not_called()

    def test_with_automatic_updates_off_the_login_shows_the_update_as_before(self) -> None:
        with mock.patch.object(app.auto_update_ui, "at_login", return_value=None), \
                mock.patch.object(app.auto_update_ui, "enabled", return_value=False), \
                mock.patch.object(app.auto_update_ui, "service_running", return_value=True):
            _code, built = self.run_main(["--autostart"], read_available_update=UPDATE)
        self.assertIs(UPDATE, built.call_args.args[2])
        self.assertIsNone(built.call_args.kwargs["auto_result"])

    def test_see_whats_new_opens_the_last_result(self) -> None:
        done = result()
        with mock.patch.object(app.auto_update_ui.auto_update, "read_result", return_value=done), \
                mock.patch.object(app.auto_update_ui, "mark") as mark:
            _code, built = self.run_main(["--show-auto-update"])
        mark.assert_called_once_with(done, "notified", "opened")
        self.assertIs(done, built.call_args.kwargs["auto_result"])


if __name__ == "__main__":
    unittest.main()

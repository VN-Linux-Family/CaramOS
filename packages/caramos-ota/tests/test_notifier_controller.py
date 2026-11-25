"""Behavior tests for the single-window OTA notifier controller."""

from __future__ import annotations

import unittest
from unittest import mock

from caramos_ota_notifier import app


class FakeWindow:
    def __init__(self) -> None:
        self.title = ""
        self.deletable = True
        self.destroyed = False
        self.shown = False
        self.signals = {}
        self.stack = None

    def connect(self, signal, callback) -> None:
        self.signals[signal] = callback

    def set_deletable(self, value: bool) -> None:
        self.deletable = value

    def set_title(self, title: str) -> None:
        self.title = title

    def destroy(self) -> None:
        self.destroyed = True

    def show_all(self) -> None:
        self.shown = True
        if self.stack is not None:
            self.stack.show_all()


class FakeStack:
    """GtkStack as GTK 3 has it: set_visible_child_name() does nothing for a page that is not shown, and while no
    page is visible the first one shown (or added already shown) becomes the visible one."""

    def __init__(self) -> None:
        self.children = {}
        self.visible = None

    @staticmethod
    def _shown(child) -> bool:
        return bool(getattr(child, "shown", False))

    def _first_shown(self):
        return next((name for name, child in self.children.items() if self._shown(child)), None)

    def add_named(self, child, name: str) -> None:
        self.children[name] = child
        if self.visible is None and self._shown(child):
            self.visible = name

    def set_visible_child_name(self, name: str) -> None:
        if name in self.children and self._shown(self.children[name]):
            self.visible = name

    def get_child_by_name(self, name: str):
        return self.children.get(name)

    def remove(self, child) -> None:
        for name, current in list(self.children.items()):
            if current is child:
                del self.children[name]
                if self.visible == name:
                    self.visible = self._first_shown()

    def show_all(self) -> None:
        for name, child in self.children.items():
            child.show_all()
            if self.visible is None:
                self.visible = name


class FakeProgressBar:
    def __init__(self) -> None:
        self.pulses = 0
        self.fraction = 0.0

    def pulse(self) -> None:
        self.pulses += 1

    def set_fraction(self, fraction: float) -> None:
        self.fraction = fraction


class FakeLabel:
    def __init__(self) -> None:
        self.text = ""

    def set_text(self, text: str) -> None:
        self.text = text


class FakeTextBuffer:
    """Gtk.TextBuffer's calls the progress log makes; iterators are character offsets."""

    def __init__(self) -> None:
        self.text = ""
        self.inserts = 0
        self.marks = []

    def get_start_iter(self) -> int:
        return 0

    def get_end_iter(self) -> int:
        return len(self.text)

    def get_iter_at_line(self, line: int) -> int:
        offset = 0
        for _number in range(line):
            offset = self.text.index("\n", offset) + 1
        return offset

    def get_line_count(self) -> int:
        return self.text.count("\n") + 1

    def insert(self, where: int, text: str) -> None:
        self.text = self.text[:where] + text + self.text[where:]
        self.inserts += 1

    def delete(self, start: int, end: int) -> None:
        self.text = self.text[:start] + self.text[end:]

    def set_text(self, text: str) -> None:
        self.text = text

    def create_mark(self, name, where: int, left_gravity: bool):
        mark = (name, where, left_gravity)
        self.marks.append(mark)
        return mark


class FakeAdjustment:
    """Gtk.Adjustment: the value stays within 0..upper - page; "changed" comes before "value-changed"."""

    def __init__(self, page: float = 180.0) -> None:
        self.value = 0.0
        self.upper = page
        self.page = page
        self.handlers = {}

    def connect(self, signal: str, callback) -> None:
        self.handlers.setdefault(signal, []).append(callback)

    def _emit(self, signal: str) -> None:
        for callback in self.handlers.get(signal, []):
            callback(self)

    def get_value(self) -> float:
        return self.value

    def get_upper(self) -> float:
        return self.upper

    def get_page_size(self) -> float:
        return self.page

    def set_value(self, value: float) -> None:
        value = max(0.0, min(value, self.upper - self.page))
        if value != self.value:
            self.value = value
            self._emit("value-changed")

    def configure(self, upper: float) -> None:
        """The text view's height changed: lines were added, removed or laid out."""

        self.upper = max(upper, self.page)
        value = max(0.0, min(self.value, self.upper - self.page))
        clamped, self.value = value != self.value, value
        self._emit("changed")
        if clamped:
            self._emit("value-changed")


class FakeTextView:
    def __init__(self) -> None:
        self.buffer = FakeTextBuffer()
        self.adjustment = FakeAdjustment()

    def get_buffer(self) -> FakeTextBuffer:
        return self.buffer

    def get_vadjustment(self) -> FakeAdjustment:
        return self.adjustment


class FakePage:
    def __init__(self, name: str) -> None:
        self.name = name
        self.shown = False

    def show_all(self) -> None:
        self.shown = True


class FakeGtk:
    def __init__(self) -> None:
        self.quit_calls = 0

    def main_quit(self) -> None:
        self.quit_calls += 1


class FakeGLib:
    PRIORITY_LOW = 300

    def __init__(self) -> None:
        self.timeout_callbacks = []
        self.idle_callbacks = []
        self.low_idle_callbacks = []
        self.removed_sources = []

    def timeout_add(self, _interval, callback) -> int:
        self.timeout_callbacks.append(callback)
        return 41

    def idle_add(self, callback, *args, priority=None) -> int:
        if priority == self.PRIORITY_LOW:
            self.low_idle_callbacks.append(callback)
        else:
            self.idle_callbacks.append((callback, args))
        return 42

    def run_low_idles(self) -> None:
        callbacks, self.low_idle_callbacks = self.low_idle_callbacks, []
        for callback in callbacks:
            callback()

    def source_remove(self, source_id: int) -> None:
        self.removed_sources.append(source_id)


class FakeThread:
    def __init__(self, *, target, daemon: bool) -> None:
        self.target = target
        self.daemon = daemon
        self.started = False

    def start(self) -> None:
        self.started = True


class UpdateWindowControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.window = FakeWindow()
        self.stack = FakeStack()
        self.window.stack = self.stack
        self.progress = FakeProgressBar()
        self.stage = FakeLabel()
        self.log_view = FakeTextView()
        self.gtk = FakeGtk()
        self.glib = FakeGLib()

        self.patches = [
            mock.patch.object(app, "build_update_window", return_value=(self.window, self.stack)),
            mock.patch.object(app, "build_update_page", return_value=FakePage("info")),
            mock.patch.object(app, "build_progress_page", return_value=(FakePage("progress"), self.progress, self.stage, self.log_view)),
            mock.patch.object(app, "build_no_update_page", return_value=FakePage("no-update")),
            mock.patch.object(app.threading, "Thread", FakeThread),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_controller(self, update_info=None):
        return app.UpdateWindowController(self.gtk, self.glib, update_info, {"current_version": "1.0"})

    def test_manual_no_update_uses_no_update_page(self) -> None:
        controller = self.make_controller()

        self.assertIs(controller.window, self.window)
        self.assertEqual("no-update", self.stack.visible)
        self.assertEqual({"no-update"}, set(self.stack.children))

    def test_an_update_waiting_at_login_opens_on_its_update_page(self) -> None:
        # The login autostart builds the pages before the window is shown. 1.5.1 added the progress page first and
        # GtkStack ignored showing the update page, which was not shown yet: the window opened on "Updating to
        # CaramOS 1.1" / "Getting ready…" with no button, and the update never started.
        controller = self.make_controller({"release": "1.1"})
        controller.show()

        self.assertEqual("info", self.stack.visible)
        self.assertFalse(controller.upgrade_running)
        self.assertEqual({"info", "progress"}, set(self.stack.children))

        controller.start_upgrade()
        self.assertEqual("progress", self.stack.visible)

    def test_nothing_waiting_at_login_opens_on_the_no_update_page(self) -> None:
        controller = self.make_controller()
        controller.show()

        self.assertEqual("no-update", self.stack.visible)

    def test_update_reuses_window_and_blocks_close(self) -> None:
        controller = self.make_controller({"release": "1.1"})
        original_window = controller.window

        controller.start_upgrade()
        controller.start_upgrade()

        self.assertIs(original_window, controller.window)
        # The progress page names the version the update goes to.
        app.build_progress_page.assert_called_once_with({"release": "1.1"})
        self.assertEqual("progress", self.stack.visible)
        self.assertTrue(controller.upgrade_running)
        self.assertFalse(self.window.deletable)
        self.assertEqual(1, len(self.glib.timeout_callbacks))
        self.assertTrue(controller.thread.started)
        self.assertTrue(controller.close())
        self.assertFalse(self.window.destroyed)
        self.assertEqual(0, self.gtk.quit_calls)

    def test_upgrade_done_switches_same_window_to_result(self) -> None:
        controller = self.make_controller({"release": "1.1"})
        controller.start_upgrade()
        result_page = FakePage("result")

        with mock.patch.object(app, "build_result_page", return_value=result_page) as build_result:
            repeat = controller.on_upgrade_done(app.DONE, "complete")

        self.assertFalse(repeat)
        self.assertFalse(controller.upgrade_running)
        self.assertEqual([41], self.glib.removed_sources)
        self.assertEqual(1.0, self.progress.fraction)
        self.assertEqual("Updated.", self.stage.text)
        self.assertEqual("result", self.stack.visible)
        self.assertIs(result_page, self.stack.children["result"])
        self.assertTrue(result_page.shown)
        self.assertTrue(self.window.deletable)
        build_result.assert_called_once_with(app.DONE, "complete", controller.close, None, None,
                                             update_info={"release": "1.1"})

    def test_the_window_title_stays_the_name_of_the_app(self) -> None:
        # Up to 1.4.0 the title said "CaramOS - Updating…", then "CaramOS - Update complete!"; the pages say it now.
        for outcome in (app.DONE, app.FAILED, app.CANCELLED, app.BUSY):
            with self.subTest(outcome=outcome):
                self.window.title = "Update Center"
                controller = self.make_controller({"release": "1.1"})
                controller.start_upgrade()
                self.assertEqual("Update Center", self.window.title)
                with mock.patch.object(app, "build_result_page", return_value=FakePage("result")):
                    controller.on_upgrade_done(outcome, "")
                self.assertEqual("Update Center", self.window.title)

    def test_a_failed_update_can_ask_vnlf_for_help_with_its_log(self) -> None:
        controller = self.make_controller({"release": "1.1", "title": "Zalo"})
        controller.start_upgrade()
        with mock.patch.object(app, "build_result_page", return_value=FakePage("result")) as build_result, \
                mock.patch.object(app.problem, "help_available", return_value=True), \
                mock.patch.object(app.problem, "ask_for_help") as ask:
            controller.on_upgrade_done(app.FAILED, "Error: Migration update failed.")
            on_help = build_result.call_args.args[3]
            on_help()
        ask.assert_called_once_with("Error: Migration update failed.", {"release": "1.1", "title": "Zalo"})

    def test_exit_codes_tell_a_failure_from_no_password_and_a_busy_updater(self) -> None:
        self.assertEqual(app.DONE, app.upgrade_outcome(0))
        self.assertEqual(app.CANCELLED, app.upgrade_outcome(126))   # pkexec: the password window was closed
        self.assertEqual(app.CANCELLED, app.upgrade_outcome(127))   # pkexec: not authorized
        self.assertEqual(app.BUSY, app.upgrade_outcome(7))          # caramos-ota: another run holds the lock
        for code in (1, 4, 5, 6, 8):
            self.assertEqual(app.FAILED, app.upgrade_outcome(code))

    def test_run_upgrade_stream_reports_a_closed_password_window(self) -> None:
        lines = []
        process = mock.Mock()
        process.stdout = iter(["Error executing command as another user: Request dismissed\n"])
        process.wait.return_value = 126
        with mock.patch.object(app.subprocess, "Popen", return_value=process), \
                mock.patch.object(app.threading, "Timer", return_value=mock.Mock()):
            outcome, detail = app.run_upgrade_stream(lines.append)
        self.assertEqual(app.CANCELLED, outcome)
        self.assertEqual("Error executing command as another user: Request dismissed", detail)
        self.assertEqual(["Error executing command as another user: Request dismissed"], lines)

    def test_no_password_or_a_busy_updater_offer_try_again_and_no_help(self) -> None:
        for outcome, stage in ((app.CANCELLED, "Not updated."), (app.BUSY, "Another update is running.")):
            with self.subTest(outcome=outcome):
                controller = self.make_controller({"release": "1.1"})
                controller.start_upgrade()
                with mock.patch.object(app, "build_result_page", return_value=FakePage("result")) as build_result, \
                        mock.patch.object(app.problem, "help_available", return_value=True):
                    controller.on_upgrade_done(outcome, "Error: Another CaramOS OTA operation is already running.")
                build_result.assert_called_once_with(outcome, "Error: Another CaramOS OTA operation is already running.",
                                                     controller.close, None, controller.start_upgrade,
                                                     update_info={"release": "1.1"})
                self.assertEqual(stage, self.stage.text)
                self.assertFalse(controller.upgrade_running)

    def test_try_again_shows_only_the_new_run(self) -> None:
        controller = self.make_controller({"release": "1.1"})
        controller.start_upgrade()
        controller.queue_log_line("Error executing command as another user: Request dismissed")
        with mock.patch.object(app, "build_result_page", return_value=FakePage("result")) as build_result:
            controller.on_upgrade_done(app.CANCELLED, "Error executing command as another user: Request dismissed")
        on_retry = build_result.call_args.args[4]

        on_retry()

        self.assertTrue(controller.upgrade_running)
        self.assertEqual("progress", self.stack.visible)
        self.assertEqual("", self.log_view.buffer.text)
        self.assertEqual("Getting ready…", self.stage.text)
        self.assertEqual(0.0, self.progress.fraction)

    def test_worker_queues_lines_for_one_flush_on_glib(self) -> None:
        controller = self.make_controller({"release": "1.1"})

        def fake_upgrade(on_line):
            for line in ("Updating package index", "starting migration", "Get:1 http://archive.ubuntu.com"):
                on_line(line)
            return app.DONE, "done"

        with mock.patch.object(app, "run_upgrade_stream", side_effect=fake_upgrade):
            controller._do_upgrade()

        # One callback for the three lines, not one per line.
        self.assertEqual([controller.flush_log_lines], self.glib.timeout_callbacks)
        self.assertEqual([(controller.on_upgrade_done, (app.DONE, "done"))], self.glib.idle_callbacks)
        self.assertEqual("", self.log_view.buffer.text)

        self.assertFalse(controller.flush_log_lines())
        self.assertEqual("Updating package index\nstarting migration\nGet:1 http://archive.ubuntu.com\n",
                         self.log_view.buffer.text)
        self.assertEqual(1, self.log_view.buffer.inserts)
        self.assertEqual("Updating…", self.stage.text)

        controller.queue_log_line("Run: zalo")
        self.assertEqual(2, len(self.glib.timeout_callbacks))
        controller.flush_log_lines()
        self.assertEqual("Applying the changes…", self.stage.text)

    def test_a_flood_of_lines_keeps_the_end_in_two_inserts(self) -> None:
        # The 1.3.4 -> 1.3.5 update of a machine Driver Check had left broken printed 49,233 objtool lines.
        controller = self.make_controller({"release": "1.1"})
        flood = [f"nvidia.o: warning: objtool: _nv{number:06d}rm+0x4" for number in range(49233)]

        for line in flood[:30000]:
            controller.queue_log_line(line)
        controller.flush_log_lines()
        for line in flood[30000:]:
            controller.queue_log_line(line)
        controller.queue_log_line("Update complete.")
        controller.flush_log_lines()

        lines = self.log_view.buffer.text.split("\n")
        self.assertEqual("", lines.pop())
        self.assertEqual(app.LOG_VIEW_LINES, len(lines))
        self.assertEqual(flood[-(app.LOG_VIEW_LINES - 1):] + ["Update complete."], lines)
        self.assertEqual(2, len(self.glib.timeout_callbacks))
        self.assertEqual(2, self.log_view.buffer.inserts)
        self.assertEqual([], self.log_view.buffer.marks)   # 1.3.5 left one per line in the buffer
        self.assertEqual("Finishing…", self.stage.text)

    def test_the_log_shows_its_end_once_gtk_has_laid_it_out(self) -> None:
        controller = self.make_controller({"release": "1.1"})
        adjustment = self.log_view.adjustment

        controller.queue_log_line("Get:1 http://archive.ubuntu.com")
        controller.flush_log_lines()
        adjustment.configure(5000)   # GTK laid out the new lines
        adjustment.configure(9000)
        self.assertEqual(0, adjustment.value)
        self.assertEqual(1, len(self.glib.low_idle_callbacks))   # after GTK's layout, once

        self.glib.run_low_idles()
        self.assertEqual(9000 - 180, adjustment.value)

        adjustment.set_value(1200)   # the reader scrolled up, then opened a wider window
        adjustment.configure(7000)
        self.glib.run_low_idles()
        self.assertEqual(7000 - 180, adjustment.value)

    def test_the_log_is_not_scrolled_without_a_progress_page(self) -> None:
        controller = self.make_controller()

        controller._show_log_end()

        self.assertIsNone(controller.log_view)
        self.assertEqual([], self.glib.low_idle_callbacks)

    def test_upgrade_done_shows_the_last_queued_lines_first(self) -> None:
        controller = self.make_controller({"release": "1.1"})
        controller.start_upgrade()
        controller.queue_log_line("Update complete.")

        with mock.patch.object(app, "build_result_page", return_value=FakePage("result")):
            controller.on_upgrade_done(app.DONE, "Update complete.")

        self.assertEqual("Update complete.\n", self.log_view.buffer.text)
        self.assertEqual("Updated.", self.stage.text)
        self.assertFalse(controller.flush_log_lines())   # the queued callback finds nothing left
        self.assertEqual(1, self.log_view.buffer.inserts)

    def test_close_after_result_quits_main_loop(self) -> None:
        controller = self.make_controller({"release": "1.1"})

        self.assertFalse(controller.close())
        self.assertTrue(self.window.destroyed)
        self.assertEqual(1, self.gtk.quit_calls)


class NotifierMainTests(unittest.TestCase):
    def test_autostart_without_update_exits_without_window(self) -> None:
        fake_gtk = mock.Mock()
        with (
            mock.patch.object(app, "has_display", return_value=True),
            mock.patch.object(app, "import_gtk", return_value=(fake_gtk, object(), object())),
            mock.patch.object(app, "read_available_update", return_value=None),
            mock.patch.object(app, "read_no_update_status", return_value={}),
            mock.patch.object(app, "UpdateWindowController") as controller,
        ):
            result = app.main(["--autostart"])

        self.assertEqual(0, result)
        controller.assert_not_called()
        fake_gtk.main.assert_not_called()


if __name__ == "__main__":
    unittest.main()

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
        for name, current in list(self.children.items()):
            if current is child:
                del self.children[name]


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

    def test_update_reuses_window_and_blocks_close(self) -> None:
        controller = self.make_controller({"release": "1.1"})
        original_window = controller.window

        controller.start_upgrade()
        controller.start_upgrade()

        self.assertIs(original_window, controller.window)
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
            repeat = controller.on_upgrade_done(True, "complete")

        self.assertFalse(repeat)
        self.assertFalse(controller.upgrade_running)
        self.assertEqual([41], self.glib.removed_sources)
        self.assertEqual(1.0, self.progress.fraction)
        self.assertEqual("Update complete.", self.stage.text)
        self.assertEqual("result", self.stack.visible)
        self.assertIs(result_page, self.stack.children["result"])
        self.assertTrue(result_page.shown)
        self.assertTrue(self.window.deletable)
        self.assertEqual("CaramOS - Update complete!", self.window.title)
        build_result.assert_called_once_with(True, "complete", controller.close, None)

    def test_a_failed_update_can_ask_vnlf_for_help_with_its_log(self) -> None:
        controller = self.make_controller({"release": "1.1", "title": "Zalo"})
        controller.start_upgrade()
        with mock.patch.object(app, "build_result_page", return_value=FakePage("result")) as build_result, \
                mock.patch.object(app.problem, "help_available", return_value=True), \
                mock.patch.object(app.problem, "ask_for_help") as ask:
            controller.on_upgrade_done(False, "Error: Migration update failed.")
            on_help = build_result.call_args.args[3]
            on_help()
        ask.assert_called_once_with("Error: Migration update failed.", {"release": "1.1", "title": "Zalo"})

    def test_worker_queues_lines_for_one_flush_on_glib(self) -> None:
        controller = self.make_controller({"release": "1.1"})

        def fake_upgrade(on_line):
            for line in ("Updating package index", "starting migration", "Get:1 http://archive.ubuntu.com"):
                on_line(line)
            return True, "done"

        with mock.patch.object(app, "run_upgrade_stream", side_effect=fake_upgrade):
            controller._do_upgrade()

        # One callback for the three lines, not one per line.
        self.assertEqual([controller.flush_log_lines], self.glib.timeout_callbacks)
        self.assertEqual([(controller.on_upgrade_done, (True, "done"))], self.glib.idle_callbacks)
        self.assertEqual("", self.log_view.buffer.text)

        self.assertFalse(controller.flush_log_lines())
        self.assertEqual("Updating package index\nstarting migration\nGet:1 http://archive.ubuntu.com\n",
                         self.log_view.buffer.text)
        self.assertEqual(1, self.log_view.buffer.inserts)
        self.assertEqual("Updating CaramOS…", self.stage.text)

        controller.queue_log_line("Run: zalo")
        self.assertEqual(2, len(self.glib.timeout_callbacks))
        controller.flush_log_lines()
        self.assertEqual("Running system migrations…", self.stage.text)

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
        self.assertEqual("Finishing the update…", self.stage.text)

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
            controller.on_upgrade_done(True, "Update complete.")

        self.assertEqual("Update complete.\n", self.log_view.buffer.text)
        self.assertEqual("Update complete.", self.stage.text)
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

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
    def __init__(self) -> None:
        self.timeout_callbacks = []
        self.idle_callbacks = []
        self.removed_sources = []

    def timeout_add(self, _interval, callback) -> int:
        self.timeout_callbacks.append(callback)
        return 41

    def idle_add(self, callback, *args) -> int:
        self.idle_callbacks.append((callback, args))
        return 42

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
        self.log_view = object()
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
        self.assertEqual("Cập nhật hoàn tất.", self.stage.text)
        self.assertEqual("result", self.stack.visible)
        self.assertIs(result_page, self.stack.children["result"])
        self.assertTrue(result_page.shown)
        self.assertTrue(self.window.deletable)
        self.assertEqual("CaramOS - Cập nhật thành công!", self.window.title)
        build_result.assert_called_once_with(True, "complete", controller.close)

    def test_worker_schedules_ui_callbacks_on_glib(self) -> None:
        controller = self.make_controller({"release": "1.1"})

        def fake_upgrade(on_line):
            on_line("starting migration")
            return True, "done"

        with mock.patch.object(app, "run_upgrade_stream", side_effect=fake_upgrade):
            controller._do_upgrade()

        self.assertEqual(
            [(controller.append_log_line, ("starting migration",)), (controller.on_upgrade_done, (True, "done"))],
            self.glib.idle_callbacks,
        )

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

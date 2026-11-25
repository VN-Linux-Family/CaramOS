"""Builds the Phòng máy window's pages (never shown) and prints what they hold as JSON, for tests/test_lab.py.

It runs in a process of its own: GTK 4 loaded into the test run would keep the GTK 3 tests (Xfce Control Center,
tray icons) from loading theirs. Not a test module itself (its name does not start with test_).
"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "usr/lib/python3/dist-packages"))
sys.path.insert(0, str(ROOT / "usr/share/caramos-ota/lab"))

TEACHER_STATE = {"role": "teacher", "backend": "veyon", "room": "Phòng máy 1", "user": "cogiao"}
STUDENT_STATE = {"role": "student", "backend": "veyon", "room": "Phòng máy 1",
                 "teacher": {"host": "192.168.1.2", "name": "maygv"}}


def main() -> int:
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gdk, Gtk
    except (ImportError, ValueError):
        print(json.dumps({"gtk": False}))
        return 0
    if not Gtk.init_check() or Gdk.Display.get_default() is None:
        print(json.dumps({"gtk": False}))
        return 0
    Adw.init()
    from caramos_lab import app as lab_app, awake, pairing, system

    application = Adw.Application(application_id="net.vietnamlinuxfamily.CaramOSLabTest")
    application.register(None)

    def widgets(widget, kind):
        found = [widget] if isinstance(widget, kind) else []
        child = widget.get_first_child()
        while child is not None:
            found += widgets(child, kind)
            child = child.get_next_sibling()
        return found

    def window(state: dict):
        with mock.patch.object(system, "read_state", return_value=state):
            return lab_app.build_window(application)

    def page_of(win):
        return win.nav.get_visible_page()

    def buttons(win):
        return [button for button in widgets(page_of(win), Gtk.Button) if button.get_label()]

    def describe(win) -> dict:
        page = page_of(win)
        return {"tag": page.get_tag(),
                "rows": [row.get_title() for row in widgets(page, Adw.ActionRow)],
                "pills": [button.get_label() for button in buttons(win) if button.has_css_class("pill")],
                "main": [button.get_label() for button in buttons(win) if button.has_css_class("suggested-action")],
                "status": [(status.get_title(), status.get_description()) for status in widgets(page, Adw.StatusPage)]}

    result: dict = {"gtk": True}
    result["first"] = describe(window({}))
    teacher = window(TEACHER_STATE)
    result["teacher"] = describe(teacher)
    teacher.teacher_setup()
    result["teacher_setup"] = describe(teacher)
    student = window(STUDENT_STATE)
    result["student"] = describe(student)
    with mock.patch.object(system, "read_state", return_value=STUDENT_STATE):
        stacks = []
        with mock.patch.object(threading, "Thread"):
            student.student_find()                       # from the first page
            student.student_find()                       # Search again
            stacks.append([page.get_tag() for page in student.nav.get_navigation_stack()])
            student.student_code(pairing.Teacher("192.168.1.2", "maygv", "Phòng máy 1", "veyon"))
            result["student_code"] = describe(student)
            stacks.append([page.get_tag() for page in student.nav.get_navigation_stack()])
            student.student_find()                       # Pair again from a later page
            stacks.append([page.get_tag() for page in student.nav.get_navigation_stack()])
        result["search_stacks"] = stacks
        with mock.patch.object(awake, "restore"):
            student.left_lab(STUDENT_STATE)
        result["left"] = describe(student)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

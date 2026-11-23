"""Running the root helper through pkexec, off the main loop: the window stays alive while polkit asks for the
password and while the helper works."""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable
from typing import Any

from gi.repository import GLib

from .. import HELPER
from ..i18n import _

Done = Callable[[bool, dict[str, Any]], None]


def run_helper(args: list[str], done: Done, stdin: str | None = None) -> None:
    """Runs caramos-business-helper ARGS as root; done(ok, answer) in the main loop."""

    def work() -> None:
        try:
            result = subprocess.run(["pkexec", HELPER, *args], input=stdin, capture_output=True, text=True,
                                    timeout=300, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            GLib.idle_add(done, False, {"error": str(exc)})
            return
        if result.returncode in (126, 127) and not result.stdout.strip():
            GLib.idle_add(done, False, {"error": _("The password was not given.")})
            return
        try:
            answer = json.loads(result.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            answer = {"ok": False, "error": result.stderr.strip() or _("The helper did not answer.")}
        GLib.idle_add(done, bool(answer.get("ok")), answer)

    threading.Thread(target=work, daemon=True).start()


def in_thread(work: Callable[[], Any], done: Callable[[Any, Exception | None], None]) -> None:
    """Runs work() in a thread; done(result, error) in the main loop."""

    def run() -> None:
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 - shown to the user, whatever it is
            GLib.idle_add(done, None, exc)
            return
        GLib.idle_add(done, result, None)

    threading.Thread(target=run, daemon=True).start()

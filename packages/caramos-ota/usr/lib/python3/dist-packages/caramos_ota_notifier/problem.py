"""After a failed update, or a failed check for updates: ask VNLF for help with what the updater logged.

The result page's "Ask for help" saves the updater's output and the end of the day's OTA log to
~/.cache/caramos-ota/update-failure.log and opens Feedback & Help with it (caramos-help --log), which takes
personal data out of it and attaches it for VNLF's team only.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from caramos_ota.constants import LOG_DIR
from caramos_ota.i18n import _, localized

HELP_COMMAND = "/usr/bin/caramos-help"
OTA_LOG_TAIL = 48 * 1024   # bytes from the end of the day's OTA log


def help_available() -> bool:
    return os.access(HELP_COMMAND, os.X_OK)


def failure_log_path() -> Path:
    cache = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return Path(cache) / "caramos-ota" / "update-failure.log"


def _ota_log_tail(log_dir: Path) -> tuple[str, str]:
    """The newest OTA log's name and its end; empty when there is none or it cannot be read."""

    try:
        newest = max(log_dir.glob("*.log"), key=lambda path: path.name)
        with newest.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - OTA_LOG_TAIL))
            return newest.name, handle.read().decode("utf-8", errors="replace")
    except (ValueError, OSError):
        return "", ""


def failure_log_text(detail: str, update_info: dict[str, Any] | None, log_dir: Path = LOG_DIR, *,
                     checking: bool = False) -> str:
    """checking: the check for new versions failed (the window opened by hand), not an update."""

    info = update_info or {}
    when = datetime.now().astimezone().isoformat(timespec='seconds')
    if checking:
        lines = [
            f"Update Center: checking for updates failed at {when}",
            "",
            "== Output of caramos-ota --check ==",
            detail.strip() or "(nothing)",
        ]
    else:
        lines = [
            f"Update Center: the update failed at {when}",
            f"Installed: CaramOS {info.get('current_version') or '?'}; update: {info.get('title_en') or info.get('title') or '?'}",
            f"Migrations: {', '.join(info.get('migration_ids') or []) or '?'}",
            "",
            "== Output of caramos-ota --upgrade ==",
            detail.strip() or "(nothing)",
        ]
    name, tail = _ota_log_tail(log_dir)
    if tail:
        lines += ["", f"== End of {log_dir / name} ==", tail.strip()]
    return "\n".join(lines) + "\n"


def help_message(update_info: dict[str, Any] | None, *, checking: bool = False) -> str:
    if checking:
        return _("The Update Center could not check for updates.")
    title = localized(update_info or {}, "title")
    if title:
        return _("The Update Center could not install the update “%s”.") % title
    return _("The Update Center could not install the update.")


def ask_for_help(detail: str, update_info: dict[str, Any] | None, *, checking: bool = False) -> bool:
    """Save the log and open Feedback & Help with it; False when that did not work."""

    path = failure_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(failure_log_text(detail, update_info, checking=checking), encoding="utf-8")
        subprocess.Popen([HELP_COMMAND, "--type", "bug", "--message", help_message(update_info, checking=checking),
                          "--log", str(path)],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError:
        return False
    return True

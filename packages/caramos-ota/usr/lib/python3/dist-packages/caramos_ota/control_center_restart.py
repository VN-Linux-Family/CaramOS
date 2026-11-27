"""The CaramOS Control Center of each running Xfce session starts again after an update changed it (postinst).

The Control Center of Xfce (/usr/share/caramos-ota/xfce/caramos-control-center, which the CaramOS panel plugin
xfce4-caramos-plugin starts in the taskbar) runs for the whole session. It reads its style and its translations when it
starts, but loads some of its parts only when they are first used, such as the sound level of the sound keys (osd.py).
Updates install while people work since CaramOS 1.5, so a part loaded after an update came from the new files and was
drawn with the old style: the slim sound level of caramos-ota 1.5.2-0caramos6 (ticket H-1216) showed in the tall box of
the one before, until the next login.

postinst runs `python3 -I -m caramos_ota.control_center_restart --old-version <the version replaced>`. When the update
changed a file of the Control Center (the checksums dpkg keeps; preinst copies the old ones), each running Control
Center gets SIGTERM, and the panel plugin starts the installed one three seconds later: only the clock and the Control
Center button go away from the taskbar for that time. An update from a version before CaramOS 1.5.2.2 ends them
whatever changed, since a Control Center running then may already mix the two.

Nothing here may fail the update: postinst ignores the exit status, and this ends with 0 whatever happens.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

LAUNCHER = "/usr/share/caramos-ota/xfce/caramos-control-center"
MD5SUMS = Path("/var/lib/dpkg/info/caramos-ota.md5sums")
# preinst copies the checksums of the version being replaced here (debian/preinst); postinst deletes the copy.
BEFORE = Path("/run/caramos-ota/control-center-before.md5sums")
# A Control Center running on a version before this one may already show new parts in the old style.
FIXED_IN = "1.5.2.2~"
# What the Control Center reads, as dpkg's md5sums names it: the program, its code and style, and its translations
# (the domain of the Cinnamon Control Center, caramos_xfce_cc/i18n.py).
CONTROL_CENTER_FILE = re.compile(
    r"usr/share/caramos-ota/xfce/(?:caramos-control-center|control-center/.+)"
    r"|usr/share/locale/[^/]+/LC_MESSAGES/caramos-control-center\.mo"
)


def control_center_sums(text: str) -> set[str]:
    """The lines of an md5sums file ("<checksum>  <path>") that name a file of the Control Center."""

    sums = set()
    for line in text.splitlines():
        checksum, separator, path = line.partition("  ")
        if separator and CONTROL_CENTER_FILE.fullmatch(path):
            sums.add(f"{checksum}  {path}")
    return sums


def read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def files_changed(before: str | None, after: str | None) -> bool:
    """Whether the update changed a file of the Control Center. Without both lists nobody knows, so: yes."""

    if before is None or after is None:
        return True
    return control_center_sums(before) != control_center_sums(after)


def older_than_fix(old_version: str) -> bool:
    try:
        result = subprocess.run(["dpkg", "--compare-versions", old_version, "lt", FIXED_IN], check=False,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        return True
    return result.returncode == 0


def in_chroot(proc: Path) -> bool:
    """A chroot, as when the ISO is built: the processes listed there are those of the computer building it."""

    try:
        here = os.stat("/")
        init = os.stat(proc / "1" / "root")
    except OSError:
        return True
    return (here.st_dev, here.st_ino) != (init.st_dev, init.st_ino)


def is_control_center(arguments: list[str]) -> bool:
    """The Control Center's command line: Python running the launcher (its first line names /usr/bin/python3)."""

    if not arguments:
        return False
    if arguments[0] == LAUNCHER:
        return True
    return os.path.basename(arguments[0]).startswith("python") and LAUNCHER in arguments[1:3]


def running_control_centers(proc: Path) -> list[int]:
    pids = []
    try:
        entries = list(proc.iterdir())
    except OSError:
        return pids
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:  # it ended meanwhile
            continue
        arguments = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
        if is_control_center(arguments):
            pids.append(int(entry.name))
    return sorted(pids)


def restart(old_version: str, before: Path = BEFORE, md5sums: Path = MD5SUMS, proc: Path = Path("/proc"),
            kill: Callable[[int, int], None] = os.kill) -> list[int]:
    """End the running Control Centers when the update from `old_version` calls for it; the ones ended."""

    if not old_version:  # a first install: nothing runs from before
        return []
    if not older_than_fix(old_version) and not files_changed(read(before), read(md5sums)):
        return []
    if in_chroot(proc):
        return []
    ended = []
    for pid in running_control_centers(proc):
        try:
            kill(pid, signal.SIGTERM)
        except OSError:
            continue
        ended.append(pid)
    return ended


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m caramos_ota.control_center_restart",
                                     description="Start the CaramOS Control Center of running Xfce sessions again "
                                                 "after caramos-ota changed it (postinst).")
    parser.add_argument("--old-version", default="", help="the version of caramos-ota this update replaced")
    try:
        args = parser.parse_args(argv)
        ended = restart(args.old_version)
    except (Exception, SystemExit) as exc:  # never at the cost of the update
        print(f"caramos-ota: the Control Center was not started again: {exc}", file=sys.stderr)
        return 0
    if ended:
        print(f"caramos-ota: the CaramOS Control Center starts again in {len(ended)} session(s), "
              f"with the files of this update.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

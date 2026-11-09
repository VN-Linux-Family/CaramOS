"""Entry point of Driver Check.

    caramos-driver-check              open the app: scan, results, one-click driver installs, hardware reports
    caramos-driver-check --autostart  at login: open the app or notify only when there is news (state.py)
    caramos-driver-check --hotplug    a device that needs a driver was plugged in: notify about new problems
    caramos-driver-check --json       print the report, e.g. for a bug report; no window

CARAMOS_DRIVER_CHECK_DEMO=<case> shows made-up hardware (demo.py) and CARAMOS_DRIVER_CHECK_FAKE_HELPER=1
pretends to install, to work on the window without the hardware or root.
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys
import time

from caramos_ota.i18n import _

from . import notify
from . import state as user_state
from .analysis import Report, analyze
from .drivers import DriverProposal, lookup
from .hardware import SystemReader
from .knowledge import read_libfprint_support
from .logs import note, system_summary

APP_ID = "net.vietnamlinuxfamily.CaramOSDriverCheck"


class Scanner:
    """What the window and the login check read; demo.DemoScanner replaces it for development.

    Each step goes to Driver Check's log (logs.note), which a help request can attach: how long reading the
    hardware and asking for drivers took on this computer, and with how much memory free.
    """

    def __init__(self) -> None:
        self.fingerprints = read_libfprint_support()
        self._lookup: tuple[tuple, list[DriverProposal]] | None = None

    def snapshot(self):
        start = time.monotonic()
        snapshot = SystemReader().snapshot()
        note(f"hardware read in {time.monotonic() - start:.1f} s: {len(snapshot.pci)} PCI, {len(snapshot.usb)} USB, "
             f"{len(snapshot.acpi)} ACPI devices{' · live USB' if snapshot.live else ''} · {system_summary()}")
        return snapshot

    @staticmethod
    def _lookup_key(snapshot) -> tuple:
        """What the drivers UbuntuDrivers proposes depend on: the devices, the installed and the known packages."""

        stamps = []
        for path in ("/var/lib/dpkg/status", "/var/lib/apt/lists"):
            try:
                stamps.append(os.stat(path).st_mtime_ns)
            except OSError:
                stamps.append(0)
        devices = tuple((device.address, device.id, device.driver, bool(device.net)) for device in snapshot.pci)
        return devices, snapshot.live, tuple(stamps)

    def proposals(self, snapshot) -> list[DriverProposal]:
        key = self._lookup_key(snapshot)
        if self._lookup is not None and self._lookup[0] == key:
            return self._lookup[1]   # checking again: the same computer and packages, the same answer
        found = lookup(snapshot)
        if found.outcome == "skipped":
            note(f"driver lookup skipped: {found.detail}")
        elif found.outcome == "done":
            peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // 1024
            names = ", ".join(proposal.package for proposal in found.proposals) or "none"
            note(f"driver lookup for {found.detail}: {found.seconds:.1f} s, peak {peak} MB, proposals: {names} · "
                 f"{system_summary()}")
        elif found.outcome == "timeout":
            note(f"driver lookup for {found.detail} stopped after {found.seconds:.0f} s · {system_summary()}")
        else:
            note(f"driver lookup failed after {found.seconds:.1f} s: {found.detail}")
        proposals = list(found.proposals)
        if found.outcome in ("skipped", "done"):
            self._lookup = (key, proposals)
        return proposals

    def analyze(self, snapshot, proposals) -> Report:
        return analyze(snapshot, self.fingerprints, proposals)

    def connected(self) -> bool:
        reader = SystemReader()
        return reader.connected(reader.net_interfaces())


def make_scanner():
    case = os.environ.get("CARAMOS_DRIVER_CHECK_DEMO", "")
    if case:
        from .demo import DemoScanner

        return DemoScanner(case)
    return Scanner()


def has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def open_window() -> int:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib

    from .ui.common import load_css
    from .ui.window import MainWindow

    GLib.set_prgname("caramos-driver-check")
    GLib.set_application_name(_("Driver Check"))
    application = Adw.Application(application_id=APP_ID)

    def activate(app) -> None:
        window = app.get_active_window()
        if window is not None:
            window.present()
            return
        load_css()
        MainWindow(app, make_scanner()).present()

    application.connect("activate", activate)
    return application.run([sys.argv[0]])


def autostart(hotplug: bool = False) -> int:
    """The check at login, or right after a device that needs a driver was plugged in (hotplug).

    For hotplug, systemd starts caramos-driver-check-hotplug.service in the user's session: the udev rule
    71-caramos-capt-printers.rules asks for it when a Canon CAPT printer without a driver is plugged in.
    """

    # No UbuntuDrivers here: loading the APT cache at every login would cost a second or two.
    scanner = make_scanner()
    snapshot = scanner.snapshot()
    report = scanner.analyze(snapshot, ())
    present = {device.key for device in snapshot.devices}
    path = user_state.state_path()
    previous = user_state.load(path)
    decision = user_state.decide(report, previous, present)
    if hotplug and not decision.new:
        # Only news about what was plugged in; what got solved is for the login check to tell.
        return 0
    try:
        user_state.save(path, user_state.remember(report, previous, present))
    except OSError:
        pass
    if decision.action == user_state.QUIET:
        return 0
    if decision.action == user_state.SHOW_WINDOW:
        return open_window()
    title, body = notify.text_for(decision, report)
    return notify.show(title, body, notify.WAIT_SECONDS[decision.action])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caramos-driver-check")
    parser.add_argument("--autostart", action="store_true",
                        help="login mode: open the app or notify only when something changed")
    parser.add_argument("--hotplug", action="store_true",
                        help="a device that needs a driver was plugged in: notify only about new problems")
    parser.add_argument("--json", action="store_true", help="print the report as JSON and exit")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    if args.json:
        scanner = make_scanner()
        snapshot = scanner.snapshot()
        report = scanner.analyze(snapshot, scanner.proposals(snapshot))
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        return 0
    if not has_display():
        return 0
    if args.autostart or args.hotplug:
        return autostart(hotplug=args.hotplug)
    return open_window()

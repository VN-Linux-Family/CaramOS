"""printer.log: what a help request says about the printers, when the computer has one (logs.system_logs).

CUPS logs to /var/log/cups/error_log, not to the journal, so system.log shows nothing when a printer does not
print. This log has:
- the printing packages and the Canon CAPT drivers installed (captdriver, Canon's own);
- the USB printers: id, name, interface, driver (usblp) and the IEEE 1284 id they report, which decides the
  driver the automatic setup picks;
- each USB print queue: its driver (make and model), its state with CUPS's message, and its jobs (number,
  user, size, time: no document names). Network queues are only counted: their names and addresses can name
  the office;
- how the automatic printer setup (configure-printer@.service) went in this boot;
- the end of CUPS's error_log, which the users of the adm group may read (the first user of a CaramOS install
  is one).

Besides what logs.redact takes out, it drops serial numbers and document names: with debug logging on, CUPS
logs each job's title (argv[3]).
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import knowledge
from .hardware import SystemReader
from .logs import redact, tail

PACKAGES = ("cups-daemon", "cups-filters", "printer-driver-captdriver", "system-config-printer-udev", "ipp-usb")
ERROR_LOG = "var/log/cups/error_log"
ERROR_LOG_LIMIT = 12 * 1024   # characters kept of the end of error_log
READ_LIMIT = 128 * 1024       # bytes read from its end
SETUP_LINES = 30
JOB_LINES = 5
COMMAND_TIMEOUT = 10
STATES = {"3": "idle", "4": "printing", "5": "stopped"}   # printer-state
# usb://Canon/LBP2900?serial=…, "serial:…" (udev-configure-printer), SN:/SERN: in IEEE 1284 ids.
SERIAL = re.compile(r"(?i)\b(serial[=:]|SN:|SERN:|SERIALNUMBER:)[^;&\s'\"]+")
TITLE = re.compile(r'(argv\[3\]=)"[^"]*"')
JOB_ATTRIBUTE = re.compile(r"\b((?:job-name|document-name-supplied|document-name|job-originating-host-name)"
                           r"\b[^=\n]*=\s*)(\"[^\"]*\"|\S+)")
POSTSCRIPT_TITLE = re.compile(r"(%%Title:).*")
# With debug logging on, cupsd's chatter with its clients fills the end of error_log; the jobs' lines stay.
NOISE = re.compile(r"^D \[[^\]]*\] (?:\[Client \d+\]|cupsdSetBusyState|cupsdMarkDirty|Discarding unused)")

Runner = Callable[[Sequence[str]], str]


def run(arguments: Sequence[str]) -> str:
    """The output of a command, also when it exits with an error (dpkg-query for a package not installed)."""

    try:
        done = subprocess.run(list(arguments), check=False, capture_output=True, text=True, timeout=COMMAND_TIMEOUT,
                              env={**os.environ, "LC_ALL": "C.UTF-8"})
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout


def scrub(text: str) -> str:
    """logs.redact, then serial numbers and document names."""

    text = SERIAL.sub(r"\1[REDACTED]", redact(text))
    text = TITLE.sub(r'\1"[REDACTED_TITLE]"', text)
    text = JOB_ATTRIBUTE.sub(r"\1[REDACTED]", text)
    return POSTSCRIPT_TITLE.sub(r"\1 [REDACTED_TITLE]", text)


@dataclass(frozen=True)
class UsbPrinter:
    interface: str   # "3-1:1.0"
    id: str          # "04a9:2676"
    name: str        # "Canon LBP2900"
    protocol: str    # "7/1/2": class, subclass, protocol (2 bidirectional, 4 IPP over USB)
    driver: str      # the kernel driver of the interface: "usblp", "" for none
    device_id: str   # the IEEE 1284 id the printer reports (usblp reads it)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _hex(text: str) -> int:
    try:
        return int(text, 16)
    except ValueError:
        return 0


def usb_printers(root: Path = Path("/")) -> list[UsbPrinter]:
    """The printer interfaces (USB class 7) of the plugged-in devices."""

    devices = root / "sys/bus/usb/devices"
    try:
        entries = sorted(devices.iterdir())
    except OSError:
        return []
    found = []
    for interface in entries:
        if ":" not in interface.name or _read(interface / "bInterfaceClass") != "07":
            continue
        device = devices / interface.name.split(":")[0]
        driver = interface / "driver"
        found.append(UsbPrinter(
            interface=interface.name,
            id=f"{_read(device / 'idVendor')}:{_read(device / 'idProduct')}",
            name=" ".join(part for part in (_read(device / "manufacturer"), _read(device / "product")) if part),
            protocol=f"7/{_hex(_read(interface / 'bInterfaceSubClass'))}/{_hex(_read(interface / 'bInterfaceProtocol'))}",
            driver=os.path.basename(os.readlink(driver)) if driver.is_symlink() else "",
            device_id=_read(interface / "ieee1284_id"),
        ))
    return found


def queues(runner: Runner = run) -> list[tuple[str, str]]:
    """(name, device URI) of each print queue."""

    found = []
    for line in runner(["lpstat", "-v"]).splitlines():
        match = re.match(r"device for (\S+): (\S+)", line)
        if match:
            found.append((match.group(1), match.group(2)))
    return found


def _options(runner: Runner, name: str) -> dict[str, str]:
    try:
        parts = shlex.split(runner(["lpoptions", "-p", name]))
    except ValueError:
        return {}
    return dict(part.split("=", 1) for part in parts if "=" in part)


def _lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def _capt_support(printer: UsbPrinter) -> str:
    vendor, _, product = printer.id.partition(":")
    if vendor != knowledge.CANON or product not in knowledge.CAPT_PRINTERS:
        return ""
    if product in knowledge.CAPTDRIVER_WORKS:
        support = "captdriver drives it"
    elif product in knowledge.CAPTDRIVER_MODELS:
        support = "captdriver drives it, experimental"
    else:
        support = "only Canon's driver drives it"
    return f"Canon CAPT printer ({knowledge.CAPT_PRINTERS[product]}): {support}"


def _error_log(root: Path) -> str:
    try:
        with (root / ERROR_LOG).open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - READ_LIMIT))
            data = handle.read()
    except PermissionError:
        return "(not readable: only root and the adm group may read it)"
    except OSError:
        return "(none)"
    lines = [line for line in data.decode("utf-8", errors="replace").splitlines() if not NOISE.match(line)]
    return tail("\n".join(lines).strip(), ERROR_LOG_LIMIT) or "(empty)"


def printer_log(root: Path = Path("/"), runner: Runner = run) -> str:
    """printer.log, or "" when the computer has no USB printer and no print queue."""

    printers = usb_printers(root)
    every_queue = queues(runner)
    if not printers and not every_queue:
        return ""
    lines = ["== Printing packages =="]
    lines += _lines(runner(["dpkg-query", "-W", "-f", "${Package} ${Version} ${db:Status-Abbrev}\n", *PACKAGES]))
    lines.append("Canon CAPT drivers installed: " + (", ".join(SystemReader(root).capt_drivers()) or "none"))

    lines += ["", "== USB printers =="]
    for printer in printers:
        lines.append(f"{printer.interface}: USB {printer.id} {printer.name or '?'} · {printer.protocol} · "
                     f"driver {printer.driver or 'none'}")
        if printer.device_id:
            lines.append(f"  IEEE 1284 id: {printer.device_id}")
        support = _capt_support(printer)
        if support:
            lines.append(f"  {support}")
    if not printers:
        lines.append("(none plugged in)")

    lines += ["", "== Print queues of USB printers =="]
    usb_queues = [(name, uri) for name, uri in every_queue if uri.startswith("usb:")]
    for name, uri in usb_queues:
        options = _options(runner, name)
        state = options.get("printer-state", "?")
        lines.append(f"{name}: {options.get('printer-make-and-model', '?')} · {uri}")
        lines.append(f"  state {STATES.get(state, state)}, reasons {options.get('printer-state-reasons', '?')}, "
                     f"accepting jobs {options.get('printer-is-accepting-jobs', '?')}")
        lines += [f"  {line.strip()}" for line in _lines(runner(["lpstat", "-p", name]))]
        waiting = _lines(runner(["lpstat", "-W", "not-completed", "-o", name]))
        done = _lines(runner(["lpstat", "-W", "completed", "-o", name]))[-JOB_LINES:]
        lines.append(f"  jobs not done: {len(waiting)}")
        lines += [f"    {line}" for line in waiting[:JOB_LINES]]
        lines.append(f"  last jobs done: {len(done) or 'none'}")
        lines += [f"    {line}" for line in done]
    if not usb_queues:
        lines.append("(none)")
    others = len(every_queue) - len(usb_queues)
    if others:
        lines.append(f"{others} other queue(s), for network printers and the like, left out")

    lines += ["", f"== Automatic printer setup in this boot (configure-printer@, last {SETUP_LINES} lines) =="]
    setup = runner(["journalctl", "-b", "0", "-q", "--no-pager", "-o", "short-iso", "-n", str(SETUP_LINES),
                    "-u", "configure-printer@*"])
    lines.append(setup.strip() or "(none readable)")
    lines += ["", "== End of CUPS's error_log ==", _error_log(root)]
    return scrub("\n".join(lines)) + "\n"

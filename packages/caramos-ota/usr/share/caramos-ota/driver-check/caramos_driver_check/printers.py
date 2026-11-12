"""printer.log: what a help request says about the printers, when the computer has one (logs.system_logs).

CUPS logs to /var/log/cups/error_log, not to the journal, so system.log shows nothing when a printer does not
print. This log has:
- the printing packages and the Canon CAPT drivers installed (captdriver, Canon's own);
- the USB printers: id, name, interface, driver (usblp) and the IEEE 1284 id they report, which decides the
  driver the automatic setup picks;
- each print queue of a USB printer or of Canon's driver (ccp://): its driver (make and model), its state with
  CUPS's message, and its jobs (number, user, size, time: no document names). Other network queues are only
  counted: their names and addresses can name the office;
- with Canon's driver (canon_capt): its daemon, the printers registered with it, its 32-bit libraries and what
  its units logged in this boot;
- how the automatic printer setup (configure-printer@.service) went in this boot;
- the end of CUPS's error_log, which the users of the adm group may read (the first user of a CaramOS install
  is one).

Besides what logs.redact takes out (IP addresses among them), it drops serial numbers, also in the device names
Canon's driver uses, and document names: with debug logging on, CUPS logs each job's title (argv[3]).
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import canon_capt, knowledge
from .hardware import SystemReader
from .logs import redact, tail

PACKAGES = ("cups-daemon", "cups-filters", "printer-driver-captdriver", "system-config-printer-udev", "ipp-usb",
            *canon_capt.PACKAGES)
ERROR_LOG = "var/log/cups/error_log"
ERROR_LOG_LIMIT = 12 * 1024   # characters kept of the end of error_log
READ_LIMIT = 128 * 1024       # bytes read from its end
SETUP_LINES = 30
CANON_LINES = 30
JOB_LINES = 5
COMMAND_TIMEOUT = 10
STATES = {"3": "idle", "4": "printing", "5": "stopped"}   # printer-state
# usb://Canon/LBP2900?serial=…, "serial:…" (udev-configure-printer), SN:/SERN: in IEEE 1284 ids.
SERIAL = re.compile(r"(?i)\b(serial[=:]|SN:|SERN:|SERIALNUMBER:)[^;&\s'\"]+")
TITLE = re.compile(r'(argv\[3\]=)"[^"]*"')
# /dev/usb/canon-capt-<product>-<serial> (72-caramos-canon-capt.rules), in ccpd.conf and in its units' journal.
CANON_DEVICE = re.compile(r"(canon-capt-[0-9a-f]{4}-)[^\s/'\"]+")
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
    text = CANON_DEVICE.sub(r"\1[REDACTED]", text)
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
    elif product in canon_capt.USB_MODELS:
        support = f"only Canon's driver drives it, with its {canon_capt.USB_MODELS[product]} PPD"
    else:
        support = "no Linux driver drives it"
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


def _first_word(text: str) -> str:
    return (text.split() or ["?"])[0]


def _canon_daemons(root: Path) -> str:
    """Canon's daemon and status monitors running, by name: "1 ccpd, 1 captmoncnabb"."""

    counts: dict[str, int] = {}
    for pid in canon_capt.canon_processes(root / "proc"):
        name = _read(root / "proc" / str(pid) / "comm") or "?"
        counts[name] = counts.get(name, 0) + 1
    return ", ".join(f"{count} {name}" for name, count in sorted(counts.items())) or "none"


def _canon(root: Path, runner: Runner, every_queue: list[tuple[str, str]]) -> list[str]:
    """What Canon's CAPT driver (canon_capt) has set up, or [] when there is no trace of it."""

    def there(path: Path) -> Path:
        return root / path.relative_to("/")

    conf = there(canon_capt.CCPD_CONF)
    wants = there(canon_capt.BOOT_WANTS)
    ccp_queues = [name for name, uri in every_queue if uri.startswith("ccp:")]
    if not (canon_capt.installed(root) or conf.exists() or wants.is_symlink() or ccp_queues):
        return []
    lines = ["", "== Canon's CAPT driver =="]
    lines.append(f"{canon_capt.SERVICE}: {_first_word(runner(['systemctl', 'is-active', canon_capt.SERVICE]))}, "
                 f"starts at boot: {'yes' if wants.is_symlink() else 'no'} · Canon's own {canon_capt.SYSV_UNIT}: "
                 f"{_first_word(runner(['systemctl', 'is-enabled', canon_capt.SYSV_UNIT]))}")
    lines.append(f"Canon's programs running: {_canon_daemons(root)}")
    lines.append("32-bit packages: " + (
        "on" if "i386" in runner(["dpkg", "--print-foreign-architectures"]).split() else "off"))
    readable = True
    try:
        printers = canon_capt.registered(conf.read_text(encoding="utf-8", errors="replace"))
    except FileNotFoundError:
        printers = {}
    except OSError:
        printers, readable = {}, False
    lines.append(f"Printers registered with ccpd ({canon_capt.CCPD_CONF}):")
    for name, path in printers.items():
        where = ""
        if path.startswith("/dev/"):
            where = " (plugged in)" if (root / path.lstrip("/")).exists() else " (not plugged in)"
        queue = "" if name in ccp_queues else ", but no ccp:// print queue has this name"
        lines.append(f"  {name}: {path}{where}{queue}")
    if not printers:
        lines.append("  (none)" if readable else "  (not readable)")
    if readable:
        lines += [f"  print queue {name} (ccp://) is not registered with ccpd" for name in ccp_queues
                  if name not in printers]
    wanted = canon_capt.network_addresses(printers)
    allowed = []
    for line in _read(there(canon_capt.DROPIN)).splitlines():
        if line.startswith("IPAddressAllow="):
            allowed += line.split("=", 1)[1].split()
    if wanted or allowed:
        same = "the network printers above" if sorted(wanted) == sorted(allowed) else \
            f"{len(allowed)} address(es), NOT those of the {len(wanted)} network printer(s) above"
        lines.append(f"ccpd may reach on the network ({canon_capt.DROPIN.name}): {same}")
    lines += ["", f"== {canon_capt.SERVICE} and its setup in this boot (last {CANON_LINES} lines) =="]
    journal = runner(["journalctl", "-b", "0", "-q", "--no-pager", "-o", "short-iso", "-n", str(CANON_LINES),
                      "-u", canon_capt.SERVICE, "-u", "caramos-canon-capt-setup.service"])
    lines.append(journal.strip() or "(none readable)")
    return lines


def printer_log(root: Path = Path("/"), runner: Runner = run) -> str:
    """printer.log, or "" when the computer has no USB printer and no print queue."""

    printers = usb_printers(root)
    every_queue = queues(runner)
    if not printers and not every_queue:
        return ""
    lines = ["== Printing packages =="]
    canon = canon_capt.installed(root)
    lines += _lines(runner(["dpkg-query", "-W", "-f", "${binary:Package} ${Version} ${db:Status-Abbrev}\n",
                            *PACKAGES, *(canon_capt.I386_LIBRARIES if canon else ())]))
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

    lines += ["", "== Print queues of USB printers and of Canon's driver =="]
    shown = [(name, uri) for name, uri in every_queue if uri.startswith(("usb:", "ccp:"))]
    for name, uri in shown:
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
    if not shown:
        lines.append("(none)")
    others = len(every_queue) - len(shown)
    if others:
        lines.append(f"{others} other queue(s), for network printers and the like, left out")
    lines += _canon(root, runner, every_queue)

    lines += ["", f"== Automatic printer setup in this boot (configure-printer@, last {SETUP_LINES} lines) =="]
    setup = runner(["journalctl", "-b", "0", "-q", "--no-pager", "-o", "short-iso", "-n", str(SETUP_LINES),
                    "-u", "configure-printer@*"])
    lines.append(setup.strip() or "(none readable)")
    lines += ["", "== End of CUPS's error_log ==", _error_log(root)]
    return scrub("\n".join(lines)) + "\n"

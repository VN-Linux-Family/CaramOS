"""Logs attached to a help request, without personal data.

- What an app logged when something failed: the App Center and the Update Center save it to a file and open
  Feedback & Help with it (caramos-help --type bug --message TEXT --log FILE).
- system.log, made when the form opens: CaramOS and kernel, live USB or not, CPU, memory and swap, the boot
  options, how the computer starts (UEFI entries, Secure Boot) and its disks, and the warnings and errors of
  this boot (and the end of the previous one, after a freeze and a restart).
- driver-check.log: what each Driver Check scan did and how long it took (note()).

The form attaches them, ticked, to the request's report, which only VNLF's moderators see, never the community
(HELP_API.md, "Logs"). A log keeps its last lines up to LOG_LIMIT, after e-mail and IP addresses, MAC
addresses, passwords and tokens, the home folder, the computer's name and the user's login name are taken out.
"""

from __future__ import annotations

import getpass
import json
import os
import platform
import re
import subprocess
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from caramos_ota_audit.redaction import redact_text

LOG_LIMIT = 24 * 1024     # characters kept of each log: its end, where the error is
READ_LIMIT = 256 * 1024   # bytes read from the end of a file
MAX_LOGS = 4
MIN_USER_NAME = 3         # shorter login names are also ordinary words
DRIVER_CHECK_LOG_LIMIT = 64 * 1024
JOURNAL_LINES = 200       # warnings and errors of this boot
PREVIOUS_BOOT_LINES = 60
JOURNAL_TIMEOUT = 10
JOURNAL_SCAN = 10         # times more lines read than kept, so that firewall notices do not crowd out the rest
# Firewall notices: ufw logs each dropped broadcast, and on a busy network they were all the log kept (H-1108).
JOURNAL_NOISE = ("[UFW BLOCK]", "[UFW AUDIT]", "[UFW ALLOW]", "[UFW LIMIT BLOCK]")
UNFINISHED_STATES = frozenset({"half-installed", "unpacked", "half-configured"})
COMMAND_TIMEOUT = 10
SECURE_BOOT = "sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
BOOT_ENTRY = re.compile(r"^Boot([0-9A-Fa-f]{4})(\*?)\s+(.*?)\t(.*)$")
GPT_PARTITION = re.compile(r"HD\(\d+,GPT,([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}),")
EFI_FILE = re.compile(r"File\(([^)]*)\)")
# A word of a boot entry's name with letters and digits, 8 or more: the firmware names its entries after the
# disk, with the serial number in it.
SERIAL_LIKE = re.compile(r"\b(?=[\w-]*\d)(?=[\w-]*[A-Za-z])[\w-]{8,}\b")
# The mount points the log names; another one (a USB stick, a data partition) shows as "mounted".
SYSTEM_MOUNTS = frozenset({"/", "/boot", "/boot/efi", "/home", "/var", "/usr", "[SWAP]", "/cdrom", "/isodevice"})


@dataclass(frozen=True)
class Log:
    name: str   # the file's name, shown on the form
    text: str


def redact(text: str, user: str | None = None) -> str:
    text = redact_text(text, long_tokens=False)
    try:
        user = getpass.getuser() if user is None else user
    except (KeyError, OSError):
        user = ""
    if len(user) >= MIN_USER_NAME and user != "root":
        text = re.sub(rf"(?<![\w.-]){re.escape(user)}(?![\w-])", "[REDACTED_USER]", text)
    return text


def tail(text: str, limit: int = LOG_LIMIT) -> str:
    """The end of text in at most limit characters, starting at a line."""

    if len(text) <= limit:
        return text
    end = text[-limit:]
    newline = end.find("\n")
    return "…\n" + (end[newline + 1:] if 0 <= newline < len(end) - 1 else end)


def read_log(path: Path) -> Log | None:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - READ_LIMIT))
            data = handle.read()
    except OSError:
        return None
    text = tail(redact(data.decode("utf-8", errors="replace")).strip())
    return Log(path.name, text) if text else None


def read_logs(paths: Iterable[str | Path]) -> tuple[Log, ...]:
    logs = []
    for path in list(paths)[:MAX_LOGS]:
        log = read_log(Path(path))
        if log is not None:
            logs.append(log)
    return tuple(logs)


# Driver Check's own log --------------------------------------------------------------------------

def _cache_dir() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")


def driver_check_log_path() -> Path:
    return _cache_dir() / "caramos-driver-check" / "driver-check.log"


def note(line: str, path: Path | None = None) -> None:
    """Add a line, after the time, to Driver Check's log, which keeps its last DRIVER_CHECK_LOG_LIMIT bytes."""

    path = path or driver_check_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"{stamp} {line}\n")
        if path.stat().st_size > 2 * DRIVER_CHECK_LOG_LIMIT:
            path.write_text(tail(path.read_text(encoding="utf-8", errors="replace"), DRIVER_CHECK_LOG_LIMIT),
                            encoding="utf-8")
    except OSError:
        pass


# The computer ----------------------------------------------------------------------------------

def _gib(kib: int) -> str:
    return f"{kib / 1024 / 1024:.1f} GiB"


def _meminfo(path: Path) -> dict[str, int]:
    values = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            name, _, rest = line.partition(":")
            if rest.strip().split()[:1]:
                values[name] = int(rest.split()[0])
    except (OSError, ValueError):
        pass
    return values


def system_summary(root: Path = Path("/")) -> str:
    """One line: CPU, load, memory, swap and uptime."""

    model = ""
    try:
        for line in (root / "proc/cpuinfo").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("model name"):
                model = " ".join(line.split(":", 1)[1].split())
                break
    except OSError:
        pass
    parts = [f"CPU {model or '?'}, {os.cpu_count() or '?'} threads"]
    try:
        parts.append("load " + " ".join((root / "proc/loadavg").read_text(encoding="utf-8").split()[:3]))
    except OSError:
        pass
    memory = _meminfo(root / "proc/meminfo")
    if memory.get("MemTotal"):
        parts.append(f"memory {_gib(memory['MemTotal'])}, {_gib(memory.get('MemAvailable', 0))} available")
    if "SwapTotal" in memory:
        parts.append(f"swap {_gib(memory['SwapTotal'])}, {_gib(memory.get('SwapFree', 0))} free")
    try:
        minutes = int(float((root / "proc/uptime").read_text(encoding="utf-8").split()[0]) // 60)
        parts.append(f"up {minutes} min")
    except (OSError, ValueError, IndexError):
        pass
    return " · ".join(parts)


def _journal(arguments: list[str], lines: int) -> str:
    try:
        done = subprocess.run(["journalctl", *arguments, "-p", "warning", "--no-pager", "-q", "-o", "short-iso",
                               "-n", str(lines * JOURNAL_SCAN)], check=False, capture_output=True, text=True,
                              timeout=JOURNAL_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return ""
    if done.returncode != 0:
        return ""
    kept = [line for line in done.stdout.strip().splitlines() if not any(noise in line for noise in JOURNAL_NOISE)]
    return "\n".join(collapse_repeats(kept)[-lines:])


def _message(line: str) -> str:
    """A journal line without its time and the computer's name (journalctl -o short-iso)."""

    parts = line.split(" ", 2)
    return parts[2] if len(parts) == 3 else line


def collapse_repeats(lines: list[str]) -> list[str]:
    """Each message once, where it came last, with how many times it came: a device that logs the same error
    every few seconds took most of the 200 lines (H-1097, a Realtek Ethernet port and its PCIe errors)."""

    counts = Counter(_message(line) for line in lines)
    kept, seen = [], set()
    for line in reversed(lines):
        message = _message(line)
        if message in seen:
            continue
        seen.add(message)
        kept.append(f"{line} [{counts[message]} times]" if counts[message] > 1 else line)
    kept.reverse()
    return kept


def _command(arguments: list[str]) -> str:
    try:
        done = subprocess.run(arguments, check=False, capture_output=True, text=True, timeout=COMMAND_TIMEOUT,
                              env={**os.environ, "LC_ALL": "C.UTF-8"})
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _size(value: object) -> str:
    try:
        count = int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return "?"
    return f"{count / 1024 ** 3:.1f} GiB" if count >= 1024 ** 3 else f"{count // 1024 ** 2} MiB"


def disks() -> tuple[list[str], dict[str, str]]:
    """A line for each disk with its partitions, and the partition each PARTUUID is (for the boot entries)."""

    try:
        tree = json.loads(_command(["lsblk", "-J", "-b", "-o", "NAME,TYPE,SIZE,TRAN,FSTYPE,MOUNTPOINTS,MODEL,PARTUUID"])
                          or "{}")
    except ValueError:
        return [], {}
    lines: list[str] = []
    partitions: dict[str, str] = {}

    def walk(device: dict, found: list[str]) -> None:
        for child in device.get("children") or ():
            name = str(child.get("name") or "?")
            if child.get("partuuid"):
                partitions[str(child["partuuid"]).lower()] = name
            mounts = [point if point in SYSTEM_MOUNTS else "mounted" for point in child.get("mountpoints") or () if point]
            found.append(" ".join([name, str(child.get("fstype") or "-"), _size(child.get("size")), *mounts]))
            walk(child, found)

    for disk in (tree.get("blockdevices") or ()) if isinstance(tree, dict) else ():
        name = str(disk.get("name") or "")
        if disk.get("type") != "disk" or name.startswith(("zram", "loop", "ram")):
            continue
        found: list[str] = []
        walk(disk, found)
        about = ", ".join(part for part in (_size(disk.get("size")), str(disk.get("tran") or ""),
                                            " ".join(str(disk.get("model") or "").split())) if part)
        lines.append(f"Disk {name}: {about}" + "".join(f" · {part}" for part in found))
    return lines, partitions


def _entry_kind(path: str) -> str:
    if any(tag in path for tag in ("MAC(", "IPv4(", "IPv6(", "Uri(")):
        return "network"
    if "USB(" in path:
        return "USB"
    if any(tag in path for tag in ("NVMe(", "Sata(", "Scsi(", "HD(", "CDROM(")):
        return "disk"
    return "other"


def boot_lines(root: Path, partitions: dict[str, str]) -> list[str]:
    """How the computer starts: BIOS or UEFI, Secure Boot, and the UEFI boot entries of operating systems with the
    partition and file each starts, so that an entry left by an older system shows (a grub> prompt, H-1097).
    The firmware's own entries (network, USB, a whole disk) are only counted: their names carry serial numbers."""

    if not (root / "sys/firmware/efi").is_dir():
        return ["Boot: BIOS (legacy)"]
    about = ["Boot: UEFI"]
    try:
        state = (root / SECURE_BOOT).read_bytes()[4:5]
        about.append("Secure Boot " + ("on" if state == b"\x01" else "off"))
    except OSError:
        pass
    current = order = ""
    entries: list[str] = []
    kinds: dict[str, str] = {}
    for line in _command(["efibootmgr"]).splitlines():
        if line.startswith("BootCurrent:"):
            current = line.split(":", 1)[1].strip()
        elif line.startswith("BootOrder:"):
            order = ", ".join(line.split(":", 1)[1].strip().split(","))
        match = BOOT_ENTRY.match(line)
        if match is None:
            continue
        number, active, label, path = match.groups()
        partition, file = GPT_PARTITION.search(path), EFI_FILE.search(path)
        if partition is None or file is None:
            kinds[number] = _entry_kind(path)
            continue
        where = partitions.get(partition.group(1).lower(), "a partition this computer does not have")
        name = SERIAL_LIKE.sub("…", " ".join(label.split())) or "?"
        entries.append(f"EFI entry {number}{'' if active else ' (turned off)'} {name}: {where} {file.group(1)}")
    if current:
        about.append(f"started from entry {current}" + (f" (the firmware's entry for a {kinds[current]})"
                                                        if current in kinds else ""))
    if order:
        about.append(f"order {order}")
    if kinds:
        counted = Counter(kinds.values())
        about.append("the firmware's own entries: " + ", ".join(f"{count} {kind}" for kind, count in sorted(counted.items())))
    return [" · ".join(about), *entries]


def unfinished_packages(root: Path = Path("/")) -> list[str]:
    """Packages dpkg could not finish installing: every apt-get install fails until they are fixed."""

    found = []
    package = ""
    try:
        status = (root / "var/lib/dpkg/status").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return found
    for line in status.splitlines():
        if line.startswith("Package:"):
            package = line.split(":", 1)[1].strip()
        elif line.startswith("Status:") and package:
            words = line.split()
            if len(words) == 4 and words[3] in UNFINISHED_STATES:
                found.append(package)
    return found


def system_log(root: Path = Path("/")) -> str:
    try:
        command_line = (root / "proc/cmdline").read_text(encoding="utf-8")
        flags = (root / "proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        command_line = flags = ""
    live = "boot=casper" in command_line.split()
    virtual = " hypervisor" in flags
    release = ""
    try:
        for line in (root / "etc/caramos-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("VERSION="):
                release = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    lines_head = [f"CaramOS {release or '?'} · Linux {platform.release()} · live USB: {'yes' if live else 'no'} · "
                  f"virtual machine: {'yes' if virtual else 'no'}", system_summary(root)]
    if command_line.strip():
        lines_head.append("Boot options: " + redact(command_line.strip()))
    unfinished = unfinished_packages(root)
    if unfinished:
        lines_head.append("Not fully installed (dpkg): " + ", ".join(unfinished[:20]))
    disk_lines, partitions = disks()
    lines_head += [redact(line) for line in (*boot_lines(root, partitions), *disk_lines)]
    head = "\n".join(lines_head)
    journal = redact(_journal(["-b", "0"], JOURNAL_LINES))
    # After a freeze the computer was restarted: how the previous boot ended. A live USB has no previous boot.
    previous = "" if live else redact(_journal(["-b", "-1"], PREVIOUS_BOOT_LINES))
    # The journal gives way, from its oldest lines, so that the computer's lines always fit LOG_LIMIT.
    room = LOG_LIMIT - len(head) - 200
    if previous:
        previous = tail(previous, room // 3)
        room -= len(previous)
    lines = [head, "", f"== Warnings and errors of this boot (last {JOURNAL_LINES}, a repeated one once) ==",
             tail(journal, max(room, 1000)) or "(none readable)"]
    if previous:
        lines += ["", f"== End of the previous boot (warnings and errors, last {PREVIOUS_BOOT_LINES}) ==", previous]
    return "\n".join(lines) + "\n"


def system_logs() -> tuple[Log, ...]:
    """What a help request carries about the computer: system.log, and driver-check.log when Driver Check ran."""

    found = [Log("system.log", system_log().strip())]
    driver_check = read_log(driver_check_log_path())
    if driver_check is not None:
        found.append(driver_check)
    return tuple(found)

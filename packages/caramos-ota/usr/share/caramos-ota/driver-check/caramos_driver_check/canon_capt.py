"""Canon's own CAPT printer driver, for the Canon laser printers captdriver does not drive (LBP6300dn, LBP3300...).

Canon's terms let nobody but Canon hand the driver out, so it cannot go into the CaramOS PPA. This computer
downloads it from Canon once the user agreed to Canon's download terms in the Driver Check window; its size and
SHA-256 must be those of the archive CaramOS checked. Canon's two packages (CAPT driver 2.71 of 2017, the last
one) are installed as Canon made them, and everything around them is CaramOS's own:

- the 32-bit libraries their 32-bit parts (captfilter, captmon*) need: the amd64 packages do not ask for them;
- a systemd unit for Canon's daemon, ccpd, which Canon only starts from an old init script nothing runs at boot.
  ccpd ignores SIGTERM and listens as root on every address (ports 59687 and 59787); the unit lets it talk to this
  computer and to the network printers set up here only (IPAddressAllow, in a drop-in written below);
- a fixed device name per USB printer (72-caramos-canon-capt.rules): ccpd opens the path it was given, and
  /dev/usb/lpN changes with the order printers are plugged in;
- a print queue per printer, ccp://localhost:59687 with Canon's PPD, registered under the same name with ccpdadmin.

Canon's maintainer scripts kill every process whose `ps awx` line has "ccpd" or "captmon", cutting the PID column
at 5 characters: with the 7-digit PIDs of Ubuntu 24.04 that is a random process, and a ccpd still running makes
the loop endless. The daemon is stopped before dpkg runs, and the install stops when another program has those
words on its command line (an editor open on /etc/ccpd.conf).
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import shutil
import signal
import subprocess
import tarfile
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Canon Asia, "CAPT Printer Driver for Linux V2.71" (0100459601; the Vietnamese page serves the same file).
TERMS_PAGE = "https://vn.canon/vi/support/0100459601"
TARBALL_URL = "https://gdlp01.c-wss.com/gds/6/0100004596/05/linux-capt-drv-v271-uken.tar.gz"
TARBALL_SIZE = 127_521_219
TARBALL_SHA256 = "8565a2fdc4f452bb8cf97ceadadd6614d12eac73e253ac6d59e61b8abae941be"
TARBALL_ROOT = "linux-capt-drv-v271-uken"
DEBS = ("64-bit_Driver/Debian/cndrvcups-common_3.21-1_amd64.deb",
        "64-bit_Driver/Debian/cndrvcups-capt_2.71-1_amd64.deb")
LICENSE = "Doc/LICENSE-EN.txt"
PACKAGES = ("cndrvcups-common", "cndrvcups-capt")
# What captfilter and the captmon* status monitors (32-bit) load; with these they find all their libraries.
I386_LIBRARIES = ("libc6:i386", "libpopt0:i386", "libxml2:i386", "zlib1g:i386", "libstdc++6:i386",
                  "libgcc-s1:i386")

CACHE_DIR = Path("/var/cache/caramos-driver-check")
STATE_DIR = Path("/var/lib/caramos-driver-check/canon-capt")
CCPD = Path("/usr/sbin/ccpd")
CCPDADMIN = Path("/usr/sbin/ccpdadmin")
CCPD_CONF = Path("/etc/ccpd.conf")
PPD_DIR = Path("/usr/share/cups/model")
SERVICE = "caramos-canon-capt.service"
# The unit has no [Install] section, so the package does not enable it on every computer: the install adds this.
BOOT_WANTS = Path("/etc/systemd/system/multi-user.target.wants") / SERVICE
DROPIN = Path("/etc/systemd/system/caramos-canon-capt.service.d/50-printers.conf")
SYSV_UNIT = "ccpd.service"   # what systemd makes of Canon's /etc/init.d/ccpd; masked so ccpd never runs twice
QUEUE_URI = "ccp://localhost:59687"
DEVICE_DIR = Path("/dev/usb")
DEVICE_PREFIX = "canon-capt-"
SYSFS_USB = Path("/sys/bus/usb/devices")
CANON = "04a9"
# captdriver's CUPS filter (printer-driver-captdriver): where it is installed, the models it drives stay with it.
CAPTDRIVER_FILTER = Path("/usr/lib/cups/filter/rastertocapt")
CAPTDRIVER_PRODUCTS = frozenset({"2676", "26da", "266a", "26db", "271a"})   # knowledge.CAPTDRIVER_MODELS

ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "HOME": "/root",
       "DEBIAN_FRONTEND": "noninteractive"}
DOWNLOAD_ATTEMPTS = 4
DOWNLOAD_TIMEOUT = 60
CHUNK = 256 * 1024
USER_AGENT = "CaramOS-Driver-Check"


@dataclass(frozen=True)
class Model:
    key: str      # the queue name and the name in the network printer form
    name: str     # what the printer is sold as
    ppd: str      # Canon's PPD (the English "K" one)
    network: bool = False   # sold with a network port, or with Canon's network board


# Canon's model list (Doc/README-capt-2.71UK.txt), with the models its README says work on a network.
MODELS = {model.key: model for model in (
    Model("LBP1120", "LBP-1120", "CNCUPSLBP1120CAPTK.ppd"),
    Model("LBP1210", "LBP-1210", "CNCUPSLBP1210CAPTK.ppd"),
    Model("LBP2900", "LBP2900/LBP2900B", "CNCUPSLBP2900CAPTK.ppd"),
    Model("LBP3000", "LBP3000", "CNCUPSLBP3000CAPTK.ppd"),
    Model("LBP3050", "LBP3010/LBP3018/LBP3050", "CNCUPSLBP3050CAPTK.ppd"),
    Model("LBP3150", "LBP3100/LBP3108/LBP3150", "CNCUPSLBP3150CAPTK.ppd"),
    Model("LBP3200", "LBP3200", "CNCUPSLBP3200CAPTK.ppd"),
    Model("LBP3210", "LBP3210", "CNCUPSLBP3210CAPTK.ppd"),
    Model("LBP3250", "LBP3250", "CNCUPSLBP3250CAPTK.ppd"),
    Model("LBP3300", "LBP3300", "CNCUPSLBP3300CAPTK.ppd", network=True),
    Model("LBP3310", "LBP3310", "CNCUPSLBP3310CAPTK.ppd", network=True),
    Model("LBP3500", "LBP3500", "CNCUPSLBP3500CAPTK.ppd", network=True),
    Model("LBP5000", "LBP5000", "CNCUPSLBP5000CAPTK.ppd", network=True),
    Model("LBP5050", "LBP5050", "CNCUPSLBP5050CAPTK.ppd", network=True),
    Model("LBP5100", "LBP5100", "CNCUPSLBP5100CAPTK.ppd"),
    Model("LBP5300", "LBP5300", "CNCUPSLBP5300CAPTK.ppd", network=True),
    Model("LBP6018", "LBP6000/LBP6018", "CNCUPSLBP6018CAPTK.ppd"),
    Model("LBP6020", "LBP6020", "CNCUPSLBP6020CAPTK.ppd"),
    Model("LBP6200", "LBP6200", "CNCUPSLBP6200CAPTK.ppd"),
    Model("LBP6300", "LBP6300dn", "CNCUPSLBP6300CAPTK.ppd", network=True),
    Model("LBP6300n", "LBP6300n", "CNCUPSLBP6300nCAPTK.ppd", network=True),
    Model("LBP6310", "LBP6310dn", "CNCUPSLBP6310CAPTK.ppd", network=True),
    Model("LBP7018C", "LBP7010C/LBP7018C", "CNCUPSLBP7018CCAPTK.ppd"),
    Model("LBP7200C", "LBP7200C/LBP7200Cdn", "CNCUPSLBP7200CCAPTK.ppd", network=True),
    Model("LBP7210C", "LBP7210Cdn", "CNCUPSLBP7210CCAPTK.ppd", network=True),
    Model("LBP9100C", "LBP9100Cdn", "CNCUPSLBP9100CCAPTK.ppd", network=True),
    Model("LBP9200C", "LBP9200C", "CNCUPSLBP9200CCAPTK.ppd", network=True),
)}

# USB product IDs (knowledge.CAPT_PRINTERS) -> the model whose PPD drives it. Canon's driver has no PPD for the
# LBP810 (260a), LBP3600 (2654) and LBP5200 (266e).
USB_MODELS = {
    "2617": "LBP1210", "262b": "LBP1120", "2636": "LBP3200", "2657": "LBP3210", "266a": "LBP3000",
    "2676": "LBP2900", "2679": "LBP5000", "267e": "LBP3300", "268b": "LBP3500", "26a1": "LBP5300",
    "26a4": "LBP5100", "26b9": "LBP3310", "26ba": "LBP5050", "26da": "LBP3050", "26db": "LBP3150",
    "26ea": "LBP9100C", "26f1": "LBP7200C", "26ff": "LBP6300", "271a": "LBP6018", "271b": "LBP6200",
    "271c": "LBP7018C", "2771": "LBP6020",
}

NET_TARGET = re.compile(r"^canon-capt-net:(?P<model>[A-Za-z0-9]{4,12})@(?P<address>[0-9.]{7,15})$")
INSTALL_TARGET = "canon-capt"

Emit = Callable[..., None]


class CanonError(RuntimeError):
    """A step that failed, with the code the window turns into words (install.error_text)."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


# Targets ---------------------------------------------------------------------------------------


def is_target(target: str) -> bool:
    return target == INSTALL_TARGET or target.startswith("canon-capt-net:")


def network_target(model: str, address: str) -> str:
    return f"canon-capt-net:{model}@{address}"


def parse_network_target(target: str) -> tuple[Model, str]:
    """(model, printer address) of canon-capt-net:<model>@<IPv4>; ValueError when it is not one."""

    match = NET_TARGET.fullmatch(target)
    if match is None or match["model"] not in MODELS:
        raise ValueError(f"not a Canon network printer target: {target!r}")
    return MODELS[match["model"]], valid_address(match["address"])


def valid_address(text: str) -> str:
    """The printer's IPv4 address, written the usual way; ValueError for anything a printer cannot have."""

    address = ipaddress.IPv4Address(text.strip())
    if address.is_loopback or address.is_multicast or address.is_unspecified or address.is_reserved \
            or str(address) == "255.255.255.255":
        raise ValueError(f"not a printer address: {text!r}")
    return str(address)


# This computer ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class UsbPrinter:
    product: str        # USB product ID
    serial: str
    sysfs: str          # /sys/bus/usb/devices/<name>

    @property
    def model(self) -> Model | None:
        key = USB_MODELS.get(self.product)
        return MODELS[key] if key else None

    @property
    def device(self) -> str:
        """The fixed name 72-caramos-canon-capt.rules gives the printer's /dev/usb/lpN."""
        return str(DEVICE_DIR / f"{DEVICE_PREFIX}{self.product}-{self.serial}")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _entries(directory: Path) -> list[Path]:
    try:
        return sorted(directory.iterdir())
    except OSError:
        return []


def usb_printers(sysfs: Path = SYSFS_USB) -> list[UsbPrinter]:
    """Canon CAPT printers plugged in that Canon's driver drives."""

    found = []
    for entry in _entries(sysfs):
        if _read(entry / "idVendor").lower() != CANON:
            continue
        product = _read(entry / "idProduct").lower()
        if product in USB_MODELS:
            found.append(UsbPrinter(product, _read(entry / "serial"), str(entry)))
    return found


def installed(root: Path = Path("/")) -> bool:
    return (root / CCPD.relative_to("/")).is_file() and (root / CCPDADMIN.relative_to("/")).is_file()


def registered(text: str) -> dict[str, str]:
    """{queue name: device path} from ccpd.conf (<Printer name> ... DevicePath ... </Printer>)."""

    printers: dict[str, str] = {}
    name = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        opening = re.fullmatch(r"<Printer\s+(\S+)\s*>", line)
        if opening:
            name = opening.group(1)
            continue
        if line.startswith("</Printer"):
            name = ""
            continue
        if name and line.split(None, 1)[0] == "DevicePath" and len(line.split(None, 1)) == 2:
            printers[name] = line.split(None, 1)[1].strip()
    return printers


def read_registered(path: Path = CCPD_CONF) -> dict[str, str]:
    return registered(_read(path)) if path.is_file() else {}


def network_addresses(printers: dict[str, str]) -> list[str]:
    """The addresses of the network printers ccpd talks to (DevicePath net:<address>)."""

    addresses = []
    for path in printers.values():
        if path.startswith("net:"):
            try:
                address = valid_address(path[4:])
            except ValueError:
                continue
            if address not in addresses:
                addresses.append(address)
    return addresses


def dropin_text(addresses: list[str]) -> str:
    return ("# Written by CaramOS Driver Check: the network printers Canon's daemon may talk to, besides this\n"
            "# computer (caramos-canon-capt.service allows localhost only).\n"
            "[Service]\n"
            f"IPAddressAllow={' '.join(addresses)}\n")


def blocking_processes(proc: Path = Path("/proc")) -> list[tuple[int, str]]:
    """Processes Canon's maintainer scripts would take for ccpd: "ccpd" or "captmon" in their `ps awx` line.

    Canon's own daemons (ccpd, captmon*) are not in the list: they are stopped before. The caller is not either.
    """

    found = []
    me = os.getpid()
    for entry in _entries(proc):
        if not entry.name.isdigit() or int(entry.name) == me:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
            comm = (entry / "comm").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        line = raw.replace(b"\0", b" ").decode("utf-8", errors="replace").strip() or f"[{comm}]"
        if "ccpd" not in line and "captmon" not in line:
            continue
        if comm == "ccpd" or comm.startswith("captmon"):
            continue
        found.append((int(entry.name), line))
    return found


def canon_processes(proc: Path = Path("/proc")) -> list[int]:
    pids = []
    for entry in _entries(proc):
        if not entry.name.isdigit():
            continue
        comm = _read(entry / "comm")
        if comm == "ccpd" or comm.startswith("captmon"):
            pids.append(int(entry.name))
    return pids


# Running things --------------------------------------------------------------------------------


def _run(args: list[str], emit: Emit | None = None, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(args, env=ENV, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, check=False, timeout=300)
    if emit is not None:
        for line in result.stdout.splitlines():
            if line.strip():
                emit("log", line=line)
    if check and result.returncode != 0:
        raise CanonError("setup", f"{' '.join(args)} failed with exit code {result.returncode}")
    return result


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return _run(["systemctl", *args], check=False)


def _refuse_lookalikes(emit: Emit) -> None:
    others = blocking_processes()
    if others:
        for pid, line in others:
            emit("log", line=f"Program {pid} has 'ccpd' or 'captmon' in its command line: {line[:200]}")
        raise CanonError("canon-busy", "close the programs above first: Canon's install would kill them")


def stop_daemon(emit: Emit) -> None:
    """Stop Canon's daemon and its status monitors, which ignore SIGTERM, for Canon's maintainer scripts.

    Those scripts kill whatever else has "ccpd" or "captmon" in its command line: with such a program running,
    nothing is stopped and CanonError("canon-busy") says which one it is.
    """

    _refuse_lookalikes(emit)
    _systemctl("stop", SERVICE)
    for pid in canon_processes():
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    for _ in range(20):
        if not canon_processes():
            break
        time.sleep(0.1)
    _refuse_lookalikes(emit)   # one that started meanwhile


# Download --------------------------------------------------------------------------------------


def download(emit: Emit, start: int, end: int, url: str = TARBALL_URL, size: int = TARBALL_SIZE,
             sha256: str = TARBALL_SHA256, directory: Path = CACHE_DIR) -> Path:
    """Canon's archive, downloaded (resuming a cut download) and checked; progress goes from start to end %."""

    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    target = directory / url.rsplit("/", 1)[-1]
    if target.is_file() and target.stat().st_size == size and _sha256(target) == sha256:
        emit("progress", percent=end)
        return target
    last_error = ""
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        have = target.stat().st_size if target.is_file() else 0
        if have > size:
            target.unlink()
            have = 0
        headers = {"User-Agent": USER_AGENT}
        if have:
            headers["Range"] = f"bytes={have}-"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                        timeout=DOWNLOAD_TIMEOUT) as response:
                if have and response.status != 206:
                    have = 0   # the server sent the whole file again
                shown = -1
                with target.open("ab" if have else "wb") as handle:
                    while True:
                        chunk = response.read(CHUNK)
                        if not chunk:
                            break
                        handle.write(chunk)
                        have += len(chunk)
                        percent = start + (end - start) * min(have, size) // size
                        if percent != shown:
                            emit("progress", percent=percent)
                            shown = percent
        except OSError as exc:   # urllib.error.URLError and socket timeouts are OSErrors
            last_error = str(exc)
            emit("log", line=f"Download from Canon interrupted ({exc}), attempt {attempt}/{DOWNLOAD_ATTEMPTS}")
            time.sleep(min(10, 2 * attempt))
            continue
        if have == size:
            break
        last_error = f"got {have} of {size} bytes"
    if not target.is_file() or target.stat().st_size != size:
        raise CanonError("download", f"could not download Canon's driver from {url}: {last_error}")
    digest = _sha256(target)
    if digest != sha256:
        target.unlink()
        raise CanonError("checksum", f"Canon's file changed: SHA-256 {digest}, expected {sha256}")
    emit("log", line=f"Downloaded {url} ({size} bytes, SHA-256 {sha256})")
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract(tarball: Path, directory: Path) -> tuple[list[Path], Path]:
    """Only the two amd64 packages and the licence, as plain files: ([debs], licence)."""

    wanted = {f"{TARBALL_ROOT}/{name}": Path(name).name for name in (*DEBS, LICENSE)}
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, mode=0o700)
    with tarfile.open(tarball, "r:gz") as archive:
        for member in archive.getmembers():
            name = wanted.get(member.name)
            if name is None:
                continue
            if not member.isfile():
                raise CanonError("checksum", f"{member.name} in Canon's archive is not a plain file")
            source = archive.extractfile(member)
            assert source is not None
            with (directory / name).open("wb") as handle:
                shutil.copyfileobj(source, handle)
    missing = [name for name in wanted.values() if not (directory / name).is_file()]
    if missing:
        raise CanonError("checksum", f"Canon's archive lacks {', '.join(missing)}")
    return [directory / Path(name).name for name in DEBS], directory / Path(LICENSE).name


# Install ---------------------------------------------------------------------------------------


def _ensure_i386(emit: Emit) -> bool:
    """Turn on 32-bit packages; True when they were off (the package lists then need an update)."""

    foreign = _run(["dpkg", "--print-foreign-architectures"], check=False).stdout.split()
    if "i386" in foreign:
        return False
    emit("log", line="dpkg --add-architecture i386")
    _run(["dpkg", "--add-architecture", "i386"])
    return True


def configure_service(emit: Emit) -> None:
    """Canon's daemon at boot through the CaramOS unit, never through Canon's init script."""

    _systemctl("mask", SYSV_UNIT)
    BOOT_WANTS.parent.mkdir(parents=True, exist_ok=True)
    if not BOOT_WANTS.is_symlink():
        BOOT_WANTS.symlink_to(f"/usr/lib/systemd/system/{SERVICE}")
    write_dropin(read_registered())
    _systemctl("daemon-reload")
    emit("log", line=f"{SERVICE} starts at boot")


def write_dropin(printers: dict[str, str]) -> bool:
    """The drop-in letting ccpd reach the network printers; True when it changed."""

    addresses = network_addresses(printers)
    if not addresses:
        if DROPIN.exists():
            DROPIN.unlink()
            return True
        return False
    text = dropin_text(addresses)
    if _read(DROPIN) == text.strip():
        return False
    DROPIN.parent.mkdir(parents=True, exist_ok=True)
    DROPIN.write_text(text, encoding="utf-8")
    return True


def install_driver(emit: Emit, run_apt: Callable[[list[str], int, int], int]) -> list[str]:
    """Download, check and install Canon's driver unless it is there; the packages installed."""

    if installed():
        emit("log", line="Canon's CAPT driver is installed already")
        emit("progress", percent=85)
        return []
    emit("stage", stage="canon-download")
    tarball = download(emit, 10, 55)
    debs, licence = extract(tarball, CACHE_DIR / "canon-capt")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(licence, STATE_DIR / licence.name)
    stop_daemon(emit)
    if _ensure_i386(emit) and run_apt(["update"], 55, 60) != 0:
        emit("log", line="apt-get update reported errors; installing from the lists it has")
    emit("stage", stage="install")
    code = run_apt(["install", "-y", "--", *(str(deb) for deb in debs), *I386_LIBRARIES], 60, 85)
    if code != 0:
        raise CanonError("apt", "installing Canon's packages failed")
    shutil.rmtree(CACHE_DIR / "canon-capt", ignore_errors=True)
    tarball.unlink(missing_ok=True)
    if not installed():
        raise CanonError("apt", "Canon's packages are installed but ccpd is missing")
    return [*PACKAGES, *I386_LIBRARIES]


# Print queues ----------------------------------------------------------------------------------


def queues() -> dict[str, str]:
    """{queue: device URI} of every CUPS queue."""

    result = _run(["lpstat", "-v"], check=False)
    found = {}
    for line in result.stdout.splitlines():
        match = re.match(r"^device for (\S+): (\S+)", line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def _free_name(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    number = 2
    while f"{base}-{number}" in taken:
        number += 1
    return f"{base}-{number}"


def add_queue(name: str, model: Model, device: str, emit: Emit, description: str) -> None:
    ppd = PPD_DIR / model.ppd
    if not ppd.is_file():
        raise CanonError("setup", f"Canon's driver has no {ppd}")
    _run(["lpadmin", "-p", name, "-P", str(ppd), "-v", QUEUE_URI, "-D", description, "-E",
          "-o", "PageSize=A4", "-o", "printer-is-shared=false"], emit)
    _run([str(CCPDADMIN), "-p", name, "-o", device], emit)
    emit("log", line=f"Print queue {name}: {model.name} at {device}")


def _uri_serial(uri: str) -> str:
    """The serial number in a CUPS USB device URI: usb://Canon/LBP6300?serial=0000A1B2C3D4."""

    return urllib.parse.parse_qs(urllib.parse.urlsplit(uri).query).get("serial", [""])[0]


def setup_usb(emit: Emit) -> list[str]:
    """A queue for each Canon CAPT printer plugged in that has none; the queues added.

    A usb:// queue for such a printer (made before CaramOS 1.3.7, or by hand) bypasses ccpd and hangs: it goes.
    Where captdriver is installed, the models it drives keep it, with their usb:// queues.
    """

    captdriver = CAPTDRIVER_FILTER.is_file()
    printers = [printer for printer in usb_printers() if printer.model is not None
                and not (captdriver and printer.product in CAPTDRIVER_PRODUCTS)]
    if not printers:
        return []
    known = read_registered()
    every = queues()
    added = []
    for printer in printers:
        for name, uri in list(every.items()):
            if uri.startswith("usb://Canon/") and printer.serial and _uri_serial(uri) == printer.serial:
                _run(["lpadmin", "-x", name], emit, check=False)
                emit("log", line=f"Removed print queue {name} ({uri}): it bypassed Canon's daemon")
                del every[name]
        if printer.device in known.values():
            continue
        model = printer.model
        assert model is not None
        name = _free_name(model.key, set(every) | set(known))
        add_queue(name, model, printer.device, emit, f"Canon {model.name}")
        known[name] = printer.device
        every[name] = QUEUE_URI
        added.append(name)
    return added


def setup_network(model: Model, address: str, emit: Emit) -> str:
    """A queue for a network printer, or the queue it has already; its name."""

    known = read_registered()
    for name, path in known.items():
        if path == f"net:{address}":
            emit("log", line=f"{address} has print queue {name} already")
            return name
    name = _free_name(f"{model.key}-LAN", set(queues()) | set(known))
    add_queue(name, model, f"net:{address}", emit, f"Canon {model.name} ({address})")
    return name


def restart(emit: Emit) -> None:
    changed = write_dropin(read_registered())
    if changed:
        _systemctl("daemon-reload")
    result = _systemctl("restart", SERVICE)
    if result.returncode != 0:
        emit("log", line=result.stdout.strip())
        raise CanonError("setup", f"{SERVICE} did not start")


# Entry points (from caramos-driver-check-helper, as root) --------------------------------------


def install(targets: list[str], emit: Emit, run_apt: Callable[[list[str], int, int], int],
            online: Callable[[], bool]) -> tuple[bool, bool, list[str], str]:
    """(ok, restart needed, packages installed, error) for canon-capt and canon-capt-net:<model>@<address>."""

    networks = [parse_network_target(target) for target in targets if target != INSTALL_TARGET]
    try:
        if INSTALL_TARGET in targets and not any(printer.model for printer in usb_printers()):
            raise CanonError("refused", "no Canon CAPT printer that Canon's driver drives is plugged in")
        if not installed():
            if not online():
                return False, False, [], "offline"
            # The 32-bit libraries must be the version of their 64-bit twins: the lists must be current.
            emit("stage", stage="update")
            if run_apt(["update"], 0, 8) != 0:
                emit("log", line="apt-get update reported errors; installing from the lists it has")
        packages = install_driver(emit, run_apt)
        emit("stage", stage="canon-printers")
        configure_service(emit)
        names = setup_usb(emit)
        for model, address in networks:
            names.append(setup_network(model, address, emit))
        restart(emit)
        for name in names:
            emit("printer", name=name)
        emit("progress", percent=100)
        return True, False, packages, ""
    except CanonError as exc:
        emit("log", line=str(exc))
        return False, False, [], exc.code


def setup(emit: Emit) -> bool:
    """Plugged-in printers, from caramos-canon-capt-setup.service: queues for new ones, then a restart of ccpd,
    whose status monitor holds the device the printer had before it was unplugged."""

    if not installed():
        return True
    try:
        setup_usb(emit)
        restart(emit)
    except CanonError as exc:
        emit("log", line=str(exc))
        return False
    return True


def remove(emit: Emit, run_apt: Callable[[list[str], int, int], int]) -> tuple[bool, str]:
    """Canon's driver, its queues and what CaramOS set up around it; the 32-bit libraries stay."""

    try:
        printers = read_registered()
        stop_daemon(emit)
        every = queues()
        for name in printers:
            if installed():
                _run([str(CCPDADMIN), "-x", name], emit, check=False)
            if every.get(name, "").startswith("ccp:"):
                _run(["lpadmin", "-x", name], emit, check=False)
        stop_daemon(emit)   # ccpdadmin may start what it talks to
        if BOOT_WANTS.is_symlink():
            BOOT_WANTS.unlink()
        if DROPIN.exists():
            DROPIN.unlink()
        try:
            DROPIN.parent.rmdir()
        except OSError:
            pass   # not there, or someone put another drop-in in it
        _systemctl("unmask", SYSV_UNIT)
        _systemctl("daemon-reload")
        if run_apt(["purge", "-y", *PACKAGES], 20, 95) != 0:
            raise CanonError("apt", "removing Canon's packages failed")
        _systemctl("daemon-reload")   # forget the unit systemd made of Canon's init script
        shutil.rmtree(STATE_DIR, ignore_errors=True)
        emit("progress", percent=100)
        return True, ""
    except CanonError as exc:
        emit("log", line=str(exc))
        if installed() and BOOT_WANTS.is_symlink():
            _systemctl("start", SERVICE)   # the printers keep working
        return False, exc.code

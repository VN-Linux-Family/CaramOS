"""Privileged Driver Check helper, started by the window through pkexec.

    caramos-driver-check-helper install <target>...

A target is an NVIDIA driver series ("nvidia:580-open") or a driver package ("bcmwl-kernel-source"). The
helper does not trust the caller: it asks UbuntuDrivers for the drivers of the hardware it finds itself
and refuses any target that is not one of them, or not one Ubuntu installs automatically (drivers.py).
NVIDIA goes through UbuntuDrivers' desktop package list, like `ubuntu-drivers install nvidia:580-open`,
so the signed kernel modules come with it: those of the newest kernel of the series, which then comes too
(kernel_for_modules()). Offline, the Broadcom driver installs from the CaramOS USB stick through Linux
Mint's mintdrivers-add-live-media.

Before installing, the helper checks that the disks have room for what APT is about to download and unpack,
and for the initramfs files the drivers and new kernels add to /boot. When one does not, it installs nothing:
an install that runs out of room halfway leaves dpkg broken, and every later install fails until it is fixed.

Progress goes to stdout as JSON lines (events.py):

    {"event": "stage", "stage": "update" | "media" | "install" | "finish"}
    {"event": "progress", "percent": 0-100}
    {"event": "log", "line": "..."}
    {"event": "space", "path": "/", "need": bytes, "free": bytes}   (one per file system that lacks room)
    {"event": "done", "ok": true, "restart": true, "packages": [...], "error": ""}
"""

from __future__ import annotations

import fcntl
import io
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .drivers import NVIDIA_DRIVER, ON_INSTALL_MEDIA, one_click
from .events import emit

LOCK_FILE = Path("/run/caramos-driver-check.lock")
MAX_TARGETS = 4
TIMEOUT = 3600
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "HOME": "/root",
       "DEBIAN_FRONTEND": "noninteractive"}
# APT's status lines come on stdout, between its output. dpkg keeps the pty APT gives it (Dpkg::Use-Pty, the
# default): APT marks its status fd close-on-exec, so with Dpkg::Use-Pty=0 dpkg and every maintainer script ran
# with stdout closed and failed at their first echo. update-initramfs is one of them, so every NVIDIA install
# broke dpkg (ticket H-1110).
APT = ["apt-get", "-o", "DPkg::Lock::Timeout=600", "-o", "APT::Status-Fd=1"]
# Linking the NVIDIA kernel modules while installing prints tens of thousands of these, which tell users nothing.
OBJTOOL_WARNING = re.compile(r"^\S+\.o: warning: objtool: ")
TARGET_RE = re.compile(r"^(nvidia:\d{3}(-server)?(-open)?|[a-z0-9][a-z0-9+.-]{1,80})$")
ADD_MEDIA = "mintdrivers-add-live-media"
REMOVE_MEDIA = "mintdrivers-remove-live-media"
MEDIA_INFO = Path("/media/mintdrivers/.disk/info")
# What Driver Manager unloads before loading Broadcom's wl driver, so Wi-Fi works without a restart.
BROADCOM_CONFLICTS = ("b44", "b43", "b43legacy", "ssb", "brcmsmac", "bcma")

MIB = 1024 * 1024
# Room kept beyond APT's own figures: the NVIDIA modules are linked while installing and are in no
# Installed-Size (about 200 MiB for 580), and a nearly full file system (btrfs above all) fails before it
# reaches zero. Asking for a little too much only means freeing a little more; too little breaks dpkg.
ROOT_MARGIN = 1024 * MIB
BOOT_MARGIN = 32 * MIB
# vmlinuz, System.map and config of one kernel, which sit in /boot next to its initramfs.
KERNEL_FILES = 64 * MIB
# The size of an initramfs when the running kernel's cannot be read.
DEFAULT_INITRAMFS = 128 * MIB
KERNEL_IMAGE = re.compile(r"^linux-image-(\d\S*)$")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


class UsageError(ValueError):
    pass


class Refused(RuntimeError):
    """A target that is not a driver for this computer, or a step that cannot run."""


def parse_args(argv: list[str]) -> list[str]:
    if len(argv) < 2 or argv[0] != "install":
        raise UsageError("usage: caramos-driver-check-helper install <target>...")
    targets = argv[1:]
    if len(targets) > MAX_TARGETS or len(set(targets)) != len(targets):
        raise UsageError("too many or duplicate targets")
    for target in targets:
        if not TARGET_RE.fullmatch(target):
            raise UsageError(f"invalid target: {target!r}")
    return targets


def apt_progress(line: str) -> float | None:
    """APT::Status-Fd lines: dlstatus:/pmstatus:<pkg>:<percent>:<text> -> 0..1, downloads first."""

    parts = line.split(":", 3)
    if len(parts) < 3 or parts[0] not in ("dlstatus", "pmstatus"):
        return None
    try:
        percent = float(parts[2])
    except ValueError:
        return None
    return percent / 200 if parts[0] == "dlstatus" else 0.5 + percent / 200


def online() -> bool:
    """The same test Driver Manager makes."""

    try:
        socket.create_connection(("8.8.8.8", 53), timeout=5).close()
        return True
    except OSError:
        return False


def _stream(args: list[str], on_line: Callable[[str], None]) -> int:
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=ENV,
                               stdin=subprocess.DEVNULL)
    timer = threading.Timer(TIMEOUT, process.kill)
    timer.start()
    assert process.stdout is not None
    # Lines end at \n only: on dpkg's pty they end in \r\n, and a line redrawn in place
    # ("Reading database ... 5%\r...") keeps only its last state.
    output = io.TextIOWrapper(process.stdout, encoding="utf-8", errors="replace", newline="\n")
    try:
        for raw in output:
            on_line(raw.rstrip("\r\n").rsplit("\r", 1)[-1])
        return process.wait()
    finally:
        timer.cancel()
        output.close()


def run_apt(args: list[str], start: int, end: int) -> int:
    """Run apt-get, mapping its progress to start..end percent of the whole run."""

    hidden = 0

    def on_line(line: str) -> None:
        nonlocal hidden
        fraction = apt_progress(line)
        if fraction is not None:
            emit("progress", percent=int(start + (end - start) * fraction))
        elif OBJTOOL_WARNING.match(line):
            hidden += 1
        elif line.strip():
            emit("log", line=line)

    code = _stream([*APT, *args], on_line)
    if hidden:
        emit("log", line=f"({hidden} objtool warnings from linking the NVIDIA kernel modules are not shown)")
    return code


def _detect():
    import apt_pkg
    from UbuntuDrivers import detect

    apt_pkg.init_config()
    apt_pkg.init_system()
    return apt_pkg, detect, apt_pkg.Cache(None)


def plan(targets: list[str], cache, detect) -> list[str]:
    """The packages to install for the targets; Refused when a target is not for this computer."""

    drivers = detect.system_driver_packages(cache, include_oem=False)
    packages: list[str] = []
    for target in targets:
        if target.startswith("nvidia:"):
            name = "nvidia-driver-" + target.split(":", 1)[1]
            if name not in drivers or not NVIDIA_DRIVER.match(name):
                raise Refused(f"{name} is not a driver for this computer")
            wanted = detect.get_desktop_package_list(cache, include_oem=False, driver_string=target)
            if not wanted:
                # No signed kernel modules for this kernel: build them with DKMS, as Driver Manager does.
                wanted = detect.get_desktop_package_list(cache, include_oem=False, driver_string=target,
                                                         include_dkms=True)
            packages.extend(wanted)
            packages.extend(kernel_for_modules(wanted, cache))
        else:
            if target not in drivers or not one_click(target):
                raise Refused(f"{target} is not a driver for this computer")
            try:
                installed = cache[target].current_ver is not None
            except KeyError:
                installed = False
            if not installed:
                packages.append(target)
    return list(dict.fromkeys(packages))


MODULES_META = re.compile(r"^linux-modules-nvidia-\d+(?:-server)?(?:-open)?-(?P<kernel>[a-z].*)$")


def kernel_for_modules(packages: list[str], cache) -> list[str]:
    """The kernel metapackage of the NVIDIA modules metapackage in packages (linux-generic-hwe-24.04).

    The modules metapackage follows the newest kernel of its series, and its install links the modules
    against that kernel's headers. On a computer not updated since installing (the CaramOS ISO has 6.14,
    the series is at 7.0 by now), APT brought the new kernel's modules without its headers: the link failed
    and dpkg was left broken. Installing the kernel metapackage too brings the headers and the rest of that
    kernel; on an up-to-date computer it changes nothing.
    """

    found = []
    for package in packages:
        match = MODULES_META.match(package)
        if not match:
            continue
        kernel = f"linux-{match.group('kernel')}"
        try:
            if cache[kernel].has_versions:
                found.append(kernel)
        except KeyError:
            continue
    return found


@dataclass(frozen=True)
class Needs:
    """What an install takes, as APT resolves it: bytes to download, bytes unpacked, and the kernels it adds."""

    download: int
    installed: int
    kernels: tuple[str, ...] = ()


@dataclass(frozen=True)
class Shortage:
    """A file system (by its mount point) without room for the install."""

    path: str
    need: int
    free: int


def needs(cache, packages: list[str]) -> Needs:
    """Mark packages the way apt-get install does and read the sizes APT would print.

    The download leaves out archives APT already has. The installed size is the change in Installed-Size, so
    upgrades count only what they add. A kernel the install adds (linux-image-7.0.0-42-generic for a modules
    metapackage of a newer kernel, see kernel_for_modules()) also brings an initramfs in /boot.
    """

    import apt_pkg

    depcache = apt_pkg.DepCache(cache)
    with apt_pkg.ActionGroup(depcache):
        for name in packages:
            depcache.mark_install(cache[name])
    sources = apt_pkg.SourceList()
    sources.read_main_list()
    fetcher = apt_pkg.Acquire()
    try:
        apt_pkg.PackageManager(depcache).get_archives(fetcher, sources, apt_pkg.PackageRecords(cache))
        download = fetcher.fetch_needed
    finally:
        fetcher.shutdown()
    kernels = tuple(match.group(1) for package in cache.packages
                    if depcache.marked_install(package) and (match := KERNEL_IMAGE.match(package.name)))
    return Needs(download, depcache.usr_size, kernels)


def mount_point(path: str, stat: Callable = os.stat) -> str:
    """The mount point of the file system path is on: its highest parent on the same device."""

    path = os.path.abspath(path)
    device = stat(path).st_dev
    while path != "/":
        parent = os.path.dirname(path)
        if stat(parent).st_dev != device:
            break
        path = parent
    return path


def shortages(need: Needs, archives: str, initramfs: int, *, stat: Callable = os.stat,
              statvfs: Callable = os.statvfs) -> list[Shortage]:
    """The file systems that lack room for the install.

    / takes the unpacked files, the archive cache the download, and /boot an initramfs for each new kernel plus
    the rebuilt one of the running kernel (the NVIDIA and DKMS packages rebuild it). When they share a file
    system, their needs add up there.
    """

    wanted = (
        ("/", max(need.installed, 0) + ROOT_MARGIN),
        ("/boot", len(need.kernels) * (initramfs + KERNEL_FILES) + initramfs + BOOT_MARGIN),
        (archives, need.download),
    )
    totals: dict[int, list] = {}
    for path, size in wanted:
        try:
            device = stat(path).st_dev
        except OSError:
            continue
        if device in totals:
            totals[device][1] += size
        else:
            totals[device] = [path, size]
    found = []
    for path, size in totals.values():
        info = statvfs(path)
        free = info.f_bavail * info.f_frsize
        if size > free:
            found.append(Shortage(mount_point(path, stat), size, free))
    return found


def check_space(cache, packages: list[str]) -> list[Shortage]:
    """The shortages of free space for installing packages; none when the estimate itself fails.

    The check only exists to stop an install that cannot finish, so an error in it lets the install go on.
    """

    try:
        import apt_pkg

        need = needs(cache, packages)
        archives = apt_pkg.config.find_dir("Dir::Cache::Archives") or "/var/cache/apt/archives"
        try:
            initramfs = os.stat(f"/boot/initrd.img-{os.uname().release}").st_size
        except OSError:
            initramfs = DEFAULT_INITRAMFS
        emit("log", line=f"Space needed: {need.download // MIB} MiB to download, {need.installed // MIB} MiB "
                         f"once installed, new kernels: {', '.join(need.kernels) or 'none'}")
        return shortages(need, archives, initramfs)
    except Exception as exc:   # noqa: BLE001 - a wrong estimate must not block a driver that fits
        emit("log", line=f"Could not check the free space ({type(exc).__name__}: {exc}); installing anyway")
        return []


def reload_broadcom() -> bool:
    """Start Broadcom's wl driver now; False when it needs a restart (or Secure Boot blocks it)."""

    subprocess.run(["modprobe", "-r", *BROADCOM_CONFLICTS], env=ENV, check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return subprocess.run(["modprobe", "wl"], env=ENV, check=False, stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL).returncode == 0


def install(targets: list[str]) -> tuple[bool, bool, list[str], str]:
    """(ok, restart needed, installed packages, error)."""

    media = False
    try:
        if online():
            emit("stage", stage="update")
            if run_apt(["update"], 0, 25) != 0:
                emit("log", line="apt-get update reported errors; installing from the lists it has")
        elif all(target in ON_INSTALL_MEDIA for target in targets) and shutil.which(ADD_MEDIA):
            emit("stage", stage="media")
            _stream([ADD_MEDIA], lambda line: emit("log", line=line) if line.strip() else None)
            media = True
            if not MEDIA_INFO.exists():
                return False, False, [], "no-media"
        else:
            return False, False, [], "offline"

        _apt_pkg, detect, cache = _detect()
        packages = plan(targets, cache, detect)
        if not packages:
            emit("progress", percent=100)
            return True, False, [], ""
        lacking = check_space(cache, packages)
        if lacking:
            for item in lacking:
                emit("space", path=item.path, need=item.need, free=item.free)
                emit("log", line=f"Not enough free space on {item.path}: {item.need // MIB} MiB needed, "
                                 f"{item.free // MIB} MiB free")
            return False, False, [], "space"
        nvidia = any(name.startswith("nvidia-") for name in packages)
        if nvidia:
            detect.nvidia_desktop_pre_installation_hook(packages)
        emit("stage", stage="install")
        code = run_apt(["install", "-y", "-o", "DPkg::options::=--force-confnew", "--", *packages], 25, 95)
        if code != 0:
            return False, False, [], "apt"
        emit("stage", stage="finish")
        restart = nvidia
        if nvidia:
            detect.nvidia_desktop_post_installation_hook()
        if any(name in ON_INSTALL_MEDIA for name in packages):
            restart = restart or not reload_broadcom()
        emit("progress", percent=100)
        return True, restart, packages, ""
    finally:
        if media and shutil.which(REMOVE_MEDIA):
            subprocess.run([REMOVE_MEDIA], env=ENV, check=False, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)


def main(argv: list[str] | None = None) -> int:
    try:
        targets = parse_args(sys.argv[1:] if argv is None else argv)
    except UsageError as exc:
        print(exc, file=sys.stderr)
        return EXIT_USAGE
    if os.geteuid() != 0:
        print("caramos-driver-check-helper must run as root (through pkexec)", file=sys.stderr)
        return EXIT_USAGE
    with LOCK_FILE.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            emit("done", ok=False, restart=False, packages=[], error="busy")
            return EXIT_FAILED
        try:
            ok, restart, packages, error = install(targets)
        except Refused as exc:
            emit("log", line=str(exc))
            ok, restart, packages, error = False, False, [], "refused"
        except Exception as exc:   # noqa: BLE001 - report anything to the window instead of a traceback
            emit("log", line=f"{type(exc).__name__}: {exc}")
            ok, restart, packages, error = False, False, [], "internal"
    emit("done", ok=ok, restart=restart, packages=packages, error=error)
    return EXIT_OK if ok else EXIT_FAILED

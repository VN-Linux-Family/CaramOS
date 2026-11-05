"""Privileged Driver Check helper, started by the window through pkexec.

    caramos-driver-check-helper install <target>...

A target is an NVIDIA driver series ("nvidia:580-open") or a driver package ("bcmwl-kernel-source"). The
helper does not trust the caller: it asks UbuntuDrivers for the drivers of the hardware it finds itself
and refuses any target that is not one of them, or not one Ubuntu installs automatically (drivers.py).
NVIDIA goes through UbuntuDrivers' desktop package list, like `ubuntu-drivers install nvidia:580-open`,
so the signed kernel modules for the running kernel come with it. Offline, the Broadcom driver installs
from the CaramOS USB stick through Linux Mint's mintdrivers-add-live-media.

Progress goes to stdout as JSON lines (events.py):

    {"event": "stage", "stage": "update" | "media" | "install" | "finish"}
    {"event": "progress", "percent": 0-100}
    {"event": "log", "line": "..."}
    {"event": "done", "ok": true, "restart": true, "packages": [...], "error": ""}
"""

from __future__ import annotations

import fcntl
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from .drivers import NVIDIA_DRIVER, ON_INSTALL_MEDIA, one_click
from .events import emit

LOCK_FILE = Path("/run/caramos-driver-check.lock")
MAX_TARGETS = 4
TIMEOUT = 3600
ENV = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8", "HOME": "/root",
       "DEBIAN_FRONTEND": "noninteractive"}
APT = ["apt-get", "-o", "DPkg::Lock::Timeout=600", "-o", "APT::Status-Fd=1", "-o", "Dpkg::Use-Pty=0"]
TARGET_RE = re.compile(r"^(nvidia:\d{3}(-server)?(-open)?|[a-z0-9][a-z0-9+.-]{1,80})$")
ADD_MEDIA = "mintdrivers-add-live-media"
REMOVE_MEDIA = "mintdrivers-remove-live-media"
MEDIA_INFO = Path("/media/mintdrivers/.disk/info")
# What Driver Manager unloads before loading Broadcom's wl driver, so Wi-Fi works without a restart.
BROADCOM_CONFLICTS = ("b44", "b43", "b43legacy", "ssb", "brcmsmac", "bcma")

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
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=ENV,
                               stdin=subprocess.DEVNULL, errors="replace")
    timer = threading.Timer(TIMEOUT, process.kill)
    timer.start()
    try:
        assert process.stdout is not None
        for raw in process.stdout:
            on_line(raw.rstrip("\n"))
        return process.wait()
    finally:
        timer.cancel()
        if process.stdout is not None:
            process.stdout.close()


def run_apt(args: list[str], start: int, end: int) -> int:
    """Run apt-get, mapping its progress to start..end percent of the whole run."""

    def on_line(line: str) -> None:
        fraction = apt_progress(line)
        if fraction is not None:
            emit("progress", percent=int(start + (end - start) * fraction))
        elif line.strip():
            emit("log", line=line)

    return _stream([*APT, *args], on_line)


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

"""Automatic updates ("Tự động cập nhật"): new CaramOS versions install by themselves, and every user who is logged in
is told afterwards. On by default; the Update Center has the switch.

The setting
    SETTINGS_FILE, AUTO_UPDATE=yes or no, which `sudo caramos-ota --auto-update on|off` writes, and the Update Center's
    switch through pkexec and HELPER (polkit action net.vietnamlinuxfamily.caramos-ota.auto-update: administrators
    only). Without the file, or with a value it cannot read, automatic updates are on: new installs and computers that
    update to this version have them on.

When an update installs
    caramos-ota-check.timer runs caramos-ota-check.service once a day (`caramos-ota --check`, with ProtectHome, which
    finds the update and writes it into state.json). When that check succeeds, its OnSuccess= starts UNIT, which runs
    `caramos-ota --auto-upgrade` (run() below) as root without ProtectHome: migrations change the settings of each
    user, as an update from the Update Center does. With automatic updates on and an update waiting, run() starts
    `caramos-ota --upgrade --yes --unattended`, the Update Center's own update, without questions (UNATTENDED_ENV: no
    debconf questions, dpkg keeps configuration files an administrator changed), at a low priority (see the unit),
    while a logind lock asks anyone who shuts the computer down to wait.

When it waits (skip_reason)
    On the live USB; when / is an overlay (CaramOS Doanh nghiệp's frozen shared computers); on a metered connection
    (NetworkManager); on battery under MIN_BATTERY percent; when the disks lack room (caramos_ota.diskspace, Driver
    Check's check); when APT or dpkg is busy, or another caramos-ota run holds the lock (an update started in the
    Update Center): then systemd tries again 15 minutes later (EXIT_RETRY, see the unit); when the last automatic try of
    the same update failed; when the update changes open desktops and someone is logged in to one (below). Nothing
    else happens then: the Update Center opens at the next login with the update and its Update button, as when
    automatic updates are off, and says why it waited.

Open desktops
    A migration that would change what someone sees on an open desktop (the panel rebuilt, the wallpaper, Fcitx
    restarted, `dconf update`, which Cinnamon 6.6 does not survive) has "unattended": "nobody-logged-in" in its
    manifest (registry.NOBODY_LOGGED_IN; the default, and every legacy migration): an automatic update that includes
    it waits until no one has a desktop open. The others say "anytime": what they change applies from the next login,
    or cannot be seen; in an automatic update they leave out the reloads that would show (context.unattended: the
    Start Menu is not reloaded, Fcitx is not started), so nothing moves on the screen while someone works. A
    migration whose visible part concerns each user's own settings changes the system at once and leaves that part
    for the next login of each user who is logged in (caramos_ota_update.deferred), and says "anytime" too: Show
    desktop and the Trash on the desktop (both from 1.5.1) do.

Telling the users
    The result goes to RESULT_FILE, which everyone can read. Each user's caramos-ota-auto-update-notify.path (a
    systemd user unit of the session) then runs `caramos-ota-notifier --auto-update-result`: "CaramOS đã cập nhật lên
    X.Y.Z" with "Xem có gì mới", or after a failure a notification whose button opens the Update Center's failure page
    with "Nhờ giúp đỡ". The login autostart does the same for what a user has not seen yet (caramos_ota_notifier).
"""

from __future__ import annotations

import fcntl
import json
import os
import pwd
import signal
import struct
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .constants import EXIT_ERROR, EXIT_LOCK, EXIT_OK, LOCK_FILE, STATE_DIR
from .diskspace import MIB, Needs, Shortage, shortages
from .logging_utils import log_error, log_info, log_warn, now_iso

SETTINGS_FILE = Path("/etc/caramos-ota/auto-update.conf")
SETTING = "AUTO_UPDATE"
SETTINGS_TEXT = """\
# CaramOS automatic updates: Update Center > Automatic updates, or sudo caramos-ota --auto-update on|off.
# yes: new CaramOS versions install by themselves; no: the Update Center asks first. Without this file: yes.
{key}={value}
"""
RESULT_FILE = STATE_DIR / "auto-update.json"
STATUS_KEY = "auto_update"   # the last automatic try, in state.json
UNIT = "caramos-ota-auto-update.service"
OTA_COMMAND = "/usr/bin/caramos-ota"
HELPER = "/usr/share/caramos-ota/auto-update/caramos-auto-update-helper"
APT_CONFIG = "/usr/share/caramos-ota/auto-update/apt.conf"

# The unit's RestartForceExitStatus: APT, dpkg or another CaramOS update was busy, try again a little later.
EXIT_RETRY = 75
MIN_BATTERY = 50
# What an update may take; the migrations decide what they install. With Driver Check's margins: about 1.5 GiB free
# where / and the package cache are.
OTA_NEEDS = Needs(download=256 * MIB, installed=256 * MIB)
APT_ARCHIVES = Path("/var/cache/apt/archives")
APT_LOCKS = (Path("/var/lib/dpkg/lock-frontend"), Path("/var/lib/dpkg/lock"), Path("/var/lib/apt/lists/lock"),
             APT_ARCHIVES / "lock")
POWER_SUPPLY = Path("/sys/class/power_supply")
PROC_CMDLINE = Path("/proc/cmdline")
PROC_MOUNTS = Path("/proc/mounts")
SYSTEM_LOCALE = Path("/etc/default/locale")
REBOOT_REQUIRED = Path("/run/reboot-required")
GRAPHICAL = ("x11", "wayland", "mir")
OUTPUT_LIMIT = 200_000   # characters of the update's output kept for the failure page and the help request

# The run without anyone to answer: no debconf or ucf questions, dpkg keeps a configuration file the administrator
# changed (APT_CONFIG: --force-confdef --force-confold), and needrestart, when installed, restarts no service.
UNATTENDED_ENV = {
    "DEBIAN_FRONTEND": "noninteractive",
    "DEBCONF_NONINTERACTIVE_SEEN": "true",
    "APT_LISTCHANGES_FRONTEND": "none",
    "UCF_FORCE_CONFFOLD": "1",
    "NEEDRESTART_SUSPEND": "1",
    "APT_CONFIG": APT_CONFIG,
    # caramos-ota writes to a pipe here: unbuffered, its lines stay in order with the warnings it sends to stderr.
    "PYTHONUNBUFFERED": "1",
}

# Why an automatic update waited; the Update Center words each one.
LIVE = "live"
OVERLAY = "overlayroot"
METERED = "metered"
BATTERY = "battery"
DISK = "disk"
APT_BUSY = "apt-busy"
OTA_BUSY = "ota-busy"
FAILED_BEFORE = "failed-before"
IN_USE = "in-use"
REASONS = (LIVE, OVERLAY, METERED, BATTERY, DISK, APT_BUSY, OTA_BUSY, FAILED_BEFORE, IN_USE)
RETRY = frozenset({APT_BUSY, OTA_BUSY})

# How a try ended (state.json and RESULT_FILE).
SKIPPED = "skipped"
RUNNING = "running"
DONE = "done"
FAILED = "failed"

# The reason shown to anyone who shuts the computer down while it updates, in the language of the system.
INHIBIT_WHY = {
    "vi": "CaramOS đang tự cập nhật. Chờ vài phút cho xong rồi hãy tắt máy.",
    "en": "CaramOS is updating itself. Wait a few minutes until it finishes before shutting down.",
}
INHIBIT_SECONDS = 4 * 3600   # longer than the unit lets an update run


# The setting -------------------------------------------------------------------------------------


def read_setting(path: Path | None = None) -> bool | None:
    """AUTO_UPDATE of the settings file: True, False, or None when the file or a clear value is missing."""

    try:
        text = (path or SETTINGS_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    value = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw = line.split("=", 1)
        if key.strip() != SETTING:
            continue
        word = raw.strip().strip("\"'").strip().lower()
        value = True if word in ("yes", "true", "on", "1") else False if word in ("no", "false", "off", "0") else None
    return value


def is_enabled(path: Path | None = None) -> bool:
    """Automatic updates are on unless the setting says no."""

    return read_setting(path) is not False


def set_enabled(enabled: bool, path: Path | None = None) -> None:
    """Write the setting (root): a new file renamed over the old one, readable by everyone."""

    path = path or SETTINGS_FILE
    path.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(SETTINGS_TEXT.format(key=SETTING, value="yes" if enabled else "no"))
        os.chmod(staging, 0o644)
        os.replace(staging, path)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise


def change_setting(enabled: bool, by: str, path: Path | None = None) -> None:
    """Write the setting and say so in the OTA log (init_log first)."""

    set_enabled(enabled, path)
    log_info(f"Automatic updates turned {'on' if enabled else 'off'} by {by}")


def caller(environ: dict[str, str] | None = None) -> str:
    """Who asked for the change: the account behind pkexec or sudo, else root."""

    env = os.environ if environ is None else environ
    for variable in ("PKEXEC_UID", "SUDO_UID"):
        value = env.get(variable, "")
        if value.isdigit():
            try:
                return pwd.getpwuid(int(value)).pw_name
            except KeyError:
                return f"uid {value}"
    return "root"


def helper_main(argv: list[str]) -> int:
    """The Update Center's switch: `pkexec caramos-auto-update-helper on|off`."""

    from .logging_utils import init_log

    if len(argv) != 1 or argv[0] not in ("on", "off"):
        print("Usage: caramos-auto-update-helper on|off")
        return 2
    if os.geteuid() != 0:
        print("Error: run through pkexec.")
        return 2
    init_log()
    try:
        change_setting(argv[0] == "on", f"{caller()} (Update Center)")
    except OSError as exc:
        log_error(f"Could not write {SETTINGS_FILE}: {exc}")
        print(f"Error: {exc}")
        return EXIT_ERROR
    return EXIT_OK


# What stops an automatic update now --------------------------------------------------------------


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def live_session(cmdline: Path | None = None) -> bool:
    """Running from the CaramOS USB stick (casper), whose changes are gone at shutdown."""

    return "boot=casper" in _read(cmdline or PROC_CMDLINE).split()


def overlay_root(mounts: Path | None = None) -> bool:
    """/ is an overlay: overlayroot, which CaramOS Doanh nghiệp uses to freeze shared computers (or the live USB)."""

    return any(len(fields) >= 3 and fields[1] == "/" and fields[2] == "overlay"
               for fields in map(str.split, _read(mounts or PROC_MOUNTS).splitlines()))


def metered(run=subprocess.run) -> bool:
    """NetworkManager says the connection is metered (a phone's hotspot, mobile broadband), or guesses so."""

    try:
        result = run(["busctl", "get-property", "org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager",
                      "org.freedesktop.NetworkManager", "Metered"],
                     capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    fields = (result.stdout or "").split()
    # "u 1" NM_METERED_YES, "u 3" NM_METERED_GUESS_YES; no NetworkManager: not metered.
    return result.returncode == 0 and len(fields) == 2 and fields[1] in ("1", "3")


def battery_low(root: Path | None = None, minimum: int = MIN_BATTERY) -> bool:
    """On battery, with the computer's own batteries under minimum percent. False on mains power, without a battery
    (a desktop computer), or when the level cannot be read."""

    try:
        supplies = sorted((root or POWER_SUPPLY).iterdir())
    except OSError:
        return False
    levels = []
    for supply in supplies:
        kind = _read(supply / "type")
        if kind == "Battery":
            if _read(supply / "scope") == "Device":
                continue   # a wireless mouse's or keyboard's
            if _read(supply / "status") in ("Charging", "Full", "Not charging"):
                return False   # plugged in
            level = _read(supply / "capacity")
            if level.isdigit():
                levels.append(int(level))
        elif _read(supply / "online") == "1":
            return False   # mains or USB-C power
    return bool(levels) and sum(levels) / len(levels) < minimum


def _locked(path: Path) -> bool:
    """Whether another process holds the fcntl lock APT and dpkg take on path (F_GETLK: this one takes nothing)."""

    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        # struct flock on amd64: short l_type, short l_whence, (padding), off_t l_start, off_t l_len, pid_t l_pid.
        query = struct.pack("hhqqi4x", fcntl.F_WRLCK, 0, 0, 0, 0)
        answer = fcntl.fcntl(fd, fcntl.F_GETLK, query)
        return struct.unpack("hhqqi4x", answer)[0] != fcntl.F_UNLCK
    except OSError:
        return False
    finally:
        os.close(fd)


def apt_busy(locks: tuple[Path, ...] | None = None) -> bool:
    """APT or dpkg is at work: Update Manager, the App Center, Driver Check, or apt in a terminal."""

    return any(_locked(lock) for lock in (APT_LOCKS if locks is None else locks))


def ota_busy(lock: Path | None = None) -> bool:
    """Another caramos-ota run holds the OTA lock: an update the person started in the Update Center, or a check."""

    try:
        fd = os.open(lock or LOCK_FILE, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    except OSError:
        return False
    finally:
        os.close(fd)   # also lets go of the lock if it was taken
    return False


def low_disk(archives: Path | None = None) -> list[Shortage]:
    """The file systems without room for an update (diskspace.shortages, with no kernel and no initramfs)."""

    try:
        return shortages(OTA_NEEDS, str(archives or APT_ARCHIVES), 0)
    except OSError:
        return []


def desktop_sessions(run=subprocess.run) -> list[str] | None:
    """The users who have a desktop open now (graphical sessions of user accounts, not the login screen's); None when
    logind cannot tell."""

    try:
        listed = run(["loginctl", "list-sessions", "--no-legend"], capture_output=True, text=True, timeout=15,
                     check=False)
        if listed.returncode != 0:
            return None
        users = set()
        for line in (listed.stdout or "").splitlines():
            fields = line.split()
            if not fields:
                continue
            shown = run(["loginctl", "show-session", fields[0], "-p", "Name", "-p", "Type", "-p", "Class", "-p",
                         "State"], capture_output=True, text=True, timeout=15, check=False)
            props = dict(item.split("=", 1) for item in (shown.stdout or "").splitlines() if "=" in item)
            if (props.get("Class") == "user" and props.get("Type") in GRAPHICAL
                    and props.get("State") in ("active", "online")):
                users.add(props.get("Name") or "?")
    except (OSError, subprocess.SubprocessError):
        return None
    return sorted(users)


def changes_open_desktops(plan, desktop: str | None = None) -> list[str]:
    """The pending migrations whose automatic run waits until nobody is logged in (registry.NOBODY_LOGGED_IN).

    Migrations for the other edition do not count: the runner only records them as done.
    """

    from caramos_ota_update.desktop import applies, current_desktop
    from caramos_ota_update.registry import ANYTIME

    desktop = current_desktop() if desktop is None else desktop
    return [item.migration_id for item in plan.migrations
            if applies(item.desktops, desktop) and item.unattended != ANYTIME]


def update_key(update: dict[str, Any] | None) -> str:
    """One update, whatever check found it: the version it brings and its migrations."""

    update = update or {}
    release = update.get("release") or update.get("to_version") or "?"
    return f"{release}:{','.join(str(item) for item in update.get('migration_ids') or [])}"


def skip_reason(update: dict[str, Any], plan, state: dict[str, Any]) -> tuple[str, str] | None:
    """(reason, detail for the log) when the update must wait; None when it can install now."""

    if live_session():
        return LIVE, "running from the live USB"
    if overlay_root():
        return OVERLAY, "/ is an overlay (overlayroot)"
    last = state.get(STATUS_KEY)
    if isinstance(last, dict) and last.get("outcome") == FAILED and last.get("update") == update_key(update):
        return FAILED_BEFORE, "the last automatic try of this update failed; the Update Center offers it"
    if ota_busy():
        return OTA_BUSY, "another caramos-ota run holds the lock"
    if apt_busy():
        return APT_BUSY, "APT or dpkg is busy"
    if metered():
        return METERED, "the connection is metered"
    if battery_low():
        return BATTERY, f"on battery under {MIN_BATTERY}%"
    lacking = low_disk()
    if lacking:
        return DISK, "; ".join(f"{item.path}: {item.free // MIB} MiB free, {item.need // MIB} MiB needed"
                               for item in lacking)
    waiting = changes_open_desktops(plan)
    if waiting:
        users = desktop_sessions()
        if users is None or users:
            who = ", ".join(users) if users else "logind cannot tell who"
            return IN_USE, f"{', '.join(waiting)} would change open desktops ({who} logged in)"
    return None


# The try -----------------------------------------------------------------------------------------


def record(outcome: str, update: dict[str, Any], reason: str = "") -> None:
    """The last automatic try in state.json: the Update Center says why an update waited."""

    from .state import load_state, save_state

    state = load_state()
    state[STATUS_KEY] = {"at": now_iso(), "outcome": outcome, "reason": reason, "update": update_key(update),
                         "release": update.get("release") or update.get("to_version")}
    save_state(state)


def system_language(path: Path | None = None) -> str:
    """"vi" or "en": the language of LANG in /etc/default/locale (the system's, as the service has no session)."""

    for line in _read(path or SYSTEM_LOCALE).splitlines():
        if line.strip().startswith("LANG="):
            return "vi" if line.split("=", 1)[1].strip().strip("\"'").startswith("vi") else "en"
    return "en"


def reboot_marker(path: Path | None = None) -> str | None:
    """None without /run/reboot-required, else the packages it names (.pkgs)."""

    path = path or REBOOT_REQUIRED
    if not path.exists():
        return None
    return _read(path.with_name(path.name + ".pkgs"))


def run_upgrade(language: str | None = None) -> tuple[int, str]:
    """`caramos-ota --upgrade --yes --unattended` while a logind lock delays shutting down: (exit code, output)."""

    why = INHIBIT_WHY.get(language or system_language(), INHIBIT_WHY["en"])
    inhibitor = None
    try:
        # A lock held by a process of its own: the update runs even where logind cannot give one (no lock, no wait).
        inhibitor = subprocess.Popen(["systemd-inhibit", "--what=shutdown", "--mode=block", "--who=CaramOS",
                                      f"--why={why}", "sleep", str(INHIBIT_SECONDS)],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
    except OSError as exc:
        log_warn(f"Automatic update: no shutdown lock ({exc})")
    environment = dict(os.environ)
    environment.update(UNATTENDED_ENV)
    try:
        result = subprocess.run([OTA_COMMAND, "--upgrade", "--yes", "--unattended"], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                                env=environment, check=False)
        return result.returncode, result.stdout or ""
    except OSError as exc:
        return EXIT_ERROR, str(exc)
    finally:
        if inhibitor is not None:
            try:
                os.killpg(inhibitor.pid, signal.SIGTERM)
                inhibitor.wait(timeout=10)
            except (OSError, subprocess.SubprocessError):
                pass


def write_result(result: dict[str, Any], path: Path | None = None) -> None:
    """The result for the users' notifiers, renamed into place (their path units see the new file)."""

    path = path or RESULT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, staging = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        os.chmod(staging, 0o644)
        os.replace(staging, path)
    except BaseException:
        Path(staging).unlink(missing_ok=True)
        raise


def read_result(path: Path | None = None) -> dict[str, Any] | None:
    try:
        result = json.loads((path or RESULT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    return result if isinstance(result, dict) and result.get("outcome") in (DONE, FAILED) else None


def run() -> int:
    """`caramos-ota --auto-upgrade` (UNIT, after each successful daily check; root, init_log done)."""

    from caramos_ota_update.registry import version_lt

    from .manifest import resolve_update_plan
    from .release import detect_caramos
    from .state import load_state

    if not is_enabled():
        log_info(f"Automatic update: off ({SETTINGS_FILE}); the Update Center asks first")
        return EXIT_OK
    state = load_state()
    update = state.get("available_update")
    if not isinstance(update, dict) or not update.get("packages"):
        log_info("Automatic update: no update is waiting")
        return EXIT_OK
    release_info = detect_caramos()
    plan = resolve_update_plan(release_info, persist_ledger=False)
    if not plan.migrations and not version_lt(release_info.version, plan.target_version):
        log_info("Automatic update: nothing left to install")
        return EXIT_OK

    reason = skip_reason(update, plan, state)
    if reason is not None:
        code, detail = reason
        record(SKIPPED, update, code)
        retry = code in RETRY
        log_info(f"Automatic update to {update.get('release')} waits: {code} ({detail}); "
                 + ("trying again in 15 minutes" if retry else "the Update Center offers it at the next login"))
        print(f"Automatic update waits: {detail}")
        return EXIT_RETRY if retry else EXIT_OK

    log_info(f"Automatic update: installing CaramOS {update.get('release')} "
             f"({len(plan.migrations)} change(s), from {release_info.version})")
    record(RUNNING, update)
    restart_before = reboot_marker()
    started_at = now_iso()
    # Shutting down now (systemctl sends SIGTERM to this process only, KillMode=mixed): the update finishes first,
    # within the unit's TimeoutStopSec, as an interrupted dpkg would break later updates.
    previous = signal.signal(signal.SIGTERM, lambda *_args: log_warn("Automatic update: asked to stop; finishing first"))
    try:
        code, output = run_upgrade()
    finally:
        signal.signal(signal.SIGTERM, previous)
    if code == EXIT_LOCK:
        record(SKIPPED, update, OTA_BUSY)
        log_info("Automatic update waits: another caramos-ota run took the lock; trying again in 15 minutes")
        return EXIT_RETRY
    restart_after = reboot_marker()
    outcome = DONE if code == 0 else FAILED
    result = {
        "schema": 1,
        "id": f"{datetime.now():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:8]}",
        "outcome": outcome,
        "started_at": started_at,
        "finished_at": now_iso(),
        "exit_code": code,
        "from_version": release_info.version,
        "to_version": update.get("release") or plan.target_version,
        "restart": restart_after is not None and restart_after != restart_before,
        "update": update,
        "update_key": update_key(update),
        "output": output[-OUTPUT_LIMIT:],
    }
    write_result(result)
    record(outcome, update)
    if outcome == DONE:
        log_info(f"Automatic update to {result['to_version']} finished"
                 + ("; a restart finishes it" if result["restart"] else ""))
        return EXIT_OK
    log_error(f"Automatic update to {result['to_version']} failed (exit code {code}); the Update Center shows the "
              "failure at the next login")
    return code if 0 < code < 256 and code != EXIT_RETRY else EXIT_ERROR


def status_lines(state: dict[str, Any]) -> list[str]:
    """For `caramos-ota --status`."""

    lines = [f"Automatic updates:    {'on' if is_enabled() else 'off'}"]
    last = state.get(STATUS_KEY)
    if isinstance(last, dict):
        what = str(last.get("outcome") or "?")
        if last.get("reason"):
            what += f" ({last['reason']})"
        lines.append(f"Last automatic try:   {last.get('at', '?')} {what}, CaramOS {last.get('release') or '?'}")
    return lines

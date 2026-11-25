"""computer.log: what a help request says about this computer, so that VNLF can answer a question about hardware,
drivers, printers or being "logged out" without asking the person to look anything up (logs.system_logs).

Requests arrived without it: someone asking for drivers for H61, B75 and X79 boards and Xprinter receipt printers sent
plain feedback, and a company whose Zalo and Lark lost their sign-in after the screen rested could not say how the
computers lock or sleep. The log has:
- CaramOS's version and edition, the Ubuntu base and the kernel; the computer's maker, model, board and firmware as
  the firmware names them (the DMI fields everyone may read: no serial numbers); memory and the room left on /;
- the PCI devices with their ids and the drivers in use (lspci -nnk), the USB devices (lsusb) and their drivers
  (lsusb -t);
- the print queues: connection, driver (make and model) and state; only the queues of USB printers keep their names,
  as in printer.log, since the names of network printers can name the office;
- how the screen locks and the computer sleeps for this user: Cinnamon's settings (gsettings), or Xfce's power
  manager (xfconf) and light-locker; "set by this user" marks what the person changed. Whether LightDM logs someone
  in by itself (on or off, not who), and whether the keyring where Zalo, Lark and the browsers keep their sign-in is
  locked now: after an automatic login no password unlocks it, so they ask for it, or lose the sign-in;
- the logins, logouts, locks (Xfce's lock is a LightDM login screen), sleeps and wake-ups of this boot and the one
  before, one line each, from the system journal (readable by the adm group, which the first user of an install is
  in): no program's messages, no user names.

Everything is read as the user, without root, and logs.redact takes out e-mail and IP addresses, the computer's name
and the user's login name. No message contents, no files of the user.
"""

from __future__ import annotations

import getpass
import os
import platform
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from .logs import LOG_LIMIT, redact

COMMAND_TIMEOUT = 10
PCI_LIMIT = 12 * 1024        # characters of lspci -nnk kept
USB_LIMIT = 4 * 1024
EVENTS_PER_BOOT = 40
JOURNAL_LINES = 4000         # journal lines read per boot, before the events are picked out
DMI = "sys/class/dmi/id"
CHASSIS = {"3": "desktop", "4": "desktop", "5": "desktop", "6": "desktop", "7": "desktop", "8": "laptop",
           "9": "laptop", "10": "laptop", "13": "all-in-one", "14": "laptop", "15": "desktop", "16": "desktop",
           "30": "tablet", "31": "convertible laptop", "32": "detachable laptop", "35": "mini PC", "36": "stick PC"}
LIGHTDM_FILES = ("usr/share/lightdm/lightdm.conf.d/*.conf", "etc/lightdm/lightdm.conf.d/*.conf",
                 "etc/lightdm/lightdm.conf")
# What decides when the screen locks and the computer sleeps, per desktop.
CINNAMON_SCHEMAS = {
    "org.cinnamon.desktop.session": ("idle-delay",),
    "org.cinnamon.desktop.screensaver": ("lock-enabled", "lock-delay"),
    "org.cinnamon.settings-daemon.plugins.power": (
        "lock-on-suspend", "sleep-display-ac", "sleep-display-battery", "sleep-inactive-ac-timeout",
        "sleep-inactive-ac-type", "sleep-inactive-battery-timeout", "sleep-inactive-battery-type",
        "lid-close-ac-action", "lid-close-battery-action"),
}
XFCE_SCHEMAS = {"apps.light-locker": ("lock-after-screensaver", "late-locking", "lock-on-suspend", "lock-on-lid")}
XFCE_POWER_KEYS = re.compile(r"^/xfce4-power-manager/(blank-on-|dpms-|inactivity-|lock-screen-|lid-action|"
                             r"sleep-button|power-button|logind-handle)")
# The Secret Service of gnome-keyring, asked without starting it.
SECRETS = ("busctl", "--user", "--auto-start=no")
SECRETS_SERVICE = "org.freedesktop.secrets"
# Keyring names that say nothing about the person; another one is only called "another keyring".
KEYRING_LABELS = ("Login", "login", "Default keyring", "Default")
JOURNAL_LINE = re.compile(r"^(\d{4})-(\d\d-\d\d)T(\d\d:\d\d:\d\d)\S* \S+ ([\w.@-]+?)(?:\[\d+\])?: (.*)$")
LIGHTDM_SERVICES = {"lightdm-greeter": "the login screen", "lightdm-autologin": "an automatic login",
                    "lightdm": "a login with the password"}

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def run(arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """A command as this user; one that cannot start or takes too long fails (127, 124)."""

    try:
        return subprocess.run(list(arguments), check=False, capture_output=True, text=True, errors="replace",
                              timeout=COMMAND_TIMEOUT, stdin=subprocess.DEVNULL,
                              env={**os.environ, "LC_ALL": "C.UTF-8"})
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(list(arguments), 124, "", "timed out")
    except OSError as exc:
        return subprocess.CompletedProcess(list(arguments), 127, "", str(exc))


def _out(runner: Runner, arguments: Sequence[str]) -> str:
    result = runner(arguments)
    return result.stdout if result.returncode == 0 else ""


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def _head(text: str, limit: int) -> str:
    """The start of text in at most limit characters, ending at a line."""

    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    return cut[:cut.rfind("\n")] + "\n…" if "\n" in cut else cut + "…"


def _gib(count: float) -> str:
    return f"{count / 1024 ** 3:.1f} GiB"


# The computer -------------------------------------------------------------------------------------------------------


def edition(root: Path, environ: Mapping[str, str]) -> str:
    """The desktop this session runs, else the edition's."""

    names = f"{environ.get('XDG_CURRENT_DESKTOP', '')}:{environ.get('DESKTOP_SESSION', '')}".lower()
    if "cinnamon" in names or (not names.strip(":") and (root / "usr/bin/cinnamon").exists()):
        return "Cinnamon"
    if "xfce" in names or (not names.strip(":") and (root / "usr/bin/xfce4-session").exists()):
        return "Xfce"
    return names.strip(":") or "unknown"


def _release(root: Path, key: str, path: str) -> str:
    for line in _read(root / path).splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip().strip('"')
    return ""


def summary(root: Path, environ: Mapping[str, str]) -> list[str]:
    version = _release(root, "VERSION", "etc/caramos-release") or "?"
    base = _release(root, "DISTRIB_DESCRIPTION", "etc/upstream-release/lsb-release") or \
        _release(root, "UBUNTU_CODENAME", "etc/os-release") or "?"
    session = environ.get("XDG_SESSION_TYPE") or "?"
    lines = [f"CaramOS {version}, {edition(root, environ)} edition ({session} session) · {base} · "
             f"Linux {platform.release()} {platform.machine()}"]
    dmi = {name: _read(root / DMI / name) for name in ("sys_vendor", "product_name", "product_version",
                                                        "board_vendor", "board_name", "bios_vendor", "bios_version",
                                                        "bios_date", "chassis_type")}
    model = " ".join(part for part in (dmi["sys_vendor"], dmi["product_name"], dmi["product_version"]) if part)
    board = " ".join(part for part in (dmi["board_vendor"], dmi["board_name"]) if part)
    firmware = " ".join(part for part in (dmi["bios_vendor"], dmi["bios_version"]) if part)
    chassis = CHASSIS.get(dmi["chassis_type"], f"chassis {dmi['chassis_type'] or '?'}")
    dated = f" ({dmi['bios_date']})" if dmi["bios_date"] else ""
    lines.append(f"Computer: {model or '?'} · {chassis} · board {board or '?'} · firmware {firmware or '?'}{dated}")
    memory = ""
    for line in _read(root / "proc/meminfo").splitlines():
        if line.startswith("MemTotal:") and line.split()[1:2]:
            memory = _gib(int(line.split()[1]) * 1024)
    try:
        usage = shutil.disk_usage(root)
        disk = f"{_gib(usage.free)} free of {_gib(usage.total)} on /"
    except OSError:
        disk = "? on /"
    lines.append(f"Memory {memory or '?'} · disk: {disk}")
    return lines


def devices(runner: Runner) -> list[str]:
    lines = ["", "== PCI devices (lspci -nnk) =="]
    lines.append(_head(_out(runner, ["lspci", "-nnk"]), PCI_LIMIT) or "(lspci gave nothing)")
    lines += ["", "== USB devices (lsusb) =="]
    lines.append(_head(_out(runner, ["lsusb"]), USB_LIMIT) or "(lsusb gave nothing)")
    lines += ["", "== USB drivers (lsusb -t) =="]
    lines.append(_head(_out(runner, ["lsusb", "-t"]), USB_LIMIT) or "(lsusb -t gave nothing)")
    return lines


def printer_lines(runner: Runner) -> list[str]:
    """Each print queue: connection, driver and state; the names of USB queues only."""

    from .printers import STATES, _options, queues   # printers imports logs, which imports this module

    def text(arguments: Sequence[str]) -> str:
        return runner(arguments).stdout

    found = queues(text)
    lines = ["", "== Printers (CUPS) =="]
    if not found:
        return lines + ["(no print queue)"]
    default = _out(runner, ["lpstat", "-d"]).strip()
    for number, (name, uri) in enumerate(found, 1):
        options = _options(text, name)
        scheme = uri.split(":", 1)[0]
        usb = scheme in ("usb", "ccp")
        title = name if usb else f"queue {number}"
        state = options.get("printer-state", "?")
        mark = " (default)" if default.endswith(f": {name}") else ""
        lines.append(f"{title}{mark}: {scheme} · {options.get('printer-make-and-model', '?')} · "
                     f"{STATES.get(state, state)}, {options.get('printer-state-reasons', '?')}")
    return lines


# The screen lock, sleep and the login -------------------------------------------------------------------------------


def autologin(root: Path) -> str:
    """"on" when LightDM logs a user in by itself (who is left out), else "off"; LightDM's later files win."""

    user = timeout = ""
    for pattern in LIGHTDM_FILES:
        for path in sorted(root.glob(pattern)):
            section = ""
            for raw in _read(path).splitlines():
                line = raw.strip()
                if line.startswith("[") and line.endswith("]"):
                    section = line
                elif section in ("[Seat:*]", "[SeatDefaults]") and "=" in line and not line.startswith("#"):
                    key, value = (part.strip() for part in line.split("=", 1))
                    if key == "autologin-user":
                        user = value
                    elif key == "autologin-user-timeout":
                        timeout = value
    if not user:
        return "off"
    return "on" + (f", after {timeout} s at the login screen" if timeout and timeout != "0" else "")


def _settings(runner: Runner, schema: str, keys: Sequence[str]) -> list[str]:
    """Each key's value as this user sees it, and whether the user set it (their own dconf value)."""

    listed = runner(["gsettings", "list-recursively", schema])
    if listed.returncode != 0:
        return []
    values = {}
    for line in listed.stdout.splitlines():
        parts = line.split(" ", 2)
        if len(parts) == 3 and parts[0] == schema:
            values[parts[1]] = parts[2]
    own = set()
    for line in _out(runner, ["dconf", "dump", "/" + schema.replace(".", "/") + "/"]).splitlines():
        if "=" in line and not line.startswith("["):
            own.add(line.split("=", 1)[0].strip())
    shown = [f"{key} {values[key]}" + (" (set by this user)" if key in own else "") for key in keys if key in values]
    # "[schema] key value": a colon after ...session would look like a secret to logs.redact.
    return [f"[{schema}] " + ", ".join(shown)] if shown else []


def lock_settings(runner: Runner, desktop: str) -> list[str]:
    lines = []
    if desktop != "Xfce":
        for schema, keys in CINNAMON_SCHEMAS.items():
            lines += _settings(runner, schema, keys)
    if desktop != "Cinnamon":
        listed = _out(runner, ["xfconf-query", "-c", "xfce4-power-manager", "-l", "-v"])
        values = []
        for line in listed.splitlines():
            parts = line.split(None, 1)
            if parts and XFCE_POWER_KEYS.match(parts[0]):
                values.append(f"{parts[0].rsplit('/', 1)[1]} {parts[1].strip() if len(parts) > 1 else ''}".strip())
        if listed:
            lines.append("[xfce4-power-manager] " + (", ".join(values) or "nothing set")
                         + " (xfconf; a key not listed has the power manager's own default)")
        for schema, keys in XFCE_SCHEMAS.items():
            lines += _settings(runner, schema, keys)
    return lines


def _not_running(error: str) -> bool:
    error = error.lower()
    return any(words in error for words in ("not activatable", "no owner", "serviceunknown", "not provided",
                                            "was not provided", "failed to connect"))


def keyring(runner: Runner) -> str:
    """The keyring where apps keep saved sign-ins (the Secret Service's "default" collection) and whether it is locked
    now, asked without starting gnome-keyring. After an automatic login no password unlocks it: Zalo, Lark and the
    browsers then ask for it, or lose their sign-in when the question is closed."""

    alias = runner([*SECRETS, "call", SECRETS_SERVICE, "/org/freedesktop/secrets", "org.freedesktop.Secret.Service",
                    "ReadAlias", "s", "default"])
    if alias.returncode != 0:
        if _not_running(alias.stderr):
            return "the keyring service is not running"
        return "unknown" + (f" ({alias.stderr.strip()[:120]})" if alias.stderr.strip() else "")
    found = re.search(r'"(/[^"]*)"', alias.stdout)
    path = found.group(1) if found else ""
    if path in ("", "/"):
        return "none yet: the first app that saves a sign-in asks to make one"

    def prop(name: str) -> str:
        result = runner([*SECRETS, "get-property", SECRETS_SERVICE, path, "org.freedesktop.Secret.Collection", name])
        return result.stdout.strip() if result.returncode == 0 else ""

    locked = prop("Locked")
    label = re.match(r'^s "(.*)"$', prop("Label"))
    name = f"“{label.group(1)}”" if label and label.group(1) in KEYRING_LABELS else "another keyring"
    state = {"b true": "locked", "b false": "unlocked"}.get(locked, "unknown")
    return f"{name}, {state}"


def login_lines(root: Path, runner: Runner, desktop: str) -> list[str]:
    lines = ["", "== Screen lock, sleep and login (this user) =="]
    lines.append(f"Automatic login (LightDM): {autologin(root)}")
    lines.append(f"Keyring for saved sign-ins: {keyring(runner)}")
    lines += lock_settings(runner, desktop) or ["(the lock and sleep settings could not be read)"]
    return lines


# The logins and sleeps in the journal -------------------------------------------------------------------------------


def _who(name: str, me: str) -> str:
    if name == me:
        return "this user"
    if name == "lightdm":
        return "the login screen"
    return "another user"


def event(identifier: str, message: str, me: str) -> str:
    """One journal message as a line without names; "" when it is not a login, lock, sleep or power event."""

    if identifier == "systemd-logind":
        found = re.match(r"New session (\S+) of user (\S+?)\.?$", message)
        if found:
            return f"session {found[1]} opened for {_who(found[2], me)}"
        found = re.match(r"Removed session (\S+?)\.?$", message)
        if found:
            return f"session {found[1]} closed"
        found = re.match(r"Session (\S+) logged out\.", message)
        if found:
            return f"session {found[1]} logged out"
        found = re.match(r"Lid (opened|closed)\.", message)
        if found:
            return f"lid {found[1]}"
        for words, text in (("Power key pressed", "power button pressed"), ("Suspend key pressed", "sleep key pressed"),
                            ("System is powering down", "shutting down"), ("System is rebooting", "restarting")):
            if message.startswith(words):
                return text
        found = re.match(r"The system will (suspend|hibernate|power off|reboot|halt)", message)
        if found:
            return f"the system will {found[1]}"
        return ""
    if identifier == "systemd-sleep":
        found = re.match(r"Entering sleep state '(\w+)'", message)
        if found:
            return f"going to sleep ({found[1]})"
        if message.startswith("System returned from sleep state"):
            return "woke up"
        return ""
    if identifier == "lightdm":
        found = re.match(r"pam_unix\(([\w-]+):session\): session (opened|closed) for user ([^\s(]+)", message)
        if found and found[1] in LIGHTDM_SERVICES:
            return f"{LIGHTDM_SERVICES[found[1]]} {found[2]} ({_who(found[3], me)})"
    return ""


def boot_events(runner: Runner, boot: str, me: str) -> list[str] | None:
    """The events of one boot (0 this one, -1 the one before); None when the journal does not have it."""

    result = runner(["journalctl", "-b", boot, "-q", "-o", "short-iso", "--no-pager", "-n", str(JOURNAL_LINES),
                     "_COMM=systemd-logind", "+", "_COMM=systemd-sleep", "+", "_COMM=lightdm"])
    if result.returncode != 0:
        return None
    found = []
    text_logins = set()
    for line in result.stdout.splitlines():
        match = JOURNAL_LINE.match(line)
        if match is None:
            continue
        text = event(match[4], match[5].strip(), me)
        session = re.match(r"session (\d+) ", text)
        if session:
            # A number: a login without a desktop (SSH, a text console), which only crowds out the desktop's events;
            # LightDM's sessions are c1, c2...
            text_logins.add(session[1])
            continue
        if text:
            found.append(f"{match[2]} {match[3]} {text}")
    found = found[-EVENTS_PER_BOOT:]
    if text_logins:
        found.append(f"({len(text_logins)} logins without a desktop, over SSH or a text console, left out)")
    return found


def session_lines(runner: Runner, me: str) -> list[str]:
    lines = ["", "== Logins, locks and sleep: this boot and the one before (from the journal) =="]
    for boot, title in (("-1", "The boot before"), ("0", "This boot")):
        events = boot_events(runner, boot, me)
        if events is None:
            lines.append(f"{title}: not in the journal")
        elif not events:
            lines.append(f"{title}: no logins or sleeps the user may read (the system journal needs the adm group)")
        else:
            lines.append(f"{title}:")
            lines += [f"  {line}" for line in events]
    return lines


def computer_log(root: Path = Path("/"), runner: Runner = run, environ: Mapping[str, str] | None = None) -> str:
    environ = os.environ if environ is None else environ
    try:
        me = getpass.getuser()
    except (KeyError, OSError):
        me = ""
    desktop = edition(root, environ)
    lines = ["== This computer ==", *summary(root, environ), *devices(runner)]
    for part in (lambda: printer_lines(runner), lambda: login_lines(root, runner, desktop),
                 lambda: session_lines(runner, me)):
        try:
            lines += part()
        except Exception as exc:   # noqa: BLE001 - one part that cannot be read must not cost the others
            lines += ["", f"(could not be read: {exc})"]
    return _head(redact("\n".join(lines), me), LOG_LIMIT) + "\n"

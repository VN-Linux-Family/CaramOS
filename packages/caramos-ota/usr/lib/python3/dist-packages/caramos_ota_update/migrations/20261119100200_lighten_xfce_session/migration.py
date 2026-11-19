"""CaramOS Xfce: less memory at login, with every feature kept.

Measured on the 2 GB test VM, 3 minutes after an automatic login: 742 MB used, part of it by programs that wait
in the background for something that rarely happens.

- evolution-alarm-notify, the reminder daemon of calendars, starts the Evolution data server and GNOME Online
  Accounts (five processes, about 63 MiB) although most users never add an event. Migration 20261010120100 starts
  it through a wrapper that waits for an event, a task or a calendar account, but only for Cinnamon sessions
  (/etc/xdg/xdg-cinnamon/autostart). The same entry now goes to /etc/xdg/caramos-xfce/autostart, which Xfce
  sessions read first.
- The Bluetooth tray applet, blueman-applet (about 26 MiB), ran on computers without Bluetooth, like most school
  desktops. It now starts only where there is an adapter at login. A dongle plugged in later gets it at the next
  login; the Control Center's Bluetooth tile works either way.
- Linux Mint's System Reports tray icon, mintreport-tray (about 30 MiB), no longer starts at login (the owner,
  2026-11-19). System Reports stays in the menu.
- Flameshot no longer waits in the background from login (about 26 MiB; the owner, 2026-11-19). Print Screen,
  Super+Shift+S and the Control Center run `flameshot gui`, which takes the screenshot by itself. Copying it starts
  Flameshot through D-Bus, which keeps the picture on the clipboard and then stays, with its tray icon, until the
  user logs out. CaramOS put its autostart entry in /etc/skel, so it is in each user's ~/.config/autostart; it gets
  Hidden=true there, as Xfce's Session and Startup writes it, where it is still CaramOS's.

Then the owner (2026-11-19, "bản này tập trung giáo dục nên siêu cơ bản"): the Xfce edition is for school computer
labs and stays basic, so these go too. Sizes from the 2 GB test VM, 13 minutes after boot:

- The print queue applet, system-config-printer-applet (about 21 MiB), which shows print jobs and printer errors in
  the tray. Printing is the same; Printers in the menu shows the queues.
- xiccd (about 8 MiB with colord, which it starts): colour profiles for calibrated screens. CUPS still starts colord
  for the printers that use it.
- GNOME Online Accounts (about 10 MiB, three processes): gvfs's GOA volume monitor started it in every session, for
  the thumbnailer and the file managers, although the Xfce edition has nowhere to add an online account. Its
  .monitor file is moved aside with a local dpkg diversion, which package updates keep; gvfs reads only *.monitor.
- fwupd-refresh.timer: twice a day, and soon after a boot that missed it, it started fwupd (27 MiB, 47 MiB while
  refreshing), which also started Bluetooth, to download the list of firmware updates. fwupdmgr still works when
  someone runs it.
- ModemManager (about 6 MiB), which only USB 3G/4G modems need. It is disabled, not stopped, so a connection that
  is up stays up until the next boot; `sudo systemctl enable --now ModemManager` brings it back.
- xfwm4 synchronised with the screen through OpenGL (vblank_mode auto picks GLX), which loads Mesa and LLVM into it:
  about 44 of its 54 MiB. CaramOS's xfwm4 defaults in /etc/xdg/caramos-xfce now say XPresent, which X does alone,
  and so do the users who have the "auto" that xfwm4 wrote at their first login. A user's own other choice stays.

The login entries can be turned on again in Session and Startup. Mint's Update Manager stays, the one that tells
about security updates.
"""

from __future__ import annotations

import importlib
import os
import stat
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = ("Xfce sessions start the calendar reminders, the Bluetooth applet, System Reports and Flameshot only "
               "when they are needed, without the print queue icon, colour profiles, online accounts, the firmware "
               "refresh and ModemManager, and xfwm4 without OpenGL")

XFCE_AUTOSTART = Path("/etc/xdg/caramos-xfce/autostart")
SYSTEM_AUTOSTART = Path("/etc/xdg/autostart")
BLUEMAN = "blueman.desktop"
BLUEMAN_WRAPPER = Path("/usr/local/libexec/caramos-blueman-applet")
BLUEMAN_WRAPPER_SCRIPT = """\
#!/bin/sh
# CaramOS Xfce (caramos-ota): the Bluetooth tray applet (~26 MiB) only on a computer with Bluetooth. A dongle
# plugged in later gets it at the next login; the Control Center's Bluetooth tile works either way.
for adapter in /sys/class/bluetooth/hci*; do
    [ -e "$adapter" ] && exec blueman-applet "$@"
done
exit 0
"""
MINTREPORT = "mintreport.desktop"
MINTREPORT_EXEC = "Exec=mintreport-tray"
MINTREPORT_COMMENT = (
    f"CaramOS Xfce (caramos-ota): a copy of {SYSTEM_AUTOSTART / MINTREPORT}. The System Reports tray icon",
    "(~30 MiB) does not start at login; System Reports is in the menu. Session and Startup can turn it on again.",
)
PRINT_APPLET = "print-applet.desktop"
XICCD = "xiccd.desktop"
# The system's login entries that Xfce sessions skip: (file, the Exec lines it is known with, why).
HIDDEN_AT_LOGIN = (
    (MINTREPORT, (MINTREPORT_EXEC,), MINTREPORT_COMMENT),
    (PRINT_APPLET, ("Exec=system-config-printer-applet",), (
        f"CaramOS Xfce (caramos-ota): a copy of {SYSTEM_AUTOSTART / PRINT_APPLET}. The print queue icon (~21 MiB)",
        "does not start at login; Printers in the menu shows the queues. Session and Startup can turn it on again.",
    )),
    (XICCD, ("Exec=xiccd",), (
        f"CaramOS Xfce (caramos-ota): a copy of {SYSTEM_AUTOSTART / XICCD}. Colour profiles for calibrated",
        "screens (xiccd and colord, ~8 MiB) do not start at login. Session and Startup can turn them on again.",
    )),
)

# System units a school computer lab does without, and whether to stop them at once. ModemManager is only disabled:
# a USB 3G/4G connection that is up stays up until the next boot.
DISABLED_UNITS = (("fwupd-refresh.timer", True), ("ModemManager.service", False))
GOA_MONITOR = Path("/usr/share/gvfs/remote-volume-monitors/goa.monitor")
GOA_MONITOR_DIVERTED = GOA_MONITOR.with_name("goa.monitor.distrib")  # gvfs reads only *.monitor

# CaramOS's xfwm4 defaults (config/includes.chroot.xfce of the ISO), which come before Mint's for Xfce sessions.
XFWM4_DEFAULTS = Path("/etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml")
XFWM4_VBLANK = '<property name="vblank_mode" type="string" value="xpresent"/>'
# At a user's first login xfwm4 writes its own defaults into the user's xfconf, vblank_mode "auto" among them, and
# the user's value wins over the system's. So users who have logged in before change from "auto" through xfconf
# itself, as each user: through the xfconfd of their session when they are logged in (it keeps the channel in memory
# and would write "auto" back), through a private bus otherwise. Any other value is the user's own and stays.
VBLANK_QUERY = ("xfconf-query", "-c", "xfwm4", "-p", "/general/vblank_mode")
XFCE_CONFIG_DIRS = "/etc/xdg/caramos-xfce:/etc/xdg/xdg-xfce:/etc/xdg"  # an Xfce session's (Xsession.d 61caramos-xfce)
RUNTIME_ROOT = Path("/run/user")
SKEL = Path("/etc/skel")

lighten = importlib.import_module("caramos_ota_update.migrations.20261010120100_lighten_desktop_session.migration")

FLAMESHOT_AUTOSTART = lighten.FLAMESHOT_AUTOSTART
# The Exec lines of CaramOS's entry: the ISO's first one, and the one without OpenGL (migration 20261010120100).
FLAMESHOT_EXECS = (lighten.FLAMESHOT_EXEC, lighten.FLAMESHOT_EXEC_WITHOUT_GL)
FLAMESHOT_COMMENT = (
    "CaramOS Xfce (caramos-ota): Flameshot does not wait in the background from login (~26 MiB). Print Screen",
    "starts it when it is needed. Session and Startup can turn this on again.",
)


def blueman_override(original: str) -> str:
    """The package's entry, run through the wrapper that checks for an adapter, or "" if it is not as expected."""

    lines = original.splitlines()
    exec_lines = [index for index, line in enumerate(lines) if line.startswith("Exec=")]
    if "[Desktop Entry]" not in lines or len(exec_lines) != 1 or lines[exec_lines[0]] != "Exec=blueman-applet":
        return ""
    lines[exec_lines[0]] = f"Exec={BLUEMAN_WRAPPER}"
    index = lines.index("[Desktop Entry]") + 1
    lines[index:index] = [f"# CaramOS Xfce (caramos-ota): copy of {SYSTEM_AUTOSTART / BLUEMAN} started through",
                          f"# {BLUEMAN_WRAPPER}, which runs it only on a computer with Bluetooth."]
    return "\n".join(lines) + "\n"


def hidden(original: str, execs: tuple[str, ...], comment: tuple[str, ...]) -> str:
    """The autostart entry `original` with `comment` and Hidden=true at the end of its [Desktop Entry] group.

    "" when its Exec line is not one of `execs` (someone changed it) or it already says whether it is hidden.
    """

    lines = original.splitlines()
    if "[Desktop Entry]" not in lines:
        return ""
    start = lines.index("[Desktop Entry]") + 1
    end = next((index for index in range(start, len(lines)) if lines[index].startswith("[")), len(lines))
    group = lines[start:end]
    exec_lines = [line for line in group if line.startswith("Exec=")]
    if len(exec_lines) != 1 or exec_lines[0] not in execs:
        return ""
    if any(line.split("=", 1)[0].strip() == "Hidden" for line in group if "=" in line):
        return ""
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[:end] + [f"# {line}" for line in comment] + ["Hidden=true"] + lines[end:]) + "\n"


def _open_folder(home: Path, parts: tuple[str, ...], uid: int) -> int:
    """A descriptor of home/parts, each folder opened without following a link and owned by `uid`."""

    folder = os.open(home, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=folder)
            os.close(folder)
            folder = child
            if os.fstat(folder).st_uid != uid:
                raise PermissionError(f"{part} is not its user's")
        return folder
    except BaseException:
        os.close(folder)
        raise


def hide_flameshot(home: Path, uid: int, dry_run: bool = False) -> str:
    """Add Hidden=true to <home>/.config/autostart/flameshot.desktop, a file of `uid`, while it is CaramOS's.

    It runs as root in the users' homes, so it follows no symbolic link and changes only a file of the user in
    folders of the user, replacing it in a single rename with the same owner and mode. Says what happened.
    """

    target = home / FLAMESHOT_AUTOSTART
    try:
        folder = _open_folder(home, FLAMESHOT_AUTOSTART.parent.parts, uid)
    except FileNotFoundError:
        return f"no {target}"
    except OSError as exc:
        return f"skip {target}: {exc.strerror or exc} (a symbolic link?)"
    name = FLAMESHOT_AUTOSTART.name
    try:
        try:
            handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=folder)
        except FileNotFoundError:
            return f"no {target}"
        except OSError as exc:
            return f"skip {target}: {exc.strerror} (a symbolic link?)"
        with os.fdopen(handle, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != uid:
                return f"skip {target}: not a file of its user"
            raw = source.read()
        try:
            new = hidden(raw.decode("utf-8"), FLAMESHOT_EXECS, FLAMESHOT_COMMENT)
        except UnicodeDecodeError:
            return f"skip {target}: not UTF-8"
        if not new:
            return f"{target}: already hidden, or changed by its user; left alone"
        if dry_run:
            return f"would stop Flameshot from starting at login: {target}"
        temporary = f".{name}.caramos-ota-{os.getpid()}"
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder)
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(new.encode("utf-8"))
                output.flush()
                os.fsync(output.fileno())
                os.fchown(output.fileno(), info.st_uid, info.st_gid)
                os.fchmod(output.fileno(), stat.S_IMODE(info.st_mode))
            os.rename(temporary, name, src_dir_fd=folder, dst_dir_fd=folder)
        except BaseException:
            try:
                os.unlink(temporary, dir_fd=folder)
            except OSError:
                pass
            raise
        return f"Flameshot no longer starts at login: {target}"
    finally:
        os.close(folder)


def disable_units(context: MigrationContext, unit_dirs: tuple[Path, ...] = lighten.UNIT_DIRS,
                  running: bool = False) -> None:
    for unit, stop in DISABLED_UNITS:
        if not any((directory / unit).exists() for directory in unit_dirs):
            context.log(f"{unit} is not installed")
            continue
        context.ensure_service_disabled(unit)
        if stop and running:
            context.run_command(["systemctl", "stop", "--no-block", unit], allow_fail=True)


def divert_goa_monitor(context: MigrationContext, monitor: Path = GOA_MONITOR,
                       diverted: Path = GOA_MONITOR_DIVERTED) -> None:
    """Move gvfs's GOA volume monitor aside, where gvfs does not look and package updates leave it."""

    listed = context.run_command(["dpkg-divert", "--list", str(monitor)], allow_fail=True)
    if listed is not None and listed.returncode == 0 and listed.stdout.strip():
        context.log(f"left alone: {listed.stdout.strip()}")
        return
    context.run_command(["dpkg-divert", "--local", "--rename", "--divert", str(diverted), "--add", str(monitor)])


def xfwm4_with_xpresent(original: str) -> str:
    """CaramOS's xfwm4.xml with vblank_mode xpresent next to use_compositing in its general group.

    "" when it already says a vblank_mode, or is not as expected.
    """

    if 'name="vblank_mode"' in original:
        return ""
    lines = original.splitlines(keepends=True)
    after = next((index for index, line in enumerate(lines) if 'name="use_compositing"' in line), None)
    if after is None:
        return ""
    indent = lines[after][:len(lines[after]) - len(lines[after].lstrip())]
    lines.insert(after + 1, f"{indent}{XFWM4_VBLANK}\n")
    new = "".join(lines)
    try:
        general = ElementTree.fromstring(new.encode("utf-8")).find("property[@name='general']")
    except ElementTree.ParseError:
        return ""
    if general is None or general.find("property[@name='vblank_mode']") is None:
        return ""
    return new


def xfwm4_without_opengl(context: MigrationContext, path: Path = XFWM4_DEFAULTS) -> None:
    try:
        new = xfwm4_with_xpresent(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        context.log(f"no {path}")
        return
    except ValueError:
        new = ""
    if new:
        lighten._write(context, path, new)
    else:
        context.log(f"{path} already says a vblank_mode, or is not as expected; left alone")


def users_xfwm4_without_opengl(context: MigrationContext, users: list[tuple[str, int]],
                               runtime_root: Path = RUNTIME_ROOT) -> None:
    for username, uid in users:
        runtime = runtime_root / str(uid)
        env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "XDG_CONFIG_DIRS": XFCE_CONFIG_DIRS}  # runuser sets HOME
        prefix = ["runuser", "-u", username, "--"]
        if (runtime / "bus").exists():
            env.update(XDG_RUNTIME_DIR=str(runtime), DBUS_SESSION_BUS_ADDRESS=f"unix:path={runtime}/bus")
        else:
            prefix += ["dbus-run-session", "--"]
        current = context.run_command([*prefix, *VBLANK_QUERY], allow_fail=True, env=env)
        if current is not None and (current.returncode != 0 or current.stdout.strip() != "auto"):
            context.log(f"xfwm4 of {username}: vblank_mode {current.stdout.strip() or 'not set'}; left alone")
            continue
        context.run_command([*prefix, *VBLANK_QUERY, "-s", "xpresent"], allow_fail=True, env=env)


def run(context: MigrationContext, system_autostart: Path = SYSTEM_AUTOSTART,
        xfce_autostart: Path = XFCE_AUTOSTART, alarm_wrapper: Path = lighten.ALARM_NOTIFY_WRAPPER,
        blueman_wrapper: Path = BLUEMAN_WRAPPER, homes: list[tuple[Path, int]] | None = None,
        unit_dirs: tuple[Path, ...] = lighten.UNIT_DIRS, running: bool | None = None,
        goa_monitor: Path = GOA_MONITOR, xfwm4_defaults: Path = XFWM4_DEFAULTS,
        users: list[tuple[str, int]] | None = None, runtime_root: Path = RUNTIME_ROOT) -> None:
    original = system_autostart / lighten.ALARM_NOTIFY
    if original.is_file():
        override = lighten.alarm_notify_override(original.read_text(encoding="utf-8"))
        if override:
            lighten._write(context, alarm_wrapper, lighten.ALARM_NOTIFY_WRAPPER_SCRIPT, 0o755)
            lighten._write(context, xfce_autostart / lighten.ALARM_NOTIFY, override)
        else:
            context.log(f"{original} has an unexpected Exec line; left alone")
    else:
        context.log(f"no {original}")
    original = system_autostart / BLUEMAN
    if original.is_file():
        override = blueman_override(original.read_text(encoding="utf-8"))
        if override:
            lighten._write(context, blueman_wrapper, BLUEMAN_WRAPPER_SCRIPT, 0o755)
            lighten._write(context, xfce_autostart / BLUEMAN, override)
        else:
            context.log(f"{original} has an unexpected Exec line; left alone")
    else:
        context.log(f"no {original}")
    for name, execs, comment in HIDDEN_AT_LOGIN:
        original = system_autostart / name
        if not original.is_file():
            context.log(f"no {original}")
            continue
        override = hidden(original.read_text(encoding="utf-8"), execs, comment)
        if override:
            lighten._write(context, xfce_autostart / name, override)
        else:
            context.log(f"{original} is not as expected; left alone")
    if homes is None:
        homes = [(SKEL, 0)] + [(Path(info.pw_dir), info.pw_uid) for info in lighten._desktop_users()]
    for home, uid in homes:
        try:
            context.log(hide_flameshot(home, uid, dry_run=context.dry_run))
        except OSError as exc:
            context.log(f"could not change {home / FLAMESHOT_AUTOSTART}: {exc}")
    disable_units(context, unit_dirs, lighten._systemd_running() if running is None else running)
    divert_goa_monitor(context, goa_monitor, goa_monitor.with_name(GOA_MONITOR_DIVERTED.name))
    xfwm4_without_opengl(context, xfwm4_defaults)
    if users is None:
        users = [(info.pw_name, info.pw_uid) for info in lighten._desktop_users()]
    users_xfwm4_without_opengl(context, users, runtime_root)

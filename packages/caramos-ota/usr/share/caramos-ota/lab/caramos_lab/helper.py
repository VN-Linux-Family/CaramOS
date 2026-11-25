"""What the lab tool does as root (caramos-lab-helper, run through pkexec).

    caramos-lab-helper teacher --backend veyon|epoptes --room ROOM
    caramos-lab-helper student --backend veyon|epoptes --room ROOM --teacher-host IP --teacher-name NAME --key FILE
    caramos-lab-helper add-computers --room ROOM        JSON lines {"name","ip","mac"} on stdin (Veyon rooms)
    caramos-lab-helper leave

Each step is reported on stdout as a JSON line ({"event": "step"|"log"|"added"|"done"|"error", …}) for the window.
Packages come from Ubuntu (Veyon 4.7, Epoptes 23.08). Veyon needs the QCA RSA plugin, which is only a Recommends:
without it every key command fails with "RSA not supported". Veyon's service is not enabled by its package.

A lab computer also gets a few defaults for every user (70_caramos-lab.gschema.override): the folder tree in the
left pane of Files, for the "cây thư mục" lessons.

With Veyon, caramos-lab-veyon-check.timer starts Veyon Server again when it is gone (watchdog.py): Veyon 4.7.5 does not,
and Veyon Master showed such computers as an orange screen until they restarted. A student's account also stops its
desktop from locking or sleeping by itself (awake.py, run as the user by the window and at each login).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from caramos_ota.constants import APT_NONINTERACTIVE_OPTIONS, NONINTERACTIVE_ENV

from . import BACKENDS, EPOPTES, STATE_DIR, STUDENT, TEACHER, VEYON
from . import system
from .pairing import PairingError, Student, pairing_code, parse_registration, valid_hostname, valid_ip, valid_room

KEY_NAME = "giaovien"
PRIVATE_KEY = Path(f"/etc/veyon/keys/private/{KEY_NAME}/key")
PACKAGES = {
    (VEYON, TEACHER): ["veyon-master", "veyon-service", "veyon-configurator", "libqca-qt5-2-plugins"],
    (VEYON, STUDENT): ["veyon-service", "libqca-qt5-2-plugins"],
    # Epoptes 23.08's window imports distutils, which Python 3.12 dropped; setuptools brings it back (checked on
    # CaramOS 1.3.10: "No module named 'distutils'" without it).
    (EPOPTES, TEACHER): ["epoptes", "python3-setuptools"],
    (EPOPTES, STUDENT): ["epoptes-client"],
}
# Opened only when ufw is active (it is not by default).
PORTS = {
    (VEYON, TEACHER): ["11400/tcp", "47011/udp", "47012/tcp"],
    (VEYON, STUDENT): ["11100/tcp"],
    (EPOPTES, TEACHER): ["789/tcp", "5499:5599/tcp", "47011/udp", "47012/tcp"],
    (EPOPTES, STUDENT): [],
}
LAB_OVERRIDE = Path("/usr/share/glib-2.0/schemas/70_caramos-lab.gschema.override")
LAB_DEFAULTS = """# CaramOS Phòng máy: defaults of a lab computer, written by caramos-lab-helper (removed when it leaves the lab).
# Files shows the folder tree in its left pane, like Windows Explorer, for the "cây thư mục" lessons.
[org.nemo.window-state]
side-pane-view='tree'
"""
EPOPTES_DEFAULT = Path("/etc/default/epoptes-client")
VEYON_CHECK_TIMER = "caramos-lab-veyon-check.timer"
STATE_FILE = Path(STATE_DIR) / "state.json"


class HelperError(Exception):
    pass


def emit(event: str, **fields) -> None:
    try:
        print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)
    except (BrokenPipeError, OSError):
        pass  # the window closed: carry on, an interrupted apt or dpkg would be worse


def run(command: list[str], check: bool = True, quiet: bool = False, env: dict | None = None,
        stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(command, capture_output=True, text=True, env=env, input=stdin, check=False)
    except FileNotFoundError:
        result = subprocess.CompletedProcess(command, 127, "", f"{command[0]}: not installed")
    output = (result.stdout + result.stderr).strip()
    if output and not quiet:
        for line in output.splitlines()[-20:]:
            emit("log", text=line)
    failed = result.returncode != 0 or (command[0] == "veyon-cli" and "[ERROR]" in output)
    if check and failed:
        raise HelperError(f"{' '.join(command[:4])} failed: {output.splitlines()[-1] if output else result.returncode}")
    return result


def installed(package: str) -> bool:
    result = subprocess.run(["dpkg-query", "-W", "-f=${Status}", package], capture_output=True, text=True,
                            check=False)
    return result.stdout.strip() == "install ok installed"


def apt_install(packages: list[str]) -> None:
    missing = [package for package in packages if not installed(package)]
    if not missing:
        emit("log", text="already installed: " + " ".join(packages))
        return
    # Nobody can answer dpkg here: it asks nothing about configuration files (ticket H-1207).
    env = {**os.environ, **NONINTERACTIVE_ENV}
    command = ["apt-get", "-o", "DPkg::Lock::Timeout=300", *APT_NONINTERACTIVE_OPTIONS, "install", "-y",
               "--no-install-recommends", *missing]
    for attempt in range(2):
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
        for line in process.stdout:
            emit("log", text=line.rstrip())
        if process.wait() == 0:
            return
        if attempt == 0:
            emit("step", text="apt-update")
            run(["apt-get", "-o", "DPkg::Lock::Timeout=300", "update"], check=False, env=env)
    raise HelperError("apt-get install " + " ".join(missing) + " failed")


def ufw_allow(ports: list[str]) -> None:
    if not ports or shutil.which("ufw") is None:
        return
    if "Status: active" not in run(["ufw", "status"], check=False, quiet=True).stdout:
        return
    for port in ports:
        run(["ufw", "allow", port], check=False)


def write_lab_defaults() -> None:
    LAB_OVERRIDE.write_text(LAB_DEFAULTS, encoding="utf-8")
    os.chmod(LAB_OVERRIDE, 0o644)
    run(["glib-compile-schemas", str(LAB_OVERRIDE.parent)], check=False, quiet=True)


def remove_lab_defaults() -> None:
    if LAB_OVERRIDE.exists():
        LAB_OVERRIDE.unlink()
        run(["glib-compile-schemas", str(LAB_OVERRIDE.parent)], check=False, quiet=True)


def write_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps({**state, "updated": int(time.time())}, ensure_ascii=False, indent=1) + "\n",
                         encoding="utf-8")
    os.chmod(temporary, 0o644)
    os.replace(temporary, STATE_FILE)


# ---- Veyon ----------------------------------------------------------------------------------------------------


def veyon(*args: str, check: bool = True, quiet: bool = True) -> subprocess.CompletedProcess[str]:
    return run(["veyon-cli", *args], check=check, quiet=quiet)


def network_objects() -> list[dict]:
    """The rooms and computers of Veyon's builtin directory; a fresh configuration has no such key yet."""

    result = veyon("config", "get", "BuiltinDirectory/NetworkObjects", check=False)
    if result.returncode != 0 or "[ERROR]" in result.stdout + result.stderr:
        return []
    text = result.stdout.strip()
    start = text.find("[")
    try:
        objects = json.loads(text[start:]) if start >= 0 else []
    except json.JSONDecodeError:
        return []
    return [item for item in objects if isinstance(item, dict)]


def room_uid(room: str, objects: list[dict]) -> str | None:
    for item in objects:
        if item.get("Type") == 2 and item.get("Name") == room:
            return item.get("Uid")
    return None


def ensure_room(room: str) -> None:
    if room_uid(room, network_objects()) is None:
        veyon("networkobjects", "add", "location", room)


def add_computer(room: str, student: Student, host: str | None = None) -> None:
    """Add a computer to the room; an older entry with the same network card goes first (its IP changed).

    Not by name: computers cloned from one image may all be called the same, and each must stay in the room.
    host replaces the IP as the address Veyon uses (the teacher's own computer goes in by its name).
    """

    objects = network_objects()
    parent = room_uid(room, objects)
    if parent is None:
        veyon("networkobjects", "add", "location", room)
        parent = room_uid(room, network_objects())
    for item in objects:
        if item.get("Type") == 3 and item.get("ParentUid") == parent and (
                (item.get("MacAddress") or "").lower() == student.mac):
            veyon("networkobjects", "remove", item["Uid"].strip("{}"))
    veyon("networkobjects", "add", "computer", student.name, host or student.ip, student.mac, room)


def veyon_teacher(room: str, user: str) -> bytes:
    if not PRIVATE_KEY.exists():
        veyon("authkeys", "create", KEY_NAME)
    # Veyon Master runs as the teacher: only their group may read the private key.
    veyon("authkeys", "setaccessgroup", f"{KEY_NAME}/private", system.primary_group(user))
    for key, value in (("Authentication/Method", "1"), ("Master/AutoSelectCurrentLocation", "true"),
                       ("Master/HideLocalComputer", "true")):
        veyon("config", "set", key, value)
    ensure_room(room)
    ip = system.local_ip()
    mac = system.mac_of(ip) if ip else None
    if ip and mac and valid_hostname(system.hostname()):
        # The teacher's own computer in the room, by its name: Veyon Master then knows it is this computer, opens
        # on this room by itself and leaves the teacher's own screen out (checked in a VM: by IP it does neither).
        add_computer(room, Student(name=system.hostname(), ip=ip, mac=mac), host=system.hostname())
    run(["systemctl", "enable", "--now", "veyon.service"])
    run(["systemctl", "restart", "veyon.service"], check=False, quiet=True)
    run(["systemctl", "enable", "--now", VEYON_CHECK_TIMER], check=False, quiet=True)
    return system.VEYON_PUBLIC_KEY.read_bytes()


def veyon_student(key_file: Path) -> None:
    veyon("authkeys", "delete", f"{KEY_NAME}/public", check=False)
    veyon("authkeys", "import", f"{KEY_NAME}/public", str(key_file))
    veyon("config", "set", "Authentication/Method", "1")
    run(["systemctl", "enable", "--now", "veyon.service"])
    run(["systemctl", "restart", "veyon.service"], check=False, quiet=True)
    run(["systemctl", "enable", "--now", VEYON_CHECK_TIMER], check=False, quiet=True)


# ---- Epoptes --------------------------------------------------------------------------------------------------


def epoptes_teacher(user: str) -> bytes:
    run(["gpasswd", "-a", user, "epoptes"])
    run(["systemctl", "enable", "--now", "epoptes.service"])
    return system.EPOPTES_CERT.read_bytes()


def epoptes_student(teacher_host: str, cert_file: Path) -> None:
    EPOPTES_DEFAULT.write_text(f"# CaramOS Phòng máy (caramos-lab-helper): the teacher's computer.\nSERVER={teacher_host}\n",
                               encoding="utf-8")
    os.chmod(EPOPTES_DEFAULT, 0o644)
    system.EPOPTES_CERT.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cert_file, system.EPOPTES_CERT)
    os.chmod(system.EPOPTES_CERT, 0o644)
    run(["systemctl", "enable", "epoptes-client.service"])
    run(["systemctl", "restart", "epoptes-client.service"], check=False, quiet=True)


# ---- commands -------------------------------------------------------------------------------------------------


def teacher(backend: str, room: str) -> None:
    user = system.login_user()
    emit("step", text="install")
    apt_install(PACKAGES[(backend, TEACHER)])
    emit("step", text="configure")
    key = veyon_teacher(room, user) if backend == VEYON else epoptes_teacher(user)
    ufw_allow(PORTS[(backend, TEACHER)])
    write_lab_defaults()
    write_state({"role": TEACHER, "backend": backend, "room": room, "user": user, "code": pairing_code(key)})
    emit("done", code=pairing_code(key))


def student(backend: str, room: str, teacher_host: str, teacher_name: str, key_file: Path) -> None:
    key = key_file.read_bytes()
    if len(key) > 64 * 1024 or b"-----BEGIN " not in key:
        raise HelperError("the key file is not a PEM key or certificate")
    emit("step", text="install")
    apt_install(PACKAGES[(backend, STUDENT)])
    emit("step", text="configure")
    if backend == VEYON:
        veyon_student(key_file)
    else:
        epoptes_student(teacher_host, key_file)
    ufw_allow(PORTS[(backend, STUDENT)])
    write_lab_defaults()
    write_state({"role": STUDENT, "backend": backend, "room": room,
                 "teacher": {"host": teacher_host, "name": teacher_name}, "code": pairing_code(key)})
    emit("done", code=pairing_code(key))


def add_computers(room: str, lines) -> None:
    """Students that registered while the pairing page is open, one JSON line each, until stdin closes."""

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            student = parse_registration(line.encode("utf-8"))
            add_computer(room, student)
        except (PairingError, HelperError) as error:
            emit("error", text=str(error), line=line[:200])
            continue
        emit("added", **student.as_json())


def leave() -> None:
    state = system.read_state(STATE_FILE)
    backend = state.get("backend")
    if backend == VEYON:
        run(["systemctl", "disable", "--now", VEYON_CHECK_TIMER], check=False, quiet=True)
        veyon("authkeys", "delete", f"{KEY_NAME}/public", check=False)
        if state.get("role") == TEACHER:
            veyon("authkeys", "delete", f"{KEY_NAME}/private", check=False)
        veyon("config", "set", "Authentication/Method", "0", check=False)
        # Last: veyon-cli saving its configuration enables veyon.service again (Service/Autostart, checked in a VM),
        # which left Veyon Server starting at every boot of a computer that had left the lab.
        run(["systemctl", "disable", "--now", "veyon.service"], check=False, quiet=True)
    elif backend == EPOPTES:
        if state.get("role") == STUDENT:
            run(["systemctl", "disable", "--now", "epoptes-client.service"], check=False, quiet=True)
            EPOPTES_DEFAULT.unlink(missing_ok=True)
        else:
            run(["systemctl", "disable", "--now", "epoptes.service"], check=False, quiet=True)
    remove_lab_defaults()
    STATE_FILE.unlink(missing_ok=True)
    emit("done")


def main(argv: list[str] | None = None) -> int:
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    parser = argparse.ArgumentParser(prog="caramos-lab-helper")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("teacher", "student"):
        command = commands.add_parser(name)
        command.add_argument("--backend", choices=BACKENDS, required=True)
        command.add_argument("--room", required=True)
        if name == "student":
            command.add_argument("--teacher-host", required=True)
            command.add_argument("--teacher-name", required=True)
            command.add_argument("--key", type=Path, required=True)
    commands.add_parser("add-computers").add_argument("--room", required=True)
    commands.add_parser("leave")
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        emit("error", text="must run as root (pkexec)")
        return 2
    try:
        if getattr(args, "room", None) is not None and not valid_room(args.room):
            raise HelperError("bad room name")
        if args.command == "teacher":
            teacher(args.backend, args.room)
        elif args.command == "student":
            if not (valid_ip(args.teacher_host) and valid_hostname(args.teacher_name)):
                raise HelperError("bad teacher address")
            student(args.backend, args.room, args.teacher_host, args.teacher_name, args.key)
        elif args.command == "add-computers":
            add_computers(args.room, sys.stdin)
        else:
            leave()
    except (HelperError, OSError, KeyError) as error:
        emit("error", text=str(error))
        return 1
    return 0

#!/usr/bin/python3 -I
"""Phòng máy's Veyon steps (caramos_lab.helper) against the installed veyon-cli, as root in a test container.

Runs the lab helper's own code: teacher setup, a student that pairs twice with the same network card (its IP
changed), a student's setup with the teacher's public key, leaving the lab. Only systemctl is fake (no systemd in
the container: /usr/local/bin/systemctl logs its calls to /tmp/systemctl.log). Usage:

    lab_cli_check.py CARAMOS_OTA_TREE TEACHER_USER
"""

import json
import os
import pwd
import subprocess
import sys
from pathlib import Path

tree = Path(sys.argv[1])
sys.path[:0] = [str(tree / "usr/share/caramos-ota/lab"), str(tree / "usr/lib/python3/dist-packages")]

from caramos_lab import STUDENT, TEACHER, VEYON, helper, system  # noqa: E402
from caramos_lab.pairing import Student  # noqa: E402

ROOM = "Phòng máy 1"
failures = []


def check(condition: bool, what: str) -> None:
    print(("ok   " if condition else "FAIL ") + what, flush=True)
    if not condition:
        failures.append(what)


def objects() -> list[dict]:
    return helper.network_objects()


def computers() -> list[dict]:
    return [item for item in objects() if item.get("Type") == 3]


def systemctl_calls() -> list[str]:
    try:
        return Path("/tmp/systemctl.log").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


user = sys.argv[2]
os.environ["PKEXEC_UID"] = str(pwd.getpwnam(user).pw_uid)

# --- teacher -----------------------------------------------------------------------------------------------------
helper.teacher(VEYON, ROOM)
state = system.read_state(helper.STATE_FILE)
check(state.get("role") == TEACHER and state.get("backend") == VEYON, f"teacher state written: {state}")
check(helper.PRIVATE_KEY.is_file(), f"{helper.PRIVATE_KEY} created by authkeys create")
check(system.VEYON_PUBLIC_KEY.is_file(), f"{system.VEYON_PUBLIC_KEY} created by authkeys create")
group = system.primary_group(user)
key_group = Path(helper.PRIVATE_KEY).group()
check(key_group == group, f"authkeys setaccessgroup: private key group {key_group} == {group}")
method = helper.veyon("config", "get", "Authentication/Method").stdout.strip()
check(method == "1", f"Authentication/Method is {method!r}")
for key, expected in (("Master/AutoSelectCurrentLocation", "true"), ("Master/HideLocalComputer", "true")):
    value = helper.veyon("config", "get", key).stdout.strip()
    check(value == expected, f"{key} is {value!r}")
room = helper.room_uid(ROOM, objects())
check(room is not None, f"networkobjects add location {ROOM!r} (uid {room})")
own = [item for item in computers() if item.get("HostAddress") == system.hostname()]
check(len(own) == 1, f"the teacher's computer is in the room by its name: {own}")

# --- students pairing (add-computers) ----------------------------------------------------------------------------
helper.add_computer(ROOM, Student(name="may01", ip="192.168.1.11", mac="52:54:00:00:00:11"))
helper.add_computer(ROOM, Student(name="may02", ip="192.168.1.12", mac="52:54:00:00:00:12"))
helper.add_computer(ROOM, Student(name="may01", ip="192.168.1.21", mac="52:54:00:00:00:11"))  # new IP
by_mac = {item.get("MacAddress", "").lower(): item for item in computers()}
check(len(computers()) == 3, f"3 computers in the room: {[c.get('Name') for c in computers()]}")
check(by_mac.get("52:54:00:00:00:11", {}).get("HostAddress") == "192.168.1.21",
      "a computer that pairs again with a new IP replaces its old entry (networkobjects remove by uid)")
check(all(item.get("ParentUid") == room for item in computers()), "all computers are in the room")
listing = helper.veyon("networkobjects", "list").stdout
check("may02" in listing and ROOM in listing, "networkobjects list shows the room and its computers")

# --- a student's computer ----------------------------------------------------------------------------------------
key_file = Path("/tmp/giaovien-public.pem")
key_file.write_bytes(system.VEYON_PUBLIC_KEY.read_bytes())
helper.student(VEYON, ROOM, "192.168.1.2", "maygv", key_file)
keys = helper.veyon("authkeys", "list").stdout
check("giaovien/public" in keys, f"authkeys import giaovien/public: {keys.split()}")
check(system.VEYON_PUBLIC_KEY.read_bytes() == key_file.read_bytes(), "the imported public key is the teacher's")
state = system.read_state(helper.STATE_FILE)
check(state.get("role") == STUDENT, "student state written")
calls = systemctl_calls()
check("systemctl enable --now veyon.service" in calls, "the helper enables veyon.service")
check(any(call in ("systemctl enable veyon", "systemctl enable veyon.service") for call in calls),
      "veyon-cli saving its configuration enables veyon.service itself (Service/Autostart), as 4.7.5 did")

# --- leaving the lab ---------------------------------------------------------------------------------------------
helper.teacher(VEYON, ROOM)  # the teacher's computer leaves: both keys go
Path("/tmp/systemctl.log").write_text("", encoding="utf-8")
helper.leave()
keys = helper.veyon("authkeys", "list").stdout
check("giaovien" not in keys, f"leave: authkeys delete removed the lab's keys ({keys.split()})")
method = helper.veyon("config", "get", "Authentication/Method").stdout.strip()
check(method == "0", f"leave: Authentication/Method is {method!r}")
calls = systemctl_calls()
check(bool(calls) and calls[-1] == "systemctl disable --now veyon.service",
      f"leave: veyon.service disabled last, after veyon-cli enabled it again ({calls})")

print(json.dumps({"failures": failures}, ensure_ascii=False))
sys.exit(1 if failures else 0)

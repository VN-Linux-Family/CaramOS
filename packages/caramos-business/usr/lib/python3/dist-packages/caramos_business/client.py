"""The employee side of pairing (PROTOCOL.md "Pairing code"): find the admins on the LAN, check the code the user
types against the admin's key, register with this machine's box key, and what this machine reports about itself
(MACHINE). authed() makes the authenticated requests of part 2 (the Rust agent makes its own; tests and tools use
this one)."""

from __future__ import annotations

import json
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import protocol
from .i18n import _

CARAMOS_RELEASE = Path("/etc/caramos-release")


class PairingError(Exception):
    """A pairing that cannot go on; its text is for the window."""


class TokenRefused(PairingError):
    """An enrolment file's token that the admin refuses for good (expired, used up, withdrawn)."""


def discover(timeout: float = 2.0) -> list[dict[str, Any]]:
    """The admins that answer a broadcast on the LAN: [{"name", "ip", "port", "fingerprint", "pairing"}]."""

    found: dict[str, dict[str, Any]] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # From discovery's own port when it is free: a firewall on this machine lets the answers in there (they come
        # from the admin's address, which connection tracking does not match to a broadcast). Else any port.
        try:
            sock.bind(("0.0.0.0", protocol.UDP_PORT))
        except OSError:
            pass
        sock.settimeout(0.3)
        sock.sendto(protocol.DISCOVER.encode("ascii"), ("255.255.255.255", protocol.UDP_PORT))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, (ip, _port) = sock.recvfrom(protocol.MAX_DATAGRAM + 1)
            except socket.timeout:
                continue
            except OSError:
                break
            answer = protocol.parse_here(data)
            if answer is not None:
                found[ip] = dict(answer, ip=ip)
    return sorted(found.values(), key=lambda admin: admin["name"])


def _request(url: str, body: Any = None, timeout: float = 8.0) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - http on the LAN, by design
            return response.status, json.loads(response.read(protocol.MAX_BODY).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read(protocol.MAX_BODY).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return exc.code, None
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise PairingError(_("The admin machine does not answer. Is it on, and on the same network?")) from exc


def admin_url(ip: str, port: int = protocol.HTTP_PORT) -> str:
    return f"http://{ip}:{port}"


def edition() -> str:
    if Path("/usr/bin/cinnamon").exists():
        return "cinnamon"
    if Path("/usr/bin/xfce4-session").exists():
        return "xfce"
    return "other"


def caramos_version(path: Path = CARAMOS_RELEASE) -> str:
    try:
        match = re.search(r'^VERSION="?([^"\n]*)"?$', path.read_text(encoding="utf-8"), re.M)
    except OSError:
        return ""
    value = match.group(1) if match else ""
    return value if protocol.VERSION.match(value) else ""


def route_toward(ip: str) -> tuple[str, str]:
    """(this machine's IPv4, its card's MAC) on the way to an address."""

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((ip, protocol.HTTP_PORT))  # UDP: sends nothing
        local = sock.getsockname()[0]
    mac = ""
    try:
        routes = json.loads(subprocess.run(["ip", "-j", "route", "get", ip], capture_output=True, text=True,
                                           timeout=5, check=True).stdout)
        device = routes[0]["dev"] if routes else ""
        mac = Path(f"/sys/class/net/{device}/address").read_text(encoding="ascii").strip() if device else ""
    except (OSError, ValueError, KeyError, IndexError, subprocess.SubprocessError):
        pass
    return local, mac if protocol.MAC.match(mac) else ""


def machine_info(admin_ip: str) -> dict[str, str]:
    ip, mac = route_toward(admin_ip)
    name = socket.gethostname().split(".")[0]
    return protocol.validate_machine({"name": name, "ip": ip, "mac": mac, "edition": edition(),
                                      "version": caramos_version()})


def agent_config(url: str, answer: dict[str, Any]) -> dict[str, str]:
    """agent.json from a pairing's or an enrolment's answer. From 0.3 it holds the admin's box key too (PROTOCOL.md
    part 3, "Changes during implementation"): the agent's first request, GET /policy, needs it for its HMAC."""

    key = protocol.unb64(answer["admin_key"], 32)
    protocol.unb64(answer["admin_box_key"], 32)
    return {"admin_url": url, "admin_name": answer["admin_name"][:64], "admin_key": answer["admin_key"],
            "admin_box_key": answer["admin_box_key"], "fingerprint": protocol.fingerprint(key),
            "machine_id": answer["machine_id"]}


def pair(ip: str, code: str, box_private: bytes, port: int = protocol.HTTP_PORT) -> tuple[dict[str, str], str]:
    """Pairs with the admin at ip with the code its window shows (SPAKE2, PROTOCOL.md part 3): (the agent's config,
    "approved" or "pending")."""

    from . import pairing  # noqa: PLC0415 - needs python3-spake2, only here

    code = code.strip()
    if not re.fullmatch(r"\d{6}", code):
        raise PairingError(_("The code has 6 digits."))
    url = admin_url(ip, port)
    try:
        answer = pairing.pair_with_code(url, code, machine_info(ip), protocol.b64(protocol.box_public(box_private)))
    except pairing.PairingError as exc:
        raise PairingError(str(exc)) from exc
    return agent_config(url, answer), answer["state"]


def enroll(data: dict[str, Any], box_private: bytes, find: Any = None) -> tuple[dict[str, str], str]:
    """Enrols with an enrolment file (PROTOCOL.md part 3): at the file's address, or where discovery finds the
    admin with the file's fingerprint. (the agent's config, state)."""

    from . import pairing  # noqa: PLC0415

    box_key = protocol.b64(protocol.box_public(box_private))
    url = data["admin_url"]
    ip = url.split("//", 1)[1].rsplit(":", 1)[0]
    try:
        answer = pairing.enroll_with_file(data, machine_info(ip), box_key, url)
    except pairing.TokenRefused as exc:
        raise TokenRefused(str(exc)) from exc
    except pairing.Unreachable as first:
        moved = [found for found in (find or discover)(2.0) if found.get("fingerprint") == data["fingerprint"]]
        if not moved:
            raise PairingError(str(first)) from first
        ip = moved[0]["ip"]
        url = admin_url(ip, moved[0].get("port", protocol.HTTP_PORT))
        try:
            answer = pairing.enroll_with_file(data, machine_info(ip), box_key, url)
        except pairing.TokenRefused as exc:
            raise TokenRefused(str(exc)) from exc
        except pairing.PairingError as exc:
            raise PairingError(str(exc)) from exc
    except pairing.PairingError as exc:
        raise PairingError(str(exc)) from exc
    return agent_config(url, answer), answer["state"]


def os_machine_id(path: Path) -> str:
    """/etc/machine-id, or '' when it is not one (32 lower-case hex digits)."""

    try:
        value = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return ""
    return value if re.fullmatch(r"[0-9a-f]{32}", value) else ""


def cloned(info: Any, os_machine_id_path: Path, marker: Path) -> bool:
    """Whether this disk is a clone of the paired machine (PROTOCOL.md part 2 "Cloned disks"): the agent marked it,
    or /etc/machine-id is no longer the one admin.json kept at pairing."""

    if marker.exists():
        return True
    paired_on = info.get("machine_id_os") if isinstance(info, dict) else None
    here = os_machine_id(os_machine_id_path)
    return bool(paired_on and here and here != paired_on)


def paired_by_older_version(info: Any, box_key: Path) -> bool:
    """Whether the pairing is 0.1's: it has no machine key, so the agent cannot sign its requests and the admin shows
    "needs pairing again" (PROTOCOL.md part 2, "Changes to part 1"). Only the key's existence is looked at: it is
    root's."""

    return isinstance(info, dict) and not box_key.exists()


def authed(url: str, machine_id: str, mac_key: bytes, method: str, target: str, body: Any = None,
           timeout: float = 70.0, now: float | None = None) -> tuple[int, Any]:
    """An authenticated request (PROTOCOL.md part 2): (status, JSON answer or None)."""

    data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = protocol.auth_headers(machine_id, mac_key, method, target, data, now)
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url + target, data=data if method == "POST" else None, headers=headers,
                                     method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - http on the LAN, by design
            return response.status, json.loads(response.read(protocol.MAX_INVENTORY).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read(protocol.MAX_BODY).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return exc.code, None

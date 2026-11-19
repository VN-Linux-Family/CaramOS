"""Pairing a student's computer with the teacher's over the school LAN.

While the teacher's pairing page is open, the teacher's computer answers UDP broadcasts on port 47011 and serves
on TCP 47012:
    GET  /caramos-lab/v1/key       the Veyon public key (PEM) or the Epoptes server certificate
    POST /caramos-lab/v1/register  {"name": hostname, "ip": IPv4, "mac": "aa:bb:…"} of a paired student
A student's computer broadcasts a discovery request, lists the teachers that answer, downloads the key of the one
picked and checks it against the 6-digit code shown on the teacher's screen: pairing_code() of the key bytes. A
computer that only pretends to be the teacher's cannot know a key with the same code in the minute it has.

Everything here is plain Python (no GTK, no root) and validated strictly: the teacher's computer passes what
students send to veyon-cli through the root helper.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import socket
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from . import BACKENDS

MAGIC = "CARAMOS-LAB/1"
UDP_PORT = 47011
HTTP_PORT = 47012
KEY_PATH = "/caramos-lab/v1/key"
REGISTER_PATH = "/caramos-lab/v1/register"
MAX_DATAGRAM = 2048
MAX_BODY = 2048
MAX_KEY = 64 * 1024

HOSTNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
MAC = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")
ROOM = re.compile(r"^[\w][\w \-]{0,39}$")


class PairingError(Exception):
    pass


def pairing_code(key: bytes) -> str:
    """Six digits from the SHA-256 of the key or certificate, shown as "123 456" on the teacher's screen."""

    return f"{int(hashlib.sha256(key).hexdigest()[:15], 16) % 1_000_000:06d}"


def spaced(code: str) -> str:
    return f"{code[:3]} {code[3:]}"


def clean_code(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def valid_hostname(name: str) -> bool:
    return len(name) <= 253 and bool(HOSTNAME.match(name))


def valid_ip(text: str) -> bool:
    try:
        address = ipaddress.IPv4Address(text)
    except ValueError:
        return False
    return address.is_private or address.is_link_local


def valid_mac(text: str) -> bool:
    return bool(MAC.match(text)) and text != "00:00:00:00:00:00"


def valid_room(text: str) -> bool:
    return bool(ROOM.match(text)) and text == text.strip()


@dataclass(frozen=True)
class Teacher:
    """A teacher's computer that answered the discovery broadcast."""

    host: str
    name: str
    room: str
    backend: str
    port: int = HTTP_PORT


@dataclass(frozen=True)
class Student:
    """A student's computer that registered with the teacher's."""

    name: str
    ip: str
    mac: str

    def as_json(self) -> dict[str, str]:
        return {"name": self.name, "ip": self.ip, "mac": self.mac}


def discovery_request() -> bytes:
    return json.dumps({"magic": MAGIC, "type": "discover"}).encode("utf-8")


def announcement(name: str, room: str, backend: str, port: int = HTTP_PORT) -> bytes:
    return json.dumps({"magic": MAGIC, "type": "teacher", "name": name, "room": room, "backend": backend,
                       "port": port}, ensure_ascii=False).encode("utf-8")


def parse_announcement(data: bytes, host: str) -> Teacher | None:
    try:
        message = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(message, dict) or message.get("magic") != MAGIC or message.get("type") != "teacher":
        return None
    name, room, backend, port = message.get("name"), message.get("room"), message.get("backend"), message.get("port")
    if not (isinstance(name, str) and valid_hostname(name) and isinstance(room, str) and valid_room(room)
            and backend in BACKENDS and isinstance(port, int) and 1024 < port < 65536 and valid_ip(host)):
        return None
    return Teacher(host=host, name=name, room=room, backend=backend, port=port)


def parse_registration(data: bytes) -> Student:
    try:
        message = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PairingError("not JSON") from error
    if not isinstance(message, dict):
        raise PairingError("not an object")
    name, ip, mac = message.get("name"), message.get("ip"), message.get("mac")
    if not (isinstance(name, str) and valid_hostname(name)):
        raise PairingError("bad name")
    if not (isinstance(ip, str) and valid_ip(ip)):
        raise PairingError("bad ip")
    if not (isinstance(mac, str) and valid_mac(mac.lower())):
        raise PairingError("bad mac")
    return Student(name=name, ip=ip, mac=mac.lower())


# ---- teacher's side -------------------------------------------------------------------------------------------


class TeacherServer:
    """The discovery answer and the key download, only while the teacher's pairing page is open.

    on_register(student) is called from a server thread for each valid registration; the IP a student reports must
    be the address it connects from.
    """

    def __init__(self, name: str, room: str, backend: str, key: bytes,
                 on_register: Callable[[Student], None], udp_port: int = UDP_PORT, http_port: int = HTTP_PORT,
                 bind: str = "0.0.0.0") -> None:
        self.name, self.room, self.backend, self.key = name, room, backend, key
        self.on_register = on_register
        self.code = pairing_code(key)
        self._udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._udp.bind((bind, udp_port))
        self._udp.settimeout(0.5)
        self._http = ThreadingHTTPServer((bind, http_port), self._handler())
        self._http.daemon_threads = True
        self.http_port = self._http.server_address[1]
        self.udp_port = self._udp.getsockname()[1]
        self._stop = threading.Event()
        self._threads = [threading.Thread(target=self._answer, daemon=True),
                         threading.Thread(target=self._http.serve_forever, daemon=True)]

    def start(self) -> "TeacherServer":
        for thread in self._threads:
            thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._http.shutdown()
        self._http.server_close()
        self._udp.close()

    def _answer(self) -> None:
        reply = announcement(self.name, self.room, self.backend, self.http_port)
        while not self._stop.is_set():
            try:
                data, peer = self._udp.recvfrom(MAX_DATAGRAM)
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                message = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(message, dict) and message.get("magic") == MAGIC and message.get("type") == "discover":
                try:
                    self._udp.sendto(reply, peer)
                except OSError:
                    pass

    def _handler(self):
        server = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "CaramOS-Lab/1"

            def log_message(self, *_args) -> None:  # no request logs on stderr
                pass

            def _send(self, status: int, body: bytes, kind: str = "application/json") -> None:
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == KEY_PATH:
                    self._send(200, server.key, "application/x-pem-file")
                else:
                    self._send(404, b'{"ok": false}')

            def do_POST(self) -> None:  # noqa: N802
                if self.path != REGISTER_PATH:
                    self._send(404, b'{"ok": false}')
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = -1
                if not 0 < length <= MAX_BODY:
                    self._send(413, b'{"ok": false}')
                    return
                try:
                    student = parse_registration(self.rfile.read(length))
                except PairingError:
                    self._send(400, b'{"ok": false}')
                    return
                if student.ip != self.client_address[0]:
                    self._send(400, b'{"ok": false}')
                    return
                server.on_register(student)
                self._send(200, b'{"ok": true}')

        return Handler


# ---- student's side -------------------------------------------------------------------------------------------


def broadcast_addresses() -> list[str]:
    """255.255.255.255 plus the broadcast address of each IPv4 network this computer is on."""

    addresses = ["255.255.255.255"]
    try:
        import subprocess
        result = subprocess.run(["ip", "-j", "-4", "addr"], capture_output=True, text=True, check=False, timeout=5)
        for interface in json.loads(result.stdout or "[]"):
            for info in interface.get("addr_info", []):
                if info.get("broadcast") and info["broadcast"] not in addresses:
                    addresses.append(info["broadcast"])
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    return addresses


def discover(timeout: float = 2.5, port: int = UDP_PORT, targets: list[str] | None = None) -> list[Teacher]:
    """The teachers' computers whose pairing page is open, each once."""

    found: dict[tuple[str, int], Teacher] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(0.3)
        request = discovery_request()
        for target in targets or broadcast_addresses():
            try:
                sock.sendto(request, (target, port))
            except OSError:
                continue
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, peer = sock.recvfrom(MAX_DATAGRAM)
            except socket.timeout:
                continue
            teacher = parse_announcement(data, peer[0])
            if teacher is not None:
                found[(teacher.host, teacher.port)] = teacher
    return sorted(found.values(), key=lambda item: (item.room, item.name, item.host))


def fetch_key(teacher: Teacher, timeout: float = 10) -> bytes:
    url = f"http://{teacher.host}:{teacher.port}{KEY_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            data = response.read(MAX_KEY + 1)
    except (urllib.error.URLError, OSError) as error:
        raise PairingError(f"cannot download the key from {teacher.host}: {error}") from error
    if not data or len(data) > MAX_KEY or b"-----BEGIN " not in data:
        raise PairingError("the teacher's computer did not send a key")
    return data


def check_code(key: bytes, typed: str) -> bool:
    return clean_code(typed) == pairing_code(key)


def register(teacher: Teacher, student: Student, timeout: float = 10) -> None:
    body = json.dumps(student.as_json()).encode("utf-8")
    request = urllib.request.Request(f"http://{teacher.host}:{teacher.port}{REGISTER_PATH}", data=body,
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(MAX_BODY)
    except (urllib.error.URLError, OSError) as error:
        raise PairingError(f"the teacher's computer did not take the registration: {error}") from error

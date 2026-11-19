"""What the lab tool needs to know about this computer: its name, address and network card, Veyon and Epoptes."""

from __future__ import annotations

import grp
import json
import os
import pwd
import socket
import subprocess
from pathlib import Path

from . import STATE_DIR

VEYON_PUBLIC_KEY = Path("/etc/veyon/keys/public/giaovien/key")
EPOPTES_CERT = Path("/etc/epoptes/server.crt")
STATE_FILE = Path(STATE_DIR) / "state.json"


def hostname() -> str:
    return socket.gethostname().split(".")[0]


def local_ip(toward: str = "192.0.2.1", port: int = 9) -> str | None:
    """The IPv4 address this computer uses toward an address (UDP connect sends nothing)."""

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect((toward, port))
            address = sock.getsockname()[0]
    except OSError:
        return None
    return None if address.startswith("0.") else address


def interfaces() -> list[dict]:
    try:
        result = subprocess.run(["ip", "-j", "addr"], capture_output=True, text=True, check=False, timeout=5)
        data = json.loads(result.stdout or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    return data if isinstance(data, list) else []


def mac_of(ip: str, links: list[dict] | None = None) -> str | None:
    for link in links if links is not None else interfaces():
        for info in link.get("addr_info", []):
            if info.get("family") == "inet" and info.get("local") == ip:
                mac = (link.get("address") or "").lower()
                return mac if mac and mac != "00:00:00:00:00:00" else None
    return None


def primary_group(user: str) -> str:
    return grp.getgrgid(pwd.getpwnam(user).pw_gid).gr_name


def login_user() -> str:
    """The user who opened the window (pkexec sets PKEXEC_UID for the helper)."""

    uid = os.environ.get("PKEXEC_UID")
    return pwd.getpwuid(int(uid) if uid and uid.isdigit() else os.getuid()).pw_name


def read_state(path: Path = STATE_FILE) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def teacher_key(backend: str) -> bytes | None:
    """What students download: Veyon's public key or Epoptes' server certificate (both world-readable)."""

    path = VEYON_PUBLIC_KEY if backend == "veyon" else EPOPTES_CERT
    try:
        return path.read_bytes()
    except OSError:
        return None

"""Finding the network printers for the admin window's "Tìm máy in trong mạng": ippfind (cups-ipp-utils) or
avahi-browse (avahi-utils), whichever is installed, both asking for IPP printers over DNS-SD."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

from . import protocol


@dataclass(frozen=True)
class Found:
    name: str
    uri: str
    location: str


def _unescape(text: str) -> str:
    """avahi-browse -p escapes some characters as \\DDD (decimal)."""

    return re.sub(r"\\(\d{3})", lambda match: chr(int(match.group(1))), text)


def parse_avahi(output: str) -> list[Found]:
    """avahi-browse -rpt _ipp._tcp: '=;iface;IPv4;name;_ipp._tcp;local;host;address;port;"txt" "txt"'."""

    found: dict[str, Found] = {}
    for line in output.splitlines():
        fields = line.split(";", 9)
        if len(fields) < 10 or fields[0] != "=" or fields[2] != "IPv4":
            continue
        name, address, port = _unescape(fields[3]), fields[7], fields[8]
        txt = dict(re.findall(r'"([^"=]+)=([^"]*)"', _unescape(fields[9])))
        resource = txt.get("rp", "ipp/print").lstrip("/")
        scheme = "ipps" if txt.get("TLS") and fields[4] == "_ipps._tcp" else "ipp"
        uri = f"{scheme}://{address}:{port}/{resource}" if port != "631" else f"{scheme}://{address}/{resource}"
        if protocol.valid_printer_uri(uri):
            found[uri] = Found(txt.get("ty") or name, uri, txt.get("note", ""))
    return list(found.values())


def parse_ippfind(output: str) -> list[Found]:
    """Lines 'URI<TAB>name<TAB>note' (ippfind --exec echo, see find())."""

    found: dict[str, Found] = {}
    for line in output.splitlines():
        parts = line.split("\t")
        uri = parts[0].strip()
        if not protocol.valid_printer_uri(uri):
            continue
        name = parts[1].strip() if len(parts) > 1 else ""
        note = parts[2].strip() if len(parts) > 2 else ""
        found[uri] = Found(name or uri.split("//", 1)[1].split("/", 1)[0], uri, note)
    return list(found.values())


def find(timeout: int = 5) -> list[Found]:
    """The IPP printers that answer on the LAN within timeout seconds."""

    if shutil.which("avahi-browse"):
        try:
            result = subprocess.run(["avahi-browse", "-rpt", "_ipp._tcp"], capture_output=True, text=True,
                                    timeout=timeout + 10, check=False)
            printers = parse_avahi(result.stdout)
            if printers:
                return printers
        except (OSError, subprocess.SubprocessError):
            pass
    if shutil.which("ippfind"):
        try:
            result = subprocess.run(["ippfind", "-T", str(timeout), "_ipp._tcp", "--exec", "printf",
                                     "%s\\t%s\\t%s\\n", "{}", "{service_name}", "{txt_note}", ";"],
                                    capture_output=True, text=True, timeout=timeout + 10, check=False)
            return parse_ippfind(result.stdout)
        except (OSError, subprocess.SubprocessError):
            pass
    return []


def uri_for_address(address: str) -> str | None:
    """The usual IPP Everywhere address of a printer at an IP address or host name."""

    address = address.strip()
    uri = f"ipp://{address}/ipp/print"
    return uri if address and protocol.valid_printer_uri(uri) else None

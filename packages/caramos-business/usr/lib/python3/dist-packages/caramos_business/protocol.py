"""The protocol of PROTOCOL.md, parts 1 to 3: ports and paths, the checks every message gets, the Ed25519 signatures
of policies, commands, removal notices and ticket lists, the machine keys (X25519 and HKDF), request MACs, sealed
secrets, the policy's format 2 with departments and machine overrides, commands, inventory and health, and the
transcripts and confirmations of pairing (SPAKE2) and of enrolment by file (part 3).

Plain Python plus the cryptography package (in every CaramOS). The Rust agent does the same checks; both are tested
against tests/protocol-examples (v2/ for part 2, v3/ for part 3). Where the admin is stricter than the contract (it
refuses to sign a few things an agent would accept), PROTOCOL.md says so."""

from __future__ import annotations

import base64
import binascii
import datetime
import hashlib
import hmac
import ipaddress
import json
import os
import re
import time
import urllib.parse
from typing import Any

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .i18n import _

UDP_PORT = 47021
HTTP_PORT = 47022
PREFIX = "/caramos-business/v1"
MAGIC = "CARAMOS-BUSINESS/1"
DISCOVER = f"{MAGIC} DISCOVER"
HERE = f"{MAGIC} HERE "
MAX_DATAGRAM = 2048
MAX_BODY = 64 * 1024
MAX_INVENTORY = 1024 * 1024
MAX_POLICY = 1024 * 1024
MAX_FILE = 20 * 1024 * 1024
MAX_PERIODS = 50
MAX_NAME = 60
MAX_DETAIL = 200
PAIRING_SECONDS = 600
FORMAT = 2
FILE_TYPES = ("jpg", "png", "webp")
EDITIONS = ("cinnamon", "xfce", "other")
WALLPAPER_STATES = ("applied", "failed", "off")
FOLDER_STATES = ("server", "local", "failed", "off")

# Part 2
HKDF_SALT = b"caramos-business/2"
HKDF_SALT_3 = b"caramos-business/3"      # part 3: pairing and enrolment
MAX_SKEW = 86400            # a request whose time is further off is refused
SKEW_PROBLEM = 120          # the health checks flag more
WAIT_SECONDS = 50
MAX_WAIT_COMMANDS = 50
MAX_DEPARTMENTS = 50
MAX_COMMAND_LIFETIME = datetime.timedelta(hours=24)
# Every section is opt-in (PROTOCOL.md part 2, "Everything is opt-in"): absent means not managed.
SECTIONS = ("wallpaper", "folders", "shares", "browser", "printers", "power", "apps", "usb", "screen_lock",
            "firewall", "inventory", "wifi", "shared", "snapshots")
CAPABILITIES = SECTIONS + ("commands", "licence-report", "tickets")
CAPABILITY = re.compile(r"^[a-z_-]{1,32}$")
SNAPSHOT_SCHEDULES = ("daily", "weekly", "monthly")
TICKET_STATES = ("new", "working", "waiting", "done")
ENCRYPTION = ("luks", "none", "unknown")
TOKEN_ID = re.compile(r"^[0-9a-f]{16}$")
TICKET_ID = re.compile(r"^HT-\d{4,9}$")
HOSTNAME_PREFIX = re.compile(r"^[a-z0-9-]{1,20}$")
RESULT_STATES = ("done", "failed", "refused", "expired", "ignored")
USB_STORAGE = ("allow", "read-only", "block")
USB_STATES = USB_STORAGE + ("unlocked",)
LAPTOP_CHOICES = ("skip", "suspend", "same")
WIFI_SECURITY = ("wpa-psk", "open")

SHA256 = re.compile(r"^[0-9a-f]{64}$")
MONTH_DAY = re.compile(r"^(\d{2})-(\d{2})$")
HOSTNAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
MAC = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$")
LOGIN = re.compile(r"^[a-z_][a-z0-9_.-]{0,31}$")
SHARE = re.compile(r"^smb://([A-Za-z0-9.-]+)/([^/\s@]+)((?:/[^/\s@]+)*)/?$")
VERSION = re.compile(r"^[0-9][0-9A-Za-z.+~-]{0,31}$|^$")
TIME_OF_DAY = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
DEPARTMENT_ID = re.compile(r"^[a-z0-9-]{1,32}$")
APP_ID = re.compile(r"^[a-z0-9-]{1,40}$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
DOMAIN_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
SECTION_KEY = re.compile(r"^[a-z_]{1,32}$")


class ProtocolError(ValueError):
    """A message or policy that does not follow PROTOCOL.md. section and scope say where, for the window: the
    settings section ("browser") and the layer ("company", "department:ke-toan", "machine:<id>")."""

    def __init__(self, message: str, section: str | None = None, scope: str | None = None) -> None:
        super().__init__(message)
        self.section = section
        self.scope = scope


class CommandRefused(ProtocolError):
    """A command an agent does not run; state is the result it reports: refused, expired or ignored."""

    def __init__(self, message: str, state: str) -> None:
        super().__init__(message)
        self.state = state


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProtocolError(message)


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _number(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)) and value == value  # not NaN


def _short_text(value: Any, limit: int) -> bool:
    return isinstance(value, str) and len(value) <= limit and "\n" not in value


def _clean_text(value: Any, limit: int, *, empty: bool = True, newlines: bool = False) -> bool:
    """A string of at most limit characters without control characters (newlines only if allowed)."""

    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        return False
    return not any(ord(char) < 32 and not (newlines and char == "\n") or ord(char) == 127 for char in value)


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(value: Any, length: int | None = None) -> bytes:
    _require(isinstance(value, str), "not base64")
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProtocolError("not base64") from exc
    _require(length is None or len(data) == length, "a key of the wrong length")
    return data


# -- keys, fingerprints, pairing ---------------------------------------------------------------------------------------

def public_bytes(key: Ed25519PrivateKey | Ed25519PublicKey) -> bytes:
    public = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    return public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def fingerprint(public: bytes) -> str:
    return hashlib.sha256(public).hexdigest()[:16]


def new_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


def key_to_pem(key: Ed25519PrivateKey) -> bytes:
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def key_from_pem(data: bytes) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(data, password=None)
    _require(isinstance(key, Ed25519PrivateKey), "not an Ed25519 key")
    return key


# -- machine keys (part 2, "Machine keys and request authentication") -------------------------------------------------

def new_box_key() -> bytes:
    """A new X25519 private key, raw 32 bytes (admin-box.key, agent-box.key)."""

    return X25519PrivateKey.generate().private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                                     serialization.NoEncryption())


def box_public(private: bytes) -> bytes:
    return X25519PrivateKey.from_private_bytes(private).public_key().public_bytes(serialization.Encoding.Raw,
                                                                                serialization.PublicFormat.Raw)


def shared_secret(private: bytes, public: bytes) -> bytes:
    try:
        return X25519PrivateKey.from_private_bytes(private).exchange(X25519PublicKey.from_public_bytes(public))
    except ValueError as exc:
        raise ProtocolError("not an X25519 key") from exc


def _derive(secret: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=HKDF_SALT, info=info).derive(secret)


def machine_keys(private: bytes, public: bytes) -> tuple[bytes, bytes]:
    """(mac_key, seal_key) between one side's private box key and the other side's public one."""

    secret = shared_secret(private, public)
    return _derive(secret, b"mac"), _derive(secret, b"seal")


def mac_message(method: str, target: str, when: str | int, body: bytes) -> bytes:
    return f"{method}\n{target}\n{when}\n{hashlib.sha256(body).hexdigest()}".encode("utf-8")


def request_mac(mac_key: bytes, method: str, target: str, when: str | int, body: bytes = b"") -> str:
    return b64(hmac.new(mac_key, mac_message(method, target, when, body), hashlib.sha256).digest())


def check_request_mac(mac_key: bytes, method: str, target: str, when: str, body: bytes, mac: Any) -> bool:
    """Whether a request's X-Caramos-Mac is right, compared in constant time."""

    try:
        given = unb64(mac)
    except ProtocolError:
        return False
    expected = hmac.new(mac_key, mac_message(method, target, when, body), hashlib.sha256).digest()
    return hmac.compare_digest(given, expected)


def auth_headers(machine_id: str, mac_key: bytes, method: str, target: str, body: bytes = b"",
                 now: float | None = None) -> dict[str, str]:
    """The three headers of an authenticated request (what the agent sends; used by tests and tools)."""

    when = str(int(time.time() if now is None else now))
    return {"X-Caramos-Machine": machine_id, "X-Caramos-Time": when,
            "X-Caramos-Mac": request_mac(mac_key, method, target, when, body)}


def seal(seal_key: bytes, machine_id: str, secrets: dict[str, Any], nonce: bytes | None = None) -> str:
    """A machine's secrets sealed for it: base64(nonce || ChaCha20-Poly1305(plaintext, aad=machine_id))."""

    nonce = nonce or os.urandom(12)
    plaintext = json.dumps(secrets, ensure_ascii=False).encode("utf-8")
    return b64(nonce + ChaCha20Poly1305(seal_key).encrypt(nonce, plaintext, machine_id.encode("ascii")))


def unseal(seal_key: bytes, machine_id: str, blob: Any) -> dict[str, Any]:
    data = unb64(blob)
    _require(len(data) >= 12 + 16, "a sealed blob that is too short")
    try:
        plaintext = ChaCha20Poly1305(seal_key).decrypt(data[:12], data[12:], machine_id.encode("ascii"))
        value = json.loads(plaintext.decode("utf-8"))
    except (InvalidTag, UnicodeDecodeError, ValueError) as exc:
        raise ProtocolError("the sealed secrets do not open with this key") from exc
    _require(isinstance(value, dict), "the sealed secrets are not an object")
    return value


# -- signed texts: the policy and commands -----------------------------------------------------------------------------

def _sign_text(key: Ed25519PrivateKey, value: dict[str, Any], field: str) -> dict[str, str]:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return {field: text, "signature": b64(key.sign(text.encode("utf-8")))}


def verify_signed_text(signed: Any, public: bytes, field: str) -> str:
    """The text of a signed envelope ({field: text, "signature"}) once its signature matches the key."""

    _require(isinstance(signed, dict), "not an object")
    text, signature = signed.get(field), signed.get("signature")
    _require(isinstance(text, str) and isinstance(signature, str), f"{field} and signature must be strings")
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(base64.b64decode(signature, validate=True),
                                                          text.encode("utf-8"))
    except (InvalidSignature, ValueError, binascii.Error) as exc:
        raise ProtocolError("the signature does not match the admin's key") from exc
    return text


def sign_policy(key: Ed25519PrivateKey, policy: dict[str, Any]) -> dict[str, str]:
    """GET /policy's answer: the policy as a JSON text and the signature of that text's bytes. Refuses a policy
    that is not valid or whose text is over 1 MiB."""

    validate_policy(policy)
    signed = _sign_text(key, policy, "policy")
    size = len(signed["policy"].encode("utf-8"))
    if size > MAX_POLICY:
        raise ProtocolError(_("The settings are too big to send (%(size)d KB, at most %(limit)d KB). Remove some "
                              "blocked websites, bookmarks or machine settings.")
                            % {"size": size // 1024, "limit": MAX_POLICY // 1024})
    return signed


def verify_signed_policy(signed: Any, public: bytes) -> dict[str, Any]:
    """The policy of a GET /policy answer, after its signature and its contents are checked."""

    text = verify_signed_text(signed, public, "policy")
    _require(len(text.encode("utf-8")) <= MAX_POLICY, "the policy is over 1 MiB")
    try:
        policy = json.loads(text)
    except ValueError as exc:
        raise ProtocolError("the policy is not JSON") from exc
    validate_policy(policy)
    return policy


# -- the policy: part 1's rules, used inside the sections --------------------------------------------------------------

def valid_month_day(value: Any) -> bool:
    match = MONTH_DAY.match(value) if isinstance(value, str) else None
    if not match:
        return False
    try:
        datetime.date(2024, int(match.group(1)), int(match.group(2)))  # a leap year: 02-29 is a day
    except ValueError:
        return False
    return True


def valid_share(value: Any) -> bool:
    return isinstance(value, str) and ".." not in value and SHARE.match(value) is not None


def valid_time(value: Any) -> bool:
    return isinstance(value, str) and TIME_OF_DAY.match(value) is not None


def minutes_of(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def valid_domain(value: Any) -> bool:
    """A domain to block: lower-case labels of [a-z0-9-], at least two of them, no scheme, no path, not an IP."""

    if not isinstance(value, str) or not 3 <= len(value) <= 253:
        return False
    try:
        ipaddress.ip_address(value)
        return False
    except ValueError:
        pass
    labels = value.split(".")
    return len(labels) >= 2 and all(DOMAIN_LABEL.match(label) for label in labels)


def valid_web_url(value: Any, limit: int = 2000) -> bool:
    if not _clean_text(value, limit, empty=False) or " " in value:
        return False
    try:
        parts = urllib.parse.urlsplit(value)
        host = parts.hostname
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(host)


def valid_printer_uri(value: Any) -> bool:
    if not _clean_text(value, 500, empty=False) or " " in value or "@" in value:
        return False
    try:
        parts = urllib.parse.urlsplit(value)
        host = parts.hostname
        parts.port  # noqa: B018 - raises ValueError for a bad port
    except ValueError:
        return False
    return parts.scheme in ("ipp", "ipps") and bool(host)


def valid_passphrase(value: Any) -> bool:
    """A WPA passphrase: 8 to 63 printable ASCII characters."""

    return isinstance(value, str) and 8 <= len(value) <= 63 and all(32 <= ord(char) < 127 for char in value)


def _days(value: Any) -> bool:
    return (isinstance(value, list) and 0 < len(value) <= 7 and len(set(map(str, value))) == len(value)
            and all(_int(day) and 1 <= day <= 7 for day in value))


def _within(value: Any, low: int, high: int) -> bool:
    return _int(value) and low <= value <= high


def _object(value: Any, message: str) -> dict[str, Any]:
    _require(isinstance(value, dict), message)
    return value


def _list(value: Any, limit: int, message: str) -> list[Any]:
    _require(isinstance(value, list) and len(value) <= limit, message)
    return value


def _unique(values: list[Any], message: str) -> None:
    _require(len(set(values)) == len(values), message)


# -- the settings sections (part 2, "Settings sections") ---------------------------------------------------------------

def _wallpaper(value: Any, files: dict[str, Any]) -> None:
    wallpaper = _object(value, _("The wallpaper settings are not valid."))
    default = wallpaper.get("default")
    _require(default is None or default in files, _("A picture is missing: choose it again."))
    periods = _list(wallpaper.get("periods", []), MAX_PERIODS, _("At most 50 special days."))
    for period in periods:
        _require(isinstance(period, dict), _("The special days are not valid."))
        _require(_short_text(period.get("name", ""), MAX_NAME), _("A name is longer than 60 characters."))
        _require(valid_month_day(period.get("from")) and valid_month_day(period.get("to")),
                 _("Write the days as day/month, such as 25/1."))
        _require(period.get("image") in files, _("A picture is missing: choose it again."))
    _require(isinstance(wallpaper.get("lock", False), bool), _("The wallpaper settings are not valid."))


def _folders(value: Any, _files: dict[str, Any]) -> None:
    folders = _object(value, _("The folder settings are not valid."))
    _require(valid_share(folders.get("share")),
             _("The shared folder is an address like smb://server/folder, without a password."))
    _require(isinstance(folders.get("tidy", False), bool), _("The folder settings are not valid."))


def _shares(value: Any, _files: dict[str, Any]) -> None:
    shares = _list(value, 20, _("At most 20 shared drives."))
    for share in shares:
        _require(isinstance(share, dict), _("The shared drives are not valid."))
        _require(_clean_text(share.get("name"), MAX_NAME, empty=False),
                 _("Each shared drive needs a name of at most 60 characters."))
        url = share.get("url")
        _require(valid_share(url) and "%" not in url,
                 _("A shared drive is an address like smb://server/folder, without %u and without a password."))
    _unique([share["url"] for share in shares], _("The same shared drive is listed twice."))


def _browser(value: Any, _files: dict[str, Any]) -> None:
    browser = _object(value, _("The browser settings are not valid."))
    homepage = browser.get("homepage")
    _require(homepage is None or valid_web_url(homepage), _("The home page is a web address that starts with "
                                                            "https:// or http://."))
    bookmarks = _list(browser.get("bookmarks", []), 50, _("At most 50 bookmarks."))
    for bookmark in bookmarks:
        _require(isinstance(bookmark, dict) and _clean_text(bookmark.get("name"), MAX_NAME, empty=False),
                 _("Each bookmark needs a name of at most 60 characters."))
        _require(valid_web_url(bookmark.get("url")), _("A bookmark's address is not a web address."))
    block = _list(browser.get("block", []), 500, _("At most 500 blocked websites."))
    for domain in block:
        _require(valid_domain(domain), _("“%s” is not a website name such as facebook.com.") % domain)
    _unique(block, _("A website is listed twice."))
    hours = browser.get("block_hours")
    if hours is not None:
        _object(hours, _("The blocking hours are not valid."))
        _require(_days(hours.get("days")), _("Choose at least one day."))
        ranges = hours.get("ranges")
        _require(isinstance(ranges, list) and 0 < len(ranges) <= 6, _("Give one to six time ranges."))
        for pair in ranges:
            _require(isinstance(pair, list) and len(pair) == 2 and all(valid_time(item) for item in pair),
                     _("Write times as HH:MM, such as 08:00."))
            _require(minutes_of(pair[0]) < minutes_of(pair[1]),
                     _("A time range ends after it starts, on the same day."))
    _require(isinstance(browser.get("safe_search", False), bool), _("The browser settings are not valid."))


def _printers(value: Any, _files: dict[str, Any]) -> None:
    printers = _list(value, 20, _("At most 20 printers."))
    defaults = 0
    for printer in printers:
        _require(isinstance(printer, dict), _("The printers are not valid."))
        _require(_clean_text(printer.get("name"), MAX_NAME, empty=False),
                 _("Each printer needs a name of at most 60 characters."))
        _require(valid_printer_uri(printer.get("uri")),
                 _("A printer's address starts with ipp:// or ipps://, such as ipp://192.168.1.50/ipp/print."))
        _require(_clean_text(printer.get("location", ""), MAX_NAME), _("A location is longer than 60 characters."))
        _require(isinstance(printer.get("default", False), bool), _("The printers are not valid."))
        defaults += printer.get("default") is True
    _require(defaults <= 1, _("Only one printer can be the default."))
    _unique([printer["name"] for printer in printers], _("Two printers have the same name."))


def _power(value: Any, _files: dict[str, Any]) -> None:
    power = _object(value, _("The power schedule is not valid."))
    shutdown = power.get("shutdown")
    if shutdown is not None:
        _object(shutdown, _("The power schedule is not valid."))
        _require(_days(shutdown.get("days")), _("Choose at least one day."))
        _require(valid_time(shutdown.get("time")), _("Write times as HH:MM, such as 08:00."))
        _require(_within(shutdown.get("warn_minutes", 10), 1, 30), _("The warning comes 1 to 30 minutes before."))
        _require(_within(shutdown.get("postpone_minutes", 30), 5, 120), _("A postponement is 5 to 120 minutes."))
        _require(_within(shutdown.get("max_postpones", 2), 0, 5), _("At most 5 postponements."))
        _require(shutdown.get("laptops", "skip") in LAPTOP_CHOICES, _("The power schedule is not valid."))
    wake = power.get("wake")
    if wake is not None:
        _object(wake, _("The power schedule is not valid."))
        _require(_days(wake.get("days")), _("Choose at least one day."))
        _require(valid_time(wake.get("time")), _("Write times as HH:MM, such as 08:00."))


def _apps(value: Any, _files: dict[str, Any]) -> None:
    apps = _object(value, _("The app settings are not valid."))
    lists = []
    for key in ("required", "forbidden"):
        ids = _list(apps.get(key, []), 50, _("At most 50 apps in each list."))
        _require(all(isinstance(item, str) and APP_ID.match(item) for item in ids), _("An app is not in the App "
                                                                                     "Center's list."))
        _unique(ids, _("An app is listed twice."))
        lists.append(set(ids))
    _require(not lists[0] & lists[1], _("An app cannot be both required and forbidden."))


def _usb(value: Any, _files: dict[str, Any]) -> None:
    _require(isinstance(value, dict) and value.get("storage") in USB_STORAGE, _("The USB setting is not valid."))


def _screen_lock(value: Any, _files: dict[str, Any]) -> None:
    lock = _object(value, _("The screen lock settings are not valid."))
    _require(_within(lock.get("idle_minutes"), 1, 120), _("The screen locks after 1 to 120 minutes."))
    _require(isinstance(lock.get("on_suspend", True), bool), _("The screen lock settings are not valid."))


def _firewall(value: Any, _files: dict[str, Any]) -> None:
    _require(isinstance(value, dict) and value.get("enabled") is True,
             _("The firewall can only be turned on by the company."))


def _inventory(value: Any, _files: dict[str, Any]) -> None:
    _require(isinstance(value, dict) and value.get("enabled") is True,
             _("The inventory is turned on with enabled: true; off is null."))


def _wifi(value: Any, _files: dict[str, Any]) -> None:
    networks = _list(value, 10, _("At most 10 Wi-Fi networks."))
    for network in networks:
        _require(isinstance(network, dict), _("The Wi-Fi networks are not valid."))
        ssid = network.get("ssid")
        _require(isinstance(ssid, str) and 1 <= len(ssid.encode("utf-8")) <= 32 and _clean_text(ssid, 32),
                 _("A Wi-Fi name has 1 to 32 bytes."))
        _require(network.get("security") in WIFI_SECURITY, _("The Wi-Fi networks are not valid."))
        _require(isinstance(network.get("hidden", False), bool), _("The Wi-Fi networks are not valid."))
    _unique([network["ssid"] for network in networks], _("The same Wi-Fi network is listed twice."))


def _shared(value: Any, _files: dict[str, Any]) -> None:
    shared = _object(value, _("The shared-machine settings are not valid."))
    for key in ("guest", "freeze", "low_memory_ok"):
        _require(isinstance(shared.get(key, False), bool), _("The shared-machine settings are not valid."))
    maintenance = shared.get("maintenance")
    if maintenance is not None:
        _object(maintenance, _("The maintenance time is not valid."))
        _require(_days(maintenance.get("days")), _("Choose the days of the maintenance time."))
        _require(valid_time(maintenance.get("time")), _("The maintenance time is not valid."))
        _require(_within(maintenance.get("max_minutes", 60), 15, 240),
                 _("Maintenance takes 15 to 240 minutes at most."))


def _snapshots(value: Any, _files: dict[str, Any]) -> None:
    snapshots = _object(value, _("The system snapshot settings are not valid."))
    _require(snapshots.get("schedule") in SNAPSHOT_SCHEDULES, _("The system snapshot settings are not valid."))
    _require(_within(snapshots.get("keep"), 1, 20), _("Keep 1 to 20 system snapshots."))
    _require(isinstance(snapshots.get("before_update", False), bool), _("The system snapshot settings are not valid."))


SECTION_CHECKS = {"wallpaper": _wallpaper, "folders": _folders, "shares": _shares, "browser": _browser,
                  "printers": _printers, "power": _power, "apps": _apps, "usb": _usb, "screen_lock": _screen_lock,
                  "firewall": _firewall, "inventory": _inventory, "wifi": _wifi, "shared": _shared,
                  "snapshots": _snapshots}


def validate_settings(settings: Any, files: dict[str, Any], scope: str = "company") -> None:
    """One layer of settings: each known section null or valid. Unknown sections are left for later versions."""

    if not isinstance(settings, dict):
        raise ProtocolError(_("The settings are not valid."), scope=scope)
    for section, check in SECTION_CHECKS.items():
        if section in settings and settings[section] is not None:
            try:
                check(settings[section], files)
            except ProtocolError as exc:
                raise ProtocolError(str(exc), section=section, scope=scope) from None


def validate_policy(policy: Any) -> None:
    """Raises ProtocolError unless the policy follows "Policy (format 2)" of PROTOCOL.md."""

    _require(isinstance(policy, dict), "the policy is not an object")
    _require(policy.get("format") == FORMAT, "unknown policy format")
    serial = policy.get("serial")
    _require(_int(serial) and serial >= 1, "serial must be ≥ 1")
    _require(_short_text(policy.get("issued", ""), 40), "bad issued time")
    _require(_short_text(policy.get("admin", ""), 64), "bad admin name")
    unb64(policy.get("admin_box_key"), 32)
    files = policy.get("files", {})
    _require(isinstance(files, dict), "files must be an object")
    for sha, info in files.items():
        _require(isinstance(sha, str) and SHA256.match(sha) is not None, f"bad sha256: {sha!r}")
        _require(isinstance(info, dict), "a file must be an object")
        size = info.get("size")
        _require(_int(size) and 0 < size <= MAX_FILE, "bad file size")
        _require(info.get("type") in FILE_TYPES, "bad file type")
    validate_settings(policy.get("settings", {}), files)
    departments = policy.get("departments", {})
    _require(isinstance(departments, dict) and len(departments) <= MAX_DEPARTMENTS, "at most 50 departments")
    for department_id, department in departments.items():
        _require(isinstance(department_id, str) and DEPARTMENT_ID.match(department_id) is not None,
                 f"bad department id: {department_id!r}")
        _require(isinstance(department, dict) and _clean_text(department.get("name"), MAX_NAME, empty=False),
                 "a department needs a name of at most 60 characters")
        validate_settings(department.get("settings", {}), files, f"department:{department_id}")
    members = policy.get("members", {})
    _require(isinstance(members, dict), "members must be an object")
    for machine_id, department_id in members.items():
        _require(isinstance(machine_id, str) and UUID.match(machine_id) is not None, "bad machine id")
        _require(department_id in departments, f"unknown department: {department_id!r}")
    machines = policy.get("machines", {})
    _require(isinstance(machines, dict), "machines must be an object")
    for machine_id, machine in machines.items():
        _require(isinstance(machine_id, str) and UUID.match(machine_id) is not None, "bad machine id")
        _require(isinstance(machine, dict), "a machine must be an object")
        validate_settings(machine.get("settings", {}), files, f"machine:{machine_id}")
        sealed = machine.get("sealed")
        _require(sealed is None or (isinstance(sealed, str) and len(sealed) <= 65536 and len(unb64(sealed)) >= 28),
                 "bad sealed secrets")


def layers(policy: dict[str, Any], machine_id: str) -> list[tuple[str, dict[str, Any]]]:
    """The settings layers that apply to a machine, in order: (scope, settings) for the company, its department
    and the machine itself."""

    found = [("company", policy.get("settings") or {})]
    department = (policy.get("members") or {}).get(machine_id)
    departments = policy.get("departments") or {}
    if department in departments:
        found.append((f"department:{department}", departments[department].get("settings") or {}))
    machine = (policy.get("machines") or {}).get(machine_id)
    if isinstance(machine, dict):
        found.append((f"machine:{machine_id}", machine.get("settings") or {}))
    return found


def effective_settings(policy: dict[str, Any], machine_id: str) -> dict[str, Any]:
    """A machine's settings: a section in a later layer replaces the whole section of an earlier one; null means
    off; a section in no layer is not managed (absent here)."""

    result: dict[str, Any] = {}
    for _scope, settings in layers(policy, machine_id):
        result.update(settings)
    return result


def setting_sources(policy: dict[str, Any], machine_id: str) -> dict[str, str]:
    """For each section of the effective settings, the scope it comes from."""

    sources: dict[str, str] = {}
    for scope, settings in layers(policy, machine_id):
        for section in settings:
            sources[section] = scope
    return sources


def wallpaper_for(settings: dict[str, Any], day: datetime.date) -> str | None:
    """The sha256 of the wallpaper for this day: the first period that holds it, else the default."""

    wallpaper = settings.get("wallpaper")
    if not wallpaper:
        return None
    today = (day.month, day.day)
    for period in wallpaper.get("periods", []):
        start = tuple(int(part) for part in period["from"].split("-"))
        end = tuple(int(part) for part in period["to"].split("-"))
        inside = start <= today <= end if start <= end else today >= start or today <= end
        if inside:
            return period["image"]
    return wallpaper.get("default")


def used_images(policy: dict[str, Any]) -> list[str]:
    """Every picture any layer's wallpaper uses, in order, once each."""

    found: list[str] = []
    all_layers = [policy.get("settings") or {}]
    all_layers += [(department or {}).get("settings") or {}
                   for department in (policy.get("departments") or {}).values()]
    all_layers += [(machine or {}).get("settings") or {} for machine in (policy.get("machines") or {}).values()]
    for settings in all_layers:
        wallpaper = settings.get("wallpaper") if isinstance(settings, dict) else None
        if not isinstance(wallpaper, dict):
            continue
        for sha in [wallpaper.get("default")] + [period.get("image") for period in wallpaper.get("periods", [])
                                                 if isinstance(period, dict)]:
            if isinstance(sha, str) and sha not in found:
                found.append(sha)
    return found


# -- commands (part 2, "Signed commands") ------------------------------------------------------------------------------

def _no_args(args: dict[str, Any]) -> None:
    _require(args == {}, "this action takes no arguments")


def _message_args(args: dict[str, Any]) -> None:
    _require(set(args) <= {"title", "body", "ack"}, "unknown arguments")
    _require(_clean_text(args.get("title"), 80, empty=False), "a title of 1 to 80 characters")
    _require(_clean_text(args.get("body", ""), 1000, newlines=True), "a body of at most 1000 characters")
    _require(isinstance(args.get("ack", False), bool), "ack must be true or false")


def _countdown_args(args: dict[str, Any]) -> None:
    _require(set(args) == {"warn_seconds"} and _within(args["warn_seconds"], 0, 900), "warn_seconds 0-900")


def _cancel_args(args: dict[str, Any]) -> None:
    _require(set(args) == {"id"} and isinstance(args["id"], str) and UUID.match(args["id"]) is not None,
             "the id of a command")


def valid_ipv4(value: Any) -> bool:
    try:
        return isinstance(value, str) and ipaddress.ip_address(value).version == 4
    except ValueError:
        return False


def _remote_help_args(args: dict[str, Any]) -> None:
    _require(set(args) in ({"admin_host", "port", "mode", "admin_name"}, {"admin_host", "port", "mode", "admin_name", "psk"}),
             "admin_host, port, mode, admin_name and psk")
    if "psk" in args:
        _require(isinstance(args["psk"], str) and len(args["psk"]) <= 1024 and len(unb64(args["psk"])) >= 28,
                 "psk is a sealed blob")
    _require(valid_ipv4(args["admin_host"]), "admin_host is an IPv4 address")
    _require(_within(args["port"], 1025, 65535), "a port from 1025 to 65535")
    _require(args["mode"] in ("view", "control"), "mode is view or control")
    _require(_clean_text(args["admin_name"], 64), "admin_name of at most 64 characters")


def _usb_unlock_args(args: dict[str, Any]) -> None:
    _require(set(args) == {"minutes"} and _within(args["minutes"], 1, 240), "minutes 1-240")


ACTIONS = {"sync": _no_args, "inventory": _no_args, "lock": _no_args, "message": _message_args,
           "logout": _countdown_args, "restart": _countdown_args, "shutdown": _countdown_args,
           "cancel": _cancel_args, "update": _no_args, "remote_help": _remote_help_args,
           "usb_unlock": _usb_unlock_args}


def parse_time(value: Any) -> datetime.datetime:
    """An ISO 8601 time with its offset."""

    _require(isinstance(value, str) and len(value) <= 40, "not a time")
    try:
        parsed = datetime.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ProtocolError("not an ISO 8601 time") from exc
    _require(parsed.tzinfo is not None, "a time without its offset")
    return parsed


def validate_targets(targets: Any) -> None:
    _require(isinstance(targets, dict) and len(targets) == 1, "targets has exactly one key")
    (kind, value), = targets.items()
    if kind == "all":
        _require(value is True, "all must be true")
    elif kind == "machines":
        _require(isinstance(value, list) and 0 < len(value) <= 1000
                 and all(isinstance(item, str) and UUID.match(item) for item in value), "bad machine ids")
    elif kind == "departments":
        _require(isinstance(value, list) and 0 < len(value) <= MAX_DEPARTMENTS
                 and all(isinstance(item, str) and DEPARTMENT_ID.match(item) for item in value), "bad departments")
    else:
        raise ProtocolError("targets is machines, departments or all")


def validate_command(command: Any) -> None:
    _require(isinstance(command, dict), "the command is not an object")
    _require(_int(command.get("seq")) and command["seq"] >= 1, "seq must be ≥ 1")
    _require(isinstance(command.get("id"), str) and UUID.match(command["id"]) is not None, "id is a uuid")
    validate_targets(command.get("targets"))
    action = command.get("action")
    _require(action in ACTIONS, f"unknown action: {action!r}")
    args = command.get("args")
    _require(isinstance(args, dict), "args must be an object")
    ACTIONS[action](args)
    parse_time(command.get("issued"))
    parse_time(command.get("expires"))


def sign_command(key: Ed25519PrivateKey, command: dict[str, Any]) -> dict[str, str]:
    """The envelope of a command the admin makes. Its lifetime is the admin's rule: expires comes after issued and
    at most 24 hours later (an agent checks only that expires has not passed, as the test vectors' 2099 shows)."""

    validate_command(command)
    issued, expires = parse_time(command["issued"]), parse_time(command["expires"])
    _require(issued < expires <= issued + MAX_COMMAND_LIFETIME, "expires at most 24 hours after issued")
    return _sign_text(key, command, "command")


def verify_command(envelope: Any, public: bytes) -> dict[str, Any]:
    text = verify_signed_text(envelope, public, "command")
    try:
        command = json.loads(text)
    except ValueError as exc:
        raise ProtocolError("the command is not JSON") from exc
    validate_command(command)
    return command


def targets_machine(command: dict[str, Any], machine_id: str, department: str | None) -> bool:
    targets = command.get("targets") or {}
    if targets.get("all") is True:
        return True
    if machine_id in (targets.get("machines") or []):
        return True
    return department is not None and department in (targets.get("departments") or [])


def check_command(envelope: Any, public: bytes, machine_id: str, department: str | None, last_seq: int,
                  now: datetime.datetime | None = None) -> dict[str, Any]:
    """The agent's checks of part 2, in order: signature and contents, targets, expiry, seq. Raises CommandRefused
    with the result state the agent reports."""

    try:
        command = verify_command(envelope, public)
    except ProtocolError as exc:
        raise CommandRefused(str(exc), "refused") from exc
    if not targets_machine(command, machine_id, department):
        raise CommandRefused("not for this machine", "ignored")
    if parse_time(command["expires"]) <= (now or datetime.datetime.now().astimezone()):
        raise CommandRefused("expired", "expired")
    if command["seq"] <= last_seq:
        raise CommandRefused("already run", "ignored")
    return command


# -- machines, check-ins, results, help, discovery ---------------------------------------------------------------------

def validate_machine(machine: Any) -> dict[str, str]:
    _require(isinstance(machine, dict), "machine must be an object")
    name, ip, mac = machine.get("name"), machine.get("ip"), machine.get("mac", "")
    _require(isinstance(name, str) and HOSTNAME.match(name) is not None, "bad machine name")
    _require(valid_ipv4(ip), "bad ip")
    _require(isinstance(mac, str) and (mac == "" or MAC.match(mac) is not None), "bad mac")
    _require(machine.get("edition") in EDITIONS, "bad edition")
    version = machine.get("version", "")
    _require(isinstance(version, str) and VERSION.match(version) is not None, "bad version")
    return {"name": name, "ip": ip, "mac": mac, "edition": machine["edition"], "version": version}


def validate_user_status(status: Any) -> dict[str, str]:
    _require(isinstance(status, dict), "a user status must be an object")
    user = status.get("user")
    _require(isinstance(user, str) and LOGIN.match(user) is not None, "bad user")
    _require(status.get("wallpaper") in WALLPAPER_STATES, "bad wallpaper state")
    _require(status.get("folders") in FOLDER_STATES, "bad folders state")
    _require(_short_text(status.get("detail", ""), MAX_DETAIL), "bad detail")
    _require(_short_text(status.get("time", ""), 40), "bad time")
    return {key: status.get(key, "") for key in ("user", "wallpaper", "folders", "detail", "time")}


def validate_register(body: Any) -> dict[str, Any]:
    """POST /register (part 3, enrolment by file): {"token_id", "time", "machine", "box_key", "proof"}. machine is kept
    as sent too, for the transcript."""

    _require(isinstance(body, dict), "not an object")
    _require(isinstance(body.get("token_id"), str) and TOKEN_ID.match(body["token_id"]) is not None, "bad token_id")
    _require(_int(body.get("time")), "bad time")
    sent = body.get("machine")
    machine = validate_machine(sent)
    box_key = unb64(body.get("box_key"), 32)
    unb64(body.get("proof"), 32)
    return {"token_id": body["token_id"], "time": body["time"], "machine": machine, "sent_machine": sent,
            "box_key": b64(box_key), "proof": body["proof"]}


# -- pairing with a code and enrolment by file (part 3) ----------------------------------------------------------------

PAIR_ID_EMPLOYEE = b"caramos-business employee"
PAIR_ID_ADMIN = b"caramos-business admin"
SPAKE2_MESSAGE = 33


def canonical(value: Any) -> bytes:
    """The bytes transcripts are made of: compact JSON with sorted keys, UTF-8."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def derive_3(ikm: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=HKDF_SALT_3, info=info).derive(ikm)


def hmac_b64(key: bytes, message: bytes) -> str:
    return b64(hmac.new(key, message, hashlib.sha256).digest())


def same_mac(key: bytes, message: bytes, given: Any) -> bool:
    try:
        raw = unb64(given)
    except ProtocolError:
        return False
    return hmac.compare_digest(raw, hmac.new(key, message, hashlib.sha256).digest())


def pair_keys(key: bytes) -> tuple[bytes, bytes]:
    """(k_employee, k_admin) from SPAKE2's key."""

    return derive_3(key, b"pair employee"), derive_3(key, b"pair admin")


def pair_transcript(session: str, msg_a: str, msg_b: str, admin_name: str, admin_key: str, admin_box_key: str,
                    machine_box_key: str, machine: Any) -> bytes:
    return canonical({"kind": "caramos-business/3 pair", "session": session, "msg_a": msg_a, "msg_b": msg_b,
                      "admin_name": admin_name, "admin_key": admin_key, "admin_box_key": admin_box_key,
                      "machine_box_key": machine_box_key, "machine": machine})


def answer_message(transcript: bytes, machine_id: str, state: str) -> bytes:
    """What the admin's confirmation covers: the transcript, the machine id and the state."""

    return transcript + b"\n" + machine_id.encode("ascii") + b"\n" + state.encode("ascii")


def enroll_proof_key(token: bytes) -> bytes:
    return derive_3(token, b"enroll")


def enroll_transcript(token_id: str, when: int, admin_key: str, machine_box_key: str, machine: Any) -> bytes:
    return canonical({"kind": "caramos-business/3 enroll", "token_id": token_id, "time": when,
                      "admin_key": admin_key, "machine_box_key": machine_box_key, "machine": machine})


def validate_pair_start(body: Any) -> bytes:
    """POST /pair/start: the employee's SPAKE2 message (33 bytes, side A)."""

    _require(isinstance(body, dict), "not an object")
    message = unb64(body.get("msg"), SPAKE2_MESSAGE)
    _require(message[:1] == b"A", "not an employee's message")
    return message


def validate_pair_finish(body: Any) -> dict[str, Any]:
    """POST /pair/finish: {"session", "machine", "box_key", "confirm"}; machine is kept as sent too."""

    _require(isinstance(body, dict), "not an object")
    _require(isinstance(body.get("session"), str) and UUID.match(body["session"]) is not None, "bad session")
    sent = body.get("machine")
    machine = validate_machine(sent)
    box_key = unb64(body.get("box_key"), 32)
    unb64(body.get("confirm"), 32)
    return {"session": body["session"], "machine": machine, "sent_machine": sent, "box_key": b64(box_key),
            "confirm": body["confirm"]}


def validate_enroll_file(data: Any, now: datetime.datetime | None = None) -> dict[str, Any]:
    """An enrolment file ("Enrolment file" of part 3): checked before anything is pinned from it."""

    _require(isinstance(data, dict), _("This is not an enrolment file."))
    _require(data.get("format") == 1 and data.get("kind") == "caramos-business-enroll",
             _("This is not an enrolment file."))
    url = data.get("admin_url")
    parsed = urllib.parse.urlsplit(url) if isinstance(url, str) else None
    _require(parsed is not None and parsed.scheme == "http" and valid_ipv4(parsed.hostname or "")
             and parsed.port is not None and parsed.path in ("", "/"), _("The file's admin address is not valid."))
    _require(_clean_text(data.get("admin_name"), 64, empty=False), _("This is not an enrolment file."))
    unb64(data.get("admin_key"), 32)
    unb64(data.get("admin_box_key"), 32)  # "Changes during implementation": the agent's first HMAC needs it
    _require(data.get("fingerprint") == fingerprint(unb64(data["admin_key"], 32)),
             _("The file's fingerprint does not match its key."))
    department = data.get("department")
    _require(department is None or (isinstance(department, str) and DEPARTMENT_ID.match(department) is not None),
             _("This is not an enrolment file."))
    _require(_clean_text(data.get("department_name") or "", MAX_NAME), _("This is not an enrolment file."))
    _require(isinstance(data.get("token_id"), str) and TOKEN_ID.match(data["token_id"]) is not None,
             _("This is not an enrolment file."))
    unb64(data.get("token"), 32)
    expires = parse_time(data.get("expires"))
    _require(expires > (now or datetime.datetime.now().astimezone()), _("This enrolment file has expired."))
    _require(_within(data.get("max_uses"), 1, 500), _("This is not an enrolment file."))
    prefix = data.get("hostname_prefix")
    _require(prefix is None or (isinstance(prefix, str) and HOSTNAME_PREFIX.match(prefix) is not None),
             _("This is not an enrolment file."))
    return data


# -- removal notices and ticket lists (part 3) -------------------------------------------------------------------------

def sign_notice(key: Ed25519PrivateKey, machine_id: str, admin_name: str, when: str) -> dict[str, str]:
    """The removal notice of "Gỡ khỏi công ty": {"notice": text, "signature"}."""

    return _sign_text(key, {"kind": "removed", "machine_id": machine_id, "admin": admin_name, "time": when}, "notice")


def verify_notice(signed: Any, public: bytes, machine_id: str) -> dict[str, Any]:
    text = verify_signed_text(signed, public, "notice")
    try:
        notice = json.loads(text)
    except ValueError as exc:
        raise ProtocolError("the notice is not JSON") from exc
    _require(isinstance(notice, dict) and notice.get("kind") == "removed", "not a removal notice")
    _require(notice.get("machine_id") == machine_id, "a notice for another machine")
    return notice


def sign_tickets(key: Ed25519PrivateKey, value: dict[str, Any]) -> dict[str, str]:
    """GET /tickets' answer: {"tickets": text, "signature"}."""

    return _sign_text(key, value, "tickets")


def verify_tickets(signed: Any, public: bytes, machine_id: str) -> dict[str, Any]:
    text = verify_signed_text(signed, public, "tickets")
    try:
        value = json.loads(text)
    except ValueError as exc:
        raise ProtocolError("the ticket list is not JSON") from exc
    _require(isinstance(value, dict) and value.get("kind") == "tickets", "not a ticket list")
    _require(value.get("machine_id") == machine_id, "a ticket list for another machine")
    _require(_int(value.get("version")) and isinstance(value.get("tickets"), list), "bad ticket list")
    return value


# Health (part 2, "Inventory and health"): numbers may be null where the agent could not tell.
HEALTH_ENUMS = {"disk_health": ("ok", "failing", "unknown"), "firewall": ("on", "off", "unknown")}


def validate_health(health: Any) -> dict[str, Any]:
    _require(isinstance(health, dict), "health must be an object")
    result: dict[str, Any] = {}
    for key, low, high in (("disk_free_pct", 0, 100), ("battery_health_pct", 0, 200), ("uptime_hours", 0, 10 ** 6)):
        value = health.get(key)
        _require(value is None or (_number(value) and low <= value <= high), f"bad {key}")
        result[key] = value
    for key, values in HEALTH_ENUMS.items():
        value = health.get(key, "unknown")
        _require(value in values, f"bad {key}")
        result[key] = value
    updates = health.get("updates") or {}
    _require(isinstance(updates, dict), "bad updates")
    result["updates"] = {}
    for key in ("security", "other"):
        value = updates.get(key, 0)
        _require(_int(value) and 0 <= value <= 100000, f"bad updates.{key}")
        result["updates"][key] = value
    _require(isinstance(health.get("reboot_required", False), bool), "bad reboot_required")
    result["reboot_required"] = health.get("reboot_required", False)
    version = health.get("caramos_version", "")
    _require(isinstance(version, str) and VERSION.match(version) is not None, "bad caramos_version")
    result["caramos_version"] = version
    applied = health.get("applied") or {}
    _require(isinstance(applied, dict) and len(applied) <= 32, "bad applied")
    for section, state in applied.items():
        _require(isinstance(section, str) and SECTION_KEY.match(section) is not None, "bad applied section")
        _require(_clean_text(state, MAX_DETAIL) and (state == "ok" or state.startswith("failed")),
                 "applied is ok or failed: <reason>")
    result["applied"] = dict(applied)
    # Part 3 ("Security report"): absent keys mean the agent does not report them (0.2).
    memory = health.get("memory_mb")
    _require(memory is None or (_int(memory) and 0 <= memory <= 10 ** 8), "bad memory_mb")
    result["memory_mb"] = memory
    result["encryption"] = health.get("encryption", "unknown")
    _require(result["encryption"] in ENCRYPTION, "bad encryption")
    lock_on = health.get("screen_lock_on")
    _require(lock_on is None or isinstance(lock_on, bool), "bad screen_lock_on")
    result["screen_lock_on"] = lock_on
    usb = health.get("usb_storage")
    _require(usb is None or usb in USB_STATES, "bad usb_storage")
    result["usb_storage"] = usb
    for key in ("frozen", "freeze_configured"):
        _require(isinstance(health.get(key, False), bool), f"bad {key}")
        result[key] = health.get(key, False)
    for key in ("last_maintenance", "last_snapshot"):
        value = health.get(key)
        _require(value is None or _short_text(value, 40), f"bad {key}")
        result[key] = value
    _require(_clean_text(health.get("maintenance_result", ""), MAX_DETAIL), "bad maintenance_result")
    result["maintenance_result"] = health.get("maintenance_result", "")
    space = health.get("snapshot_space_mb")
    _require(space is None or (_int(space) and 0 <= space <= 10 ** 9), "bad snapshot_space_mb")
    result["snapshot_space_mb"] = space
    return result


def validate_capabilities(capabilities: Any) -> list[str]:
    _require(isinstance(capabilities, list) and len(capabilities) <= 64, "bad capabilities")
    _require(all(isinstance(item, str) and CAPABILITY.match(item) for item in capabilities), "bad capabilities")
    return list(dict.fromkeys(capabilities))


def validate_checkin(body: Any) -> dict[str, Any]:
    """POST /checkin: part 1's body without the token, plus health and capabilities (kept when absent)."""

    _require(isinstance(body, dict), "not an object")
    machine = validate_machine(body.get("machine"))
    serial = body.get("policy_serial")
    _require(serial is None or _int(serial), "bad policy_serial")
    users = body.get("users", [])
    _require(isinstance(users, list) and len(users) <= 50, "bad users")
    result: dict[str, Any] = {"machine": machine, "policy_serial": serial,
                              "users": [validate_user_status(user) for user in users]}
    machine_id = body.get("machine_id")
    _require(machine_id is None or (isinstance(machine_id, str) and UUID.match(machine_id)), "bad machine_id")
    result["machine_id"] = machine_id
    if body.get("health") is not None:
        result["health"] = validate_health(body["health"])
    if body.get("capabilities") is not None:
        result["capabilities"] = validate_capabilities(body["capabilities"])
    return result


def validate_result(body: Any) -> dict[str, Any]:
    """POST /result: {"id", "state", "detail", "time"}."""

    _require(isinstance(body, dict), "not an object")
    _require(isinstance(body.get("id"), str) and UUID.match(body["id"]) is not None, "id is a uuid")
    _require(body.get("state") in RESULT_STATES, "bad state")
    _require(_clean_text(body.get("detail", ""), 300, newlines=True), "detail of at most 300 characters")
    _require(_short_text(body.get("time", ""), 40), "bad time")
    return {"id": body["id"], "state": body["state"], "detail": body.get("detail", ""), "time": body.get("time", "")}


def validate_help(body: Any) -> dict[str, Any]:
    """POST /help: {"user", "note", "time"}."""

    _require(isinstance(body, dict), "not an object")
    user = body.get("user", "")
    _require(isinstance(user, str) and (user == "" or LOGIN.match(user) is not None), "bad user")
    _require(_clean_text(body.get("note", ""), 300, newlines=True), "note of at most 300 characters")
    _require(_short_text(body.get("time", ""), 40), "bad time")
    return {"user": user, "note": body.get("note", ""), "time": body.get("time", "")}


# Inventory: a schema per key. Strings are at most 200 characters, lists at most 500 items (PROTOCOL.md); numbers may
# be null when the agent could not read them. Unknown keys are dropped.
STR, INT, NUM, BOOL = "str", "int", "num", "bool"
INVENTORY_SCHEMA: dict[str, Any] = {
    "collected": STR,
    "hash": STR,
    "system": {"vendor": STR, "product": STR, "serial": STR, "bios": STR,
               "chassis": ("desktop", "laptop", "other"), "boot_time": STR},
    "cpu": {"model": STR, "cores": INT, "threads": INT},
    "memory": {"total_mb": INT, "modules": [{"size_mb": INT, "type": STR, "speed_mts": INT, "slot": STR}]},
    "disks": [{"name": STR, "model": STR, "serial": STR, "size_gb": NUM, "rotational": BOOL, "transport": STR,
               "health": ("ok", "failing", "unknown")}],
    "batteries": [{"name": STR, "design_wh": NUM, "full_wh": NUM, "health_pct": NUM, "cycles": INT}],
    "monitors": [{"connector": STR, "name": STR, "serial": STR}],
    "network": [{"name": STR, "mac": STR, "ipv4": STR, "wired": BOOL}],
    "os": {"caramos": STR, "edition": ("cinnamon", "xfce", "other"), "kernel": STR},
    "apps": [{"id": STR, "name": STR, "version": STR, "source": ("deb", "flatpak"), "package": STR, "licence": STR,
              "origin": STR}],
}


def _conform(value: Any, schema: Any, where: str) -> Any:
    if isinstance(schema, dict):
        if value is None:
            value = {}
        _require(isinstance(value, dict), f"{where} must be an object")
        return {key: _conform(value.get(key), inner, f"{where}.{key}") for key, inner in schema.items()}
    if isinstance(schema, list):
        if value is None:
            return []
        _require(isinstance(value, list) and len(value) <= 500, f"{where} must be a list of at most 500 items")
        return [_conform(item, schema[0], f"{where}[]") for item in value]
    if isinstance(schema, tuple):
        if value is None:
            return None
        _require(value in schema, f"{where} is one of {', '.join(schema)}")
        return value
    if value is None:
        return "" if schema == STR else None
    if schema == STR:
        _require(isinstance(value, str) and len(value) <= 200, f"{where} must be a text of at most 200 characters")
    elif schema == INT:
        _require(_int(value), f"{where} must be a whole number")
    elif schema == NUM:
        _require(_number(value), f"{where} must be a number")
    elif schema == BOOL:
        _require(isinstance(value, bool), f"{where} must be true or false")
    return value


def validate_inventory(inventory: Any) -> dict[str, Any]:
    """POST /inventory's body, keeping only what PROTOCOL.md lists."""

    _require(isinstance(inventory, dict), "the inventory is not an object")
    result = _conform(inventory, INVENTORY_SCHEMA, "inventory")
    _require(result["hash"] == "" or SHA256.match(result["hash"]) is not None, "hash is a sha256")
    return result


def here_datagram(name: str, public: bytes, pairing: bool) -> bytes:
    body = json.dumps({"name": name, "port": HTTP_PORT, "fingerprint": fingerprint(public), "pairing": pairing},
                      ensure_ascii=False)
    return (HERE + body).encode("utf-8")


def parse_here(data: bytes) -> dict[str, Any] | None:
    """An admin's answer to discovery, or None for anything else."""

    if len(data) > MAX_DATAGRAM:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text.startswith(HERE):
        return None
    try:
        answer = json.loads(text[len(HERE):])
    except ValueError:
        return None
    if not isinstance(answer, dict):
        return None
    name, port, print_, pairing = (answer.get("name"), answer.get("port"), answer.get("fingerprint"),
                                   answer.get("pairing"))
    if not (_short_text(name, 64) and isinstance(port, int) and 0 < port < 65536 and isinstance(print_, str)
            and re.fullmatch(r"[0-9a-f]{16}", print_) and isinstance(pairing, bool)):
        return None
    return {"name": name, "port": port, "fingerprint": print_, "pairing": pairing}

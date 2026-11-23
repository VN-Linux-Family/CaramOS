"""Pairing with a code (SPAKE2) and enrolment by file (PROTOCOL.md part 3): the admin's pairing window, its SPAKE2
sessions and enrolment tokens, and the employee's side of both exchanges.

The code is random for each pairing window, and never travels: python3-spake2 turns it into a key on both sides, and
each side proves it holds the same key with an HMAC over a transcript of what was exchanged. The employee confirms
first, so that every guess costs a failure the admin counts."""

from __future__ import annotations

import datetime
import grp
import json
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

from . import protocol
from .i18n import _
from .store import read_json, write_json

TOKENS = "enroll-tokens.json"     # root:sudo 0640: the tokens' public details and use counts
KEYS = "enroll-keys.json"         # 0600: {token_id: hex of the proof key}
MAX_FAILURES = 20                 # failed confirmations in one pairing window, or failed proofs of one token
SESSION_SECONDS = 60
MAX_SESSIONS = 16
SESSIONS_PER_IP = 2
CLOCK_WINDOW = 600                # an enrolment request's time may be this far off
REPLAY_SECONDS = 20 * 60
MAX_TOKEN_DAYS = 30
MAX_TOKEN_USES = 500


class PairingError(Exception):
    """A pairing or enrolment that did not work, with a sentence for the user."""


class Unreachable(PairingError):
    """The admin machine did not answer at all."""


class TokenRefused(PairingError):
    """The enrolment file's token is expired, used up or withdrawn: trying again does not help."""


class PairingBusy(protocol.ProtocolError):
    """Too many pairing sessions at once (429)."""


def spake2_module() -> Any:
    try:
        import spake2  # noqa: PLC0415 - python3-spake2 is needed only for pairing
    except ImportError as exc:  # pragma: no cover - a Depends of the package
        raise PairingError(_("python3-spake2 is missing: install it to pair machines.")) from exc
    return spake2


def now_iso(now: datetime.datetime | None = None) -> str:
    return (now or datetime.datetime.now().astimezone()).isoformat(timespec="seconds")


# -- the pairing window (admin) ----------------------------------------------------------------------------------------

def _readable_by_admins(path: Path) -> None:
    """root:sudo 0640, as the admin state folder: the window shows the code again after a restart."""

    try:
        group = grp.getgrnam("sudo").gr_gid
    except KeyError:
        os.chmod(path, 0o644)
        return
    if os.geteuid() == 0:
        os.chown(path, 0, group)
    os.chmod(path, 0o640)


def open_pairing(path: Path, seconds: int = protocol.PAIRING_SECONDS, now: float | None = None) -> dict[str, Any]:
    """A new pairing window with a new random code: {"code", "until"}."""

    window = {"code": f"{secrets.randbelow(1_000_000):06d}", "until": int((now or time.time()) + seconds)}
    write_json(path, window, mode=0o640)
    _readable_by_admins(path)
    return window


def read_pairing(path: Path, now: float | None = None) -> dict[str, Any] | None:
    """The open pairing window, or None (closed, or its time ran out)."""

    window = read_json(path)
    if not (isinstance(window, dict) and isinstance(window.get("code"), str) and isinstance(window.get("until"), int)):
        return None
    if window["until"] <= (now or time.time()) or len(window["code"]) != 6 or not window["code"].isdigit():
        return None
    return window


def close_pairing(path: Path) -> None:
    path.unlink(missing_ok=True)


class Sessions:
    """The admin's SPAKE2 sessions of the open pairing window: at most MAX_SESSIONS, SESSIONS_PER_IP per address,
    each SESSION_SECONDS; and the failed confirmations of the window."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.items: dict[str, dict[str, Any]] = {}
        self.failures = 0

    def _prune(self, now: float) -> None:
        self.items = {key: value for key, value in self.items.items() if now - value["started"] < SESSION_SECONDS}

    def start(self, code: str, msg_a: bytes, ip: str, now: float | None = None) -> tuple[str, bytes, bytes]:
        """(session, msg_b, key) for an employee's first message; raises PairingBusy or ProtocolError."""

        now = time.time() if now is None else now
        with self.lock:
            self._prune(now)
            if len(self.items) >= MAX_SESSIONS or sum(1 for item in self.items.values() if item["ip"] == ip) >= \
                    SESSIONS_PER_IP:
                raise PairingBusy("too many pairing sessions")
        spake2 = spake2_module()
        side = spake2.SPAKE2_B(code.encode("ascii"), idA=protocol.PAIR_ID_EMPLOYEE, idB=protocol.PAIR_ID_ADMIN)
        msg_b = side.start()
        try:
            key = side.finish(msg_a)
        except Exception as exc:  # noqa: BLE001 - spake2 raises its own errors for a bad message
            raise protocol.ProtocolError(f"not a SPAKE2 message: {exc}") from exc
        session = str(uuid.uuid4())
        with self.lock:
            self.items[session] = {"key": key, "msg_a": protocol.b64(msg_a), "msg_b": protocol.b64(msg_b),
                                   "started": now, "ip": ip}
        return session, msg_b, key

    def take(self, session: str, now: float | None = None) -> dict[str, Any] | None:
        with self.lock:
            self._prune(time.time() if now is None else now)
            return self.items.pop(session, None)

    def failed(self) -> int:
        """Counts a failed confirmation; the count so far."""

        with self.lock:
            self.failures += 1
            return self.failures

    def reset(self) -> None:
        with self.lock:
            self.items.clear()
            self.failures = 0


# -- enrolment tokens (admin) ------------------------------------------------------------------------------------------

def read_tokens(state: Path) -> dict[str, Any]:
    tokens = read_json(state / TOKENS, {})
    return tokens if isinstance(tokens, dict) else {}


def read_keys(state: Path) -> dict[str, str]:
    keys = read_json(state / KEYS, {})
    return keys if isinstance(keys, dict) else {}


def validate_token_options(options: Any, departments: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(options, dict):
        raise protocol.ProtocolError(_("The enrolment file options could not be read."))
    department = options.get("department")
    if department is not None and department not in departments:
        raise protocol.ProtocolError(_("That department does not exist."))
    days, uses = options.get("days", 7), options.get("max_uses", 30)
    if not (protocol._int(days) and 1 <= days <= MAX_TOKEN_DAYS):  # noqa: SLF001 - the same rule
        raise protocol.ProtocolError(_("An enrolment file lasts 1 to 30 days."))
    if not (protocol._int(uses) and 1 <= uses <= MAX_TOKEN_USES):  # noqa: SLF001
        raise protocol.ProtocolError(_("An enrolment file adds 1 to 500 machines."))
    prefix = options.get("hostname_prefix") or None
    if prefix is not None and not (isinstance(prefix, str) and protocol.HOSTNAME_PREFIX.match(prefix)):
        raise protocol.ProtocolError(_("A name prefix has up to 20 lower-case letters, digits or hyphens."))
    return {"department": department, "days": days, "max_uses": uses, "hostname_prefix": prefix}


def create_token(state: Path, options: dict[str, Any], *, admin_url: str, admin_name: str, admin_key: str,
                 admin_box_key: str, department_name: str, by: str,
                 now: datetime.datetime | None = None) -> dict[str, Any]:
    """Makes a token and returns the enrolment file's contents. Keeps the public details in enroll-tokens.json and the
    proof key in enroll-keys.json (0600); never the token. Call it with locked(state)."""

    now = now or datetime.datetime.now().astimezone()
    token, token_id = secrets.token_bytes(32), secrets.token_hex(8)
    expires = now_iso(now + datetime.timedelta(days=options["days"]))
    tokens, keys = read_tokens(state), read_keys(state)
    tokens[token_id] = {"created": now_iso(now), "by": by, "department": options["department"], "expires": expires,
                        "max_uses": options["max_uses"], "uses": 0, "revoked": None, "failures": 0, "machines": [],
                        "hostname_prefix": options["hostname_prefix"]}
    keys[token_id] = protocol.enroll_proof_key(token).hex()
    write_json(state / KEYS, keys, mode=0o600)
    write_json(state / TOKENS, tokens)
    return {"format": 1, "kind": "caramos-business-enroll", "admin_url": admin_url, "admin_name": admin_name,
            "admin_key": admin_key, "admin_box_key": admin_box_key,
            "fingerprint": protocol.fingerprint(protocol.unb64(admin_key, 32)),
            "department": options["department"], "department_name": department_name if options["department"] else "",
            "token_id": token_id, "token": protocol.b64(token), "expires": expires, "max_uses": options["max_uses"],
            "hostname_prefix": options["hostname_prefix"]}


def revoke_token(state: Path, token_id: str, now: datetime.datetime | None = None) -> bool:
    """Call it with locked(state)."""

    tokens = read_tokens(state)
    record = tokens.get(token_id)
    if not isinstance(record, dict) or record.get("revoked"):
        return False
    record["revoked"] = now_iso(now)
    write_json(state / TOKENS, tokens)
    keys = read_keys(state)
    if keys.pop(token_id, None) is not None:
        write_json(state / KEYS, keys, mode=0o600)
    return True


def token_usable(record: Any, now: datetime.datetime) -> bool:
    if not isinstance(record, dict) or record.get("revoked"):
        return False
    try:
        expires = datetime.datetime.fromisoformat(record.get("expires", ""))
    except (TypeError, ValueError):
        return False
    return expires > now and record.get("uses", 0) < record.get("max_uses", 0)


class Replays:
    """Proofs seen lately: a sniffed request sent again is refused (and not counted)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.seen: dict[str, float] = {}

    def check(self, proof: str, now: float | None = None) -> bool:
        """Whether the proof is new; it is remembered for REPLAY_SECONDS."""

        now = time.time() if now is None else now
        with self.lock:
            self.seen = {key: value for key, value in self.seen.items() if now - value < REPLAY_SECONDS}
            if proof in self.seen:
                return False
            self.seen[proof] = now
            return True


def check_enrolment(state: Path, request: dict[str, Any], admin_key: str, now: datetime.datetime,
                    replays: Replays) -> tuple[str, dict[str, Any] | None, bytes | None]:
    """("ok", token record, proof key) or ("token" or "proof" or "replay", None, None). A wrong proof is counted;
    MAX_FAILURES of them revoke the token. "ok" takes one use of the token at once, so that two machines enrolling
    at the same moment cannot pass its number of uses. Call it with locked(state)."""

    tokens, keys = read_tokens(state), read_keys(state)
    token_id = request["token_id"]
    record, key_hex = tokens.get(token_id), keys.get(token_id)
    if not token_usable(record, now) or not isinstance(key_hex, str):
        return "token", None, None
    proof_key = bytes.fromhex(key_hex)
    if abs(now.timestamp() - request["time"]) > CLOCK_WINDOW:
        return "proof", None, None
    message = protocol.enroll_transcript(token_id, request["time"], admin_key, request["box_key"],
                                         request["sent_machine"])
    if not protocol.same_mac(proof_key, message, request["proof"]):
        record["failures"] = record.get("failures", 0) + 1
        if record["failures"] >= MAX_FAILURES:
            record["revoked"] = now_iso(now)
        write_json(state / TOKENS, tokens)
        return "proof", None, None
    if not replays.check(request["proof"], now.timestamp()):
        return "replay", None, None
    record["uses"] = record.get("uses", 0) + 1
    write_json(state / TOKENS, tokens)
    return "ok", record, proof_key


def add_machine(state: Path, token_id: str, machine_id: str) -> None:
    """The machine a use of the token added. Call it with locked(state)."""

    tokens = read_tokens(state)
    record = tokens.get(token_id)
    if isinstance(record, dict):
        record["machines"] = [*record.get("machines", []), machine_id][-MAX_TOKEN_USES:]
        write_json(state / TOKENS, tokens)


# -- the employee's side -----------------------------------------------------------------------------------------------

Post = Callable[[str, dict[str, Any]], tuple[int, Any]]


def post_json(url: str, body: dict[str, Any], timeout: float = 15.0) -> tuple[int, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - http on the LAN, by design
            return response.status, json.loads(response.read(protocol.MAX_BODY).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read(protocol.MAX_BODY).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return exc.code, None
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        raise Unreachable(_("The admin machine does not answer. Is it on, and on the same network?")) from exc


def _error_of(answer: Any) -> str:
    return answer.get("error", "") if isinstance(answer, dict) else ""


def pair_with_code(url: str, code: str, machine: dict[str, Any], box_key: str, post: Post = post_json,
                   entropy: Callable[[int], bytes] | None = None) -> dict[str, Any]:
    """The employee's side of "Pairing with a code": {"admin_name", "admin_key", "admin_box_key", "machine_id",
    "state"} once the admin's confirmation checked out. box_key is the machine's public box key (base64)."""

    spake2 = spake2_module()
    extra = {"entropy_f": entropy} if entropy else {}
    side = spake2.SPAKE2_A(code.encode("ascii"), idA=protocol.PAIR_ID_EMPLOYEE, idB=protocol.PAIR_ID_ADMIN, **extra)
    msg_a = protocol.b64(side.start())
    status, answer = post(f"{url}{protocol.PREFIX}/pair/start", {"msg": msg_a})
    if status == 403:
        raise PairingError(_("The admin machine is not adding machines now."))
    if status == 429:
        raise PairingError(_("The admin machine is busy pairing other machines: try again in a minute."))
    if status != 200 or not isinstance(answer, dict):
        raise PairingError(_("The admin machine did not answer as expected."))
    try:
        session = answer["session"]
        protocol.unb64(answer["admin_key"], 32)
        protocol.unb64(answer["admin_box_key"], 32)
        msg_b = protocol.unb64(answer["msg"], protocol.SPAKE2_MESSAGE)
        admin_name = answer["admin_name"]
        if not (isinstance(session, str) and protocol.UUID.match(session) and isinstance(admin_name, str)):
            raise protocol.ProtocolError("bad answer")
        key = side.finish(msg_b)
    except Exception as exc:  # noqa: BLE001 - KeyError, ProtocolError and spake2's own errors
        raise PairingError(_("The admin machine did not answer as expected.")) from exc
    k_employee, k_admin = protocol.pair_keys(key)
    transcript = protocol.pair_transcript(session, msg_a, answer["msg"], admin_name, answer["admin_key"],
                                          answer["admin_box_key"], box_key, machine)
    status, finish = post(f"{url}{protocol.PREFIX}/pair/finish",
                          {"session": session, "machine": machine, "box_key": box_key,
                           "confirm": protocol.hmac_b64(k_employee, transcript)})
    if status == 403 and _error_of(finish) == "wrong code":
        raise PairingError(_("The code is not right."))
    if status == 403:
        raise PairingError(_("The pairing took too long: try again."))
    if status != 200 or not isinstance(finish, dict):
        raise PairingError(_("The admin machine did not answer as expected."))
    machine_id, state = finish.get("machine_id"), finish.get("state")
    if not (isinstance(machine_id, str) and protocol.UUID.match(machine_id) and state in ("approved", "pending")
            and protocol.same_mac(k_admin, protocol.answer_message(transcript, machine_id, state),
                                  finish.get("confirm"))):
        raise PairingError(_("The admin machine's answer does not match the code. Check the admin machine and the "
                             "code."))
    return {"admin_name": admin_name, "admin_key": answer["admin_key"], "admin_box_key": answer["admin_box_key"],
            "machine_id": machine_id, "state": state}


def enroll_with_file(data: dict[str, Any], machine: dict[str, Any], box_key: str, url: str, post: Post = post_json,
                     now: float | None = None) -> dict[str, Any]:
    """The employee's side of "Enrolment file": {"admin_name", "admin_key", "admin_box_key", "machine_id", "state"}
    once the admin's confirmation (made with the token's proof key) checked out."""

    token = protocol.unb64(data["token"], 32)
    proof_key = protocol.enroll_proof_key(token)
    when = int(time.time() if now is None else now)
    transcript = protocol.enroll_transcript(data["token_id"], when, data["admin_key"], box_key, machine)
    status, answer = post(f"{url}{protocol.PREFIX}/register",
                          {"token_id": data["token_id"], "time": when, "machine": machine, "box_key": box_key,
                           "proof": protocol.hmac_b64(proof_key, transcript)})
    if status == 403 and _error_of(answer) == "token":
        raise TokenRefused(_("This enrolment file has expired, has been used up, or was withdrawn: pair this machine "
                             "with a code."))
    if status == 403:
        raise PairingError(_("The admin machine did not accept this enrolment file. Check the date and time of this "
                             "machine."))
    if status != 200 or not isinstance(answer, dict):
        raise PairingError(_("The admin machine did not answer as expected."))
    machine_id, state = answer.get("machine_id"), answer.get("state")
    if not (isinstance(machine_id, str) and protocol.UUID.match(machine_id) and state in ("approved", "pending")
            and protocol.same_mac(proof_key, protocol.answer_message(transcript, machine_id, state),
                                  answer.get("confirm"))):
        raise PairingError(_("The answer did not come from the admin machine that made this file."))
    return {"admin_name": data["admin_name"], "admin_key": data["admin_key"], "admin_box_key": data["admin_box_key"],
            "machine_id": machine_id, "state": state}

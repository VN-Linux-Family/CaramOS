"""caramos-business-server: the admin machine's side of the network (PROTOCOL.md, parts 1 to 3). A systemd service,
root: it reads the keys and writes the state the window shows.

UDP 47021 answers discovery. HTTP 47022 pairs machines with a code (SPAKE2) while pairing is open, enrols machines
with a token from an enrolment file, and serves the authenticated requests of paired, approved machines: the signed
policy and its files, check-ins with health, inventories, the long-poll /wait for commands and new policies, results,
help requests (which become tickets) and the machine's signed ticket list. A removed machine gets its signed removal
notice. A thread sends Wake-on-LAN packets at the wake and maintenance times of the policy. Everything that comes in
is checked before it is stored."""

from __future__ import annotations

import datetime
import json
import logging
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import ADMIN_BOX_KEY, ADMIN_KEY, ADMIN_STATE, PAIRING, VIEWER_PORT, admin, health, pairing, protocol, tickets
from .i18n import _
from .store import locked, read_json, write_json

LOG = logging.getLogger("caramos-business-server")
FILE_PATH = re.compile(rf"^{protocol.PREFIX}/files/([0-9a-f]{{64}})$")
# Failed confirmations before pairing closes by itself: a machine on the LAN cannot try the million codes.
MAX_WRONG_CODES = pairing.MAX_FAILURES
WATCH_SECONDS = 0.5
WAKE_CHECK_SECONDS = 20
MAINTENANCE_WAKE_MINUTES = 5
POSTS = ("/checkin", "/inventory", "/result", "/help")
REMOTE_HELP_RULE = "caramos-business-remote-help"
# How far ahead of this admin's policy a machine's serial may be for the admin to catch up (after a restore).
MAX_CATCH_UP = 10000


class Snapshot:
    """What /wait needs, re-read when the helper or a handler rewrites the files: the signed policy's serial and
    contents, the commands with their envelopes, which machines answered which command, and each machine's tickets
    version."""

    def __init__(self, state: Path) -> None:
        self.state = state
        self.lock = threading.Lock()
        self.stamp: tuple[int | None, ...] | None = None
        self.serial = 0
        self.policy: dict[str, Any] = {}
        self.commands: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.answered: dict[str, set[str]] = {}
        self.ticket_versions: dict[str, int] = {}

    def _stamp(self) -> tuple[int | None, ...]:
        stamps = []
        for name in (admin.SIGNED, admin.COMMANDS, admin.RESULTS, tickets.TICKETS):
            try:
                stamps.append((self.state / name).stat().st_mtime_ns)
            except OSError:
                stamps.append(None)
        return tuple(stamps)

    def refresh(self) -> bool:
        """Re-reads what changed; whether anything did."""

        with self.lock:
            return self._refresh()

    def _refresh(self) -> bool:
        stamp = self._stamp()
        if stamp == self.stamp:
            return False
        signed = read_json(self.state / admin.SIGNED)
        try:
            policy = json.loads(signed["policy"]) if isinstance(signed, dict) else {}
        except (KeyError, TypeError, ValueError):
            policy = {}
        commands = []
        for envelope in admin.read_commands(self.state)["commands"]:
            command = admin.command_of(envelope)
            if command is not None and isinstance(command.get("seq"), int):
                commands.append((command, envelope))
        commands.sort(key=lambda item: item[0]["seq"])
        self.policy, self.serial = policy, int(policy.get("serial", 0)) if isinstance(policy, dict) else 0
        self.answered = {command_id: set(per_machine) for command_id, per_machine in admin.read_results(self.state).items()
                         if isinstance(per_machine, dict)}
        store = tickets.read(self.state)
        self.ticket_versions = {machine_id: tickets.version(store, machine_id) for machine_id in store["versions"]}
        self.commands, self.stamp = commands, stamp
        return True

    def ticket_version(self, machine_id: str) -> int:
        with self.lock:
            return self.ticket_versions.get(machine_id, 0)

    def for_machine(self, machine_id: str, after: int, paired: str = "") -> list[dict[str, Any]]:
        """The envelopes of the commands for a machine with a seq above after, oldest first, at most 50; not those
        issued before it paired (a message to all from this morning is not for a machine added this afternoon), nor
        those it already answered (a frozen machine's command record goes back to the disk's copy at each reboot)."""

        department = (self.policy.get("members") or {}).get(machine_id)
        since = admin.parse_iso(paired)
        found = []
        for command, envelope in self.commands:
            if command["seq"] <= after or not protocol.targets_machine(command, machine_id, department):
                continue
            if machine_id in self.answered.get(command.get("id", ""), set()):
                continue
            issued = admin.parse_iso(command.get("issued"))
            if since and issued and issued < since:
                continue
            found.append(envelope)
        return found[:protocol.MAX_WAIT_COMMANDS]

    def command_ids(self) -> set[str]:
        return {command.get("id") for command, _envelope in self.commands}


class Admin:
    """What the handlers share: the keys, the state folder, the cached snapshot and the machines' MAC keys."""

    def __init__(self, key: Any, name: str, state: Path = ADMIN_STATE, pairing_file: Path = PAIRING,
                 box_path: Path = ADMIN_BOX_KEY) -> None:
        self.key = key
        self.public = protocol.public_bytes(key)
        self.public_b64 = protocol.b64(self.public)
        self.name = name
        self.state = state
        self.pairing = pairing_file
        self.box_path = box_path
        self.lock = threading.Lock()
        self.changed = threading.Condition()
        self.sessions = pairing.Sessions()
        self.window_code: str | None = None
        self.replays = pairing.Replays()
        self.ticket_lists: dict[str, tuple[int, dict[str, str]]] = {}
        # The tickets version each machine's last /wait answer carried: a newer one answers /wait at once.
        self.told_tickets: dict[str, int] = {}
        self.mac_keys: dict[str, tuple[str, bytes]] = {}
        self.skews: dict[str, int] = {}
        self.wait_seconds: float = protocol.WAIT_SECONDS
        self.snapshot = Snapshot(state)
        self.snapshot.refresh()
        self._box: bytes | None = None

    def hello(self) -> dict[str, Any]:
        return {"name": self.name, "fingerprint": protocol.fingerprint(self.public),
                "pairing": self.pairing_code() is not None}

    def box_private(self) -> bytes | None:
        """The admin's box key; read when first needed (an admin from before 0.2 gets it from the helper)."""

        if self._box is None:
            try:
                self._box = admin.read_box_key(self.box_path)
            except (OSError, ValueError):
                return None
        return self._box

    def mac_key(self, machine_id: str, box_key: str | None = None) -> bytes | None:
        if box_key is None:
            entry = admin.read_machines(self.state).get(machine_id)
            box_key = entry.get("box_key") if isinstance(entry, dict) else None
        private = self.box_private()
        if not box_key or private is None:
            return None
        with self.lock:
            cached = self.mac_keys.get(machine_id)
            if cached and cached[0] == box_key:
                return cached[1]
        try:
            mac_key, _seal = protocol.machine_keys(private, protocol.unb64(box_key, 32))
        except protocol.ProtocolError:
            return None
        with self.lock:
            self.mac_keys[machine_id] = (box_key, mac_key)
        return mac_key

    def identify(self, method: str, target: str, headers: Any, body: bytes,
                 now: float | None = None) -> tuple[str, str] | None:
        """(machine_id, "approved" or "pending" or "removed") of an authenticated request, or None (unknown machine,
        wrong MAC, time a day off). A removed machine authenticates with the box key removed.json kept. Records the
        machine's clock skew."""

        machine_id, when, mac = (headers.get("X-Caramos-Machine", ""), headers.get("X-Caramos-Time", ""),
                                 headers.get("X-Caramos-Mac", ""))
        if not protocol.UUID.match(machine_id or "") or not re.fullmatch(r"-?\d{1,12}", when or ""):
            return None
        now = time.time() if now is None else now
        if abs(now - int(when)) > protocol.MAX_SKEW:
            return None
        entry = admin.read_machines(self.state).get(machine_id)
        if isinstance(entry, dict):
            kind, box_key = ("approved" if admin.approved(entry) else "pending"), entry.get("box_key")
        else:
            record = admin.read_removed(self.state).get(machine_id) or {}
            kind, box_key = "removed", record.get("box_key")
        if not box_key:
            return None
        mac_key = self.mac_key(machine_id, box_key)
        if mac_key is None or not protocol.check_request_mac(mac_key, method, target, when, body, mac):
            return None
        with self.lock:
            self.skews[machine_id] = int(now) - int(when)
        return machine_id, kind

    def authenticate(self, method: str, target: str, headers: Any, body: bytes, now: float | None = None) -> str | None:
        """The machine_id of an authenticated request from an approved machine, or None."""

        found = self.identify(method, target, headers, body, now)
        return found[0] if found and found[1] == "approved" else None

    def pairing_code(self) -> str | None:
        """The open pairing window's code; a new window forgets the sessions and failures of the last one."""

        window = pairing.read_pairing(self.pairing)
        code = window["code"] if window else None
        with self.lock:
            if code != self.window_code:
                self.window_code = code
                self.sessions.reset()
        return code

    def removal_notice(self, machine_id: str) -> dict[str, str] | None:
        notice = (admin.read_removed(self.state).get(machine_id) or {}).get("notice")
        return notice if isinstance(notice, dict) else None

    def ticket_list(self, machine_id: str) -> dict[str, str]:
        """The machine's signed ticket list, signed again when its version moved."""

        store = tickets.read(self.state)
        version = tickets.version(store, machine_id)
        with self.lock:
            cached = self.ticket_lists.get(machine_id)
            if cached and cached[0] == version:
                return cached[1]
        signed = protocol.sign_tickets(self.key, tickets.machine_list(store, machine_id))
        with self.lock:
            self.ticket_lists[machine_id] = (version, signed)
        return signed

    def pending(self, machine_id: str, after: int, serial: int) -> list[dict[str, Any]] | None:
        """What /wait answers now, or None to keep waiting."""

        self.snapshot.refresh()  # two stat() calls: the answer never lags the files
        paired = (admin.read_machines(self.state).get(machine_id) or {}).get("paired", "")
        commands = self.snapshot.for_machine(machine_id, after, paired)
        if commands or self.snapshot.serial != serial:
            return commands
        return None

    def watch(self, stop: threading.Event | None = None) -> None:
        """Wakes the waiting /wait requests within a second of a new policy or new commands."""

        while not (stop and stop.is_set()):
            try:
                if self.snapshot.refresh():
                    with self.changed:
                        self.changed.notify_all()
            except Exception:  # noqa: BLE001 - the watcher must not die
                LOG.exception("watching the state")
            time.sleep(WATCH_SECONDS)

    def register(self, machine: dict[str, str], box_key: str, via: str = "code",
                 department: str | None = None) -> tuple[str, str]:
        """(machine_id, state) of a machine that paired; pending when the admin approves each machine."""

        with locked(self.state):
            pending = admin.read_options(self.state)["approve_machines"]
            replaced: list[str] = []
            if not department:  # a computer paired again stays in its department
                members = admin.read_policy(self.state).get("members") or {}
                same = [key for key, entry in admin.read_machines(self.state).items()
                        if machine.get("mac") and (entry.get("machine") or {}).get("mac") == machine.get("mac")]
                department = next((members[key] for key in same if key in members), None)
            machine_id = admin.register(machine, box_key, self.state, via=via, pending=pending, department=department,
                                        replaced=replaced)
            if pending:
                summary = _("%(name)s asks to join the company (%(ip)s).") % machine
            else:
                summary = _("%(name)s joined the company (%(ip)s).") % machine
            admin.audit("register", summary, "", self.state, machine_id=machine_id, name=machine["name"],
                        ip=machine["ip"], via=via, pairing="pending" if pending else "approved")
            if not pending:
                resign(self.state, self.key, self.name, machine_id, department, self.box_private())
        return machine_id, "pending" if pending else "approved"

    def check_in(self, machine_id: str, report: dict[str, Any]) -> bool:
        now = datetime.datetime.now().astimezone()
        with locked(self.state):
            entry = admin.check_in(machine_id, report, self.state, now)
            if entry is None:
                return False
            records = admin.read_health(self.state)
            effective = protocol.effective_settings(self.snapshot.policy, machine_id)
            with self.lock:
                skew = self.skews.get(machine_id)
            records[machine_id] = health.update_record(records.get(machine_id), entry, effective, now, skew)
            write_json(self.state / admin.HEALTH, records)
            catch_up(self.state, self.key, self.name, report.get("policy_serial"), self.box_private())
        return True


def catch_up(state: Path, key: Any, name: str, reported: Any, box_private: bytes | None) -> bool:
    """A machine holds a newer policy than this admin's: the admin was restored from a backup made before its last
    saves. Machines refuse a policy whose serial is not above the one they stored, so the same settings are signed
    again with a serial above the machine's, and the machines take them at their next /wait. Called with
    locked(state); whether it signed."""

    policy = admin.read_policy(state)
    serial = policy.get("serial")
    if not (isinstance(reported, int) and isinstance(serial, int) and serial and box_private is not None):
        return False
    # A paired machine can only hold serials this admin key signed; the cap keeps a misbehaving one from pushing the
    # numbers far ahead.
    if not serial < reported <= serial + MAX_CATCH_UP:
        return False
    try:
        saved = admin.save_policy(admin.draft_from_policy(policy), key, name, state, box_private=box_private,
                                  min_serial=reported + 1)
    except (protocol.ProtocolError, OSError) as exc:
        LOG.warning("could not sign the policy again above serial %s: %s", reported, exc)
        return False
    admin.audit("settings", _("The settings were signed again as version %(new)d: a machine had version %(old)d "
                              "(this admin machine was restored from an older backup).") % {
                    "new": saved["serial"], "old": reported}, "", state, serial=saved["serial"], changes=[],
                reason="catch-up", behind=serial)
    LOG.info("signed the policy again as serial %d: a machine had %d", saved["serial"], reported)
    return True


def resign(state: Path, key: Any, name: str, machine_id: str, department: str | None,
           box_private: bytes | None) -> bool:
    """A machine that joined after the last save gets the Wi-Fi passphrases of its networks, and the department of
    its enrolment file: the policy is signed again (serial + 1). Called with locked(state); whether it signed."""

    policy = admin.read_policy(state)
    if not policy.get("serial") or box_private is None:
        return False
    draft = admin.draft_from_policy(policy)
    joins = bool(department and department in draft["departments"] and draft["members"].get(machine_id) != department)
    if joins:
        draft["members"][machine_id] = department
    if not joins and not admin.needs_seal(policy, machine_id):
        return False
    try:
        admin.save_policy(draft, key, name, state, box_private=box_private)
    except (protocol.ProtocolError, OSError) as exc:
        LOG.warning("could not sign the policy again for %s: %s", machine_id, exc)
        return False
    LOG.info("signed the policy again for %s", machine_id)
    return True


def magic_packet(mac: str) -> bytes:
    return b"\xff" * 6 + bytes.fromhex(mac.replace(":", "")) * 16


def wake_macs(machine_id: str, entry: dict[str, Any], state: Path) -> list[str]:
    """The cards to wake a machine by: the one it reports toward the admin, and its wired ones."""

    macs = [(entry.get("machine") or {}).get("mac", "")]
    inventory = admin.read_inventory(machine_id, state) or {}
    macs += [card.get("mac", "") for card in inventory.get("network") or [] if card.get("wired")]
    return [mac for mac in dict.fromkeys(macs) if mac and protocol.MAC.match(mac)]


def due_wakes(policy: dict[str, Any], machines: dict[str, Any], now: datetime.datetime) -> list[str]:
    """The machines whose effective settings wake them at this minute: part 2's `wake`, and 5 minutes before the
    maintenance time of a machine that restores itself at reboot (part 3)."""

    due = []
    soon = now + datetime.timedelta(minutes=MAINTENANCE_WAKE_MINUTES)
    for machine_id in machines:
        effective = protocol.effective_settings(policy, machine_id)
        wake = (effective.get("power") or {}).get("wake")
        shared = effective.get("shared") or {}
        maintenance = shared.get("maintenance") if shared.get("freeze") else None
        if wake and now.isoweekday() in wake.get("days", []) and wake.get("time") == now.strftime("%H:%M"):
            due.append(machine_id)
        elif maintenance and soon.isoweekday() in maintenance.get("days", []) and \
                maintenance.get("time") == soon.strftime("%H:%M"):
            due.append(machine_id)
    return due


def send_wake(mac: str, sock: socket.socket | None = None) -> None:
    own = sock is None
    sock = sock or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for port in (9, 7):
            sock.sendto(magic_packet(mac), ("255.255.255.255", port))
    finally:
        if own:
            sock.close()


def serve_wake(state: Admin, stop: threading.Event | None = None) -> None:
    """Sends the magic packets at the wake times, once per machine and minute."""

    sent: set[tuple[str, str]] = set()
    while not (stop and stop.is_set()):
        now = datetime.datetime.now().astimezone()
        minute = now.strftime("%Y-%m-%d %H:%M")
        try:
            machines = admin.read_machines(state.state)
            for machine_id in due_wakes(state.snapshot.policy, machines, now):
                if (machine_id, minute) in sent:
                    continue
                sent.add((machine_id, minute))
                for mac in wake_macs(machine_id, machines[machine_id], state.state):
                    send_wake(mac)
                    LOG.info("wake-on-lan %s (%s)", admin.machine_name(machines, machine_id), mac)
        except Exception:  # noqa: BLE001 - the thread must not die
            LOG.exception("wake-on-lan")
        sent = {item for item in sent if item[1] >= (now - datetime.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M")}
        time.sleep(WAKE_CHECK_SECONDS)


def make_handler(state: Admin) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "caramos-business"

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - the base class's name
            LOG.info("%s %s", self.address_string(), format % args)

        def answer(self, status: int, body: Any) -> None:
            data = (json.dumps(body, ensure_ascii=False) + "\n").encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def raw_body(self, limit: int) -> bytes | None:
            """The request's body; None when it is longer than limit (or its length is not a number)."""

            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None
            if not 0 <= length <= limit:
                return None
            return self.rfile.read(length) if length else b""

        def route(self) -> tuple[str, dict[str, list[str]]]:
            parts = urllib.parse.urlsplit(self.path)
            path = parts.path
            if path.startswith(protocol.PREFIX):
                path = path[len(protocol.PREFIX):]
            else:
                path = "/not-found"
            return path, urllib.parse.parse_qs(parts.query)

        def empty(self, status: int) -> None:
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def who(self, method: str, body: bytes) -> str | None:
            """The approved machine of an HMAC request, or None once the answer (401, 403 pending, 410) is sent.
            GET /policy answers a removed machine with its notice itself."""

            found = state.identify(method, self.path, self.headers, body)
            if found is None:
                self.answer(401, {"error": "not authenticated"})
                return None
            machine_id, kind = found
            if kind == "pending":
                self.answer(403, {"error": "pending"})
                return None
            if kind == "removed":
                notice = state.removal_notice(machine_id)
                if self.route()[0] == "/policy" and notice:
                    self.answer(200, notice)
                else:
                    self.empty(410)
                return None
            return machine_id

        def do_GET(self) -> None:  # noqa: N802 - http.server's name
            path, query = self.route()
            if path == "/hello":
                self.answer(200, state.hello())
                return
            is_file = FILE_PATH.match(f"{protocol.PREFIX}{path}") is not None
            if path not in ("/policy", "/wait", "/tickets") and not is_file:
                self.answer(404, {"error": "not found"})
                return
            machine_id = self.who("GET", b"")
            if machine_id is None:
                return
            if path == "/policy":
                signed = read_json(state.state / admin.SIGNED)
                if isinstance(signed, dict):
                    self.answer(200, signed)
                else:
                    self.answer(404, {"error": "no policy yet"})
            elif is_file:
                self.send_file(path.rsplit("/", 1)[1])
            elif path == "/tickets":
                self.answer(200, state.ticket_list(machine_id))
            else:
                self.wait(machine_id, query)

        def send_file(self, sha: str) -> None:
            policy = admin.read_policy(state.state)
            if sha not in policy.get("files", {}):
                self.answer(404, {"error": "not a file of the policy"})
                return
            try:
                data = (state.state / admin.FILES / sha).read_bytes()
            except OSError:
                self.answer(404, {"error": "missing"})
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def wait(self, machine_id: str, query: dict[str, list[str]]) -> None:
            try:
                after = int(query["after"][0])
                serial = int(query["serial"][0])
            except (KeyError, IndexError, ValueError):
                self.answer(400, {"error": "after and serial are numbers"})
                return
            deadline = time.monotonic() + state.wait_seconds
            with state.changed:
                while True:
                    commands = state.pending(machine_id, after, serial)
                    # A public note or status change reaches the employee within a second or two, not at the end of
                    # the long poll. The first wait after the server starts only sets the mark: the agent fetched its
                    # tickets when it started.
                    version = state.snapshot.ticket_version(machine_id)
                    moved = state.told_tickets.setdefault(machine_id, version) != version
                    remaining = deadline - time.monotonic()
                    if commands is not None or moved or remaining <= 0:
                        break
                    state.changed.wait(min(remaining, 1.0))
                state.told_tickets[machine_id] = version
            self.answer(200, {"serial": state.snapshot.serial, "commands": commands or [], "tickets": version})

        def do_POST(self) -> None:  # noqa: N802 - http.server's name
            path, _query = self.route()
            limit = protocol.MAX_INVENTORY if path == "/inventory" else protocol.MAX_BODY
            raw = self.raw_body(limit)
            if raw is None:
                self.answer(413, {"error": "the body is too big"})
                return
            unauthenticated = {"/pair/start": self.pair_start, "/pair/finish": self.pair_finish,
                               "/register": self.register}
            if path in unauthenticated:
                try:
                    body = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    self.answer(400, {"error": "not JSON"})
                    return
                unauthenticated[path](body)
                return
            if path not in POSTS:
                self.answer(404, {"error": "not found"})
                return
            machine_id = self.who("POST", raw)
            if machine_id is None:
                return
            try:
                body = json.loads(raw.decode("utf-8"))
                {"/checkin": self.check_in, "/inventory": self.inventory, "/result": self.result,
                 "/help": self.help_request}[path](machine_id, body)
            except (UnicodeDecodeError, ValueError) as exc:  # ProtocolError is a ValueError
                self.answer(400, {"error": str(exc) or "not JSON"})

        def admin_box_b64(self) -> str | None:
            private = state.box_private()
            return protocol.b64(protocol.box_public(private)) if private is not None else None

        def pair_start(self, body: Any) -> None:
            code = state.pairing_code()
            if code is None:
                self.answer(403, {"error": "pairing closed"})
                return
            box = self.admin_box_b64()
            if box is None:
                self.answer(503, {"error": "the admin has no box key yet"})
                return
            try:
                msg_a = protocol.validate_pair_start(body)
                session, msg_b, _key = state.sessions.start(code, msg_a, self.client_address[0])
            except pairing.PairingBusy:
                self.answer(429, {"error": "busy"})
                return
            except protocol.ProtocolError as exc:
                self.answer(400, {"error": str(exc)})
                return
            self.answer(200, {"session": session, "msg": protocol.b64(msg_b), "admin_name": state.name,
                              "admin_key": state.public_b64, "admin_box_key": box})

        def pair_finish(self, body: Any) -> None:
            if state.pairing_code() is None:
                self.answer(403, {"error": "pairing closed"})
                return
            try:
                request = protocol.validate_pair_finish(body)
            except protocol.ProtocolError as exc:
                self.answer(400, {"error": str(exc)})
                return
            session = state.sessions.take(request["session"])
            if session is None:
                self.answer(403, {"error": "session"})
                return
            k_employee, k_admin = protocol.pair_keys(session["key"])
            transcript = protocol.pair_transcript(request["session"], session["msg_a"], session["msg_b"], state.name,
                                                  state.public_b64, self.admin_box_b64() or "", request["box_key"],
                                                  request["sent_machine"])
            if not protocol.same_mac(k_employee, transcript, request["confirm"]):
                if state.sessions.failed() == MAX_WRONG_CODES:
                    admin.close_pairing(state.pairing)
                    LOG.warning("pairing closed after %d wrong codes", MAX_WRONG_CODES)
                    with locked(state.state):
                        admin.audit("pairing", _("Adding machines stopped by itself after 20 wrong codes."), "",
                                    state.state, pairing="closed", reason="wrong codes")
                self.answer(403, {"error": "wrong code"})
                return
            machine_id, pairing_state = state.register(request["machine"], request["box_key"])
            LOG.info("paired %s (%s), %s", request["machine"]["name"], request["machine"]["ip"], pairing_state)
            self.answer(200, {"machine_id": machine_id, "state": pairing_state,
                              "confirm": protocol.hmac_b64(k_admin, protocol.answer_message(transcript, machine_id,
                                                                                             pairing_state))})

        def register(self, body: Any) -> None:
            """Enrolment with a token from an enrolment file (PROTOCOL.md part 3)."""

            try:
                request = protocol.validate_register(body)
            except protocol.ProtocolError as exc:
                self.answer(400, {"error": str(exc)})
                return
            now = datetime.datetime.now().astimezone()
            with locked(state.state):
                outcome, record, proof_key = pairing.check_enrolment(state.state, request, state.public_b64, now,
                                                                     state.replays)
                if outcome == "proof":
                    token = pairing.read_tokens(state.state).get(request["token_id"]) or {}
                    if token.get("revoked") and token.get("failures", 0) == pairing.MAX_FAILURES:
                        admin.audit("enroll-token", _("An enrolment file was turned off after too many wrong "
                                                      "requests."), "", state.state, token_id=request["token_id"],
                                    token="disabled")
            if outcome != "ok" or record is None or proof_key is None:
                self.answer(403, {"error": "token" if outcome == "token" else "proof"})
                return
            via = f"enroll:{request['token_id']}"
            machine_id, pairing_state = state.register(request["machine"], request["box_key"], via,
                                                       record.get("department"))
            with locked(state.state):
                pairing.add_machine(state.state, request["token_id"], machine_id)
            message = protocol.enroll_transcript(request["token_id"], request["time"], state.public_b64,
                                                 request["box_key"], request["sent_machine"])
            LOG.info("enrolled %s (%s), %s", request["machine"]["name"], request["machine"]["ip"], pairing_state)
            self.answer(200, {"machine_id": machine_id, "state": pairing_state,
                              "confirm": protocol.hmac_b64(proof_key, protocol.answer_message(message, machine_id,
                                                                                               pairing_state))})

        def check_in(self, machine_id: str, body: Any) -> None:
            report = protocol.validate_checkin(body)
            if report["machine_id"] not in (None, machine_id):
                raise protocol.ProtocolError("the body's machine_id is not the header's")
            if not state.check_in(machine_id, report):
                self.answer(401, {"error": "unknown machine"})
                return
            self.answer(200, {"ok": True})

        def inventory(self, machine_id: str, body: Any) -> None:
            state.snapshot.refresh()
            if not protocol.effective_settings(state.snapshot.policy, machine_id).get("inventory"):
                self.answer(403, {"error": "the inventory is not turned on for this machine"})
                return
            inventory = protocol.validate_inventory(body)
            admin.write_inventory(machine_id, inventory, state.state)
            self.answer(200, {"ok": True})

        def result(self, machine_id: str, body: Any) -> None:
            result = protocol.validate_result(body)
            with locked(state.state):
                admin.record_result(machine_id, result, state.snapshot.command_ids(), state.state)
            self.answer(200, {"ok": True})

        def help_request(self, machine_id: str, body: Any) -> None:
            request = protocol.validate_help(body)
            entry = admin.read_machines(state.state).get(machine_id) or {}
            with locked(state.state):
                ticket, version = tickets.create(state.state, machine_id, request, entry.get("health"),
                                                 admin.read_inventory(machine_id, state.state))
            LOG.info("help request from %s: %s", machine_id, ticket["id"])
            self.answer(200, {"ticket": ticket["id"], "tickets": version})

    return Handler


def serve_discovery(state: Admin, sock: socket.socket) -> None:
    """Answers DISCOVER datagrams, to the sender."""

    while True:
        try:
            data, sender = sock.recvfrom(protocol.MAX_DATAGRAM + 1)
        except OSError:
            return
        if data.strip() == protocol.DISCOVER.encode("ascii"):
            try:
                sock.sendto(protocol.here_datagram(state.name, state.public, state.pairing_code() is not None),
                            sender)
            except OSError as exc:
                LOG.warning("discovery answer to %s: %s", sender, exc)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64


def clear_remote_help_rules() -> None:
    """Removes the viewer-port rules a remote help session left behind (PROTOCOL.md part 3)."""

    for tool in ("iptables", "ip6tables"):
        for _attempt in range(8):
            done = subprocess.run([tool, "-D", "INPUT", "-p", "tcp", "--dport", str(VIEWER_PORT), "!", "-i", "lo",
                                   "-m", "comment", "--comment", REMOTE_HELP_RULE, "-j", "DROP"],
                                  capture_output=True, timeout=30, check=False)
            if done.returncode != 0:
                break


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        clear_remote_help_rules()
    except (OSError, subprocess.SubprocessError) as exc:
        LOG.warning("could not check the remote help rules: %s", exc)
    try:
        key = protocol.key_from_pem(ADMIN_KEY.read_bytes())
    except (OSError, ValueError) as exc:
        LOG.error("no admin key (%s): choose the admin role in the window first", exc)
        return 1
    state = Admin(key, socket.gethostname().split(".")[0])
    if state.box_private() is None:
        LOG.warning("no box key yet: paired machines cannot authenticate until the window saves once")
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp.bind(("0.0.0.0", protocol.UDP_PORT))
    threading.Thread(target=serve_discovery, args=(state, udp), daemon=True).start()
    threading.Thread(target=state.watch, daemon=True).start()
    threading.Thread(target=serve_wake, args=(state,), daemon=True).start()
    http = Server(("0.0.0.0", protocol.HTTP_PORT), make_handler(state))
    LOG.info("serving %s on UDP %d and HTTP %d", state.name, protocol.UDP_PORT, protocol.HTTP_PORT)
    try:
        http.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

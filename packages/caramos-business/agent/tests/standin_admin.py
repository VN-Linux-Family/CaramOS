#!/usr/bin/python3
"""A stand-in admin for testing the 0.3 agent on VMs (PROTOCOL.md parts 2 and 3), with the fixed test keys of
../../tests/protocol-examples/v2/keys.json. Never use it, or those keys, for anything real.

    standin_admin.py serve STATE [--port 47022] [--bind 0.0.0.0]
    standin_admin.py machine STATE --url http://IP:PORT --name NAME [--pending] [--machine-id-os ID]
    standin_admin.py approve STATE MACHINE_ID
    standin_admin.py remove STATE MACHINE_ID
    standin_admin.py policy STATE POLICY.json [--secrets SECRETS.json]
    standin_admin.py command STATE ACTION 'ARGS-JSON' [--machines ID,...|--departments ID,...] [--expires-minutes N]
                     [--psk-file FILE]
    standin_admin.py ticket STATE (--machine ID --user LOGIN --note TEXT | --id HT-0001 [--status S] [--text T])

STATE is a folder: signed-policy.json, files/<sha256>, commands.json, results.json, machines.json (each machine's box
key and state), removed.json (removal notices), tickets.json, pairings/<machine_id>/ (the agent.json and agent-box.key
`machine` made, to copy to /etc/caramos-business/), and log/ with every request it received, each with whether its MAC
was right.

- Every request but /hello needs the machine's MAC (from 0.3 GET /policy and /files too): 401 without it. A pending
  machine gets 403 {"error": "pending"}; a removed one gets its signed notice from GET /policy and 410 elsewhere.
- `/wait` answers at once when the policy serial differs or there are commands after `after` that this machine has
  not answered (no second delivery), and wakes when the tickets or the machines change; it carries the machine's
  tickets version.
- `policy` fills in format, serial (one more than the last), issued, admin_box_key and, from SECRETS
  (`{"<machine_id>": {"wifi": {"<ssid>": "<passphrase>"}}}`), each machine's sealed secrets; it copies the files the
  policy names (`"files": {"<path>": "<type>"}` becomes the sha256 entries).
- `command remote_help` with `--psk-file` (`<identity>:<64 hex>`, as the admin's remote-help.psk) seals the key for
  the one target machine into `args.psk`.
"""

from __future__ import annotations

import argparse
import base64
import datetime
import hashlib
import hmac
import json
import os
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

HERE = Path(__file__).resolve().parent
KEYS = json.loads((HERE.parent.parent / "tests/protocol-examples/v2/keys.json").read_text(encoding="utf-8"))
B64 = lambda data: base64.b64encode(data).decode("ascii")
RAW = serialization.Encoding.Raw, serialization.PublicFormat.Raw
API = "/caramos-business/v1"
TZ = datetime.timezone(datetime.timedelta(hours=7))
ADMIN_NAME = "standin"

SIGN = Ed25519PrivateKey.from_private_bytes(base64.b64decode(KEYS["admin_sign_seed"]))
ADMIN_BOX = X25519PrivateKey.from_private_bytes(base64.b64decode(KEYS["admin_box_seed"]))
ADMIN_KEY_B64 = B64(SIGN.public_key().public_bytes(*RAW))
ADMIN_BOX_B64 = B64(ADMIN_BOX.public_key().public_bytes(*RAW))
FINGERPRINT = hashlib.sha256(SIGN.public_key().public_bytes(*RAW)).hexdigest()[:16]


def shared_keys(machine_public: bytes) -> tuple[bytes, bytes]:
    secret = ADMIN_BOX.exchange(X25519PublicKey.from_public_bytes(machine_public))
    derive = lambda info: HKDF(algorithm=hashes.SHA256(), length=32, salt=b"caramos-business/2", info=info).derive(secret)
    return derive(b"mac"), derive(b"seal")


def now_iso() -> str:
    return datetime.datetime.now(TZ).replace(microsecond=0).isoformat()


def compact(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def signed(value: dict, field: str, *, pretty: bool = False) -> dict:
    text = json.dumps(value, ensure_ascii=False, indent=1) if pretty else compact(value)
    return {field: text, "signature": B64(SIGN.sign(text.encode("utf-8")))}


def seal(secrets: dict, machine_id: str, machine_public: bytes) -> str:
    _mac, seal_key = shared_keys(machine_public)
    nonce = os.urandom(12)
    return B64(nonce + ChaCha20Poly1305(seal_key).encrypt(nonce, compact(secrets).encode("utf-8"), machine_id.encode("ascii")))


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, value, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.chmod(temp, mode)
    temp.replace(path)


# ---- the server -----------------------------------------------------------------------------------------------


class State:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.lock = threading.Lock()

    def path(self, name: str) -> Path:
        return self.folder / name

    def signed_policy(self) -> dict:
        return read_json(self.path("signed-policy.json"), {})

    def serial(self) -> int:
        text = self.signed_policy().get("policy")
        return json.loads(text)["serial"] if text else 0

    def machines(self) -> dict:
        return read_json(self.path("machines.json"), {})

    def removed(self) -> dict:
        return read_json(self.path("removed.json"), {})

    def box_key(self, machine_id: str) -> bytes | None:
        entry = self.machines().get(machine_id) or self.removed().get(machine_id)
        return base64.b64decode(entry["box_key"]) if entry else None

    def department(self, machine_id: str) -> str | None:
        text = self.signed_policy().get("policy")
        return json.loads(text).get("members", {}).get(machine_id) if text else None

    def answered(self, machine_id: str) -> set:
        return {command_id for command_id, by in read_json(self.path("results.json"), {}).items() if machine_id in by}

    def commands_after(self, seq: int, machine_id: str) -> list:
        found, answered, department = [], self.answered(machine_id), self.department(machine_id)
        for envelope in read_json(self.path("commands.json"), {"commands": []})["commands"]:
            command = json.loads(envelope["command"])
            targets = command["targets"]
            ours = targets.get("all") or machine_id in targets.get("machines", []) or department in targets.get("departments", [])
            if command["seq"] > seq and ours and command["id"] not in answered:
                found.append(envelope)
        return found[:50]

    def tickets_version(self, machine_id: str) -> int:
        return read_json(self.path("tickets.json"), {}).get("versions", {}).get(machine_id, 0)

    def signed_tickets(self, machine_id: str) -> dict:
        store = read_json(self.path("tickets.json"), {"tickets": []})
        mine = [{"id": t["id"], "user": t["user"], "created": t["created"], "status": t["status"], "note": t["note"],
                 "updates": t.get("updates", [])[-20:]}
                for t in store["tickets"] if t["machine_id"] == machine_id][-50:]
        return signed({"kind": "tickets", "machine_id": machine_id, "version": self.tickets_version(machine_id),
                       "issued": now_iso(), "tickets": mine}, "tickets")

    def mtimes(self) -> tuple:
        return tuple(self.path(name).stat().st_mtime_ns if self.path(name).exists() else 0
                     for name in ("signed-policy.json", "commands.json", "tickets.json", "machines.json", "removed.json"))

    def log(self, kind: str, entry: dict) -> None:
        with self.lock:
            folder = self.path("log")
            folder.mkdir(parents=True, exist_ok=True)
            with (folder / f"{kind}.jsonl").open("a", encoding="utf-8") as out:
                out.write(json.dumps(dict(entry, received=now_iso()), ensure_ascii=False) + "\n")


def add_ticket(state: State, machine_id: str, user: str, note: str) -> tuple[str, int]:
    with state.lock:
        store = read_json(state.path("tickets.json"), {"next": 1, "versions": {}, "tickets": []})
        ticket_id = f"HT-{store['next']:04d}"
        store["next"] += 1
        store["tickets"].append({"id": ticket_id, "machine_id": machine_id, "user": user, "note": note[:300],
                                 "created": now_iso(), "status": "new", "updates": []})
        store["versions"][machine_id] = store["versions"].get(machine_id, 0) + 1
        write_json(state.path("tickets.json"), store)
        return ticket_id, store["versions"][machine_id]


def handler(state: State):
    class Handler(BaseHTTPRequestHandler):
        server_version = "standin-admin/0.3"

        def log_message(self, fmt, *args) -> None:
            sys.stderr.write(f"{now_iso()} {self.client_address[0]} {fmt % args}\n")

        def send(self, status: int, body: bytes = b"", kind: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, value) -> None:
            self.send(200, json.dumps(value, ensure_ascii=False).encode("utf-8"))

        def authenticated(self, body: bytes) -> str | None:
            machine = self.headers.get("X-Caramos-Machine", "")
            when = self.headers.get("X-Caramos-Time", "")
            mac = self.headers.get("X-Caramos-Mac", "")
            public = state.box_key(machine)
            if public is None:
                return None
            mac_key, _seal = shared_keys(public)
            message = f"{self.command}\n{self.path}\n{when}\n{hashlib.sha256(body).hexdigest()}".encode("ascii")
            expected = B64(hmac.new(mac_key, message, hashlib.sha256).digest())
            fresh = when.isdigit() and abs(time.time() - int(when)) <= 86400
            return machine if (hmac.compare_digest(mac, expected) and fresh) else None

        def gate(self, body: bytes) -> str | None:
            """The machine of an authenticated request that may go on; None when an answer was sent."""
            machine = self.authenticated(body)
            if machine is None:
                state.log("rejected", {"method": self.command, "path": self.path})
                self.send(401, b"{}")
                return None
            removed = state.removed().get(machine)
            if removed:
                state.log("removed", {"machine": machine, "path": self.path})
                if self.command == "GET" and self.path == f"{API}/policy":
                    self.send_json(removed["notice"])
                else:
                    self.send(410)
                return None
            if state.machines()[machine].get("state") == "pending":
                state.log("pending", {"machine": machine, "path": self.path})
                self.send(403, b'{"error": "pending"}')
                return None
            return machine

        def do_GET(self) -> None:  # noqa: N802
            if self.path == f"{API}/hello":
                return self.send_json({"name": ADMIN_NAME, "fingerprint": FINGERPRINT, "pairing": False})
            machine = self.gate(b"")
            if machine is None:
                return None
            state.log("get", {"machine": machine, "path": self.path})
            if self.path == f"{API}/policy":
                return self.send_json(state.signed_policy())
            if self.path == f"{API}/tickets":
                return self.send_json(state.signed_tickets(machine))
            if self.path.startswith(f"{API}/files/"):
                sha = self.path.rsplit("/", 1)[-1]
                path = state.path("files") / sha
                return self.send(200, path.read_bytes(), "application/octet-stream") if path.is_file() and len(sha) == 64 else self.send(404, b"{}")
            if self.path.startswith(f"{API}/wait?"):
                query = dict(part.split("=", 1) for part in self.path.split("?", 1)[1].split("&"))
                after, serial = int(query.get("after", 0)), int(query.get("serial", 0))
                start, deadline = state.mtimes(), time.time() + 50
                while time.time() < deadline:
                    if state.commands_after(after, machine) or state.serial() != serial or state.mtimes() != start:
                        break
                    time.sleep(0.5)
                return self.send_json({"serial": state.serial(), "commands": state.commands_after(after, machine),
                                       "tickets": state.tickets_version(machine)})
            self.send(404, b"{}")

        def do_POST(self) -> None:  # noqa: N802
            body = self.rfile.read(min(int(self.headers.get("Content-Length", "0")), 2 * 1024 * 1024))
            machine = self.gate(body)
            if machine is None:
                return None
            kind = self.path.removeprefix(f"{API}/")
            try:
                value = json.loads(body)
            except ValueError:
                return self.send(400, b"{}")
            state.log(kind, {"machine": machine, "body": value})
            if kind == "result":
                with state.lock:
                    results = read_json(state.path("results.json"), {})
                    results.setdefault(value["id"], {})[machine] = dict(value, received=now_iso())
                    write_json(state.path("results.json"), results)
            if kind == "help":
                ticket_id, version = add_ticket(state, machine, value.get("user", ""), value.get("note", ""))
                return self.send_json({"ticket": ticket_id, "tickets": version})
            self.send(200, b'{"ok": true}')

    return Handler


def serve(args) -> None:
    state = State(Path(args.state))
    server = ThreadingHTTPServer((args.bind, args.port), handler(state))
    server.daemon_threads = True
    print(f"stand-in admin on {args.bind}:{args.port}, state {args.state}, fingerprint {FINGERPRINT}", flush=True)
    server.serve_forever()


# ---- machines -------------------------------------------------------------------------------------------------


def make_machine(args) -> None:
    state = State(Path(args.state))
    machine_id = str(uuid.uuid4())
    box = X25519PrivateKey.generate()
    public = box.public_key().public_bytes(*RAW)
    folder = state.path("pairings") / machine_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "agent-box.key").write_bytes(box.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw,
                                                              serialization.NoEncryption()))
    agent = {"admin_url": args.url, "admin_name": ADMIN_NAME, "admin_key": ADMIN_KEY_B64, "admin_box_key": ADMIN_BOX_B64,
             "fingerprint": FINGERPRINT, "machine_id": machine_id}
    if args.machine_id_os:
        agent["machine_id_os"] = args.machine_id_os
    write_json(folder / "agent.json", agent, 0o600)
    machines = state.machines()
    machines[machine_id] = {"name": args.name, "box_key": B64(public), "state": "pending" if args.pending else "approved",
                            "paired": now_iso()}
    write_json(state.path("machines.json"), machines)
    print(json.dumps({"machine_id": machine_id, "folder": str(folder)}))


def approve(args) -> None:
    state = State(Path(args.state))
    machines = state.machines()
    machines[args.machine_id]["state"] = "approved"
    write_json(state.path("machines.json"), machines)
    print(f"{args.machine_id} approved")


def remove(args) -> None:
    state = State(Path(args.state))
    machines = state.machines()
    entry = machines.pop(args.machine_id)
    notice = signed({"kind": "removed", "machine_id": args.machine_id, "admin": ADMIN_NAME, "time": now_iso()}, "notice")
    removed = state.removed()
    removed[args.machine_id] = {"time": now_iso(), "name": entry.get("name", ""), "box_key": entry["box_key"], "notice": notice}
    write_json(state.path("removed.json"), removed)
    write_json(state.path("machines.json"), machines)
    print(json.dumps(notice))


# ---- publishing -----------------------------------------------------------------------------------------------


def publish_policy(args) -> None:
    state = State(Path(args.state))
    policy = read_json(Path(args.policy), None)
    if not isinstance(policy, dict):
        sys.exit("the policy is not a JSON object")
    files = {}
    for path, kind in policy.pop("files", {}).items():
        data = Path(path).read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        state.path("files").mkdir(parents=True, exist_ok=True)
        (state.path("files") / sha).write_bytes(data)
        files[sha] = {"size": len(data), "type": kind}
    secrets = read_json(Path(args.secrets), {}) if args.secrets else {}
    entries = policy.setdefault("machines", {})
    for machine_id, machine_secrets in secrets.items():
        entries.setdefault(machine_id, {}).setdefault("settings", {})
        entries[machine_id]["sealed"] = seal(machine_secrets, machine_id, state.box_key(machine_id))
    full = {"format": 2, "serial": state.serial() + 1, "issued": now_iso(), "admin": ADMIN_NAME, "admin_box_key": ADMIN_BOX_B64,
            "files": files}
    full.update({key: value for key, value in policy.items() if key not in full})
    write_json(state.path("signed-policy.json"), signed(full, "policy"))
    print(f"policy {full['serial']} signed")


def publish_command(args) -> None:
    state = State(Path(args.state))
    store = read_json(state.path("commands.json"), {"seq": 0, "commands": []})
    seq = store["seq"] + 1
    if args.machines:
        targets = {"machines": args.machines.split(",")}
    elif args.departments:
        targets = {"departments": args.departments.split(",")}
    else:
        targets = {"all": True}
    command_args = json.loads(args.args)
    if args.psk_file:
        if len(targets.get("machines", [])) != 1:
            sys.exit("remote help goes to one machine")
        identity, key = Path(args.psk_file).read_text(encoding="ascii").strip().split(":", 1)
        machine_id = targets["machines"][0]
        command_args["psk"] = seal({"identity": identity, "key": key}, machine_id, state.box_key(machine_id))
    issued = datetime.datetime.now(TZ).replace(microsecond=0)
    command = {"seq": seq, "id": str(uuid.uuid4()), "targets": targets, "action": args.action, "args": command_args,
               "issued": issued.isoformat(), "expires": (issued + datetime.timedelta(minutes=args.expires_minutes)).isoformat()}
    store["seq"] = seq
    store["commands"].append(signed(command, "command", pretty=True))
    write_json(state.path("commands.json"), store)
    print(json.dumps({"seq": seq, "id": command["id"]}))


def ticket(args) -> None:
    state = State(Path(args.state))
    if args.machine:
        ticket_id, version = add_ticket(state, args.machine, args.user, args.note)
        print(json.dumps({"ticket": ticket_id, "version": version}))
        return
    with state.lock:
        store = read_json(state.path("tickets.json"), {"next": 1, "versions": {}, "tickets": []})
        found = next(t for t in store["tickets"] if t["id"] == args.id)
        update = {"time": now_iso(), "text": (args.text or "")[:500]}
        if args.status and args.status != found["status"]:
            found["status"] = update["status"] = args.status
        found.setdefault("updates", []).append(update)
        store["versions"][found["machine_id"]] = store["versions"].get(found["machine_id"], 0) + 1
        write_json(state.path("tickets.json"), store)
    print(json.dumps({"ticket": args.id, "version": store["versions"][found["machine_id"]]}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="what", required=True)
    serve_parser = commands.add_parser("serve")
    serve_parser.add_argument("state")
    serve_parser.add_argument("--port", type=int, default=47022)
    serve_parser.add_argument("--bind", default="0.0.0.0")
    machine_parser = commands.add_parser("machine")
    machine_parser.add_argument("state")
    machine_parser.add_argument("--url", required=True)
    machine_parser.add_argument("--name", required=True)
    machine_parser.add_argument("--pending", action="store_true")
    machine_parser.add_argument("--machine-id-os")
    for name in ("approve", "remove"):
        sub = commands.add_parser(name)
        sub.add_argument("state")
        sub.add_argument("machine_id")
    policy_parser = commands.add_parser("policy")
    policy_parser.add_argument("state")
    policy_parser.add_argument("policy")
    policy_parser.add_argument("--secrets")
    command_parser = commands.add_parser("command")
    command_parser.add_argument("state")
    command_parser.add_argument("action")
    command_parser.add_argument("args")
    command_parser.add_argument("--machines")
    command_parser.add_argument("--departments")
    command_parser.add_argument("--expires-minutes", type=int, default=30)
    command_parser.add_argument("--psk-file")
    ticket_parser = commands.add_parser("ticket")
    ticket_parser.add_argument("state")
    ticket_parser.add_argument("--machine")
    ticket_parser.add_argument("--user")
    ticket_parser.add_argument("--note", default="")
    ticket_parser.add_argument("--id")
    ticket_parser.add_argument("--status", choices=["new", "working", "waiting", "done"])
    ticket_parser.add_argument("--text")
    args = parser.parse_args()
    {"serve": serve, "machine": make_machine, "approve": approve, "remove": remove, "policy": publish_policy,
     "command": publish_command, "ticket": ticket}[args.what](args)


if __name__ == "__main__":
    main()

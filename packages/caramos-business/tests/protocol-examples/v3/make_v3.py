#!/usr/bin/python3
"""Makes the version 0.3 test vectors of PROTOCOL.md part 3 (run from this folder, where python3-spake2 and
python3-cryptography are installed: Ubuntu 24.04 with universe). The keys are v2's fixed test keys: never use them for
anything real. Entropy, nonces and times are fixed so that the files come out the same at every run.

Not made here: apt-cache-policy-sources.txt and apt-cache-policy-packages.txt are real `apt-cache policy` output
(Ubuntu 24.04 with Linux Mint's, the CaramOS PPA's and Google's repositories, 2026-11-23), with `***` marks added to
google-chrome-stable, caramos-ota and mint-common to show them installed; expected-42_caramos-business-maintenance is
the script verified on the test VM."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path

import spake2
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

HERE = Path(__file__).resolve().parent
B64 = lambda data: base64.b64encode(data).decode("ascii")
RAW = serialization.Encoding.Raw, serialization.PublicFormat.Raw

ADMIN_SIGN_SEED = bytes(range(0, 32))       # v2's keys
ADMIN_BOX_SEED = bytes(range(32, 64))
MACHINE_BOX_SEED = bytes(range(64, 96))
MACHINE_ID = "7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6"
OTHER_MACHINE_ID = "0d9e8f7a-6b5c-4d3e-9f21-0a1b2c3d4e5f"
SEAL_NONCE = bytes(range(100, 112))         # fixed only for the vectors; real seals use a random nonce
PSK_NONCE = bytes(range(112, 124))
TOKEN = bytes(range(200, 232))
TOKEN_ID = "a1b2c3d4e5f60718"
CODE = b"482913"
SESSION = "6f1d2c3b-4a59-4e68-8d7c-1b2a3c4d5e6f"
WHEN = 1795200000                           # 2026-11-21T22:40:00+07:00
ADMIN_NAME = "quan-ly"
ROOT_UUID = "33113ae9-4550-4a48-a3cb-12d57f6ae6ff"
MACHINE = {"name": "ke-toan-01", "ip": "192.168.1.20", "mac": "52:54:00:12:34:56", "edition": "cinnamon",
           "version": "1.4.0"}
SALT = b"caramos-business/3"


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compact(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def hkdf(ikm: bytes, info: bytes, salt: bytes = SALT) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt, info=info).derive(ikm)


def mac(key: bytes, message: bytes) -> bytes:
    return hmac.new(key, message, hashlib.sha256).digest()


def write(name: str, value: object) -> None:
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def write_text(name: str, text: str) -> None:
    (HERE / name).write_text(text, encoding="utf-8")


def signed(key: Ed25519PrivateKey, value: dict, field: str, *, compact_text: bool = True) -> dict:
    text = compact(value) if compact_text else json.dumps(value, ensure_ascii=False, indent=1)
    return {field: text, "signature": B64(key.sign(text.encode("utf-8")))}


def entropy(seed: bytes):
    """A fixed stand-in for os.urandom: SHA-256(seed + 4-byte big-endian counter), concatenated."""

    counter = [0]

    def take(count: int) -> bytes:
        out = b""
        while len(out) < count:
            out += hashlib.sha256(seed + counter[0].to_bytes(4, "big")).digest()
            counter[0] += 1
        return out[:count]

    return take


def main() -> None:
    sign_key = Ed25519PrivateKey.from_private_bytes(ADMIN_SIGN_SEED)
    admin_box = X25519PrivateKey.from_private_bytes(ADMIN_BOX_SEED)
    machine_box = X25519PrivateKey.from_private_bytes(MACHINE_BOX_SEED)
    admin_key_b64 = B64(sign_key.public_key().public_bytes(*RAW))
    admin_box_b64 = B64(admin_box.public_key().public_bytes(*RAW))
    machine_box_b64 = B64(machine_box.public_key().public_bytes(*RAW))
    secret = admin_box.exchange(machine_box.public_key())
    mac_key = hkdf(secret, b"mac", salt=b"caramos-business/2")
    seal_key = hkdf(secret, b"seal", salt=b"caramos-business/2")
    fingerprint = hashlib.sha256(sign_key.public_key().public_bytes(*RAW)).hexdigest()[:16]
    write("keys.json", {"note": "v2's keys (see ../v2/keys.json)", "admin_sign_public": admin_key_b64,
                        "admin_box_public": admin_box_b64, "machine_box_public": machine_box_b64,
                        "machine_id": MACHINE_ID, "fingerprint": fingerprint, "mac_key_hex": mac_key.hex(),
                        "seal_key_hex": seal_key.hex()})

    # Pairing with a code (SPAKE2, python3-spake2 0.8, fixed entropy).
    ids = {"idA": b"caramos-business employee", "idB": b"caramos-business admin"}
    employee = spake2.SPAKE2_A(CODE, entropy_f=entropy(b"caramos-business/3 test entropy A"), **ids)
    admin = spake2.SPAKE2_B(CODE, entropy_f=entropy(b"caramos-business/3 test entropy B"), **ids)
    msg_a, msg_b = employee.start(), admin.start()
    key = employee.finish(msg_b)
    assert key == admin.finish(msg_a)
    k_employee, k_admin = hkdf(key, b"pair employee"), hkdf(key, b"pair admin")
    transcript = canonical({"kind": "caramos-business/3 pair", "session": SESSION, "msg_a": B64(msg_a),
                            "msg_b": B64(msg_b), "admin_name": ADMIN_NAME, "admin_key": admin_key_b64,
                            "admin_box_key": admin_box_b64, "machine_box_key": machine_box_b64, "machine": MACHINE})
    state = "approved"
    wrong = spake2.SPAKE2_B(b"000000", entropy_f=entropy(b"caramos-business/3 test entropy B"), **ids)
    wrong.start()
    wrong_key = wrong.finish(msg_a)
    write("pair-spake2.json", {
        "code": CODE.decode("ascii"), "idA": ids["idA"].decode("ascii"), "idB": ids["idB"].decode("ascii"),
        "entropy": "SHA-256(seed + 4-byte big-endian counter) blocks, concatenated",
        "entropy_seed_employee": "caramos-business/3 test entropy A",
        "entropy_seed_admin": "caramos-business/3 test entropy B",
        "start_request": {"msg": B64(msg_a)},
        "start_answer": {"session": SESSION, "msg": B64(msg_b), "admin_name": ADMIN_NAME, "admin_key": admin_key_b64,
                         "admin_box_key": admin_box_b64},
        "K_hex": key.hex(), "k_employee_hex": k_employee.hex(), "k_admin_hex": k_admin.hex(),
        "T": transcript.decode("utf-8"),
        "finish_request": {"session": SESSION, "machine": MACHINE, "box_key": machine_box_b64,
                           "confirm": B64(mac(k_employee, transcript))},
        "finish_answer": {"machine_id": MACHINE_ID, "state": state,
                          "confirm": B64(mac(k_admin, transcript + b"\n" + MACHINE_ID.encode() + b"\n" + state.encode()))},
        "wrong_code_admin_K_hex": wrong_key.hex(),
        "wrong_code_expected_confirm": B64(mac(hkdf(wrong_key, b"pair employee"), transcript)),
    })

    # Enrolment file and /register.
    # admin_box_key: "Changes during implementation" (the agent's first request needs it for its HMAC).
    enroll_file = {"format": 1, "kind": "caramos-business-enroll", "admin_url": "http://192.168.1.5:47022",
                   "admin_name": ADMIN_NAME, "admin_key": admin_key_b64, "admin_box_key": admin_box_b64,
                   "fingerprint": fingerprint,
                   "department": "ke-toan", "department_name": "Kế toán", "token_id": TOKEN_ID, "token": B64(TOKEN),
                   "expires": "2099-01-01T00:00:00+07:00", "max_uses": 30, "hostname_prefix": None}
    write("enroll-file.json", enroll_file)
    proof_key = hkdf(TOKEN, b"enroll")
    e_bytes = canonical({"kind": "caramos-business/3 enroll", "token_id": TOKEN_ID, "time": WHEN,
                         "admin_key": admin_key_b64, "machine_box_key": machine_box_b64, "machine": MACHINE})
    enroll_state = "pending"
    write("enroll-register.json", {
        "proof_key_hex": proof_key.hex(), "E": e_bytes.decode("utf-8"),
        "request": {"token_id": TOKEN_ID, "time": WHEN, "machine": MACHINE, "box_key": machine_box_b64,
                    "proof": B64(mac(proof_key, e_bytes))},
        "answer": {"machine_id": MACHINE_ID, "state": enroll_state,
                   "confirm": B64(mac(proof_key, e_bytes + b"\n" + MACHINE_ID.encode() + b"\n" + enroll_state.encode()))},
        "admin_keeps": {"enroll-keys.json": {TOKEN_ID: proof_key.hex()}},
    })

    # HMAC of the two GET requests that need it from 0.3.
    image = (HERE.parent / "file-a003b925fd02ab1b2d86a43dfd0d3d74a904c23c1ab303d114ad0bf25bb7edc7").read_bytes()
    sha = hashlib.sha256(image).hexdigest()
    for name, path in (("mac-policy.json", "/caramos-business/v1/policy"),
                       ("mac-files.json", f"/caramos-business/v1/files/{sha}")):
        message = f"GET\n{path}\n{WHEN}\n{hashlib.sha256(b'').hexdigest()}".encode("ascii")
        write(name, {"method": "GET", "path": path, "time": WHEN, "body": "", "message": message.decode("ascii"),
                     "headers": {"X-Caramos-Machine": MACHINE_ID, "X-Caramos-Time": str(WHEN),
                                 "X-Caramos-Mac": B64(mac(mac_key, message))}})

    # A format 2 policy with the new sections.
    secrets = {"wifi": {"CongTy": "matkhau-wifi-123"}}
    sealed = B64(SEAL_NONCE + ChaCha20Poly1305(seal_key).encrypt(SEAL_NONCE, json.dumps(secrets, ensure_ascii=False)
                                                                 .encode("utf-8"), MACHINE_ID.encode("ascii")))
    shared = {"guest": True, "freeze": True, "maintenance": {"days": [7], "time": "02:00", "max_minutes": 60},
              "low_memory_ok": False}
    policy = {
        "format": 2, "serial": 21, "issued": "2026-11-23T09:00:00+07:00", "admin": ADMIN_NAME,
        "admin_box_key": admin_box_b64,
        "files": {sha: {"size": len(image), "type": "jpg"}},
        "settings": {
            "wallpaper": {"default": sha, "periods": [], "lock": False},
            "inventory": {"enabled": True},
            "screen_lock": {"idle_minutes": 10, "on_suspend": True},
            "wifi": [{"ssid": "CongTy", "security": "wpa-psk", "hidden": False}],
            "snapshots": {"schedule": "weekly", "keep": 3, "before_update": True},
        },
        "departments": {
            "ke-toan": {"name": "Kế toán", "settings": {"usb": {"storage": "block"}}},
            "phong-may": {"name": "Phòng máy", "settings": {"shared": shared, "snapshots": None}},
        },
        "members": {MACHINE_ID: "ke-toan", OTHER_MACHINE_ID: "phong-may"},
        "machines": {MACHINE_ID: {"settings": {}, "sealed": sealed}},
    }
    write("policy.json", policy)
    write("signed-policy.json", signed(sign_key, policy, "policy"))

    def effective(value: dict, machine_id: str) -> dict:
        result = dict(value["settings"])
        department = value["members"].get(machine_id)
        if department:
            result.update(value["departments"][department]["settings"])
        result.update(value["machines"].get(machine_id, {}).get("settings", {}))
        return result

    write("effective-machine.json", effective(policy, MACHINE_ID))
    write("effective-other-machine.json", effective(policy, OTHER_MACHINE_ID))

    def broken(path: list[str], new: object) -> dict:
        value = json.loads(json.dumps(policy))
        target = value
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = new
        return value

    lab = ["departments", "phong-may", "settings", "shared"]
    invalid = {
        "shared-maintenance-time": broken(lab + ["maintenance"], {"days": [7], "time": "25:00", "max_minutes": 60}),
        "shared-maintenance-days": broken(lab + ["maintenance"], {"days": [0], "time": "02:00", "max_minutes": 60}),
        "shared-max-minutes": broken(lab + ["maintenance"], {"days": [7], "time": "02:00", "max_minutes": 5}),
        "shared-freeze-type": broken(lab + ["freeze"], "yes"),
        "snapshots-schedule": broken(["settings", "snapshots", "schedule"], "hourly"),
        "snapshots-keep": broken(["settings", "snapshots", "keep"], 0),
        "snapshots-before-update": broken(["settings", "snapshots", "before_update"], "true"),
    }
    for name, value in invalid.items():
        write(f"invalid-{name}.json", value)
    # Valid for the agent, refused by the admin: a freeze without a maintenance window.
    write("admin-invalid-freeze-without-maintenance.json", broken(lab + ["maintenance"], None))

    conflict = json.loads(json.dumps(policy))
    conflict["serial"] = 22
    conflict["settings"]["folders"] = {"share": "smb://nas/nhanvien/%u", "tidy": True}
    write("policy-freeze-conflict.json", conflict)
    write("signed-policy-freeze-conflict.json", signed(sign_key, conflict, "policy"))

    # Remote help with a pre-shared key.
    psk = {"identity": "rh-0123456789abcdef", "key": bytes(range(32, 64)).hex()}
    sealed_psk = B64(PSK_NONCE + ChaCha20Poly1305(seal_key).encrypt(PSK_NONCE, compact(psk).encode("utf-8"),
                                                                    MACHINE_ID.encode("ascii")))
    command = {"seq": 61, "id": "00000000-0000-4000-8000-000000000061", "targets": {"machines": [MACHINE_ID]},
               "action": "remote_help",
               "args": {"admin_host": "192.168.1.5", "port": 5501, "mode": "control", "admin_name": ADMIN_NAME,
                        "psk": sealed_psk},
               "issued": "2026-11-23T09:00:00+07:00", "expires": "2099-01-01T00:00:00+07:00"}
    write("command-remote-help.json", signed(sign_key, command, "command", compact_text=False))
    write("remote-help-psk.json", {"nonce_hex": PSK_NONCE.hex(), "plaintext": psk,
                                   "psk_file_line": f"{psk['identity']}:{psk['key']}"})

    # Removal notices.
    def notice(machine_id: str) -> dict:
        return signed(sign_key, {"kind": "removed", "machine_id": machine_id, "admin": ADMIN_NAME,
                                 "time": "2026-11-23T10:00:00+07:00"}, "notice")

    write("removed-notice.json", notice(MACHINE_ID))
    write("removed-notice-other.json", notice(OTHER_MACHINE_ID))
    tampered = notice(OTHER_MACHINE_ID)
    tampered["notice"] = tampered["notice"].replace(OTHER_MACHINE_ID, MACHINE_ID)
    write("removed-notice-tampered.json", tampered)

    # Tickets.
    tickets = {"kind": "tickets", "machine_id": MACHINE_ID, "version": 7, "issued": "2026-11-23T11:00:00+07:00",
               "tickets": [
                   {"id": "HT-0007", "user": "lan", "created": "2026-11-23T08:10:00+07:00", "status": "working",
                    "note": "Máy in không in được",
                    "updates": [{"time": "2026-11-23T08:30:00+07:00", "status": "working",
                                 "text": "Bên mình đang xem, chiều nay xong."}]},
                   {"id": "HT-0005", "user": "minh", "created": "2026-11-20T15:00:00+07:00", "status": "done",
                    "note": "Không vào được ổ chung",
                    "updates": [{"time": "2026-11-21T09:00:00+07:00", "status": "done",
                                 "text": "Đã cấp lại mật khẩu ổ chung."}]},
                   {"id": "HT-0006", "user": "lan", "created": "2026-11-22T10:00:00+07:00", "status": "new",
                    "note": "Cài giúp phần mềm kế toán", "updates": []},
               ]}
    write("tickets.json", signed(sign_key, tickets, "tickets"))
    write("tickets-user-lan.json", {"version": 7, "tickets": [ticket for ticket in tickets["tickets"]
                                                               if ticket["user"] == "lan"]})
    write("wait-answer.json", {"serial": 21, "commands": [], "tickets": 7})

    # The origins the licence report expects for apt-cache-policy-packages.txt.
    write("apt-origins.json", {"hello": "ubuntu-main", "cowsay": "ubuntu-universe", "caramos-local-test": "local-deb",
                               "google-chrome-stable": "third-party:dl.google.com", "caramos-ota": "caramos-ppa",
                               "mint-common": "mint"})

    write("inventory-apps.json", {"apps": [
        {"id": "vlc.desktop", "name": "VLC", "version": "3.0.20-3build6", "source": "deb", "package": "vlc",
         "licence": "GPL-2+", "origin": "ubuntu-universe"},
        {"id": "google-chrome.desktop", "name": "Google Chrome", "version": "158.0.8127.36-1", "source": "deb",
         "package": "google-chrome-stable", "licence": "unknown", "origin": "third-party:dl.google.com"},
        {"id": "org.libreoffice.LibreOffice", "name": "LibreOffice", "version": "25.8.3.2", "source": "flatpak",
         "package": "org.libreoffice.LibreOffice", "licence": "MPL-2.0", "origin": "flathub"},
    ]})
    write("health.json", {"health": {
        "disk_free_pct": 48, "disk_health": "ok", "battery_health_pct": None, "updates": {"security": 0, "other": 3},
        "reboot_required": False, "firewall": "on", "caramos_version": "1.4.0", "uptime_hours": 2,
        "applied": {"shared": "ok", "snapshots": "ok"},
        "memory_mb": 7834, "encryption": "none", "screen_lock_on": True, "usb_storage": "block",
        "frozen": False, "freeze_configured": False, "last_maintenance": None, "maintenance_result": "",
        "last_snapshot": "2026-11-23T01:02:55+07:00", "snapshot_space_mb": 6780},
        "capabilities": ["wallpaper", "folders", "shares", "browser", "printers", "power", "apps", "usb",
                         "screen_lock", "firewall", "inventory", "wifi", "commands", "licence-report", "shared",
                         "snapshots", "tickets"]})

    # The files the agent writes for this policy (the GRUB script is committed as verified, not made here).
    managed = "# Managed by CaramOS Doanh nghiệp (caramos-business-agent): changes here are replaced.\n"
    write_text("expected-overlayroot.local.conf", managed + 'overlayroot="tmpfs:swap=1,recurse=0"\n')
    write_text("expected-71-caramos-business.cfg",
               managed + "# A frozen machine cannot clear GRUB's recordfail, which would show the menu for 30 s at "
               "every boot.\nGRUB_RECORDFAIL_TIMEOUT=0\n")
    write_text("expected-lightdm-guest.conf", managed + "[Seat:*]\nallow-guest=true\ngreeter-allow-guest=true\n")
    timeshift = {
        "backup_device_uuid": ROOT_UUID, "parent_device_uuid": "", "do_first_run": "false", "btrfs_mode": "false",
        "include_btrfs_home": "false", "stop_cron_emails": "true",
        "schedule_monthly": "false", "schedule_weekly": "true", "schedule_daily": "false", "schedule_hourly": "false",
        "schedule_boot": "false",
        "count_monthly": "2", "count_weekly": "3", "count_daily": "5", "count_hourly": "6", "count_boot": "5",
        "snapshot_size": "0", "snapshot_count": "0", "exclude": ["/home/**", "/root/**"], "exclude-apps": [],
    }
    write_text("expected-timeshift.json", json.dumps(timeshift, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()

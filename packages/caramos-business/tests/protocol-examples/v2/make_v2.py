#!/usr/bin/python3
"""Makes the version 0.2 test vectors of PROTOCOL.md part 2 (run from this folder). The keys are fixed test keys:
never use them for anything real. Both the Python and the Rust tests read the files this writes."""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
import json
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.x509.oid import NameOID

HERE = Path(__file__).resolve().parent
B64 = lambda data: base64.b64encode(data).decode("ascii")
RAW = serialization.Encoding.Raw, serialization.PublicFormat.Raw

ADMIN_SIGN_SEED = bytes(range(0, 32))       # the same key as part 1's test-key.json
ADMIN_BOX_SEED = bytes(range(32, 64))
MACHINE_BOX_SEED = bytes(range(64, 96))
MACHINE_ID = "7f0c2e4a-1b3d-4c5e-8f90-a1b2c3d4e5f6"
OTHER_MACHINE_ID = "0d9e8f7a-6b5c-4d3e-9f21-0a1b2c3d4e5f"
NONCE = bytes(range(100, 112))              # fixed only for the vectors; real seals use a random nonce


def derive(secret: bytes, info: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=b"caramos-business/2", info=info).derive(secret)


def write(name: str, value: object) -> None:
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def signed(key: Ed25519PrivateKey, value: dict, field: str) -> dict:
    text = json.dumps(value, ensure_ascii=False, indent=1)
    return {field: text, "signature": B64(key.sign(text.encode("utf-8")))}


def main() -> None:
    sign_key = Ed25519PrivateKey.from_private_bytes(ADMIN_SIGN_SEED)
    admin_box = X25519PrivateKey.from_private_bytes(ADMIN_BOX_SEED)
    machine_box = X25519PrivateKey.from_private_bytes(MACHINE_BOX_SEED)
    admin_box_pub = admin_box.public_key().public_bytes(*RAW)
    machine_box_pub = machine_box.public_key().public_bytes(*RAW)
    secret_admin_side = admin_box.exchange(machine_box.public_key())
    secret_machine_side = machine_box.exchange(admin_box.public_key())
    assert secret_admin_side == secret_machine_side
    mac_key, seal_key = derive(secret_admin_side, b"mac"), derive(secret_admin_side, b"seal")
    write("keys.json", {
        "admin_sign_seed": B64(ADMIN_SIGN_SEED),
        "admin_sign_public": B64(sign_key.public_key().public_bytes(*RAW)),
        "admin_box_seed": B64(ADMIN_BOX_SEED), "admin_box_public": B64(admin_box_pub),
        "machine_box_seed": B64(MACHINE_BOX_SEED), "machine_box_public": B64(machine_box_pub),
        "machine_id": MACHINE_ID, "shared_secret_hex": secret_admin_side.hex(),
        "mac_key_hex": mac_key.hex(), "seal_key_hex": seal_key.hex(),
    })

    # A request MAC.
    body = json.dumps({"machine": {"name": "kt-01"}, "users": []}, separators=(",", ":")).encode("utf-8")
    path, when = "/caramos-business/v1/checkin", 1795200000
    message = f"POST\n{path}\n{when}\n{hashlib.sha256(body).hexdigest()}".encode("ascii")
    write("mac.json", {"method": "POST", "path": path, "time": when, "body": body.decode("utf-8"),
                       "message": message.decode("ascii"),
                       "mac": B64(hmac.new(mac_key, message, hashlib.sha256).digest())})
    wait_path = "/caramos-business/v1/wait?after=4&serial=12"
    wait_message = f"GET\n{wait_path}\n{when}\n{hashlib.sha256(b'').hexdigest()}".encode("ascii")
    write("mac-wait.json", {"method": "GET", "path": wait_path, "time": when, "body": "",
                            "message": wait_message.decode("ascii"),
                            "mac": B64(hmac.new(mac_key, wait_message, hashlib.sha256).digest())})

    # Secrets sealed for the machine.
    secrets = {"wifi": {"CongTy": "matkhau-wifi-123"}}
    plaintext = json.dumps(secrets, ensure_ascii=False).encode("utf-8")
    sealed = B64(NONCE + ChaCha20Poly1305(seal_key).encrypt(NONCE, plaintext, MACHINE_ID.encode("ascii")))
    write("sealed.json", {"machine_id": MACHINE_ID, "nonce_hex": NONCE.hex(), "plaintext": secrets, "sealed": sealed})

    # The remote help certificate (self-signed, EC P-256, made once; regenerating changes it, which is fine).
    cert_file = HERE / "remote-help-cert.pem"
    if not cert_file.exists():
        from cryptography.hazmat.primitives.asymmetric import ec
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "caramos-business remote help (test)")])
        now = datetime.datetime(2026, 11, 21, tzinfo=datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(1).not_valid_before(now).not_valid_after(now + datetime.timedelta(days=3650))
                .sign(key, hashes.SHA256()))
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    cert_pem = cert_file.read_text(encoding="ascii")

    # A format 2 policy with a department and a machine override.
    image = (HERE.parent / "file-a003b925fd02ab1b2d86a43dfd0d3d74a904c23c1ab303d114ad0bf25bb7edc7").read_bytes()
    sha = hashlib.sha256(image).hexdigest()
    policy = {
        "format": 2, "serial": 12, "issued": "2026-11-21T09:00:00+07:00", "admin": "máy-quản-lý",
        "admin_box_key": B64(admin_box_pub), "remote_help_cert": cert_pem,
        "files": {sha: {"size": len(image), "type": "jpg"}},
        "settings": {
            "wallpaper": {"default": sha, "periods": [], "lock": False},
            "browser": {"homepage": "https://amis.misa.vn", "bookmarks": [{"name": "Thuế điện tử", "url": "https://thuedientu.gdt.gov.vn"}],
                        "block": ["facebook.com", "tiktok.com", "youtube.com"],
                        "block_hours": {"days": [1, 2, 3, 4, 5, 6], "ranges": [["08:00", "12:00"], ["13:30", "17:30"]]},
                        "safe_search": True},
            "printers": [{"name": "Máy in tầng 2", "uri": "ipp://192.168.1.50/ipp/print", "location": "Tầng 2", "default": True}],
            "power": {"shutdown": {"days": [1, 2, 3, 4, 5, 6], "time": "18:30", "warn_minutes": 10, "postpone_minutes": 30,
                                   "max_postpones": 2, "laptops": "skip"},
                      "wake": {"days": [1, 2, 3, 4, 5, 6], "time": "07:45"}},
            "usb": {"storage": "read-only"},
            "screen_lock": {"idle_minutes": 10, "on_suspend": True},
            "wifi": [{"ssid": "CongTy", "security": "wpa-psk", "hidden": False}],
        },
        "departments": {"ke-toan": {"name": "Kế toán", "settings": {
            "shares": [{"name": "Kế toán", "url": "smb://nas/ketoan"}],
            "usb": {"storage": "block"},
            "apps": {"required": ["libreoffice"], "forbidden": ["discord"]}}},
            "kinh-doanh": {"name": "Kinh doanh", "settings": {"browser": None}}},
        "members": {MACHINE_ID: "ke-toan", OTHER_MACHINE_ID: "kinh-doanh"},
        "machines": {MACHINE_ID: {"settings": {"screen_lock": {"idle_minutes": 5, "on_suspend": True}}, "sealed": sealed}},
    }
    write("policy.json", policy)
    write("signed-policy.json", signed(sign_key, policy, "policy"))
    effective = dict(policy["settings"])
    effective.update(policy["departments"]["ke-toan"]["settings"])
    effective.update(policy["machines"][MACHINE_ID]["settings"])
    write("effective-machine.json", effective)
    other = dict(policy["settings"])
    other.update(policy["departments"]["kinh-doanh"]["settings"])
    write("effective-other-machine.json", other)

    # Signed commands.
    def command(seq: int, targets: dict, action: str, args: dict, expires: str = "2099-01-01T00:00:00+07:00") -> dict:
        return {"seq": seq, "id": f"00000000-0000-4000-8000-{seq:012d}", "targets": targets, "action": action,
                "args": args, "issued": "2026-11-21T14:00:00+07:00", "expires": expires}

    message_cmd = command(41, {"machines": [MACHINE_ID]}, "message", {"title": "Họp 15h", "body": "Phòng họp tầng 3.", "ack": True})
    write("command-message.json", signed(sign_key, message_cmd, "command"))
    write("command-department.json", signed(sign_key, command(42, {"departments": ["ke-toan"]}, "lock", {}), "command"))
    write("command-other-department.json", signed(sign_key, command(43, {"departments": ["kinh-doanh"]}, "lock", {}), "command"))
    write("command-all.json", signed(sign_key, command(44, {"all": True}, "sync", {}), "command"))
    write("command-expired.json", signed(sign_key, command(45, {"all": True}, "lock", {}, expires="2026-11-21T14:10:00+07:00"), "command"))
    tampered = signed(sign_key, message_cmd, "command")
    tampered["command"] = tampered["command"].replace("Họp 15h", "Họp 16h")
    write("command-tampered.json", tampered)
    write("command-bad-action.json", signed(sign_key, command(46, {"all": True}, "shell", {"run": "id"}), "command"))
    write("command-bad-args.json", signed(sign_key, command(47, {"all": True}, "usb_unlock", {"minutes": 9999}), "command"))

    # Invalid format 2 policies: each must be refused (the admin refuses to sign them, the agent to apply them).
    def broken(**changes: object) -> dict:
        value = json.loads(json.dumps(policy))
        for dotted, new in changes.items():
            target = value
            parts = dotted.split("__")
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = new
        return value

    invalid = {
        "format-1": broken(format=1),
        # One error each: the members keep pointing at departments that exist.
        "department-id": broken(departments=dict(policy["departments"], **{"Kế Toán!": {"name": "x", "settings": {}}})),
        "member-unknown-department": broken(members={MACHINE_ID: "khong-co"}),
        "printer-uri": broken(settings__printers=[{"name": "x", "uri": "socket://192.168.1.50:9100", "location": "", "default": False}]),
        "printer-two-defaults": broken(settings__printers=[
            {"name": "a", "uri": "ipp://10.0.0.1/ipp/print", "location": "", "default": True},
            {"name": "b", "uri": "ipp://10.0.0.2/ipp/print", "location": "", "default": True}]),
        "browser-domain": broken(settings__browser__block=["https://facebook.com/x"]),
        "browser-hours-midnight": broken(settings__browser__block_hours={"days": [1], "ranges": [["22:00", "02:00"]]}),
        "power-warn": broken(settings__power__shutdown__warn_minutes=90),
        "usb-value": broken(settings__usb={"storage": "maybe"}),
        "apps-both": broken(settings__apps={"required": ["vlc"], "forbidden": ["vlc"]}),
        "wifi-ssid": broken(settings__wifi=[{"ssid": "x" * 40, "security": "wpa-psk", "hidden": False}]),
        "screen-lock": broken(settings__screen_lock={"idle_minutes": 0, "on_suspend": True}),
        "share-percent-u": broken(**{"departments__ke-toan__settings__shares": [{"name": "x", "url": "smb://nas/%u"}]}),
    }
    for name, value in invalid.items():
        write(f"invalid-{name}.json", value)


if __name__ == "__main__":
    main()

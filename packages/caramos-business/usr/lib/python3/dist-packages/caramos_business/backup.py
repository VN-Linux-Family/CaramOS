"""The admin machine's backup (PROTOCOL.md part 2, "Admin backup and restore").

A backup holds the admin's keys and certificate and all of /var/lib/caramos-business/admin, so that another machine
can take over: the employee machines find it by discovery, since the pinned key is the same.

Format: b"CBKP1", a 16-byte salt, a 12-byte nonce, then the tar encrypted with AES-256-GCM under a key that scrypt
(n=2^15, r=8, p=1) makes from the passphrase. No additional data: the header is checked by the key and the nonce."""

from __future__ import annotations

import io
import os
import tarfile
from pathlib import Path, PurePosixPath

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from .i18n import _

MAGIC = b"CBKP1"
SALT_SIZE = 16
NONCE_SIZE = 12
MIN_PASSPHRASE = 8
MAX_BACKUP = 2 * 1024 ** 3
# 0.2's admin-tls.key and admin-tls.pem are gone (remote help uses a key per session from 0.3): an old backup's copies
# are skipped when it is restored.
KEY_FILES = ("admin-key.pem", "admin-box.key")
SECRET_FILES = {"admin-key.pem", "admin-box.key"}
ETC_PREFIX = "etc/caramos-business"
STATE_PREFIX = "var/lib/caramos-business/admin"


class BackupError(Exception):
    """A backup that cannot be made or opened; the text is for the window."""


def _key(passphrase: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode("utf-8"))


def make_tar(etc: Path, state: Path) -> bytes:
    """The tar of the keys and the state, with neutral owners."""

    buffer = io.BytesIO()

    def neutral(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
        if not (info.isfile() or info.isdir()):
            return None  # no links or devices in a backup
        info.uid = info.gid = 0
        info.uname = info.gname = "root"
        return info

    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name in KEY_FILES:
            path = etc / name
            if path.is_file():
                tar.add(path, arcname=f"{ETC_PREFIX}/{name}", filter=neutral)
        if state.is_dir():
            tar.add(state, arcname=STATE_PREFIX, filter=neutral)
    return buffer.getvalue()


def encrypt(data: bytes, passphrase: str, salt: bytes | None = None, nonce: bytes | None = None) -> bytes:
    if len(passphrase) < MIN_PASSPHRASE:
        raise BackupError(_("The passphrase needs at least 8 characters."))
    salt = salt or os.urandom(SALT_SIZE)
    nonce = nonce or os.urandom(NONCE_SIZE)
    return MAGIC + salt + nonce + AESGCM(_key(passphrase, salt)).encrypt(nonce, data, None)


def decrypt(blob: bytes, passphrase: str) -> bytes:
    header = len(MAGIC) + SALT_SIZE + NONCE_SIZE
    if not blob.startswith(MAGIC) or len(blob) < header + 16:
        raise BackupError(_("This is not a CaramOS Business backup."))
    salt = blob[len(MAGIC):len(MAGIC) + SALT_SIZE]
    nonce = blob[len(MAGIC) + SALT_SIZE:header]
    try:
        return AESGCM(_key(passphrase, salt)).decrypt(nonce, blob[header:], None)
    except InvalidTag as exc:
        raise BackupError(_("The passphrase is wrong, or the backup is damaged.")) from exc


def make_backup(passphrase: str, etc: Path, state: Path) -> bytes:
    if not (etc / "admin-key.pem").is_file():
        raise BackupError(_("This machine has no admin key to back up."))
    return encrypt(make_tar(etc, state), passphrase)


def _target(name: str, etc: Path, state: Path) -> tuple[Path, int] | None:
    """Where a member of the tar goes, and its mode; None for anything a backup does not hold."""

    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return None
    text = str(path)
    if text.startswith(ETC_PREFIX + "/") and path.name in KEY_FILES and len(path.parts) == 3:
        return etc / path.name, 0o600 if path.name in SECRET_FILES else 0o644
    if text == STATE_PREFIX:
        return state, 0o755
    if text.startswith(STATE_PREFIX + "/"):
        relative = PurePosixPath(*path.parts[len(PurePosixPath(STATE_PREFIX).parts):])
        mode = 0o600 if relative.name in ("secrets.json", "enroll-keys.json", ".lock") else 0o644
        return state.joinpath(*relative.parts), mode
    return None


def restore(blob: bytes, passphrase: str, etc: Path, state: Path) -> list[str]:
    """Writes a backup's files back (keys 0600); the names of the files written. Nothing is written unless the
    whole backup opens and holds the admin's signing key."""

    data = decrypt(blob, passphrase)
    try:
        tar = tarfile.open(fileobj=io.BytesIO(data), mode="r")
        members = tar.getmembers()
    except tarfile.TarError as exc:
        raise BackupError(_("The backup is damaged.")) from exc
    names = {member.name for member in members}
    if f"{ETC_PREFIX}/admin-key.pem" not in names:
        raise BackupError(_("The backup has no admin key."))
    written = []
    with tar:
        for member in members:
            target = _target(member.name, etc, state)
            if target is None or not (member.isfile() or member.isdir()):
                continue
            path, mode = target
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
                os.chmod(path, 0o755 if path != state else 0o750)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = tar.extractfile(member)
            if handle is None:
                continue
            staging = path.with_name(f".{path.name}.restore")
            with open(os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode), "wb") as out:
                out.write(handle.read())
            os.chmod(staging, mode)
            os.replace(staging, path)
            written.append(member.name)
    return written

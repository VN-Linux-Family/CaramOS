"""Return system files that are owned by a regular login account to root.

ISO builds before the overlay fix copied ``config/includes.chroot`` with ``cp -a``, which kept the
build machine's uid/gid (1001 for most releases), and the Bibata cursor theme was unpacked from a
tarball owned by uid 1000. On an installed machine those ids belong to real login accounts, so the
account that owns ``/etc``, ``/usr/bin`` or ``/usr/local/bin`` can replace files that root reads or
runs. This migration hands every such item back to ``root:root`` and drops the group/other write
bits it inherited.

Scope:

- ``/etc`` and ``/usr`` are scanned recursively without following symlinks or leaving their
  filesystem.
- Only items whose *owner* is a regular account (uid 1000-60000) are changed. Items owned by root
  or a system account are left alone, including root-owned items with a regular group, which an
  administrator may have set on purpose.
- ``/usr/local`` belongs to the machine's administrator (FHS): only its standard directories, which
  the ISO created with the wrong owner, are checked, never the content inside them.
"""

from __future__ import annotations

import json
import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, NamedTuple

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Return system files owned by a regular user account to root"

MIGRATION_ID = "20261003210000_fix_system_file_ownership"
SCAN_ROOTS = (Path("/etc"), Path("/usr"))
LOCAL_ROOT = Path("/usr/local")
LOCAL_SKELETON = (
    LOCAL_ROOT,
    *(LOCAL_ROOT / name for name in ("bin", "etc", "games", "include", "lib", "man", "sbin", "share", "src")),
    LOCAL_ROOT / "share/ca-certificates",
    LOCAL_ROOT / "share/man",
)
BACKUP_DIR = Path("/var/lib/caramos-ota/backups") / MIGRATION_ID
# Debian/Ubuntu UID_MIN/UID_MAX for login accounts (login.defs defaults).
REGULAR_ID_MIN = 1000
REGULAR_ID_MAX = 60000
LOG_SAMPLE = 20
WRITE_BITS = stat.S_IWGRP | stat.S_IWOTH
SETID_BITS = stat.S_ISUID | stat.S_ISGID

# Indirection points so tests can simulate ownership and chown without root.
_lstat = os.lstat
_fstat = os.fstat
_fchown_root = lambda fd: os.fchown(fd, 0, 0)  # noqa: E731
_lchown_root = lambda path: os.chown(path, 0, 0, follow_symlinks=False)  # noqa: E731


# NamedTuple, not @dataclass: the runner loads migrations without registering them in sys.modules.
class OwnershipFix(NamedTuple):
    path: Path
    uid: int
    gid: int
    mode: int
    device: int
    inode: int

    def record(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "uid": self.uid,
            "gid": self.gid,
            "mode": oct(stat.S_IMODE(self.mode)),
            "type": stat.filemode(self.mode)[0],
        }


def _is_regular_account(owner_id: int) -> bool:
    return REGULAR_ID_MIN <= owner_id <= REGULAR_ID_MAX


def _fix_for(path: Path, info: os.stat_result) -> OwnershipFix | None:
    if not _is_regular_account(info.st_uid):
        return None
    return OwnershipFix(path, info.st_uid, info.st_gid, info.st_mode, info.st_dev, info.st_ino)


def _walk(root: Path, skip: Path) -> Iterator[tuple[Path, os.stat_result]]:
    """Yield root and everything below it without entering other mounts or following symlinks."""

    try:
        root_info = _lstat(root)
    except OSError:
        return
    yield root, root_info
    if not stat.S_ISDIR(root_info.st_mode):
        return
    device = root_info.st_dev
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            path = directory / name
            if path == skip:
                continue
            try:
                info = _lstat(path)
            except OSError:
                continue
            if stat.S_ISDIR(info.st_mode):
                # A directory on another device is a mount point: neither touch nor enter it. Only
                # directories are compared, because overlayfs (live session) reports the lower
                # layer's device for files that were never copied up.
                if info.st_dev != device:
                    continue
                pending.append(path)
            yield path, info


def find_fixes(
    scan_roots: tuple[Path, ...] = SCAN_ROOTS,
    local_root: Path = LOCAL_ROOT,
    local_skeleton: tuple[Path, ...] = LOCAL_SKELETON,
) -> list[OwnershipFix]:
    """Return items to hand back to root, parents before children."""

    fixes: list[OwnershipFix] = []
    for root in scan_roots:
        for path, info in _walk(root, skip=local_root):
            fix = _fix_for(path, info)
            if fix:
                fixes.append(fix)
    for path in local_skeleton:
        try:
            info = _lstat(path)
        except OSError:
            continue
        fix = _fix_for(path, info) if stat.S_ISDIR(info.st_mode) else None
        if fix:
            fixes.append(fix)
    # Locking parents first stops their old owner from swapping entries while children are fixed.
    return sorted(fixes, key=lambda fix: (len(fix.path.parts), str(fix.path)))


def _new_mode(mode: int) -> int:
    new_mode = stat.S_IMODE(mode) & ~WRITE_BITS
    if stat.S_ISREG(mode):
        # chown clears set-id bits; restoring them would make a file its old owner wrote set-id root.
        new_mode &= ~SETID_BITS
    return new_mode


def apply_fix(fix: OwnershipFix) -> str | None:
    """Hand one item to root:root. Return a reason when it was skipped."""

    if not (stat.S_ISREG(fix.mode) or stat.S_ISDIR(fix.mode)):
        # Symlinks, FIFOs and sockets: only the owner matters and lchown never follows a link.
        _lchown_root(fix.path)
        return None
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        fd = os.open(fix.path, flags)
    except OSError as exc:
        return f"cannot open: {exc.strerror}"
    try:
        info = _fstat(fd)
        # Only ever touch the inode that was scanned, even if the path was swapped meanwhile.
        if (info.st_dev, info.st_ino) != (fix.device, fix.inode):
            return "changed since scan"
        _fchown_root(fd)
        os.fchmod(fd, _new_mode(info.st_mode))
    finally:
        os.close(fd)
    return None


def _write_backup(fixes: list[OwnershipFix]) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = BACKUP_DIR / f"ownership-before-{stamp}.json"
    payload = {"schema": 1, "migration": MIGRATION_ID, "items": [fix.record() for fix in fixes]}
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return backup


def run(context: MigrationContext) -> None:
    started = time.monotonic()
    fixes = find_fixes(SCAN_ROOTS, LOCAL_ROOT, LOCAL_SKELETON)
    context.log(f"scanned {', '.join(map(str, SCAN_ROOTS))} in {time.monotonic() - started:.1f}s")
    if not fixes:
        context.log("no system path is owned by a regular user account; nothing to change")
        return

    context.log(f"{len(fixes)} system path(s) owned by a regular user account will be returned to root:root")
    for fix in fixes[:LOG_SAMPLE]:
        context.log(f"  {fix.path} (uid {fix.uid}, gid {fix.gid}, mode {oct(stat.S_IMODE(fix.mode))})")
    if len(fixes) > LOG_SAMPLE:
        context.log(f"  ... and {len(fixes) - LOG_SAMPLE} more")
    if context.dry_run:
        return

    backup = _write_backup(fixes)
    context.log(f"previous owners and modes saved to {backup}")
    skipped = 0
    for fix in fixes:
        try:
            reason = apply_fix(fix)
        except OSError as exc:
            reason = exc.strerror or str(exc)
        if reason:
            skipped += 1
            context.log(f"warning: left {fix.path} unchanged: {reason}")
    # A path that cannot be fixed (immutable, vanished) must not block later migrations forever.
    context.log(f"returned {len(fixes) - skipped} path(s) to root:root; {skipped} skipped")

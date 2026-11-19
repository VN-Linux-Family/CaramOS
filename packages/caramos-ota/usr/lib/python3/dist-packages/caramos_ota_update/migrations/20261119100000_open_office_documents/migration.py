"""Office documents and .zip files open in an app that opens them, not in the folder they are in.

The package does most of it: /etc/xdg/mimeapps.list makes the App Center's office suites the default apps of Word,
Excel, PowerPoint and OpenDocument files, and caramos-open-document the last one, which suggests installing a suite
when none is installed. That works at once, in the sessions that are open too.

The ISO's /etc/skel/.config/mimeapps.list, which every user's ~/.config/mimeapps.list was copied from, also said
that .zip and .tar files open with Nemo. Nemo only shows the folder a file is in, so a .zip did not open at all. This
removes those two lines from /etc/skel and from each user's copy, when they are still the ISO's, so archives open in
the archive manager. Every other line is kept, and a default the user chose for archives stays.

The files belong to the users: a ~/.config or a mimeapps.list that is a symbolic link, or that is not the user's,
is left alone, and the new file replaces the old one in a single rename, with the same owner and mode.
"""

from __future__ import annotations

import os
import pwd
import stat
from pathlib import Path

from caramos_ota_update.context import MigrationContext

DESCRIPTION = "Office documents and archives open in an app that opens them"

SKEL = Path("/etc/skel")
CONFIG = ".config"
NAME = "mimeapps.list"
GROUP = "[Default Applications]"
# What the ISO wrote for archives (config/includes.chroot/etc/skel/.config/mimeapps.list until 1.4.0).
STALE = frozenset({"application/zip=nemo.desktop", "application/x-tar=nemo.desktop"})


def cleaned(text: str) -> str | None:
    """`text` without the ISO's Nemo lines for archives, or None when it has none of them."""

    kept = []
    group = None
    removed = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            group = stripped
        elif group == GROUP and stripped.rstrip(";") in STALE:
            removed = True
            continue
        kept.append(line)
    return "".join(kept) if removed else None


def _desktop_users() -> list[pwd.struct_passwd]:
    users = [entry for entry in pwd.getpwall()
             if 1000 <= entry.pw_uid < 60000 and not entry.pw_shell.endswith(("/nologin", "/false"))]
    return sorted(users, key=lambda entry: entry.pw_uid)


def fix(home: Path, uid: int, dry_run: bool = False) -> str:
    """Remove the stale lines from <home>/.config/mimeapps.list, a file of `uid`. Says what happened."""

    target = home / CONFIG / NAME
    try:
        config = os.open(home / CONFIG, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return f"no {target}"
    except OSError as exc:
        return f"skip {target}: {exc.strerror} (a symbolic link?)"
    try:
        if os.fstat(config).st_uid != uid:
            return f"skip {target}: {home / CONFIG} is not its user's"
        try:
            handle = os.open(NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=config)
        except FileNotFoundError:
            return f"no {target}"
        except OSError as exc:
            return f"skip {target}: {exc.strerror} (a symbolic link?)"
        with os.fdopen(handle, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != uid:
                return f"skip {target}: not a file of its user"
            raw = source.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return f"skip {target}: not UTF-8"
        new = cleaned(text)
        if new is None:
            return f"{target}: no Nemo default for archives"
        if dry_run:
            return f"would remove the Nemo default for archives from {target}"
        temporary = f".{NAME}.caramos-ota-{os.getpid()}"
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=config)
        try:
            with os.fdopen(handle, "wb") as output:
                output.write(new.encode("utf-8"))
                output.flush()
                os.fsync(output.fileno())
                os.fchown(output.fileno(), info.st_uid, info.st_gid)
                os.fchmod(output.fileno(), stat.S_IMODE(info.st_mode))
            os.rename(temporary, NAME, src_dir_fd=config, dst_dir_fd=config)
        except BaseException:
            try:
                os.unlink(temporary, dir_fd=config)
            except OSError:
                pass
            raise
        return f"removed the Nemo default for archives from {target}"
    finally:
        os.close(config)


def run(context: MigrationContext) -> None:
    targets = [(SKEL, 0)] + [(Path(entry.pw_dir), entry.pw_uid) for entry in _desktop_users()]
    for home, uid in targets:
        try:
            context.log(fix(home, uid, dry_run=context.dry_run))
        except OSError as exc:
            context.log(f"could not change {home / CONFIG / NAME}: {exc}")

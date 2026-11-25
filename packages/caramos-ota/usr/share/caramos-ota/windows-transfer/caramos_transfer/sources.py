"""Where the Windows data is: a Windows partition of this computer, a folder (an old disk on a USB adapter), or a
shared folder of the old PC; then the Windows accounts in it and what each one holds.

A Windows partition is mounted read-only through udisks (the session's password window asks when the disk is an
internal one) and unmounted again at the end; one the desktop has mounted already is used as it is. Nothing here
ever writes to the source. A partition BitLocker locks is listed as locked (Partition.locked): it cannot be read until
Windows decrypts it, and up to 1.5.1 the window left it out without a word. One that Files (Nemo) unlocked with its
recovery key has its NTFS file system under it, which is listed as usual.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from caramos_ota.i18n import _

# Folders of Users\ that are not accounts.
NOT_ACCOUNTS = {"all users", "default", "default user", "defaultuser0", "public", "wdagutilityaccount", "desktop.ini",
                "temp", "administrator.default"}
# Windows XP: C:\Documents and Settings\<user>\My Documents\My Pictures…
XP_FOLDERS = {"Desktop": ("Desktop",), "Documents": ("My Documents",), "Pictures": ("My Documents", "My Pictures"),
              "Music": ("My Documents", "My Music"), "Videos": ("My Documents", "My Videos"), "Downloads": ()}


# lsblk's FSTYPE of the file systems that hold Windows, and of a partition BitLocker encrypts.
NTFS = ("ntfs", "ntfs3")
BITLOCKER = "bitlocker"


@dataclass
class Partition:
    device: str               # /dev/sda3
    label: str                # "Windows", "OS", "" …
    size: int                 # bytes
    mountpoint: str | None    # where it is mounted now
    removable: bool
    locked: bool = False      # encrypted by BitLocker: unreadable until Windows turns BitLocker off

    def title(self) -> str:
        if self.label:
            return _("Windows disk “{label}”").format(label=self.label)
        return _("Windows disk {device}").format(device=self.device)


def parse_lsblk(text: str) -> list[Partition]:
    """NTFS partitions, and the partitions BitLocker locks, in `lsblk -J -b -o PATH,FSTYPE,LABEL,SIZE,MOUNTPOINTS,
    HOTPLUG,RM` output."""

    found: list[Partition] = []

    def walk(devices: list, removable: bool = False) -> None:
        for device in devices or []:
            hotplug = bool(device.get("hotplug")) or bool(device.get("rm")) or removable
            fstype = (device.get("fstype") or "").lower()
            children = device.get("children") or []
            if fstype in NTFS:
                points = [point for point in device.get("mountpoints") or [] if point]
                found.append(Partition(device.get("path") or "", device.get("label") or "",
                                       int(device.get("size") or 0), points[0] if points else None, hotplug))
            elif fstype == BITLOCKER and not any((child.get("fstype") or "").lower() in NTFS for child in children):
                found.append(Partition(device.get("path") or "", device.get("label") or "",
                                       int(device.get("size") or 0), None, hotplug, locked=True))
            walk(children, hotplug)

    try:
        walk(json.loads(text).get("blockdevices") or [])
    except (ValueError, AttributeError, TypeError):
        return []
    # Small NTFS partitions are Windows' recovery and reserved partitions, not where the accounts are.
    return [partition for partition in found if partition.size >= 2 * 1024 ** 3]


def windows_partitions() -> list[Partition]:
    try:
        result = subprocess.run(["lsblk", "-J", "-b", "-o", "NAME,PATH,FSTYPE,LABEL,SIZE,MOUNTPOINTS,HOTPLUG,RM"],
                                capture_output=True, text=True, check=False, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    return parse_lsblk(result.stdout) if result.returncode == 0 else []


class MountError(Exception):
    """The source could not be opened; the message is for the user."""


def mount_read_only(partition: Partition) -> tuple[Path, bool]:
    """(where it is mounted, True when this mounted it). A partition mounted already is used as it is."""

    if partition.mountpoint:
        return Path(partition.mountpoint), False
    try:
        result = subprocess.run(["udisksctl", "mount", "--block-device", partition.device, "--options", "ro"],
                                capture_output=True, text=True, check=False, timeout=120)
    except (OSError, subprocess.SubprocessError) as error:
        raise MountError(_("The Windows disk could not be opened.")) from error
    match = re.search(r" at (/\S.*?)\.?\s*$", result.stdout.strip())
    if result.returncode != 0 or not match:
        detail = (result.stderr or result.stdout).strip()
        if "NotAuthorized" in detail or "dismissed" in detail.lower():
            raise MountError(_("The Windows disk was not opened: the password was not entered."))
        if "hibernat" in detail.lower() or "unclean" in detail.lower() or "dirty" in detail.lower():
            raise MountError(_("Windows did not shut down fully (Fast Startup or hibernation). Start Windows, "
                               "choose Shut down while holding Shift, then try again."))
        raise MountError(_("The Windows disk could not be opened.") + (f" ({detail[:160]})" if detail else ""))
    return Path(match.group(1)), True


def unmount(partition: Partition) -> None:
    subprocess.run(["udisksctl", "unmount", "--block-device", partition.device], capture_output=True, check=False,
                   timeout=60)


def smb_uri(address: str) -> str | None:
    """smb://host/share for "\\\\HOST\\share", "HOST\\share", "smb://host/share" or "192.168.1.5/Users"."""

    text = address.strip().replace("\\", "/")
    if text.lower().startswith("smb:"):
        text = text[4:]
    text = text.strip("/")
    parts = [part for part in text.split("/") if part]
    if len(parts) < 2 or not re.fullmatch(r"[\w.-]+", parts[0]):
        return None
    return "smb://" + "/".join(parts)


# ---- Accounts ------------------------------------------------------------------------------------------------

@dataclass
class Profile:
    name: str
    path: Path
    folders: dict[str, Path]           # "Desktop", "Documents"… -> where they are in this account
    last_used: datetime | None = None

    @property
    def appdata(self) -> Path:
        return self.path / "AppData"


def _child(folder: Path, name: str) -> Path | None:
    """folder/name, matching the name without case (NTFS through Linux keeps the case it was written with)."""

    direct = folder / name
    if direct.exists():
        return direct
    try:
        for entry in os.scandir(folder):
            if entry.name.lower() == name.lower():
                return Path(entry.path)
    except OSError:
        return None
    return None


def _walk(folder: Path, *names: str) -> Path | None:
    current: Path | None = folder
    for name in names:
        if current is None:
            return None
        current = _child(current, name)
    return current


def _last_used(path: Path) -> datetime | None:
    for name in ("NTUSER.DAT", "ntuser.dat"):
        try:
            return datetime.fromtimestamp((path / name).stat().st_mtime)
        except OSError:
            continue
    return None


def is_profile(path: Path) -> bool:
    return any(_child(path, name) is not None for name in ("NTUSER.DAT", "Desktop", "Documents", "My Documents"))


def profile_at(path: Path, xp: bool = False) -> Profile:
    folders: dict[str, Path] = {}
    if xp:
        for key, names in XP_FOLDERS.items():
            found = _walk(path, *names) if names else None
            if found is not None and found.is_dir():
                folders[key] = found
    else:
        for key in ("Desktop", "Documents", "Pictures", "Downloads", "Music", "Videos"):
            found = _child(path, key)
            if found is not None and found.is_dir() and not found.is_symlink():
                folders[key] = found
    return Profile(path.name, path, folders, _last_used(path))


def find_profiles(root: Path) -> list[Profile]:
    """The accounts under a drive root (Users\\*, or Documents and Settings\\* of Windows XP), a Users folder, or
    the account folder itself."""

    users = _child(root, "Users")
    xp = False
    if users is None:
        users = _child(root, "Documents and Settings")
        xp = users is not None
    candidates: list[Path] = []
    if users is not None and users.is_dir():
        base = users
    elif is_profile(root):
        return [profile_at(root)]
    else:
        base = root
    try:
        for entry in sorted(os.scandir(base), key=lambda item: item.name.lower()):
            if entry.is_symlink() or not entry.is_dir() or entry.name.lower() in NOT_ACCOUNTS:
                continue
            if is_profile(Path(entry.path)):
                candidates.append(Path(entry.path))
    except OSError as error:
        raise MountError(_("This folder cannot be read.")) from error
    profiles = [profile_at(path, xp) for path in candidates]
    return [profile for profile in profiles if profile.folders]


# ---- What an account holds -----------------------------------------------------------------------------------

DESKTOP, DOCUMENTS, PICTURES = "Desktop", "Documents", "Pictures"
DOWNLOADS, MUSIC, VIDEOS = "Downloads", "Music", "Videos"
ZALO, BOOKMARKS, OUTLOOK, FONTS = "zalo", "bookmarks", "outlook", "fonts"
FOLDER_ITEMS = (DESKTOP, DOCUMENTS, PICTURES, DOWNLOADS, MUSIC, VIDEOS)
ZALO_FOLDER = "Zalo Received Files"
# Chromium browsers keep their bookmarks in "<User Data>/<profile>/Bookmarks".
BROWSERS = (("Google Chrome", ("AppData", "Local", "Google", "Chrome", "User Data")),
            ("Microsoft Edge", ("AppData", "Local", "Microsoft", "Edge", "User Data")),
            ("Cốc Cốc", ("AppData", "Local", "CocCoc", "Browser", "User Data")))
OUTLOOK_PLACES = (("Documents", "Outlook Files"), ("AppData", "Local", "Microsoft", "Outlook"),
                  ("My Documents", "Outlook Files"))
USER_FONTS = ("AppData", "Local", "Microsoft", "Windows", "Fonts")
FONT_SUFFIXES = (".ttf", ".otf", ".ttc", ".fon")


def zalo_folder(profile: Profile) -> Path | None:
    for key in (DOCUMENTS, DOWNLOADS, DESKTOP):
        folder = profile.folders.get(key)
        found = _child(folder, ZALO_FOLDER) if folder else None
        if found is not None and found.is_dir():
            return found
    found = _child(profile.path, ZALO_FOLDER)
    return found if found is not None and found.is_dir() else None


def bookmark_files(profile: Profile) -> list[tuple[str, str, Path]]:
    """(browser, browser profile, Bookmarks file) of each Chromium browser profile with bookmarks."""

    found = []
    for browser, names in BROWSERS:
        data = _walk(profile.path, *names)
        if data is None or not data.is_dir():
            continue
        try:
            entries = sorted(os.scandir(data), key=lambda entry: (entry.name != "Default", entry.name))
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir() and (entry.name == "Default" or entry.name.startswith("Profile ")):
                bookmarks = _child(Path(entry.path), "Bookmarks")
                if bookmarks is not None and bookmarks.is_file():
                    found.append((browser, entry.name, bookmarks))
    return found


def outlook_files(profile: Profile) -> list[Path]:
    found: list[Path] = []
    for names in OUTLOOK_PLACES:
        folder = _walk(profile.path, *names)
        if folder is None or not folder.is_dir():
            continue
        try:
            for entry in os.scandir(folder):
                if entry.is_file() and entry.name.lower().endswith(".pst") and Path(entry.path) not in found:
                    found.append(Path(entry.path))
        except OSError:
            continue
    return sorted(found)


def font_files(profile: Profile) -> list[Path]:
    folder = _walk(profile.path, *USER_FONTS)
    if folder is None or not folder.is_dir():
        return []
    try:
        return sorted(Path(entry.path) for entry in os.scandir(folder)
                      if entry.is_file() and entry.name.lower().endswith(FONT_SUFFIXES))
    except OSError:
        return []


@dataclass
class Size:
    files: int = 0
    bytes: int = 0
    unreadable: int = 0


def measure(folder: Path, skip: Callable[[Path], bool] | None = None, stop: Callable[[], bool] | None = None) -> Size:
    """Files and bytes under a folder, without following links (Windows' "My Music" junctions and the like)."""

    size = Size()
    stack = [folder]
    while stack:
        if stop is not None and stop():
            break
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            size.unreadable += 1
            continue
        for entry in entries:
            path = Path(entry.path)
            try:
                if entry.is_symlink() or (skip is not None and skip(path)):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    stack.append(path)
                elif entry.is_file(follow_symlinks=False):
                    size.files += 1
                    size.bytes += entry.stat(follow_symlinks=False).st_size
            except OSError:
                size.unreadable += 1
    return size


@dataclass
class Item:
    key: str
    sources: list[Path] = field(default_factory=list)
    size: Size | None = None
    available: bool = True        # e.g. Outlook mail without readpst still copies the .pst files
    note: str = ""


def items_of(profile: Profile) -> dict[str, Item]:
    items = {key: Item(key, [folder]) for key, folder in profile.folders.items() if key in FOLDER_ITEMS}
    zalo = zalo_folder(profile)
    if zalo is not None:
        items[ZALO] = Item(ZALO, [zalo])
    bookmarks = bookmark_files(profile)
    if bookmarks:
        items[BOOKMARKS] = Item(BOOKMARKS, [path for _browser, _profile, path in bookmarks])
    outlook = outlook_files(profile)
    if outlook:
        items[OUTLOOK] = Item(OUTLOOK, outlook)
    fonts = font_files(profile)
    if fonts:
        items[FONTS] = Item(FONTS, fonts)
    return items

"""Copying what the user picked, with progress: folders into the matching CaramOS folders, bookmarks into one web
page, Outlook mail into mbox files, fonts into ~/.local/share/fonts.

Nothing is ever overwritten: a name that is taken gets " (2)", " (3)"… before its extension, and each file is created
with O_EXCL, so a file that appears meanwhile is not replaced either. A file being copied when the user stops is
removed again. Windows' own clutter (desktop.ini, Thumbs.db, shortcuts .lnk, Office's ~$ lock files) and links (the
"My Music" junctions inside Documents) are left out. Files that cannot be read are listed at the end.
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Callable

from caramos_ota.i18n import _

from . import sources

CHUNK = 1024 * 1024
SKIP_NAMES = {"desktop.ini", "thumbs.db", "ehthumbs.db", "ehthumbs_vista.db", ".ds_store", "$recycle.bin",
              "system volume information"}
# Microsoft's fonts, which come with Windows and Office under their licence: never copied (Times New Roman and
# Arial come from the App Center's Microsoft Core Fonts, whose licence the user accepts there).
MICROSOFT_FONT_FILES = ("arial", "times", "cour", "verdana", "tahoma", "georgia", "trebuc", "comic", "impact",
                        "webdings", "wingding", "calibri", "cambria", "candara", "consola", "constan", "corbel",
                        "segoe", "segui", "symbol", "marlett", "lucon", "micross", "mso", "msyh", "msjh", "simsun",
                        "malgun", "gadugi", "ebrima", "javatext", "himalaya", "mvboli", "nirmala", "sylfaen",
                        "palabi", "pala", "framd", "gabriola", "holomdl2", "bahnschrift", "seguiemj", "ariblk")


class Cancelled(Exception):
    """The user stopped the copy."""


def skipped(path: Path) -> bool:
    name = path.name.lower()
    return name in SKIP_NAMES or name.endswith(".lnk") or name.startswith("~$")


def split_name(name: str) -> tuple[str, str]:
    """("báo cáo", ".docx"); a name that starts with a dot keeps it ("…", "")."""

    stem, dot, suffix = name.rpartition(".")
    if not dot or not stem:
        return name, ""
    return stem, "." + suffix


def free_name(target: Path) -> Path:
    """target, or "name (2).ext", "name (3).ext"… when it is taken."""

    if not os.path.lexists(target):
        return target
    stem, suffix = split_name(target.name)
    number = 2
    while True:
        candidate = target.with_name(f"{stem} ({number}){suffix}")
        if not os.path.lexists(candidate):
            return candidate
        number += 1


def user_dir(key: str, home: Path | None = None) -> Path:
    """The CaramOS folder for a Windows folder ("Documents" -> ~/Tài liệu in Vietnamese)."""

    home = home or Path.home()
    names = {"Desktop": "DESKTOP", "Documents": "DOCUMENTS", "Pictures": "PICTURES", "Downloads": "DOWNLOAD",
             "Music": "MUSIC", "Videos": "VIDEOS"}
    try:
        result = subprocess.run(["xdg-user-dir", names[key]], capture_output=True, text=True, check=False, timeout=5)
        path = Path(result.stdout.strip())
        if result.returncode == 0 and path.is_absolute() and path.resolve() != home.resolve():
            return path
    except (OSError, subprocess.SubprocessError):
        pass
    return home / key


# ---- Progress ------------------------------------------------------------------------------------------------

@dataclass
class Report:
    """What happened to one item, for the summary page."""

    key: str
    files: int = 0
    bytes: int = 0
    target: Path | None = None
    extra: int = 0                     # bookmarks written, fonts skipped as Microsoft's…
    same: int = 0                      # fonts that were on this computer already
    failed: list[str] = field(default_factory=list)
    note: str = ""


class Copier:
    """Runs the plan in a thread; on_progress(done_bytes, total_bytes, item, name) is called from that thread."""

    def __init__(self, total: int, on_progress: Callable[[int, int, str, str], None]) -> None:
        self.total = max(total, 1)
        self.done = 0
        self.on_progress = on_progress
        self.stop = threading.Event()

    def progress(self, item: str, name: str, count: int = 0) -> None:
        self.done += count
        self.on_progress(min(self.done, self.total), self.total, item, name)

    def copy_file(self, source: Path, folder: Path, item: str, name: str | None = None) -> Path:
        stat = source.stat()
        folder.mkdir(parents=True, exist_ok=True)
        while True:
            target = free_name(folder / (name or source.name))
            try:
                handle = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                break
            except FileExistsError:
                continue
        try:
            with open(source, "rb") as reader, os.fdopen(handle, "wb") as writer:
                self.progress(item, source.name)
                while True:
                    if self.stop.is_set():
                        raise Cancelled
                    chunk = reader.read(CHUNK)
                    if not chunk:
                        break
                    writer.write(chunk)
                    self.progress(item, source.name, len(chunk))
            os.utime(target, (stat.st_atime, stat.st_mtime))
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target

    def copy_tree(self, source: Path, target: Path, report: Report) -> None:
        """Merge source into target: folders that exist are used, files that exist get " (2)" names."""

        folders = {source: target}
        for root, directories, files in os.walk(source, followlinks=False):
            if self.stop.is_set():
                raise Cancelled
            here = Path(root)
            destination = folders[here]
            keep = []
            for name in sorted(directories):
                path = here / name
                if path.is_symlink() or skipped(path):
                    continue
                wanted = destination / name
                if os.path.lexists(wanted) and not wanted.is_dir():
                    wanted = free_name(wanted)
                folders[path] = wanted
                keep.append(name)
            directories[:] = keep
            try:
                destination.mkdir(parents=True, exist_ok=True)
            except OSError:
                report.failed.append(str(here))
                continue
            for name in sorted(files):
                path = here / name
                if path.is_symlink() or skipped(path):
                    continue
                try:
                    self.copy_file(path, destination, report.key)
                    report.files += 1
                    report.bytes += path.stat().st_size
                except Cancelled:
                    raise
                except OSError:
                    report.failed.append(str(path))


# ---- Bookmarks -----------------------------------------------------------------------------------------------

WEBKIT_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)


def unix_time(webkit: str | int | None) -> int:
    """Chrome's dates are microseconds since 1601."""

    try:
        value = int(webkit or 0)
    except (TypeError, ValueError):
        return 0
    if value <= 0:
        return 0
    return max(0, int(value / 1_000_000 - (datetime(1970, 1, 1, tzinfo=timezone.utc) - WEBKIT_EPOCH).total_seconds()))


def bookmark_page(sources_list: list[tuple[str, str, dict]], title: str) -> tuple[str, int]:
    """One Netscape bookmark file (what Firefox and Chrome import) with a folder for each browser profile."""

    lines = ["<!DOCTYPE NETSCAPE-Bookmark-file-1>",
             "<!-- This is an automatically generated file. It will be read and overwritten. DO NOT EDIT! -->",
             '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
             f"<TITLE>{escape(title)}</TITLE>", f"<H1>{escape(title)}</H1>", "<DL><p>"]
    count = 0
    root_names = {"bookmark_bar": _("Bookmarks bar"), "other": _("Other bookmarks"), "synced": _("Mobile bookmarks")}

    def node(item: dict, depth: int) -> None:
        nonlocal count
        indent = "    " * depth
        if item.get("type") == "url" and item.get("url"):
            added = unix_time(item.get("date_added"))
            lines.append(f'{indent}<DT><A HREF="{escape(item["url"], quote=True)}" ADD_DATE="{added}">'
                         f"{escape(item.get('name') or item['url'])}</A>")
            count += 1
        elif item.get("type") == "folder":
            children = item.get("children") or []
            if not children:
                return
            lines.append(f'{indent}<DT><H3 ADD_DATE="{unix_time(item.get("date_added"))}">'
                         f"{escape(item.get('name') or '')}</H3>")
            lines.append(f"{indent}<DL><p>")
            for child in children:
                node(child, depth + 1)
            lines.append(f"{indent}</DL><p>")

    for browser, profile, data in sources_list:
        label = browser if profile == "Default" else f"{browser} ({profile})"
        lines.append(f'    <DT><H3>{escape(label)}</H3>')
        lines.append("    <DL><p>")
        roots = data.get("roots") or {}
        for key, name in root_names.items():
            root = roots.get(key)
            if isinstance(root, dict) and root.get("children"):
                node({**root, "name": name, "type": "folder"}, 2)
        lines.append("    </DL><p>")
    lines.append("</DL><p>")
    return "\n".join(lines) + "\n", count


def read_bookmarks(files: list[tuple[str, str, Path]]) -> list[tuple[str, str, dict]]:
    found = []
    for browser, profile, path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            found.append((browser, profile, data))
    return found


# ---- Fonts ---------------------------------------------------------------------------------------------------

def font_names(path: Path) -> list[str]:
    """Copyright, trademark and manufacturer strings of a TrueType/OpenType font's name table (the first font of a
    collection)."""

    try:
        with open(path, "rb") as stream:
            data = stream.read(4 * 1024 * 1024)
    except OSError:
        return []
    offset = 0
    if data[:4] == b"ttcf" and len(data) >= 16:
        offset = struct.unpack(">I", data[12:16])[0]
    try:
        tables = struct.unpack(">H", data[offset + 4:offset + 6])[0]
        for index in range(tables):
            entry = offset + 12 + 16 * index
            tag, _checksum, start, length = struct.unpack(">4sIII", data[entry:entry + 16])
            if tag != b"name":
                continue
            table = data[start:start + length]
            count, strings = struct.unpack(">HH", table[2:6])
            found = []
            for record in range(count):
                platform, encoding, _language, name_id, size, at = struct.unpack(
                    ">HHHHHH", table[6 + 12 * record:18 + 12 * record])
                if name_id not in (0, 7, 8):
                    continue
                raw = table[strings + at:strings + at + size]
                found.append(raw.decode("utf-16-be", "ignore") if platform in (0, 3) else raw.decode("latin-1"))
            return found
    except (struct.error, IndexError):
        return []
    return []


def microsoft_font(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith(MICROSOFT_FONT_FILES):
        return True
    return any("microsoft" in text.lower() for text in font_names(path))


# ---- Outlook -------------------------------------------------------------------------------------------------

def readpst() -> str | None:
    return shutil.which("readpst")


def convert_pst(pst: Path, folder: Path, runner=subprocess.run) -> tuple[bool, str]:
    """readpst writes one .mbox file per mail folder (and contacts, calendar) into folder."""

    folder.mkdir(parents=True, exist_ok=True)
    try:
        result = runner([readpst() or "readpst", "-8", "-q", "-o", str(folder), str(pst)], capture_output=True,
                        text=True, check=False, timeout=3600)
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    return result.returncode == 0, (result.stderr or result.stdout or "").strip()[:300]


# ---- The plan ------------------------------------------------------------------------------------------------

def bookmarks_file_name() -> str:
    return _("Bookmarks from Windows") + ".html"


def outlook_folder_name() -> str:
    return _("Outlook mail")


@dataclass
class Plan:
    profile: sources.Profile
    items: dict[str, sources.Item]
    chosen: list[str]

    def total_bytes(self) -> int:
        return sum(self.items[key].size.bytes for key in self.effective() if self.items[key].size)

    def effective(self) -> list[str]:
        """The chosen items; Zalo's folder is left out when it is inside a chosen folder (copied with it)."""

        keys = [key for key in self.chosen if key in self.items]
        if sources.ZALO in keys:
            zalo = self.items[sources.ZALO].sources[0]
            for key in sources.FOLDER_ITEMS:
                folder = self.profile.folders.get(key)
                if key in keys and folder is not None and folder in zalo.parents:
                    keys.remove(sources.ZALO)
                    break
        return keys


def run_plan(plan: Plan, copier: Copier, home: Path | None = None) -> list[Report]:
    reports = []
    documents = user_dir(sources.DOCUMENTS, home)
    try:
        for key in plan.effective():
            item = plan.items[key]
            report = Report(key)
            reports.append(report)
            if key in sources.FOLDER_ITEMS:
                report.target = user_dir(key, home)
                copier.copy_tree(item.sources[0], report.target, report)
            elif key == sources.ZALO:
                report.target = documents / sources.ZALO_FOLDER
                copier.copy_tree(item.sources[0], report.target, report)
            elif key == sources.BOOKMARKS:
                files = sources.bookmark_files(plan.profile)
                page, count = bookmark_page(read_bookmarks(files), _("Bookmarks"))
                documents.mkdir(parents=True, exist_ok=True)
                target = free_name(documents / bookmarks_file_name())
                with open(target, "x", encoding="utf-8") as stream:
                    stream.write(page)
                report.target, report.extra, report.files = target, count, 1
                copier.progress(key, target.name, item.size.bytes if item.size else 0)
            elif key == sources.OUTLOOK:
                base = documents / outlook_folder_name()
                report.target = base
                for pst in item.sources:
                    if readpst():
                        folder = free_name(base / split_name(pst.name)[0])
                        ok, detail = convert_pst(pst, folder)
                        copier.progress(key, pst.name, pst.stat().st_size)
                        if ok:
                            report.files += 1
                        else:
                            report.failed.append(f"{pst} ({detail})" if detail else str(pst))
                    else:
                        copier.copy_file(pst, base, key)
                        report.files += 1
                        report.note = "copied"
            elif key == sources.FONTS:
                target = (home or Path.home()) / ".local/share/fonts"
                report.target = target
                for font in item.sources:
                    if microsoft_font(font):
                        report.extra += 1
                        copier.progress(key, font.name, font.stat().st_size)
                        continue
                    existing = target / font.name
                    if existing.exists() and existing.stat().st_size == font.stat().st_size:
                        copier.progress(key, font.name, font.stat().st_size)
                        report.same += 1       # the same font is there already
                        continue
                    try:
                        copier.copy_file(font, target, key)
                        report.files += 1
                    except OSError:
                        report.failed.append(str(font))
                if report.files:
                    subprocess.run(["fc-cache", "-f", str(target)], capture_output=True, check=False, timeout=300)
    except Cancelled:
        if reports:
            reports[-1].note = "stopped"
    return reports

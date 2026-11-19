"""Daily wallpaper: a new photo of Vietnam each day, managed from Cinnamon's own Backgrounds settings.

Ticket H-1161 asked for something like Windows Spotlight. The photos are photos of Vietnam with free licences,
picked by people. Their list is on the CaramOS website (LIST_URL, made by scripts/wallpapers.py of the caramos-landing
repository, which also hosts the photos), so the team can change the photos without a CaramOS update; each entry has
the photo's address, SHA-256, title, author and licence. Without the website the last list fetched is used, then
MANIFEST, the copy shipped in this package. A photo is only taken from ALLOWED_HOSTS, and only when its bytes match
the SHA-256 of the list and look like a picture. Every computer shows the same photo on a given day.

Nothing changes the user's wallpaper unless they ask for it, in the place they already know:
- Each day's photo is saved in FOLDER_NAME under ~/.local/share/caramos/wallpapers, a folder added once to the
  folders of System Settings > Backgrounds (~/.config/cinnamon/backgrounds/user-folders.lst). Removing it there
  turns the feature off for good.
- Picking one of its photos as the wallpaper turns the daily change on: while the wallpaper is a photo of that
  folder, each new day's photo becomes the wallpaper. Picking any other wallpaper turns it off again.
- A Backgrounds slideshow of that folder also works: Cinnamon's slideshow picks up each new photo by itself.
- On CaramOS Xfce the folder is a GTK bookmark instead, so Desktop settings list it under Folder; the same
  rules hold for each monitor and workspace, and Xfce's "Change the background" plays the folder.

The file names carry the title, author and licence, which Backgrounds shows under each photo, and NOTES_NAME in the
folder lists each photo's source page. A download goes to a hidden file next to the folder, so a slideshow never
sees half a photo, and the oldest photos go once there are more than KEEP, never the current wallpaper.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote, unquote, urlparse

MANIFEST = Path("/usr/share/caramos-ota/daily-wallpaper/photos.json")
LIST_URL = "https://caramos.vietnamlinuxfamily.net/wallpapers/photos.json"
ALLOWED_HOSTS = ("caramos.vietnamlinuxfamily.net", "upload.wikimedia.org", "thumb.wikimedia.org")
LIST_MAX_BYTES = 1 << 20
PHOTO_MAX_BYTES = 25 << 20
FOLDER_NAME = "Việt Nam mỗi ngày"
NOTES_NAME = "Nguồn ảnh.txt"
KEEP = 14
EPOCH = dt.date(2026, 1, 1)
USER_AGENT = "CaramOS-daily-wallpaper/1.0 (+https://caramos.vietnamlinuxfamily.net)"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UNSAFE_RE = re.compile(r"[\x00-\x1f/\\:*?\"<>|&]+")


class WallpaperError(RuntimeError):
    """A photo could not be fetched or checked."""


@dataclass(frozen=True)
class Photo:
    id: str
    url: str
    sha256: str
    title: str
    author: str
    license: str
    source: str


def allowed_url(url: str, allow_files: bool) -> bool:
    """https on one of ALLOWED_HOSTS; file:// only in a list read from a file (the packaged one, tests)."""

    parsed = urlparse(url)
    if parsed.scheme == "https":
        return (parsed.hostname or "") in ALLOWED_HOSTS
    return allow_files and parsed.scheme == "file"


def parse_manifest(text: str, allow_files: bool = False) -> list[Photo]:
    """The photos of a list; entries with a missing field, a bad hash or an address elsewhere are left out."""

    raw = json.loads(text)
    photos = []
    for entry in raw.get("photos", []) if isinstance(raw, dict) else []:
        try:
            photo = Photo(**{field: str(entry[field]).strip() for field in Photo.__dataclass_fields__})
        except (KeyError, TypeError):
            continue
        if SHA256_RE.fullmatch(photo.sha256) and allowed_url(photo.url, allow_files) and photo.title:
            photos.append(photo)
    return photos


def load_manifest(path: Path = MANIFEST) -> list[Photo]:
    return parse_manifest(path.read_text(encoding="utf-8"), allow_files=True)


def fetch_list(url: str, cache: Path, opener: Callable = urllib.request.urlopen, timeout: int = 30) -> list[Photo]:
    """The list on the website, kept in cache for the days the website cannot be reached; [] when it fails."""

    allow_files = url.startswith("file://")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener(request, timeout=timeout) as response:
            data = response.read(LIST_MAX_BYTES + 1)
        if len(data) > LIST_MAX_BYTES:
            return []
        photos = parse_manifest(data.decode("utf-8"), allow_files=allow_files)
    except (OSError, ValueError, UnicodeDecodeError):
        return []
    if photos:
        cache.parent.mkdir(parents=True, exist_ok=True)
        staging = cache.with_name(cache.name + ".part")
        staging.write_bytes(data)
        os.replace(staging, cache)
    return photos


def load_cached(cache: Path) -> list[Photo]:
    try:
        return parse_manifest(cache.read_text(encoding="utf-8"), allow_files=False)
    except (OSError, ValueError):
        return []


def looks_like_picture(head: bytes) -> bool:
    """JPEG, PNG or WebP, from the first bytes: a web page or an error message never becomes a wallpaper."""

    return head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG\r\n\x1a\n") or (
        head[:4] == b"RIFF" and head[8:12] == b"WEBP")


def photo_for_day(photos: list[Photo], day: dt.date) -> Photo:
    """The same photo on every computer on a given day, in the manifest's order."""

    if not photos:
        raise WallpaperError("the photo list is empty")
    return photos[(day - EPOCH).days % len(photos)]


def candidates(photos: list[Photo], day: dt.date, count: int = 3) -> list[Photo]:
    """The day's photo, then the next ones: one that cannot be fetched or checked gives way to the next."""

    first = (day - EPOCH).days % len(photos) if photos else 0
    return [photos[(first + step) % len(photos)] for step in range(min(count, len(photos)))]


def file_name(photo: Photo, day: dt.date) -> str:
    """"2026-11-17 Vịnh Hạ Long (Ảnh: Tên tác giả, CC BY-SA 4.0).jpg": shown by Backgrounds, sorted by day."""

    def clean(text: str) -> str:
        return re.sub(r"\s+", " ", UNSAFE_RE.sub(" ", text)).strip()

    credit = clean(f"{photo.author}, {photo.license}")
    name = f"{day.isoformat()} {clean(photo.title)} (Ảnh: {credit})"
    suffix = Path(urlparse(photo.url).path).suffix.lower()
    suffix = suffix if suffix in (".jpg", ".jpeg", ".png", ".webp") else ".jpg"
    while len(name.encode("utf-8")) > 200:
        name = name[:-1]
    return name.rstrip() + suffix


def folder_of(home: Path) -> Path:
    return home / ".local/share/caramos/wallpapers" / FOLDER_NAME


def register_folder(folder: Path, folders_list: Path, pictures: Path) -> bool:
    """Add folder to the Backgrounds folders; True when it was added. Cinnamon creates the list with the
    Pictures folder in it, so a new list starts with that one too."""

    try:
        lines = folders_list.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        lines = [str(pictures)]
    if str(folder) in lines:
        return False
    folders_list.parent.mkdir(parents=True, exist_ok=True)
    folders_list.write_text("".join(f"{line}\n" for line in lines + [str(folder)] if line.strip()), encoding="utf-8")
    return True


def folder_listed(folder: Path, folders_list: Path) -> bool:
    try:
        return str(folder) in folders_list.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return False


# CaramOS Xfce: Xfce's Desktop settings show one folder's pictures, picked under Folder, which lists the GTK
# bookmarks (Nemo's sidebar shows them too). The folder is added there once; removing the bookmark turns the feature
# off for good, as removing it from Cinnamon's Backgrounds does. The desktop's pictures are xfconf properties.
XFCE_LAST_IMAGE_RE = re.compile(r"^/backdrop/screen\d+/monitor[^/]+(?:/workspace\d+)?/last-image$")
# The five CaramOS wallpapers of the Xfce edition (migration 20261118090100). Folder lists a folder only while it is
# the current one or a bookmark, so they were out of sight once another folder was picked (the owner could not find
# them, 2026-11-19): they are bookmarked too, once, before the daily photos.
XFCE_WALLPAPERS = Path("/usr/share/backgrounds/CaramOS")


def _bookmarks(bookmarks: Path) -> list[str]:
    try:
        return bookmarks.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []


def bookmarked(folder: Path, bookmarks: Path) -> bool:
    return any(uri_path(line.split(" ", 1)[0]) == folder for line in _bookmarks(bookmarks) if line.strip())


def add_bookmark(folder: Path, bookmarks: Path) -> bool:
    """Add folder to the GTK bookmarks; True when it was added. Its name there is the folder's, FOLDER_NAME."""

    if bookmarked(folder, bookmarks):
        return False
    lines = [line for line in _bookmarks(bookmarks) if line.strip()] + [file_uri(folder)]
    bookmarks.parent.mkdir(parents=True, exist_ok=True)
    bookmarks.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return True


def xfce_following(folder: Path, images: dict[str, str]) -> list[str]:
    """The Xfce desktop properties (monitor, workspace) whose picture is a photo of folder: they follow the daily
    photo. Another picture on one of them leaves that one alone."""

    return [name for name, value in sorted(images.items())
            if XFCE_LAST_IMAGE_RE.match(name) and value and Path(value).parent == folder]


def uri_path(uri: str) -> Path | None:
    """The file of a file:// URI, as Backgrounds writes it (percent-encoded)."""

    parsed = urlparse(uri.strip())
    if parsed.scheme != "file":
        return None
    return Path(unquote(parsed.path))


def file_uri(path: Path) -> str:
    return "file://" + quote(str(path))


def mode(folder: Path, picture_uri: str, slideshow: bool, image_source: str) -> str:
    """'slideshow' when Cinnamon's slideshow plays the folder, 'follow' when the wallpaper is one of its photos,
    otherwise 'off'."""

    if slideshow and image_source.startswith("directory://"):
        source = Path(unquote(image_source[len("directory://"):])).expanduser()
        if source == folder:
            return "slideshow"
    current = uri_path(picture_uri)
    if current is not None and current.parent == folder:
        return "follow"
    return "off"


def fetch(photo: Photo, target: Path, opener: Callable = urllib.request.urlopen, timeout: int = 60) -> None:
    """Download photo to target through a hidden file next to target's folder, checking its SHA-256."""

    request = urllib.request.Request(photo.url, headers={"User-Agent": USER_AGENT})
    staging_dir = target.parent.parent
    fd, staging = tempfile.mkstemp(prefix=".caramos-wallpaper-", suffix=".part", dir=staging_dir)
    digest = hashlib.sha256()
    size = 0
    head = b""
    try:
        with os.fdopen(fd, "wb") as out, opener(request, timeout=timeout) as response:
            while chunk := response.read(1 << 16):
                size += len(chunk)
                if size > PHOTO_MAX_BYTES:
                    raise WallpaperError(f"{photo.id}: larger than {PHOTO_MAX_BYTES >> 20} MB")
                if len(head) < 16:
                    head = (head + chunk)[:16]
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != photo.sha256:
            raise WallpaperError(f"{photo.id}: the download does not match its SHA-256")
        if not looks_like_picture(head):
            raise WallpaperError(f"{photo.id}: not a JPEG, PNG or WebP picture")
        os.chmod(staging, 0o644)   # mkstemp makes it 0600; a picture is not a secret
        os.replace(staging, target)
    except OSError as exc:
        raise WallpaperError(f"{photo.id}: {exc}") from exc
    finally:
        if os.path.exists(staging):
            os.unlink(staging)


def write_notes(folder: Path, photos: dict[str, dict]) -> None:
    """NOTES_NAME: where each photo in the folder comes from (Backgrounds lists only the pictures)."""

    lines = ["Ảnh trong thư mục này là ảnh Việt Nam có giấy phép tự do, CaramOS tải mỗi ngày một ảnh.",
             "Danh sách ảnh: https://caramos.vietnamlinuxfamily.net/wallpapers/",
             "Photos of Vietnam with free licences, one a day, fetched by CaramOS.", ""]
    for name in sorted(photos):
        photo = photos[name]
        lines += [name, f"  {photo.get('title', '')} - {photo.get('author', '')}, {photo.get('license', '')}",
                  f"  {photo.get('source', '')}", ""]
    (folder / NOTES_NAME).write_text("\n".join(lines), encoding="utf-8")


def prune(folder: Path, keep: int, current: Path | None, also: frozenset[Path] | set[Path] = frozenset()) -> list[Path]:
    """Delete the oldest daily photos beyond keep; the current wallpaper stays, and so do the pictures in also (the
    Xfce desktop's, one per monitor and workspace)."""

    photos = sorted(path for path in folder.iterdir()
                    if path.is_file() and re.match(r"^\d{4}-\d{2}-\d{2} ", path.name))
    removed = []
    for path in photos[:-keep] if keep > 0 else photos:
        if (current is not None and path == current) or path in also:
            continue
        path.unlink(missing_ok=True)
        removed.append(path)
    return removed

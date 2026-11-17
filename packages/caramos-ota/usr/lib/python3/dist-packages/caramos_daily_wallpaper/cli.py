"""caramos-daily-wallpaper: save today's photo of Vietnam and, if the user chose the daily photos, show it.

Run by caramos-daily-wallpaper.timer (a systemd user timer: daily and shortly after login). See core.py for how
the feature is turned on and off from System Settings > Backgrounds.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import fcntl
import json
import subprocess
import sys
from pathlib import Path

from . import core

BACKGROUND = "org.cinnamon.desktop.background"
SLIDESHOW = "org.cinnamon.desktop.background.slideshow"


def gsettings_get(schema: str, key: str) -> str:
    result = subprocess.run(["gsettings", "get", schema, key], check=False, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    text = result.stdout.strip()
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text
    return str(value).lower() if isinstance(value, bool) else str(value)


def gsettings_set_string(schema: str, key: str, value: str) -> bool:
    literal = "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    return subprocess.run(["gsettings", "set", schema, key, literal], check=False,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def pictures_dir(home: Path) -> Path:
    try:
        result = subprocess.run(["xdg-user-dir", "PICTURES"], check=False, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        path = Path(result.stdout.strip())
        if result.returncode == 0 and path.is_absolute() and path != home:
            return path
    except OSError:
        pass
    return home / "Pictures"


def metered() -> bool:
    """Whether the network is metered (a phone's hotspot set so in NetworkManager): no download then."""

    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio

        return bool(Gio.NetworkMonitor.get_default().get_network_metered())
    except Exception:
        return False


def load_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def photo_list(list_url: str, cache: Path, packaged: Path) -> list[core.Photo]:
    """The website's list, else the one fetched last time, else the copy in this package."""

    photos = core.fetch_list(list_url, cache)
    if photos:
        return photos
    print("the photo list on the website could not be read; using the last one", file=sys.stderr)
    return core.load_cached(cache) or core.load_manifest(packaged)


def run(home: Path, day: dt.date, manifest: Path, force: bool = False, list_url: str = core.LIST_URL) -> int:
    folder = core.folder_of(home)
    folders_list = home / ".config/cinnamon/backgrounds/user-folders.lst"
    state_path = home / ".local/state/caramos/daily-wallpaper.json"
    state = load_state(state_path)

    if not state.get("registered"):
        folder.mkdir(parents=True, exist_ok=True)
        core.register_folder(folder, folders_list, pictures_dir(home))
        state["registered"] = True
        save_state(state_path, state)
        print(f"added {folder} to the folders of System Settings > Backgrounds")
    elif not core.folder_listed(folder, folders_list):
        print("the daily photos were removed from System Settings > Backgrounds; nothing to do")
        return 0
    folder.mkdir(parents=True, exist_ok=True)

    files = {name: meta for name, meta in state.get("files", {}).items() if isinstance(meta, dict)}
    state["files"] = files
    saved_today = sorted(folder.glob(f"{day.isoformat()} *"))
    if saved_today:
        target = saved_today[-1]
    else:
        if metered() and not force:
            print("the network is metered: today's photo waits for another connection")
            return 0
        photos = photo_list(list_url, home / ".cache/caramos/daily-wallpaper/photos.json", manifest)
        # Today's photo, or the next one when it cannot be fetched or its bytes changed.
        target = None
        for photo in core.candidates(photos, day):
            attempt = folder / core.file_name(photo, day)
            try:
                core.fetch(photo, attempt)
            except core.WallpaperError as exc:
                print(f"skipped {photo.id}: {exc}", file=sys.stderr)
                continue
            target = attempt
            files[target.name] = {"id": photo.id, "title": photo.title, "author": photo.author,
                                  "license": photo.license, "source": photo.source}
            print(f"saved {target.name}")
            break
        if target is None:
            print("no photo could be fetched today; trying again later", file=sys.stderr)
            return 0

    picture_uri = gsettings_get(BACKGROUND, "picture-uri")
    slideshow = gsettings_get(SLIDESHOW, "slideshow-enabled") == "true"
    image_source = gsettings_get(SLIDESHOW, "image-source")
    current = core.uri_path(picture_uri)
    if core.mode(folder, picture_uri, slideshow, image_source) == "follow" and current != target:
        if gsettings_set_string(BACKGROUND, "picture-uri", core.file_uri(target)):
            current = target
            print("the wallpaper is today's photo")

    for removed in core.prune(folder, core.KEEP, current):
        files.pop(removed.name, None)
    state["files"] = {name: meta for name, meta in files.items() if (folder / name).exists()}
    core.write_notes(folder, state["files"])
    save_state(state_path, state)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caramos-daily-wallpaper", description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="download even on a metered connection")
    parser.add_argument("--day", type=dt.date.fromisoformat, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--manifest", type=Path, default=core.MANIFEST, help=argparse.SUPPRESS)
    parser.add_argument("--list-url", default=core.LIST_URL, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    home = Path.home()
    lock_path = home / ".local/state/caramos/daily-wallpaper.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("another run is busy")
            return 0
        return run(home, args.day or dt.date.today(), args.manifest, force=args.force, list_url=args.list_url)

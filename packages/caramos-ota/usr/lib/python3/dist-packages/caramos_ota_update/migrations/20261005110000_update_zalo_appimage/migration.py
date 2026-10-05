"""Install Zalo for Linux from VN-Linux-Family/zalo-for-linux.

CaramOS ISOs up to 1.0.16 downloaded Zalo 26.5.10 from hthienloc/zalo-for-linux. That repository moved to
VN-Linux-Family/zalo-for-linux and the old download is gone, so those machines would keep a Zalo nothing
updates. This migration replaces the AppImage CaramOS installed with the pinned release of the new
repository. The ISO build relies on it as well: hook 0300 only writes the launcher, and the OTA bootstrap
then runs this migration in the rootfs, which downloads the AppImage.

An AppImage at the CaramOS path that is not a CaramOS build was put there by the user and is left alone.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import NamedTuple

from caramos_ota_update.context import MigrationContext, MigrationContextError

DESCRIPTION = "Install Zalo from the VN-Linux-Family/zalo-for-linux releases"

ZALO_APPIMAGE = Path("/usr/local/bin/Zalo.AppImage")
ZALO_LAUNCHER = Path("/usr/share/applications/zalo.desktop")
# What CaramOS installed, so a later Zalo update can tell its own build from one the user put there.
STATE_FILE = Path("/var/lib/caramos-ota/zalo-appimage.json")

REPOSITORY = "VN-Linux-Family/zalo-for-linux"
RELEASE_TAG = "26.10.10"
# ZaDark flavour without the bundled Wine ("Full"), the flavour CaramOS has always shipped.
ASSET_NAME = "Zalo-26.10.10+ZaDark-26.2.1-ed91566-x86_64.AppImage"
ASSET_SHA256 = "b57e5e23eff15c25263dab604a2881068e17a57999a57e172e23e176cac00c0e"
ASSET_SIZE = 220082475
# Upstream CI rebuilds a tag and deletes the assets of the previous build, so the commit hash in the
# name (and the file) can change. The same flavour of the same tag is then looked up in the release.
ASSET_PATTERN = re.compile(re.escape(f"Zalo-{RELEASE_TAG}+ZaDark-") + r"[0-9.]+-[0-9a-f]{7}-x86_64\.AppImage")

# sha256 of the AppImages CaramOS builds installed before this migration.
CARAMOS_BUILDS = {
    "9e1c58db3d4c373ef87c578bacb448eab92afe4d6d4d892ecf36f26ea8362983": "26.5.10 (hthienloc, ISOs up to 1.0.16)",
    "2cb85a26e77cc0e580743d5a20fffffce83f70e1ed81cb88238424ac4115b71d": "26.5.10 (VN-Linux-Family rebuild)",
}

USER_AGENT = "caramos-ota"
TIMEOUT_SECONDS = 60
DOWNLOAD_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 5
FREE_SPACE_MARGIN = 64 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


class Asset(NamedTuple):
    name: str
    url: str
    sha256: str
    size: int


def release_download_url(name: str) -> str:
    return f"https://github.com/{REPOSITORY}/releases/download/{RELEASE_TAG}/{urllib.parse.quote(name)}"


PINNED_ASSET = Asset(ASSET_NAME, release_download_url(ASSET_NAME), ASSET_SHA256, ASSET_SIZE)


def plan_action(installed_sha256: str | None, launcher_present: bool, state: dict) -> str:
    """Return install, replace, current, absent or user for what is at ZALO_APPIMAGE."""

    if installed_sha256 is None:
        # A launcher without its AppImage is the ISO build (hook 0300) or a broken install.
        return "install" if launcher_present else "absent"
    recorded = state.get("sha256")
    if installed_sha256 == ASSET_SHA256 or (installed_sha256 == recorded and state.get("tag") == RELEASE_TAG):
        return "current"
    if installed_sha256 in CARAMOS_BUILDS or installed_sha256 == recorded:
        return "replace"
    return "user"


def file_sha256(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except FileNotFoundError:
        return None


def load_state() -> dict:
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def launcher_present() -> bool:
    try:
        return str(ZALO_APPIMAGE) in ZALO_LAUNCHER.read_text(encoding="utf-8")
    except (FileNotFoundError, UnicodeDecodeError):
        return False


def _open(url: str, accept: str | None = None):
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT_SECONDS)


def resolve_rebuilt_asset() -> Asset:
    """Find the AppImage of RELEASE_TAG in the release when the pinned file has been replaced."""

    api_url = f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{RELEASE_TAG}"
    with _open(api_url, accept="application/vnd.github+json") as response:
        release = json.load(response)
    matches = [item for item in release.get("assets", []) if ASSET_PATTERN.fullmatch(str(item.get("name", "")))]
    if len(matches) != 1:
        raise MigrationContextError(f"expected one Zalo AppImage in release {RELEASE_TAG}, found {len(matches)}")
    item = matches[0]
    digest = str(item.get("digest") or "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise MigrationContextError(f"release {RELEASE_TAG} gives no sha256 for {item['name']}")
    url = str(item.get("browser_download_url", ""))
    if url != release_download_url(item["name"]):
        raise MigrationContextError(f"unexpected download URL for {item['name']}: {url}")
    return Asset(item["name"], url, digest.removeprefix("sha256:"), int(item["size"]))


def download(asset: Asset, directory: Path) -> Path:
    """Download asset next to its destination and return the verified, executable temporary file."""

    fd, name = tempfile.mkstemp(prefix=".Zalo.AppImage.", dir=directory)
    tmp = Path(name)
    try:
        digest = hashlib.sha256()
        size = 0
        with os.fdopen(fd, "wb") as out, _open(asset.url) as response:
            while chunk := response.read(CHUNK_SIZE):
                out.write(chunk)
                digest.update(chunk)
                size += len(chunk)
            out.flush()
            os.fsync(out.fileno())
        if size != asset.size or digest.hexdigest() != asset.sha256:
            raise MigrationContextError(
                f"{asset.name} failed verification: got {size} bytes sha256 {digest.hexdigest()}, "
                f"expected {asset.size} bytes sha256 {asset.sha256}"
            )
        tmp.chmod(0o755)
        return tmp
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def fetch(context: MigrationContext, directory: Path) -> tuple[Asset, Path]:
    asset = PINNED_ASSET
    last_error: Exception | None = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            context.log(f"download {asset.url} ({asset.size // (1024 * 1024)} MiB), attempt {attempt}")
            return asset, download(asset, directory)
        except urllib.error.HTTPError as error:
            last_error = error
            if error.code == 404 and asset == PINNED_ASSET:
                context.log(f"{asset.name} is no longer published; looking up the {RELEASE_TAG} release")
                try:
                    asset = resolve_rebuilt_asset()
                except (OSError, ValueError, KeyError, MigrationContextError) as resolve_error:
                    last_error = resolve_error
                else:
                    continue
        except (OSError, MigrationContextError) as error:
            last_error = error
        context.log(f"download failed: {last_error}")
        if attempt < DOWNLOAD_ATTEMPTS:
            time.sleep(RETRY_DELAY_SECONDS * attempt)
    raise MigrationContextError(f"could not download Zalo {RELEASE_TAG} from {REPOSITORY}: {last_error}")


def run(context: MigrationContext) -> None:
    if ZALO_APPIMAGE.is_symlink():
        context.log(f"{ZALO_APPIMAGE} is a symlink managed outside CaramOS; leaving Zalo as it is")
        return
    state = load_state()
    installed = file_sha256(ZALO_APPIMAGE)
    action = plan_action(installed, launcher_present(), state)
    if action == "absent":
        context.log("Zalo is not installed; nothing to do")
        return
    if action == "current":
        context.log(f"Zalo {RELEASE_TAG} from {REPOSITORY} is already installed")
        return
    if action == "user":
        context.log(f"{ZALO_APPIMAGE} (sha256 {installed}) is not a CaramOS build; leaving it as it is")
        return

    previous = CARAMOS_BUILDS.get(installed or "", "missing" if installed is None else "earlier CaramOS install")
    context.log(f"{action} Zalo: {previous} -> {RELEASE_TAG} from {REPOSITORY}")
    if context.dry_run:
        return

    directory = ZALO_APPIMAGE.parent
    directory.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(directory).free
    if free < ASSET_SIZE + FREE_SPACE_MARGIN:
        raise MigrationContextError(
            f"not enough free space in {directory} for Zalo: {free // (1024 * 1024)} MiB free, "
            f"{(ASSET_SIZE + FREE_SPACE_MARGIN) // (1024 * 1024)} MiB needed"
        )
    asset, tmp = fetch(context, directory)
    # A running Zalo keeps the old file open, so replacing it is safe; the new one is used on next start.
    os.replace(tmp, ZALO_APPIMAGE)
    record = {"repository": REPOSITORY, "tag": RELEASE_TAG, "asset": asset.name, "sha256": asset.sha256}
    context.write_file_if_changed(STATE_FILE, json.dumps(record, indent=2) + "\n")
    context.log(f"installed {asset.name} at {ZALO_APPIMAGE}")

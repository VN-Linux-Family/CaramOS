"""Migration for 1.0.6: install CaramOS Ubiquity slideshow and branding."""

from __future__ import annotations

import shutil
import struct
from pathlib import Path

from caramos_ota_update.context import MigrationContext

FROM_VERSION = "1.0.5"
TO_VERSION = "1.0.6"
DESCRIPTION = "Install CaramOS custom Ubiquity slideshow assets and installer branding"

SOURCE_ROOT = Path("/usr/share/caramos-ota/slideshow")
TARGET_ROOT = Path("/usr/share/ubiquity-slideshow")
LOCALE_ROOTS = (Path("/usr/share/locale"), Path("/usr/share/locale-langpack"))
REPLACEMENTS = {
    "Linux Mint": "CaramOS",
    "linux mint": "CaramOS",
    "linuxmint": "caramos",
    "Install Linux Mint": "Install CaramOS",
    "cài đặt Linux Mint": "cài đặt CaramOS",
    "Cài đặt Linux Mint": "Cài đặt CaramOS",
}


def _copy_tree(source: Path, target: Path) -> None:
    """Copy a directory tree, replacing existing files from the same paths."""

    for source_path in source.rglob("*"):
        relative_path = source_path.relative_to(source)
        target_path = target / relative_path
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)


def _parse_mo(data: bytes) -> tuple[bool, int, list[tuple[bytes, bytes]]]:
    """Parse a GNU gettext .mo catalog without external build dependencies."""

    if len(data) < 28:
        raise ValueError("file too small")
    magic_le = struct.unpack("<I", data[:4])[0]
    magic_be = struct.unpack(">I", data[:4])[0]
    if magic_le == 0x950412DE:
        endian = "<"
    elif magic_be == 0x950412DE:
        endian = ">"
    else:
        raise ValueError("invalid gettext catalog magic")

    _magic, revision, count, originals_offset, translations_offset, _hash_size, _hash_offset = struct.unpack(
        endian + "7I", data[:28]
    )
    messages: list[tuple[bytes, bytes]] = []
    for index in range(count):
        original_length, original_offset = struct.unpack(
            endian + "2I", data[originals_offset + index * 8 : originals_offset + index * 8 + 8]
        )
        translation_length, translation_offset = struct.unpack(
            endian + "2I", data[translations_offset + index * 8 : translations_offset + index * 8 + 8]
        )
        original = data[original_offset : original_offset + original_length]
        translation = data[translation_offset : translation_offset + translation_length]
        messages.append((original, translation))
    return endian == "<", revision, messages


def _build_mo(little_endian: bool, revision: int, messages: list[tuple[bytes, bytes]]) -> bytes:
    """Build a GNU gettext .mo catalog from parsed messages."""

    endian = "<" if little_endian else ">"
    messages = sorted(messages, key=lambda item: item[0])
    count = len(messages)
    originals_offset = 28
    translations_offset = originals_offset + count * 8
    strings_offset = translations_offset + count * 8
    originals_table: list[tuple[int, int]] = []
    translations_table: list[tuple[int, int]] = []
    strings = bytearray()

    for original, _translation in messages:
        originals_table.append((len(original), strings_offset + len(strings)))
        strings.extend(original + b"\0")
    for _original, translation in messages:
        translations_table.append((len(translation), strings_offset + len(strings)))
        strings.extend(translation + b"\0")

    output = bytearray()
    output.extend(struct.pack(endian + "7I", 0x950412DE, revision, count, originals_offset, translations_offset, 0, 0))
    for length, offset in originals_table:
        output.extend(struct.pack(endian + "2I", length, offset))
    for length, offset in translations_table:
        output.extend(struct.pack(endian + "2I", length, offset))
    output.extend(strings)
    return bytes(output)


def _patch_text(text: str) -> str:
    for old, new in REPLACEMENTS.items():
        text = text.replace(old, new)
    return text


def _patch_mo(path: Path) -> bool:
    """Patch Linux Mint strings in one gettext catalog."""

    data = path.read_bytes()
    little_endian, revision, messages = _parse_mo(data)
    changed = False
    patched: list[tuple[bytes, bytes]] = []
    for original, translation in messages:
        parts = translation.split(b"\0")
        new_parts = []
        for part in parts:
            try:
                text = part.decode("utf-8")
            except UnicodeDecodeError:
                new_parts.append(part)
                continue
            new_text = _patch_text(text)
            if new_text != text:
                changed = True
            new_parts.append(new_text.encode("utf-8"))
        patched.append((original, b"\0".join(new_parts)))
    if not changed:
        return False
    backup = path.with_suffix(path.suffix + ".caramos.bak")
    if not backup.exists():
        backup.write_bytes(data)
    path.write_bytes(_build_mo(little_endian, revision, patched))
    return True


def _patch_ubiquity_translations(context: MigrationContext) -> None:
    """Patch installed Ubiquity translation catalogs."""

    patched_count = 0
    for root in LOCALE_ROOTS:
        if not root.exists():
            continue
        for path in root.glob("*/LC_MESSAGES/ubiquity*.mo"):
            try:
                if _patch_mo(path):
                    patched_count += 1
                    context.log(f"patched ubiquity translation: {path}")
            except Exception as exc:
                context.log(f"warning: skipped ubiquity translation {path}: {exc}")
    context.log(f"patched ubiquity translation catalogs: {patched_count}")


def run(context: MigrationContext) -> None:
    """Install slideshow files and debrand installer strings used by live boot."""

    if context.dry_run:
        context.log(f"[dry-run] copy {SOURCE_ROOT}/slides to {TARGET_ROOT}/slides")
        context.log(f"[dry-run] copy {SOURCE_ROOT}/slideshow.conf to {TARGET_ROOT}/slideshow.conf")
        context.log("[dry-run] patch Ubiquity gettext catalogs under /usr/share/locale*")
        return

    slides_source = SOURCE_ROOT / "slides"
    config_source = SOURCE_ROOT / "slideshow.conf"
    if not slides_source.is_dir():
        raise FileNotFoundError(f"missing slideshow source directory: {slides_source}")
    if not config_source.is_file():
        raise FileNotFoundError(f"missing slideshow config: {config_source}")

    _copy_tree(slides_source, TARGET_ROOT / "slides")
    TARGET_ROOT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_source, TARGET_ROOT / "slideshow.conf")
    context.log("installed CaramOS Ubiquity slideshow assets")
    _patch_ubiquity_translations(context)

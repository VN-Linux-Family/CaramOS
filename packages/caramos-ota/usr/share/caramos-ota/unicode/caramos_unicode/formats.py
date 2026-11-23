"""Each kind of file the converter reads, and the new file it writes next to the old one.

Office files (.docx, .xlsx, .pptx, .odt, .ods, .odp, .rtf, and .doc/.xls through LibreOffice) say which font each piece
of text uses: only text in a legacy font (.VnTime, VNI-Times…, see legacy.classify_font) is converted, in the
encoding of that font, and the font becomes Times New Roman, Arial or Courier New. The XML is edited in place, piece
by piece, so everything else in the file stays byte for byte. Plain text (.txt, .csv) and web pages without legacy
fonts have no fonts: legacy.guess() says which encoding the text reads in, and the caller asks the user when it is
unsure.

The result always goes to a new file, "<name> (Unicode).<ext>" (then "(Unicode) (2)"…) next to the old one, or in the
Documents folder when that folder cannot be written (a Windows disk mounted read-only). Nothing is ever overwritten:
the file is written under a temporary name and linked to its final name, which fails if the name was taken.
"""

from __future__ import annotations

import html
import io
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable

from caramos_ota.i18n import _

from . import legacy
from .legacy import TCVN3, VNI, LegacyFont, classify_font, to_unicode

TEXT_SUFFIXES = (".txt", ".csv")
HTML_SUFFIXES = (".html", ".htm")
OFFICE_SUFFIXES = (".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp")
OLD_OFFICE = {".doc": ".docx", ".xls": ".xlsx"}
SUFFIXES = TEXT_SUFFIXES + HTML_SUFFIXES + (".rtf",) + OFFICE_SUFFIXES + tuple(OLD_OFFICE)
MIXED = "mixed"
LINES = "lines"               # text without fonts: each line in the encoding it reads best in
LIBREOFFICE_FLATPAK = "org.libreoffice.LibreOffice"


class ConversionError(Exception):
    """A file that cannot be converted; the message is for the user (translated)."""


@dataclass
class Result:
    source: Path
    output: Path | None = None      # the new file, None when nothing was written
    encoding: str | None = None     # TCVN3, VNI or MIXED
    changed: int = 0                # pieces of text converted (runs, cells, lines)
    note: str = ""                  # why nothing was written, or where the file went
    fallback: bool = False          # written to the Documents folder: the file's folder is read-only


@dataclass
class Analysis:
    """What a file needs before converting: a choice of encoding for text without fonts."""

    source: Path
    needs_choice: bool = False
    guess: legacy.Guess | None = None
    samples: dict[str, str] = field(default_factory=dict)   # encoding -> what the start of the text becomes
    note: str = ""                                          # nothing to convert, and why


# ---- Writing the new file ------------------------------------------------------------------------------------

def documents_dir() -> Path:
    try:
        result = subprocess.run(["xdg-user-dir", "DOCUMENTS"], capture_output=True, text=True, check=False, timeout=5)
        path = Path(result.stdout.strip())
        if result.returncode == 0 and path.is_absolute() and path != Path.home():
            return path
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home()


def candidates(directory: Path, stem: str, suffix: str):
    yield directory / f"{stem} (Unicode){suffix}"
    number = 2
    while True:
        yield directory / f"{stem} (Unicode) ({number}){suffix}"
        number += 1


def create_new(directory: Path, stem: str, suffix: str, data: bytes) -> Path:
    """Create the first free name with O_EXCL, which fails when the name exists (on USB sticks too)."""

    for target in candidates(directory, stem, suffix):
        try:
            handle = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            continue
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(data)
        except OSError:
            target.unlink(missing_ok=True)
            raise
        return target
    raise AssertionError("unreachable")


def write_new(source: Path, data: bytes, suffix: str | None = None,
              fallback_dir: Callable[[], Path] | None = None) -> tuple[Path, bool]:
    """Write data to the first free "<name> (Unicode)" name; (path, True) when it went to the Documents folder."""

    suffix = source.suffix if suffix is None else suffix
    try:
        return create_new(source.parent, source.stem, suffix, data), False
    except OSError:
        pass
    try:
        return create_new((fallback_dir or documents_dir)(), source.stem, suffix, data), True
    except OSError as error:
        raise ConversionError(_("The new file cannot be written next to the old one or in the Documents "
                                "folder.")) from error


# ---- XML pieces ----------------------------------------------------------------------------------------------

_TOKEN = re.compile(r"<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|<![^>]*>|<[^>]*>|[^<]+", re.S)
_NAME = re.compile(r"<(/?)([^\s/>]+)")
_ENTITY = re.compile(r"&(#x[0-9a-fA-F]+|#[0-9]+|lt|gt|amp|quot|apos);")
_NAMED = {"lt": "<", "gt": ">", "amp": "&", "quot": '"', "apos": "'"}


def xml_unescape(text: str) -> str:
    def entity(match: re.Match) -> str:
        name = match.group(1)
        if name.startswith("#x"):
            return chr(int(name[2:], 16))
        if name.startswith("#"):
            return chr(int(name[1:]))
        return _NAMED[name]

    return _ENTITY.sub(entity, text)


def xml_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def tag(token: str) -> tuple[str, str]:
    """(name, kind) of a token: kind is "start", "end", "empty", "text" or "other"."""

    if not token.startswith("<"):
        return "", "text"
    if token.startswith(("<?", "<!")):
        return "", "other"
    match = _NAME.match(token)
    if not match:
        return "", "other"
    if match.group(1):
        return match.group(2), "end"
    return match.group(2), "empty" if token.endswith("/>") else "start"


def attribute(token: str, name: str) -> str | None:
    match = re.search(r"(?:^|\s)" + re.escape(name) + r"\s*=\s*(\"([^\"]*)\"|'([^']*)')", token)
    if not match:
        return None
    return xml_unescape(match.group(2) if match.group(2) is not None else match.group(3))


def set_attribute(token: str, name: str, value: str) -> str:
    pattern = re.compile(r"((?:^|\s)" + re.escape(name) + r"\s*=\s*)(\"[^\"]*\"|'[^']*')")
    quoted = '"' + xml_escape(value).replace('"', "&quot;") + '"'
    return pattern.sub(lambda match: match.group(1) + quoted, token, count=1)


def rename_fonts(token: str, names: tuple[str, ...]) -> str:
    """The token with each legacy font in these attributes replaced by its Unicode font."""

    for name in names:
        value = attribute(token, name)
        font = classify_font(value)
        if font is not None:
            token = set_attribute(token, name, font.replacement)
    return token


def convert_piece(text: str, font: LegacyFont) -> str:
    return to_unicode(text, font.encoding, font.upper)


# ---- Plain text and CSV --------------------------------------------------------------------------------------

def decode_bytes(data: bytes) -> tuple[str, str]:
    """(text, how it was stored): "utf-8-sig", "utf-8" or "cp1252" (bytes undefined there kept as Latin-1)."""

    if data.startswith(b"\xef\xbb\xbf"):
        try:
            return data[3:].decode("utf-8"), "utf-8-sig"
        except UnicodeDecodeError:
            pass
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return "".join(bytes([byte]).decode("cp1252", errors="ignore") or chr(byte) for byte in data), "cp1252"


_VIETNAMESE_UNICODE = re.compile("[ăđơưĂĐƠƯĩũĨŨ\u1ea0-\u1ef9]")


def already_unicode(text: str) -> bool:
    return bool(_VIETNAMESE_UNICODE.search(text))


def analyze_text(path: Path, text: str) -> Analysis:
    if already_unicode(text):
        # Unicode already; lines pasted from an old document may still be TCVN3 or VNI: ask, offering "auto".
        if legacy.convert_lines(text, TCVN3)[1] == 0:
            return Analysis(path, note=_("This file is already in Unicode."))
        found = legacy.guess(text)
        samples = {encoding: legacy.sample(to_unicode(text, encoding)) for encoding in legacy.ENCODINGS}
        return Analysis(path, needs_choice=True, guess=legacy.Guess(found.encoding or TCVN3, False, found.scores),
                        samples=samples)
    found = legacy.guess(text)
    if found.encoding is None:
        return Analysis(path, guess=found, note=_("No TCVN3 or VNI text was found in this file."))
    samples = {encoding: legacy.sample(to_unicode(text, encoding)) for encoding in legacy.ENCODINGS}
    return Analysis(path, needs_choice=not found.confident, guess=found, samples=samples)


def convert_text(text: str, choice: str, found: legacy.Guess | None) -> tuple[str, str, int]:
    """(converted text, encoding used, lines changed) for a choice: TCVN3, VNI or LINES."""

    if choice == LINES:
        default = found.encoding if found and found.encoding else TCVN3
        converted, changed = legacy.convert_lines(text, default)
        return converted, MIXED, changed
    converted = to_unicode(text, choice)
    changed = sum(1 for old, new in zip(text.splitlines(), converted.splitlines()) if old != new)
    return converted, choice, changed


def convert_text_file(path: Path, choice: str | None) -> Result:
    text, stored = decode_bytes(path.read_bytes())
    analysis = analyze_text(path, text)
    if analysis.note:
        return Result(path, note=analysis.note)
    if choice is None:
        if analysis.needs_choice:
            raise ConversionError(_("Not sure whether this text is TCVN3 or VNI: choose one."))
        choice = analysis.guess.encoding
    converted, encoding, changed = convert_text(text, choice, analysis.guess)
    if changed == 0:
        return Result(path, note=_("No TCVN3 or VNI text was found in this file."))
    # A CSV keeps a byte order mark, so Excel on Windows reads it as Unicode too.
    bom = path.suffix.lower() == ".csv" or stored == "utf-8-sig"
    data = ("\ufeff" if bom else "").encode("utf-8") + converted.encode("utf-8")
    output, fallback = write_new(path, data)
    return Result(path, output, encoding, changed, fallback=fallback)


# ---- Web pages -----------------------------------------------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_CSS_RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")
_CSS_FONT = re.compile(r"font-family\s*:\s*([^;}]+)", re.I)
_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([\w-]+)""", re.I)


def first_family(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(",")[0].strip().strip("'\"") or None


def css_fonts(css: str) -> tuple[dict[str, str], dict[str, str]]:
    """{tag: font} and {class: font} of simple CSS rules (p {…}, .vn {…}, td.vn {…})."""

    tags, classes = {}, {}
    for selectors, body in _CSS_RULE.findall(re.sub(r"/\*.*?\*/", "", css, flags=re.S)):
        match = _CSS_FONT.search(body)
        if not match:
            continue
        font = first_family(match.group(1))
        for selector in selectors.split(","):
            selector = selector.strip().lower()
            if re.fullmatch(r"[a-z][a-z0-9]*", selector):
                tags[selector] = font
            elif re.fullmatch(r"[a-z0-9]*\.[\w-]+", selector):
                classes[selector.split(".", 1)[1]] = font
    return tags, classes


class _Page(HTMLParser):
    """Re-writes a page with the text in legacy fonts converted (or all text, with `everything`)."""

    def __init__(self, everything: LegacyFont | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[tuple[str, LegacyFont | None]] = []
        self.tags: dict[str, str] = {}
        self.classes: dict[str, str] = {}
        self.everything = everything
        self.legacy_seen = False
        self.changed = 0
        self.encodings: set[str] = set()
        self.text: list[str] = []       # the page's visible text, for guessing
        self.raw_tag = ""

    def current(self) -> LegacyFont | None:
        return self.everything if self.everything is not None else (self.stack[-1][1] if self.stack else None)

    def font_of(self, tag_name: str, attrs: dict[str, str | None]) -> LegacyFont | None:
        style = attrs.get("style") or ""
        match = _CSS_FONT.search(style)
        name = first_family(match.group(1)) if match else None
        if name is None and tag_name == "font":
            name = first_family(attrs.get("face"))
        if name is None:
            for css_class in (attrs.get("class") or "").split():
                if css_class in self.classes:
                    name = self.classes[css_class]
        if name is None:
            name = self.tags.get(tag_name)
        if name is None:
            return self.stack[-1][1] if self.stack else None
        return classify_font(name)

    def rewrite_tag(self, text: str) -> str:
        def replace(match: re.Match) -> str:
            font = classify_font(match.group(2))
            return match.group(1) + font.replacement if font else match.group(0)

        text = re.sub(r"(font-family\s*:\s*['\"]?)([^;,'\"}]+)", replace, text, flags=re.I)
        text = re.sub(r"(face\s*=\s*['\"]?)([^,'\">]+)", replace, text, flags=re.I)
        return re.sub(r"(charset\s*=\s*['\"]?)[\w-]+", lambda match: match.group(1) + "utf-8", text, flags=re.I)

    def handle_starttag(self, tag_name: str, attrs) -> None:
        values = dict(attrs)
        font = self.font_of(tag_name, values)
        self.legacy_seen |= font is not None and tag_name != "meta"
        self.out.append(self.rewrite_tag(self.get_starttag_text() or ""))
        if tag_name in ("script", "style"):
            self.raw_tag = tag_name
        if tag_name not in _VOID:
            self.stack.append((tag_name, font))

    def handle_startendtag(self, tag_name: str, attrs) -> None:
        self.out.append(self.rewrite_tag(self.get_starttag_text() or ""))

    def handle_endtag(self, tag_name: str) -> None:
        self.out.append(f"</{tag_name}>")
        if tag_name == self.raw_tag:
            self.raw_tag = ""
        if any(name == tag_name for name, _font in self.stack):
            while self.stack:
                name, _font = self.stack.pop()
                if name == tag_name:
                    break

    def handle_data(self, data: str) -> None:
        if self.raw_tag == "style":
            tags, classes = css_fonts(data)
            self.tags.update(tags)
            self.classes.update(classes)
            self.legacy_seen |= any(classify_font(font) for font in (*tags.values(), *classes.values()))
            self.out.append(self.rewrite_tag(data))
            return
        if self.raw_tag:
            self.out.append(data)
            return
        self.text.append(data)
        font = self.current()
        if font is not None and data.strip():
            converted = convert_piece(data, font)
            if converted != data:
                self.changed += 1
                self.encodings.add(font.encoding)
            data = converted
        self.out.append(html.escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        self.out.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self.out.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self.out.append(f"<?{data}>")

    def unknown_decl(self, data: str) -> None:
        self.out.append(f"<![{data}]>")


def decode_page(data: bytes) -> str:
    match = _CHARSET.search(data[:4096])
    declared = match.group(1).decode("ascii", "ignore").lower() if match else ""
    if declared in ("utf-8", "utf8"):
        try:
            return data.decode("utf-8-sig")
        except UnicodeDecodeError:
            pass
    text, _stored = decode_bytes(data)
    return text


def with_charset(page: str) -> str:
    """The page with a charset declaration (the converted page is UTF-8)."""

    if re.search(r"<meta[^>]+charset", page, re.I):
        return page
    tag_text = '<meta charset="utf-8">'
    head = re.search(r"<head\b[^>]*>", page, re.I)
    if head:
        return page[:head.end()] + tag_text + page[head.end():]
    root = re.search(r"<html\b[^>]*>", page, re.I)
    if root:
        return page[:root.end()] + f"<head>{tag_text}</head>" + page[root.end():]
    return tag_text + page


def parse_page(text: str, everything: LegacyFont | None = None) -> _Page:
    page = _Page(everything)
    page.feed(text)
    page.close()
    return page


def analyze_html(path: Path) -> Analysis:
    text = decode_page(path.read_bytes())
    page = parse_page(text)
    if page.legacy_seen:
        return Analysis(path)
    return analyze_text(path, "".join(page.text))


def convert_html_file(path: Path, choice: str | None) -> Result:
    text = decode_page(path.read_bytes())
    page = parse_page(text)
    encoding = None
    if not page.legacy_seen:
        analysis = analyze_text(path, "".join(page.text))
        if analysis.note:
            return Result(path, note=analysis.note)
        if choice is None and analysis.needs_choice:
            raise ConversionError(_("Not sure whether this text is TCVN3 or VNI: choose one."))
        encoding = choice if choice not in (None, LINES) else analysis.guess.encoding
        page = parse_page(text, LegacyFont(encoding, False, "Times New Roman"))
    if page.changed == 0:
        return Result(path, note=_("No TCVN3 or VNI text was found in this file."))
    output, fallback = write_new(path, with_charset("".join(page.out)).encode("utf-8"))
    encodings = page.encodings
    return Result(path, output, encoding or (encodings.pop() if len(encodings) == 1 else MIXED), page.changed,
                  fallback=fallback)


# ---- RTF -----------------------------------------------------------------------------------------------------

_RTF_CONTROL = re.compile(rb"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\([^a-zA-Z])")
_RTF_SKIP = {b"fonttbl", b"colortbl", b"stylesheet", b"info", b"pict", b"object", b"themedata", b"colorschememapping",
             b"latentstyles", b"datastore", b"xmlnstbl", b"listtable", b"listoverridetable", b"rsidtbl", b"generator"}


def group_end(data: bytes, start: int) -> int:
    """The index just after the group that opens at data[start] ("{")."""

    depth, index = 0, start
    while index < len(data):
        char = data[index:index + 1]
        if char == b"\\":
            index += 2
            continue
        if char == b"{":
            depth += 1
        elif char == b"}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return len(data)


def font_entries(data: bytes) -> list[tuple[int, int, int]]:
    """(number, start, end) of each {\\fN …} entry of the font table."""

    table = re.search(rb"\{\\fonttbl", data)
    if not table:
        return []
    end = group_end(data, table.start())
    entries, index = [], table.end()
    while index < end - 1:
        match = re.compile(rb"\{\\f(\d+)").search(data, index, end)
        if not match:
            break
        close = group_end(data, match.start())
        entries.append((int(match.group(1)), match.start(), close))
        index = close
    return entries


def font_name(entry: bytes) -> bytes:
    """The name in a font table entry: its text outside nested groups ({\\*\\panose …}), before the ";"."""

    body = entry[1:-1]
    text, index = bytearray(), 0
    while index < len(body):
        char = body[index:index + 1]
        if char == b"{":
            index = group_end(body, index)
            continue
        if char == b"\\":
            match = re.compile(rb"\\([a-zA-Z]+)(-?\d+)? ?|\\'[0-9a-fA-F]{2}|\\.").match(body, index)
            index = match.end() if match else index + 1
            continue
        text += char
        index += 1
    return bytes(text).split(b";")[0].strip()


def rtf_fonts(data: bytes) -> tuple[dict[int, str], int]:
    """{number: name} of the font table and the default font number (\\deff)."""

    default = re.search(rb"\\deff(\d+)", data)
    fonts = {number: font_name(data[start:end]).decode("cp1252", "replace")
             for number, start, end in font_entries(data)}
    return fonts, int(default.group(1)) if default else 0


def rewrite_font_table(data: bytes, legacy_fonts: dict[int, LegacyFont]) -> bytes:
    for number, start, end in reversed(font_entries(data)):
        font = legacy_fonts.get(number)
        if font is None:
            continue
        entry = data[start:end]
        name = font_name(entry)
        position = entry.rfind(name + b";") if name else -1
        if position < 0:
            continue
        entry = entry[:position] + font.replacement.encode("ascii") + entry[position + len(name):]
        entry = re.sub(rb"\\fcharset\d+", rb"\\fcharset0", entry, count=1)
        data = data[:start] + entry + data[end:]
    return data


def rtf_escape(text: str, fallback_chars: int) -> bytes:
    out = bytearray()
    for char in text:
        code = ord(char)
        if char in "\\{}":
            out += b"\\" + char.encode("ascii")
        elif 32 <= code < 128:
            out += char.encode("ascii")
        elif char in "\r\n":
            continue
        else:
            value = code if code < 32768 else code - 65536
            out += b"\\u" + str(value).encode("ascii") + b"?" * fallback_chars + (b" " if fallback_chars == 0 else b"")
    return bytes(out)


def convert_rtf(data: bytes) -> tuple[bytes, int, set[str]]:
    """(new RTF, pieces converted, encodings seen)."""

    fonts, default = rtf_fonts(data)
    legacy_fonts = {number: font for number, name in fonts.items() if (font := classify_font(name))}
    if not legacy_fonts:
        return data, 0, set()
    out = bytearray()
    stack: list[dict] = [{"font": default, "uc": 1, "skip": False, "table": False}]
    buffer: list[str] = []
    changed, encodings = 0, set()
    index, length = 0, len(data)

    def flush() -> None:
        nonlocal changed
        if not buffer:
            return
        font = legacy_fonts[stack[-1]["font"]]
        text = "".join(buffer)
        converted = convert_piece(text, font)
        out.extend(rtf_escape(converted, stack[-1]["uc"]))
        changed += converted != text
        encodings.add(font.encoding)
        buffer.clear()

    def in_legacy_text() -> bool:
        state = stack[-1]
        return not state["skip"] and state["font"] in legacy_fonts

    while index < length:
        char = data[index:index + 1]
        if char in (b"{", b"}"):
            flush()
            if char == b"{":
                stack.append(dict(stack[-1]))
            elif len(stack) > 1:
                stack.pop()
            out += char
            index += 1
            continue
        if char in (b"\r", b"\n"):
            if not buffer:
                out += char
            index += 1
            continue
        if char == b"\\":
            match = _RTF_CONTROL.match(data, index)
            if not match:
                out += char
                index += 1
                continue
            word, number, hexa, symbol = match.groups()
            if symbol == b"-" and in_legacy_text() and legacy_fonts[stack[-1]["font"]].encoding == TCVN3:
                buffer.append(chr(0xAD))          # TCVN3's ư is Windows-1252's soft hyphen: RTF writes \-
                index = match.end()
                continue
            if hexa is not None and in_legacy_text():
                buffer.append(bytes([int(hexa, 16)]).decode("cp1252", errors="ignore") or chr(int(hexa, 16)))
                index = match.end()
                continue
            if word == b"u" and number is not None and in_legacy_text():
                value = int(number)
                buffer.append(chr(value + 65536 if value < 0 else value))
                index = match.end()
                for _skip in range(stack[-1]["uc"]):   # the fallback characters after \uN
                    if data[index:index + 2] == b"\\'":
                        index += 4
                    elif index < length and data[index:index + 1] not in (b"\\", b"{", b"}"):
                        index += 1
                continue
            flush()
            if word == b"bin" and number is not None:
                end = match.end() + int(number)
                out += data[index:end]
                index = end
                continue
            state = stack[-1]
            if word is not None:
                if word == b"f" and number is not None and not state["table"]:
                    state["font"] = int(number)
                elif word == b"plain":
                    state["font"] = default
                elif word == b"uc" and number is not None:
                    state["uc"] = int(number)
                elif word in _RTF_SKIP:
                    state["skip"] = True
                    state["table"] = word == b"fonttbl"
            elif symbol == b"*":
                state["skip"] = True
            out += data[index:match.end()]
            index = match.end()
            continue
        # plain text bytes
        end = index
        while end < length and data[end:end + 1] not in (b"\\", b"{", b"}", b"\r", b"\n"):
            end += 1
        if in_legacy_text():
            buffer.append(data[index:end].decode("cp1252", errors="replace"))
        else:
            out += data[index:end]
        index = end
    flush()
    return rewrite_font_table(bytes(out), legacy_fonts), changed, encodings


def convert_rtf_file(path: Path) -> Result:
    data, changed, encodings = convert_rtf(path.read_bytes())
    if changed == 0:
        return Result(path, note=_("No text in a TCVN3 or VNI font was found in this file."))
    output, fallback = write_new(path, data)
    return Result(path, output, encodings.pop() if len(encodings) == 1 else MIXED, changed, fallback=fallback)


# ---- Word (.docx) --------------------------------------------------------------------------------------------

_W_FONT_ATTRIBUTES = ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia")
_WORD_TEXT_PARTS = re.compile(r"word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$")
_DRAWING_PARTS = re.compile(r"(word|ppt|xl)/(charts|diagrams|drawings)/[^/]+\.xml$")


def _font_attributes(token: str) -> dict[str, str]:
    return {name: value for name, value in re.findall(r'w:(\w+)="([^"]*)"', token)}


class WordStyles:
    """The fonts of styles.xml: docDefaults, styles with their basedOn chains, and the theme's fonts."""

    def __init__(self, styles: str | None, theme: str | None) -> None:
        self.defaults: dict[str, str] = {}
        self.styles: dict[str, tuple[str | None, dict[str, str]]] = {}
        self.default_paragraph: str | None = None
        self.theme = {"minor": None, "major": None}
        if theme:
            for kind in ("minor", "major"):
                match = re.search(rf"<a:{kind}Font>.*?<a:latin typeface=\"([^\"]*)\"", theme, re.S)
                if match:
                    self.theme[kind] = match.group(1)
        if not styles:
            return
        defaults = re.search(r"<w:rPrDefault>(.*?)</w:rPrDefault>", styles, re.S)
        if defaults:
            fonts = re.search(r"<w:rFonts\b[^>]*>", defaults.group(1))
            self.defaults = _font_attributes(fonts.group(0)) if fonts else {}
        for head, body in re.findall(r"<w:style\b([^>]*)>(.*?)</w:style>", styles, re.S):
            style_id = re.search(r'w:styleId="([^"]*)"', head)
            if not style_id:
                continue
            if 'w:type="paragraph"' in head and 'w:default="1"' in head:
                self.default_paragraph = style_id.group(1)
            own = re.sub(r"<w:pPr>.*?</w:pPr>|<w:tblStylePr\b.*?</w:tblStylePr>", "", body, flags=re.S)
            based = re.search(r'<w:basedOn w:val="([^"]*)"', own)
            fonts = re.search(r"<w:rFonts\b[^>]*>", own)
            self.styles[style_id.group(1)] = (based.group(1) if based else None,
                                              _font_attributes(fonts.group(0)) if fonts else {})

    def chain(self, style_id: str | None) -> list[dict[str, str]]:
        found, seen = [], set()
        while style_id and style_id in self.styles and style_id not in seen and len(seen) < 32:
            seen.add(style_id)
            based, fonts = self.styles[style_id]
            found.append(fonts)
            style_id = based
        return found

    def font(self, which: str, direct: dict[str, str], run_style: str | None,
             paragraph_style: str | None) -> str | None:
        levels = [direct, *self.chain(run_style), *self.chain(paragraph_style or self.default_paragraph),
                  self.defaults]
        for fonts in levels:
            theme = fonts.get(which + "Theme")
            if theme:
                return self.theme["major" if theme.startswith("major") else "minor"]
            if fonts.get(which):
                return fonts[which]
        return None


def convert_word_part(xml: str, styles: WordStyles) -> tuple[str, int, set[str]]:
    """Convert the text of runs in legacy fonts. Word keeps TCVN3's ư (byte 0xAD, a soft hyphen in Windows-1252) as
    <w:softHyphen/>, and some characters as <w:sym w:font=… w:char=…/>: those become text too."""

    tokens = _TOKEN.findall(xml)
    stack: list[str] = []
    paragraphs: list[str | None] = []
    runs: list[dict] = []
    converting: LegacyFont | None = None
    changed, encodings = 0, set()

    def run_font() -> LegacyFont | None:
        run = runs[-1]
        paragraph_style = paragraphs[-1] if paragraphs else None
        font = (styles.font("hAnsi", run["fonts"], run["style"], paragraph_style)
                or styles.font("ascii", run["fonts"], run["style"], paragraph_style))
        return classify_font(font)

    for position, token in enumerate(tokens):
        name, kind = tag(token)
        if kind == "start":
            if name == "w:p":
                paragraphs.append(None)
            elif name == "w:r":
                runs.append({"style": None, "fonts": {}})
            elif name in ("w:t", "w:delText") and stack and stack[-1] == "w:r" and runs:
                converting = run_font()
            stack.append(name)
        elif kind == "empty":
            parent = stack[-1] if stack else ""
            grandparent = stack[-2] if len(stack) > 1 else ""
            if name == "w:pStyle" and parent == "w:pPr" and grandparent == "w:p" and paragraphs:
                paragraphs[-1] = attribute(token, "w:val")
            elif parent == "w:rPr" and grandparent == "w:r" and runs:
                if name == "w:rStyle":
                    runs[-1]["style"] = attribute(token, "w:val")
                elif name == "w:rFonts":
                    runs[-1]["fonts"] = _font_attributes(token)
            elif name == "w:softHyphen" and parent == "w:r" and runs:
                font = run_font()
                if font is not None and font.encoding == TCVN3:
                    tokens[position] = f"<w:t>{convert_piece(chr(0xAD), font)}</w:t>"
                    changed += 1
                    encodings.add(TCVN3)
            elif name == "w:sym" and parent == "w:r":
                font = classify_font(attribute(token, "w:font"))
                code = attribute(token, "w:char") or ""
                if font is not None and re.fullmatch(r"[0-9A-Fa-f]{2,4}", code):
                    text = convert_piece(chr(int(code, 16) & 0xFF), font)
                    tokens[position] = f'<w:t xml:space="preserve">{xml_escape(text)}</w:t>'
                    changed += 1
                    encodings.add(font.encoding)
            if name == "w:rFonts":
                tokens[position] = rename_fonts(token, _W_FONT_ATTRIBUTES)
        elif kind == "end":
            if stack:
                stack.pop()
            if name in ("w:t", "w:delText"):
                converting = None
            elif name == "w:r" and runs:
                runs.pop()
            elif name == "w:p" and paragraphs:
                paragraphs.pop()
        elif kind == "text" and converting is not None and stack and stack[-1] in ("w:t", "w:delText"):
            text = xml_unescape(token)
            converted = convert_piece(text, converting)
            if converted != text:
                tokens[position] = xml_escape(converted)
                changed += 1
                encodings.add(converting.encoding)
    return "".join(tokens), changed, encodings


def rename_word_fonts(xml: str) -> str:
    return re.sub(r"<w:rFonts\b[^>]*>", lambda match: rename_fonts(match.group(0), _W_FONT_ATTRIBUTES), xml)


# ---- DrawingML text (PowerPoint, and charts, SmartArt and shapes in every OOXML file) -------------------------

_THEME_FONT = re.compile(r"\+(mn|mj)-(lt|ea|cs)")


def theme_fonts(theme: str | None) -> dict[str, str | None]:
    fonts = {"mn": None, "mj": None}
    for key, kind in (("mn", "minor"), ("mj", "major")):
        match = re.search(rf"<a:{kind}Font>.*?<a:latin typeface=\"([^\"]*)\"", theme or "", re.S)
        if match:
            fonts[key] = match.group(1)
    return fonts


def level_fonts(xml: str) -> dict[int, str]:
    """{level: typeface} of <a:lvlNpPr><a:defRPr><a:latin typeface=…> in a list style or text style."""

    found = {}
    for level, body in re.findall(r"<a:lvl(\d)pPr\b[^>]*>(.*?)</a:lvl\1pPr>", xml, re.S):
        match = re.search(r"<a:defRPr\b[^>]*>.*?<a:latin typeface=\"([^\"]*)\"", body, re.S)
        if match:
            found[int(level) - 1] = match.group(1)
    return found


class SlideFonts:
    """Where a run without its own font gets it: the slide master's text styles, then the theme."""

    def __init__(self, master: str | None, theme: str | None, default_style: str | None = None) -> None:
        self.theme = theme_fonts(theme)
        styles = {"title": "+mj-lt", "body": "+mn-lt", "other": "+mn-lt"}
        self.levels: dict[str, dict[int, str]] = {key: {} for key in styles}
        for key in styles:
            match = re.search(rf"<p:{key}Style>(.*?)</p:{key}Style>", master or "", re.S)
            if match:
                self.levels[key] = level_fonts(match.group(1))
        if default_style:
            self.levels["other"] = {**level_fonts(default_style), **self.levels["other"]}
        self.styles = styles

    def resolve(self, typeface: str | None) -> str | None:
        if typeface is None:
            return None
        match = _THEME_FONT.fullmatch(typeface)
        if match:
            return self.theme[match.group(1)]
        return typeface

    def default(self, placeholder: str | None, level: int) -> str | None:
        key = "title" if placeholder in ("title", "ctrTitle") else "other" if placeholder is None else "body"
        levels = self.levels[key]
        return self.resolve(levels.get(level, levels.get(0, self.styles[key])))


def convert_drawing_part(xml: str, fonts: SlideFonts | None) -> tuple[str, int, set[str]]:
    tokens = _TOKEN.findall(xml)
    stack: list[str] = []
    shapes: list[dict] = []          # placeholder type and list-style fonts of the shapes we are in
    level = 0
    run_font: str | None = None
    converting: LegacyFont | None = None
    changed, encodings = 0, set()
    in_list_style = 0
    for position, token in enumerate(tokens):
        name, kind = tag(token)
        if kind in ("start", "empty"):
            parent = stack[-1] if stack else ""
            if name in ("p:sp", "p:graphicFrame", "xdr:sp", "cdr:sp") and kind == "start":
                shapes.append({"placeholder": None, "levels": {}})
            elif name == "p:ph" and shapes:
                shapes[-1]["placeholder"] = attribute(token, "type") or "body"
            elif name == "a:lstStyle" and kind == "start":
                in_list_style += 1
            elif name == "a:pPr" and not in_list_style:
                level = int(attribute(token, "lvl") or 0)
            elif name in ("a:r", "a:fld") and kind == "start":
                run_font = None
            elif name == "a:latin" and parent == "a:rPr" and len(stack) > 1 and stack[-2] in ("a:r", "a:fld"):
                run_font = attribute(token, "typeface")
            elif name == "a:latin" and in_list_style and shapes:
                for depth in range(len(stack) - 1, -1, -1):
                    match = re.fullmatch(r"a:lvl(\d)pPr", stack[depth])
                    if match:
                        shapes[-1]["levels"][int(match.group(1)) - 1] = attribute(token, "typeface")
                        break
            elif name == "a:t" and kind == "start" and parent in ("a:r", "a:fld"):
                font = run_font
                if font is None and shapes and level in shapes[-1]["levels"]:
                    font = shapes[-1]["levels"][level]
                if fonts is not None:
                    font = fonts.resolve(font) if font else fonts.default(shapes[-1]["placeholder"] if shapes else None,
                                                                          level)
                converting = classify_font(font)
            if name in ("a:latin", "a:ea", "a:cs"):
                tokens[position] = rename_fonts(token, ("typeface",))
            if kind == "start":
                stack.append(name)
        elif kind == "end":
            if stack:
                stack.pop()
            if name == "a:t":
                converting = None
            elif name == "a:lstStyle":
                in_list_style -= 1
            elif name == "a:p":
                level = 0
            elif name in ("p:sp", "p:graphicFrame", "xdr:sp", "cdr:sp") and shapes:
                shapes.pop()
        elif kind == "text" and converting is not None and stack and stack[-1] == "a:t":
            text = xml_unescape(token)
            converted = convert_piece(text, converting)
            if converted != text:
                tokens[position] = xml_escape(converted)
                changed += 1
                encodings.add(converting.encoding)
    return "".join(tokens), changed, encodings


def rename_typefaces(xml: str) -> str:
    return re.sub(r"<a:(?:latin|ea|cs)\b[^>]*>", lambda match: rename_fonts(match.group(0), ("typeface",)), xml)


# ---- Excel (.xlsx) -------------------------------------------------------------------------------------------

def excel_cell_fonts(styles: str | None) -> list[LegacyFont | None]:
    """The legacy font (or None) of each cell format (cellXfs) of styles.xml, by index."""

    if not styles:
        return []
    fonts_block = re.search(r"<fonts\b[^>]*>(.*?)</fonts>", styles, re.S)
    names = []
    for font in re.findall(r"<font\b[^>]*?(?:/>|>(.*?)</font>)", fonts_block.group(1) if fonts_block else "", re.S):
        match = re.search(r'<name val="([^"]*)"', font or "")
        names.append(classify_font(xml_unescape(match.group(1))) if match else None)
    formats = re.search(r"<cellXfs\b[^>]*>(.*?)</cellXfs>", styles, re.S)
    result = []
    for xf in re.findall(r"<xf\b[^>]*>", formats.group(1) if formats else ""):
        font_id = re.search(r'fontId="(\d+)"', xf)
        index = int(font_id.group(1)) if font_id else 0
        result.append(names[index] if index < len(names) else None)
    return result


def convert_rich(body: str, cell_font: LegacyFont | None) -> tuple[str, int, set[str]]:
    """A shared string, inline string or comment: plain <t>, or runs <r> with their own <rFont>."""

    changed, encodings = 0, set()

    def text_of(segment: str, font: LegacyFont | None) -> str:
        nonlocal changed

        def replace(match: re.Match) -> str:
            nonlocal changed
            text = xml_unescape(match.group(2))
            converted = convert_piece(text, font)
            if converted == text:
                return match.group(0)
            changed += 1
            encodings.add(font.encoding)
            return match.group(1) + xml_escape(converted) + match.group(3)

        if font is None:
            return segment
        return re.sub(r"(<t\b[^>]*>)(.*?)(</t>)", replace, segment, flags=re.S)

    if "<r>" not in body and "<r " not in body:
        return text_of(body, cell_font), changed, encodings

    def run(match: re.Match) -> str:
        segment = match.group(0)
        own = re.search(r'<rFont val="([^"]*)"', segment)
        font = classify_font(xml_unescape(own.group(1))) if own else cell_font
        segment = text_of(segment, font)
        return re.sub(r'(<rFont val=")([^"]*)(")', lambda found: found.group(1) + (
            classify_font(xml_unescape(found.group(2))).replacement if classify_font(xml_unescape(found.group(2)))
            else found.group(2)) + found.group(3), segment)

    # Phonetic runs (<rPh>) belong to East Asian text and stay as they are.
    body = re.sub(r"<r\b[^>]*>.*?</r>", run, body, flags=re.S)
    return body, changed, encodings


_CELL = re.compile(r"<c\b([^>]*?)(/>|>(.*?)</c>)", re.S)


def convert_xlsx_parts(parts: dict[str, bytes]) -> tuple[dict[str, bytes], int, set[str]]:
    styles = parts.get("xl/styles.xml", b"").decode("utf-8") or None
    cell_fonts = excel_cell_fonts(styles)
    changed, encodings = 0, set()
    shared_xml = parts.get("xl/sharedStrings.xml", b"").decode("utf-8")
    shared = re.findall(r"<si>(.*?)</si>|<si/>", shared_xml, re.S) if shared_xml else []
    sheets = sorted(name for name in parts if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
    usage: dict[int, dict[LegacyFont | None, list[tuple[str, int]]]] = {}   # string -> font -> cells

    def font_of(attributes: str) -> LegacyFont | None:
        style = re.search(r'\bs="(\d+)"', attributes)
        index = int(style.group(1)) if style else 0
        return cell_fonts[index] if index < len(cell_fonts) else None

    texts: dict[str, str] = {}
    sheet_cells: dict[str, list[str]] = {}       # the cells that show a shared string, put back after
    for sheet in sheets:
        xml = parts[sheet].decode("utf-8")
        cells: list[str] = []
        sheet_cells[sheet] = cells

        def cell(match: re.Match) -> str:
            nonlocal changed
            attributes, body = match.group(1), match.group(3) or ""
            kind = re.search(r'\bt="(\w+)"', attributes)
            kind = kind.group(1) if kind else "n"
            font = font_of(attributes)
            if kind == "s":
                value = re.search(r"<v>(\d+)</v>", body)
                if value:
                    usage.setdefault(int(value.group(1)), {}).setdefault(font, []).append((sheet, len(cells)))
                cells.append(match.group(0))
                return f"\x00CELL{len(cells) - 1}\x00"
            if font is not None and kind == "inlineStr":
                new_body, count, seen = convert_rich(body, font)
                changed += count
                encodings.update(seen)
                return match.group(0).replace(body, new_body, 1) if count else match.group(0)
            if font is not None and kind == "str":
                def literal(found: re.Match) -> str:
                    return found.group(1) + convert_piece(found.group(2), font) + found.group(3)

                new_body = re.sub(r"(<v>)(.*?)(</v>)", lambda found: found.group(1) + xml_escape(
                    convert_piece(xml_unescape(found.group(2)), font)) + found.group(3), body, flags=re.S)
                new_body = re.sub(r"(<f\b[^>]*>)(.*?)(</f>)", lambda found: found.group(1) + re.sub(
                    r'(&quot;|")((?:(?!&quot;|").)*)(&quot;|")', literal, found.group(2)) + found.group(3), new_body,
                                  flags=re.S)
                if new_body != body:
                    changed += 1
                    encodings.add(font.encoding)
                    return match.group(0).replace(body, new_body, 1)
            return match.group(0)

        texts[sheet] = _CELL.sub(cell, xml)

    # Shared strings: convert in place when every cell that shows a string gives the same result, else add a
    # converted copy for the cells in a legacy font (the same text can be in a Unicode font elsewhere).
    new_strings = list(shared)
    repoint: dict[tuple[str, int], int] = {}
    for index, by_font in usage.items():
        if index >= len(shared) or shared[index] is None:
            continue
        results = {font: convert_rich(shared[index], font) for font in by_font}
        in_place_font = None if None in by_font else next(iter(by_font))
        in_place = results[in_place_font]
        new_strings[index] = in_place[0]
        changed += in_place[1]
        encodings.update(in_place[2])
        for font, (body, count, seen) in results.items():
            if body == in_place[0]:
                continue
            new_strings.append(body)
            changed += count
            encodings.update(seen)
            for place in by_font[font]:
                repoint[place] = len(new_strings) - 1
    out = dict(parts)
    for sheet in sheets:
        cells = sheet_cells[sheet]
        xml = texts[sheet]

        def put_back(match: re.Match) -> str:
            number = int(match.group(1))
            original = cells[number]
            if (sheet, number) in repoint:
                return re.sub(r"<v>\d+</v>", f"<v>{repoint[(sheet, number)]}</v>", original, count=1)
            return original

        xml = re.sub(r"\x00CELL(\d+)\x00", put_back, xml)
        out[sheet] = xml.encode("utf-8")
    if shared_xml and (new_strings != shared):
        items = "".join(f"<si>{body}</si>" for body in new_strings)
        start = re.search(r"<sst\b[^>]*>", shared_xml)
        head = start.group(0)
        head = re.sub(r'uniqueCount="\d+"', f'uniqueCount="{len(new_strings)}"', head)
        head = re.sub(r'\bcount="(\d+)"', lambda match: f'count="{max(int(match.group(1)), len(new_strings))}"', head)
        end = shared_xml.rfind("</sst>")
        out["xl/sharedStrings.xml"] = (shared_xml[:start.start()] + head + items + shared_xml[end:]).encode("utf-8")
    for name in parts:
        if re.fullmatch(r"xl/comments\d*\.xml", name):
            xml = parts[name].decode("utf-8")

            def comment(match: re.Match) -> str:
                nonlocal changed
                body, count, seen = convert_rich(match.group(2), None)
                changed += count
                encodings.update(seen)
                return match.group(1) + body + match.group(3)

            out[name] = re.sub(r"(<text>)(.*?)(</text>)", comment, xml, flags=re.S).encode("utf-8")
    if styles:
        out["xl/styles.xml"] = re.sub(r'(<name val=")([^"]*)(")', lambda match: match.group(1) + (
            classify_font(xml_unescape(match.group(2))).replacement if classify_font(xml_unescape(match.group(2)))
            else match.group(2)) + match.group(3), styles).encode("utf-8")
    return out, changed, encodings


# ---- OpenDocument (.odt, .ods, .odp) -------------------------------------------------------------------------

_ODF_CONTEXT = {"text:p": "paragraph", "text:h": "paragraph", "text:span": "text", "table:table-cell": "table-cell",
                "table:covered-table-cell": "table-cell"}
_ODF_SHAPES = ("draw:frame", "draw:custom-shape", "draw:rect", "draw:ellipse", "draw:text-box", "draw:polygon")


class OdfStyles:
    """Fonts of style:style and style:default-style elements (both files), with their parents and font faces."""

    def __init__(self, *documents: str) -> None:
        self.faces: dict[str, str] = {}
        self.styles: dict[tuple[str, str], tuple[str | None, str | None]] = {}
        self.defaults: dict[str, str | None] = {}
        for xml in documents:
            for token in re.findall(r"<style:font-face\b[^>]*>", xml):
                name = attribute(token, "style:name")
                family = attribute(token, "svg:font-family")
                if name:
                    self.faces[name] = (family or name).strip().strip("'\"")
            current: tuple | None = None
            for token in _TOKEN.findall(xml):
                name, kind = tag(token)
                if name in ("style:style", "style:default-style") and kind in ("start", "empty"):
                    family = attribute(token, "style:family") or ""
                    if name == "style:default-style":
                        current = ("default", family)
                        self.defaults.setdefault(family, None)
                    else:
                        style_name = attribute(token, "style:name") or ""
                        current = ("style", family, style_name)
                        self.styles[(family, style_name)] = (attribute(token, "style:parent-style-name"), None)
                    if kind == "empty":
                        current = None
                elif name == "style:text-properties" and current is not None:
                    font = attribute(token, "style:font-name")
                    font = self.faces.get(font, font) if font else attribute(token, "fo:font-family")
                    if font:
                        font = font.strip().strip("'\"")
                        if current[0] == "default":
                            self.defaults[current[1]] = font
                        else:
                            parent, _old = self.styles[(current[1], current[2])]
                            self.styles[(current[1], current[2])] = (parent, font)
                elif name in ("style:style", "style:default-style") and kind == "end":
                    current = None

    def font(self, family: str, name: str | None) -> str | None:
        seen = set()
        while name and (family, name) not in seen and len(seen) < 32:
            seen.add((family, name))
            parent, font = self.styles.get((family, name), (None, None))
            if font:
                return font
            name = parent
        return None


def _expand_columns(columns: list[tuple[str | None, int]], index: int) -> str | None:
    position = 0
    for style, repeat in columns:
        if index < position + repeat:
            return style
        position += repeat
    return None


def convert_odf_part(xml: str, styles: OdfStyles) -> tuple[str, int, set[str]]:
    tokens = _TOKEN.findall(xml)
    stack: list[tuple[str, str | None]] = []        # element, font
    tables: list[dict] = []
    changed, encodings = 0, set()
    paragraph_default = styles.defaults.get("paragraph")
    for position, token in enumerate(tokens):
        name, kind = tag(token)
        if kind in ("start", "empty"):
            inherited = stack[-1][1] if stack else None
            font = inherited
            if name == "table:table" and kind == "start":
                tables.append({"columns": [], "column": 0})
            elif name == "table:table-column" and tables:
                repeat = int(attribute(token, "table:number-columns-repeated") or 1)
                tables[-1]["columns"].append((attribute(token, "table:default-cell-style-name"), repeat))
            elif name == "table:table-row" and tables:
                tables[-1]["column"] = 0
            if name in _ODF_CONTEXT:
                family = _ODF_CONTEXT[name]
                style = attribute(token, "text:style-name") or attribute(token, "table:style-name")
                if family == "table-cell" and tables:
                    table = tables[-1]
                    if style is None:
                        style = _expand_columns(table["columns"], table["column"])
                    table["column"] += int(attribute(token, "table:number-columns-repeated") or 1)
                own = styles.font(family, style)
                if own is None and family == "table-cell":
                    own = styles.font(family, "Default") or styles.defaults.get("table-cell")
                if own is None and family == "paragraph" and inherited is None:
                    own = paragraph_default
                font = own or inherited
            elif name in _ODF_SHAPES:
                style = attribute(token, "presentation:style-name") or attribute(token, "draw:style-name")
                family = "presentation" if attribute(token, "presentation:style-name") else "graphic"
                font = styles.font(family, style) or inherited
            if kind == "start":
                stack.append((name, font))
        elif kind == "end":
            if stack:
                stack.pop()
            if name == "table:table" and tables:
                tables.pop()
        elif kind == "text" and stack and stack[-1][0] in ("text:p", "text:h", "text:span", "text:a"):
            legacy_font = classify_font(stack[-1][1])
            if legacy_font is None:
                continue
            text = xml_unescape(token)
            converted = convert_piece(text, legacy_font)
            if converted != text:
                tokens[position] = xml_escape(converted)
                changed += 1
                encodings.add(legacy_font.encoding)
    return "".join(tokens), changed, encodings


def rename_odf_fonts(xml: str) -> str:
    """Legacy font faces of this part become their Unicode fonts; a face of that font declared already is used
    instead, and two legacy faces of one replacement become one face."""

    faces = OdfStyles(xml).faces
    by_family = {family: name for name, family in faces.items() if classify_font(family) is None}
    mapping: dict[str, str] = {}
    for name, family in faces.items():
        font = classify_font(family) or classify_font(name)
        if font is not None:
            mapping[name] = by_family.get(font.replacement, font.replacement)
    declared = set(by_family.values())

    def face(match: re.Match) -> str:
        token = match.group(0)
        name = attribute(token, "style:name")
        if name not in mapping:
            return token
        if mapping[name] in declared:
            return ""                                    # the face of that font is declared already
        declared.add(mapping[name])
        token = set_attribute(token, "style:name", mapping[name])
        return set_attribute(token, "svg:font-family", f"'{mapping[name]}'")

    xml = re.sub(r"<style:font-face\b[^>]*?(?:/>|>.*?</style:font-face>)", face, xml, flags=re.S)
    for attribute_name in ("style:font-name", "style:font-name-asian", "style:font-name-complex"):
        xml = re.sub(r'(' + attribute_name + r'=")([^"]*)(")',
                     lambda match: match.group(1) + mapping.get(xml_unescape(match.group(2)), match.group(2))
                     + match.group(3), xml)
    return re.sub(r'(fo:font-family=")([^"]*)(")', lambda match: match.group(1) + (
        classify_font(xml_unescape(match.group(2))).replacement
        if classify_font(xml_unescape(match.group(2))) else match.group(2)) + match.group(3), xml)


# ---- Zip containers ------------------------------------------------------------------------------------------

def read_zip(path: Path) -> tuple[list[zipfile.ZipInfo], dict[str, bytes]]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            return infos, {info.filename: archive.read(info.filename) for info in infos}
    except (zipfile.BadZipFile, OSError, KeyError) as error:
        raise ConversionError(_("This file is damaged or is not really a {kind} file.").format(
            kind=path.suffix.lstrip(".").upper())) from error


def write_zip(infos: list[zipfile.ZipInfo], parts: dict[str, bytes]) -> bytes:
    """The same entries in the same order; an OpenDocument's mimetype stays first and uncompressed."""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for info in infos:
            new = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            new.compress_type = zipfile.ZIP_STORED if info.filename == "mimetype" else zipfile.ZIP_DEFLATED
            new.external_attr = info.external_attr
            archive.writestr(new, parts[info.filename])
    return buffer.getvalue()


def _decode(data: bytes) -> str:
    return data.decode("utf-8")


def convert_docx_parts(parts: dict[str, bytes]) -> tuple[dict[str, bytes], int, set[str]]:
    styles_xml = _decode(parts["word/styles.xml"]) if "word/styles.xml" in parts else None
    theme = next((_decode(data) for name, data in parts.items() if re.fullmatch(r"word/theme/theme\d*\.xml", name)),
                 None)
    styles = WordStyles(styles_xml, theme)
    out, changed, encodings = dict(parts), 0, set()
    for name, data in parts.items():
        if _WORD_TEXT_PARTS.fullmatch(name):
            xml, count, seen = convert_word_part(_decode(data), styles)
        elif _DRAWING_PARTS.fullmatch(name):
            xml, count, seen = convert_drawing_part(_decode(data), None)
        else:
            continue
        out[name] = xml.encode("utf-8")
        changed += count
        encodings |= seen
    if changed and styles_xml:
        out["word/styles.xml"] = rename_word_fonts(styles_xml).encode("utf-8")
    return out, changed, encodings


def convert_pptx_parts(parts: dict[str, bytes]) -> tuple[dict[str, bytes], int, set[str]]:
    master = next((_decode(data) for name, data in sorted(parts.items())
                   if re.fullmatch(r"ppt/slideMasters/slideMaster\d+\.xml", name)), None)
    theme = next((_decode(data) for name, data in sorted(parts.items())
                  if re.fullmatch(r"ppt/theme/theme\d+\.xml", name)), None)
    presentation = _decode(parts.get("ppt/presentation.xml", b""))
    default_style = re.search(r"<p:defaultTextStyle>(.*?)</p:defaultTextStyle>", presentation, re.S)
    fonts = SlideFonts(master, theme, default_style.group(1) if default_style else None)
    out, changed, encodings = dict(parts), 0, set()
    for name, data in parts.items():
        if re.fullmatch(r"ppt/(slides|slideLayouts|slideMasters|notesSlides|notesMasters|handoutMasters)/[^/]+\.xml",
                        name):
            xml, count, seen = convert_drawing_part(_decode(data), fonts)
        elif _DRAWING_PARTS.fullmatch(name):
            xml, count, seen = convert_drawing_part(_decode(data), None)
        else:
            continue
        out[name] = xml.encode("utf-8")
        changed += count
        encodings |= seen
    if changed:
        for name, data in parts.items():
            if re.fullmatch(r"ppt/theme/theme\d+\.xml", name):
                out[name] = rename_typefaces(_decode(data)).encode("utf-8")
            elif name == "ppt/presentation.xml":
                out[name] = rename_typefaces(_decode(data)).encode("utf-8")
    return out, changed, encodings


def convert_odf_parts(parts: dict[str, bytes]) -> tuple[dict[str, bytes], int, set[str]]:
    content = _decode(parts.get("content.xml", b""))
    styles_xml = _decode(parts.get("styles.xml", b""))
    styles = OdfStyles(styles_xml, content)
    out, changed, encodings = dict(parts), 0, set()
    for name, xml in (("content.xml", content), ("styles.xml", styles_xml)):
        if not xml:
            continue
        converted, count, seen = convert_odf_part(xml, styles)
        changed += count
        encodings |= seen
        out[name] = converted.encode("utf-8")
    if changed:
        for name in ("content.xml", "styles.xml"):
            if name in out:
                out[name] = rename_odf_fonts(_decode(out[name])).encode("utf-8")
    return out, changed, encodings


CONTAINERS = {".docx": convert_docx_parts, ".xlsx": convert_xlsx_parts, ".pptx": convert_pptx_parts,
              ".odt": convert_odf_parts, ".ods": convert_odf_parts, ".odp": convert_odf_parts}


def convert_container(path: Path, suffix: str | None = None, source: Path | None = None) -> Result:
    """An OOXML or OpenDocument file; `source` is the file the user chose when `path` is LibreOffice's copy."""

    suffix = (suffix or path.suffix).lower()
    infos, parts = read_zip(path)
    try:
        new_parts, changed, encodings = CONTAINERS[suffix](parts)
    except (UnicodeDecodeError, KeyError) as error:
        raise ConversionError(_("This file is damaged or is not really a {kind} file.").format(
            kind=suffix.lstrip(".").upper())) from error
    original = source or path
    if changed == 0:
        return Result(original, note=_("No text in a TCVN3 or VNI font was found in this file."))
    output, fallback = write_new(original, write_zip(infos, new_parts), suffix)
    return Result(original, output, encodings.pop() if len(encodings) == 1 else MIXED, changed, fallback=fallback)


# ---- .doc and .xls through LibreOffice -----------------------------------------------------------------------

def libreoffice() -> list[str] | None:
    for command in ("soffice", "libreoffice"):
        found = shutil.which(command)
        if found:
            return [found]
    if shutil.which("flatpak"):
        try:
            result = subprocess.run(["flatpak", "info", LIBREOFFICE_FLATPAK], capture_output=True, check=False,
                                    timeout=20)
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode == 0:
            return ["flatpak", "run", LIBREOFFICE_FLATPAK]
    return None


def convert_old_office(path: Path, office: Callable[[], list[str] | None] = libreoffice) -> Result:
    target = OLD_OFFICE[path.suffix.lower()]
    command = office()
    if command is None:
        raise ConversionError(_("Reading a {old} file needs LibreOffice. Open the file in your office app, save it as "
                                "{new}, and convert that file; or install LibreOffice from the App Center.").format(
            old=path.suffix.lower(), new=target))
    # In the cache (not /tmp) so that LibreOffice from Flathub can reach it; its own profile, so that a LibreOffice
    # window the user has open does not take the job.
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="caramos-unicode-", dir=cache) as work:
        work_path = Path(work)
        copy = work_path / f"document{path.suffix.lower()}"
        shutil.copyfile(path, copy)
        try:
            subprocess.run([*command, f"-env:UserInstallation=file://{work_path / 'profile'}", "--headless",
                            "--convert-to", target.lstrip("."), "--outdir", str(work_path), str(copy)],
                           capture_output=True, check=False, timeout=180)
        except (OSError, subprocess.SubprocessError) as error:
            raise ConversionError(_("LibreOffice could not open this file.")) from error
        converted = work_path / f"document{target}"
        if not converted.exists():
            raise ConversionError(_("LibreOffice could not open this file."))
        return convert_container(converted, target, source=path)


# ---- One file ------------------------------------------------------------------------------------------------

def analyze(path: Path) -> Analysis:
    suffix = path.suffix.lower()
    if suffix not in SUFFIXES:
        return Analysis(path, note=_("This kind of file cannot be converted."))
    if suffix in TEXT_SUFFIXES:
        text, _stored = decode_bytes(path.read_bytes())
        return analyze_text(path, text)
    if suffix in HTML_SUFFIXES:
        return analyze_html(path)
    return Analysis(path)


def convert(path: Path, choice: str | None = None) -> Result:
    """Convert one file. choice: TCVN3, VNI or LINES for text without fonts; None to use the guess."""

    suffix = path.suffix.lower()
    if not path.is_file():
        raise ConversionError(_("The file is no longer there."))
    if suffix in TEXT_SUFFIXES:
        return convert_text_file(path, choice)
    if suffix in HTML_SUFFIXES:
        return convert_html_file(path, choice)
    if suffix == ".rtf":
        return convert_rtf_file(path)
    if suffix in CONTAINERS:
        return convert_container(path)
    if suffix in OLD_OFFICE:
        return convert_old_office(path)
    raise ConversionError(_("This kind of file cannot be converted."))

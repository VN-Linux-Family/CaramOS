"""Gettext checks for the CaramOS Control Center applet and its Vietnamese catalog."""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
APPLET_JS = ROOT / "usr/share/caramos-ota/applets/caramos-control-center@caramos/applet.js"
PO_DIR = ROOT / "po/caramos-control-center"
VI_PO = PO_DIR / "vi.po"
POT = PO_DIR / "caramos-control-center.pot"

GETTEXT_BLOCK = """const Gettext = imports.gettext;
const TEXT_DOMAIN = 'caramos-control-center';
Gettext.bindtextdomain(TEXT_DOMAIN, '/usr/share/locale');

function _(text) {
    return Gettext.dgettext(TEXT_DOMAIN, text);
}

function ngettext(singular, plural, count) {
    return Gettext.dngettext(TEXT_DOMAIN, singular, plural, count);
}
"""

REGENERATE_HINT = (
    "regenerate the template from packages/caramos-ota with: xgettext --language=JavaScript "
    "--from-code=UTF-8 --keyword=_ --keyword=ngettext:1,2 --add-comments=Translators: "
    "--package-name=caramos-control-center -o po/caramos-control-center/caramos-control-center.pot "
    "usr/share/caramos-ota/applets/caramos-control-center@caramos/applet.js"
)

# Letters that only appear in Vietnamese text (vowels with Vietnamese diacritics, plus Đ/đ).
VIETNAMESE = re.compile("[àáâãèéêìíòóôõùúýăđĩũơưÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝĂĐĨŨƠƯẠ-ỹ]")
PLACEHOLDER = re.compile(r"%[sd]")

# A '/' after one of these starts a regular expression literal, not a division.
REGEX_PRECEDERS = set("(,=:[!&|?{};+-*%<>~^")
REGEX_KEYWORDS = {"return", "typeof", "case", "in", "of", "delete", "void", "throw", "new", "else", "do", "yield", "await"}

JS_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}
PO_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v", "\\": "\\", '"': '"'}


def decode_js_string(raw: str) -> str:
    out = []
    index = 0
    while index < len(raw):
        char = raw[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue
        nxt = raw[index + 1]
        if nxt == "x":
            out.append(chr(int(raw[index + 2:index + 4], 16)))
            index += 4
        elif nxt == "u" and raw[index + 2] == "{":
            end = raw.index("}", index)
            out.append(chr(int(raw[index + 3:end], 16)))
            index = end + 1
        elif nxt == "u":
            out.append(chr(int(raw[index + 2:index + 6], 16)))
            index += 6
        elif nxt == "\n":
            index += 2
        else:
            out.append(JS_ESCAPES.get(nxt, nxt))
            index += 2
    return "".join(out)


def scan_js(source: str):
    """Split JavaScript into comment-free code and string literals.

    Returns (code, strings): `code` is the source with comments blanked out (offsets preserved) and
    `strings` maps the offset of each quote/backtick to (quote, end offset, decoded value). Template
    literals contribute one entry per text chunk, keyed by the offset of the chunk's opening delimiter.
    """
    code = list(source)
    strings = {}
    stack = []  # '{' for a code block, '${' for a template expression
    index = 0
    length = len(source)
    last_significant = ""

    def blank(start: int, end: int) -> None:
        for position in range(start, end):
            if code[position] != "\n":
                code[position] = " "

    def scan_template_chunk(start: int) -> int:
        """Scan template text after the delimiter at `start`; return the offset after the chunk."""
        position = start + 1
        while position < length:
            char = source[position]
            if char == "\\":
                position += 2
                continue
            if char == "`":
                strings[start] = ("`", position + 1, decode_js_string(source[start + 1:position]))
                return position + 1
            if char == "$" and source[position + 1:position + 2] == "{":
                strings[start] = ("`", position, decode_js_string(source[start + 1:position]))
                stack.append("${")
                return position + 2
            position += 1
        raise ValueError(f"unterminated template literal at offset {start}")

    while index < length:
        char = source[index]
        if char in " \t\r\n":
            index += 1
            continue
        if source.startswith("//", index):
            end = source.find("\n", index)
            end = length if end == -1 else end
            blank(index, end)
            index = end
            continue
        if source.startswith("/*", index):
            end = source.index("*/", index + 2) + 2
            blank(index, end)
            index = end
            continue
        if char in "'\"":
            position = index + 1
            while source[position] != char:
                if source[position] == "\n":
                    raise ValueError(f"unterminated string at offset {index}")
                position += 2 if source[position] == "\\" else 1
            strings[index] = (char, position + 1, decode_js_string(source[index + 1:position]))
            index = position + 1
            last_significant = "string"
            continue
        if char == "`":
            index = scan_template_chunk(index)
            last_significant = "string" if source[index - 1] == "`" else "{"
            continue
        if char == "/":
            previous_word = last_significant if last_significant.isidentifier() else ""
            if last_significant == "" or last_significant in REGEX_PRECEDERS or previous_word in REGEX_KEYWORDS:
                position = index + 1
                in_class = False
                while True:
                    current = source[position]
                    if current == "\\":
                        position += 2
                        continue
                    if current == "\n":
                        raise ValueError(f"unterminated regular expression at offset {index}")
                    if current == "[":
                        in_class = True
                    elif current == "]":
                        in_class = False
                    elif current == "/" and not in_class:
                        break
                    position += 1
                position += 1
                while position < length and (source[position].isalnum() or source[position] == "_"):
                    position += 1
                index = position
                last_significant = "regex"
                continue
            index += 1
            last_significant = "/"
            continue
        if char == "{":
            stack.append("{")
            index += 1
            last_significant = "{"
            continue
        if char == "}":
            opener = stack.pop() if stack else "{"
            if opener == "${":
                index = scan_template_chunk(index)
                last_significant = "string" if source[index - 1] == "`" else "{"
            else:
                index += 1
                last_significant = "}"
            continue
        if char.isalnum() or char in "_$":
            position = index
            while position < length and (source[position].isalnum() or source[position] in "_$"):
                position += 1
            last_significant = source[index:position]
            index = position
            continue
        last_significant = char
        index += 1
    return "".join(code), strings


def parse_po(path: Path):
    """Parse a PO file into a list of entries (dicts with msgid, msgid_plural, msgstr list, flags)."""
    entries = []
    entry = None
    field = None

    def unquote(text: str) -> str:
        text = text.strip()
        if len(text) < 2 or text[0] != '"' or text[-1] != '"':
            raise ValueError(f"{path}: malformed string {text!r}")
        return re.sub(r"\\(.)", lambda match: PO_ESCAPES.get(match.group(1), match.group(1)), text[1:-1])

    def finish() -> None:
        if entry is not None and "msgid" in entry:
            entries.append(entry)

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            finish()
            entry, field = None, None
            continue
        if line.startswith("#~"):
            continue
        if entry is None:
            entry = {"flags": set(), "msgstr": {}}
        if line.startswith("#,"):
            entry["flags"].update(flag.strip() for flag in line[2:].split(","))
            continue
        if line.startswith("#"):
            continue
        if line.startswith('"'):
            if field is None:
                raise ValueError(f"{path}: continuation without a field: {raw_line!r}")
            if isinstance(field, int):
                entry["msgstr"][field] += unquote(line)
            else:
                entry[field] += unquote(line)
            continue
        keyword, _, rest = line.partition(" ")
        if "msgid" in entry and keyword in ("msgctxt", "msgid") and entry["msgstr"]:
            finish()
            entry = {"flags": set(), "msgstr": {}}
        match = re.fullmatch(r"msgstr\[(\d+)\]", keyword)
        if match:
            field = int(match.group(1))
            entry["msgstr"][field] = unquote(rest)
        elif keyword == "msgstr":
            field = 0
            entry["msgstr"][0] = unquote(rest)
        elif keyword in ("msgid", "msgid_plural", "msgctxt"):
            field = keyword
            entry[keyword] = unquote(rest)
        else:
            raise ValueError(f"{path}: unexpected line {raw_line!r}")
    finish()
    return entries


def po_catalog(path: Path):
    """Map (msgid, msgid_plural or None) to its entry, skipping the header."""
    catalog = {}
    for entry in parse_po(path):
        if entry["msgid"] == "" and "msgctxt" not in entry:
            continue
        catalog[(entry["msgid"], entry.get("msgid_plural"))] = entry
    return catalog


def po_header(path: Path) -> str:
    for entry in parse_po(path):
        if entry["msgid"] == "":
            return entry["msgstr"].get(0, "")
    return ""


def applet_messages(source: str):
    """Return the set of (msgid, msgid_plural or None) used by _() and ngettext() calls.

    Raises AssertionError when a call does not pass literal strings, so every message stays
    extractable by xgettext.
    """
    code, strings = scan_js(source)
    messages = set()

    def literal_at(position: int, where: str):
        while code[position].isspace():
            position += 1
        if position not in strings or strings[position][0] not in "'\"":
            raise AssertionError(f"{where}: expected a quoted string literal at offset {position}")
        quote, end, value = strings[position]
        return value, end

    def expect(position: int, token: str, where: str) -> int:
        while code[position].isspace():
            position += 1
        if not code.startswith(token, position):
            raise AssertionError(f"{where}: expected {token!r} at offset {position}, found {code[position:position + 20]!r}")
        return position + len(token)

    for match in re.finditer(r"(?<![\w$.])(_|ngettext)\(", code):
        start = match.start()
        if any(begin < start < end for begin, (quote, end, _value) in strings.items()):
            continue
        if re.search(r"function\s+$", code[max(0, start - 20):start]):
            continue
        line = code.count("\n", 0, start) + 1
        where = f"applet.js:{line} {match.group(1)}()"
        if match.group(1) == "_":
            msgid, end = literal_at(match.end(), where)
            expect(end, ")", where)
            messages.add((msgid, None))
        else:
            singular, end = literal_at(match.end(), where)
            end = expect(end, ",", where)
            plural, end = literal_at(end, where)
            expect(end, ",", where)
            messages.add((singular, plural))
    return messages


class ControlCenterGettextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source = APPLET_JS.read_text(encoding="utf-8")
        cls.messages = applet_messages(cls.source)
        cls.catalog = po_catalog(VI_PO)

    def test_applet_uses_its_own_gettext_domain(self) -> None:
        self.assertIn(GETTEXT_BLOCK, self.source)
        self.assertEqual(1, len(re.findall(r"\bfunction _\(", self.source)))
        self.assertEqual(1, len(re.findall(r"\bfunction ngettext\(", self.source)))
        self.assertNotRegex(self.source, r"function _\(\s*(\w+)\s*\)\s*\{\s*return\s+\1\s*;?\s*\}")
        self.assertNotRegex(self.source, r"(?:const|let|var)\s+(?:_|ngettext)\s*=")
        self.assertGreater(len(self.messages), 100)

    def test_string_literals_are_not_vietnamese(self) -> None:
        _code, strings = scan_js(self.source)
        offenders = [
            f"applet.js:{self.source.count(chr(10), 0, start) + 1}: {value!r}"
            for start, (_quote, _end, value) in sorted(strings.items())
            if VIETNAMESE.search(value)
        ]
        self.assertEqual([], offenders, "user-visible text must be an English msgid translated in vi.po")

    def test_every_message_has_a_vietnamese_translation(self) -> None:
        missing = []
        for msgid, plural in sorted(self.messages, key=lambda item: item[0]):
            entry = self.catalog.get((msgid, plural))
            if entry is None:
                missing.append(f"{msgid!r}: not in vi.po")
                continue
            if "fuzzy" in entry["flags"]:
                missing.append(f"{msgid!r}: fuzzy")
            translations = [entry["msgstr"].get(index, "") for index in range(max(1, len(entry["msgstr"])))]
            if not all(translations):
                missing.append(f"{msgid!r}: empty msgstr")
                continue
            expected = sorted(PLACEHOLDER.findall(msgid))
            for translation in translations:
                if sorted(PLACEHOLDER.findall(translation)) != expected:
                    missing.append(f"{msgid!r}: placeholders differ in {translation!r}")
        self.assertEqual([], missing)

    def test_vietnamese_catalog_header(self) -> None:
        header = po_header(VI_PO)
        for field in (
            "Project-Id-Version: caramos-control-center\n",
            "Language: vi\n",
            "Content-Type: text/plain; charset=UTF-8\n",
            "Plural-Forms: nplurals=1; plural=0;\n",
        ):
            self.assertIn(field, header)
        for (msgid, plural), entry in self.catalog.items():
            if plural is not None:
                self.assertEqual([0], sorted(entry["msgstr"]), msgid)

    def test_messages_have_no_template_expressions(self) -> None:
        for msgid, plural in self.messages | set(self.catalog):
            self.assertNotIn("${", msgid)
            self.assertNotIn("${", plural or "")

    def test_template_matches_applet(self) -> None:
        template = set(po_catalog(POT))
        self.assertEqual(sorted(self.messages - template, key=str), [], f"missing from the template; {REGENERATE_HINT}")
        self.assertEqual(sorted(template - self.messages, key=str), [], f"stale in the template; {REGENERATE_HINT}")

    def test_catalog_compiles(self) -> None:
        msgfmt = shutil.which("msgfmt")
        if not msgfmt:
            self.skipTest("msgfmt is unavailable")
        result = subprocess.run(
            [msgfmt, "-c", "--statistics", "-o", "/dev/null", str(VI_PO)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertNotIn("fuzzy", result.stderr)
        self.assertNotIn("untranslated", result.stderr)


if __name__ == "__main__":
    unittest.main()

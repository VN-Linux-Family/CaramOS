"""The two old Vietnamese encodings, their fonts, and a guess for text that has no fonts.

TCVN3 ("ABC", TCVN 5712:1993, table VN3) gives each Vietnamese letter its own byte in 0xA1-0xFE. It has only seven
capital letters with marks (Ă Â Ê Ô Ơ Ư Đ): a capital such as Ấ was typed with the same byte as ấ in an "H" font
(.VnTimeH, .VnArialH…), whose letters are all capitals, so text in those fonts becomes capitals here.

VNI-Windows writes a letter as its plain base letter followed by a byte for its marks (a + ù = á, a + á = ấ,
a + ê = ă, a + é = ắ), and has single bytes for đ, ơ, ư and the i family (í ì æ ó ò = í ì ỉ ĩ ị) and ỵ (î).

Both tables were written by hand for CaramOS from the published code charts and checked against well-known texts in
both encodings (see tests/test_unicode_converter.py); the TCVN3 table is also checked against glibc's TCVN5712-1
converter where iconv has it. The C1 range (0x80-0x9F) is left alone: in Word documents it holds smart quotes and
dashes that AutoCorrect typed in any font, not letters. A Word document keeps a legacy font's bytes as the
Windows-1252 characters of those bytes (0xB5 is "µ"), so the tables map characters; symbol fonts' private-use copies
(U+F000 + byte) are read too.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

TCVN3, VNI = "tcvn3", "vni"
ENCODINGS = (TCVN3, VNI)

# TCVN3 byte -> letter (lower-case fonts; the "H" fonts show the same bytes as capitals).
TCVN3_BYTES = {
    0xA1: "Ă", 0xA2: "Â", 0xA3: "Ê", 0xA4: "Ô", 0xA5: "Ơ", 0xA6: "Ư", 0xA7: "Đ",
    0xA8: "ă", 0xA9: "â", 0xAA: "ê", 0xAB: "ô", 0xAC: "ơ", 0xAD: "ư", 0xAE: "đ",
    0xB5: "à", 0xB6: "ả", 0xB7: "ã", 0xB8: "á", 0xB9: "ạ",
    0xBB: "ằ", 0xBC: "ẳ", 0xBD: "ẵ", 0xBE: "ắ", 0xC6: "ặ",
    0xC7: "ầ", 0xC8: "ẩ", 0xC9: "ẫ", 0xCA: "ấ", 0xCB: "ậ",
    0xCC: "è", 0xCE: "ẻ", 0xCF: "ẽ", 0xD0: "é", 0xD1: "ẹ",
    0xD2: "ề", 0xD3: "ể", 0xD4: "ễ", 0xD5: "ế", 0xD6: "ệ",
    0xD7: "ì", 0xD8: "ỉ", 0xDC: "ĩ", 0xDD: "í", 0xDE: "ị",
    0xDF: "ò", 0xE1: "ỏ", 0xE2: "õ", 0xE3: "ó", 0xE4: "ọ",
    0xE5: "ồ", 0xE6: "ổ", 0xE7: "ỗ", 0xE8: "ố", 0xE9: "ộ",
    0xEA: "ờ", 0xEB: "ở", 0xEC: "ỡ", 0xED: "ớ", 0xEE: "ợ",
    0xEF: "ù", 0xF1: "ủ", 0xF2: "ũ", 0xF3: "ú", 0xF4: "ụ",
    0xF5: "ừ", 0xF6: "ử", 0xF7: "ữ", 0xF8: "ứ", 0xF9: "ự",
    0xFA: "ỳ", 0xFB: "ỷ", 0xFC: "ỹ", 0xFD: "ý", 0xFE: "ỵ",
}
TCVN3_MAP = {**{byte: letter for byte, letter in TCVN3_BYTES.items()},
             **{0xF000 + byte: letter for byte, letter in TCVN3_BYTES.items()}}

# VNI: a plain vowel followed by one of these bytes. Each byte stands for a shape (circumflex, breve or none) and a
# tone; the capital bytes go with capital letters.
CIRCUMFLEX, BREVE, HORN = "\N{COMBINING CIRCUMFLEX ACCENT}", "\N{COMBINING BREVE}", "\N{COMBINING HORN}"
ACUTE, GRAVE, HOOK = "\N{COMBINING ACUTE ACCENT}", "\N{COMBINING GRAVE ACCENT}", "\N{COMBINING HOOK ABOVE}"
TILDE, DOT = "\N{COMBINING TILDE}", "\N{COMBINING DOT BELOW}"
_MARKS = {
    "ù": ("", ACUTE), "ø": ("", GRAVE), "û": ("", HOOK), "õ": ("", TILDE), "ï": ("", DOT),
    "â": (CIRCUMFLEX, ""), "á": (CIRCUMFLEX, ACUTE), "à": (CIRCUMFLEX, GRAVE), "å": (CIRCUMFLEX, HOOK),
    "ã": (CIRCUMFLEX, TILDE), "ä": (CIRCUMFLEX, DOT),
    "ê": (BREVE, ""), "é": (BREVE, ACUTE), "è": (BREVE, GRAVE), "ú": (BREVE, HOOK), "ü": (BREVE, TILDE),
    "ë": (BREVE, DOT),
}
VNI_MARKS = {**_MARKS, **{mark.upper(): value for mark, value in _MARKS.items()}}
_SINGLES = {"ô": "ơ", "ö": "ư", "ñ": "đ", "í": "í", "ì": "ì", "æ": "ỉ", "ó": "ĩ", "ò": "ị", "î": "ỵ"}
VNI_SINGLES = {**_SINGLES, **{byte.upper(): letter.upper() for byte, letter in _SINGLES.items()}}
VNI_BASES = {**{vowel: vowel for vowel in "aeiouyAEIOUY"}, "ô": "ơ", "ö": "ư", "Ô": "Ơ", "Ö": "Ư"}
_SHAPED = {CIRCUMFLEX: set("aeoAEO"), BREVE: set("aA"), "": None}

TONE_MARKS = (GRAVE, ACUTE, TILDE, HOOK, DOT)


def tcvn3_to_unicode(text: str, upper: bool = False) -> str:
    converted = text.translate(TCVN3_MAP)
    return converted.upper() if upper else converted


def vni_to_unicode(text: str) -> str:
    out: list[str] = []
    index, length = 0, len(text)
    while index < length:
        char = text[index]
        base = VNI_BASES.get(char)
        if base is not None and index + 1 < length and text[index + 1] in VNI_MARKS:
            shape, tone = VNI_MARKS[text[index + 1]]
            allowed = _SHAPED[shape]
            if allowed is None or base in allowed:
                out.append(unicodedata.normalize("NFC", base + shape + tone))
                index += 2
                continue
        out.append(VNI_SINGLES.get(char, char))
        index += 1
    return "".join(out)


def to_unicode(text: str, encoding: str, upper: bool = False) -> str:
    if encoding == TCVN3:
        return tcvn3_to_unicode(text, upper)
    if encoding == VNI:
        converted = vni_to_unicode(text)
        return converted.upper() if upper else converted
    raise ValueError(f"unknown encoding {encoding!r}")


# ---- Fonts ---------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class LegacyFont:
    encoding: str          # TCVN3 or VNI
    upper: bool            # an "H" font: every letter is a capital
    replacement: str       # the Unicode font that takes its place


_SANS = ("arial", "helve", "univer", "avant", "avo", "swiss", "gothic", "lucida", "tekni", "aptima", "optima",
         "futura", "tahoma", "verdana")
_MONO = ("courier", "couri")


def classify_font(name: str | None) -> LegacyFont | None:
    """.VnTime, .VnTimeH, .VnArial… (TCVN3) and VNI-Times, VNI-Helve… (VNI); None for any other font."""

    if not name:
        return None
    clean = name.strip().strip("'\"").strip()
    lower = clean.lower()
    if re.match(r"vni[-_ ]", lower):
        encoding, upper = VNI, False
    elif re.match(r"\.vn[a-z]", lower):
        encoding, upper = TCVN3, clean.endswith("H")
    else:
        return None
    if any(word in lower for word in _MONO):
        replacement = "Courier New"
    elif any(word in lower for word in _SANS):
        replacement = "Arial"
    else:
        replacement = "Times New Roman"
    return LegacyFont(encoding, upper, replacement)


# ---- Text without fonts: which encoding? ----------------------------------------------------------------------

_ONSETS = ("ngh", "ng", "gh", "gi", "ch", "kh", "nh", "ph", "qu", "th", "tr", "b", "c", "d", "đ", "g", "h", "k", "l",
           "m", "n", "p", "r", "s", "t", "v", "x", "")
_RIMES = frozenset("""
a ai ao au ay ac ach am an ang anh ap at ăc ăm ăn ăng ăp ăt âc âm ân âng âp ât âu ây
e ec em en eng eo ep et ê êch êm ên ênh êp êt êu
i ia ich im in inh ip it iu iêc iêm iên iêng iêp iêt iêu
o oc oi om on ong op ot oong ooc oa oac oach oai oam oan oang oanh oao oap oat oay oăc oăm oăn oăng oăt
oe oen oeo oet ô ôc ôi ôm ôn ông ôp ôt ơ ơi ơm ơn ơp ơt
u uc ui um un ung up ut ua uân uâng uât uây uê uêch uênh uy uya uych uyên uyêt uyn uynh uyp uyt uyu uơ
uôc uôi uôm uôn uông uôt ư ưa ưc ưi ưm ưn ưng ưt ưu ươc ươi ươm ươn ương ươp ươt ươu
y ya ych yn ynh yp yt yu yêm yên yêng yêt yêu
""".split())
_STOP_ENDINGS = ("c", "ch", "p", "t")
_FRONT = "eêiy"
VIETNAMESE_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzàáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợ"
                               "ùúủũụưừứửữựỳýỷỹỵ")
_WORD = re.compile(r"[^\W\d_]+")
# Latin-1 symbols that TCVN3 uses for letters (µ, ¸, ®…) and that Vietnamese text in Unicode never has.
_JUNK = frozenset(chr(code) for code in range(0xA1, 0xC0)) | {"×", "÷"}


def syllable(word: str) -> bool:
    """A Vietnamese syllable: one tone at most, an onset and a rime that exist, the c/k, g/gh, ng/ngh rules and the
    tones a syllable ending in c, ch, p or t can have."""

    decomposed = unicodedata.normalize("NFD", word.lower())
    tones = [char for char in decomposed if char in TONE_MARKS]
    if len(tones) > 1:
        return False
    bare = unicodedata.normalize("NFC", "".join(char for char in decomposed if char not in TONE_MARKS))
    tone = tones[0] if tones else ""
    for onset in _ONSETS:
        if not bare.startswith(onset):
            continue
        rime = bare[len(onset):]
        if onset == "gi" and rime == "":
            rime = "i"                       # gì
        if rime not in _RIMES:
            continue
        front = rime[0] in _FRONT
        if onset in ("k", "gh", "ngh") and not front:
            continue
        if onset in ("c", "ng") and front:
            continue
        if rime.endswith(_STOP_ENDINGS) and tone not in (ACUTE, DOT):
            continue
        return True
    return False


@dataclass(frozen=True)
class Score:
    valid: int           # words with Vietnamese marks that are real syllables
    invalid: int         # words with marks that are not, and stray symbols

    @property
    def net(self) -> int:
        return self.valid - self.invalid


def score(text: str) -> Score:
    valid = invalid = 0
    for match in _WORD.finditer(text):
        word = match.group(0)
        if word.isascii():
            continue
        lower = word.lower()
        if all(char in VIETNAMESE_LETTERS for char in lower) and syllable(lower):
            valid += 1
        else:
            invalid += 1
    invalid += sum(1 for char in text if char in _JUNK)
    return Score(valid, invalid)


@dataclass(frozen=True)
class Guess:
    encoding: str | None     # TCVN3, VNI, or None: nothing in an old encoding
    confident: bool
    scores: dict[str, Score]


def guess(text: str) -> Guess:
    """Which encoding reads as Vietnamese: the one whose words are real syllables, by a clear margin."""

    raw = score(text)
    scores = {TCVN3: score(tcvn3_to_unicode(text)), VNI: score(vni_to_unicode(text)), "raw": raw}
    best = max(ENCODINGS, key=lambda encoding: (scores[encoding].net, encoding == TCVN3))
    other = VNI if best == TCVN3 else TCVN3
    top = scores[best]
    if top.valid == 0 or top.net <= raw.net:
        return Guess(None, True, scores)
    margin = top.net - scores[other].net
    confident = top.valid >= 3 and margin >= 3 and top.invalid * 4 <= top.valid
    return Guess(best, confident, scores)


def convert_lines(text: str, default: str) -> tuple[str, int]:
    """"Auto": each line in the encoding it reads best in (unchanged when it reads best as it is), the default on a
    tie. Returns the text and how many lines changed."""

    out, changed = [], 0
    for line in text.splitlines(keepends=True):
        options = {"raw": line, TCVN3: tcvn3_to_unicode(line), VNI: vni_to_unicode(line)}
        nets = {name: score(value).net for name, value in options.items()}
        best = max(nets.values())
        if nets["raw"] == best:
            choice = "raw"
        elif nets[default] == best:
            choice = default
        else:
            choice = TCVN3 if nets[TCVN3] == best else VNI
        out.append(options[choice])
        changed += choice != "raw" and options[choice] != line
    return "".join(out), changed


def sample(text: str, limit: int = 160) -> str:
    """The first lines with letters outside ASCII, for showing what a choice would give."""

    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.isascii()]
    joined = " ".join(lines)
    return joined if len(joined) <= limit else joined[:limit].rsplit(" ", 1)[0] + "…"

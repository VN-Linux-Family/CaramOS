"""Chuyển mã sang Unicode (usr/share/caramos-ota/unicode): the TCVN3 and VNI tables, the guess for text without fonts,
each file format, the new file next to the old one, the command line and the Nemo action."""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "usr/share/caramos-ota/unicode"))

from caramos_unicode import app, formats, legacy  # noqa: E402

ACTION = ROOT / "usr/share/nemo/actions/caramos-unicode.nemo_action"
VOWELS = "aăâeêioôơuưy"
GRAVE, ACUTE, HOOK = "\N{COMBINING GRAVE ACCENT}", "\N{COMBINING ACUTE ACCENT}", "\N{COMBINING HOOK ABOVE}"
TILDE, DOT = "\N{COMBINING TILDE}", "\N{COMBINING DOT BELOW}"
TONES = ("", GRAVE, ACUTE, HOOK, TILDE, DOT)     # none, huyền, sắc, hỏi, ngã, nặng


def letters(upper: bool = False) -> list[str]:
    found = [unicodedata.normalize("NFC", vowel + tone) for vowel in VOWELS for tone in TONES] + ["đ"]
    return [letter.upper() for letter in found] if upper else found


# Texts typed in the old encodings, as they are found in documents of the 1990s and 2000s.
TCVN3_TEXTS = {
    "Céng hoµ x· héi chñ nghÜa ViÖt Nam": "Cộng hoà xã hội chủ nghĩa Việt Nam",
    "§éc lËp - Tù do - H¹nh phóc": "Độc lập - Tự do - Hạnh phúc",
    "Bé Gi¸o dôc vµ §µo t¹o": "Bộ Giáo dục và Đào tạo",
    "Tr\xadêng häc, ng\xadêi d©n, ®\xadîc": "Trường học, người dân, được",
    "QuyÕt ®Þnh cña Thñ t\xadíng ChÝnh phñ": "Quyết định của Thủ tướng Chính phủ",
    "Thµnh phè Hå ChÝ Minh, ngµy 05 th¸ng 9 n¨m 2003": "Thành phố Hồ Chí Minh, ngày 05 tháng 9 năm 2003",
    "c¬ quan, tæ chøc, ®Ò nghÞ, sö dông, tõ, mçi, cò, mïa, kú, Mü, ý kiÕn":
        "cơ quan, tổ chức, đề nghị, sử dụng, từ, mỗi, cũ, mùa, kỳ, Mỹ, ý kiến",
    "cÊp, cÇn, chuÈn, dÉn, mÆt, n¾m, b»ng, kh¼ng, s½n, trÎ, sÏ, ®Ñp, dÔ, cßn, bá":
        "cấp, cần, chuẩn, dẫn, mặt, nắm, bằng, khẳng, sẵn, trẻ, sẽ, đẹp, dễ, còn, bỏ",
}
VNI_TEXTS = {
    "Coäng hoøa xaõ hoäi chuû nghóa Vieät Nam": "Cộng hòa xã hội chủ nghĩa Việt Nam",
    "Ñoäc laäp - Töï do - Haïnh phuùc": "Độc lập - Tự do - Hạnh phúc",
    "COÄNG HOØA XAÕ HOÄI CHUÛ NGHÓA VIEÄT NAM": "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
    "Haø Noäi, Ñaø Naüng, Thöøa Thieân Hueá, Caàn Thô, Bình Döông, Soùc Traêng":
        "Hà Nội, Đà Nẵng, Thừa Thiên Huế, Cần Thơ, Bình Dương, Sóc Trăng",
    "Vónh Long, Quaûng Trò, Khaùnh Hoøa, Ñaék Laék, Haûi Phoøng, Baïc Lieâu, Phuù Thoï":
        "Vĩnh Long, Quảng Trị, Khánh Hòa, Đắk Lắk, Hải Phòng, Bạc Liêu, Phú Thọ",
    "Tröôøng hoïc, ngöôøi daân, ñöôïc, khaúng ñònh, saün saøng, maët, baèng, naém":
        "Trường học, người dân, được, khẳng định, sẵn sàng, mặt, bằng, nắm",
    "tænh, kyû nieäm, yù kieán, Myõ, moãi, treû, seõ, ñeïp, deã, söû duïng, töø, cuõ":
        "tỉnh, kỷ niệm, ý kiến, Mỹ, mỗi, trẻ, sẽ, đẹp, dễ, sử dụng, từ, cũ",
}

# The VNI keyboard's marks as bytes: a vowel, then one byte for its shape and tone (written out for the test from
# the VNI-Windows code chart, independently of legacy.VNI_MARKS).
VNI_TONE_BYTES = {"": "", ACUTE: "ù", GRAVE: "ø", HOOK: "û", TILDE: "õ", DOT: "ï"}
VNI_CIRCUMFLEX = {"": "â", ACUTE: "á", GRAVE: "à", HOOK: "å", TILDE: "ã", DOT: "ä"}
VNI_BREVE = {"": "ê", ACUTE: "é", GRAVE: "è", HOOK: "ú", TILDE: "ü", DOT: "ë"}
VNI_I = {"": "i", ACUTE: "í", GRAVE: "ì", HOOK: "æ", TILDE: "ó", DOT: "ò"}


def vni_encode(letter: str) -> str:
    upper = letter.isupper()
    decomposed = unicodedata.normalize("NFD", letter.lower())
    if decomposed == "đ":
        return "Ñ" if upper else "ñ"
    tone = next((char for char in decomposed if char in TONES[1:]), "")
    base = decomposed.replace(tone, "") if tone else decomposed
    if base == "i":
        text = VNI_I[tone]
    elif base == "y" and tone == DOT:
        text = "î"
    elif base in ("o\N{COMBINING HORN}", "u\N{COMBINING HORN}"):
        text = {"o\N{COMBINING HORN}": "ô", "u\N{COMBINING HORN}": "ö"}[base] + VNI_TONE_BYTES[tone]
    elif base.endswith("\N{COMBINING CIRCUMFLEX ACCENT}"):
        text = base[0] + VNI_CIRCUMFLEX[tone]
    elif base.endswith("\N{COMBINING BREVE}"):
        text = base[0] + VNI_BREVE[tone]
    else:
        text = base + VNI_TONE_BYTES[tone]
    return text.upper() if upper else text


def iconv(data: bytes, source: str, target: str) -> bytes | None:
    try:
        result = subprocess.run(["iconv", "-f", source, "-t", target], input=data, capture_output=True, check=False)
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


def glibc_has_tcvn3() -> bool:
    return iconv(b"\xb5", "TCVN5712-1", "UTF-8") is not None


class TableTests(unittest.TestCase):
    @unittest.skipUnless(glibc_has_tcvn3(), "iconv has no TCVN5712-1")
    def test_tcvn3_table_matches_glibc(self) -> None:
        for byte, letter in legacy.TCVN3_BYTES.items():
            glibc = unicodedata.normalize("NFC", iconv(bytes([byte]), "TCVN5712-1", "UTF-8").decode("utf-8"))
            self.assertEqual(glibc, letter, hex(byte))

    @unittest.skipUnless(glibc_has_tcvn3(), "iconv has no TCVN5712-1")
    def test_every_letter_with_every_tone_in_tcvn3(self) -> None:
        # glibc writes each lower-case letter in TCVN3; the converter reads it back, as capitals in an "H" font.
        for letter in letters():
            encoded = iconv(letter.encode("utf-8"), "UTF-8", "TCVN5712-1")
            self.assertIsNotNone(encoded, letter)
            text = encoded.decode("cp1252", errors="ignore") or chr(encoded[0])
            self.assertEqual(letter, legacy.tcvn3_to_unicode(text), letter)
            self.assertEqual(letter.upper(), legacy.tcvn3_to_unicode(text, upper=True), letter)

    def test_tcvn3_texts(self) -> None:
        for old, new in TCVN3_TEXTS.items():
            self.assertEqual(new, legacy.tcvn3_to_unicode(old))
        self.assertEqual("CỘNG HOÀ XÃ HỘI CHỦ NGHĨA VIỆT NAM",
                         legacy.tcvn3_to_unicode("Céng hoµ x· héi chñ nghÜa ViÖt Nam", upper=True))

    def test_tcvn3_keeps_smart_quotes_dashes_and_ascii(self) -> None:
        text = "“H¹nh phóc” – 2024 … ok"     # Word's AutoCorrect quotes and dashes, in any font
        self.assertEqual("“Hạnh phúc” – 2024 … ok", legacy.tcvn3_to_unicode(text))

    def test_symbol_font_copies(self) -> None:
        self.assertEqual("à", legacy.tcvn3_to_unicode(chr(0xF0B5)))

    def test_every_letter_with_every_tone_in_vni(self) -> None:
        for letter in letters() + letters(upper=True):
            self.assertEqual(letter, legacy.vni_to_unicode(vni_encode(letter)), f"{letter} {vni_encode(letter)!r}")

    def test_vni_texts(self) -> None:
        for old, new in VNI_TEXTS.items():
            self.assertEqual(new, legacy.vni_to_unicode(old))

    def test_vni_case_follows_the_base_letter(self) -> None:
        self.assertEqual("Á", legacy.vni_to_unicode("Aù"))
        self.assertEqual("á", legacy.vni_to_unicode("aÙ"))

    def test_output_is_precomposed(self) -> None:
        for text in (*TCVN3_TEXTS, *VNI_TEXTS):
            for converted in (legacy.tcvn3_to_unicode(text), legacy.vni_to_unicode(text)):
                self.assertEqual(unicodedata.normalize("NFC", converted), converted)


class FontTests(unittest.TestCase):
    def test_legacy_fonts(self) -> None:
        cases = {
            ".VnTime": (legacy.TCVN3, False, "Times New Roman"),
            ".VnTimeH": (legacy.TCVN3, True, "Times New Roman"),
            ".VnArial": (legacy.TCVN3, False, "Arial"),
            ".VnArialH": (legacy.TCVN3, True, "Arial"),
            ".VnArial NarrowH": (legacy.TCVN3, True, "Arial"),
            ".VnCourier New": (legacy.TCVN3, False, "Courier New"),
            ".VnBlackH": (legacy.TCVN3, True, "Times New Roman"),
            "VNI-Times": (legacy.VNI, False, "Times New Roman"),
            "VNI-Helve": (legacy.VNI, False, "Arial"),
            "VNI-Helve-Condense": (legacy.VNI, False, "Arial"),
            "'VNI-Times'": (legacy.VNI, False, "Times New Roman"),
        }
        for name, (encoding, upper, replacement) in cases.items():
            self.assertEqual(legacy.LegacyFont(encoding, upper, replacement), legacy.classify_font(name), name)

    def test_unicode_fonts(self) -> None:
        for name in ("Times New Roman", "Arial", "Calibri", "VnExpress Sans", "Liberation Serif", "", None):
            self.assertIsNone(legacy.classify_font(name), name)


class GuessTests(unittest.TestCase):
    TCVN3_PARAGRAPH = "\n".join(TCVN3_TEXTS)
    VNI_PARAGRAPH = "\n".join(VNI_TEXTS)

    def test_syllables(self) -> None:
        for word in ("cộng", "hoà", "nghĩa", "trường", "người", "khuỷu", "quyết", "giữa", "gì", "gìn", "kỷ", "học",
                     "huênh", "oong", "ngoằn", "thuở", "quỳnh"):
            self.assertTrue(legacy.syllable(word), word)
        for word in ("céng", "hoứa", "xaừ", "nghúa", "vieọt", "cac", "kan", "nghá", "ẹoọc", "hoọi"):
            self.assertFalse(legacy.syllable(word), word)

    def test_clear_cases(self) -> None:
        tcvn3 = legacy.guess(self.TCVN3_PARAGRAPH)
        self.assertEqual((legacy.TCVN3, True), (tcvn3.encoding, tcvn3.confident))
        vni = legacy.guess(self.VNI_PARAGRAPH)
        self.assertEqual((legacy.VNI, True), (vni.encoding, vni.confident))

    def test_unsure_and_nothing(self) -> None:
        short = legacy.guess("Haø")
        self.assertEqual((legacy.VNI, False), (short.encoding, short.confident))
        for text in ("Hello world 123", "Cộng hòa xã hội chủ nghĩa Việt Nam", ""):
            self.assertIsNone(legacy.guess(text).encoding, text)

    def test_line_by_line(self) -> None:
        text = "Céng hoµ x· héi\r\nCoäng hoøa xaõ hoäi\r\nCộng hòa xã hội\r\nplain\r\n"
        converted, changed = legacy.convert_lines(text, legacy.TCVN3)
        self.assertEqual("Cộng hoà xã hội\r\nCộng hòa xã hội\r\nCộng hòa xã hội\r\nplain\r\n", converted)
        self.assertEqual(2, changed)

    def test_sample(self) -> None:
        self.assertEqual("Cộng hoà xã hội", legacy.sample("abc\n  Cộng hoà xã hội  \n"))
        self.assertTrue(legacy.sample("Ủy ban " * 40).endswith("…"))


# ---- files -------------------------------------------------------------------------------------------------

def make_zip(path: Path, parts: dict[str, str | bytes], stored_first: str | None = None) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in parts.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_STORED if name == stored_first else zipfile.ZIP_DEFLATED
            archive.writestr(info, data if isinstance(data, bytes) else data.encode("utf-8"))


def read_zip(path: Path) -> dict[str, str]:
    with zipfile.ZipFile(path) as archive:
        return {name: archive.read(name).decode("utf-8", "replace") for name in archive.namelist()}


W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def docx(path: Path, body: str, styles: str | None = None) -> None:
    parts = {"[Content_Types].xml": "<Types/>",
             "word/document.xml": f"<w:document {W}><w:body>{body}</w:body></w:document>"}
    if styles is not None:
        parts["word/styles.xml"] = f"<w:styles {W}>{styles}</w:styles>"
    make_zip(path, parts)


def run(text: str, font: str | None = None) -> str:
    props = f'<w:rPr><w:rFonts w:ascii="{font}" w:hAnsi="{font}"/></w:rPr>' if font else ""
    return f'<w:r>{props}<w:t xml:space="preserve">{text}</w:t></w:r>'


class FileTestCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.documents = self.dir / "Tài liệu"
        self.documents.mkdir()
        patcher = mock.patch.object(formats, "documents_dir", return_value=self.documents)
        patcher.start()
        self.addCleanup(patcher.stop)


class WordTests(FileTestCase):
    def test_runs_in_legacy_fonts_only(self) -> None:
        source = self.dir / "công văn.docx"
        body = ("<w:p>" + run("Céng hoµ x· héi", ".VnTime") + run(" chñ nghÜa", ".VnTimeH")
                + run(" Vieät Nam", "VNI-Times") + run(" µ stays", "Times New Roman") + "</w:p>"
                # ư is <w:softHyphen/> in Word documents: byte 0xAD of TCVN3 is Windows-1252's soft hyphen.
                + '<w:p><w:r><w:rPr><w:rFonts w:ascii=".VnTime" w:hAnsi=".VnTime"/></w:rPr><w:t>Tr</w:t>'
                  '<w:softHyphen/><w:t>êng &amp; ng</w:t><w:softHyphen/><w:t>êi</w:t></w:r></w:p>')
        docx(source, body)
        result = formats.convert(source)
        self.assertEqual(self.dir / "công văn (Unicode).docx", result.output)
        self.assertEqual(formats.MIXED, result.encoding)
        document = read_zip(result.output)["word/document.xml"]
        self.assertIn(">Cộng hoà xã hội<", document)
        self.assertIn("> CHỦ NGHĨA<", document)
        self.assertIn("> Việt Nam<", document)
        self.assertIn("> µ stays<", document)
        self.assertIn("<w:t>Tr</w:t><w:t>ư</w:t><w:t>ờng &amp; ng</w:t><w:t>ư</w:t><w:t>ời</w:t>", document)
        self.assertNotIn(".VnTime", document)
        self.assertNotIn("VNI-Times", document)
        self.assertIn('w:ascii="Times New Roman"', document)
        self.assertEqual(read_zip(source)["word/document.xml"].count("Céng"), 1, "the old file is unchanged")

    def test_fonts_from_styles_and_defaults(self) -> None:
        source = self.dir / "a.docx"
        styles = ('<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii=".VnTime" w:hAnsi=".VnTime"/></w:rPr>'
                  '</w:rPrDefault></w:docDefaults>'
                  '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
                  '<w:style w:type="paragraph" w:styleId="Heading1"><w:basedOn w:val="Normal"/>'
                  '<w:rPr><w:rFonts w:ascii=".VnArialH" w:hAnsi=".VnArialH"/></w:rPr></w:style>'
                  '<w:style w:type="character" w:styleId="Uni"><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/>'
                  '</w:rPr></w:style>')
        body = ('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>' + run("b¸o c¸o") + "</w:p>"
                + "<w:p>" + run("n¨m häc") + '<w:r><w:rPr><w:rStyle w:val="Uni"/></w:rPr><w:t>µ</w:t></w:r></w:p>')
        docx(source, body, styles)
        parts = read_zip(formats.convert(source).output)
        self.assertIn(">BÁO CÁO<", parts["word/document.xml"])
        self.assertIn(">năm học<", parts["word/document.xml"])
        self.assertIn(">µ<", parts["word/document.xml"], "a character style in a Unicode font wins")
        self.assertNotIn(".Vn", parts["word/styles.xml"])
        self.assertIn('w:ascii="Arial" w:hAnsi="Arial"', parts["word/styles.xml"])

    def test_nothing_to_convert_writes_nothing(self) -> None:
        source = self.dir / "b.docx"
        docx(source, "<w:p>" + run("Văn bản Unicode", "Times New Roman") + "</w:p>")
        result = formats.convert(source)
        self.assertIsNone(result.output)
        self.assertTrue(result.note)
        self.assertEqual(["Tài liệu", "b.docx"], sorted(path.name for path in self.dir.iterdir()))

    def test_never_overwrites(self) -> None:
        source = self.dir / "c.docx"
        docx(source, "<w:p>" + run("Hµ Néi", ".VnTime") + "</w:p>")
        (self.dir / "c (Unicode).docx").write_text("mine", encoding="utf-8")
        first = formats.convert(source).output
        second = formats.convert(source).output
        self.assertEqual(("c (Unicode) (2).docx", "c (Unicode) (3).docx"), (first.name, second.name))
        self.assertEqual("mine", (self.dir / "c (Unicode).docx").read_text(encoding="utf-8"))

    @unittest.skipIf(os.geteuid() == 0, "root writes into read-only folders")
    def test_read_only_folder_goes_to_documents(self) -> None:
        folder = self.dir / "windows"
        folder.mkdir()
        source = folder / "d.docx"
        docx(source, "<w:p>" + run("Hµ Néi", ".VnTime") + "</w:p>")
        folder.chmod(0o555)
        self.addCleanup(folder.chmod, 0o755)
        result = formats.convert(source)
        self.assertEqual(self.documents / "d (Unicode).docx", result.output)
        self.assertTrue(result.fallback)
        self.assertIn("Documents", app.describe(result))

    def test_damaged_file(self) -> None:
        source = self.dir / "e.docx"
        source.write_bytes(b"not a zip")
        with self.assertRaises(formats.ConversionError):
            formats.convert(source)


class ExcelTests(FileTestCase):
    STYLES = ('<styleSheet><fonts count="3"><font><sz val="11"/><name val="Calibri"/></font>'
              '<font><sz val="12"/><name val=".VnTime"/></font><font><name val="VNI-Times"/></font></fonts>'
              '<cellXfs count="3"><xf numFmtId="0" fontId="0"/><xf numFmtId="0" fontId="1"/><xf fontId="2"/>'
              '</cellXfs></styleSheet>')

    def test_cells_in_legacy_fonts(self) -> None:
        source = self.dir / "bảng lương.xlsx"
        sheet = ('<worksheet><sheetData><row r="1">'
                 '<c r="A1" s="1" t="s"><v>0</v></c>'          # "Hä vµ tªn" in .VnTime
                 '<c r="B1" t="s"><v>0</v></c>'                # the same string in Calibri: it must stay
                 '<c r="C1" s="2" t="s"><v>1</v></c>'          # VNI
                 '<c r="D1" s="1" t="inlineStr"><is><t>Hµ Néi</t></is></c>'
                 '<c r="E1" s="1" t="str"><f>"Tæng: "&amp;A1</f><v>Tæng: Hä vµ tªn</v></c>'
                 '<c r="F1" s="1"><v>1990</v></c>'
                 '</row></sheetData></worksheet>')
        shared = ('<sst count="3" uniqueCount="2"><si><t>Hä vµ tªn</t></si>'
                  '<si><r><t>Ngaøy sinh </t></r><r><rPr><rFont val=".VnTime"/></rPr><t>n¨m</t></r></si></sst>')
        make_zip(source, {"[Content_Types].xml": "<Types/>", "xl/styles.xml": self.STYLES,
                          "xl/sharedStrings.xml": shared, "xl/worksheets/sheet1.xml": sheet})
        parts = read_zip(formats.convert(source).output)
        strings = parts["xl/sharedStrings.xml"]
        self.assertIn("<si><t>Hä vµ tªn</t></si>", strings, "the Calibri cell keeps its text")
        self.assertIn("<si><t>Họ và tên</t></si>", strings)
        self.assertIn('<rFont val="Times New Roman"/></rPr><t>năm</t>', strings)
        self.assertIn("<t>Ngày sinh </t>", strings)
        self.assertIn('uniqueCount="3"', strings)
        cells = parts["xl/worksheets/sheet1.xml"]
        self.assertIn('<c r="A1" s="1" t="s"><v>2</v></c>', cells)
        self.assertIn('<c r="B1" t="s"><v>0</v></c>', cells)
        self.assertIn("<is><t>Hà Nội</t></is>", cells)
        self.assertIn('<f>"Tổng: "&amp;A1</f><v>Tổng: Họ và tên</v>', cells)
        self.assertIn('<v>1990</v>', cells)
        self.assertNotIn(".VnTime", parts["xl/styles.xml"])
        self.assertIn('<name val="Times New Roman"/>', parts["xl/styles.xml"])


class SlideTests(FileTestCase):
    def test_runs_and_inherited_theme_font(self) -> None:
        source = self.dir / "trình chiếu.pptx"
        slide = ('<p:sld xmlns:a="a" xmlns:p="p"><p:cSld><p:spTree>'
                 '<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:txBody><a:p>'
                 '<a:r><a:rPr lang="vi-VN"><a:latin typeface=".VnArialH"/></a:rPr><a:t>b¸o c¸o</a:t></a:r>'
                 '</a:p></p:txBody></p:sp>'
                 '<p:sp><p:nvSpPr><p:nvPr><p:ph idx="1"/></p:nvPr></p:nvSpPr><p:txBody><a:p>'
                 '<a:r><a:rPr lang="vi-VN"/><a:t>Tæng kÕt</a:t></a:r>'
                 '<a:r><a:rPr><a:latin typeface="Arial"/></a:rPr><a:t> µ</a:t></a:r></a:p></p:txBody></p:sp>'
                 '</p:spTree></p:cSld></p:sld>')
        master = ('<p:sldMaster xmlns:a="a" xmlns:p="p"><p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr>'
                  '<a:latin typeface="+mj-lt"/></a:defRPr></a:lvl1pPr></p:titleStyle><p:bodyStyle><a:lvl1pPr>'
                  '<a:defRPr><a:latin typeface="+mn-lt"/></a:defRPr></a:lvl1pPr></p:bodyStyle></p:txStyles>'
                  '</p:sldMaster>')
        theme = ('<a:theme xmlns:a="a"><a:fontScheme><a:majorFont><a:latin typeface="Arial"/></a:majorFont>'
                 '<a:minorFont><a:latin typeface=".VnTime"/></a:minorFont></a:fontScheme></a:theme>')
        make_zip(source, {"[Content_Types].xml": "<Types/>", "ppt/slides/slide1.xml": slide,
                          "ppt/slideMasters/slideMaster1.xml": master, "ppt/theme/theme1.xml": theme})
        parts = read_zip(formats.convert(source).output)
        self.assertIn("<a:t>BÁO CÁO</a:t>", parts["ppt/slides/slide1.xml"])
        self.assertIn("<a:t>Tổng kết</a:t>", parts["ppt/slides/slide1.xml"], "the theme's body font is .VnTime")
        self.assertIn("<a:t> µ</a:t>", parts["ppt/slides/slide1.xml"])
        self.assertIn('typeface="Arial"', parts["ppt/slides/slide1.xml"])
        self.assertNotIn(".Vn", parts["ppt/slides/slide1.xml"] + parts["ppt/theme/theme1.xml"])


ODF_NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
          'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
          'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
          'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
          'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"')


class OpenDocumentTests(FileTestCase):
    def odf(self, name: str, body: str, styles: str = "", faces: str = "") -> Path:
        content = (f'<office:document-content {ODF_NS}><office:font-face-decls>{faces}</office:font-face-decls>'
                   f"<office:automatic-styles>{styles}</office:automatic-styles><office:body>{body}</office:body>"
                   "</office:document-content>")
        source = self.dir / name
        mimetype = "application/vnd.oasis.opendocument." + {"odt": "text", "ods": "spreadsheet"}[name[-3:]]
        make_zip(source, {"mimetype": mimetype, "content.xml": content, "META-INF/manifest.xml": "<m/>"},
                 stored_first="mimetype")
        return source

    FACES = ('<style:font-face style:name=".VnTime" svg:font-family="\'.VnTime\'"/>'
             '<style:font-face style:name="VNI-Times" svg:font-family="\'VNI-Times\'"/>'
             '<style:font-face style:name="Arial" svg:font-family="Arial"/>')

    def test_text_document(self) -> None:
        styles = ('<style:style style:name="P1" style:family="paragraph"><style:text-properties '
                  'style:font-name=".VnTime"/></style:style><style:style style:name="T1" style:family="text">'
                  '<style:text-properties style:font-name="VNI-Times"/></style:style>'
                  '<style:style style:name="T2" style:family="text"><style:text-properties style:font-name="Arial"/>'
                  '</style:style>')
        body = ('<office:text><text:p text:style-name="P1">Tr\xadêng häc <text:span text:style-name="T1">vaø '
                'nhaø</text:span><text:s/>®Òu <text:span text:style-name="T2">µ</text:span> tèt</text:p></office:text>')
        result = formats.convert(self.odf("thư.odt", body, styles, self.FACES))
        with zipfile.ZipFile(result.output) as archive:
            first = archive.infolist()[0]
            self.assertEqual(("mimetype", zipfile.ZIP_STORED), (first.filename, first.compress_type))
            content = archive.read("content.xml").decode("utf-8")
        self.assertIn(">Trường học <", content)
        self.assertIn(">và nhà</text:span>", content)
        self.assertIn("đều ", content)
        self.assertIn(">µ</text:span> tốt<", content, "a span in a Unicode font stays")
        self.assertNotIn(".VnTime", content)
        self.assertNotIn("VNI-Times", content)
        self.assertEqual(1, content.count('style:name="Times New Roman"'), "one face for both legacy fonts")

    def test_spreadsheet_column_styles(self) -> None:
        styles = ('<style:style style:name="ce1" style:family="table-cell"><style:text-properties '
                  'style:font-name=".VnTime"/></style:style>')
        body = ('<office:spreadsheet><table:table table:name="T">'
                '<table:table-column table:number-columns-repeated="2"/>'
                '<table:table-column table:default-cell-style-name="ce1"/><table:table-row>'
                '<table:table-cell table:number-columns-repeated="2"><text:p>µ</text:p></table:table-cell>'
                '<table:table-cell><text:p>Hµ Néi</text:p></table:table-cell></table:table-row></table:table>'
                '</office:spreadsheet>')
        content = read_zip(formats.convert(self.odf("sổ.ods", body, styles, self.FACES)).output)["content.xml"]
        self.assertIn("<text:p>µ</text:p>", content)
        self.assertIn("<text:p>Hà Nội</text:p>", content)


def u(code: int) -> bytes:
    """An RTF Unicode escape with its one fallback character."""

    return b"\\u" + str(code).encode("ascii") + b"?"


class RtfTests(FileTestCase):
    def test_font_table_escapes_and_soft_hyphen(self) -> None:
        rtf = (rb"{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\fswiss Arial;}{\f1\froman\fcharset0 .VnTime;}"
               rb"{\f2\fnil VNI-Times{\*\falt VNI Times};}}"
               rb"\pard\plain \f1 C\'e9ng ho\'b5 Tr\-\'eang \u181\'b5 x\'b7\par "
               rb"{\f2 Vie\'e4t Nam}\par \f0 \'b5 stays\par }")
        source = self.dir / "đơn.rtf"
        source.write_bytes(rtf)
        output = formats.convert(source).output.read_bytes()
        self.assertIn(rb"\fcharset0 Times New Roman;", output)
        self.assertNotIn(b".VnTime", output)
        self.assertNotIn(b"VNI-Times;", output)
        self.assertIn(b"C" + u(0x1ED9) + b"ng ho" + u(0xE0), output)              # Cộng hoà
        self.assertIn(b"Tr" + u(0x1B0) + u(0x1EDD) + b"ng", output)               # Trường: the soft hyphen was ư
        self.assertGreaterEqual(output.count(u(0xE0)), 2)                          # \u181 (µ) in .VnTime is à too
        self.assertIn(b"Vi" + u(0x1EC7) + b"t Nam", output)                       # Việt
        self.assertIn(rb"\f0 \'b5 stays", output)


class TextTests(FileTestCase):
    def test_text_and_csv(self) -> None:
        text = self.dir / "tcvn3.txt"
        text.write_bytes("Céng hoµ x· héi chñ nghÜa ViÖt Nam\r\n§éc lËp - Tù do - H¹nh phóc\r\nTr\xadêng häc\r\n"
                         .encode("cp1252"))
        result = formats.convert(text)
        self.assertEqual(legacy.TCVN3, result.encoding)
        self.assertEqual("Cộng hoà xã hội chủ nghĩa Việt Nam\r\nĐộc lập - Tự do - Hạnh phúc\r\nTrường học\r\n",
                         result.output.read_bytes().decode("utf-8"))
        table = self.dir / "danh sách.csv"
        table.write_bytes("Hoï teân,Queâ quaùn\nNguyeãn Vaên An,Haø Noäi\nTraàn Thò Bình,Ñaø Naüng\n"
                          .encode("cp1252"))
        data = formats.convert(table).output.read_bytes()
        self.assertTrue(data.startswith(b"\xef\xbb\xbf"), "a byte order mark for Excel")
        self.assertIn("Nguyễn Văn An,Hà Nội", data.decode("utf-8-sig"))

    def test_unsure_unicode_and_lines(self) -> None:
        short = self.dir / "ngắn.txt"
        short.write_bytes("Haø".encode("cp1252"))
        self.assertTrue(formats.analyze(short).needs_choice)
        with self.assertRaises(formats.ConversionError):
            formats.convert(short)
        self.assertEqual("Hà", formats.convert(short, legacy.VNI).output.read_text(encoding="utf-8"))
        unicode_file = self.dir / "unicode.txt"
        unicode_file.write_text("Cộng hòa xã hội\n", encoding="utf-8")
        self.assertIn("Unicode", formats.convert(unicode_file).note)
        mixed = self.dir / "lẫn.txt"
        mixed.write_text("Cộng hòa xã hội\nCéng hoµ x· héi\nCoäng hoøa xaõ hoäi\n", encoding="utf-8")
        analysis = formats.analyze(mixed)
        self.assertTrue(analysis.needs_choice)
        self.assertIn("Cộng hoà xã hội", analysis.samples[legacy.TCVN3])     # what line 2 reads as in TCVN3
        self.assertIn("Cộng hòa xã hội", analysis.samples[legacy.VNI])
        result = formats.convert(mixed, formats.LINES)
        self.assertEqual("Cộng hòa xã hội\nCộng hoà xã hội\nCộng hòa xã hội\n",
                         result.output.read_text(encoding="utf-8"))


class HtmlTests(FileTestCase):
    def test_fonts_css_and_charset(self) -> None:
        page = ('<html><head><meta http-equiv="Content-Type" content="text/html; charset=windows-1252">'
                '<style>.vn { font-family: ".VnTime", serif } p { color: red }</style>'
                '<script>var x = "µ";</script></head><body>'
                '<p><font face=".VnTime">Céng hoµ</font> <span style="font-family: VNI-Times">Ñoäc laäp</span></p>'
                '<p class="vn">Tr\xadêng &amp; µ</p><p>µ plain</p></body></html>')
        source = self.dir / "trang.html"
        source.write_bytes(page.encode("cp1252"))
        output = formats.convert(source).output.read_text(encoding="utf-8")
        self.assertIn("charset=utf-8", output)
        self.assertIn('<font face="Times New Roman">Cộng hoà</font>', output)
        self.assertIn("Độc lập", output)
        self.assertIn('<p class="vn">Trường &amp; à</p>', output)
        self.assertIn("<p>µ plain</p>", output)
        self.assertIn('var x = "µ";', output, "scripts stay as they are")
        self.assertNotIn(".VnTime", output)

    def test_page_without_fonts_is_guessed(self) -> None:
        source = self.dir / "cu.htm"
        source.write_bytes(("<html><body><p>" + " ".join(TCVN3_TEXTS) + "</p></body></html>").encode("cp1252"))
        output = formats.convert(source).output.read_text(encoding="utf-8")
        self.assertIn("Cộng hoà xã hội chủ nghĩa Việt Nam", output)
        self.assertIn('<html><head><meta charset="utf-8"></head>', output)


class OldOfficeTests(FileTestCase):
    def test_doc_through_libreoffice(self) -> None:
        source = self.dir / "cũ.doc"
        source.write_bytes(b"\xd0\xcf\x11\xe0 old Word")
        calls = []

        def fake_soffice(command, **_kwargs):
            calls.append(command)
            outdir = Path(command[command.index("--outdir") + 1])
            docx(outdir / "document.docx", "<w:p>" + run("Hµ Néi", ".VnTime") + "</w:p>")
            return subprocess.CompletedProcess(command, 0, b"", b"")

        with mock.patch.object(formats.subprocess, "run", side_effect=fake_soffice), \
                mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(self.dir / "cache")}):
            result = formats.convert_old_office(source, office=lambda: ["soffice"])
        self.assertEqual(self.dir / "cũ (Unicode).docx", result.output)
        self.assertIn(">Hà Nội<", read_zip(result.output)["word/document.xml"])
        self.assertIn("--headless", calls[0])
        self.assertTrue(any(part.startswith("-env:UserInstallation=") for part in calls[0]), "its own profile")

    def test_a_home_that_cannot_be_written_uses_tmp(self) -> None:
        # Launchpad's builders run with HOME=/sbuild-nonexistent.
        source = self.dir / "cũ.doc"
        source.write_bytes(b"\xd0\xcf\x11\xe0 old Word")
        outdirs = []

        def fake_soffice(command, **_kwargs):
            outdir = Path(command[command.index("--outdir") + 1])
            outdirs.append(outdir)
            docx(outdir / "document.docx", "<w:p>" + run("Hµ Néi", ".VnTime") + "</w:p>")
            return subprocess.CompletedProcess(command, 0, b"", b"")

        blocked = self.dir / "file-not-folder"
        blocked.write_text("x", encoding="utf-8")
        with mock.patch.object(formats.subprocess, "run", side_effect=fake_soffice), \
                mock.patch.dict(os.environ, {"XDG_CACHE_HOME": str(blocked / "cache")}):
            result = formats.convert_old_office(source, office=lambda: ["soffice"])
        self.assertEqual(self.dir / "cũ (Unicode).docx", result.output)
        self.assertFalse(str(outdirs[0]).startswith(str(blocked)))
        self.assertIn(">Hà Nội<", read_zip(result.output)["word/document.xml"])

    def test_without_libreoffice(self) -> None:
        source = self.dir / "bảng.xls"
        source.write_bytes(b"\xd0\xcf\x11\xe0")
        with self.assertRaises(formats.ConversionError) as raised:
            formats.convert_old_office(source, office=lambda: None)
        self.assertIn(".xlsx", str(raised.exception))


class CommandLineTests(FileTestCase):
    def test_cli(self) -> None:
        good = self.dir / "a.txt"
        good.write_bytes("\n".join(TCVN3_TEXTS).encode("cp1252"))
        unsure = self.dir / "b.txt"
        unsure.write_bytes("Haø".encode("cp1252"))
        out, err = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", out), mock.patch("sys.stderr", err):
            status = app.main([str(good), str(unsure)])
        self.assertEqual(1, status)
        self.assertIn("a (Unicode).txt", out.getvalue())
        self.assertIn("--from", err.getvalue())
        with mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(0, app.main(["--from", "vni", str(unsure)]))
        self.assertTrue((self.dir / "b (Unicode).txt").exists())


class PackagingTests(unittest.TestCase):
    def test_nemo_action(self) -> None:
        import configparser

        action = configparser.ConfigParser(interpolation=None)
        action.optionxform = str
        action.read(ACTION, encoding="utf-8")
        section = action["Nemo Action"]
        self.assertEqual("Chuyển mã sang Unicode", section["Name[vi]"])
        self.assertEqual("Convert to Unicode", section["Name"])
        self.assertEqual("/usr/bin/caramos-unicode --gui %F", section["Exec"])
        extensions = {"." + item for item in section["Extensions"].split(";") if item}
        self.assertEqual(set(formats.SUFFIXES), extensions)
        self.assertEqual("notnone", section["Selection"])

    def test_package_ships_it(self) -> None:
        install = (ROOT / "debian/install").read_text(encoding="utf-8")
        for line in ("usr/bin/caramos-unicode usr/bin/", "usr/share/caramos-ota/unicode usr/share/caramos-ota/",
                     "usr/share/nemo/actions/caramos-unicode.nemo_action usr/share/nemo/actions/"):
            self.assertIn(line, install)
        self.assertTrue(os.access(ROOT / "usr/bin/caramos-unicode", os.X_OK))


class TranslationTests(unittest.TestCase):
    def test_every_message_is_in_the_vietnamese_catalog(self) -> None:
        sys.path.insert(0, str(Path(__file__).parent))
        from test_ota_i18n import PO, msgids, source_msgids

        translated = msgids(PO)
        for path in sorted((ROOT / "usr/share/caramos-ota/unicode/caramos_unicode").glob("*.py")):
            missing = sorted(source_msgids(path) - translated)
            self.assertEqual([], missing, f"{path.name}: add these to po/caramos-ota/vi.po (see po/README.md)")


if __name__ == "__main__":
    unittest.main()

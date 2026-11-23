#!/usr/bin/env python3
"""Build the handover document template of CaramOS Doanh nghiệp ("In biên bản bàn giao", PROTOCOL.md part 3).

    tools/make-handover-template.py [--out usr/share/caramos-business/templates]

Writes bien-ban-ban-giao-tai-san.docx (OOXML, no LibreOffice needed). The output is reproducible: the same script
writes byte-identical files, which are committed. The layout is caramos-ota's "Biên bản bàn giao tài sản"
(tools/make-nd30-templates.py, Nghị định 30/2020/NĐ-CP Phụ lục I: A4, margins 20/20/30/20 mm, Times New Roman, the
two-column header with the national name), copied here so that nothing depends on caramos-ota's paths.

The window fills it (caramos_business.handover): each placeholder below is the whole text of one <w:t> element, and
the asset table has one row whose cells hold the row placeholders, copied once per asset.
"""

from __future__ import annotations

import argparse
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "usr/share/caramos-business/templates"
NAME = "bien-ban-ban-giao-tai-san.docx"
FIELDS = ("TEN_CONG_TY", "SO", "NGAY", "THANG", "NAM", "DIA_DIEM", "BEN_GIAO", "CHUC_VU_GIAO", "BEN_NHAN",
          "CHUC_VU_NHAN", "LY_DO")
ROW_FIELDS = ("STT", "TEN_TAI_SAN", "MA_SO", "DON_VI", "SO_LUONG", "TINH_TRANG", "GHI_CHU")


def slot(name: str, size: float = 14, bold: bool = False, italic: bool = False) -> "R":
    """A placeholder: a run of its own, so that it is the whole text of one <w:t>."""

    return R("{{" + name + "}}", size, bold, italic)


def cm(value: float) -> int:
    """Twentieths of a point (twips) in a centimetre length."""

    return round(value * 1440 / 2.54)


PAGE_W, PAGE_H = 11906, 16838                     # A4
MARGIN_TOP, MARGIN_BOTTOM = cm(2.0), cm(2.0)
MARGIN_LEFT, MARGIN_RIGHT = cm(3.0), cm(2.0)
HEADER_DISTANCE = cm(1.0)                         # the page number sits in the top margin
TEXT_W = PAGE_W - MARGIN_LEFT - MARGIN_RIGHT      # 16 cm
LEFT_COL = cm(6.0)                                # issuing body, number, "Nơi nhận"
RIGHT_COL = TEXT_W - LEFT_COL                     # national name, date, signature
INDENT = 720                                      # 1.27 cm, Word's default tab
# "Độc lập - Tự do - Hạnh phúc" in Times New Roman Bold 13 pt is 158.91 pt long (measured with the font's metrics;
# Liberation Serif has the same): the rule under the motto has its length.
MOTTO_RULE = 3178
BODY_RULE = cm(2.0)                               # under "TÊN CƠ QUAN, TỔ CHỨC" (5.16 cm at 12 pt): about 2/5
SUMMARY_RULE = cm(3.0)                            # under a trích yếu of 7-8 cm: about 2/5
LINE = 6                                          # rule thickness, eighths of a point
DOTS = "…"


# ---- WordprocessingML pieces ---------------------------------------------------------------------------------

@dataclass
class R:
    """A run of text."""

    text: str
    size: float = 14
    bold: bool = False
    italic: bool = False
    tab: bool = False            # a tab character (for dotted lines) instead of text

    def xml(self) -> str:
        props = []
        if self.bold:
            props.append("<w:b/><w:bCs/>")
        if self.italic:
            props.append("<w:i/><w:iCs/>")
        half_points = round(self.size * 2)
        props.append(f'<w:sz w:val="{half_points}"/><w:szCs w:val="{half_points}"/>')
        if self.tab:
            content = "<w:tab/>"
        else:   # a line break where the text has "\n"
            parts = self.text.split("\n")
            content = "<w:br/>".join(f'<w:t xml:space="preserve">{escape(part)}</w:t>' for part in parts)
        return f"<w:r><w:rPr>{''.join(props)}</w:rPr>{content}</w:r>"


@dataclass
class P:
    """A paragraph. Without overrides it is the body text of the Normal style."""

    runs: list[R] = field(default_factory=list)
    align: str | None = None         # "center", "left", "both"; None = Normal (justified)
    first_line: int | None = None    # None = Normal (1.27 cm); 0 = none
    left: int = 0
    right: int = 0
    before: int | None = None        # twips; None = Normal (0)
    after: int | None = None         # twips; None = Normal (6 pt)
    line: int | None = None          # line spacing, 240 = single
    exact: int | None = None         # exact line height in twips
    rule: int | None = None          # a rule of this length centred in the paragraph's width
    width: int = TEXT_W              # width of the column the paragraph is in (for rule and dotted lines)
    keep_next: bool = False
    leader: bool = False             # a right tab stop with dots at the right edge

    def xml(self) -> str:
        props = []
        if self.keep_next:
            props.append("<w:keepNext/>")
        left, right = self.left, self.right
        if self.rule is not None:
            left = right = (self.width - self.rule) // 2
            props.append(f'<w:pBdr><w:top w:val="single" w:sz="{LINE}" w:space="0" w:color="000000"/></w:pBdr>')
        if self.leader:
            props.append(f'<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="{self.width - right}"/></w:tabs>')
        spacing = []
        if self.before is not None:
            spacing.append(f'w:before="{self.before}"')
        if self.after is not None:
            spacing.append(f'w:after="{self.after}"')
        if self.exact is not None:
            spacing.append(f'w:line="{self.exact}" w:lineRule="exact"')
        elif self.line is not None:
            spacing.append(f'w:line="{self.line}" w:lineRule="auto"')
        if spacing:
            props.append(f"<w:spacing {' '.join(spacing)}/>")
        indent = []
        if left:
            indent.append(f'w:left="{left}"')
        if right:
            indent.append(f'w:right="{right}"')
        if self.first_line is not None:
            indent.append(f'w:firstLine="{self.first_line}"')
        if indent or self.rule is not None:
            props.append("<w:ind " + (" ".join(indent) or 'w:left="0"') + "/>")
        if self.align:
            props.append(f'<w:jc w:val="{self.align}"/>')
        mark = ""
        if self.rule is not None:   # an empty line 2 pt high: only its top border shows
            mark = '<w:rPr><w:sz w:val="4"/><w:szCs w:val="4"/></w:rPr>'
        runs = "".join(run.xml() for run in self.runs)
        return f"<w:p><w:pPr>{''.join(props)}{mark}</w:pPr>{runs}</w:p>"


def centered(text: str, size: float = 14, bold: bool = False, italic: bool = False, *, before: int = 0,
             after: int = 0, width: int = TEXT_W, keep_next: bool = False) -> P:
    return P([R(text, size, bold, italic)], align="center", first_line=0, before=before, after=after,
             width=width, keep_next=keep_next)


def rule(length: int, width: int = TEXT_W, after: int = 0) -> P:
    """A rule 3 pt below the line above it (its top border; the paragraph itself is 2 pt high)."""

    return P(align="center", first_line=0, before=60, after=after, exact=40, rule=length, width=width)


def body(*runs: R, first_line: int | None = None, leader: bool = False, after: int | None = None,
         before: int | None = None, keep_next: bool = False) -> P:
    return P(list(runs), first_line=first_line, leader=leader, after=after, before=before, keep_next=keep_next)


def cell(paragraphs: list[P], width: int, *, borders: bool = False, valign: str | None = None) -> str:
    props = [f'<w:tcW w:w="{width}" w:type="dxa"/>']
    if borders:
        props.append("<w:tcBorders>" + "".join(
            f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
            for side in ("top", "left", "bottom", "right")) + "</w:tcBorders>")
    if valign:
        props.append(f'<w:vAlign w:val="{valign}"/>')
    for paragraph in paragraphs:
        paragraph.width = width
    return f"<w:tc><w:tcPr>{''.join(props)}</w:tcPr>{''.join(p.xml() for p in paragraphs)}</w:tc>"


def table(rows: list[list[tuple[list[P], int]]], widths: list[int], *, grid: bool = False, header_rows: int = 0,
          cell_margin: int = 0) -> str:
    total = sum(widths)
    borders = "" if grid else ("<w:tblBorders>" + "".join(
        f'<w:{side} w:val="nil"/>' for side in ("top", "left", "bottom", "right", "insideH", "insideV"))
        + "</w:tblBorders>")
    props = (f'<w:tblW w:w="{total}" w:type="dxa"/><w:tblInd w:w="0" w:type="dxa"/>{borders}'
             '<w:tblLayout w:type="fixed"/>'
             f'<w:tblCellMar><w:top w:w="{20 if grid else 0}" w:type="dxa"/>'
             f'<w:left w:w="{cell_margin}" w:type="dxa"/>'
             f'<w:bottom w:w="{20 if grid else 0}" w:type="dxa"/>'
             f'<w:right w:w="{cell_margin}" w:type="dxa"/></w:tblCellMar>'
             '<w:tblLook w:val="0000" w:firstRow="0" w:lastRow="0" w:firstColumn="0" w:lastColumn="0" '
             'w:noHBand="1" w:noVBand="1"/>')
    grid_xml = "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)
    rows_xml = []
    for index, row in enumerate(rows):
        row_props = "<w:cantSplit/>" + ("<w:tblHeader/>" if index < header_rows else "")
        cells = "".join(cell(paragraphs, width, borders=grid, valign="center" if grid else None)
                        for paragraphs, width in row)
        rows_xml.append(f"<w:tr><w:trPr>{row_props}</w:trPr>{cells}</w:tr>")
    return f"<w:tbl><w:tblPr>{props}</w:tblPr><w:tblGrid>{grid_xml}</w:tblGrid>{''.join(rows_xml)}</w:tbl>"


# ---- The parts every document shares -------------------------------------------------------------------------


def title(kind: str, summary: str | None) -> list[P]:
    """Ô 5a: the type of document, its summary and the short rule under them."""

    paragraphs = [centered(kind, 14, bold=True, before=360, keep_next=True)]
    if summary is not None:
        paragraphs.append(centered(summary, 14, bold=True, keep_next=True))
    paragraphs.append(rule(SUMMARY_RULE, after=240))
    return paragraphs


# ---- The document ---------------------------------------------------------------------------------------------

def header() -> str:
    """Ô 1-4 of the decree: the company at the left, the national name at the right; the number, and the place and
    date, on the next row."""

    left = [P([slot("TEN_CONG_TY", 12, bold=True)], align="center", first_line=0, before=0, after=0), rule(BODY_RULE)]
    right = [centered("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", 12, bold=True),
             centered("Độc lập - Tự do - Hạnh phúc", 13, bold=True), rule(MOTTO_RULE)]
    number_cell = [P([R("Số: ", 13), slot("SO", 13)], align="center", first_line=0, before=120, after=0)]
    date_cell = [P([slot("DIA_DIEM", 13, italic=True), R(", ngày ", 13, italic=True), slot("NGAY", 13, italic=True),
                    R(" tháng ", 13, italic=True), slot("THANG", 13, italic=True), R(" năm ", 13, italic=True),
                    slot("NAM", 13, italic=True)], align="center", first_line=0, before=120, after=0)]
    return table([[(left, LEFT_COL), (right, RIGHT_COL)], [(number_cell, LEFT_COL), (date_cell, RIGHT_COL)]],
                 [LEFT_COL, RIGHT_COL])


def ban_giao_tai_san() -> str:
    """caramos-ota's "Biên bản bàn giao tài sản", with placeholders where it has dotted lines."""

    widths = [cm(1.2), cm(4.4), cm(2.8), cm(1.6), cm(1.6), cm(2.4), cm(2.0)]
    head = ["STT", "Tên tài sản", "Mã số,\nsố sê-ri", "Đơn vị tính", "Số lượng", "Tình trạng", "Ghi chú"]

    def text_cell(runs: list[R], align: str = "center") -> list[P]:
        return [P(runs, align=align, first_line=0, before=40, after=40)]

    rows = [[(text_cell([R(name, 13, bold=True)]), width) for name, width in zip(head, widths)]]
    rows.append([(text_cell([slot(name, 13)], "left" if name in ("TEN_TAI_SAN", "GHI_CHU") else "center"), width)
                 for name, width in zip(ROW_FIELDS, widths)])
    assets = table(rows, widths, grid=True, header_rows=1, cell_margin=cm(0.1))
    before = [
        *title("BIÊN BẢN BÀN GIAO TÀI SẢN", None),
        body(R("Hôm nay, ngày "), slot("NGAY"), R(" tháng "), slot("THANG"), R(" năm "), slot("NAM"), R(", tại "),
             slot("DIA_DIEM"), R(", chúng tôi gồm:")),
        body(R("Bên giao (Bên A):", bold=True), first_line=0),
        body(R("Ông/Bà: "), slot("BEN_GIAO"), R("    Chức vụ: "), slot("CHUC_VU_GIAO"), first_line=0),
        body(R("Bên nhận (Bên B):", bold=True), first_line=0),
        body(R("Ông/Bà: "), slot("BEN_NHAN"), R("    Chức vụ: "), slot("CHUC_VU_NHAN"), first_line=0),
        body(R("Hai bên thống nhất bàn giao các tài sản sau:"), keep_next=True),
    ]
    after = [
        body(R("Lý do bàn giao: "), slot("LY_DO"), first_line=0, before=120),
        body(R("Kể từ ngày ký biên bản này, Bên B chịu trách nhiệm quản lý và sử dụng các tài sản trên.")),
        body(R("Biên bản được lập thành 02 bản có giá trị như nhau, mỗi bên giữ 01 bản./.")),
    ]
    signers = table([[([centered("ĐẠI DIỆN BÊN GIAO", 14, bold=True, before=240),
                        centered("(Ký, ghi rõ họ tên)", 14, italic=True)], TEXT_W // 2),
                      ([centered("ĐẠI DIỆN BÊN NHẬN", 14, bold=True, before=240),
                        centered("(Ký, ghi rõ họ tên)", 14, italic=True)], TEXT_W - TEXT_W // 2)]],
                    [TEXT_W // 2, TEXT_W - TEXT_W // 2])
    return "".join([header(), *(p.xml() for p in before), assets, *(p.xml() for p in after), signers])


# ---- The package ---------------------------------------------------------------------------------------------

W_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
XML_HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
FONT = "Times New Roman"

CONTENT_TYPES = XML_HEAD + (
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/word/settings.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>'
    '<Override PartName="/word/fontTable.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"/>'
    '<Override PartName="/word/header1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
    '<Override PartName="/word/header2.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
    '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
    '<Override PartName="/docProps/app.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
    '</Types>')

ROOT_RELS = XML_HEAD + (
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="word/document.xml"/>'
    '<Relationship Id="rId2" '
    'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
    'Target="docProps/core.xml"/>'
    '<Relationship Id="rId3" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
    'Target="docProps/app.xml"/>'
    '</Relationships>')

DOCUMENT_RELS = XML_HEAD + (
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
    'Target="styles.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" '
    'Target="settings.xml"/>'
    '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable" '
    'Target="fontTable.xml"/>'
    '<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" '
    'Target="header1.xml"/>'
    '<Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" '
    'Target="header2.xml"/>'
    '</Relationships>')

FONTS_XML = (f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:eastAsia="{FONT}" w:cs="{FONT}"/>')

STYLES = XML_HEAD + (
    f'<w:styles {W_NS}>'
    '<w:docDefaults><w:rPrDefault><w:rPr>'
    f'{FONTS_XML}<w:color w:val="000000"/><w:sz w:val="28"/><w:szCs w:val="28"/>'
    '<w:lang w:val="vi-VN" w:eastAsia="vi-VN" w:bidi="ar-SA"/>'
    '</w:rPr></w:rPrDefault>'
    '<w:pPrDefault><w:pPr><w:spacing w:before="0" w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
    '</w:docDefaults>'
    # Normal is the body text: what the user types next is laid out by the decree without any setting.
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/>'
    f'<w:pPr><w:widowControl/><w:spacing w:before="0" w:after="120" w:line="240" w:lineRule="auto"/>'
    f'<w:ind w:firstLine="{INDENT}"/><w:jc w:val="both"/></w:pPr>'
    f'<w:rPr>{FONTS_XML}<w:sz w:val="28"/><w:szCs w:val="28"/><w:lang w:val="vi-VN"/></w:rPr></w:style>'
    '<w:style w:type="character" w:default="1" w:styleId="DefaultParagraphFont">'
    '<w:name w:val="Default Paragraph Font"/><w:uiPriority w:val="1"/><w:semiHidden/></w:style>'
    '<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/>'
    '<w:semiHidden/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/>'
    '<w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/>'
    '</w:tblCellMar></w:tblPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Header"><w:name w:val="header"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:spacing w:after="0"/><w:ind w:firstLine="0"/><w:jc w:val="center"/></w:pPr></w:style>'
    '</w:styles>')

SETTINGS = XML_HEAD + (
    f'<w:settings {W_NS}>'
    '<w:defaultTabStop w:val="720"/><w:characterSpacingControl w:val="doNotCompress"/>'
    '<w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" '
    'w:val="15"/></w:compat>'
    '<w:themeFontLang w:val="vi-VN"/><w:decimalSymbol w:val=","/><w:listSeparator w:val=";"/>'
    '</w:settings>')

FONT_TABLE = XML_HEAD + (
    f'<w:fonts {W_NS}><w:font w:name="{FONT}"><w:panose1 w:val="02020603050405020304"/>'
    '<w:charset w:val="00"/><w:family w:val="roman"/><w:pitch w:val="variable"/></w:font></w:fonts>')

PAGE_NUMBER = XML_HEAD + (
    f'<w:hdr {W_NS}><w:p><w:pPr><w:pStyle w:val="Header"/></w:pPr>'
    '<w:fldSimple w:instr=" PAGE "><w:r><w:rPr><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr><w:t>2</w:t></w:r>'
    '</w:fldSimple></w:p></w:hdr>')

FIRST_PAGE_HEADER = XML_HEAD + f'<w:hdr {W_NS}><w:p><w:pPr><w:pStyle w:val="Header"/></w:pPr></w:p></w:hdr>'

CORE = XML_HEAD + (
    '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
    '<dc:title></dc:title><dc:creator></dc:creator><cp:lastModifiedBy></cp:lastModifiedBy>'
    '<dc:language>vi-VN</dc:language><cp:revision>1</cp:revision></cp:coreProperties>')

APP = XML_HEAD + (
    '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
    'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
    '<Template>Normal.dotm</Template><TotalTime>0</TotalTime><Application>CaramOS</Application></Properties>')


def document_xml(content: str) -> str:
    section = (f'<w:sectPr><w:headerReference w:type="default" r:id="rId4"/>'
               f'<w:headerReference w:type="first" r:id="rId5"/>'
               f'<w:pgSz w:w="{PAGE_W}" w:h="{PAGE_H}"/>'
               f'<w:pgMar w:top="{MARGIN_TOP}" w:right="{MARGIN_RIGHT}" w:bottom="{MARGIN_BOTTOM}" '
               f'w:left="{MARGIN_LEFT}" w:header="{HEADER_DISTANCE}" w:footer="{HEADER_DISTANCE}" w:gutter="0"/>'
               '<w:pgNumType w:start="1"/><w:titlePg/><w:docGrid w:linePitch="360"/></w:sectPr>')
    return XML_HEAD + f"<w:document {W_NS}><w:body>{content}{section}</w:body></w:document>"


def package(content: str) -> dict[str, str]:
    return {
        "[Content_Types].xml": CONTENT_TYPES,
        "_rels/.rels": ROOT_RELS,
        "docProps/core.xml": CORE,
        "docProps/app.xml": APP,
        "word/document.xml": document_xml(content),
        "word/_rels/document.xml.rels": DOCUMENT_RELS,
        "word/styles.xml": STYLES,
        "word/settings.xml": SETTINGS,
        "word/fontTable.xml": FONT_TABLE,
        "word/header1.xml": PAGE_NUMBER,
        "word/header2.xml": FIRST_PAGE_HEADER,
    }


def write(path: Path, parts: dict[str, str]) -> None:
    """A zip whose bytes depend only on the parts: fixed dates, order and permissions."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    with zipfile.ZipFile(temporary, "w") as archive:
        for name, text in parts.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, text.encode("utf-8"))
    temporary.chmod(0o644)
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder for the .docx file")
    args = parser.parse_args(argv)
    write(args.out / NAME, package(ban_giao_tai_san()))
    print(args.out / NAME)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

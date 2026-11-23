#!/usr/bin/env python3
"""Build the Vietnamese administrative document templates of right-click > "Mới" > "Văn bản hành chính" in Files.

    tools/make-nd30-templates.py [--out usr/share/caramos-ota/templates/nd30]

Writes one Word document (OOXML, no LibreOffice needed) for each kind of document of Nghị định 30/2020/NĐ-CP,
Phụ lục III (công văn, quyết định cá biệt, tờ trình, báo cáo, thông báo, giấy mời, biên bản), and a "Biên bản bàn
giao tài sản" for companies. The output is reproducible: the same script writes byte-identical files, which are
committed; caramos-templates puts them into each user's Templates folder (see usr/share/caramos-ota/nemo-menu).

The layout follows Phụ lục I of the decree (Thể thức, kỹ thuật trình bày văn bản hành chính), checked against the
official text on 2026-11-22:
- A4 portrait; margins top and bottom 20 mm, left 30 mm, right 20 mm (the decree allows 20-25, 20-25, 30-35, 15-20);
  Times New Roman, black, Vietnamese (vi-VN) for the spelling checker.
- The two-column borderless header: issuing body at the left (ô 2: chủ quản in capitals, 12 pt; the body itself in
  bold capitals, 12 pt, with a rule a third to a half of its length under it), the national name at the right
  (ô 1: quốc hiệu in bold capitals, 12 pt; tiêu ngữ in bold, 13 pt, with a rule as long as the motto). On the next
  row, on the same line: "Số: …/…-…" (ô 3, 13 pt) and the place and date (ô 4, italic, 13 pt). The footnote of the
  decree's font table pairs quốc hiệu 12 with tiêu ngữ 13 and the date 13.
- The document type in bold capitals, 14 pt, centred; the summary (trích yếu) under it in bold, 14 pt, with a short
  rule (ô 5a). A công văn has "V/v …" (12 pt) under its number instead (ô 5b), 6 pt below it.
- "Kính gửi:" (ô 9a) for công văn, tờ trình and báo cáo, 14 pt; several recipients on their own lines, their dashes
  under the colon.
- The body: 14 pt, justified, first line indented 1.27 cm, 6 pt between paragraphs, single line spacing; căn cứ in
  italics; "Điều 1." in bold.
- The signature block (ô 7a-7c): authority and title in bold capitals, 14 pt, the signer's name in bold, 14 pt;
  "Nơi nhận:" level with it at the left margin (ô 9b), bold italic 12 pt, its list in 11 pt.
- Page numbers 14 pt, centred in the top margin, none on the first page.
Placeholders are the decree's own (TÊN CƠ QUAN, TỔ CHỨC; QUYỀN HẠN, CHỨC VỤ CỦA NGƯỜI KÝ; Họ và tên) and dotted
lines: tab leaders to the right margin, so a line stays one line whatever is typed before it.
"""

from __future__ import annotations

import argparse
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "usr/share/caramos-ota/templates/nd30"


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


def dots(size: float = 14) -> R:
    """A dotted line to the right edge (a tab whose leader is dots)."""

    return R("", size=size, tab=True)


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


def dotted_line(first_line: int | None = 0) -> P:
    """A whole line of dots; the first line of a paragraph (first_line=None) is indented like the body."""

    return P([dots()], first_line=first_line, leader=True)


def field_line(label: str, *, bold_label: bool = False) -> P:
    """"Label: ……" with the dots up to the right edge."""

    return P([R(label + " ", bold=bold_label), dots()], leader=True)


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

def header(number: str, *, date: bool = True, subject: str | None = None, parent: str | None = "TÊN CQ, TC CHỦ QUẢN",
           body_name: str = "TÊN CƠ QUAN, TỔ CHỨC") -> str:
    """Ô 1-4 (and 5b for a công văn) in a borderless two-column table."""

    left = []
    if parent:
        left.append(centered(parent, 12))
    left += [centered(body_name, 12, bold=True), rule(BODY_RULE)]
    right = [centered("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM", 12, bold=True),
             centered("Độc lập - Tự do - Hạnh phúc", 13, bold=True), rule(MOTTO_RULE)]
    number_cell = [centered(number, 13, before=120)]
    if subject is not None:
        number_cell.append(centered(subject, 12, before=120))
    date_cell = [centered(f"{DOTS * 4}, ngày {DOTS} tháng {DOTS} năm 20{DOTS}", 13, italic=True, before=120)] \
        if date else [centered("", 13, before=120)]
    return table([[(left, LEFT_COL), (right, RIGHT_COL)], [(number_cell, LEFT_COL), (date_cell, RIGHT_COL)]],
                 [LEFT_COL, RIGHT_COL])


def title(kind: str, summary: str | None) -> list[P]:
    """Ô 5a: the type of document, its summary and the short rule under them."""

    paragraphs = [centered(kind, 14, bold=True, before=360, keep_next=True)]
    if summary is not None:
        paragraphs.append(centered(summary, 14, bold=True, keep_next=True))
    paragraphs.append(rule(SUMMARY_RULE, after=240))
    return paragraphs


def recipient_one() -> P:
    """Ô 9a with one recipient: "Kính gửi: …" on one line, centred."""

    return centered(f"Kính gửi: {DOTS * 16}", 14, before=120, after=240)


def recipient_many(count: int = 2) -> list[P]:
    """Ô 9a with several recipients: each on its own line, the dashes under the colon of "Kính gửi:"."""

    start = cm(3.5)
    colon = start + cm(1.76)       # "Kính gửi" in Times New Roman 14 pt is 1.76 cm long
    paragraphs = [P([R("Kính gửi:")], align="left", first_line=0, left=start, before=120, after=0, keep_next=True)]
    for index in range(count):
        end = "." if index == count - 1 else ";"
        paragraphs.append(P([R(f"- {DOTS * 14}{end}")], align="left", first_line=0, left=colon, before=0,
                            after=240 if index == count - 1 else 0))
    return paragraphs


def body_lines(count: int = 3, last: str = "./.") -> list[P]:
    """Dotted body text: a first line indented like a paragraph, full lines, and the closing "./."."""

    paragraphs = [dotted_line(first_line=None)]
    paragraphs += [dotted_line() for _ in range(count - 2)]
    paragraphs.append(P([dots(), R(last)], first_line=0, leader=True))
    return paragraphs


def signature(recipients: list[str], *, authority: str = "QUYỀN HẠN, CHỨC VỤ CỦA NGƯỜI KÝ",
              note: str = "(Chữ ký của người có thẩm quyền,\ndấu/chữ ký số của cơ quan, tổ chức)") -> str:
    """Ô 9b at the left and ô 7a-7c at the right, in a borderless table."""

    left = [P([R("Nơi nhận:", 12, bold=True, italic=True)], align="left", first_line=0, before=240, after=0)]
    left += [P([R(line, 11)], align="left", first_line=0, before=0, after=0) for line in recipients]
    right = [centered(authority, 14, bold=True, before=240),
             centered(note, 14, italic=True)]
    right += [centered("", 14) for _ in range(4)]
    right.append(centered("Họ và tên", 14, bold=True))
    return table([[(left, LEFT_COL), (right, RIGHT_COL)]], [LEFT_COL, RIGHT_COL])


# ---- The documents -------------------------------------------------------------------------------------------

def cong_van() -> str:
    """Mẫu 1.5 - Công văn."""

    return "".join([
        header("Số: …/…-…", subject=f"V/v {DOTS * 10}"),
        *(p.xml() for p in recipient_many()),
        *(p.xml() for p in body_lines(4)),
        signature(["- Như trên;", f"- {DOTS * 6};", f"- Lưu: VT, {DOTS * 2}."]),
    ])


def quyet_dinh() -> str:
    """Mẫu 1.2 - Quyết định (cá biệt) quy định trực tiếp."""

    paragraphs = [
        *title("QUYẾT ĐỊNH", f"Về việc {DOTS * 18}"),
        centered("THẨM QUYỀN BAN HÀNH", 14, bold=True, before=0, after=120, keep_next=True),
        P([R("Căn cứ ", italic=True), dots(), R(";", italic=True)], leader=True),
        P([R("Căn cứ ", italic=True), dots(), R(";", italic=True)], leader=True),
        P([R("Theo đề nghị của ", italic=True), dots(), R(".", italic=True)], leader=True),
        centered("QUYẾT ĐỊNH:", 14, bold=True, before=120, after=120, keep_next=True),
        P([R("Điều 1. ", bold=True), dots()], leader=True),
        dotted_line(),
        P([R("Điều 2. ", bold=True), R("Quyết định này có hiệu lực kể từ ngày ký.")]),
        P([R("Điều 3. ", bold=True), R(f"{DOTS * 12} chịu trách nhiệm thi hành Quyết định này./.")]),
    ]
    return "".join([
        header("Số: …/QĐ-…"),
        *(p.xml() for p in paragraphs),
        signature(["- Như Điều 3;", f"- {DOTS * 6};", f"- Lưu: VT, {DOTS * 2}."]),
    ])


def named(kind: str, number: str, summary: str, *, to_superior: bool, lines: int = 4,
          recipients: list[str] | None = None) -> str:
    """Mẫu 1.4 - Văn bản có tên loại (tờ trình, báo cáo, thông báo…)."""

    parts = [header(number), *(p.xml() for p in title(kind, summary))]
    if to_superior:
        parts.append(recipient_one().xml())
    parts += [p.xml() for p in body_lines(lines)]
    default = ["- Như trên;" if to_superior else f"- {DOTS * 6};", f"- {DOTS * 6};", f"- Lưu: VT, {DOTS * 2}."]
    parts.append(signature(recipients or default))
    return "".join(parts)


def giay_moi() -> str:
    """Mẫu 1.7 - Giấy mời."""

    paragraphs = [
        *title("GIẤY MỜI", DOTS * 18),
        P([R(f"{DOTS * 8} trân trọng kính mời: "), dots()], leader=True),
        P([R("Tới dự "), dots()], leader=True),
        dotted_line(),
        field_line("Chủ trì:"),
        field_line("Thời gian:"),
        field_line("Địa điểm:"),
        P([dots(), R("./.")], first_line=0, leader=True),
    ]
    return "".join([
        header("Số: …/GM-…"),
        *(p.xml() for p in paragraphs),
        signature([f"- {DOTS * 6};", f"- {DOTS * 6};", f"- Lưu: VT, {DOTS * 2}."]),
    ])


def bien_ban() -> str:
    """Mẫu 1.9 - Biên bản: no place and date in the header; secretary and chair sign."""

    paragraphs = [
        *title("BIÊN BẢN", DOTS * 18),
        field_line("Thời gian bắt đầu:"),
        field_line("Địa điểm:"),
        field_line("Thành phần tham dự:"),
        dotted_line(),
        field_line("Chủ trì (chủ tọa):"),
        field_line("Thư ký (người ghi biên bản):"),
        body(R("Nội dung (theo diễn biến cuộc họp/hội nghị/hội thảo):")),
        dotted_line(),
        dotted_line(),
        dotted_line(),
        body(R(f"Cuộc họp (hội nghị, hội thảo) kết thúc vào {DOTS} giờ {DOTS}, ngày {DOTS} tháng {DOTS} "
               f"năm {DOTS}./.")),
    ]
    signers = table([[([centered("THƯ KÝ", 14, bold=True, before=240), centered("(Chữ ký)", 14, italic=True),
                        *[centered("", 14) for _ in range(4)], centered("Họ và tên", 14, bold=True)], LEFT_COL),
                      ([centered("CHỦ TỌA", 14, bold=True, before=240),
                        centered("(Chữ ký của người có thẩm quyền,\ndấu/chữ ký số của cơ quan, tổ chức (nếu có))", 14,
                                 italic=True),
                        *[centered("", 14) for _ in range(3)], centered("Họ và tên", 14, bold=True)], RIGHT_COL)]],
                    [LEFT_COL, RIGHT_COL])
    recipients = [P([R("Nơi nhận:", 12, bold=True, italic=True)], align="left", first_line=0, before=240, after=0),
                  P([R(f"- {DOTS * 6};", 11)], align="left", first_line=0, after=0),
                  P([R("- Lưu: VT, Hồ sơ.", 11)], align="left", first_line=0, after=0)]
    return "".join([header("Số: …/BB-…", date=False), *(p.xml() for p in paragraphs), signers,
                    *(p.xml() for p in recipients)])


def ban_giao_tai_san() -> str:
    """A company's record of handing assets over, in the same layout (amis.misa.vn/33907 lists the usual parts)."""

    widths = [cm(1.2), cm(4.4), cm(2.8), cm(1.6), cm(1.6), cm(2.4), cm(2.0)]
    head = ["STT", "Tên tài sản", "Mã số,\nsố sê-ri", "Đơn vị tính", "Số lượng", "Tình trạng", "Ghi chú"]

    def text_cell(text: str, bold: bool = False) -> list[P]:
        return [P([R(text, 13, bold=bold)] if text else [], align="center", first_line=0, before=40, after=40)]

    rows = [[(text_cell(name, bold=True), width) for name, width in zip(head, widths)]]
    for number in range(1, 4):
        rows.append([(text_cell(str(number) if index == 0 else ""), width) for index, width in enumerate(widths)])
    assets = table(rows, widths, grid=True, header_rows=1, cell_margin=cm(0.1))
    before = [
        *title("BIÊN BẢN BÀN GIAO TÀI SẢN", None),
        body(R(f"Hôm nay, ngày {DOTS} tháng {DOTS} năm 20{DOTS}, tại {DOTS * 5}, chúng tôi gồm:")),
        field_line("Bên giao (Bên A):", bold_label=True),
        P([R(f"Ông/Bà: {DOTS * 13} Chức vụ: "), dots()], leader=True),
        field_line("Bên nhận (Bên B):", bold_label=True),
        P([R(f"Ông/Bà: {DOTS * 13} Chức vụ: "), dots()], leader=True),
        body(R("Hai bên thống nhất bàn giao các tài sản sau:"), keep_next=True),
    ]
    after = [
        field_line("Lý do bàn giao:"),
        body(R("Kể từ ngày ký biên bản này, Bên B chịu trách nhiệm quản lý và sử dụng các tài sản trên.")),
        body(R("Biên bản được lập thành 02 bản có giá trị như nhau, mỗi bên giữ 01 bản./.")),
    ]
    after[0].before = 120
    signers = table([[([centered("ĐẠI DIỆN BÊN GIAO", 14, bold=True, before=240),
                        centered("(Ký, ghi rõ họ tên)", 14, italic=True)], TEXT_W // 2),
                      ([centered("ĐẠI DIỆN BÊN NHẬN", 14, bold=True, before=240),
                        centered("(Ký, ghi rõ họ tên)", 14, italic=True)], TEXT_W - TEXT_W // 2)]],
                    [TEXT_W // 2, TEXT_W - TEXT_W // 2])
    return "".join([header("Số: …/BB-…", parent=None, body_name="TÊN CÔNG TY, TỔ CHỨC"),
                    *(p.xml() for p in before), assets, *(p.xml() for p in after), signers])


DOCUMENTS = {
    "Công văn.docx": cong_van,
    "Quyết định.docx": quyet_dinh,
    "Tờ trình.docx": lambda: named("TỜ TRÌNH", "Số: …/TTr-…", f"Về việc {DOTS * 18}", to_superior=True),
    "Báo cáo.docx": lambda: named("BÁO CÁO", "Số: …/BC-…", DOTS * 20, to_superior=True, lines=5),
    "Thông báo.docx": lambda: named("THÔNG BÁO", "Số: …/TB-…", f"Về việc {DOTS * 18}", to_superior=False),
    "Giấy mời.docx": giay_moi,
    "Biên bản.docx": bien_ban,
    "Biên bản bàn giao tài sản.docx": ban_giao_tai_san,
}


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
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder for the .docx files")
    args = parser.parse_args(argv)
    for name, build in DOCUMENTS.items():
        write(args.out / name, package(build()))
        print(args.out / name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

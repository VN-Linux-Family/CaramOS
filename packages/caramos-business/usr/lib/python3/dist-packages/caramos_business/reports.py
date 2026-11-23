"""The admin's reports as files (PROTOCOL.md part 3): the licence report, the security report and the tickets of a
month as XLSX through python3-openpyxl, and any of them, or a handover document, as PDF through LibreOffice
("Reports as PDF"). They are Vietnamese documents with signature lines, like the stocktaking record of export.py."""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import licences, security, text, tickets
from .i18n import _

LIBREOFFICE_FLATPAK = "org.libreoffice.LibreOffice"
CLASS_NAMES = {"free": "Tự do", "freeware": "Miễn phí", "commercial": "Thương mại", "unknown": "Chưa rõ"}
ORIGIN_NAMES = {"ubuntu-main": "Ubuntu", "ubuntu-universe": "Ubuntu (universe)", "ubuntu-restricted": "Ubuntu",
                "ubuntu-multiverse": "Ubuntu (multiverse)", "mint": "Linux Mint", "caramos-ppa": "CaramOS",
                "local-deb": "Tệp .deb cài tay", "flathub": "Flathub"}


class ReportError(Exception):
    """A report that could not be made; the text is for the window."""


# -- PDF through LibreOffice -------------------------------------------------------------------------------------------

def soffice() -> list[str] | None:
    """How to run LibreOffice: soffice on the PATH, else LibreOffice's Flatpak (which App Center installs), else
    None."""

    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return [found]
    flatpak = shutil.which("flatpak")
    if flatpak and subprocess.run([flatpak, "info", LIBREOFFICE_FLATPAK], capture_output=True, timeout=30,
                                  check=False).returncode == 0:
        # The app's own command (libreoffice) takes soffice's options; Flathub's LibreOffice has no soffice on its
        # PATH ("bwrap: execvp soffice: No such file or directory", LibreOffice 26.8.3 on CaramOS 1.4.0).
        return [flatpak, "run", LIBREOFFICE_FLATPAK]
    return None


def pdf_command(program: list[str], source: Path, outdir: Path, profile: Path) -> list[str]:
    # A profile of its own: a LibreOffice the user has open would otherwise take the job and convert nothing.
    return [*program, f"-env:UserInstallation={profile.as_uri()}", "--headless", "--convert-to", "pdf", "--outdir",
            str(outdir), str(source)]


def to_pdf(source: Path, target: Path) -> Path:
    """Converts source (XLSX or DOCX) into the PDF target. Raises ReportError with a sentence for the window."""

    program = soffice()
    if program is None:
        raise ReportError(_("Making a PDF needs LibreOffice: install it from App Center, or save the file and print "
                            "it to PDF from LibreOffice."))
    # In the user's cache: LibreOffice's Flatpak sees the home folder, but its /tmp is its own.
    cache = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    cache.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="caramos-business-pdf-", dir=cache) as folder:
        work = Path(folder)
        copy = work / ("report" + source.suffix)
        shutil.copyfile(source, copy)
        done = subprocess.run(pdf_command(program, copy, work, work / "profile"), capture_output=True, text=True,
                              timeout=300, check=False)
        made = work / "report.pdf"
        if done.returncode != 0 or not made.exists():
            raise ReportError(_("LibreOffice could not make the PDF: %s") % (done.stderr.strip()[-300:] or
                                                                           done.returncode))
        shutil.copyfile(made, target)
    return target


# -- shared XLSX parts -------------------------------------------------------------------------------------------------

def _styles() -> dict[str, Any]:
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    thin = Side(style="thin", color="808080")
    return {"border": Border(left=thin, right=thin, top=thin, bottom=thin), "fill": PatternFill("solid",
                                                                                                fgColor="E8E8E8"),
            "bold": Font(bold=True), "title": Font(bold=True, size=14), "italic": Font(italic=True, size=9),
            "center": Alignment(horizontal="center", vertical="center", wrap_text=True),
            "wrap": Alignment(vertical="top", wrap_text=True), "Alignment": Alignment, "Font": Font}


def _heading(sheet: Any, last: str, title: str, lines: list[str], now: datetime.datetime) -> int:
    """The unit, the title, the time and notes; the next free row."""

    style = _styles()
    sheet["A1"] = "Đơn vị: ................................................"
    sheet.merge_cells(f"A3:{last}3")
    sheet["A3"] = title
    sheet["A3"].font = style["title"]
    sheet["A3"].alignment = style["Alignment"](horizontal="center")
    sheet.merge_cells(f"A4:{last}4")
    sheet["A4"] = f"Lập lúc {now:%H} giờ {now:%M}, ngày {now.day} tháng {now.month} năm {now.year}"
    sheet["A4"].alignment = style["Alignment"](horizontal="center")
    row = 5
    for line in lines:
        sheet.merge_cells(f"A{row}:{last}{row}")
        sheet[f"A{row}"] = line
        sheet[f"A{row}"].font = style["italic"]
        sheet[f"A{row}"].alignment = style["Alignment"](horizontal="center", wrap_text=True)
        row += 1
    return row + 1


def _table(sheet: Any, top: int, columns: tuple[tuple[str, str, int], ...], items: list[dict[str, Any]]) -> int:
    """A bordered table with a grey header; the row after it."""

    from openpyxl.utils import get_column_letter

    style = _styles()
    for column, (_key, title, width) in enumerate(columns, start=1):
        cell = sheet.cell(row=top, column=column, value=title)
        cell.font, cell.fill, cell.border, cell.alignment = style["bold"], style["fill"], style["border"], \
            style["center"]
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.row_dimensions[top].height = 32
    for offset, item in enumerate(items, start=1):
        for column, (key, _title, _width) in enumerate(columns, start=1):
            value = item.get(key)
            cell = sheet.cell(row=top + offset, column=column, value=None if value in ("", None) else value)
            cell.border, cell.alignment = style["border"], style["wrap"]
    return top + len(items) + 1


def _signatures(sheet: Any, row: int, titles: list[tuple[int, str]], now: datetime.datetime) -> None:
    style = _styles()
    last_column = max(column for column, _title in titles)
    sheet.cell(row=row, column=last_column, value=f"Ngày {now.day} tháng {now.month} năm {now.year}").font = \
        style["Font"](italic=True)
    for column, title in titles:
        sheet.cell(row=row + 1, column=column, value=title).font = style["bold"]
        sheet.cell(row=row + 2, column=column, value="(Ký, họ tên)").font = style["italic"]


def _fit_page(sheet: Any, orientation: str) -> None:
    """A4, as wide as one page: without it the PDF cuts off whatever is past the right edge."""

    sheet.page_setup.orientation = orientation
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True


def _landscape(sheet: Any, header: int) -> None:
    _fit_page(sheet, "landscape")
    sheet.print_title_rows = f"{header}:{header}"


# -- the licence report ------------------------------------------------------------------------------------------------

LICENCE_COLUMNS = (("index", "STT", 6), ("name", "Phần mềm", 30), ("class", "Loại", 12), ("licence", "Giấy phép", 26),
                   ("origin", "Nguồn cài", 22), ("count", "Số máy", 9), ("machines", "Các máy", 50))
REGISTER_COLUMNS = (("index", "STT", 6), ("product", "Bản quyền đã mua", 30), ("seats", "Số máy được dùng", 12),
                    ("used", "Số máy đang có", 12), ("state", "Đối chiếu", 22), ("expires", "Hết hạn", 12),
                    ("invoice", "Hóa đơn", 18), ("note", "Ghi chú", 30))


def origin_text(origin: str) -> str:
    if origin.startswith("third-party:"):
        return "Bên thứ ba (%s)" % origin.split(":", 1)[1]
    if origin.startswith("flatpak:"):
        return "Flatpak (%s)" % origin.split(":", 1)[1]
    return ORIGIN_NAMES.get(origin, origin)


def licence_rows(report: dict[str, Any], names: dict[str, str]) -> list[dict[str, Any]]:
    return [{"index": index, "name": app["name"], "class": CLASS_NAMES[app["class"]], "licence": app["licence"],
             "origin": origin_text(app["origin"]), "count": len(app["machines"]),
             "machines": ", ".join(sorted(names.get(machine_id, machine_id[:8]) for machine_id in app["machines"]))}
            for index, app in enumerate(report["apps"], start=1)]


def register_state(entry: dict[str, Any]) -> str:
    if entry["used"] > entry["seats"]:
        return "Thiếu %d bản quyền" % (entry["used"] - entry["seats"])
    return "Đủ"


def write_licence_xlsx(report: dict[str, Any], names: dict[str, str], path: Path, now: datetime.datetime) -> None:
    """The summary sheet (totals, apps, the register, signatures for "Người lập" and "Giám đốc") and one sheet
    "Báo cáo phần mềm" per machine."""

    from openpyxl import Workbook

    style = _styles()
    book = Workbook()
    sheet = book.active
    sheet.title = "Tổng hợp"
    totals = report["totals"]
    top = _heading(sheet, "G", "BÁO CÁO PHẦN MỀM TRÊN CÁC MÁY", [
        licences.DISCLAIMER,
        "Tự do: %(free)d, miễn phí: %(freeware)d, thương mại: %(commercial)d, chưa rõ: %(unknown)d phần mềm."
        % totals], now)
    if report["without_inventory"]:
        sheet.cell(row=top - 1, column=1, value="Chưa có danh sách ứng dụng (chưa bật kiểm kê): " + ", ".join(
            names.get(machine_id, machine_id[:8]) for machine_id in report["without_inventory"])).font = \
            style["italic"]
        top += 1
    after = _table(sheet, top, LICENCE_COLUMNS, licence_rows(report, names))
    if report["register"]:
        sheet.cell(row=after + 1, column=1, value="Bản quyền đã mua").font = style["bold"]
        register = [dict(entry, index=index, state=register_state(entry), expires=text.vn_date(entry["expires"]))
                    for index, entry in enumerate(report["register"], start=1)]
        after = _table(sheet, after + 2, REGISTER_COLUMNS, register)
    _signatures(sheet, after + 2, [(2, "Người lập"), (6, "Giám đốc")], now)
    _landscape(sheet, top)
    used: set[str] = set()
    for machine_id in sorted(names, key=lambda key: names[key]):
        apps = [app for app in report["apps"] if machine_id in app["machines"]]
        if not apps:
            continue
        title = (names[machine_id] or machine_id[:8])[:28]
        while title in used:
            title = title[:26] + f"-{len(used)}"
        used.add(title)
        machine_sheet = book.create_sheet(title.replace("/", "-").replace(":", "-"))
        start = _heading(machine_sheet, "F", "BÁO CÁO PHẦN MỀM", [f"Máy: {names[machine_id]}",
                                                                   licences.DISCLAIMER], now)
        rows = [{"index": index, "name": app["name"], "class": CLASS_NAMES[app["class"]], "licence": app["licence"],
                 "origin": origin_text(app["origin"]), "count": ""} for index, app in enumerate(apps, start=1)]
        end = _table(machine_sheet, start, LICENCE_COLUMNS[:5], rows)
        _signatures(machine_sheet, end + 2, [(2, "Người lập"), (4, "Giám đốc")], now)
        _landscape(machine_sheet, start)
    book.save(path)


# -- the security report -----------------------------------------------------------------------------------------------

def write_security_xlsx(table: list[dict[str, Any]], audit: list[dict[str, Any]], audit_texts: list[str],
                        paragraph: str, start: datetime.date, end: datetime.date, path: Path,
                        now: datetime.datetime) -> None:
    """Three sheets: the machines with company totals, the audit extract for the period, and the paragraph for the
    labour rules."""

    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    style = _styles()
    book = Workbook()
    sheet = book.active
    sheet.title = "Báo cáo an toàn"
    last = get_column_letter(len(security.COLUMNS))
    top = _heading(sheet, last, "BÁO CÁO AN TOÀN MÁY TRẠM", [security.DISCLAIMER], now)
    after = _table(sheet, top, security.COLUMNS, table)
    counted = security.totals(table)
    sheet.cell(row=after + 1, column=1, value="Tổng hợp").font = style["bold"]
    for offset, (key, title) in enumerate(security.TOTALS, start=2):
        sheet.cell(row=after + offset, column=1, value=title)
        sheet.cell(row=after + offset, column=3, value=counted[key])
    _signatures(sheet, after + len(security.TOTALS) + 3, [(2, "Người lập"), (len(security.COLUMNS) - 2,
                                                                             "Giám đốc")], now)
    _landscape(sheet, top)
    log = book.create_sheet("Nhật ký")
    log_top = _heading(log, "D", "TRÍCH NHẬT KÝ QUẢN TRỊ", [security.period_text(start, end)], now)
    entries = [{"time": security._when(line.get("time")), "user": line.get("user", ""),  # noqa: SLF001
                "action": line.get("action", ""), "text": words} for line, words in zip(audit, audit_texts)]
    _table(log, log_top, (("time", "Thời điểm", 18), ("user", "Người làm", 14), ("action", "Loại", 14),
                          ("text", "Nội dung", 80)), entries)
    _landscape(log, log_top)
    rules = book.create_sheet("Nội quy")
    rules.column_dimensions["A"].width = 90  # about the width of a portrait A4 page
    _fit_page(rules, "portrait")
    rules["A1"] = "Đoạn đưa vào nội quy lao động (điểm a khoản 3 Điều 25 Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15)"
    rules["A1"].font = style["bold"]
    for offset, line in enumerate(paragraph.splitlines(), start=3):
        rules.cell(row=offset, column=1, value=line).alignment = style["wrap"]
    book.save(path)


# -- the tickets of a month --------------------------------------------------------------------------------------------

TICKET_COLUMNS = (("id", "Mã phiếu", 11), ("created", "Ngày gửi", 16), ("machine", "Máy", 16), ("user", "Người gửi", 14),
                  ("note", "Nội dung", 44), ("status", "Trạng thái", 14), ("assignee", "Người xử lý", 16),
                  ("first_response", "Phản hồi đầu tiên", 16), ("closed", "Xong lúc", 16))


def write_tickets_xlsx(report: dict[str, Any], names: dict[str, str], year: int, month: int, path: Path,
                       now: datetime.datetime) -> None:
    """Counts by status, the median time to the first response, and the list."""

    from openpyxl import Workbook

    style = _styles()
    book = Workbook()
    sheet = book.active
    sheet.title = f"Tháng {month}-{year}"
    median = report["median_first_response_minutes"]
    counts = report["counts"]
    lines = ["Tổng số phiếu: %d. Mới: %d, đang xử lý: %d, chờ người gửi trả lời: %d, đã xong: %d." % (
        report["total"], counts["new"], counts["working"], counts["waiting"], counts["done"]),
        "Thời gian phản hồi đầu tiên (trung vị): " + (f"{median} phút" if median is not None else "chưa có")]
    top = _heading(sheet, "I", f"PHIẾU HỖ TRỢ THÁNG {month}/{year}", lines, now)
    rows = [{"id": ticket["id"], "created": security._when(ticket.get("created")),  # noqa: SLF001
             "machine": names.get(ticket.get("machine_id", ""), ticket.get("machine_id", "")[:8]),
             "user": ticket.get("user", ""), "note": ticket.get("note", ""),
             "status": tickets.STATUS_NAMES.get(ticket.get("status"), ticket.get("status", "")),
             "assignee": ticket.get("assignee", ""), "first_response": security._when(ticket.get("first_response")),
             "closed": security._when(ticket.get("closed"))} for ticket in report["tickets"]]
    after = _table(sheet, top, TICKET_COLUMNS, rows)
    sheet.cell(row=after + 1, column=1, value="Người lập").font = style["bold"]
    _landscape(sheet, top)
    book.save(path)

"""The asset list the admin exports for the accountant ("Xuất danh sách tài sản"): an XLSX sheet laid out like a
Vietnamese stocktaking record (biên bản kiểm kê) through python3-openpyxl, or a CSV in UTF-8 with a BOM so that Excel
shows the Vietnamese letters. The headers are Vietnamese in both: it is a Vietnamese accounting form."""

from __future__ import annotations

import csv
import datetime
import io
from pathlib import Path
from typing import Any

from . import health, protocol, text

COLUMNS = (
    ("index", "STT", 6),
    ("asset_code", "Mã tài sản", 14),
    ("name", "Tên tài sản", 30),
    ("serial", "Số serial", 18),
    ("config", "Cấu hình", 40),
    ("department", "Phòng ban", 16),
    ("holder", "Người sử dụng", 20),
    ("location", "Vị trí", 16),
    ("purchase_date", "Ngày mua", 12),
    ("price_vnd", "Nguyên giá (đồng)", 16),
    ("warranty_until", "Bảo hành đến", 13),
    ("quantity", "Số lượng", 9),
    ("state", "Tình trạng", 22),
    ("note", "Ghi chú", 30),
)


def rows(machines: dict[str, Any], assets: dict[str, Any], inventories: dict[str, Any], policy: dict[str, Any],
         records: dict[str, Any], now: datetime.datetime) -> list[dict[str, Any]]:
    """One row per machine, sorted by asset code then name."""

    departments = policy.get("departments") or {}
    members = policy.get("members") or {}
    found = []
    for machine_id, entry in machines.items():
        machine = entry.get("machine") or {}
        asset = assets.get(machine_id) or {}
        inventory = inventories.get(machine_id) or {}
        model = text.model_text(inventory)
        name = f"Máy tính {machine.get('name', '')}" + (f" ({model})" if model else "")
        config = text.join_sentence([text.cpu_text(inventory), text.memory_text(inventory),
                                     text.disks_text(inventory)]) if inventory else "Chưa có thông tin kiểm kê"
        department = (departments.get(members.get(machine_id)) or {}).get("name", "")
        effective = protocol.effective_settings(policy, machine_id)
        problems = health.problems(entry, records.get(machine_id), effective, now)
        if any(problem.key == "offline" for problem in problems):
            state = "Lâu không bật"
        elif problems:
            state = "Đang dùng, cần xem"
        else:
            state = "Đang dùng"
        users = ", ".join(user.get("user", "") for user in entry.get("users") or [])
        found.append({
            "machine_id": machine_id,
            "asset_code": asset.get("asset_code", ""),
            "name": name,
            "serial": (inventory.get("system") or {}).get("serial", ""),
            "config": config,
            "department": department,
            "holder": asset.get("holder") or users,
            "location": asset.get("location", ""),
            "purchase_date": asset.get("purchase_date", ""),
            "price_vnd": asset.get("price_vnd"),
            "warranty_until": asset.get("warranty_until", ""),
            "quantity": 1,
            "state": state,
            "note": asset.get("note", ""),
        })
    found.sort(key=lambda row: (row["asset_code"] == "", row["asset_code"], row["name"]))
    for index, row in enumerate(found, start=1):
        row["index"] = index
    return found


def _date(value: str) -> datetime.date | None:
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def csv_bytes(table: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([title for _key, title, _width in COLUMNS])
    for row in table:
        values = []
        for key, _title, _width in COLUMNS:
            value = row.get(key)
            if key in ("purchase_date", "warranty_until"):
                value = text.vn_date(value or "")
            values.append("" if value is None else value)
        writer.writerow(values)
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def write_csv(table: list[dict[str, Any]], path: Path) -> None:
    path.write_bytes(csv_bytes(table))


def write_xlsx(table: list[dict[str, Any]], path: Path, now: datetime.datetime) -> None:
    """The stocktaking record: the unit, the title, the time, the table with a total, and the signatures."""

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    book = Workbook()
    sheet = book.active
    sheet.title = "Kiểm kê"
    last = get_column_letter(len(COLUMNS))
    thin = Side(style="thin", color="808080")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    sheet["A1"] = "Đơn vị: ................................................"
    sheet["A2"] = "Bộ phận: ..............................................."
    sheet.merge_cells(f"A4:{last}4")
    sheet["A4"] = "BIÊN BẢN KIỂM KÊ MÁY TÍNH"
    sheet["A4"].font = Font(bold=True, size=14)
    sheet["A4"].alignment = Alignment(horizontal="center")
    sheet.merge_cells(f"A5:{last}5")
    sheet["A5"] = f"Thời điểm kiểm kê: {now:%H} giờ {now:%M}, ngày {now.day} tháng {now.month} năm {now.year}"
    sheet["A5"].alignment = Alignment(horizontal="center")
    sheet.merge_cells(f"A6:{last}6")
    sheet["A6"] = ("Cấu hình, số serial và tình trạng do CaramOS Doanh nghiệp tự ghi nhận; mã tài sản, ngày mua, "
                   "nguyên giá, người sử dụng và vị trí do người quản trị nhập.")
    sheet["A6"].font = Font(italic=True, size=9)
    sheet["A6"].alignment = Alignment(horizontal="center", wrap_text=True)
    header = 8
    fill = PatternFill("solid", fgColor="E8E8E8")
    for column, (_key, title, width) in enumerate(COLUMNS, start=1):
        cell = sheet.cell(row=header, column=column, value=title)
        cell.font = Font(bold=True)
        cell.fill = fill
        cell.border = border
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.row_dimensions[header].height = 32
    for offset, row in enumerate(table, start=1):
        for column, (key, _title, _width) in enumerate(COLUMNS, start=1):
            value: Any = row.get(key)
            cell = sheet.cell(row=header + offset, column=column)
            if key in ("purchase_date", "warranty_until"):
                value = _date(value or "")
                cell.number_format = "dd/mm/yyyy"
            elif key == "price_vnd":
                cell.number_format = "#,##0"
            cell.value = value if value not in ("",) else None
            cell.border = border
            cell.alignment = Alignment(vertical="top", wrap_text=key in ("name", "config", "note", "state"),
                                       horizontal="center" if key in ("index", "quantity") else None)
    total = header + len(table) + 1
    sheet.cell(row=total, column=1, value="Tổng cộng").font = Font(bold=True)
    sheet.merge_cells(start_row=total, start_column=1, end_row=total, end_column=3)
    price_column = [key for key, _t, _w in COLUMNS].index("price_vnd") + 1
    quantity_column = [key for key, _t, _w in COLUMNS].index("quantity") + 1
    prices = [row["price_vnd"] for row in table if isinstance(row.get("price_vnd"), int)]
    price_cell = sheet.cell(row=total, column=price_column, value=sum(prices) if prices else None)
    price_cell.number_format = "#,##0"
    price_cell.font = Font(bold=True)
    count = sheet.cell(row=total, column=quantity_column, value=len(table))
    count.font = Font(bold=True)
    count.alignment = Alignment(horizontal="center")
    for column in range(1, len(COLUMNS) + 1):
        sheet.cell(row=total, column=column).border = border
    signatures = total + 3
    sheet.cell(row=signatures - 1, column=len(COLUMNS) - 2,
               value=f"Ngày {now.day} tháng {now.month} năm {now.year}").font = Font(italic=True)
    for column, title in ((2, "Người lập biểu"), (6, "Kế toán trưởng"), (len(COLUMNS) - 2, "Giám đốc")):
        sheet.cell(row=signatures, column=column, value=title).font = Font(bold=True)
        sheet.cell(row=signatures + 1, column=column, value="(Ký, họ tên)").font = Font(italic=True, size=9)
    sheet.freeze_panes = sheet.cell(row=header + 1, column=1)
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_title_rows = f"{header}:{header}"
    book.save(path)

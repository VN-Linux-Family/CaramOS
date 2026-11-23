"""The handover document ("In biên bản bàn giao", PROTOCOL.md part 3, "Asset lifecycle and handover"): the package's
template, made by tools/make-handover-template.py, filled with the names, the reason and one table row per asset.

Each placeholder is the whole text of one <w:t> element; the asset table has one row holding {{STT}} and the other
row placeholders, copied once per asset. Values are XML-escaped; an empty value becomes a dotted line, to be filled
in by hand."""

from __future__ import annotations

import datetime
import io
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from . import TEMPLATES, text
from .i18n import _

TEMPLATE = TEMPLATES / "bien-ban-ban-giao-tai-san.docx"
EMPTY = "…………"
FIELDS = ("TEN_CONG_TY", "SO", "NGAY", "THANG", "NAM", "DIA_DIEM", "BEN_GIAO", "CHUC_VU_GIAO", "BEN_NHAN",
          "CHUC_VU_NHAN", "LY_DO")
ROW_FIELDS = ("STT", "TEN_TAI_SAN", "MA_SO", "DON_VI", "SO_LUONG", "TINH_TRANG", "GHI_CHU")
UNITS = {"computer": "Bộ", "laptop": "Chiếc", "monitor": "Chiếc", "printer": "Chiếc", "other": "Cái"}


class HandoverError(Exception):
    """The template is missing or not the package's; the text is for the window."""


def _put(xml: str, name: str, value: str) -> str:
    return xml.replace(f">{{{{{name}}}}}<", f">{escape(value.strip()) if value and value.strip() else EMPTY}<")


def fill(values: dict[str, str], rows: list[dict[str, str]], template: Path = TEMPLATE) -> bytes:
    """The filled .docx: values by placeholder name (FIELDS), rows by ROW_FIELDS."""

    try:
        with zipfile.ZipFile(template) as archive:
            parts = {info.filename: archive.read(info) for info in archive.infolist()}
    except (OSError, zipfile.BadZipFile) as exc:
        raise HandoverError(_("The handover template is missing: reinstall CaramOS Doanh nghiệp.")) from exc
    xml = parts.get("word/document.xml", b"").decode("utf-8")
    match = re.search(r"<w:tr>(?:(?!<w:tr>).)*?\{\{STT\}\}.*?</w:tr>", xml, re.S)
    if match is None:
        raise HandoverError(_("The handover template is missing: reinstall CaramOS Doanh nghiệp."))
    copies = []
    for row in rows or [{}]:
        copy = match.group(0)
        for name in ROW_FIELDS:
            copy = _put(copy, name, str(row.get(name, "")))
        copies.append(copy)
    xml = xml[:match.start()] + "".join(copies) + xml[match.end():]
    for name in FIELDS:
        xml = _put(xml, name, values.get(name, ""))
    parts["word/document.xml"] = xml.encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def asset_row(index: int, name: str, entry: dict[str, Any], inventory: dict[str, Any] | None) -> dict[str, str]:
    """A table row for an asset: its name (and model), its code and serial, its unit, 1, and its note. The condition
    is left dotted: it is written at the handover."""

    model = text.model_text(inventory or {})
    serial = ((inventory or {}).get("system") or {}).get("serial", "")
    code = ", ".join(part for part in (entry.get("asset_code", ""), serial) if part)
    title = name if entry.get("kind") not in (None, "computer", "laptop") or not model else f"{name} ({model})"
    return {"STT": str(index), "TEN_TAI_SAN": title, "MA_SO": code, "DON_VI": UNITS.get(entry.get("kind"), "Cái"),
            "SO_LUONG": "1", "TINH_TRANG": "", "GHI_CHU": entry.get("note", "")}


def date_values(day: datetime.date) -> dict[str, str]:
    return {"NGAY": str(day.day), "THANG": str(day.month), "NAM": str(day.year)}

"""Save report: Driver Check's findings as a web page anyone can open, and the same data as JSON.

Made for the migration survey: try CaramOS from the USB stick on an office computer, save the report onto a USB
drive, and read it later on any computer. It holds the computer's model, processor, memory and disks, what works and
what needs doing, and the devices found; no names of files or people, nothing from the network.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict
from datetime import datetime
from html import escape
from pathlib import Path

from caramos_ota.i18n import _, prefers_vietnamese, ui_language

from .analysis import ABSENT, CRITICAL, INFO, OK, PROBLEM_LEVELS, TIP, WARNING, Report, area_label, kernel_version
from .hardware import Snapshot

DMI = Path("/sys/class/dmi/id")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def system_info(root: Path = Path("/")) -> dict[str, object]:
    """Model, processor, memory, disks and firmware of this computer."""

    dmi = root / str(DMI).lstrip("/")
    vendor, product, version = (_read(dmi / name) for name in ("sys_vendor", "product_name", "product_version"))
    board = " ".join(part for part in (_read(dmi / "board_vendor"), _read(dmi / "board_name")) if part)
    model = " ".join(part for part in (vendor, product) if part and part.lower() not in ("to be filled by o.e.m.",
                                                                                       "system product name"))
    if version and version.lower() not in ("to be filled by o.e.m.", "none", "not applicable", "system version"):
        model = f"{model} ({version})" if model else version
    cpu, threads = "", os.cpu_count() or 0
    for line in _read(root / "proc/cpuinfo").splitlines():
        if line.startswith("model name"):
            cpu = " ".join(line.split(":", 1)[1].split())
            break
    memory = 0
    for line in _read(root / "proc/meminfo").splitlines():
        if line.startswith("MemTotal:"):
            memory = int(line.split()[1]) * 1024
            break
    disks = []
    try:
        result = subprocess.run(["lsblk", "-J", "-b", "-d", "-o", "NAME,MODEL,SIZE,ROTA,TRAN,TYPE"],
                                capture_output=True, text=True, check=False, timeout=10)
        for disk in json.loads(result.stdout or "{}").get("blockdevices", []):
            if disk.get("type") == "disk" and int(disk.get("size") or 0) > 0 and not disk["name"].startswith(
                    ("loop", "zram", "sr")):
                disks.append({"model": (disk.get("model") or "").strip(), "size": int(disk["size"]),
                              "ssd": not disk.get("rota"), "connection": disk.get("tran") or ""})
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    release = ""
    for line in _read(root / "etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            release = line.split("=", 1)[1].strip().strip('"')
    return {"model": model, "board": board, "cpu": cpu, "threads": threads, "memory": memory, "disks": disks,
            "uefi": (root / "sys/firmware/efi").exists(), "system": release}


def gigabytes(size: int) -> str:
    text = f"{size / 1024 ** 3:.1f} GB"
    return text.replace(".", ",") if prefers_vietnamese() else text


def level_name(level: str) -> str:
    return {OK: _("Works"), TIP: _("Works"), INFO: _("Limited"), WARNING: _("Needs attention"),
            CRITICAL: _("Not working"), ABSENT: _("Not present")}.get(level, level)


def devices(snapshot: Snapshot | None) -> list[dict[str, str]]:
    found = []
    for device in (snapshot.pci + snapshot.usb) if snapshot else ():
        drivers = [device.driver] if device.driver else sorted({interface.driver for interface in device.interfaces
                                                                if interface.driver})
        found.append({"bus": device.bus.upper(), "name": device.name, "vendor": device.vendor_name,
                      "id": device.id, "driver": ", ".join(drivers)})
    return found


def report_data(report: Report, snapshot: Snapshot | None, system: dict, when: datetime) -> dict[str, object]:
    return {"tool": "CaramOS Driver Check", "saved": when.isoformat(timespec="seconds"), "computer": system,
            "result": asdict(report), "devices": devices(snapshot)}


STYLE = """
body { font-family: "Be Vietnam Pro", "Segoe UI", Roboto, "Noto Sans", Arial, sans-serif; color: #1f1f1f;
       background: #ffffff; max-width: 860px; margin: 32px auto; padding: 0 24px; line-height: 1.5; }
h1 { font-size: 1.7em; font-weight: 600; margin: 0 0 4px; }
h2 { font-size: 1.15em; font-weight: 600; margin: 32px 0 8px; padding-bottom: 4px; border-bottom: 2px solid #2b6a44; }
p.lead { color: #555; margin: 0 0 16px; }
table { border-collapse: collapse; width: 100%; font-size: 0.95em; }
th, td { text-align: left; vertical-align: top; padding: 6px 10px 6px 0; border-bottom: 1px solid #e3e3e3; }
th { font-weight: 600; width: 32%; }
td.level { white-space: nowrap; width: 20%; }
.item { margin: 0 0 14px; }
.item b { font-weight: 600; }
.muted { color: #666; font-size: 0.92em; }
footer { margin-top: 40px; color: #777; font-size: 0.85em; }
@media print { body { margin: 0; max-width: none; } h2 { break-after: avoid; } tr { break-inside: avoid; } }
"""


def report_html(report: Report, snapshot: Snapshot | None, system: dict, when: datetime) -> str:
    rows: list[str] = []

    def row(name: str, value: str) -> None:
        if value:
            rows.append(f"<tr><th>{escape(name)}</th><td>{escape(value)}</td></tr>")

    row(_("Model"), str(system.get("model") or ""))
    row(_("Mainboard"), str(system.get("board") or ""))
    if system.get("cpu"):
        row(_("Processor"), _("{cpu}, {threads} threads").format(cpu=system["cpu"], threads=system.get("threads")))
    if system.get("memory"):
        row(_("Memory"), gigabytes(int(system["memory"])))
    for disk in system.get("disks") or []:
        kind = _("SSD") if disk["ssd"] else _("hard disk")
        row(_("Disk"), " ".join(part for part in (disk["model"], gigabytes(disk["size"]), kind) if part))
    row(_("Start-up firmware"), "UEFI" if system.get("uefi") else _("Legacy BIOS"))
    checked = ", ".join(part for part in (str(system.get("system") or ""),
                                          "Linux " + kernel_version(report.kernel) if report.kernel else "") if part)
    if report.live:
        checked = _("{system}, from the USB stick").format(system=checked)
    row(_("Checked with"), checked)
    problems = [finding for finding in report.findings if finding.level in PROBLEM_LEVELS]
    tips = [finding for finding in report.findings if finding.level in (INFO, TIP)]
    if report.needs_connection:
        summary = _("This computer cannot get online yet: its network card needs a driver.")
    elif problems:
        summary = _("{count} things need attention; everything else works.").format(count=len(problems))
    else:
        summary = _("CaramOS found drivers for all the hardware it checked.")

    def findings(items) -> str:
        out = []
        for finding in items:
            device = f'<div class="muted">{escape(finding.device)} ({escape(finding.device_id)})</div>' \
                if finding.device else ""
            out.append(f'<div class="item"><b>{escape(finding.title)}</b> ({escape(level_name(finding.level))})'
                       f"{device}<div>{escape(finding.detail)}</div></div>")
        return "".join(out)

    areas = "".join(f"<tr><th>{escape(area_label(area.key))}</th>"
                    f'<td class="level">{escape(level_name(area.level))}</td>'
                    f"<td>{escape(area.summary)}</td></tr>" for area in report.areas)
    device_rows = "".join(f"<tr><td>{escape(item['bus'])}</td><td>{escape(item['name'])}</td>"
                          f"<td>{escape(item['id'])}</td><td>{escape(item['driver'] or '—')}</td></tr>"
                          for item in devices(snapshot))
    title = _("Hardware report")
    model = str(system.get("model") or "") or _("This computer")
    saved = _("Saved on {date} at {time}.").format(date=when.strftime("%d/%m/%Y"), time=when.strftime("%H:%M"))
    headings = {"computer": _("Computer"), "todo": _("To do"), "tips": _("Suggestions"),
                "hardware": _("Hardware on this computer"), "devices": _("Devices")}
    columns = (_("Bus"), _("Device"), "ID", _("Driver"))
    footer = _("Saved by CaramOS Driver Check. It holds no files, names or passwords.")

    def h2(key: str) -> str:
        return f"<h2>{escape(headings[key])}</h2>"

    parts = [
        "<!DOCTYPE html>", f'<html lang="{escape(ui_language())}"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(title)}</title><style>{STYLE}</style></head><body>",
        f"<h1>{escape(title)}</h1>",
        f'<p class="lead">{escape(model)}. {escape(saved)}</p>',
        f"<p>{escape(summary)}</p>",
        h2("computer") + f"<table>{''.join(rows)}</table>",
    ]
    if problems:
        parts.append(h2("todo") + findings(problems))
    if tips:
        parts.append(h2("tips") + findings(tips))
    parts.append(h2("hardware") + f"<table>{areas}</table>")
    if device_rows:
        head = "".join(f"<th>{escape(column)}</th>" for column in columns)
        parts.append(h2("devices") + f"<table><tr>{head}</tr>{device_rows}</table>")
    parts.append(f"<footer>{escape(footer)}</footer></body></html>")
    return "\n".join(parts) + "\n"


def default_name(when: datetime) -> str:
    return _("Hardware report") + when.strftime(" %Y-%m-%d %H%M") + ".html"


def save(path: Path, report: Report, snapshot: Snapshot | None, when: datetime | None = None,
         system: dict | None = None) -> tuple[Path, Path]:
    """Write the page to path (".html" added when missing) and the JSON next to it; never over another file."""

    when = when or datetime.now()
    system = system if system is not None else system_info()
    if path.suffix.lower() not in (".html", ".htm"):
        path = path.with_name(path.name + ".html")
    data = json.dumps(report_data(report, snapshot, system, when), ensure_ascii=False, indent=1) + "\n"
    page = report_html(report, snapshot, system, when)
    json_path = path.with_suffix(".json")
    path.write_text(page, encoding="utf-8")       # the file dialog asked before replacing a file of that name
    number = 2
    while json_path.exists():
        json_path = path.with_name(f"{path.stem} ({number}).json")
        number += 1
    json_path.write_text(data, encoding="utf-8")
    return path, json_path

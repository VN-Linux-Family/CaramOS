"""The security report (PROTOCOL.md part 3, "Security report"): one row per machine from its last check-in, company
totals, an extract of the audit log for a period, and the paragraph for the internal labour rules that tells
employees which technical measures the company uses (Personal Data Protection Law 91/2025/QH15, article 25(3)(a)).

The report and its paragraph are Vietnamese documents, like the stocktaking record: their words are not translated.
Apart from GTK so that it can be tested."""

from __future__ import annotations

import datetime
from typing import Any

from . import admin, health, protocol, text

DISCLAIMER = "Báo cáo hiện trạng kỹ thuật; không phải chứng nhận đạt cấp độ an toàn thông tin nào."

COLUMNS = (
    ("name", "Máy", 18),
    ("department", "Phòng ban", 16),
    ("firewall", "Tường lửa", 12),
    ("updates", "Bản vá bảo mật chờ cài", 22),
    ("reboot", "Cần khởi động lại", 14),
    ("screen_lock", "Khóa màn hình", 16),
    ("usb", "Ổ USB", 14),
    ("encryption", "Mã hóa ổ", 12),
    ("frozen", "Đóng băng", 14),
    ("last_maintenance", "Bảo trì gần nhất", 16),
    ("last_snapshot", "Bản lưu hệ thống gần nhất", 18),
    ("last_seen", "Lần cuối thấy máy", 16),
    ("problems", "Vấn đề", 50),
)

# What each section means for an employee, for the paragraph of the labour rules (one sentence, whatever its value).
MEASURES = {
    "wallpaper": "hình nền màn hình do công ty đặt;",
    "folders": "thư mục Màn hình nền và Tài liệu của người lao động được lưu trên máy chủ của công ty;",
    "shares": "ổ dùng chung của công ty được gắn sẵn;",
    "browser": "trình duyệt có trang chủ và dấu trang của công ty; một số trang web có thể bị chặn, có thể chỉ trong "
               "giờ làm việc;",
    "printers": "máy in của công ty được cài sẵn;",
    "power": "máy tự tắt, và có thể tự bật, theo lịch của công ty; người dùng được báo trước khi máy tắt;",
    "apps": "một số ứng dụng được cài sẵn, một số ứng dụng không được phép cài;",
    "usb": "ổ USB có thể bị chặn hoặc chỉ cho đọc; bàn phím, chuột, máy in và USB ký số vẫn dùng được;",
    "screen_lock": "màn hình tự khóa sau một thời gian không dùng;",
    "firewall": "tường lửa được bật;",
    "inventory": "máy gửi cấu hình phần cứng và danh sách ứng dụng cho bộ phận IT để quản lý tài sản và bản quyền "
                 "phần mềm;",
    "wifi": "máy tự kết nối Wi-Fi của công ty;",
    "shared": "máy dùng chung có thể có phiên khách; máy đóng băng tự xóa mọi thay đổi khi khởi động lại, nên tệp "
              "cần được lưu trên máy chủ của công ty hoặc ổ USB;",
    "snapshots": "máy lưu bản sao hệ thống (không gồm tệp của người dùng) để khôi phục khi cập nhật hỏng;",
}


def _yes_no(value: Any) -> str:
    return "Có" if value is True else "Không" if value is False else "Chưa rõ"


def _when(value: Any) -> str:
    parsed = health._parse(value)  # noqa: SLF001 - the same parsing
    return f"{parsed:%H:%M} {parsed.day}/{parsed.month}/{parsed.year}" if parsed else ""


def snapshot_space(megabytes: Any) -> str:
    """"6,6 GB" in Vietnamese notation, or "" when unknown."""

    if not isinstance(megabytes, int):
        return ""
    return f"{megabytes / 1024:.1f}".replace(".", ",") + " GB"


def row(machine_id: str, entry: dict[str, Any], policy: dict[str, Any], record: dict[str, Any] | None,
        now: datetime.datetime) -> dict[str, Any]:
    """A machine's row: plain Vietnamese values, and the raw facts the totals count."""

    machine = entry.get("machine") or {}
    values = entry.get("health") or {}
    record = record or {}
    effective = protocol.effective_settings(policy, machine_id)
    department = (policy.get("departments") or {}).get((policy.get("members") or {}).get(machine_id)) or {}
    security = (values.get("updates") or {}).get("security", 0) if values else None
    since = health._parse(record.get("security_since"))  # noqa: SLF001
    if security:
        updates = f"{security}" + (f", từ {since.day}/{since.month}/{since.year}" if since else "")
    else:
        updates = "0" if values else "Chưa rõ"
    lock = effective.get("screen_lock")
    # What the machine reported, not what the policy asks: a machine with nobody logged in reports nothing.
    screen_lock = {True: "Bật", False: "Tắt"}.get(values.get("screen_lock_on"), "Chưa rõ")
    if lock and values.get("screen_lock_on") is True:
        screen_lock = f"Bật, sau {lock['idle_minutes']} phút"
    usb_state = values.get("usb_storage") or ("allow" if values else None)
    usb = {"allow": "Cho dùng", "read-only": "Chỉ đọc", "block": "Chặn", "unlocked": "Đang mở tạm",
           None: "Chưa rõ"}.get(usb_state, "Chưa rõ")
    encryption = {"luks": "Có (LUKS)", "none": "Không", "unknown": "Chưa rõ"}.get(values.get("encryption"),
                                                                                 "Chưa rõ")
    if values.get("frozen"):
        frozen = "Đang đóng băng"
    elif values.get("freeze_configured"):
        frozen = "Chờ khởi động lại"
    elif health.freezing(effective):
        frozen = "Chưa áp dụng"
    else:
        frozen = "Không"
    problems = health.problems(entry, record, effective, now)
    return {
        "machine_id": machine_id,
        "name": machine.get("name", machine_id[:8]),
        "department": department.get("name", ""),
        "firewall": {"on": "Bật", "off": "Tắt"}.get(values.get("firewall"), "Chưa rõ"),
        "updates": updates,
        "reboot": _yes_no(values.get("reboot_required")) if values else "Chưa rõ",
        "screen_lock": screen_lock,
        "usb": usb,
        "encryption": encryption,
        "frozen": frozen,
        "last_maintenance": _when(values.get("last_maintenance")),
        "last_snapshot": text.join_sentence([_when(values.get("last_snapshot")),
                                             snapshot_space(values.get("snapshot_space_mb"))]),
        "last_seen": _when(entry.get("last_seen")),
        "problems": " ".join(problem.text for problem in problems),
        "facts": {"firewall_on": values.get("firewall") == "on", "security_waiting": bool(security),
                  "security_late": any(problem.key == "security_updates" for problem in problems),
                  "reboot": values.get("reboot_required") is True, "screen_lock": values.get("screen_lock_on") is True,
                  "usb_limited": usb_state in ("read-only", "block"), "encrypted": values.get("encryption") == "luks",
                  "frozen": values.get("frozen") is True, "problems": len(problems), "reported": bool(values)},
    }


def rows(machines: dict[str, Any], policy: dict[str, Any], records: dict[str, Any],
         now: datetime.datetime) -> list[dict[str, Any]]:
    """Every approved machine, sorted by name."""

    found = [row(machine_id, entry, policy, records.get(machine_id), now) for machine_id, entry in machines.items()
             if admin.approved(entry)]
    return sorted(found, key=lambda item: item["name"])


TOTALS = (
    ("machines", "Số máy"),
    ("reported", "Đã báo tình trạng"),
    ("firewall_on", "Tường lửa bật"),
    ("security_waiting", "Có bản vá bảo mật chờ cài"),
    ("security_late", "Bản vá bảo mật chờ quá 7 ngày"),
    ("reboot", "Cần khởi động lại"),
    ("screen_lock", "Khóa màn hình bật"),
    ("usb_limited", "Ổ USB bị chặn hoặc chỉ đọc"),
    ("encrypted", "Ổ được mã hóa"),
    ("frozen", "Đang đóng băng"),
    ("with_problems", "Có vấn đề cần xem"),
)


def totals(table: list[dict[str, Any]]) -> dict[str, int]:
    counted = {key: sum(1 for item in table if item["facts"].get(key)) for key, _title in TOTALS}
    counted["machines"] = len(table)
    counted["with_problems"] = sum(1 for item in table if item["facts"]["problems"])
    return counted


def audit_extract(lines: list[dict[str, Any]], start: datetime.date, end: datetime.date) -> list[dict[str, Any]]:
    """The audit lines from start to end (both included), oldest first."""

    found = []
    for line in lines:
        when = health._parse(line.get("time"))  # noqa: SLF001
        if when and start <= when.date() <= end:
            found.append(line)
    return sorted(found, key=lambda line: line.get("time", ""))


def labour_rules_paragraph(policy: dict[str, Any]) -> str:
    """The paragraph to paste into the internal labour rules: the measures turned on anywhere in the company (for the
    whole company, a department or one machine), what every paired machine does, and what the company never sees."""

    on = set()
    layers = [policy.get("settings") or {}]
    layers += [(department or {}).get("settings") or {} for department in (policy.get("departments") or {}).values()]
    layers += [(machine or {}).get("settings") or {} for machine in (policy.get("machines") or {}).values()]
    for layer in layers:
        on.update(section for section, value in layer.items() if value is not None)
    measures = [MEASURES[section] for section in protocol.SECTIONS if section in on and section in MEASURES]
    lines = [
        "Điều …. Biện pháp kỹ thuật trên máy tính của công ty",
        "1. Máy tính công ty giao cho người lao động sử dụng được quản lý bằng phần mềm CaramOS Doanh nghiệp. Theo "
        "điểm a khoản 3 Điều 25 Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15, công ty thông báo để người lao động "
        "biết rõ các biện pháp kỹ thuật đang được áp dụng:",
    ]
    letters = "abcdđeghiklmnopqrstuvxy"
    always = ["máy báo cho công ty tên máy, người đang đăng nhập, phiên bản hệ điều hành và tình trạng kỹ thuật: dung "
              "lượng ổ đĩa, pin, bản cập nhật đang chờ, tường lửa, khóa màn hình, mã hóa ổ;",
              "bộ phận IT có thể khóa máy, gửi thông báo, khởi động lại hoặc tắt máy khi cần, luôn có báo trước trên "
              "màn hình; hỗ trợ từ xa chỉ bắt đầu khi người lao động đồng ý và có thanh báo suốt thời gian hỗ trợ;",
              "yêu cầu hỗ trợ người lao động gửi được lưu thành phiếu hỗ trợ;"]
    items = measures + always
    for index, item in enumerate(items):
        ending = "." if index == len(items) - 1 else ""
        lines.append(f"{letters[index]}) {item[:-1] + ending if ending else item}")
    lines.append("2. Phần mềm không ghi lại màn hình (trừ khi người lao động đồng ý cho hỗ trợ từ xa), không ghi lại "
                 "phím gõ, không lưu lịch sử trang web, tin nhắn hay vị trí, và không đọc tệp nằm ngoài thư mục của "
                 "công ty.")
    lines.append("3. Trên mỗi máy, trang \"Máy này do công ty quản lý\" của ứng dụng CaramOS Doanh nghiệp luôn liệt kê "
                 "đúng những biện pháp đang áp dụng trên máy đó.")
    return "\n".join(lines)


def period_text(start: datetime.date, end: datetime.date) -> str:
    return f"từ {text.vn_date(start.isoformat())} đến {text.vn_date(end.isoformat())}"

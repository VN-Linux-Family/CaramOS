"""Packaged CaramOS product release metadata."""

from __future__ import annotations

PRODUCT_VERSION = "1.5.2.3"

# What this version changes besides its migrations: a version that changes CaramOS's own programs, such as a hotfix
# (docs/release-version-tracking.md). The Update Center and "Xem có gì mới" show the title when no migration names
# the update, and the notes after the migrations' notes. Set them with each such version, and empty them at the next
# release: tools/prepare-release.py changes only PRODUCT_VERSION.
RELEASE_TITLE_VI = "Máy kiểm tra cập nhật sau mỗi lần mở máy"
RELEASE_TITLE_EN = "The computer checks for updates after each start"
# 1.5.2.2's notes stay: most computers check at midnight or at their next start, so they go from 1.5.2.1 or older
# straight to 1.5.2.3.
RELEASE_NOTES_VI: tuple[str, ...] = (
    "Máy kiểm tra cập nhật khoảng 15 phút sau mỗi lần mở máy, ngoài lần kiểm tra lúc nửa đêm. Máy văn phòng hay "
    "phòng máy tắt trước nửa đêm giờ nhận bản sửa ngay trong ngày được dùng.",
    "Bản Xfce: sau khi máy tự cập nhật trong lúc bạn đang dùng, thanh âm lượng vẫn là thanh dẹt có số phần trăm, "
    "không còn hiện trong một khung cao. Bản cập nhật nào đổi Trung tâm điều khiển thì Trung tâm điều khiển khởi động "
    "lại ngay: đồng hồ và nút Trung tâm điều khiển trên thanh tác vụ tắt đi vài giây rồi hiện lại.",
)
RELEASE_NOTES_EN: tuple[str, ...] = (
    "The computer checks for updates about 15 minutes after each start, besides the check at midnight. Office and "
    "school computers that are off before midnight now get fixes on the day they are used.",
    "Xfce edition: after the computer updates itself while you work, the sound level stays the slim bar with the "
    "percentage instead of showing in a tall box. An update that changes the Control Center starts it again at once: "
    "the clock and the Control Center button on the taskbar go away for a few seconds, then come back.",
)

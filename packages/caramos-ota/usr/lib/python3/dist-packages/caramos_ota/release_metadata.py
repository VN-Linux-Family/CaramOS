"""Packaged CaramOS product release metadata."""

from __future__ import annotations

PRODUCT_VERSION = "1.5.2.2"

# What this version changes besides its migrations: a version that changes CaramOS's own programs, such as a hotfix
# (docs/release-version-tracking.md). The Update Center and "Xem có gì mới" show the title when no migration names
# the update, and the notes after the migrations' notes. Set them with each such version, and empty them at the next
# release: tools/prepare-release.py changes only PRODUCT_VERSION.
RELEASE_TITLE_VI = "Thanh âm lượng bản Xfce hiện đúng sau khi cập nhật"
RELEASE_TITLE_EN = "The Xfce sound level looks right after an update"
RELEASE_NOTES_VI: tuple[str, ...] = (
    "Bản Xfce: sau khi máy tự cập nhật trong lúc bạn đang dùng, thanh âm lượng vẫn là thanh dẹt có số phần trăm, "
    "không còn hiện trong một khung cao. Bản cập nhật nào đổi Trung tâm điều khiển thì Trung tâm điều khiển khởi động "
    "lại ngay: đồng hồ và nút Trung tâm điều khiển trên thanh tác vụ tắt đi vài giây rồi hiện lại.",
)
RELEASE_NOTES_EN: tuple[str, ...] = (
    "Xfce edition: after the computer updates itself while you work, the sound level stays the slim bar with the "
    "percentage instead of showing in a tall box. An update that changes the Control Center starts it again at once: "
    "the clock and the Control Center button on the taskbar go away for a few seconds, then come back.",
)

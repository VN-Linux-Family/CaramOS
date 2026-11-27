"""Packaged CaramOS product release metadata."""

from __future__ import annotations

PRODUCT_VERSION = "1.5.2.1"

# What this version changes besides its migrations: a version that changes CaramOS's own programs, such as a hotfix
# (docs/release-version-tracking.md). The Update Center and "Xem có gì mới" show the title when no migration names
# the update, and the notes after the migrations' notes. Set them with each such version, and empty them at the next
# release: tools/prepare-release.py changes only PRODUCT_VERSION.
RELEASE_TITLE_VI = "Máy cũ tự cập nhật lúc khởi động"
RELEASE_TITLE_EN = "Older computers update themselves at start-up"
RELEASE_NOTES_VI: tuple[str, ...] = (
    "Máy đang ở CaramOS 1.3.3 trở về trước giờ tự lên bản mới: bản cập nhật nào phải chờ không ai đăng nhập thì máy "
    "cài ở lần khởi động sau, trước màn hình đăng nhập. Màn hình khởi động ghi “Đang cập nhật CaramOS” kèm số bước "
    "đã xong. Việc này chỉ có một lần với mỗi máy cũ; sau đó máy tự cập nhật ngầm như các bản mới.",
    "Máy Cinnamon không còn thấy mục cập nhật chỉ dành cho bản Xfce.",
)
RELEASE_NOTES_EN: tuple[str, ...] = (
    "Computers on CaramOS 1.3.3 or older now update themselves: an update that has to wait until nobody is logged in "
    "installs at the next start, before the login screen, with “Updating CaramOS” and the steps done on the start-up "
    "screen. This happens only once for each older computer; after it, updates install in the background as on the "
    "newer versions.",
    "Cinnamon computers no longer list an update that is only for the Xfce edition.",
)

#!/bin/bash
# ============================================================
# CaramOS Build Script
# Remaster từ Linux Mint ISO → CaramOS ISO
#
# Usage:
#   sudo ./build.sh                          # Dev build (lz4, nhanh)
#   sudo ./build.sh --release                 # Release build (xz, nhỏ)
#   sudo ./build.sh /path/to/mint.iso         # Dùng ISO có sẵn
#   sudo ./build.sh --clean                   # Dọn build cũ
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/scripts/config.sh"
source "$SCRIPT_DIR/scripts/utils.sh"
# Cấu hình debug boot: xoá quiet/splash, đổi tên distro, tắt plymouth
source "$SCRIPT_DIR/scripts/boot_config.sh"

# --- Clean ---
if [ "${1}" = "--clean" ]; then
    info "Dọn dẹp build..."
    sync 2>/dev/null || true
    umount "$WORK_DIR/squashfs/proc"    2>/dev/null || true
    umount "$WORK_DIR/squashfs/sys"     2>/dev/null || true
    umount "$WORK_DIR/squashfs/dev/pts" 2>/dev/null || true
    umount "$WORK_DIR/squashfs/dev"     2>/dev/null || true
    umount "$WORK_DIR/mnt"              2>/dev/null || true
    rm -rf "$WORK_DIR" CaramOS-*.iso *.log
    ok "Đã dọn xong. (Mint ISO giữ lại)"
    exit 0
fi

# --- Kiểm tra ---
check_root
install_deps
install_gum

# --- Trap: tự động dọn khi build thất bại ---
# Được kích hoạt bởi EXIT — không làm gì nếu BUILD_OK=1 (set cuối script)
# Mục đích: đảm bảo bind mounts luôn được umount dù build lỗi ở bất kỳ bước nào,
# tránh lặp lại bug rm -rf vào /dev /proc của host
cleanup_on_fail() {
    # Build thành công → bỏ qua
    [ "${BUILD_OK:-0}" = "1" ] && return 0

    # Dùng echo trực tiếp vì gum/utils có thể chưa sẵn sàng lúc trap chạy
    echo ""
    echo -e "\033[0;31m[ERROR ]\033[0m Build thất bại! Đang dọn dẹp tự động..."

    # Umount theo thứ tự ngược với mount — dev/pts phải trước dev
    sync 2>/dev/null || true
    umount "$WORK_DIR/squashfs/proc"    2>/dev/null || true
    umount "$WORK_DIR/squashfs/sys"     2>/dev/null || true
    umount "$WORK_DIR/squashfs/dev/pts" 2>/dev/null || true
    umount "$WORK_DIR/squashfs/dev"     2>/dev/null || true
    umount "$WORK_DIR/mnt"              2>/dev/null || true

    # Chỉ xoá nếu không còn mount nào — bảo vệ host khỏi rm -rf vào /dev /proc thật
    if grep -q " $WORK_DIR/squashfs/" /proc/mounts 2>/dev/null; then
        echo -e "\033[0;31m[ERROR ]\033[0m Vẫn còn mount trong squashfs — BỎ QUA xoá thư mục."
        echo -e "\033[0;31m[ERROR ]\033[0m Dọn thủ công: sudo umount -Rlf $WORK_DIR/squashfs && sudo rm -rf $WORK_DIR/squashfs $WORK_DIR/custom $WORK_DIR/mnt"
    else
        rm -rf "$WORK_DIR/squashfs" "$WORK_DIR/custom" "$WORK_DIR/mnt" 2>/dev/null || true
        echo -e "\033[1;33m[ WARN ]\033[0m Đã xoá build dirs (cache giữ lại để build lần sau nhanh hơn)."
    fi
}
trap cleanup_on_fail EXIT

# --- Release mode ---
ISO_ARG=""
for arg in "$@"; do
    case "$arg" in
        --release)
            SQUASHFS_COMP="xz"
            SQUASHFS_OPTS="-b 1M -Xdict-size 100% -noappend"
            info "Release mode: nén xz (chậm hơn, ISO nhỏ hơn)"
            ;;
        --clean) ;;
        *) ISO_ARG="$arg" ;;
    esac
done

# --- ISO input ---
resolve_iso "$ISO_ARG"

# --- Header ---
print_header

# --- Build ---
source "$SCRIPT_DIR/scripts/extract.sh"
source "$SCRIPT_DIR/scripts/customize.sh"
source "$SCRIPT_DIR/scripts/repack.sh"

step_extract
# Mặc định: chế độ debug — sửa bootloader + tắt plymouth ngay sau khi giải nén
step_boot_config
step_customize
step_repack

# Đánh dấu build thành công — trap EXIT sẽ bỏ qua cleanup_on_fail
BUILD_OK=1

# --- Kết quả ---
print_result

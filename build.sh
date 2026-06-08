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
#   sudo ./build.sh --quick                   # Overlay + repack nhanh
#   sudo ./build.sh --shell                   # Vào chroot để test/sửa
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/scripts/config.sh"
source "$SCRIPT_DIR/scripts/utils.sh"
source "$SCRIPT_DIR/scripts/extract.sh"
# Cấu hình debug boot: xoá quiet/splash, đổi tên distro, tắt plymouth
source "$SCRIPT_DIR/scripts/boot_config.sh"
source "$SCRIPT_DIR/scripts/overlay.sh"
source "$SCRIPT_DIR/scripts/customize.sh"
source "$SCRIPT_DIR/scripts/ota_bootstrap.sh"
source "$SCRIPT_DIR/scripts/chroot_shell.sh"
source "$SCRIPT_DIR/scripts/repack.sh"

MODE="full"
ISO_ARG=""
CLEAN_OUTPUT=false
DEBUG_BOOT=0

for arg in "$@"; do
    case "$arg" in
        --release)
            SQUASHFS_COMP="xz"
            SQUASHFS_OPTS="-b 1M -Xdict-size 100% -noappend"
            info "Release mode: nén xz (chậm hơn, ISO nhỏ hơn)"
            ;;
        --debug-boot)
            DEBUG_BOOT=1
            info "Debug boot: hiện kernel log, tắt quiet/splash"
            ;;
        --prepare|--boot-only|--overlay-only|--customize-only|--shell|--repack-only|--iso-only|--quick|--clean|--clean-work|--clean-cache|--help|-h)
            MODE="${arg#--}"
            ;;
        *)
            ISO_ARG="$arg"
            ;;
    esac
done

# --- Clean/help modes không cần tải/resolve ISO ---
case "$MODE" in
    help|-h)
        print_dev_help
        exit 0
        ;;
    clean)
        info "Dọn dẹp build..."
        safe_remove_work_dirs
        rm -rf "$WORK_DIR/cache" "$WORK_DIR/cache_iso" CaramOS-*.iso ./*.log
        ok "Đã dọn xong. (Mint ISO giữ lại)"
        exit 0
        ;;
    clean-work)
        info "Dọn work tree (giữ cache)..."
        safe_remove_work_dirs
        ok "Đã xoá work tree, cache vẫn giữ lại."
        exit 0
        ;;
    clean-cache)
        info "Dọn toàn bộ build cache/work tree..."
        safe_remove_work_dirs
        rm -rf "$WORK_DIR/cache" "$WORK_DIR/cache_iso"
        ok "Đã xoá cache/work tree."
        exit 0
        ;;
esac

# --- Kiểm tra ---
check_root
install_deps
install_gum

# --- Trap: tự động dọn mount khi build thất bại ---
cleanup_on_fail() {
    [ "${BUILD_OK:-0}" = "1" ] && return 0
    echo ""
    echo -e "\033[0;31m[ERROR ]\033[0m Build thất bại! Đang dọn mount an toàn..."
    umount_chroot
    umount "$WORK_DIR/mnt" 2>/dev/null || true

    if [ "$CLEAN_OUTPUT" = true ]; then
        safe_remove_work_dirs || true
    else
        echo -e "\033[1;33m[ WARN ]\033[0m Giữ lại build dirs để bạn kiểm tra/sửa tiếp."
    fi
}
trap cleanup_on_fail EXIT

# --- ISO input ---
resolve_iso "$ISO_ARG"

validate_customized_rootfs() {
    [ -f "$WORK_DIR/squashfs/etc/caramos-customized" ] || return 1

    chroot "$WORK_DIR/squashfs" /bin/bash -c "test -f /etc/dconf/db/local && test -f /etc/xdg/autostart/caramos-theme.desktop && test -f /etc/xdg/autostart/plank.desktop && test -d /etc/skel/.config/plank/dock1 && test -d /usr/share/cinnamon/applets/Cinnamenu@json && find /usr/share/cinnamon/applets/Cinnamenu@json -name settings-schema.json -print -quit | grep -q . && test -f /usr/share/plymouth/themes/caramos/caramos.plymouth"
}

# --- Header ---
print_header

case "$MODE" in
    full)
        CLEAN_OUTPUT=true
        step_extract
        step_boot_config
        step_customize
        step_repack_and_clean
        ;;
    prepare)
        step_extract
        ;;
    boot-only)
        ensure_work_tree
        step_boot_config
        ;;
    overlay-only)
        ensure_work_tree
        step_overlay
        ;;
    customize-only)
        ensure_work_tree
        step_customize
        ;;
    shell)
        step_chroot_shell
        ;;
    repack-only)
        ensure_work_tree
        step_repack
        ;;
    iso-only)
        ensure_work_tree
        step_repack_iso
        ;;
    quick)
        ensure_work_tree
        step_boot_config
        if ! validate_customized_rootfs; then
            warn "Work tree chưa customize đầy đủ hoặc marker cũ không hợp lệ. Chạy customize trước khi repack."
            rm -f "$WORK_DIR/squashfs/etc/caramos-customized" 2>/dev/null || true
            step_customize
        else
            step_overlay
        fi
        step_repack
        ;;
    *)
        error "Mode không hỗ trợ: $MODE. Chạy sudo ./build.sh --help để xem hướng dẫn."
        ;;
esac

BUILD_OK=1

case "$MODE" in
    shell|prepare|boot-only|overlay-only|customize-only)
        ok "Hoàn tất mode: $MODE"
        ;;
    *)
        print_result
        ;;
esac

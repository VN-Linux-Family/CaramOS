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
#   sudo ./build.sh --verbose                 # Debug mode
#   sudo ./build.sh --keep-work               # Giữ work dir sau build
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/scripts/config.sh"
source "$SCRIPT_DIR/scripts/utils.sh"
source "$SCRIPT_DIR/scripts/extract.sh"
source "$SCRIPT_DIR/scripts/boot_config.sh"
source "$SCRIPT_DIR/scripts/overlay.sh"
source "$SCRIPT_DIR/scripts/customize.sh"
source "$SCRIPT_DIR/scripts/ota_bootstrap.sh"
source "$SCRIPT_DIR/scripts/chroot_shell.sh"
source "$SCRIPT_DIR/scripts/repack.sh"

# Mặc định
MODE="full"
ISO_ARG=""
AUTO_CLEAN_ON_FAIL=false
KEEP_WORK=false
VERBOSE=false
RELEASE_MODE=0
DEBUG_BOOT=0
SQUASHFS_COMP="${SQUASHFS_COMP:-lz4}"
SQUASHFS_OPTS="${SQUASHFS_OPTS:--b 256K -Xhc}"

# Parse arguments
for arg in "$@"; do
    case "$arg" in
        --release)
            RELEASE_MODE=1
            SQUASHFS_COMP="xz"
            SQUASHFS_OPTS="-b 1M -Xdict-size 100% -noappend"
            info "Release mode: nén xz (chậm hơn, ISO nhỏ hơn)"
            ;;
        --debug-boot)
            DEBUG_BOOT=1
            info "Debug boot: hiện kernel log, tắt quiet/splash"
            ;;
        --verbose|-v)
            VERBOSE=true
            set -x
            ;;
        --keep-work)
            KEEP_WORK=true
            info "Will keep work directory after build"
            ;;
        --prepare|--boot-only|--overlay-only|--customize-only|--shell|--repack-only|--iso-only|--quick)
            MODE="${arg#--}"
            ;;
        --clean)
            MODE="clean"
            ;;
        --clean-work)
            MODE="clean-work"
            ;;
        --clean-cache)
            MODE="clean-cache"
            ;;
        --help|-h)
            MODE="help"
            ;;
        *)
            ISO_ARG="$arg"
            ;;
    esac
done

export SQUASHFS_COMP SQUASHFS_OPTS DEBUG_BOOT WORK_DIR SCRIPT_DIR RELEASE_MODE

print_dev_help() {
    cat <<EOF
CaramOS Build Script - Hướng dẫn sử dụng

CÁCH DÙNG:
  sudo ./build.sh [OPTIONS] [ISO_PATH]

OPTIONS:
  --release              Build release (nén xz, ISO nhỏ hơn)
  --debug-boot           Bật debug boot (hiện logs)
  --quick                Overlay + repack nhanh (bỏ qua customize)
  --shell                Mở chroot shell để debug
  --prepare              Chỉ extract ISO
  --boot-only            Chỉ sửa boot config
  --overlay-only         Chỉ apply overlay
  --customize-only       Chỉ chạy customize
  --repack-only          Chỉ repack ISO
  --iso-only             Chỉ tạo ISO từ work dir
  --clean                Dọn sạch build (giữ cache)
  --clean-work           Dọn work dir (giữ cache)
  --clean-cache          Dọn sạch cache và work dir
  --keep-work            Giữ work dir sau build
  --verbose, -v          Hiển thị debug logs
  --help, -h             Hiển thị help này

VÍ DỤ:
  sudo ./build.sh                              # Dev build
  sudo ./build.sh --release                    # Release build
  sudo ./build.sh --quick --release            # Quick release build
  sudo ./build.sh /path/to/mint.iso            # Dùng ISO tùy chỉnh
  sudo ./build.sh --shell                      # Debug trong chroot
  sudo ./build.sh --clean                      # Dọn build
EOF
}

check_disk_space() {
    local required_gb=10
    local available_gb
    available_gb=$(df -BG "$WORK_DIR" 2>/dev/null | awk 'NR==2 {print $4}' | sed 's/G//' || echo "0")
    
    if [ "$available_gb" -lt "$required_gb" ]; then
        warn "Only ${available_gb}GB available, need ${required_gb}GB"
        warn "Build may fail due to insufficient disk space"
        if [ "${FORCE:-0}" != "1" ]; then
            read -p "Continue anyway? [y/N] " -r
            if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi
    fi
}

validate_customized_rootfs() {
    local rootfs="$WORK_DIR/squashfs"
    
    if [ ! -f "$rootfs/etc/caramos-customized" ]; then
        warn "Missing marker file: /etc/caramos-customized"
        return 1
    fi
    
    local checks=(
        "/etc/dconf/db/local"
        "/etc/xdg/autostart/caramos-theme.desktop"
        "/etc/xdg/autostart/plank.desktop"
        "/etc/skel/.config/plank/dock1"
        "/usr/share/cinnamon/applets/Cinnamenu@json/settings-schema.json"
        "/usr/share/plymouth/themes/caramos/caramos.plymouth"
    )
    
    local missing=()
    for check in "${checks[@]}"; do
        if ! chroot "$rootfs" test -e "$check" 2>/dev/null; then
            missing+=("$check")
        fi
    done
    
    if [ ${#missing[@]} -gt 0 ]; then
        warn "Missing files: ${missing[*]}"
        return 1
    fi
    
    return 0
}

# Xử lý các mode đặc biệt (không cần ISO)
case "$MODE" in
    help)
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

# Kiểm tra môi trường build
check_root
install_deps
install_gum
check_disk_space

# Dọn mount khi build fail (trừ khi đang ở chroot shell)
cleanup_on_fail() {
    [ "${BUILD_OK:-0}" = "1" ] && return 0
    
    if [ "$MODE" = "shell" ]; then
        echo ""
        echo -e "\033[1;33m[INFO]\033[0m Bạn đang ở chroot shell. Thoát bằng 'exit' để umount."
        return 0
    fi
    
    echo ""
    echo -e "\033[0;31m[ERROR]\033[0m Build thất bại! Đang dọn mount an toàn..."
    umount_chroot 2>/dev/null || true
    umount "$WORK_DIR/mnt" 2>/dev/null || true

    if [ "$AUTO_CLEAN_ON_FAIL" = true ] && [ "$KEEP_WORK" != true ]; then
        safe_remove_work_dirs || true
        echo "Đã dọn work dir."
    else
        echo -e "\033[1;33m[WARN]\033[0m Giữ lại build dirs để bạn kiểm tra/sửa tiếp:"
        echo "  - $WORK_DIR"
        echo "  - Chạy 'sudo ./build.sh --shell' để vào chroot"
    fi
}
trap cleanup_on_fail EXIT

# Resolve ISO input
if [ "$MODE" != "help" ] && [ "$MODE" != "clean" ] && [ "$MODE" != "clean-work" ] && [ "$MODE" != "clean-cache" ]; then
    resolve_iso "$ISO_ARG"
fi

print_header

# Build modes
case "$MODE" in
    full)
        AUTO_CLEAN_ON_FAIL=true
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
            warn "Work tree chưa customize đầy đủ hoặc marker cũ không hợp lệ."
            warn "Chạy customize trước khi repack..."
            rm -f "$WORK_DIR/squashfs/etc/caramos-customized" 2>/dev/null || true
            step_customize
        else
            info "Rootfs đã customized, skip customize step"
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
        if [ "$KEEP_WORK" != true ]; then
            info "Work dir: $WORK_DIR (giữ lại để debug)"
        fi
        ;;
    *)
        if [ "$KEEP_WORK" = true ]; then
            info "Work dir kept: $WORK_DIR"
        fi
        print_result
        ;;
esac

# Dọn work dir nếu không cần giữ lại
if [ "$KEEP_WORK" != true ] && [ "$MODE" != "shell" ] && [ "$MODE" != "prepare" ] && [ "$MODE" != "boot-only" ] && [ "$MODE" != "overlay-only" ] && [ "$MODE" != "customize-only" ]; then
    info "Cleaning up work directory..."
    safe_remove_work_dirs
fi

exit 0

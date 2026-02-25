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
step_customize
step_repack

# --- Kết quả ---
print_result

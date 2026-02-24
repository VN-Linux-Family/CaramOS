#!/bin/bash
# ============================================================
# CaramOS Build Script
# Remaster từ Linux Mint ISO → CaramOS ISO
#
# Usage:
#   sudo ./build.sh                          # Tự tải ISO Mint
#   sudo ./build.sh /path/to/mint.iso        # Dùng ISO có sẵn
#   sudo ./build.sh --clean                  # Dọn build cũ
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/scripts/config.sh"
source "$SCRIPT_DIR/scripts/utils.sh"

# --- Clean ---
if [ "${1}" = "--clean" ]; then
    info "Dọn dẹp build..."
    rm -rf "$WORK_DIR" *.iso *.log
    ok "Đã dọn xong."
    exit 0
fi

# --- Kiểm tra ---
check_root
install_deps
install_gum

# --- ISO input ---
resolve_iso "$1"

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

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

# --- ISO input ---
resolve_iso "$1"

echo ""
echo "============================================"
echo -e "  ${CYAN}CaramOS ${CARAMOS_VERSION}${NC} — Build từ Linux Mint"
echo "============================================"
echo "  Input:  $MINT_ISO"
echo "  Output: $OUTPUT_ISO"
echo ""

# --- Build ---
source "$SCRIPT_DIR/scripts/extract.sh"
source "$SCRIPT_DIR/scripts/customize.sh"
source "$SCRIPT_DIR/scripts/repack.sh"

step_extract
step_customize
step_repack

# --- Kết quả ---
echo ""
echo "============================================"
echo -e "  ${GREEN}✅ Build thành công!${NC}"
echo ""
echo "  ISO:  $OUTPUT_ISO"
echo "  Size: $(du -h "$OUTPUT_ISO" | cut -f1)"
echo ""
echo "  Ghi USB:"
echo "    sudo dd if=$OUTPUT_ISO of=/dev/sdX bs=4M status=progress"
echo ""
echo "  Test VM:"
echo "    qemu-system-x86_64 -m 4G -cdrom $OUTPUT_ISO -boot d -enable-kvm"
echo "============================================"

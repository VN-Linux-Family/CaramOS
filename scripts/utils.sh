#!/bin/bash
# Hàm tiện ích dùng chung

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${CYAN}[CaramOS]${NC} $1"; }
ok()    { echo -e "${GREEN}[  OK  ]${NC} $1"; }
warn()  { echo -e "${YELLOW}[ WARN ]${NC} $1"; }
error() { echo -e "${RED}[ERROR ]${NC} $1"; exit 1; }

check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        error "Cần chạy với sudo: sudo ./build.sh"
    fi
}

install_deps() {
    local DEPS="squashfs-tools xorriso rsync wget"
    local MISSING=""
    for cmd in unsquashfs mksquashfs xorriso rsync wget; do
        command -v "$cmd" &>/dev/null || MISSING="yes"
    done
    if [ -n "$MISSING" ]; then
        info "Cài công cụ build: $DEPS"
        apt-get update -qq
        apt-get install -y $DEPS
        ok "Đã cài xong công cụ."
    fi
}

resolve_iso() {
    if [ -n "$1" ] && [ -f "$1" ]; then
        MINT_ISO="$1"
        info "Dùng ISO: $MINT_ISO"
    elif [ -f "$MINT_ISO_NAME" ]; then
        MINT_ISO="$MINT_ISO_NAME"
        info "Tìm thấy ISO: $MINT_ISO"
    else
        info "Tải Linux Mint ${MINT_VERSION} ${MINT_EDITION}..."
        wget -c "$MINT_MIRROR" -O "$MINT_ISO_NAME"
        MINT_ISO="$MINT_ISO_NAME"
        ok "Tải xong: $MINT_ISO"
    fi
}

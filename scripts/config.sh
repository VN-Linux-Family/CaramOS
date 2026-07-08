#!/bin/bash
# Cấu hình build — đổi version/mirror ở đây

MINT_VERSION="22.3"
MINT_EDITION="cinnamon"
MINT_ARCH="64bit"
MINT_ISO_NAME="linuxmint-${MINT_VERSION}-${MINT_EDITION}-${MINT_ARCH}.iso"
if [ "$GITHUB_ACTIONS" = "true" ]; then
    MINT_MIRROR="https://mirrors.kernel.org/linuxmint/stable/${MINT_VERSION}/${MINT_ISO_NAME}"
else
    MINT_MIRROR="https://mirror.clearsky.vn/linuxmint/iso/stable/${MINT_VERSION}/${MINT_ISO_NAME}"
fi

# CaramOS release version — source of truth cho tên ISO/tag release.
# Khi release, Git tag phải khớp với version này (ví dụ: CARAMOS_VERSION=1.0.12 → tag v1.0.12).
CARAMOS_VERSION_MAJOR=1
CARAMOS_VERSION_MINOR=0
CARAMOS_VERSION_PATCH=12
CARAMOS_VERSION_EXTRA=""
CARAMOS_CODENAME="Open Beta"
CARAMOS_VERSION="${CARAMOS_VERSION_MAJOR}.${CARAMOS_VERSION_MINOR}.${CARAMOS_VERSION_PATCH}${CARAMOS_VERSION_EXTRA}"

# Version metadata ban đầu ghi vào rootfs trước khi chạy OTA bootstrap.
# Giữ 1.0.1 để build ISO luôn chạy đầy đủ migration chain 1.0.1 → latest.
CARAMOS_MIGRATION_BASE_VERSION="1.0.1"

OUTPUT_ISO="CaramOS-${CARAMOS_VERSION}-${MINT_EDITION}-amd64.iso"
WORK_DIR="./build"
# Nén mặc định: lz4 (nhanh cho dev). --release sẽ đổi sang xz (nhỏ, nén lâu)
SQUASHFS_COMP="lz4"
SQUASHFS_OPTS="-noappend"

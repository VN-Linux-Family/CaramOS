#!/bin/bash
# Build configuration — change version/mirror here

MINT_VERSION="22.3"
MINT_EDITION="cinnamon"
MINT_ARCH="64bit"
MINT_ISO_NAME="linuxmint-${MINT_VERSION}-${MINT_EDITION}-${MINT_ARCH}.iso"
if [ "$GITHUB_ACTIONS" = "true" ]; then
    MINT_MIRROR="https://mirrors.kernel.org/linuxmint/stable/${MINT_VERSION}/${MINT_ISO_NAME}"
else
    MINT_MIRROR="https://mirror.clearsky.vn/linuxmint/iso/stable/${MINT_VERSION}/${MINT_ISO_NAME}"
fi

# CaramOS product version. `make release VERSION=x` stamps this value.
CARAMOS_VERSION="1.0.0"
CARAMOS_CODENAME="Open Beta"

# Version metadata initially written to rootfs before running OTA bootstrap.
# Keep 1.0.1 so ISO build always runs full migration chain 1.0.1 → latest.
CARAMOS_MIGRATION_BASE_VERSION="1.0.1"

OUTPUT_ISO="CaramOS-${CARAMOS_VERSION}-${MINT_EDITION}-amd64.iso"
WORK_DIR="./build"
# Default compression: zstd (fast for dev). --release will switch to zstd level 19 (smaller, slower)
SQUASHFS_COMP="zstd"
SQUASHFS_OPTS="-b 1M -Xcompression-level 15 -noappend"

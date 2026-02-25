#!/bin/bash
# Cấu hình build — đổi version/mirror ở đây

MINT_VERSION="22.3"
MINT_EDITION="cinnamon"
MINT_ARCH="64bit"
MINT_ISO_NAME="linuxmint-${MINT_VERSION}-${MINT_EDITION}-${MINT_ARCH}.iso"
MINT_MIRROR="https://mirror.meowsmp.net/linuxmint/iso/stable/${MINT_VERSION}/${MINT_ISO_NAME}"
CARAMOS_VERSION="0.1"
OUTPUT_ISO="CaramOS-${CARAMOS_VERSION}-${MINT_EDITION}-amd64.iso"
WORK_DIR="./build"
# Nén mặc định: lz4 (nhanh cho dev). --release sẽ đổi sang xz (nhỏ, nén lâu)
SQUASHFS_COMP="lz4"
SQUASHFS_OPTS="-noappend"

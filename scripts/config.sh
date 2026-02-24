#!/bin/bash
# Cấu hình build — đổi version/mirror ở đây

MINT_VERSION="22"
MINT_EDITION="cinnamon"
MINT_ARCH="64bit"
MINT_ISO_NAME="linuxmint-${MINT_VERSION}-${MINT_EDITION}-${MINT_ARCH}.iso"
MINT_MIRROR="https://mirrors.kernel.org/linuxmint/stable/${MINT_VERSION}/${MINT_ISO_NAME}"

CARAMOS_VERSION="0.1"
OUTPUT_ISO="CaramOS-${CARAMOS_VERSION}-${MINT_EDITION}-amd64.iso"
WORK_DIR="./build"

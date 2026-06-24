#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DIST_DIR="${PKG_DIR}/dist-testkit"
REMOTE_USER="${REMOTE_USER:-caram}"
REMOTE_HOST="${REMOTE_HOST:-127.0.0.1}"
REMOTE_PORT="${REMOTE_PORT:-2222}"
REMOTE_DIR="${REMOTE_DIR:-/tmp/caramos-ota-e2e}"
TEST_RELEASE_FROM="${TEST_RELEASE_FROM:-1.0.1}"
# Test-only live-boot VM password. Override with REMOTE_PASSWORD=... if needed.
REMOTE_PASSWORD="${REMOTE_PASSWORD:-caram}"

usage() {
  cat <<EOF
Build and ship CaramOS OTA test artifacts to a VM.

Usage:
  REMOTE_USER=caram REMOTE_HOST=127.0.0.1 REMOTE_PORT=2222 ./tools/ship-ota-to-vm.sh

Defaults:
  REMOTE_USER=${REMOTE_USER}
  REMOTE_HOST=${REMOTE_HOST}
  REMOTE_PORT=${REMOTE_PORT}
  REMOTE_DIR=${REMOTE_DIR}

What it does:
  1. Build caramos-ota .deb via tools/caramos-ota-testkit.sh build-deb
  2. Clean and recreate REMOTE_DIR on the VM
  3. Copy .deb, guest runner scripts, and VM Makefile to the VM
  4. Install the shipped .deb in the VM
  5. Print the commands to run inside the VM

Password automation:
  Uses sshpass with REMOTE_PASSWORD=${REMOTE_PASSWORD} when sshpass is installed.
  This is intended only for the disposable CaramOS live-boot VM.
EOF
}

remote_ssh() {
  if command -v sshpass >/dev/null 2>&1; then
    sshpass -p "${REMOTE_PASSWORD}" ssh -o StrictHostKeyChecking=accept-new -p "${REMOTE_PORT}" "${REMOTE_USER}@${REMOTE_HOST}" "$@"
    return
  fi
  ssh -p "${REMOTE_PORT}" "${REMOTE_USER}@${REMOTE_HOST}" "$@"
}

remote_scp() {
  if command -v sshpass >/dev/null 2>&1; then
    sshpass -p "${REMOTE_PASSWORD}" scp -o StrictHostKeyChecking=accept-new -P "${REMOTE_PORT}" "$@"
    return
  fi
  scp -P "${REMOTE_PORT}" "$@"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

cd "${PKG_DIR}"
./tools/caramos-ota-testkit.sh build-deb

deb="$(find "${DIST_DIR}" -maxdepth 1 -type f -name 'caramos-ota_*.deb' | sort | tail -n 1)"
if [[ -z "${deb}" || ! -f "${deb}" ]]; then
  echo "Error: built .deb not found in ${DIST_DIR}" >&2
  exit 1
fi

remote_ssh "rm -rf -- '${REMOTE_DIR}' && mkdir -p -- '${REMOTE_DIR}'"
remote_scp \
  "${deb}" \
  "${PKG_DIR}/tools/vm-run-ota-e2e.sh" \
  "${PKG_DIR}/tools/purge-caramos-ota.sh" \
  "${PKG_DIR}/tools/Makefile.vm" \
  "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"

remote_ssh "chmod +x '${REMOTE_DIR}/vm-run-ota-e2e.sh' '${REMOTE_DIR}/purge-caramos-ota.sh' && mv '${REMOTE_DIR}/Makefile.vm' '${REMOTE_DIR}/Makefile'"
remote_ssh "printf '%s\\n' '${REMOTE_PASSWORD}' | sudo -S /bin/sh -c 'cat > /etc/caramos-release <<EOF
NAME=CaramOS
VERSION=${TEST_RELEASE_FROM}
VERSION_ID=${TEST_RELEASE_FROM}
VERSION_CODENAME=noble
UBUNTU_CODENAME=noble
CHANNEL=stable
ID=caramos
ID_LIKE=\"linuxmint ubuntu debian\"
PRETTY_NAME=\"CaramOS ${TEST_RELEASE_FROM}\"
EOF'"
remote_ssh "cd '${REMOTE_DIR}' && printf '%s\\n' '${REMOTE_PASSWORD}' | sudo -S ./vm-run-ota-e2e.sh install-shipped"

cat <<EOF
[OK] Shipped and installed OTA test artifacts to ${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}

Run this in the VM SSH session to execute the full default E2E flow:
  cd ${REMOTE_DIR}
  make test

For notifier GUI test, run inside the VM desktop terminal:
  cd ${REMOTE_DIR}
  make test-notifier
EOF

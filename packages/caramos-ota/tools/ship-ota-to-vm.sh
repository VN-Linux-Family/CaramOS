#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DIST_DIR="${PKG_DIR}/dist-testkit"
REMOTE_DIR="${REMOTE_DIR:-/tmp/caramos-ota-e2e}"
TEST_RELEASE_FROM="${TEST_RELEASE_FROM:-1.0.16.1}"
if [[ -z "${TEST_RELEASE_TARGET:-}" ]]; then
  TEST_RELEASE_TARGET="$(PYTHONPATH="${PKG_DIR}/usr/lib/python3/dist-packages" python3 -c 'from caramos_ota.release_metadata import PRODUCT_VERSION; print(PRODUCT_VERSION)')"
fi

# VM target (libvirt domain or REMOTE_HOST), SSH and sudo helpers.
# shellcheck source=tools/vm-common.sh
source "${SCRIPT_DIR}/vm-common.sh"

usage() {
  cat <<EOF
Build and ship CaramOS OTA test artifacts to a VM.

Usage:
  ./tools/ship-ota-to-vm.sh                                   # libvirt domain ${VM_DOMAIN}
  REMOTE_HOST=127.0.0.1 REMOTE_PORT=2222 ./tools/ship-ota-to-vm.sh   # any VM with key login and passwordless sudo

Current target:
  VM_DOMAIN=${VM_DOMAIN}  (used when REMOTE_HOST is empty)
  REMOTE_USER=${REMOTE_USER}
  REMOTE_HOST=${REMOTE_HOST:-<auto from libvirt>}
  REMOTE_PORT=${REMOTE_PORT}
  REMOTE_DIR=${REMOTE_DIR}

What it does:
  1. Build caramos-ota .deb via tools/caramos-ota-testkit.sh build-deb
  2. Copy the .deb, the guest runner scripts and the VM Makefile to the VM (~/.caramos-vm/ship)
  3. In the VM (tools/vm-guest/ship.sh): recreate REMOTE_DIR with them, install the shipped .deb,
     seed the VM at CaramOS ${TEST_RELEASE_FROM} and detect the ${TEST_RELEASE_TARGET} migration
  4. Print the next commands

Authentication:
  SSH key + passwordless sudo, both typed into the VM once by: make vm-bootstrap
  See VM_DEV_WORKFLOW.md.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

# Fail before the (slow) package build if the VM is not usable.
vm_require_ip
vm_ssh_ok || vm_die "cannot SSH to ${REMOTE_USER}@$(vm_ip):${REMOTE_PORT}. New VM: make vm-bootstrap, make vm-setup"
vm_require_sudo

cd "${PKG_DIR}"
./tools/caramos-ota-testkit.sh build-deb

deb="$(find "${DIST_DIR}" -maxdepth 1 -type f -name 'caramos-ota_*.deb' | sort | tail -n 1)"
if [[ -z "${deb}" || ! -f "${deb}" ]]; then
  echo "Error: built .deb not found in ${DIST_DIR}" >&2
  exit 1
fi

payload="$(mktemp -d)"
# shellcheck disable=SC2064
trap "rm -rf '${payload}'" EXIT
cp "${deb}" "${PKG_DIR}/tools/vm-run-ota-e2e.sh" "${PKG_DIR}/tools/purge-caramos-ota.sh" "${PKG_DIR}/tools/Makefile.vm" "${payload}/"
vm_push_guest
vm_push "${payload}" "${VM_GUEST_DIR}/ship" --delete
vm_run ship.sh "${REMOTE_DIR}" "${TEST_RELEASE_FROM}" "${TEST_RELEASE_TARGET}"

cat <<EOF
[OK] Shipped OTA test artifacts and prepared the ${TEST_RELEASE_TARGET} Update Center state at ${REMOTE_USER}@$(vm_ip):${REMOTE_DIR}

Next, from this host:
  make test            # full CLI migration E2E in the VM
  make test-notifier   # open the Update Center in the VM desktop
  make vm-logs         # pull OTA state/logs back to dist-testkit/vm-logs/
  make vm-shot         # screenshot the VM desktop
  make vm-reset        # throw away everything the migration did
EOF

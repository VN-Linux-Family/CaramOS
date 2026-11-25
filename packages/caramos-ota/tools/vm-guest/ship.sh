#!/bin/bash
# ship.sh <dir> <release from> <release target> (ship-ota-to-vm.sh): put the files copied to ~/.caramos-vm/ship (the
# .deb, vm-run-ota-e2e.sh, purge-caramos-ota.sh, Makefile.vm) in <dir>, make the VM say it runs CaramOS <release from>,
# install the shipped .deb and prepare the Update Center check for <release target>.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "${here}/lib.sh"
need_sudo
dir="$1" from="$2" target="$3"
rm -rf -- "${dir}"
mkdir -p -- "${dir}"
cp -- "${here}/ship/"* "${dir}/"
chmod +x "${dir}/vm-run-ota-e2e.sh" "${dir}/purge-caramos-ota.sh"
mv "${dir}/Makefile.vm" "${dir}/Makefile"
sudo -n tee /etc/caramos-release >/dev/null <<RELEASE
NAME=CaramOS
VERSION=${from}
VERSION_ID=${from}
VERSION_CODENAME=noble
UBUNTU_CODENAME=noble
CHANNEL=stable
ID=caramos
ID_LIKE="linuxmint ubuntu debian"
PRETTY_NAME="CaramOS ${from}"
RELEASE
cd "${dir}"
sudo -n ./vm-run-ota-e2e.sh install-shipped
sudo -n env TEST_RELEASE_FROM="${from}" TEST_RELEASE_TARGET="${target}" ./vm-run-ota-e2e.sh prepare-check

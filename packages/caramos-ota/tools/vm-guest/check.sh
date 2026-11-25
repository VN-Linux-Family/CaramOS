#!/bin/bash
# check.sh: fails unless passwordless sudo works (ship-ota-to-vm.sh asks before its slow package build).
here="$(cd "$(dirname "$0")" && pwd)"
. "${here}/lib.sh"
need_sudo
echo "sudo ok"

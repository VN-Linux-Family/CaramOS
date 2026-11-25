#!/bin/bash
# after-revert.sh <epoch> [keep-ota-timer]: run by vm-dev.sh reset right after a snapshot revert.
#
# A reverted VM wakes up at the moment the snapshot was taken; apt rejects repos "from the future", so the clock is set
# to the host's (<epoch>, seconds since 1970, UTC). Jumping the clock forward also makes the daily
# caramos-ota-check.timer due at once. Installing a .deb restarts that timer (postinst), the timer runs
# `caramos-ota --check`, and the check self-updates caramos-ota from the PPA over the package under test while holding
# the OTA lock. So the background check service is masked for this boot only (/run, gone after the next revert or
# reboot). The CLI (`caramos-ota --check`) still works. keep-ota-timer=1 (VM_KEEP_OTA_TIMER=1) keeps it.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
. "${here}/lib.sh"
need_sudo
epoch="$1"
keep="${2:-0}"
case "${epoch}" in '' | *[!0-9]*) echo "after-revert.sh: not a number of seconds: ${epoch}" >&2; exit 2 ;; esac
if [ "${keep}" != 1 ]; then
  sudo -n systemctl mask --runtime --now caramos-ota-check.service >/dev/null 2>&1
  sudo -n systemctl stop caramos-ota-check.timer
fi
sudo -n date -u -s "@${epoch}" >/dev/null

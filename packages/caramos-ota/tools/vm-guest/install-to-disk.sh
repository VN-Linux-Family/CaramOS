#!/bin/bash
# install-to-disk.sh (vm-dev.sh install-to-disk): start ubiquity's automatic install in the live session, answered by
# the preseed that vm-dev.sh copied to ~/.caramos-vm/install/preseed.cfg. Returns at once; wait-installer.sh waits.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "${here}/lib.sh"
need_sudo
sudo -n debconf-set-selections "${here}/install/preseed.cfg"
session_env
cd /
nohup setsid sudo -n --preserve-env=DISPLAY,XAUTHORITY,DBUS_SESSION_BUS_ADDRESS,XDG_RUNTIME_DIR \
  env WEBKIT_DISABLE_COMPOSITING_MODE=1 ubiquity --automatic gtk_ui >/tmp/caramos-vm-install.log 2>&1 </dev/null &
echo "[OK] installer started (log: /tmp/caramos-vm-install.log in the VM)"

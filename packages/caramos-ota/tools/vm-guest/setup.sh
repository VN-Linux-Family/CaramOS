#!/bin/bash
# setup.sh: one-time preparation of a new test VM (vm-dev.sh setup), after vm-dev.sh bootstrap typed the host's SSH key
# and the passwordless sudo rule into it: guest packages, and no screen lock or blanking, so screenshots show the
# desktop.
set -u
here="$(cd "$(dirname "$0")" && pwd)"
. "${here}/lib.sh"
need_sudo
echo "== installing guest packages =="
for f in /etc/apt/sources.list /etc/apt/sources.list.d/*; do
  [ -f "${f}" ] && sudo -n sed -i '/^deb cdrom:/ s/^/#/' "${f}"
done
sudo -n apt-get update || true
sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y -q -o Dpkg::Use-Pty=0 openssh-server qemu-guest-agent rsync || exit 1
sudo -n systemctl enable --now ssh
sudo -n systemctl start qemu-guest-agent || true

echo "== disabling screen lock / blanking so screenshots show the desktop =="
session_env
if gsettings set org.cinnamon.desktop.screensaver lock-enabled false &&
  gsettings set org.cinnamon.desktop.session idle-delay 0 &&
  gsettings set org.cinnamon.settings-daemon.plugins.power sleep-display-ac 0 &&
  gsettings set org.cinnamon.settings-daemon.plugins.power sleep-inactive-ac-timeout 0; then
  echo "[OK] screen lock and blanking off"
else
  echo "Warning: could not change desktop settings (is $(id -un) logged in to a Cinnamon desktop?)"
fi

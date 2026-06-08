#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Error: run with sudo/root." >&2
  exit 2
fi

echo "== stopping OTA services =="
systemctl disable --now caramos-ota-check.timer 2>/dev/null || true
systemctl stop caramos-ota-check.service 2>/dev/null || true
pkill -f caramos-ota-notifier 2>/dev/null || true

echo "== purging caramos-ota package =="
if dpkg -s caramos-ota >/dev/null 2>&1; then
  apt purge -y caramos-ota
else
  echo "caramos-ota package is not installed"
fi
apt autoremove -y || true

echo "== removing OTA files managed by test/package =="
rm -f /etc/apt/sources.list.d/caramos-ppa.sources
rm -f /usr/share/keyrings/caramos-archive-keyring.gpg
rm -f /etc/xdg/autostart/caramos-ota-notifier.desktop
rm -f /etc/logrotate.d/caramos-ota
rm -f /usr/share/polkit-1/actions/net.vietnamlinuxfamily.caramos-ota.policy
rm -f /lib/systemd/system/caramos-ota-check.service
rm -f /lib/systemd/system/caramos-ota-check.timer
rm -f /usr/bin/caramos-ota /usr/bin/caramos-ota-notifier /usr/bin/caramos-ota-update
rm -rf /usr/lib/python3/dist-packages/caramos_ota
rm -rf /usr/lib/python3/dist-packages/caramos_ota_notifier
rm -rf /usr/lib/python3/dist-packages/caramos_ota_update
rm -rf /usr/share/caramos-ota
rm -rf /var/lib/caramos-ota
rm -rf /var/log/caramos-ota

systemctl daemon-reload 2>/dev/null || true

echo "== verification =="
if dpkg -s caramos-ota >/dev/null 2>&1; then
  echo "WARN: package still installed"
else
  echo "[OK] package not installed"
fi
command -v caramos-ota 2>/dev/null && echo "WARN: caramos-ota still in PATH" || true
command -v caramos-ota-notifier 2>/dev/null && echo "WARN: caramos-ota-notifier still in PATH" || true
command -v caramos-ota-update 2>/dev/null && echo "WARN: caramos-ota-update still in PATH" || true

echo "[OK] caramos-ota cleanup complete"

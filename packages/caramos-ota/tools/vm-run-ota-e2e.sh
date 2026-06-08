#!/usr/bin/env bash
set -euo pipefail

TEST_RELEASE_FROM="${TEST_RELEASE_FROM:-1.0.1}"
TEST_RELEASE_TARGET="${TEST_RELEASE_TARGET:-1.0.3}"
BACKUP_DIR="/root/caramos-ota-e2e-backup"

usage() {
  cat <<'EOF'
CaramOS OTA VM E2E runner

Usage:
  sudo ./vm-run-ota-e2e.sh install-and-cli
  ./vm-run-ota-e2e.sh notifier
  ./vm-run-ota-e2e.sh verify
  sudo ./vm-run-ota-e2e.sh restore
  sudo ./vm-run-ota-e2e.sh purge

Commands:
  install-shipped  Purge old install and install the shipped .deb
  prepare-check    Fix live APT, reset test version, run --check
  install-and-cli  Install shipped .deb, set test release, dry-run chain, run CLI migration
  notifier         Start caramos-ota-notifier in the current desktop session
  verify           Verify installed commands, release file, and 1.0.2 branding result
  restore          Restore files backed up before install-and-cli
  purge            Purge caramos-ota and remove OTA repo/keyring/state/test leftovers

Environment:
  TEST_RELEASE_FROM=1.0.1
  TEST_RELEASE_TARGET=1.0.3
EOF
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Error: this command must run with sudo/root." >&2
    exit 2
  fi
}

latest_deb() {
  find . -maxdepth 1 -type f -name 'caramos-ota_*.deb' | sort | tail -n 1
}

backup_system() {
  mkdir -p "${BACKUP_DIR}"
  cp -a /etc/caramos-release "${BACKUP_DIR}/caramos-release" 2>/dev/null || true
  cp -a /etc/xdg/autostart/mintWelcome.desktop "${BACKUP_DIR}/mintWelcome.desktop" 2>/dev/null || true
  tar -C / -czf "${BACKUP_DIR}/linuxmint-share-lib.tgz" usr/share/linuxmint usr/lib/linuxmint 2>/dev/null || true
  echo "[OK] Backup saved to ${BACKUP_DIR}"
}

set_test_release() {
  cat > /etc/caramos-release <<EOF
NAME="CaramOS"
VERSION="${TEST_RELEASE_FROM}"
CHANNEL="stable"
UBUNTU_CODENAME="noble"
EOF
  cat > /etc/os-release <<EOF
NAME="CaramOS"
VERSION="${TEST_RELEASE_FROM}"
ID=caramos
ID_LIKE="ubuntu debian linuxmint"
PRETTY_NAME="CaramOS ${TEST_RELEASE_FROM} Cinnamon"
VERSION_ID="${TEST_RELEASE_FROM}"
HOME_URL="https://github.com/VN-Linux-Family/CaramOS"
SUPPORT_URL="https://github.com/VN-Linux-Family/CaramOS/issues"
BUG_REPORT_URL="https://github.com/VN-Linux-Family/CaramOS/issues"
PRIVACY_POLICY_URL="https://github.com/VN-Linux-Family/CaramOS"
VERSION_CODENAME=caram
UBUNTU_CODENAME=noble
CARAMOS_BASE="Linux Mint 22.3"
EOF
  cat > /etc/lsb-release <<EOF
DISTRIB_ID=CaramOS
DISTRIB_RELEASE=${TEST_RELEASE_FROM}
DISTRIB_CODENAME=caram
DISTRIB_DESCRIPTION="CaramOS ${TEST_RELEASE_FROM} Cinnamon"
EOF
  mkdir -p /etc/linuxmint
  cat > /etc/linuxmint/info <<EOF
RELEASE=${TEST_RELEASE_FROM}
CODENAME=caram
EDITION="Cinnamon"
DESCRIPTION="CaramOS ${TEST_RELEASE_FROM} Cinnamon"
DESKTOP=Gnome
TOOLKIT=GTK
NEW_FEATURES_URL=https://caramos.org/
RELEASE_NOTES_URL=https://caramos.org/
USER_GUIDE_URL=https://caramos.org/
GRUB_TITLE=CaramOS ${TEST_RELEASE_FROM} Cinnamon
EOF
  printf 'CaramOS %s \\n \\l\n' "${TEST_RELEASE_FROM}" > /etc/issue
  printf 'CaramOS %s\n' "${TEST_RELEASE_FROM}" > /etc/issue.net
  echo "[OK] Set CaramOS version metadata to ${TEST_RELEASE_FROM}"
}

install_package() {
  local deb
  deb="$(latest_deb)"
  if [[ -z "${deb}" || ! -f "${deb}" ]]; then
    echo "Error: caramos-ota .deb not found in $(pwd)" >&2
    exit 1
  fi
  apt install -y "${deb}"
  echo "[OK] Installed ${deb}"
}

smoke() {
  command -v caramos-ota
  command -v caramos-ota-notifier
  command -v caramos-ota-update
  echo "[OK] OTA commands installed"
}

run_cli_migration() {
  echo "== Dry-run migration ${TEST_RELEASE_FROM} -> ${TEST_RELEASE_TARGET} =="
  caramos-ota-update --from "${TEST_RELEASE_FROM}" --target "${TEST_RELEASE_TARGET}" --dry-run

  echo "== Run CLI migration ${TEST_RELEASE_FROM} -> ${TEST_RELEASE_TARGET} =="
  caramos-ota-update --from "${TEST_RELEASE_FROM}" --target "${TEST_RELEASE_TARGET}"
}

verify() {
  echo "== commands =="
  command -v caramos-ota || true
  command -v caramos-ota-notifier || true
  command -v caramos-ota-update || true

  echo
  echo "== release =="
  cat /etc/caramos-release 2>/dev/null || true

  echo
  echo "== mintWelcome Exec =="
  grep '^Exec=' /etc/xdg/autostart/mintWelcome.desktop 2>/dev/null || true

  echo
  echo "== sample remaining Linux Mint strings =="
  grep -RIn "Linux Mint" /usr/share/linuxmint /usr/lib/linuxmint \
    --include='*.py' \
    --include='*.desktop' \
    --include='*.json' \
    --include='*.xml' \
    --include='*.ui' 2>/dev/null | head -50 || true
}

run_notifier() {
  if ! command -v caramos-ota-notifier >/dev/null 2>&1; then
    echo "Error: caramos-ota-notifier is not installed yet." >&2
    echo "Run: sudo ./vm-run-ota-e2e.sh install-and-cli" >&2
    exit 1
  fi
  echo "Starting notifier. If no GUI appears, run this from the VM desktop terminal."
  caramos-ota-notifier
}

restore() {
  require_root
  if [[ ! -d "${BACKUP_DIR}" ]]; then
    echo "Error: backup directory not found: ${BACKUP_DIR}" >&2
    exit 1
  fi
  cp -a "${BACKUP_DIR}/caramos-release" /etc/caramos-release 2>/dev/null || true
  cp -a "${BACKUP_DIR}/mintWelcome.desktop" /etc/xdg/autostart/mintWelcome.desktop 2>/dev/null || true
  if [[ -f "${BACKUP_DIR}/linuxmint-share-lib.tgz" ]]; then
    tar -C / -xzf "${BACKUP_DIR}/linuxmint-share-lib.tgz"
  fi
  echo "[OK] Restored backup"
}

purge_ota() {
  require_root

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
  echo "[OK] caramos-ota and related OTA files removed"
}

disable_live_cdrom_source() {
  require_root
  if [[ -f /etc/apt/sources.list ]]; then
    sed -i.bak '/^deb cdrom:/ s/^/#/' /etc/apt/sources.list
  fi
  find /etc/apt/sources.list.d -maxdepth 1 -type f 2>/dev/null | while read -r source_file; do
    sed -i.bak '/^deb cdrom:/ s/^/#/' "${source_file}"
  done
  echo "[OK] Disabled live CD-ROM APT sources if present"
}

run_check_and_show_state() {
  require_root
  caramos-ota --check
  echo
  echo "== /var/lib/caramos-ota/state.json =="
  cat /var/lib/caramos-ota/state.json
}

install_shipped() {
  require_root
  purge_ota
  install_package
  smoke
}

prepare_check() {
  require_root
  disable_live_cdrom_source
  set_test_release
  run_check_and_show_state
}

install_and_cli() {
  require_root
  backup_system
  install_package
  smoke
  set_test_release
  run_cli_migration
  verify
}

cmd="${1:-}"
case "${cmd}" in
  install-shipped) install_shipped ;;
  prepare-check) prepare_check ;;
  install-and-cli) install_and_cli ;;
  notifier) run_notifier ;;
  verify) verify ;;
  restore) restore ;;
  purge) purge_ota ;;
  -h|--help|help|"") usage ;;
  *) echo "Unknown command: ${cmd}" >&2; usage; exit 1 ;;
esac

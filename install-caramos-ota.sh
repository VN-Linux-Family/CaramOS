#!/usr/bin/env bash
set -euo pipefail

PPA_URL="https://ppa.launchpadcontent.net/vietnamlinuxfamily/caram-os/ubuntu"
PPA_SUITE="noble"
PPA_COMPONENT="main"
PPA_KEY_FPR="CDAC57D9EB35115D"
KEYRING_DIR="/etc/apt/keyrings"
KEYRING_FILE="${KEYRING_DIR}/caramos-ppa.gpg"
SOURCE_FILE="/etc/apt/sources.list.d/caramos-ppa.list"
RELEASE_FILE="/etc/caramos-release"

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok() { printf '\033[1;32mOK\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mERROR\033[0m %s\n' "$*" >&2; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    fail "Vui lòng chạy bằng sudo: sudo bash $0"
    exit 2
  fi
}

write_release_metadata() {
  info "Sửa metadata nhận diện CaramOS ${CARAMOS_VERSION:-1.0.1}..."
  cat > "${RELEASE_FILE}" <<EOF
NAME=CaramOS
VERSION=${CARAMOS_VERSION:-1.0.1}
VERSION_ID=${CARAMOS_VERSION:-1.0.1}
VERSION_CODENAME=noble
UBUNTU_CODENAME=noble
CHANNEL=stable
ID=caramos
ID_LIKE="linuxmint ubuntu debian"
PRETTY_NAME="CaramOS ${CARAMOS_VERSION:-1.0.1}"
EOF
  ok "Đã ghi ${RELEASE_FILE}"
}

disable_live_cdrom_source() {
  info "Tắt nguồn APT cdrom live ISO nếu có..."
  if [[ -f /etc/apt/sources.list ]]; then
    sed -i.bak '/^deb cdrom:/ s/^/# /' /etc/apt/sources.list
  fi
  if [[ -d /etc/apt/sources.list.d ]]; then
    find /etc/apt/sources.list.d -maxdepth 1 -type f \( -name '*.list' -o -name '*.sources' \) -print0 \
      | while IFS= read -r -d '' source_file; do
          sed -i.bak '/^deb cdrom:/ s/^/# /' "${source_file}"
        done
  fi
  ok "Đã tắt cdrom source nếu tồn tại"
}

install_keyring() {
  info "Cập nhật keyring Launchpad PPA CaramOS..."
  mkdir -p "${KEYRING_DIR}"
  chmod 0755 "${KEYRING_DIR}"

  if command -v gpg >/dev/null 2>&1; then
    local tmp_home
    tmp_home="$(mktemp -d)"
    chmod 0700 "${tmp_home}"
    GNUPGHOME="${tmp_home}" gpg --batch --keyserver keyserver.ubuntu.com --recv-keys "${PPA_KEY_FPR}"
    GNUPGHOME="${tmp_home}" gpg --batch --export "${PPA_KEY_FPR}" > "${KEYRING_FILE}"
    rm -rf "${tmp_home}"
  elif command -v apt-key >/dev/null 2>&1; then
    warn "gpg không có sẵn, fallback sang apt-key deprecated."
    apt-key adv --keyserver keyserver.ubuntu.com --recv-keys "${PPA_KEY_FPR}"
    return 0
  else
    fail "Không tìm thấy gpg hoặc apt-key để import PPA key."
    exit 1
  fi

  chmod 0644 "${KEYRING_FILE}"
  ok "Đã ghi ${KEYRING_FILE}"
}

write_ppa_source() {
  info "Thêm CaramOS PPA source..."
  cat > "${SOURCE_FILE}" <<EOF
deb [signed-by=${KEYRING_FILE}] ${PPA_URL} ${PPA_SUITE} ${PPA_COMPONENT}
EOF
  ok "Đã ghi ${SOURCE_FILE}"
}

install_ota() {
  info "Cập nhật APT và cài caramos-ota..."
  apt-get update
  apt-get install -y caramos-ota
  ok "Đã cài caramos-ota"
}

prepare_update_state() {
  info "Kiểm tra bản cập nhật OTA để chuẩn bị popup..."
  if command -v caramos-ota >/dev/null 2>&1; then
    rm -f /var/lib/caramos-ota/state.json 2>/dev/null || true
    if ! caramos-ota --check; then
      warn "caramos-ota --check lỗi nên KHÔNG mở popup để tránh báo sai 'đã cập nhật'."
      warn "Xem log: ls -t /var/log/caramos-ota/*.log 2>/dev/null | head -1"
      warn "Sau khi sửa apt update, chạy lại: sudo caramos-ota --check && caramos-ota-notifier"
      return 1
    fi
    ok "Đã kiểm tra OTA và ghi state cho notifier"
    return 0
  else
    warn "Không tìm thấy caramos-ota sau khi cài."
    return 1
  fi
}

launch_notifier() {
  info "Mở CaramOS OTA Notifier để user đọc nội dung cập nhật..."
  if command -v caramos-ota-notifier >/dev/null 2>&1; then
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]] && command -v runuser >/dev/null 2>&1; then
      runuser -u "${SUDO_USER}" -- env DISPLAY="${DISPLAY:-:0}" XAUTHORITY="/home/${SUDO_USER}/.Xauthority" caramos-ota-notifier >/dev/null 2>&1 &
    else
      caramos-ota-notifier >/dev/null 2>&1 &
    fi
    ok "Đã gọi caramos-ota-notifier"
  else
    warn "Không tìm thấy caramos-ota-notifier sau khi cài. Chạy thử: sudo caramos-ota --check"
  fi
}

main() {
  require_root
  write_release_metadata
  disable_live_cdrom_source
  install_keyring
  write_ppa_source
  install_ota
  if prepare_update_state; then
    launch_notifier
  fi
  printf '\nHoàn tất. Popup chỉ hiển thị nội dung cập nhật; user tự bấm "Cập nhật ngay" nếu đồng ý.\nNếu popup không hiện, chạy thủ công:\n  sudo apt update\n  sudo caramos-ota --check\n  caramos-ota-notifier\n'
}

main "$@"

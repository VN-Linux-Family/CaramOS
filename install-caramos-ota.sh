#!/usr/bin/env bash
set -euo pipefail

PPA_URL="https://ppa.launchpadcontent.net/vietnamlinuxfamily/caram-os/ubuntu"
PPA_SUITE="noble"
PPA_COMPONENT="main"
PPA_KEY_FPR="CDAC57D9EB35115D"
KEYRING_DIR="/usr/share/keyrings"
KEYRING_FILE="${KEYRING_DIR}/caramos-archive-keyring.gpg"
SOURCE_FILE="/etc/apt/sources.list.d/caramos-ppa.sources"
LEGACY_SOURCE_FILE="/etc/apt/sources.list.d/caramos-ppa.list"
RELEASE_FILE="/etc/caramos-release"
TMP_GNUPG_HOME=""

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok() { printf '\033[1;32mOK\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mWARN\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31mERROR\033[0m %s\n' "$*" >&2; }

cleanup() {
  if [[ -n "${TMP_GNUPG_HOME}" && -d "${TMP_GNUPG_HOME}" ]]; then
    rm -rf "${TMP_GNUPG_HOME}"
  fi
}
trap cleanup EXIT

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    fail "Vui lòng chạy bằng sudo: sudo bash $0"
    exit 2
  fi
  if [[ ! -d /etc/apt/sources.list.d ]]; then
    fail "Không tìm thấy /etc/apt/sources.list.d; hệ thống APT không hợp lệ."
    exit 1
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

cleanup_conflicting_ppa_sources() {
  info "Dọn CaramOS PPA source cũ/trùng nếu có..."
  rm -f "${LEGACY_SOURCE_FILE}"

  if [[ -d /etc/apt/sources.list.d ]]; then
    find /etc/apt/sources.list.d -maxdepth 1 -type f \( -name '*.list' -o -name '*.sources' \) -print0 \
      | while IFS= read -r -d '' source_file; do
          [[ "${source_file}" == "${SOURCE_FILE}" ]] && continue
          if grep -Fq "${PPA_URL}" "${source_file}" 2>/dev/null; then
            mv -f "${source_file}" "${source_file}.disabled-by-caramos-ota"
            warn "Đã tắt source trùng: ${source_file}"
          fi
        done
  fi
  ok "Đã dọn source trùng"
}

install_keyring() {
  info "Cập nhật keyring Launchpad PPA CaramOS..."
  mkdir -p "${KEYRING_DIR}"
  chmod 0755 "${KEYRING_DIR}"

  if [[ -s "${KEYRING_FILE}" ]]; then
    ok "Keyring đã tồn tại: ${KEYRING_FILE}"
    return 0
  fi

  if ! command -v gpg >/dev/null 2>&1; then
    fail "Không tìm thấy gpg để import PPA key. Cài gói gnupg rồi chạy lại."
    exit 1
  fi

  TMP_GNUPG_HOME="$(mktemp -d)"
  chmod 0700 "${TMP_GNUPG_HOME}"
  GNUPGHOME="${TMP_GNUPG_HOME}" gpg --batch --keyserver keyserver.ubuntu.com --recv-keys "${PPA_KEY_FPR}"
  GNUPGHOME="${TMP_GNUPG_HOME}" gpg --batch --export "${PPA_KEY_FPR}" > "${KEYRING_FILE}.tmp"
  chmod 0644 "${KEYRING_FILE}.tmp"
  mv -f "${KEYRING_FILE}.tmp" "${KEYRING_FILE}"
  ok "Đã ghi ${KEYRING_FILE}"
}

write_ppa_source() {
  info "Thêm/cập nhật CaramOS PPA source..."
  cleanup_conflicting_ppa_sources
  if [[ ! -s "${KEYRING_FILE}" ]]; then
    fail "Thiếu keyring ${KEYRING_FILE}; không ghi APT source để tránh repo unsigned."
    exit 1
  fi
  cat > "${SOURCE_FILE}.tmp" <<EOF
Types: deb
URIs: ${PPA_URL}
Suites: ${PPA_SUITE}
Components: ${PPA_COMPONENT}
Signed-By: ${KEYRING_FILE}
EOF
  chmod 0644 "${SOURCE_FILE}.tmp"
  mv -f "${SOURCE_FILE}.tmp" "${SOURCE_FILE}"
  ok "Đã ghi ${SOURCE_FILE}"
}

install_ota() {
  info "Cập nhật APT và cài caramos-ota..."
  apt-get update
  apt-get install -y caramos-ota
  if dpkg -s caramos-ota >/dev/null 2>&1; then
    ok "caramos-ota đã sẵn sàng: $(dpkg-query -W -f='\${Version}' caramos-ota 2>/dev/null || true)"
  else
    fail "Không cài được caramos-ota"
    exit 1
  fi
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
      local user_home user_uid user_env
      user_home="$(getent passwd "${SUDO_USER}" | cut -d: -f6 || true)"
      user_uid="$(id -u "${SUDO_USER}" 2>/dev/null || true)"
      user_env=("HOME=${user_home}" "USER=${SUDO_USER}" "LOGNAME=${SUDO_USER}" "DISPLAY=${DISPLAY:-:0}")
      if [[ -n "${user_uid}" && -S "/run/user/${user_uid}/bus" ]]; then
        user_env+=("DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${user_uid}/bus")
      fi
      if [[ -n "${user_home}" && -f "${user_home}/.Xauthority" ]]; then
        user_env+=("XAUTHORITY=${user_home}/.Xauthority")
      fi
      runuser -u "${SUDO_USER}" -- env "${user_env[@]}" caramos-ota-notifier >/dev/null 2>&1 &
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

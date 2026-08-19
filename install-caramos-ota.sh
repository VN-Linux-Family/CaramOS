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
CARAMOS_VERSION="${CARAMOS_VERSION:-1.0.1}"
TMP_GNUPG_HOME=""

DRY_RUN=false
FORCE=false

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok() { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m⚠\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m✗\033[0m %s\n' "$*" >&2; }

cleanup() {
  # Xóa GPG temp
  if [[ -n "${TMP_GNUPG_HOME}" && -d "${TMP_GNUPG_HOME}" ]]; then
    rm -rf "${TMP_GNUPG_HOME}"
  fi
  # Xóa các file backup không cần thiết
  find /etc/apt -name "*.bak" -type f -delete 2>/dev/null || true
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

check_distro_compatibility() {
  info "Kiểm tra distro compatibility..."
  if [[ -f /etc/os-release ]]; then
    source /etc/os-release
    if [[ "${ID:-}" != "ubuntu" ]] && [[ "${ID:-}" != "linuxmint" ]] && [[ "${ID:-}" != "caramos" ]]; then
      warn "Distro không phải Ubuntu/Mint/CaramOS: ${ID:-unknown}"
      warn "Script có thể không hoạt động đúng"
    fi
    
    if [[ -n "${UBUNTU_CODENAME:-}" ]] && [[ "${UBUNTU_CODENAME}" != "noble" ]]; then
      warn "Distro codename khác noble: ${UBUNTU_CODENAME}"
      warn "Package có thể không tương thích. Đang sử dụng PPA_SUITE=${PPA_SUITE}"
      if [[ "${FORCE}" != "true" ]]; then
        read -r -p "Continue anyway? [y/N] " response
        if [[ ! "$response" =~ ^[Yy]$ ]]; then
          exit 0
        fi
      fi
    fi
  fi
  ok "Distro check passed"
}

write_release_metadata() {
  info "Sửa metadata nhận diện CaramOS ${CARAMOS_VERSION}..."
  if [[ "${DRY_RUN}" == "true" ]]; then
    info "[DRY RUN] Would write ${RELEASE_FILE}"
    return 0
  fi
  
  cat > "${RELEASE_FILE}" <<EOF
NAME=CaramOS
VERSION=${CARAMOS_VERSION}
VERSION_ID=${CARAMOS_VERSION}
VERSION_CODENAME=noble
UBUNTU_CODENAME=noble
CHANNEL=stable
ID=caramos
ID_LIKE="linuxmint ubuntu debian"
PRETTY_NAME="CaramOS ${CARAMOS_VERSION}"
EOF
  ok "Đã ghi ${RELEASE_FILE}"
}

disable_live_cdrom_source() {
  info "Tắt nguồn APT cdrom live ISO nếu có..."
  if [[ "${DRY_RUN}" == "true" ]]; then
    info "[DRY RUN] Would disable cdrom sources"
    return 0
  fi
  
  # Xử lý sources.list
  if [[ -f /etc/apt/sources.list ]]; then
    if grep -q '^deb cdrom:' /etc/apt/sources.list; then
      sed -i '/^deb cdrom:/ s/^/# /' /etc/apt/sources.list
      ok "Đã tắt cdrom trong /etc/apt/sources.list"
    fi
  fi
  
  # Xử lý sources.list.d
  if [[ -d /etc/apt/sources.list.d ]]; then
    find /etc/apt/sources.list.d -maxdepth 1 -type f \( -name '*.list' -o -name '*.sources' \) -print0 \
      | while IFS= read -r -d '' source_file; do
          if grep -q '^deb cdrom:' "${source_file}" 2>/dev/null; then
            sed -i '/^deb cdrom:/ s/^/# /' "${source_file}"
            ok "Đã tắt cdrom trong ${source_file}"
          fi
        done
  fi
}

cleanup_conflicting_ppa_sources() {
  info "Dọn CaramOS PPA source cũ/trùng nếu có..."
  if [[ "${DRY_RUN}" == "true" ]]; then
    info "[DRY RUN] Would cleanup conflicting sources"
    return 0
  fi
  
  # Xóa legacy source
  if [[ -f "${LEGACY_SOURCE_FILE}" ]]; then
    rm -f "${LEGACY_SOURCE_FILE}"
    ok "Đã xóa legacy source: ${LEGACY_SOURCE_FILE}"
  fi
  
  # Tìm và disable các source trùng
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
  
  if [[ "${DRY_RUN}" == "true" ]]; then
    info "[DRY RUN] Would install keyring to ${KEYRING_FILE}"
    return 0
  fi
  
  # Kiểm tra và validate key cũ
  if [[ -s "${KEYRING_FILE}" ]]; then
    if command -v gpg >/dev/null 2>&1; then
      if gpg --show-keys --with-colons "${KEYRING_FILE}" 2>/dev/null | grep -q "fpr:::::::::${PPA_KEY_FPR}:"; then
        ok "Keyring đã tồn tại và hợp lệ: ${KEYRING_FILE}"
        return 0
      else
        warn "Keyring tồn tại nhưng không hợp lệ, tải lại..."
        rm -f "${KEYRING_FILE}"
      fi
    else
      warn "Không có gpg để validate keyring, bỏ qua kiểm tra"
    fi
  fi

  if ! command -v gpg >/dev/null 2>&1; then
    fail "Không tìm thấy gpg để import PPA key. Cài gói gnupg rồi chạy lại."
    exit 1
  fi

  TMP_GNUPG_HOME="$(mktemp -d)"
  chmod 0700 "${TMP_GNUPG_HOME}"
  
  info "Đang tải GPG key ${PPA_KEY_FPR} từ keyserver..."
  if ! GNUPGHOME="${TMP_GNUPG_HOME}" gpg --batch --keyserver keyserver.ubuntu.com --recv-keys "${PPA_KEY_FPR}" 2>/dev/null; then
    warn "Không thể tải key từ keyserver.ubuntu.com, thử keys.openpgp.org..."
    GNUPGHOME="${TMP_GNUPG_HOME}" gpg --batch --keyserver keys.openpgp.org --recv-keys "${PPA_KEY_FPR}" 2>/dev/null || {
      fail "Không thể tải GPG key từ bất kỳ keyserver nào"
      exit 1
    }
  fi
  
  GNUPGHOME="${TMP_GNUPG_HOME}" gpg --batch --export "${PPA_KEY_FPR}" > "${KEYRING_FILE}.tmp"
  chmod 0644 "${KEYRING_FILE}.tmp"
  mv -f "${KEYRING_FILE}.tmp" "${KEYRING_FILE}"
  ok "Đã ghi ${KEYRING_FILE}"
}

write_ppa_source() {
  info "Thêm/cập nhật CaramOS PPA source..."
  cleanup_conflicting_ppa_sources
  
  if [[ "${DRY_RUN}" == "true" ]]; then
    info "[DRY RUN] Would write ${SOURCE_FILE}"
    return 0
  fi
  
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
  if [[ "${DRY_RUN}" == "true" ]]; then
    info "[DRY RUN] Would run: apt update && apt install caramos-ota"
    return 0
  fi
  
  info "Đang cập nhật danh sách gói (có thể mất 1-2 phút)..."
  if ! apt-get update -q 2>&1 | grep -v "Reading package lists"; then
    # Nếu -q lỗi, thử chạy bình thường
    if ! apt-get update; then
      fail "apt update thất bại. Kiểm tra kết nối mạng hoặc PPA source."
      exit 1
    fi
  fi
  
  info "Đang cài caramos-ota..."
  if ! apt-get install -y caramos-ota; then
    fail "Cài caramos-ota thất bại."
    exit 1
  fi
  
  if dpkg -s caramos-ota >/dev/null 2>&1; then
    local version
    version="$(dpkg-query -W -f='${Version}' caramos-ota 2>/dev/null || true)"
    ok "caramos-ota đã sẵn sàng: ${version}"
  else
    fail "Không cài được caramos-ota"
    exit 1
  fi
}

prepare_update_state() {
  info "Kiểm tra bản cập nhật OTA để chuẩn bị popup..."
  if [[ "${DRY_RUN}" == "true" ]]; then
    info "[DRY RUN] Would check for updates"
    return 0
  fi
  
  if ! command -v caramos-ota >/dev/null 2>&1; then
    warn "Không tìm thấy caramos-ota sau khi cài."
    return 1
  fi
  
  # Backup state cũ
  if [[ -f /var/lib/caramos-ota/state.json ]]; then
    cp /var/lib/caramos-ota/state.json /var/lib/caramos-ota/state.json.bak
    ok "Đã backup state.json cũ"
  fi
  
  # Chạy check
  if ! caramos-ota --check; then
    # Restore state cũ nếu check fail
    if [[ -f /var/lib/caramos-ota/state.json.bak ]]; then
      mv /var/lib/caramos-ota/state.json.bak /var/lib/caramos-ota/state.json
      ok "Đã restore state.json cũ"
    fi
    warn "caramos-ota --check lỗi nên KHÔNG mở popup để tránh báo sai 'đã cập nhật'."
    warn "Xem log: ls -t /var/log/caramos-ota/*.log 2>/dev/null | head -1"
    warn "Sau khi sửa apt update, chạy lại: sudo caramos-ota --check && caramos-ota-notifier"
    return 1
  fi
  
  ok "Đã kiểm tra OTA và ghi state cho notifier"
  return 0
}

launch_notifier() {
  info "Mở CaramOS OTA Notifier để user đọc nội dung cập nhật..."
  if [[ "${DRY_RUN}" == "true" ]]; then
    info "[DRY RUN] Would launch caramos-ota-notifier"
    return 0
  fi
  
  if ! command -v caramos-ota-notifier >/dev/null 2>&1; then
    warn "Không tìm thấy caramos-ota-notifier sau khi cài. Chạy thử: sudo caramos-ota --check"
    return 1
  fi
  
  # Kiểm tra DISPLAY
  if [[ -z "${DISPLAY:-}" ]]; then
    warn "Không có DISPLAY, bỏ qua launch notifier"
    return 1
  fi
  
  # Launch as user
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]] && command -v runuser >/dev/null 2>&1; then
    local user_home user_uid
    user_home="$(getent passwd "${SUDO_USER}" | cut -d: -f6 || true)"
    user_uid="$(id -u "${SUDO_USER}" 2>/dev/null || true)"
    
    if [[ -n "${user_home}" && -n "${user_uid}" ]]; then
      local user_env=(
        "HOME=${user_home}"
        "USER=${SUDO_USER}"
        "LOGNAME=${SUDO_USER}"
        "DISPLAY=${DISPLAY:-:0}"
      )
      
      if [[ -S "/run/user/${user_uid}/bus" ]]; then
        user_env+=("DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/${user_uid}/bus")
      fi
      
      if [[ -f "${user_home}/.Xauthority" ]]; then
        user_env+=("XAUTHORITY=${user_home}/.Xauthority")
      fi
      
      runuser -u "${SUDO_USER}" -- env "${user_env[@]}" caramos-ota-notifier >/dev/null 2>&1 &
      ok "Đã gọi caramos-ota-notifier (as ${SUDO_USER})"
    else
      warn "Không thể xác định user home/uid"
    fi
  else
    caramos-ota-notifier >/dev/null 2>&1 &
    ok "Đã gọi caramos-ota-notifier (as root)"
  fi
}

usage() {
  cat <<EOF
Usage: $0 [OPTIONS]

Options:
  --dry-run    Show what would be done without making changes
  --force      Skip confirmation prompts
  --help       Show this help message

Environment variables:
  CARAMOS_VERSION    Set CaramOS version (default: 1.0.1)

Example:
  sudo bash $0
  sudo CARAMOS_VERSION=1.0.2 bash $0 --dry-run
EOF
  exit 0
}

# ============================================
# MAIN
# ============================================
main() {
  # Parse arguments
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run) DRY_RUN=true; shift ;;
      --force) FORCE=true; shift ;;
      --help|help|-h) usage ;;
      *) shift ;;
    esac
  done
  
  info "CaramOS OTA Setup Script v1.0"
  
  if [[ "${DRY_RUN}" == "true" ]]; then
    warn "Running in DRY RUN mode - no changes will be made"
  fi
  
  require_root
  check_distro_compatibility
  write_release_metadata
  disable_live_cdrom_source
  install_keyring
  write_ppa_source
  install_ota
  
  if prepare_update_state; then
    launch_notifier
  fi
  
  echo ""
  echo "Hoàn tất."
  echo "Popup chỉ hiển thị nội dung cập nhật; user tự bấm 'Cập nhật ngay' nếu đồng ý."
  echo ""
  echo "Nếu popup không hiện, chạy thủ công:"
  echo "   sudo apt update"
  echo "   sudo caramos-ota --check"
  echo "   caramos-ota-notifier"
  echo ""
  
  if [[ "${DRY_RUN}" == "true" ]]; then
    warn "DRY RUN complete - no changes were made"
  fi
}

main "$@"

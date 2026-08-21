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
    fail "Please run with sudo: sudo bash $0"
    exit 2
  fi
  if [[ ! -d /etc/apt/sources.list.d ]]; then
    fail "/etc/apt/sources.list.d not found; invalid APT system."
    exit 1
  fi
}

write_release_metadata() {
  info "Updating CaramOS identification metadata ${CARAMOS_VERSION:-1.0.1}..."
  cat > "${RELEASE_FILE}.tmp" <<EOF
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
  chmod 0644 "${RELEASE_FILE}.tmp"
  mv -f "${RELEASE_FILE}.tmp" "${RELEASE_FILE}"
  ok "Written ${RELEASE_FILE}"
}

disable_live_cdrom_source() {
  info "Disabling APT cdrom live ISO source if present..."
  if [[ -f /etc/apt/sources.list ]]; then
    sed -i.bak '/^deb cdrom:/ s/^/# /' /etc/apt/sources.list
  fi
  if [[ -d /etc/apt/sources.list.d ]]; then
    find /etc/apt/sources.list.d -maxdepth 1 -type f \( -name '*.list' -o -name '*.sources' \) -print0 \
      | while IFS= read -r -d '' source_file; do
          sed -i.bak '/^deb cdrom:/ s/^/# /' "${source_file}"
        done
  fi
  ok "Disabled cdrom source if existed"
}

cleanup_conflicting_ppa_sources() {
  info "Cleaning old/duplicate CaramOS PPA sources..."
  rm -f "${LEGACY_SOURCE_FILE}"

  if [[ -d /etc/apt/sources.list.d ]]; then
    find /etc/apt/sources.list.d -maxdepth 1 -type f \( -name '*.list' -o -name '*.sources' \) -print0 \
      | while IFS= read -r -d '' source_file; do
          [[ "${source_file}" == "${SOURCE_FILE}" ]] && continue
          if grep -Fq "${PPA_URL}" "${source_file}" 2>/dev/null; then
            mv -f "${source_file}" "${source_file}.disabled-by-caramos-ota"
            warn "Disabled duplicate source: ${source_file}"
          fi
        done
  fi
  ok "Cleaned duplicate sources"
}

install_keyring() {
  info "Updating CaramOS Launchpad PPA keyring..."
  mkdir -p "${KEYRING_DIR}"
  chmod 0755 "${KEYRING_DIR}"

  if [[ -s "${KEYRING_FILE}" ]]; then
    ok "Keyring already exists: ${KEYRING_FILE}"
    return 0
  fi

  if ! command -v gpg >/dev/null 2>&1; then
    fail "gpg not found to import PPA key. Install gnupg package and retry."
    exit 1
  fi

  TMP_GNUPG_HOME="$(mktemp -d)"
  chmod 0700 "${TMP_GNUPG_HOME}"
  
  # Use hkps:// for secure keyserver communication
  if ! GNUPGHOME="${TMP_GNUPG_HOME}" gpg --batch --keyserver hkps://keyserver.ubuntu.com --recv-keys "${PPA_KEY_FPR}"; then
    # Fallback to http if hkps fails (some networks block hkps)
    warn "hkps:// keyserver failed, trying http:// keyserver..."
    GNUPGHOME="${TMP_GNUPG_HOME}" gpg --batch --keyserver http://keyserver.ubuntu.com --recv-keys "${PPA_KEY_FPR}"
  fi
  
  GNUPGHOME="${TMP_GNUPG_HOME}" gpg --batch --export "${PPA_KEY_FPR}" > "${KEYRING_FILE}.tmp"
  chmod 0644 "${KEYRING_FILE}.tmp"
  mv -f "${KEYRING_FILE}.tmp" "${KEYRING_FILE}"
  ok "Written ${KEYRING_FILE}"
}

write_ppa_source() {
  info "Adding/updating CaramOS PPA source..."
  cleanup_conflicting_ppa_sources
  if [[ ! -s "${KEYRING_FILE}" ]]; then
    fail "Missing keyring ${KEYRING_FILE}; not writing APT source to avoid unsigned repo."
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
  ok "Written ${SOURCE_FILE}"
}

install_ota() {
  info "Updating APT and installing caramos-ota..."
  if ! apt-get update; then
    fail "apt-get update failed. Check network and PPA configuration."
    exit 1
  fi
  
  if ! apt-get install -y caramos-ota; then
    fail "Failed to install caramos-ota"
    exit 1
  fi
  
  if dpkg -s caramos-ota >/dev/null 2>&1; then
    ok "caramos-ota ready: $(dpkg-query -W -f='\${Version}' caramos-ota 2>/dev/null || true)"
  else
    fail "Failed to install caramos-ota"
    exit 1
  fi
}

prepare_update_state() {
  info "Checking OTA update to prepare popup..."
  if command -v caramos-ota >/dev/null 2>&1; then
    rm -f /var/lib/caramos-ota/state.json 2>/dev/null || true
    if ! caramos-ota --check; then
      warn "caramos-ota --check failed; NOT opening popup to avoid false 'updated' notification."
      warn "Check log: ls -t /var/log/caramos-ota/*.log 2>/dev/null | head -1"
      warn "After fixing apt update, run: sudo caramos-ota --check && caramos-ota-notifier"
      return 1
    fi
    ok "OTA checked and state written for notifier"
    return 0
  else
    warn "caramos-ota not found after installation."
    return 1
  fi
}

launch_notifier() {
  info "Opening CaramOS OTA Notifier for user to read update content..."
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
      # Use nohup to detach from script
      nohup runuser -u "${SUDO_USER}" -- env "${user_env[@]}" caramos-ota-notifier >/dev/null 2>&1 &
    else
      nohup caramos-ota-notifier >/dev/null 2>&1 &
    fi
    ok "Launched caramos-ota-notifier"
  else
    warn "caramos-ota-notifier not found after installation. Try: sudo caramos-ota --check"
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
  printf '\nComplete. Popup only displays update content; user clicks "Update now" if they agree.\nIf popup does not appear, run manually:\n  sudo apt update\n  sudo caramos-ota --check\n  caramos-ota-notifier\n'
}

main "$@"

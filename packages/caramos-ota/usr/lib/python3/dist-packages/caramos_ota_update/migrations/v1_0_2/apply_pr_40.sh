#!/usr/bin/env bash
set -euo pipefail

log() {
  echo "[caramos-ota 1.0.2] $*"
}

DRY_RUN="${CARAMOS_OTA_DRY_RUN:-0}"

run_or_print() {
  if [[ "${DRY_RUN}" == "1" ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi
  "$@"
}

write_file() {
  local path="$1"
  local content="$2"
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "[dry-run] write file: ${path}"
    return 0
  fi
  printf '%s' "${content}" > "${path}"
}

# --- Mint welcome screen & system tray ---
log "Tắt Mint welcome screen..."
if [[ -f /etc/xdg/autostart/mintWelcome.desktop ]]; then
  if grep -q '^Exec=' /etc/xdg/autostart/mintWelcome.desktop; then
    run_or_print sed -i 's/^Exec=.*/Exec=mintwelcome/' /etc/xdg/autostart/mintWelcome.desktop
  else
    if [[ "${DRY_RUN}" == "1" ]]; then
      log "[dry-run] append Exec=mintwelcome to /etc/xdg/autostart/mintWelcome.desktop"
    else
      printf '\nExec=mintwelcome\n' >> /etc/xdg/autostart/mintWelcome.desktop
    fi
  fi
  log "[OK] mintWelcome disabled"
else
  log "Skip missing /etc/xdg/autostart/mintWelcome.desktop"
fi

# --- Mint System branding files ---
log "Đổi remaining branding files..."
if [[ -d /usr/share/linuxmint ]]; then
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "[dry-run] replace Linux Mint -> CaramOS under /usr/share/linuxmint"
  else
    find /usr/share/linuxmint -type f \( -name "*.py" -o -name "*.desktop" -o -name "*.json" -o -name "*.xml" -o -name "*.ui" \) \
      -exec sed -i 's/Linux Mint/CaramOS/gI' {} + 2>/dev/null || true
  fi
  log "[OK] /usr/share/linuxmint/"
else
  log "Skip missing /usr/share/linuxmint"
fi

if [[ -d /usr/lib/linuxmint ]]; then
  if [[ "${DRY_RUN}" == "1" ]]; then
    log "[dry-run] replace Linux Mint -> CaramOS under /usr/lib/linuxmint"
  else
    find /usr/lib/linuxmint -type f -name "*.py" -exec \
      sed -i 's/Linux Mint/CaramOS/gI' {} + 2>/dev/null || true
  fi
  log "[OK] /usr/lib/linuxmint/"
else
  log "Skip missing /usr/lib/linuxmint"
fi

# Đổi string chứa "Linux Mint" trong mintwelcome
if command -v msgunfmt >/dev/null 2>&1 && command -v msgfmt >/dev/null 2>&1; then
  if [[ -d /usr/share/linuxmint/locale ]]; then
    while IFS= read -r -d '' mo; do
      log "Patch translation: ${mo}"
      if [[ "${DRY_RUN}" == "1" ]]; then
        continue
      fi
      po="$(mktemp --suffix=.po)"
      msgunfmt "${mo}" > "${po}"
      sed -i 's/Linux Mint/CaramOS/gI' "${po}"
      msgfmt "${po}" -o "${mo}"
      rm -f "${po}"
    done < <(find /usr/share/linuxmint/locale -name "mintwelcome.mo" -print0)
  else
    log "Skip missing /usr/share/linuxmint/locale"
  fi
else
  log "Skip mintwelcome translation rebuild: msgunfmt/msgfmt not available"
fi

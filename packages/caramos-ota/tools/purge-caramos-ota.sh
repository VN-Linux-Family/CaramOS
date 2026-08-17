#!/usr/bin/env bash
set -euo pipefail


  echo "Error: run with sudo/root." >&2
  exit 2
fi


log() {
    echo "== $* =="
}

log_error() {
    echo "ERROR: $*" >&2
}

log_warn() {
    echo "WARN: $*" >&2
}


confirm() {
    local prompt="${1:-Continue?}"
    local default="${2:-n}"
    
    if [[ "${FORCE:-}" = "1" ]]; then
        return 0
    fi
    
    local response
    read -r -p "$prompt [y/N] " response
    case "$response" in
        [yY][eE][sS]|[yY]) 
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}


log "Stopping OTA services"

# Disable timer
if systemctl list-unit-files | grep -q caramos-ota-check.timer; then
    systemctl disable --now caramos-ota-check.timer 2>/dev/null || {
        log_warn "Failed to disable timer (may already be disabled)"
    }
else
    log "Timer not found, skipping"
fi

# Stop service
if systemctl list-unit-files | grep -q caramos-ota-check.service; then
    systemctl stop caramos-ota-check.service 2>/dev/null || {
        log_warn "Failed to stop service (may already be stopped)"
    }
else
    log "Service not found, skipping"
fi

# Kill notifier process (an toàn hơn)
log "Stopping notifier processes..."
if command -v pkill >/dev/null 2>&1; then
    pkill -x caramos-ota-notifier 2>/dev/null || true
    pkill -f "caramos-ota-notifier" 2>/dev/null || true  # fallback
elif command -v killall >/dev/null 2>&1; then
    killall caramos-ota-notifier 2>/dev/null || true
fi

# Kiểm tra process còn chạy
sleep 1
if pgrep -f caramos-ota-notifier >/dev/null 2>&1; then
    log_warn "Some OTA processes still running:"
    pgrep -f caramos-ota-notifier | xargs ps -p 2>/dev/null || true
    if confirm "Force kill remaining processes?"; then
        pkill -9 -f caramos-ota-notifier 2>/dev/null || true
    fi
fi

log "Purging caramos-ota package"

PACKAGE_INSTALLED=false
if dpkg-query -W -f='${Status}' caramos-ota 2>/dev/null | grep -q "install ok installed"; then
    PACKAGE_INSTALLED=true
    log "Package is installed, purging..."
    
    # Dùng apt purge với --dry-run để xem trước
    if [[ "${DRY_RUN:-}" != "1" ]]; then
        if ! apt purge -y caramos-ota; then
            log_error "Failed to purge package"
            log_warn "Trying dpkg --purge instead..."
            dpkg --purge caramos-ota 2>/dev/null || {
                log_error "Could not purge package. Please remove manually."
                exit 1
            }
        fi
    else
        log "DRY RUN: Would purge caramos-ota"
    fi
else
    log "Package is not installed"
fi

# Autoremove
log "Cleaning up dependencies..."
apt autoremove -y 2>/dev/null || true
apt autoclean -y 2>/dev/null || true

log "Removing OTA files"

# Files và directories cần xóa
FILES_TO_REMOVE=(
    "/etc/apt/sources.list.d/caramos-ppa.sources"
    "/usr/share/keyrings/caramos-archive-keyring.gpg"
    "/etc/xdg/autostart/caramos-ota-notifier.desktop"
    "/etc/logrotate.d/caramos-ota"
    "/usr/share/polkit-1/actions/net.vietnamlinuxfamily.caramos-ota.policy"
    "/lib/systemd/system/caramos-ota-check.service"
    "/lib/systemd/system/caramos-ota-check.timer"
    "/usr/bin/caramos-ota"
    "/usr/bin/caramos-ota-notifier"
    "/usr/bin/caramos-ota-update"
)

DIRS_TO_REMOVE=(
    "/usr/lib/python3/dist-packages/caramos_ota"
    "/usr/lib/python3/dist-packages/caramos_ota_notifier"
    "/usr/lib/python3/dist-packages/caramos_ota_update"
    "/usr/share/caramos-ota"
    "/var/lib/caramos-ota"
    "/var/log/caramos-ota"
    "/etc/caramos-ota"  # Thêm nếu có
    "/var/cache/caramos-ota"  # Cache nếu có
)

# Xóa files
for file in "${FILES_TO_REMOVE[@]}"; do
    if [[ -f "$file" ]]; then
        rm -f "$file"
        log "Removed file: $file"
    elif [[ -L "$file" ]]; then  # Kiểm tra symlink
        rm -f "$file"
        log "Removed symlink: $file"
    fi
done

# Xóa directories
for dir in "${DIRS_TO_REMOVE[@]}"; do
    if [[ -d "$dir" ]]; then
        # Kiểm tra xem có file nào không (trừ khi đã confirm)
        if [[ -n "$(ls -A "$dir" 2>/dev/null)" ]]; then
            log_warn "Directory $dir is not empty"
            if confirm "Delete directory $dir and its contents?"; then
                rm -rf "$dir"
                log "Removed directory: $dir"
            else
                log "Skipped: $dir"
            fi
        else
            rmdir "$dir" 2>/dev/null || rm -rf "$dir"
            log "Removed empty directory: $dir"
        fi
    fi
done

log "Removing user configurations..."

# Tìm tất cả user home directories
for home_dir in /home/* /root; do
    if [[ -d "$home_dir" ]]; then
        user_configs=(
            "$home_dir/.config/caramos-ota"
            "$home_dir/.local/share/caramos-ota"
            "$home_dir/.cache/caramos-ota"
        )
        
        for config in "${user_configs[@]}"; do
            if [[ -d "$config" ]]; then
                log "Removing user config: $config"
                rm -rf "$config" 2>/dev/null || true
            fi
        done
    fi
done

log "Reloading systemd"
systemctl daemon-reload 2>/dev/null || {
    log_warn "Failed to reload systemd"
}
systemctl reset-failed 2>/dev/null || true

log "Updating APT cache (optional)"
if confirm "Update APT cache now?"; then
    apt update -qq 2>/dev/null || {
        log_warn "APT update failed (may be due to removed repository)"
    }
else
    log "Skipping APT update (run 'apt update' manually later)"
fi

log "Verification"

VERIFICATION_ERRORS=0

# Kiểm tra package
if dpkg-query -W -f='${Status}' caramos-ota 2>/dev/null | grep -q "install ok installed"; then
    log_error "Package still installed!"
    VERIFICATION_ERRORS=$((VERIFICATION_ERRORS + 1))
else
    log "✅ Package not installed"
fi

# Kiểm tra binary files
for bin in caramos-ota caramos-ota-notifier caramos-ota-update; do
    if command -v "$bin" >/dev/null 2>&1; then
        log_warn "$bin still in PATH"
        VERIFICATION_ERRORS=$((VERIFICATION_ERRORS + 1))
    else
        log "✅ $bin not found in PATH"
    fi
done

# Kiểm tra systemd service
for unit in caramos-ota-check.service caramos-ota-check.timer; do
    if systemctl list-unit-files | grep -q "$unit"; then
        log_warn "$unit still exists"
        VERIFICATION_ERRORS=$((VERIFICATION_ERRORS + 1))
    else
        log "✅ $unit removed"
    fi
done

# Kiểm tra process còn chạy
if pgrep -f caramos-ota >/dev/null 2>&1; then
    log_warn "OTA processes still running:"
    pgrep -f caramos-ota | xargs ps -p 2>/dev/null || true
    VERIFICATION_ERRORS=$((VERIFICATION_ERRORS + 1))
else
    log "✅ No OTA processes running"
fi

echo ""
echo "=========================================="
if [[ $VERIFICATION_ERRORS -eq 0 ]]; then
    echo "✅ caramos-ota cleanup complete successfully"
else
    echo "⚠️ caramos-ota cleanup completed with $VERIFICATION_ERRORS warnings"
    echo "Please review the warnings above."
fi
echo "=========================================="

# Exit code
if [[ $VERIFICATION_ERRORS -eq 0 ]]; then
    exit 0
else
    exit 1
fi

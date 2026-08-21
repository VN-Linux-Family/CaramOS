#!/bin/bash
# ============================================================
# CaramOS Build Script
# Remaster from Linux Mint ISO to CaramOS ISO
#
# Usage:
#   sudo ./build.sh                          # Dev build (zstd, fast)
#   sudo ./build.sh --release                 # Release build (zstd, balanced)
#   sudo ./build.sh /path/to/mint.iso         # Use existing ISO
#   sudo ./build.sh --clean                   # Clean old build
#   sudo ./build.sh --quick                   # Overlay + quick repack
#   sudo ./build.sh --shell                   # Enter chroot to test/fix
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/scripts/config.sh"
source "$SCRIPT_DIR/scripts/utils.sh"
source "$SCRIPT_DIR/scripts/extract.sh"
source "$SCRIPT_DIR/scripts/boot_config.sh"
source "$SCRIPT_DIR/scripts/overlay.sh"
source "$SCRIPT_DIR/scripts/customize.sh"
source "$SCRIPT_DIR/scripts/ota_bootstrap.sh"
source "$SCRIPT_DIR/scripts/chroot_shell.sh"
source "$SCRIPT_DIR/scripts/repack.sh"

MODE="full"
ISO_ARG=""
CLEAN_OUTPUT=false
DEBUG_BOOT=0

check_disk_space() {
    local required_space=10000000
    local paths_to_check=("$WORK_DIR" "$SCRIPT_DIR")
    
    for check_path in "${paths_to_check[@]}"; do
        if [ ! -d "$check_path" ]; then
            warn "Directory does not exist: $check_path, skipping disk space check"
            continue
        fi
        
        local available_space=$(df "$check_path" 2>/dev/null | awk 'NR==2 {print $4}')
        
        if [ -z "$available_space" ]; then
            warn "Cannot determine available disk space for $check_path"
            continue
        fi
        
        if [ "$available_space" -lt "$required_space" ]; then
            local available_gb=$((available_space/1024/1024))
            local required_gb=$((required_space/1024/1024))
            error "Insufficient disk space in $check_path. Need at least ${required_gb}GB, currently have ${available_gb}GB"
            exit 1
        fi
        
        info "Disk space OK for $check_path: $((available_space/1024/1024))GB available"
    done
}

ensure_zstd() {
    if ! command -v zstd >/dev/null 2>&1; then
        info "zstd not found, installing..."
        apt-get update -qq
        apt-get install -y zstd
        ok "zstd installed"
    else
        info "zstd found: $(zstd --version 2>&1 | head -1)"
    fi
}

for arg in "$@"; do
    case "$arg" in
        --release)
            SQUASHFS_COMP="zstd"
            SQUASHFS_OPTS="-b 1M -Xcompression-level 19 -noappend"
            info "Release mode: zstd compression level 19 (balanced, smaller ISO)"
            ;;
        --debug-boot)
            DEBUG_BOOT=1
            info "Debug boot: show kernel log, disable quiet/splash"
            ;;
        --help|-h)
            MODE="help"
            ;;
        --prepare|--boot-only|--overlay-only|--customize-only|--shell|--repack-only|--iso-only|--quick|--clean|--clean-work|--clean-cache)
            MODE="${arg#--}"
            ;;
        *)
            ISO_ARG="$arg"
            ;;
    esac
done

case "$MODE" in
    help)
        print_dev_help
        exit 0
        ;;
    clean)
        info "Cleaning build..."
        safe_remove_work_dirs
        rm -rf "$WORK_DIR/cache" "$WORK_DIR/cache_iso" CaramOS-*.iso ./*.log
        ok "Cleanup complete. (Mint ISO preserved)"
        exit 0
        ;;
    clean-work)
        info "Cleaning work tree (preserving cache)..."
        safe_remove_work_dirs
        ok "Work tree removed, cache preserved."
        exit 0
        ;;
    clean-cache)
        info "Cleaning all build cache/work tree..."
        safe_remove_work_dirs
        rm -rf "$WORK_DIR/cache" "$WORK_DIR/cache_iso"
        ok "Cache/work tree removed."
        exit 0
        ;;
esac

if [ -n "$ISO_ARG" ] && [ ! -f "$ISO_ARG" ]; then
    error "ISO file does not exist: $ISO_ARG"
    exit 1
fi

check_root
install_deps
install_gum
ensure_zstd
check_disk_space

cleanup_on_fail() {
    [ "${BUILD_OK:-0}" = "1" ] && return 0
    echo ""
    echo -e "\033[0;31m[ERROR ]\033[0m Build failed! Cleaning up mounts safely..."
    
    umount "$WORK_DIR/squashfs/dev/pts" 2>/dev/null || true
    umount "$WORK_DIR/squashfs/dev" 2>/dev/null || true
    umount "$WORK_DIR/squashfs/proc" 2>/dev/null || true
    umount "$WORK_DIR/squashfs/sys" 2>/dev/null || true
    umount "$WORK_DIR/squashfs" 2>/dev/null || true
    umount "$WORK_DIR/mnt" 2>/dev/null || true

    if [ "$CLEAN_OUTPUT" = true ]; then
        safe_remove_work_dirs || true
    else
        echo -e "\033[1;33m[ WARN ]\033[0m Preserving build directories for inspection/repair."
    fi
}
trap cleanup_on_fail EXIT INT TERM

resolve_iso "$ISO_ARG"

validate_customized_rootfs() {
    [ -d "$WORK_DIR/squashfs" ] || return 1
    [ -f "$WORK_DIR/squashfs/etc/caramos-customized" ] || return 1

    chroot "$WORK_DIR/squashfs" /bin/bash -c "test -f /etc/dconf/db/local && test -f /etc/xdg/autostart/caramos-theme.desktop && test -f /etc/xdg/autostart/plank.desktop && test -d /etc/skel/.config/plank/dock1 && test -d /usr/share/cinnamon/applets/Cinnamenu@json && find /usr/share/cinnamon/applets/Cinnamenu@json -name settings-schema.json -print -quit | grep -q . && test -f /usr/share/plymouth/themes/caramos/caramos.plymouth"
}

print_header

case "$MODE" in
    full)
        CLEAN_OUTPUT=true
        step_extract
        step_boot_config
        step_customize
        step_repack_and_clean
        ;;
    prepare)
        step_extract
        ;;
    boot-only)
        ensure_work_tree
        step_boot_config
        ;;
    overlay-only)
        ensure_work_tree
        step_overlay
        ;;
    customize-only)
        ensure_work_tree
        step_customize
        ;;
    shell)
        step_chroot_shell
        ;;
    repack-only)
        ensure_work_tree
        step_repack
        ;;
    iso-only)
        ensure_work_tree
        step_repack_iso
        ;;
    quick)
        ensure_work_tree
        step_boot_config
        if ! validate_customized_rootfs; then
            warn "Work tree not fully customized or marker is invalid. Running customize before repack."
            rm -f "$WORK_DIR/squashfs/etc/caramos-customized" 2>/dev/null || true
            step_customize
        else
            step_overlay
        fi
        step_repack
        ;;
    *)
        error "Unsupported mode: $MODE. Run sudo ./build.sh --help for instructions."
        ;;
esac

BUILD_OK=1

case "$MODE" in
    shell|prepare|boot-only|overlay-only|customize-only)
        ok "Completed mode: $MODE"
        ;;
    *)
        print_result
        ;;
esac

#!/bin/bash
# Steps 1-3: Extract ISO + filesystem (with cache)

step_extract() {
    info "[1/7] Preparing build directory..."
    sync 2>/dev/null || true
    umount "$WORK_DIR/squashfs/proc"    2>/dev/null || true
    umount "$WORK_DIR/squashfs/sys"     2>/dev/null || true
    umount "$WORK_DIR/squashfs/dev/pts" 2>/dev/null || true
    umount "$WORK_DIR/squashfs/dev"     2>/dev/null || true
    umount "$WORK_DIR/mnt"              2>/dev/null || true
    rm -rf "$WORK_DIR/squashfs" "$WORK_DIR/custom"
    mkdir -p "$WORK_DIR"/{mnt,custom}

    CACHE_DIR="$WORK_DIR/cache"
    CACHE_ISO_DIR="$WORK_DIR/cache_iso"
    CACHE_VALID=false

    # Validate cache
    if [ -d "$CACHE_DIR" ] && [ -d "$CACHE_ISO_DIR" ] &&
       [ -f "$CACHE_DIR/etc/os-release" ] &&
       [ -f "$CACHE_ISO_DIR/casper/filesystem.squashfs" ] &&
       [ -d "$CACHE_ISO_DIR/isolinux" -o -d "$CACHE_ISO_DIR/boot/grub" ]; then
        CACHE_VALID=true
    fi

    if $CACHE_VALID; then
        info "[2/7] Using cache (skip ISO extract)..."
        ok "Cache found and validated."
    else
        info "[2/7] Extracting ISO (first time, will cache)..."
        
        # Clean old cache if exists but invalid
        rm -rf "$CACHE_DIR" "$CACHE_ISO_DIR"
        mkdir -p "$CACHE_DIR"
        
        mount -o loop,ro "$MINT_ISO" "$WORK_DIR/mnt"
        rsync -a --exclude='casper/filesystem.squashfs' "$WORK_DIR/mnt/" "$WORK_DIR/custom/"
        ok "ISO extraction complete."

        info "[3/7] Extracting filesystem.squashfs (3-5 min, first time only)..."
        if ! unsquashfs -d "$CACHE_DIR" "$WORK_DIR/mnt/casper/filesystem.squashfs"; then
            error "unsquashfs failed. Check disk space and ISO integrity."
            umount "$WORK_DIR/mnt"
            exit 1
        fi
        umount "$WORK_DIR/mnt"

        # Save ISO content separately for cache
        cp -a "$WORK_DIR/custom/." "$CACHE_ISO_DIR/"
        ok "Extraction + cache complete."
    fi

    info "  → Copying from cache..."
    cp -a "$CACHE_DIR" "$WORK_DIR/squashfs"
    cp -a "$CACHE_ISO_DIR/." "$WORK_DIR/custom/"
    ok "Ready for customization."
}

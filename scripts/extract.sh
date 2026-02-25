#!/bin/bash
# Bước 1-3: Extract ISO + filesystem (có cache)

step_extract() {
    info "[1/7] Chuẩn bị thư mục build..."
    # Dọn mount cũ nếu build trước bị lỗi
    sync 2>/dev/null || true
    umount "$WORK_DIR/squashfs/proc"    2>/dev/null || true
    umount "$WORK_DIR/squashfs/sys"     2>/dev/null || true
    umount "$WORK_DIR/squashfs/dev/pts" 2>/dev/null || true
    umount "$WORK_DIR/squashfs/dev"     2>/dev/null || true
    umount "$WORK_DIR/mnt"              2>/dev/null || true
    rm -rf "$WORK_DIR/squashfs" "$WORK_DIR/custom"
    mkdir -p "$WORK_DIR"/{mnt,custom}

    # --- Cache: giữ bản extract gốc, chỉ extract 1 lần ---
    CACHE_DIR="$WORK_DIR/cache"
    if [ -d "$CACHE_DIR" ]; then
        info "[2/7] Dùng cache (skip extract ISO)..."
        ok "Cache found."
    else
        info "[2/7] Extract ISO (lần đầu, sau này dùng cache)..."
        mount -o loop,ro "$MINT_ISO" "$WORK_DIR/mnt"
        rsync -a --exclude='casper/filesystem.squashfs' "$WORK_DIR/mnt/" "$WORK_DIR/custom/"
        ok "Extract ISO xong."

        info "[3/7] Extract filesystem.squashfs (3-5 phút, chỉ lần đầu)..."
        unsquashfs -d "$CACHE_DIR" "$WORK_DIR/mnt/casper/filesystem.squashfs"
        umount "$WORK_DIR/mnt"

        # Lưu bản ISO content riêng cho cache
        cp -a "$WORK_DIR/custom" "$WORK_DIR/cache_iso"
        ok "Extract + cache xong."
    fi

    # Copy từ cache ra bản làm việc
    info "  → Copy từ cache..."
    cp -a "$CACHE_DIR" "$WORK_DIR/squashfs"
    if [ -d "$WORK_DIR/cache_iso" ]; then
        cp -a "$WORK_DIR/cache_iso/." "$WORK_DIR/custom/"
    fi
    ok "Sẵn sàng tuỳ biến."
}

#!/bin/bash
# Bước 1-3: Extract ISO + filesystem

step_extract() {
    info "[1/7] Chuẩn bị thư mục build..."
    # Dọn mount cũ nếu build trước bị lỗi
    umount -lf "$WORK_DIR/squashfs/proc"    2>/dev/null || true
    umount -lf "$WORK_DIR/squashfs/sys"     2>/dev/null || true
    umount -lf "$WORK_DIR/squashfs/dev/pts" 2>/dev/null || true
    umount -lf "$WORK_DIR/squashfs/dev"     2>/dev/null || true
    umount -lf "$WORK_DIR/mnt"              2>/dev/null || true
    rm -rf "$WORK_DIR"
    mkdir -p "$WORK_DIR"/{mnt,custom}

    info "[2/7] Extract ISO..."
    mount -o loop,ro "$MINT_ISO" "$WORK_DIR/mnt"
    rsync -a --exclude='casper/filesystem.squashfs' "$WORK_DIR/mnt/" "$WORK_DIR/custom/"
    ok "Extract ISO xong."

    info "[3/7] Extract filesystem.squashfs (3-5 phút)..."
    unsquashfs -d "$WORK_DIR/squashfs" "$WORK_DIR/mnt/casper/filesystem.squashfs"
    umount "$WORK_DIR/mnt"
    ok "Extract filesystem xong."
}

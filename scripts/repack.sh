#!/bin/bash
# Step 7: Pack squashfs + ISO

clean_virtual_dirs() {
    local SFS="$WORK_DIR/squashfs"

    rm -rf "$SFS/tmp"/* "$SFS/var/tmp"/* 2>/dev/null || true

    for dir in proc sys dev run; do
        if [ -d "$SFS/$dir" ]; then
            find "$SFS/$dir" -mindepth 1 -delete 2>/dev/null || true
        else
            mkdir -p "$SFS/$dir"
        fi
    done
}

step_repack_squashfs() {
    ensure_work_tree
    umount_chroot
    clean_virtual_dirs

    info "  → Creating filesystem.squashfs (${SQUASHFS_COMP})..."
    mksquashfs "$WORK_DIR/squashfs" "$WORK_DIR/custom/casper/filesystem.squashfs" \
        -comp $SQUASHFS_COMP $SQUASHFS_OPTS
    ok "squashfs complete."

    printf '%s' "$(du -sx --block-size=1 "$WORK_DIR/squashfs" | cut -f1)" \
        > "$WORK_DIR/custom/casper/filesystem.size"

    local latest_initrd
    latest_initrd=$(ls -1t "$WORK_DIR"/squashfs/boot/initrd.img-* 2>/dev/null | head -1 || true)
    if [ -n "$latest_initrd" ] && [ -f "$latest_initrd" ]; then
        cp "$latest_initrd" "$WORK_DIR/custom/casper/initrd.lz"
        ok "Live initrd updated: $(basename "$latest_initrd") → casper/initrd.lz"
    else
        warn "No initrd.img-* found in rootfs to update casper/initrd.lz"
    fi
}

step_repack_iso() {
    ensure_work_tree

    cd "$WORK_DIR/custom"
    find . -type f ! -name 'md5sum.txt' -print0 | xargs -0 md5sum > md5sum.txt 2>/dev/null || true

    info "  → Creating ISO..."

    XORRISO_ARGS=(
        -as mkisofs
        -iso-level 3
        -full-iso9660-filenames
        -volid "CaramOS"
    )

    if [ -f "isolinux/isolinux.bin" ]; then
        info "    Boot: isolinux (BIOS)"
        XORRISO_ARGS+=(
            -b isolinux/isolinux.bin
            -c isolinux/boot.cat
            -no-emul-boot -boot-load-size 4 -boot-info-table
        )
    elif [ -f "boot/grub/bios.img" ]; then
        info "    Boot: GRUB (BIOS)"
        XORRISO_ARGS+=(
            -eltorito-boot boot/grub/bios.img
            -no-emul-boot -boot-load-size 4 -boot-info-table
            --grub2-boot-info --grub2-mbr /usr/lib/grub/i386-pc/boot_hybrid.img
        )
    fi

    if [ -f "EFI/boot/efiboot.img" ]; then
        info "    Boot: EFI"
        XORRISO_ARGS+=(
            -eltorito-alt-boot
            -e EFI/boot/efiboot.img
            -no-emul-boot
            -append_partition 2 0xef EFI/boot/efiboot.img
        )
    elif [ -f "boot/grub/efi.img" ]; then
        info "    Boot: GRUB EFI"
        XORRISO_ARGS+=(
            -eltorito-alt-boot
            -e boot/grub/efi.img
            -no-emul-boot
            -append_partition 2 0xef boot/grub/efi.img
        )
    fi

    if [ -f "isolinux/isolinux.bin" ] && [ -f /usr/lib/ISOLINUX/isohdpfx.bin ]; then
        XORRISO_ARGS+=(-isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin)
    fi

    XORRISO_ARGS+=(-output "$SCRIPT_DIR/$OUTPUT_ISO" .)

    xorriso "${XORRISO_ARGS[@]}"

    cd "$SCRIPT_DIR"
}

step_repack() {
    info "[7/7] Packing ISO..."
    step_repack_squashfs
    step_repack_iso
}

step_repack_and_clean() {
    step_repack
    safe_remove_work_dirs
}

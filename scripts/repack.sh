#!/bin/bash
# Bước 7: Đóng gói squashfs + ISO

step_repack() {
    info "[7/7] Đóng gói ISO..."

    # Rebuild squashfs
    info "  → Tạo filesystem.squashfs (${SQUASHFS_COMP})..."
    mksquashfs "$WORK_DIR/squashfs" "$WORK_DIR/custom/casper/filesystem.squashfs" \
        -comp $SQUASHFS_COMP $SQUASHFS_OPTS
    ok "squashfs xong."

    # Cập nhật filesystem.size
    printf '%s' "$(du -sx --block-size=1 "$WORK_DIR/squashfs" | cut -f1)" \
        > "$WORK_DIR/custom/casper/filesystem.size"

    # Cập nhật md5sum
    cd "$WORK_DIR/custom"
    find . -type f ! -name 'md5sum.txt' -print0 | xargs -0 md5sum > md5sum.txt 2>/dev/null || true

    # Tạo ISO — detect boot structure từ ISO Mint
    info "  → Tạo ISO..."

    XORRISO_ARGS=(
        -as mkisofs
        -iso-level 3
        -full-iso9660-filenames
        -volid "CaramOS"
    )

    # BIOS boot: isolinux (Mint) hoặc GRUB
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

    # UEFI boot
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

    # Isohybrid (cho ghi USB)
    if [ -f "isolinux/isolinux.bin" ]; then
        XORRISO_ARGS+=(-isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin)
    fi

    XORRISO_ARGS+=(-output "$SCRIPT_DIR/$OUTPUT_ISO" .)

    xorriso "${XORRISO_ARGS[@]}"

    cd "$SCRIPT_DIR"

    # Dọn working dirs (giữ cache)
    rm -rf "$WORK_DIR/squashfs" "$WORK_DIR/custom" "$WORK_DIR/mnt"
}

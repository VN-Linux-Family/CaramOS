#!/bin/bash
# Bước 7: Đóng gói squashfs + ISO

step_repack() {
    info "[7/7] Đóng gói ISO..."

    # Rebuild squashfs
    info "  → Tạo filesystem.squashfs (5-10 phút)..."
    mksquashfs "$WORK_DIR/squashfs" "$WORK_DIR/custom/casper/filesystem.squashfs" \
        -comp xz -b 1M -Xdict-size 100% -noappend
    ok "squashfs xong."

    # Cập nhật filesystem.size
    printf '%s' "$(du -sx --block-size=1 "$WORK_DIR/squashfs" | cut -f1)" \
        > "$WORK_DIR/custom/casper/filesystem.size"

    # Cập nhật md5sum
    cd "$WORK_DIR/custom"
    find . -type f ! -name 'md5sum.txt' -print0 | xargs -0 md5sum > md5sum.txt 2>/dev/null || true

    # Tạo ISO
    info "  → Tạo ISO..."
    xorriso -as mkisofs \
        -iso-level 3 \
        -full-iso9660-filenames \
        -volid "CaramOS ${CARAMOS_VERSION}" \
        -eltorito-boot boot/grub/bios.img \
        -no-emul-boot -boot-load-size 4 -boot-info-table \
        --grub2-boot-info --grub2-mbr /usr/lib/grub/i386-pc/boot_hybrid.img \
        -eltorito-alt-boot \
        -e EFI/boot/efiboot.img \
        -no-emul-boot \
        -append_partition 2 0xef EFI/boot/efiboot.img \
        -output "$SCRIPT_DIR/$OUTPUT_ISO" \
        .

    cd "$SCRIPT_DIR"

    # Dọn build
    rm -rf "$WORK_DIR"
}

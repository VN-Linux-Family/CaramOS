#!/bin/bash
# Bước 7: Đóng gói squashfs + ISO

clean_virtual_dirs() {
    local SFS="$WORK_DIR/squashfs"

    # Dọn file tạm trước khi pack. Nếu build bị Ctrl+C giữa hook
    # (đặc biệt WPS repack cũ), /tmp có thể còn .deb/data.tar.xz/opt rất lớn
    # và make quick sẽ vô tình đóng gói chúng vào ISO.
    rm -rf "$SFS/tmp"/* "$SFS/var/tmp"/* 2>/dev/null || true

    # Đảm bảo các virtual fs dir trống sạch trước khi pack vào squashfs.
    # KHÔNG dùng -e proc/sys/dev/run để loại trừ — nếu loại trừ, các thư mục
    # này sẽ KHÔNG TỒN TẠI trong squashfs, casper sẽ không có chỗ để mount
    # devtmpfs/proc/sysfs vào → /dev/null không tồn tại → boot crash.
    # Các dir phải có mặt nhưng TRỐNG; chúng đã được umount ở step_customize.
    for dir in proc sys dev run; do
        if [ -d "$SFS/$dir" ]; then
            # Xoá nội dung bên trong nhưng giữ thư mục gốc
            find "$SFS/$dir" -mindepth 1 -delete 2>/dev/null || true
        else
            # Thư mục không tồn tại → tạo lại để casper có chỗ mount
            mkdir -p "$SFS/$dir"
        fi
    done
}

step_repack_squashfs() {
    ensure_work_tree
    umount_chroot
    clean_virtual_dirs

    info "  → Tạo filesystem.squashfs (${SQUASHFS_COMP})..."
    mksquashfs "$WORK_DIR/squashfs" "$WORK_DIR/custom/casper/filesystem.squashfs" \
        -comp $SQUASHFS_COMP $SQUASHFS_OPTS
    ok "squashfs xong."

    # Cập nhật filesystem.size
    printf '%s' "$(du -sx --block-size=1 "$WORK_DIR/squashfs" | cut -f1)" \
        > "$WORK_DIR/custom/casper/filesystem.size"

    # Live ISO boot dùng build/custom/casper/initrd.lz, KHÔNG tự dùng file
    # /boot/initrd.img-* trong squashfs. Hook Plymouth đã regenerate initramfs
    # trong rootfs, nên phải copy file mới này ra casper/initrd.lz.
    local latest_initrd
    latest_initrd=$(ls -1t "$WORK_DIR"/squashfs/boot/initrd.img-* 2>/dev/null | head -1 || true)
    if [ -n "$latest_initrd" ] && [ -f "$latest_initrd" ]; then
        cp "$latest_initrd" "$WORK_DIR/custom/casper/initrd.lz"
        ok "live initrd đã cập nhật: $(basename "$latest_initrd") → casper/initrd.lz"
    else
        warn "không tìm thấy initrd.img-* trong rootfs để cập nhật casper/initrd.lz"
    fi

    local latest_vmlinuz
    latest_vmlinuz=$(ls -1t "$WORK_DIR"/squashfs/boot/vmlinuz-* 2>/dev/null | head -1 || true)
    if [ -n "$latest_vmlinuz" ] && [ -f "$latest_vmlinuz" ]; then
        cp "$latest_vmlinuz" "$WORK_DIR/custom/casper/vmlinuz"
        ok "live kernel đã cập nhật: $(basename "$latest_vmlinuz") → casper/vmlinuz"
    else
        warn "không tìm thấy vmlinuz-* trong rootfs để cập nhật casper/vmlinuz"
    fi
}

step_repack_iso() {
    ensure_work_tree

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
    if [ -f "isolinux/isolinux.bin" ] && [ -f /usr/lib/ISOLINUX/isohdpfx.bin ]; then
        XORRISO_ARGS+=(-isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin)
    fi

    XORRISO_ARGS+=(-output "$SCRIPT_DIR/$OUTPUT_ISO" .)

    xorriso "${XORRISO_ARGS[@]}"

    cd "$SCRIPT_DIR"
}

step_repack() {
    info "[7/7] Đóng gói ISO..."
    step_repack_squashfs
    step_repack_iso
}

step_repack_and_clean() {
    step_repack
    safe_remove_work_dirs
}

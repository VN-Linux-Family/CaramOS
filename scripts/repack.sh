#!/bin/bash
# Bước 7: Đóng gói squashfs + ISO

step_repack() {
    info "[7/7] Đóng gói ISO..."

    local SFS="$WORK_DIR/squashfs"

    # Đảm bảo các virtual fs dir trống sạch trước khi pack vào squashfs.
    # KHÔNG dùng -e proc/sys/dev/run để loại trừ — nếu loại trừ, các thư mục
    # này sẽ KHÔNG TỒN TẠI trong squashfs, casper sẽ không có chỗ để mount
    # devtmpfs/proc/sysfs vào → /dev/null không tồn tại → boot crash.
    # Các dir phải có mặt nhưng TRỐNG; chúng đã được umount ở step_customize.
    for dir in proc sys dev run; do
        if [ -d "$SFS/$dir" ]; then
            # Kiểm tra lần cuối còn mount không (paranoia check)
            if mountpoint -q "$SFS/$dir" 2>/dev/null; then
                error "CRITICAL: $SFS/$dir vẫn còn mount — không thể pack. Dọn thủ công: sudo umount -lf $SFS/$dir"
            fi
            # Xoá nội dung bên trong nhưng giữ thư mục gốc
            find "$SFS/$dir" -mindepth 1 -delete 2>/dev/null || true
        else
            # Thư mục không tồn tại → tạo lại để casper có chỗ mount
            mkdir -p "$SFS/$dir"
        fi
    done

    # Rebuild squashfs
    info "  → Tạo filesystem.squashfs (${SQUASHFS_COMP})..."
    mksquashfs "$SFS" "$WORK_DIR/custom/casper/filesystem.squashfs" \
        -comp $SQUASHFS_COMP $SQUASHFS_OPTS
    ok "squashfs xong."

    # Cập nhật filesystem.size
    printf '%s' "$(du -sx --block-size=1 "$SFS" | cut -f1)" \
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
    if [ -f "isolinux/isolinux.bin" ] && [ -f /usr/lib/ISOLINUX/isohdpfx.bin ]; then
        XORRISO_ARGS+=(-isohybrid-mbr /usr/lib/ISOLINUX/isohdpfx.bin)
    fi

    XORRISO_ARGS+=(-output "$SCRIPT_DIR/$OUTPUT_ISO" .)

    xorriso "${XORRISO_ARGS[@]}"

    cd "$SCRIPT_DIR"

    # Dọn working dirs (giữ cache)
    # Không dùng umount -Rlf trước rm -rf — xem customize.sh để biết lý do.
    # Ở đây squashfs đã được umount sạch từ step_customize; chỉ kiểm tra lại
    # để chắc chắn không còn mount nào trước khi xoá (phòng trường hợp
    # build bị gọi lại không qua step_customize, ví dụ debug repack riêng)
    if grep -q " $WORK_DIR/squashfs/" /proc/mounts 2>/dev/null; then
        warn "Phát hiện mount còn sót trong squashfs, đang umount..."
        for mp in "$SFS/dev/pts" "$SFS/dev" "$SFS/proc" "$SFS/sys" "$SFS/run"; do
            mountpoint -q "$mp" 2>/dev/null && umount -lf "$mp" || true
        done
        # Nếu vẫn còn → không rm -rf, tránh phá host
        if grep -q " $SFS/" /proc/mounts 2>/dev/null; then
            error "CRITICAL: Không umount được $SFS — bỏ qua rm -rf để bảo vệ host. Dọn thủ công bằng: sudo umount -Rlf $SFS"
        fi
    fi
    rm -rf "$SFS" "$WORK_DIR/custom" "$WORK_DIR/mnt" 2>/dev/null || true
}

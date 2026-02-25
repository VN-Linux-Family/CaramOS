#!/bin/bash
# Cấu hình bootloader cho chế độ debug:
#   - Xoá quiet + splash khỏi kernel cmdline (hiện kernel log khi boot)
#   - Đổi "Linux Mint" → "CaramOS" trong text menu bootloader
#   - Vô hiệu hoá plymouth trong rootfs (không che log bằng splash screen)
#
# Chạy SAU step_extract, TRƯỚC step_customize
# Tác động lên:
#   $WORK_DIR/custom/   → file cấu hình bootloader của ISO (isolinux, grub)
#   $WORK_DIR/squashfs/ → rootfs (tắt dịch vụ plymouth)

step_boot_config() {
    info "[2.5/7] Cấu hình debug boot (no plymouth, no quiet)..."

    local ISO_DIR="$WORK_DIR/custom"
    local ROOTFS_DIR="$WORK_DIR/squashfs"

    # ----------------------------------------------------------------
    # 1. Sửa isolinux / syslinux (BIOS boot)
    #    File thường gặp: isolinux/txt.cfg, isolinux/isolinux.cfg,
    #                     isolinux/live.cfg, syslinux/syslinux.cfg
    # ----------------------------------------------------------------
    local ISOLINUX_FILES
    ISOLINUX_FILES=$(find "$ISO_DIR" \
        -path "*/isolinux/*.cfg" -o \
        -path "*/syslinux/*.cfg" \
        2>/dev/null)

    if [ -n "$ISOLINUX_FILES" ]; then
        info "  → Sửa isolinux/syslinux config..."
        echo "$ISOLINUX_FILES" | while IFS= read -r cfg; do
            # Xoá flag quiet và splash khỏi dòng kernel/append
            sed -i 's/\bquiet\b//g; s/\bsplash\b//g' "$cfg"

            # Đổi tên distro trong menu label/title
            sed -i 's/Linux Mint/CaramOS/gI' "$cfg"

            ok "    Đã sửa: $(basename "$cfg")"
        done
    else
        warn "  → Không tìm thấy isolinux/syslinux config, bỏ qua."
    fi

    # ----------------------------------------------------------------
    # 2. Sửa GRUB config (UEFI + BIOS hybrid boot)
    #    File thường gặp: boot/grub/grub.cfg, boot/grub/loopback.cfg,
    #                     EFI/boot/grub.cfg
    # ----------------------------------------------------------------
    local GRUB_FILES
    GRUB_FILES=$(find "$ISO_DIR" \
        -path "*/grub/*.cfg" -o \
        -path "*/EFI/boot/*.cfg" \
        2>/dev/null)

    if [ -n "$GRUB_FILES" ]; then
        info "  → Sửa GRUB config..."
        echo "$GRUB_FILES" | while IFS= read -r cfg; do
            # Xoá flag quiet và splash khỏi dòng linux/linuxefi
            sed -i 's/\bquiet\b//g; s/\bsplash\b//g' "$cfg"

            # Đổi tên distro trong menu entry title
            sed -i 's/Linux Mint/CaramOS/gI' "$cfg"

            ok "    Đã sửa: $(basename "$cfg")"
        done
    else
        warn "  → Không tìm thấy GRUB config, bỏ qua."
    fi

    # ----------------------------------------------------------------
    # 3. Vô hiệu hoá plymouth trong rootfs
    #    Mask các service để systemd không khởi động splash screen,
    #    kernel log sẽ hiển thị trực tiếp ra màn hình
    # ----------------------------------------------------------------
    if [ -d "$ROOTFS_DIR/lib/systemd/system" ]; then
        info "  → Mask plymouth services trong rootfs..."

        # Danh sách service plymouth cần tắt
        local PLYMOUTH_SERVICES=(
            "plymouth-start.service"
            "plymouth-read-write.service"
            "plymouth-quit.service"
            "plymouth-quit-wait.service"
            "plymouth-reboot.service"
            "plymouth-kexec.service"
            "plymouth-poweroff.service"
            "plymouth-halt.service"
        )

        for svc in "${PLYMOUTH_SERVICES[@]}"; do
            local svc_path="$ROOTFS_DIR/lib/systemd/system/$svc"
            # Chỉ mask nếu service thực sự tồn tại trong rootfs
            if [ -f "$svc_path" ] || [ -L "$svc_path" ]; then
                # Mask = symlink /dev/null, systemd sẽ bỏ qua hoàn toàn
                ln -sf /dev/null "$ROOTFS_DIR/etc/systemd/system/$svc"
                ok "    Đã mask: $svc"
            fi
        done

        # Đảm bảo thư mục systemd/system tồn tại trong etc (nơi override)
        mkdir -p "$ROOTFS_DIR/etc/systemd/system"
    else
        warn "  → Không tìm thấy systemd trong rootfs, bỏ qua mask plymouth."
    fi

    # ----------------------------------------------------------------
    # 4. Vô hiệu hook initramfs của plymouth
    #    KHÔNG xoá /usr/bin/plymouth binary — nếu xoá, dpkg post-install
    #    scripts (initramfs-tools, kernel) sẽ gọi plymouth → exit 127 →
    #    toàn bộ apt/dpkg lỗi dây chuyền trong chroot.
    #
    #    Thay vào đó: xoá hook initramfs để plymouth KHÔNG được đóng gói
    #    vào initrd → kernel boot không có splash, log hiện bình thường.
    #    Binary vẫn tồn tại cho dpkg, nhưng systemd services đã bị mask
    #    ở bước 3 nên plymouth sẽ không chạy khi boot.
    # ----------------------------------------------------------------
    local INITRAMFS_HOOK="$ROOTFS_DIR/usr/share/initramfs-tools/hooks/plymouth"
    if [ -f "$INITRAMFS_HOOK" ]; then
        info "  → Xoá hook initramfs của plymouth (giữ binary cho dpkg)..."
        rm -f "$INITRAMFS_HOOK"
        ok "    Đã xoá: /usr/share/initramfs-tools/hooks/plymouth"
    fi

    ok "[2.5/7] Boot config debug xong."
}

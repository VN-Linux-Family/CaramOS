#!/bin/bash
# Cấu hình bootloader + plymouth theo build mode:
#   - Branding (Linux Mint → CaramOS): LUÔN áp dụng, cả debug lẫn release
#   - Debug mode (mặc định, SQUASHFS_COMP=lz4):
#       · Xoá quiet + splash khỏi kernel cmdline → hiện kernel log khi boot
#       · Mask plymouth services + xoá initramfs hook → không che log
#   - Release mode (--release, SQUASHFS_COMP=xz):
#       · Giữ nguyên quiet + splash → boot im lặng, đẹp cho người dùng cuối
#       · Giữ nguyên plymouth → splash screen hiện bình thường
#
# Chạy SAU step_extract, TRƯỚC step_customize
# Tác động lên:
#   $WORK_DIR/custom/   → file cấu hình bootloader của ISO (isolinux, grub)
#   $WORK_DIR/squashfs/ → rootfs (chỉ bị sửa ở debug mode)

step_boot_config() {
    local ISO_DIR="$WORK_DIR/custom"
    local ROOTFS_DIR="$WORK_DIR/squashfs"

    # SQUASHFS_COMP được set trong build.sh:
    #   lz4 (mặc định) = debug, xz (--release) = release
    local IS_DEBUG=true
    [ "${SQUASHFS_COMP:-lz4}" = "xz" ] && IS_DEBUG=false

    if $IS_DEBUG; then
        info "[2.5/7] Cấu hình debug boot (no quiet, no plymouth)..."
    else
        info "[2.5/7] Cấu hình release boot (branding only)..."
    fi

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
            # Đổi tên distro trong menu label/title — áp dụng mọi mode
            sed -i 's/Linux Mint/CaramOS/gI' "$cfg"

            # Chỉ xoá quiet/splash ở debug mode
            if $IS_DEBUG; then
                sed -i 's/\bquiet\b//g; s/\bsplash\b//g' "$cfg"
            fi

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
            # Đổi tên distro trong menu entry title — áp dụng mọi mode
            sed -i 's/Linux Mint/CaramOS/gI' "$cfg"

            # Chỉ xoá quiet/splash ở debug mode
            if $IS_DEBUG; then
                sed -i 's/\bquiet\b//g; s/\bsplash\b//g' "$cfg"
            fi

            ok "    Đã sửa: $(basename "$cfg")"
        done
    else
        warn "  → Không tìm thấy GRUB config, bỏ qua."
    fi

    # ----------------------------------------------------------------
    # 3. Set syslinux splash background — áp dụng mọi mode
    #
    #    Mint ISO có thể đặt MENU BACKGROUND ở nhiều file khác nhau tuỳ
    #    version: stdmenu.cfg, isolinux.cfg, txt.cfg, v.v.
    #    Chiến lược:
    #      a) Tìm thư mục isolinux trong ISO
    #      b) Copy banner → isolinux/splash.png
    #      c) Grep TẤT CẢ cfg trong isolinux/ tìm file nào đang có
    #         "MENU BACKGROUND" → update dòng đó → đúng file, đúng chỗ
    #      d) Nếu không file nào có → thêm vào stdmenu.cfg nếu tồn tại,
    #         không thì thêm vào isolinux.cfg (fallback cuối cùng)
    # ----------------------------------------------------------------
    local BANNER_SRC="$SCRIPT_DIR/caramos_vietnam_banner.png"
    local ISOLINUX_DIR
    ISOLINUX_DIR=$(find "$ISO_DIR" -maxdepth 3 -name "isolinux.bin" \
        -exec dirname {} \; 2>/dev/null | head -1)

    if [ ! -f "$BANNER_SRC" ]; then
        warn "  → Không tìm thấy caramos_vietnam_banner.png ở root repo, bỏ qua splash."
    elif [ -z "$ISOLINUX_DIR" ]; then
        warn "  → Không tìm thấy thư mục isolinux, bỏ qua splash."
    else
        info "  → Set syslinux splash background..."

        # Copy banner vào isolinux/ với tên splash.png
        cp "$BANNER_SRC" "$ISOLINUX_DIR/splash.png"
        ok "    Đã copy: splash.png → $ISOLINUX_DIR/"

        # Tìm file cfg nào ĐANG chứa dòng MENU BACKGROUND (bất kể giá trị cũ)
        local BG_CFG
        BG_CFG=$(grep -rli "MENU BACKGROUND" "$ISOLINUX_DIR/" 2>/dev/null | head -1)

        if [ -n "$BG_CFG" ]; then
            # File đã có MENU BACKGROUND → chỉ update giá trị, giữ nguyên vị trí dòng
            sed -i 's|^\(MENU BACKGROUND\).*|\1 splash.png|gI' "$BG_CFG"
            ok "    Updated MENU BACKGROUND trong: $(basename "$BG_CFG")"
        else
            # Không file nào có MENU BACKGROUND → thêm mới
            # Ưu tiên: stdmenu.cfg (Mint đặt MENU directives ở đây) → isolinux.cfg
            local INSERT_CFG="$ISOLINUX_DIR/stdmenu.cfg"
            [ ! -f "$INSERT_CFG" ] && INSERT_CFG="$ISOLINUX_DIR/isolinux.cfg"

            if [ -f "$INSERT_CFG" ]; then
                # Chèn ngay sau dòng MENU COLOR đầu tiên nếu có (cùng nhóm MENU directives),
                # không thì chèn sau dòng đầu tiên của file
                if grep -qi "^MENU COLOR" "$INSERT_CFG"; then
                    sed -i '0,/^MENU COLOR/s//MENU BACKGROUND splash.png\n&/' "$INSERT_CFG"
                else
                    sed -i '1s|^|MENU BACKGROUND splash.png\n|' "$INSERT_CFG"
                fi
                ok "    Thêm MENU BACKGROUND vào: $(basename "$INSERT_CFG")"
            else
                warn "    Không tìm thấy cfg phù hợp để thêm MENU BACKGROUND."
            fi
        fi
    fi

    # ----------------------------------------------------------------
    # 4+5. Vô hiệu hoá plymouth — CHỈ ở debug mode
    #      Release mode giữ nguyên plymouth để có splash screen đẹp
    # ----------------------------------------------------------------
    if $IS_DEBUG; then
        # -- 4. Mask plymouth systemd services --
        # Mask các service để systemd không khởi động splash screen,
        # kernel log sẽ hiển thị trực tiếp ra màn hình
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

            # Đảm bảo thư mục systemd/system tồn tại trong etc (nơi override)
            mkdir -p "$ROOTFS_DIR/etc/systemd/system"

            for svc in "${PLYMOUTH_SERVICES[@]}"; do
                local svc_path="$ROOTFS_DIR/lib/systemd/system/$svc"
                # Chỉ mask nếu service thực sự tồn tại trong rootfs
                if [ -f "$svc_path" ] || [ -L "$svc_path" ]; then
                    # Mask = symlink /dev/null, systemd sẽ bỏ qua hoàn toàn
                    ln -sf /dev/null "$ROOTFS_DIR/etc/systemd/system/$svc"
                    ok "    Đã mask: $svc"
                fi
            done
        else
            warn "  → Không tìm thấy systemd trong rootfs, bỏ qua mask plymouth."
        fi

        # -- 5. Vô hiệu hook initramfs của plymouth --
        # KHÔNG xoá /usr/bin/plymouth binary — nếu xoá, dpkg post-install
        # scripts (initramfs-tools, kernel) sẽ gọi plymouth → exit 127 →
        # toàn bộ apt/dpkg lỗi dây chuyền trong chroot.
        #
        # Thay vào đó: xoá hook initramfs để plymouth KHÔNG được đóng gói
        # vào initrd → kernel boot không có splash, log hiện bình thường.
        # Binary vẫn tồn tại cho dpkg, nhưng systemd services đã bị mask
        # ở bước 4 nên plymouth sẽ không chạy khi boot.
        local INITRAMFS_HOOK="$ROOTFS_DIR/usr/share/initramfs-tools/hooks/plymouth"
        if [ -f "$INITRAMFS_HOOK" ]; then
            info "  → Xoá hook initramfs của plymouth (giữ binary cho dpkg)..."
            rm -f "$INITRAMFS_HOOK"
            ok "    Đã xoá: /usr/share/initramfs-tools/hooks/plymouth"
        fi

        ok "[2.5/7] Boot config debug xong."
    else
        ok "[2.5/7] Boot config release xong (plymouth giữ nguyên)."
    fi
}

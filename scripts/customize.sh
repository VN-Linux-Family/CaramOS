#!/bin/bash
# Bước 4-6: Chroot + tuỳ biến + dọn dẹp

cleanup_chroot_package_state() {
    info "  → Dọn trạng thái apt/dpkg cũ trong chroot..."
    chroot "$WORK_DIR/squashfs" /bin/bash -c '
        export DEBIAN_FRONTEND=noninteractive
        mkdir -p /usr/share/package-data-downloads.disabled
        if [ -d /usr/share/package-data-downloads ]; then
            find /usr/share/package-data-downloads -maxdepth 1 -type f -exec mv -f {} /usr/share/package-data-downloads.disabled/ \; 2>/dev/null || true
        fi
        rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock 2>/dev/null || true
        timeout 60 dpkg --configure -a --force-confdef --force-confold >/dev/null 2>&1 || true
        # Build only: a mirror that drops a connection (as archive.ubuntu.com did on GitHub runners on 2026-11-23)
        # gets retried instead of failing the whole ISO. Removed again in the clean-up step.
        printf "Acquire::Retries \"5\";\n" > /etc/apt/apt.conf.d/99caramos-build-retries
    '
}

step_customize() {
    # --- Mount chroot ---
    info "[4/7] Mount chroot..."
    mount_chroot
    cleanup_chroot_package_state

    # --- Tuỳ biến ---
    info "[5/7] Tuỳ biến CaramOS..."

    # Cài thêm packages: config/packages.txt cho mọi phiên bản, config/packages-<phiên bản>.txt riêng (vd. xfce)
    if [ -f "$SCRIPT_DIR/config/packages.txt" ]; then
        info "  → Cài thêm packages..."
        cat "$SCRIPT_DIR/config/packages.txt" > "$WORK_DIR/squashfs/tmp/packages.txt"
        if [ -f "$SCRIPT_DIR/config/packages-${MINT_EDITION}.txt" ]; then
            cat "$SCRIPT_DIR/config/packages-${MINT_EDITION}.txt" >> "$WORK_DIR/squashfs/tmp/packages.txt"
        fi
        chroot "$WORK_DIR/squashfs" /bin/bash -c '
            export DEBIAN_FRONTEND=noninteractive
            APT_LOCK_TIMEOUT="${APT_LOCK_TIMEOUT:-600}"
            echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections || true
            echo "ttf-mscorefonts-installer msttcorefonts/present-mscorefonts-eula note" | debconf-set-selections || true
            # Đổi sang mirror VN (BizFly Cloud) trước khi apt-get update
            # archive.ubuntu.com đặt ở US/EU, tốc độ ~150kB/s từ VN — mirror VN đạt ~5-15MB/s
            sed -i "s|http://archive.ubuntu.com/ubuntu|http://mirror.bizflycloud.vn/ubuntu|g" /etc/apt/sources.list
            sed -i "s|http://security.ubuntu.com/ubuntu|http://mirror.bizflycloud.vn/ubuntu|g"  /etc/apt/sources.list
            apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT" update
            grep -v "^#" /tmp/packages.txt | grep -v "^$" | xargs apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT" install -y
            rm /tmp/packages.txt
        '
        ok "Cài packages xong."
    fi

    # Copy overlay
    step_overlay

    # Chạy hooks
    for hook in "$SCRIPT_DIR/config/hooks/live/"*.hook.chroot; do
        if [ -f "$hook" ]; then
            hook_name=$(basename "$hook")
            info "  → Chạy hook: $hook_name"
            cp "$hook" "$WORK_DIR/squashfs/tmp/$hook_name"
            CARAMOS_VERSION="${CARAMOS_MIGRATION_BASE_VERSION:-$CARAMOS_VERSION}" \
            MINT_VERSION="$MINT_VERSION" \
            MINT_EDITION="$MINT_EDITION" \
            chroot "$WORK_DIR/squashfs" /bin/bash "/tmp/$hook_name"
            rm -f "$WORK_DIR/squashfs/tmp/$hook_name"
            ok "Hook $hook_name xong."
        fi
    done

    # Cài OTA package và chạy tất cả migrations vào rootfs trước khi đóng ISO.
    step_ota_bootstrap

    # Chỉ đánh dấu customized sau khi TOÀN BỘ hook + OTA bootstrap đã chạy xong.
    # Nếu bị Ctrl+C giữa chừng, marker không được tạo và make quick sẽ buộc
    # chạy lại customize thay vì repack rootfs thiếu Plymouth/Cinnamenu/dock.
    chroot "$WORK_DIR/squashfs" /usr/bin/env MINT_EDITION="$MINT_EDITION" /bin/bash -c '
        set -e
        test -f /etc/dconf/db/local
        test -f /etc/xdg/autostart/caramos-theme.desktop
        test -f /etc/systemd/zram-generator.conf
        grep -q "^zram-size = ram / 2$" /etc/systemd/zram-generator.conf
        test -f /usr/share/plymouth/themes/caramos/caramos.plymouth
        # Driver Check runs at the first login; its hardware reports need hw-probe (OTA migration).
        test -f /etc/xdg/autostart/caramos-driver-check.desktop
        command -v hw-probe
        if [ "$MINT_EDITION" = xfce ]; then
            # Bản Xfce: panel CaramOS (Whisker menu, Góp ý & hỗ trợ) và Nemo làm trình quản lý tệp.
            test -f /etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml
            grep -q /usr/share/caramos-ota/xfce/caramos-help-panel.desktop /etc/xdg/caramos-xfce/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml
            test -f /usr/share/caramos-ota/xfce/caramos-help-panel.desktop
            test -f /etc/X11/Xsession.d/61caramos-xfce
            command -v nemo
            test -f /usr/share/applications/caramos-help.desktop
        else
            test -d /usr/share/cinnamon/applets/Cinnamenu@json
            find /usr/share/cinnamon/applets/Cinnamenu@json -name settings-schema.json -print -quit | grep -q .
            # Feedback & Help: the question mark on the panel (hook 0170 and an OTA migration put it there).
            test -f /usr/share/cinnamon/applets/caramos-help@caramos/applet.js
            grep -q "caramos-help@caramos" /etc/dconf/db/local.d/01-caramos-task17-panel
        fi
        date -u +"%Y-%m-%dT%H:%M:%SZ" > /etc/caramos-customized
    '
    ok "Rootfs đã được customize đầy đủ."

    # --- Dọn dẹp chroot ---
    info "[6/7] Dọn dẹp chroot..."
    chroot "$WORK_DIR/squashfs" /bin/bash -c '
        APT_LOCK_TIMEOUT="${APT_LOCK_TIMEOUT:-600}"
        apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT" clean
        # Backups debconf and dpkg keep of their databases from before the last package change.
        rm -f /var/cache/debconf/*-old /var/lib/dpkg/*-old
        rm -rf /tmp/* /var/tmp/*
        rm -f /etc/apt/apt.conf.d/99caramos-build-retries
        rm -f /etc/resolv.conf
    '
    umount_chroot
}

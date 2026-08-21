#!/bin/bash
# Steps 4-6: Chroot + customization + cleanup

cleanup_chroot_package_state() {
    info "  → Cleaning stale apt/dpkg state in chroot..."
    chroot "$WORK_DIR/squashfs" /bin/bash -c '
        export DEBIAN_FRONTEND=noninteractive
        mkdir -p /usr/share/package-data-downloads.disabled
        if [ -d /usr/share/package-data-downloads ]; then
            find /usr/share/package-data-downloads -maxdepth 1 -type f -exec mv -f {} /usr/share/package-data-downloads.disabled/ \; 2>/dev/null || true
        fi
        rm -f /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock 2>/dev/null || true
        timeout 60 dpkg --configure -a --force-confdef --force-confold >/dev/null 2>&1 || true
    '
}

step_customize() {
    info "[4/7] Mounting chroot..."
    mount_chroot
    cleanup_chroot_package_state

    info "[5/7] Customizing CaramOS..."

    if [ -f "$SCRIPT_DIR/config/packages.txt" ]; then
        info "  → Installing additional packages..."
        cp "$SCRIPT_DIR/config/packages.txt" "$WORK_DIR/squashfs/tmp/packages.txt"
        chroot "$WORK_DIR/squashfs" /bin/bash -c '
            export DEBIAN_FRONTEND=noninteractive
            APT_LOCK_TIMEOUT="${APT_LOCK_TIMEOUT:-600}"
            echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections || true
            echo "ttf-mscorefonts-installer msttcorefonts/present-mscorefonts-eula note" | debconf-set-selections || true
            sed -i "s|http://archive.ubuntu.com/ubuntu|http://mirror.bizflycloud.vn/ubuntu|g" /etc/apt/sources.list
            sed -i "s|http://security.ubuntu.com/ubuntu|http://mirror.bizflycloud.vn/ubuntu|g"  /etc/apt/sources.list
            apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT" update
            grep -v "^#" /tmp/packages.txt | grep -v "^$" | xargs apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT" install -y
            rm /tmp/packages.txt
        '
        ok "Package installation complete."
    fi

    step_overlay

    for hook in "$SCRIPT_DIR/config/hooks/live/"*.hook.chroot; do
        if [ -f "$hook" ]; then
            hook_name=$(basename "$hook")
            info "  → Running hook: $hook_name"
            cp "$hook" "$WORK_DIR/squashfs/tmp/$hook_name"
            CARAMOS_VERSION="${CARAMOS_MIGRATION_BASE_VERSION:-$CARAMOS_VERSION}" \
            MINT_VERSION="$MINT_VERSION" \
            MINT_EDITION="$MINT_EDITION" \
            chroot "$WORK_DIR/squashfs" /bin/bash "/tmp/$hook_name"
            rm -f "$WORK_DIR/squashfs/tmp/$hook_name"
            ok "Hook $hook_name complete."
        fi
    done

    step_ota_bootstrap

    chroot "$WORK_DIR/squashfs" /bin/bash -c '
        set -e
        test -f /etc/dconf/db/local
        test -f /etc/xdg/autostart/caramos-theme.desktop
        test -f /etc/systemd/zram-generator.conf
        grep -q "^zram-size = ram / 2$" /etc/systemd/zram-generator.conf
        test -d /usr/share/cinnamon/applets/Cinnamenu@json
        find /usr/share/cinnamon/applets/Cinnamenu@json -name settings-schema.json -print -quit | grep -q .
        test -f /usr/share/plymouth/themes/caramos/caramos.plymouth
        date -u +"%Y-%m-%dT%H:%M:%SZ" > /etc/caramos-customized
    '
    ok "Rootfs fully customized."

    info "[6/7] Cleaning chroot..."
    chroot "$WORK_DIR/squashfs" /bin/bash -c '
        APT_LOCK_TIMEOUT="${APT_LOCK_TIMEOUT:-600}"
        apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT" clean
        rm -rf /tmp/* /var/tmp/*
        rm -f /etc/resolv.conf
    '
    umount_chroot
}

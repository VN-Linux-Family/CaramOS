#!/bin/bash
# Bước 4-6: Chroot + tuỳ biến + dọn dẹp

step_customize() {
    # --- Mount chroot ---
    info "[4/7] Mount chroot..."
    mount --bind /dev     "$WORK_DIR/squashfs/dev"
    mount --bind /dev/pts "$WORK_DIR/squashfs/dev/pts"
    mount -t proc proc    "$WORK_DIR/squashfs/proc"
    mount -t sysfs sysfs  "$WORK_DIR/squashfs/sys"
    cp /etc/resolv.conf   "$WORK_DIR/squashfs/etc/resolv.conf"

    # --- Tuỳ biến ---
    info "[5/7] Tuỳ biến CaramOS..."

    # Cài thêm packages
    if [ -f "$SCRIPT_DIR/config/packages.txt" ]; then
        info "  → Cài thêm packages..."
        cp "$SCRIPT_DIR/config/packages.txt" "$WORK_DIR/squashfs/tmp/packages.txt"
        chroot "$WORK_DIR/squashfs" /bin/bash -c '
            export DEBIAN_FRONTEND=noninteractive
            # Pre-select SDDM as default display manager
            echo "sddm shared/default-x-display-manager select sddm" | debconf-set-selections
            # Đổi sang mirror VN (BizFly Cloud) trước khi apt-get update
            # archive.ubuntu.com đặt ở US/EU, tốc độ ~150kB/s từ VN — mirror VN đạt ~5-15MB/s
            sed -i "s|http://archive.ubuntu.com/ubuntu|http://mirror.bizflycloud.vn/ubuntu|g" /etc/apt/sources.list
            sed -i "s|http://security.ubuntu.com/ubuntu|http://mirror.bizflycloud.vn/ubuntu|g"  /etc/apt/sources.list
            apt-get update
            grep -v "^#" /tmp/packages.txt | grep -v "^$" | xargs apt-get install -y
            rm /tmp/packages.txt
        '
        ok "Cài packages xong."
    fi

    # Copy overlay
    if [ -d "$SCRIPT_DIR/config/includes.chroot" ]; then
        info "  → Copy overlay files..."
        cp -a "$SCRIPT_DIR/config/includes.chroot/"* "$WORK_DIR/squashfs/"
        ok "Copy overlay xong."
    fi

    # Chạy hooks
    for hook in "$SCRIPT_DIR/config/hooks/live/"*.hook.chroot; do
        if [ -f "$hook" ]; then
            hook_name=$(basename "$hook")
            info "  → Chạy hook: $hook_name"
            cp "$hook" "$WORK_DIR/squashfs/tmp/$hook_name"
            chroot "$WORK_DIR/squashfs" /bin/bash "/tmp/$hook_name"
            rm -f "$WORK_DIR/squashfs/tmp/$hook_name"
            ok "Hook $hook_name xong."
        fi
    done

    # --- Dọn dẹp chroot ---
    info "[6/7] Dọn dẹp chroot..."
    chroot "$WORK_DIR/squashfs" /bin/bash -c '
        apt-get clean
        rm -rf /tmp/* /var/tmp/*
        rm -f /etc/resolv.conf
    '

    # Umount theo thứ tự NGƯỢC với mount — KHÔNG dùng -Rlf một lần vì
    # kernel có thể lazy-detach nhưng mountpoint vẫn còn trong /proc/mounts,
    # khiến rm -rf sau đó xoá thẳng vào /dev /proc của host → /dev/null bị phá.
    # Thứ tự: dev/pts trước dev (dev/pts là submount của dev bind)
    local SFS="$WORK_DIR/squashfs"
    for mp in "$SFS/dev/pts" "$SFS/dev" "$SFS/proc" "$SFS/sys" "$SFS/run"; do
        # Chỉ umount nếu thực sự đang được mount (tránh lỗi khi mount thất bại ở trên)
        if mountpoint -q "$mp" 2>/dev/null; then
            umount -lf "$mp" || warn "  umount thất bại: $mp (tiếp tục)"
        fi
    done

    # Kiểm tra lần cuối — nếu vẫn còn mount trong squashfs thì DỪNG,
    # không để rm -rf chạy vào host filesystem
    if grep -q " $SFS/" /proc/mounts 2>/dev/null; then
        error "CRITICAL: Vẫn còn bind mount trong $SFS — dừng để tránh xoá host! Kiểm tra /proc/mounts rồi umount thủ công."
    fi
}

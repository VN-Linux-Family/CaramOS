#!/bin/bash
# Fast path: chỉ copy overlay vào rootfs đang làm việc.

step_overlay() {
    ensure_work_tree

    if [ -d "$SCRIPT_DIR/config/includes.chroot" ]; then
        info "Copy overlay files..."
        shopt -s nullglob dotglob
        local overlay_files=("$SCRIPT_DIR/config/includes.chroot"/*)
        if [ ${#overlay_files[@]} -eq 0 ]; then
            warn "Overlay rỗng: config/includes.chroot"
        else
            # Older builds accidentally created fcitx5/profile as a directory.
            # The correct Fcitx5 profile path is a file, so remove the stale
            # directory before overlay copy to avoid "cannot overwrite directory".
            if [ -d "$WORK_DIR/squashfs/etc/skel/.config/fcitx5/profile" ]; then
                rm -rf "$WORK_DIR/squashfs/etc/skel/.config/fcitx5/profile"
            fi
            # Copy với owner root:root và bỏ quyền ghi group/other. cp -a giữ nguyên uid/gid của máy build
            # (vd. 1001) và bit g+w do umask, khiến /etc, /usr, /usr/bin, /usr/share trong ISO thuộc về
            # uid đó: trên máy đã cài, user thứ hai (uid 1001) sẽ ghi được vào /etc và /usr.
            # Git chỉ lưu bit thực thi nên go-w không làm mất quyền nào có chủ đích.
            rsync -a --chown=root:root --chmod=go-w "$SCRIPT_DIR/config/includes.chroot/" "$WORK_DIR/squashfs/"

            # Overlay có thể thay đổi /etc/dconf/db/local.d và GSettings schemas.
            # Nếu không compile lại, make quick sẽ repack DB cũ dù source overlay đã đúng.
            if [ -d "$WORK_DIR/squashfs/etc/dconf/db/local.d" ]; then
                chroot "$WORK_DIR/squashfs" /bin/bash -c 'dconf compile /etc/dconf/db/local /etc/dconf/db/local.d || dconf update || true'
            fi
            if [ -d "$WORK_DIR/squashfs/usr/share/glib-2.0/schemas" ]; then
                chroot "$WORK_DIR/squashfs" /bin/bash -c 'glib-compile-schemas /usr/share/glib-2.0/schemas/ || true'
            fi

            ok "Copy overlay xong."
        fi
        shopt -u nullglob dotglob
    else
        warn "Không tìm thấy config/includes.chroot, bỏ qua overlay."
    fi
}

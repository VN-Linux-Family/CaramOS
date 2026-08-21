#!/bin/bash
# Fast path: only copy overlay into working rootfs.

step_overlay() {
    ensure_work_tree

    if [ -d "$SCRIPT_DIR/config/includes.chroot" ]; then
        info "Copying overlay files..."
        shopt -s nullglob dotglob
        local overlay_files=("$SCRIPT_DIR/config/includes.chroot"/*)
        if [ ${#overlay_files[@]} -eq 0 ]; then
            warn "Overlay is empty: config/includes.chroot"
        else
            # Older builds accidentally created fcitx5/profile as a directory.
            # The correct Fcitx5 profile path is a file, so remove the stale
            # directory before overlay copy to avoid "cannot overwrite directory".
            if [ -d "$WORK_DIR/squashfs/etc/skel/.config/fcitx5/profile" ]; then
                rm -rf "$WORK_DIR/squashfs/etc/skel/.config/fcitx5/profile"
            fi
            cp -a "${overlay_files[@]}" "$WORK_DIR/squashfs/"

            # Overlay may change /etc/dconf/db/local.d and GSettings schemas.
            # If not recompiled, make quick will repack old DB even if overlay source is correct.
            if [ -d "$WORK_DIR/squashfs/etc/dconf/db/local.d" ]; then
                chroot "$WORK_DIR/squashfs" /bin/bash -c 'dconf compile /etc/dconf/db/local /etc/dconf/db/local.d || dconf update || true'
            fi
            if [ -d "$WORK_DIR/squashfs/usr/share/glib-2.0/schemas" ]; then
                chroot "$WORK_DIR/squashfs" /bin/bash -c 'glib-compile-schemas /usr/share/glib-2.0/schemas/ || true'
            fi

            ok "Overlay copy complete."
        fi
        shopt -u nullglob dotglob
    else
        warn "config/includes.chroot not found, skipping overlay."
    fi
}

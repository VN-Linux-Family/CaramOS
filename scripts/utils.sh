#!/bin/bash
# Hàm tiện ích dùng chung

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

HAS_GUM=false
command -v gum &>/dev/null && HAS_GUM=true

APT_LOCK_TIMEOUT="${APT_LOCK_TIMEOUT:-600}"
APT_GET=(apt-get -o DPkg::Lock::Timeout="${APT_LOCK_TIMEOUT}")

preseed_noninteractive_packages() {
    export DEBIAN_FRONTEND=noninteractive
    echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections 2>/dev/null || true
    echo "ttf-mscorefonts-installer msttcorefonts/present-mscorefonts-eula note" | debconf-set-selections 2>/dev/null || true
}
info()  {
    if $HAS_GUM; then
        gum log --level info "$1"
    else
        echo -e "${CYAN}[CaramOS]${NC} $1"
    fi
}

ok() {
    if $HAS_GUM; then
        gum log --level info "✅ $1"
    else
        echo -e "${GREEN}[  OK  ]${NC} $1"
    fi
}

warn() {
    if $HAS_GUM; then
        gum log --level warn "$1"
    else
        echo -e "${YELLOW}[ WARN ]${NC} $1"
    fi
}

error() {
    if $HAS_GUM; then
        gum log --level error "$1"
    else
        echo -e "${RED}[ERROR ]${NC} $1"
    fi
    exit 1
}

# --- Spinner: chạy lệnh với animation chờ ---
run_step() {
    local title="$1"
    shift
    if $HAS_GUM; then
        gum spin --spinner dot --title "$title" -- "$@"
    else
        info "$title"
        "$@"
    fi
}

# --- Header đẹp ---
print_header() {
    if $HAS_GUM; then
        gum style \
            --border rounded --border-foreground 212 \
            --padding "1 3" --margin "1 0" --bold \
            "🍬 CaramOS ${CARAMOS_VERSION}" \
            "" \
            "Input:  ${MINT_ISO}" \
            "Output: ${OUTPUT_ISO}"
    else
        echo ""
        echo "============================================"
        echo -e "  ${CYAN}CaramOS ${CARAMOS_VERSION}${NC} — Build từ Linux Mint"
        echo "============================================"
        echo "  Input:  $MINT_ISO"
        echo "  Output: $OUTPUT_ISO"
        echo ""
    fi
}

# --- Kết quả ---
print_result() {
    local size
    size=$(du -h "$OUTPUT_ISO" | cut -f1)
    if $HAS_GUM; then
        gum style \
            --border double --border-foreground 82 \
            --padding "1 3" --margin "1 0" --bold \
            "✅ Build thành công!" \
            "" \
            "ISO:   ${OUTPUT_ISO}" \
            "Size:  ${size}" \
            "" \
            "Ghi USB:" \
            "  sudo dd if=${OUTPUT_ISO} of=/dev/sdX bs=4M status=progress" \
            "" \
            "Test VM:" \
            "  qemu-system-x86_64 -m 4G -cdrom ${OUTPUT_ISO} -boot d -enable-kvm"
    else
        echo ""
        echo "============================================"
        echo -e "  ${GREEN}✅ Build thành công!${NC}"
        echo ""
        echo "  ISO:  $OUTPUT_ISO"
        echo "  Size: $size"
        echo ""
        echo "  Ghi USB:"
        echo "    sudo dd if=$OUTPUT_ISO of=/dev/sdX bs=4M status=progress"
        echo ""
        echo "  Test VM:"
        echo "    qemu-system-x86_64 -m 4G -cdrom $OUTPUT_ISO -boot d -enable-kvm"
        echo "============================================"
    fi
}

# --- Checks ---
check_root() {
    if [ "$(id -u)" -ne 0 ]; then
        error "Cần chạy với sudo: sudo ./build.sh"
    fi
}

install_deps() {
    local DEPS="squashfs-tools xorriso rsync wget curl isolinux build-essential debhelper"
    local MISSING=""
    for cmd in unsquashfs mksquashfs xorriso rsync wget curl dpkg-buildpackage dh; do
        command -v "$cmd" &>/dev/null || MISSING="yes"
    done
    if [ -n "$MISSING" ]; then
        preseed_noninteractive_packages
        info "Cài công cụ build..."
        "${APT_GET[@]}" update -qq
        "${APT_GET[@]}" install -y $DEPS
        ok "Đã cài xong công cụ."
    fi
}

install_gum() {
    # Skip trong CI hoặc không có terminal
    if [ -n "$CI" ] || [ ! -t 1 ]; then
        return 0
    fi
    if ! command -v gum &>/dev/null; then
        info "Cài gum (UI đẹp cho terminal)..."
        mkdir -p /etc/apt/keyrings
        curl -fsSL https://repo.charm.sh/apt/gpg.key | gpg --dearmor -o /etc/apt/keyrings/charm.gpg
        echo "deb [signed-by=/etc/apt/keyrings/charm.gpg] https://repo.charm.sh/apt/ * *" \
            > /etc/apt/sources.list.d/charm.list
        "${APT_GET[@]}" update -qq
        "${APT_GET[@]}" install -y gum
        HAS_GUM=true
        ok "Đã cài gum."
    fi
}

resolve_iso() {
    if [ -n "$1" ] && [ -f "$1" ]; then
        MINT_ISO="$1"
        info "Dùng ISO: $MINT_ISO"
    elif [ -f "$MINT_ISO_NAME" ]; then
        MINT_ISO="$MINT_ISO_NAME"
        info "Tìm thấy ISO: $MINT_ISO"
    else
        info "Tải Linux Mint ${MINT_VERSION} ${MINT_EDITION} (~2.5GB)..."
        wget --progress=bar:force -c "$MINT_MIRROR" -O "$MINT_ISO_NAME"
        MINT_ISO="$MINT_ISO_NAME"
        ok "Tải xong: $MINT_ISO"
    fi
}

ensure_work_tree() {
    if [ ! -d "$WORK_DIR/squashfs" ] || [ ! -d "$WORK_DIR/custom" ]; then
        warn "Chưa có work tree. Đang prepare trước..."
        step_extract
    fi
}

mount_chroot() {
    ensure_work_tree

    mountpoint -q "$WORK_DIR/squashfs/dev" || mount --bind /dev "$WORK_DIR/squashfs/dev"
    mountpoint -q "$WORK_DIR/squashfs/dev/pts" || mount --bind /dev/pts "$WORK_DIR/squashfs/dev/pts"
    mountpoint -q "$WORK_DIR/squashfs/proc" || mount -t proc proc "$WORK_DIR/squashfs/proc"
    mountpoint -q "$WORK_DIR/squashfs/sys" || mount -t sysfs sysfs "$WORK_DIR/squashfs/sys"

    # Mint/Ubuntu thường để /etc/resolv.conf là symlink tới systemd-resolved.
    # Trong chroot symlink này có thể dangling, cp sẽ lỗi "not writing through
    # dangling symlink". Xoá link trước rồi copy file thật từ host vào.
    rm -f "$WORK_DIR/squashfs/etc/resolv.conf"
    cp /etc/resolv.conf "$WORK_DIR/squashfs/etc/resolv.conf"
}

umount_chroot() {
    sync 2>/dev/null || true
    umount "$WORK_DIR/squashfs/proc"    2>/dev/null || umount -lf "$WORK_DIR/squashfs/proc"    2>/dev/null || true
    umount "$WORK_DIR/squashfs/sys"     2>/dev/null || umount -lf "$WORK_DIR/squashfs/sys"     2>/dev/null || true
    umount "$WORK_DIR/squashfs/dev/pts" 2>/dev/null || umount -lf "$WORK_DIR/squashfs/dev/pts" 2>/dev/null || true
    umount "$WORK_DIR/squashfs/dev"     2>/dev/null || umount -lf "$WORK_DIR/squashfs/dev"     2>/dev/null || true
}

safe_remove_work_dirs() {
    sync 2>/dev/null || true
    umount_chroot
    umount "$WORK_DIR/mnt" 2>/dev/null || true

    if grep -q " $WORK_DIR/squashfs/" /proc/mounts 2>/dev/null; then
        error "Vẫn còn mount trong $WORK_DIR/squashfs — bỏ qua xoá để bảo vệ host. Chạy: sudo umount -Rlf $WORK_DIR/squashfs"
    fi

    rm -rf "$WORK_DIR/squashfs" "$WORK_DIR/custom" "$WORK_DIR/mnt" 2>/dev/null || true
}

print_dev_help() {
    cat <<EOF
CaramOS Dev Build Modes:
  sudo ./build.sh --prepare        Tạo build/squashfs + build/custom, giữ để sửa nhanh
  sudo ./build.sh --boot-only      Chỉ áp dụng boot config/branding
  sudo ./build.sh --overlay-only   Chỉ copy config/includes.chroot vào rootfs
  sudo ./build.sh --customize-only Chạy apt/packages + overlay + hooks trên rootfs hiện có
  sudo ./build.sh --shell          Vào chroot build/squashfs để test/sửa thủ công
  sudo ./build.sh --repack-only    Đóng lại filesystem.squashfs + ISO, giữ work tree
  sudo ./build.sh --iso-only       Chỉ tạo lại ISO từ build/custom
  sudo ./build.sh --quick          Prepare nếu cần → overlay-only → repack-only
  sudo ./build.sh --clean-work     Xoá work tree, giữ cache
  sudo ./build.sh --clean-cache    Xoá toàn bộ build cache/work tree
EOF
}

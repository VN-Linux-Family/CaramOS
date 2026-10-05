#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

ISO="${1:-CaramOS-0.1-cinnamon-amd64.iso}"
WORK_CUSTOM="build/custom"
ROOTFS="build/squashfs"

echo "== CaramOS ISO debug =="
echo "ISO: $ISO"
echo

echo "== Host files =="
if [ -f assets/splash.png ]; then
    file assets/splash.png
    file assets/splash.png | grep -q 'PNG image data, 640 x 480' \
        || echo "WARN: assets/splash.png phải là PNG 640x480, nếu không isolinux hiện nền đen"
else
    echo "MISSING: assets/splash.png"
fi
[ -f "$ISO" ] && ls -lh "$ISO" || echo "MISSING: $ISO"
echo

echo "== Isolinux config =="
if [ -d "$WORK_CUSTOM/isolinux" ]; then
    grep -RIn "menu background\|include stdmenu\|include live\|append boot=casper" "$WORK_CUSTOM/isolinux"/*.cfg || true
    [ -f "$WORK_CUSTOM/isolinux/splash.png" ] && file "$WORK_CUSTOM/isolinux/splash.png"
else
    echo "MISSING: $WORK_CUSTOM/isolinux"
fi
echo

echo "== GRUB config =="
if [ -d "$WORK_CUSTOM/boot/grub" ]; then
    grep -RIn "menuentry\|quiet\|splash\|gfxterm\|theme" "$WORK_CUSTOM/boot/grub"/*.cfg 2>/dev/null | head -80 || true
    grep -n "desktop-" "$WORK_CUSTOM/boot/grub/live-theme/theme.txt" 2>/dev/null || true
    [ -f "$WORK_CUSTOM/boot/grub/splash.png" ] && file "$WORK_CUSTOM/boot/grub/splash.png"
else
    echo "MISSING: $WORK_CUSTOM/boot/grub"
fi
echo

echo "== Plymouth rootfs =="
if [ -d "$ROOTFS/usr/share/plymouth/themes" ]; then
    DEFAULT_LINK="$ROOTFS/usr/share/plymouth/themes/default.plymouth"
    RESOLVED=""
    if [ -L "$DEFAULT_LINK" ]; then
        TARGET="$(readlink "$DEFAULT_LINK")"
        echo "default.plymouth -> $TARGET"
        if [[ "$TARGET" = /* ]]; then
            ALT_LINK="$ROOTFS$TARGET"
        else
            ALT_LINK="$(dirname "$DEFAULT_LINK")/$TARGET"
        fi
        if [ -L "$ALT_LINK" ]; then
            ALT_TARGET="$(readlink "$ALT_LINK")"
            echo "$TARGET -> $ALT_TARGET"
            if [[ "$ALT_TARGET" = /* ]]; then
                RESOLVED="$ROOTFS$ALT_TARGET"
            else
                RESOLVED="$(dirname "$ALT_LINK")/$ALT_TARGET"
            fi
        else
            RESOLVED="$ALT_LINK"
        fi
    else
        RESOLVED="$DEFAULT_LINK"
    fi

    if [ -n "$RESOLVED" ]; then
        echo "resolved: ${RESOLVED#$ROOTFS}"
        grep -RIn "Name=\|ImageDir=" "$RESOLVED" 2>/dev/null || true
    fi
    grep -RIn "Name=\|ImageDir=" "$ROOTFS/usr/share/plymouth/themes/caramos"/*.plymouth 2>/dev/null || true
    [ -f "$ROOTFS/usr/share/plymouth/themes/caramos/watermark.png" ] && file "$ROOTFS/usr/share/plymouth/themes/caramos/watermark.png" || true
else
    echo "MISSING: plymouth themes"
fi
echo

echo "== Live initrd =="
INITRD="$WORK_CUSTOM/casper/initrd.lz"
if [ -f "$INITRD" ]; then
    ls -lh "$INITRD"
    echo "CaRamOS entries:"
    lsinitramfs "$INITRD" 2>/dev/null | grep -E 'usr/share/plymouth/themes/caramos|etc/alternatives/default.plymouth|usr/share/plymouth/themes/default.plymouth' | head -80 || true
    echo "Mint/BGRT entries:"
    lsinitramfs "$INITRD" 2>/dev/null | grep -E 'usr/share/plymouth/themes/(mint-logo|bgrt)' | head -20 || true
else
    echo "MISSING: $INITRD"
fi
echo

echo "== ISO contents =="
if [ -f "$ISO" ]; then
    xorriso -indev "$ISO" -find /isolinux -name splash.png -exec report_lba -- 2>/dev/null || true
    xorriso -indev "$ISO" -find /isolinux -name isolinux.cfg -exec cat -- 2>/dev/null | sed -n '1,20p' || true
fi

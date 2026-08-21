#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

ISO="${1:-CaramOS-0.1-cinnamon-amd64.iso}"
WORK_CUSTOM="build/custom"
ROOTFS="build/squashfs"

command_exists() {
    command -v "$1" >/dev/null 2>&1
}

echo "== CaramOS ISO debug =="
echo "ISO: $ISO"
echo

echo "== Host files =="
[ -f splash.png ] && file splash.png || echo "MISSING: splash.png"
[ -f "$ISO" ] && ls -lh "$ISO" || echo "MISSING: $ISO"
echo

echo "== Isolinux config =="
if [ -d "$WORK_CUSTOM/isolinux" ]; then
    find "$WORK_CUSTOM/isolinux" -maxdepth 1 -name "*.cfg" -exec grep -HIn "menu background\|include stdmenu\|include live\|append boot=casper" {} + 2>/dev/null || true
    [ -f "$WORK_CUSTOM/isolinux/splash.png" ] && file "$WORK_CUSTOM/isolinux/splash.png" || echo "MISSING: $WORK_CUSTOM/isolinux/splash.png"
else
    echo "MISSING: $WORK_CUSTOM/isolinux"
fi
echo

echo "== GRUB config =="
if [ -d "$WORK_CUSTOM/boot/grub" ]; then
    find "$WORK_CUSTOM/boot/grub" -maxdepth 1 -name "*.cfg" -exec grep -HIn "menuentry\|quiet\|splash" {} + 2>/dev/null | head -80 || true
else
    echo "MISSING: $WORK_CUSTOM/boot/grub"
fi
echo

echo "== Plymouth rootfs =="
PLYMOUTH_DIR="$ROOTFS/usr/share/plymouth/themes"
if [ -d "$PLYMOUTH_DIR" ]; then
    DEFAULT_LINK="$PLYMOUTH_DIR/default.plymouth"
    RESOLVED=""
    
    if [ -L "$DEFAULT_LINK" ]; then
        TARGET="$(readlink "$DEFAULT_LINK")"
        echo "default.plymouth -> $TARGET"
        
        if command_exists realpath; then
            RESOLVED="$(realpath -m "$PLYMOUTH_DIR/$TARGET" 2>/dev/null || true)"
        elif command_exists readlink; then
            RESOLVED="$(readlink -f "$DEFAULT_LINK" 2>/dev/null || true)"
        fi
    else
        RESOLVED="$DEFAULT_LINK"
    fi

    if [ -n "$RESOLVED" ] && [ -f "$RESOLVED" ]; then
        echo "resolved: ${RESOLVED#$ROOTFS}"
        grep -HIn "Name=\|ImageDir=" "$RESOLVED" 2>/dev/null || true
    else
        echo "WARNING: Cannot resolve default.plymouth"
    fi
    
    if [ -d "$PLYMOUTH_DIR/caramos" ]; then
        find "$PLYMOUTH_DIR/caramos" -maxdepth 1 -name "*.plymouth" -exec grep -HIn "Name=\|ImageDir=" {} + 2>/dev/null || true
        [ -f "$PLYMOUTH_DIR/caramos/watermark.png" ] && file "$PLYMOUTH_DIR/caramos/watermark.png" || echo "MISSING: watermark.png"
    else
        echo "MISSING: $PLYMOUTH_DIR/caramos"
    fi
else
    echo "MISSING: plymouth themes"
fi
echo

echo "== Live initrd =="
INITRD="$WORK_CUSTOM/casper/initrd.lz"
if [ -f "$INITRD" ]; then
    ls -lh "$INITRD"
    
    if command_exists lsinitramfs; then
        echo "CaramOS entries:"
        lsinitramfs "$INITRD" 2>/dev/null | grep -E 'usr/share/plymouth/themes/caramos|etc/alternatives/default.plymouth|usr/share/plymouth/themes/default.plymouth' | head -80 || true
        echo "Mint/BGRT entries:"
        lsinitramfs "$INITRD" 2>/dev/null | grep -E 'usr/share/plymouth/themes/(mint-logo|bgrt)' | head -20 || true
    else
        echo "WARNING: lsinitramfs not found, skipping initrd check"
        echo "Install with: sudo apt-get install initramfs-tools"
    fi
else
    echo "MISSING: $INITRD"
fi
echo

echo "== ISO contents =="
if [ -f "$ISO" ]; then
    if command_exists xorriso; then
        xorriso -indev "$ISO" -find /isolinux -name splash.png -exec report_lba -- 2>/dev/null || true
        xorriso -indev "$ISO" -find /isolinux -name isolinux.cfg -exec cat -- 2>/dev/null | sed -n '1,20p' || true
    else
        echo "WARNING: xorriso not found, cannot inspect ISO contents"
        echo "Install with: sudo apt-get install xorriso"
    fi
fi

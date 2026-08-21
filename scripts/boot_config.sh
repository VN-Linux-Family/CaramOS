#!/bin/bash
# Bootloader + plymouth configuration by build mode:
#   - Branding (Linux Mint → CaramOS): ALWAYS applied, both dev and release
#   - Dev/Release mode keeps quiet + splash by default for Plymouth loading screen
#   - Debug boot mode (--debug-boot) removes quiet/splash from kernel cmdline
#
# Run AFTER step_extract, BEFORE step_customize.

step_boot_config() {
    local ISO_DIR="$WORK_DIR/custom"

    local IS_DEBUG=false
    [ "${DEBUG_BOOT:-0}" = "1" ] && IS_DEBUG=true

    if $IS_DEBUG; then
        info "[2.5/7] Configuring debug boot (no quiet/splash)..."
    else
        info "[2.5/7] Configuring beautiful boot (branding + Plymouth)..."
    fi

    local BRAND_NAME="CaramOS"
    local BRAND_VERSION="${CARAMOS_VERSION:-0.1}"
    local BRAND_TITLE="${BRAND_NAME} ${BRAND_VERSION} ${MINT_EDITION^} 64-bit"
    local LIVE_USER="caram"
    local LIVE_HOST="caram"
    local LIVE_LOCALE="vi_VN.UTF-8"

    local ISOLINUX_FILES
    ISOLINUX_FILES=$(find "$ISO_DIR" \
        -path "*/isolinux/*.cfg" -o \
        -path "*/syslinux/*.cfg" \
        2>/dev/null)

    if [ -n "$ISOLINUX_FILES" ]; then
        info "  → Fixing isolinux/syslinux config..."
        echo "$ISOLINUX_FILES" | while IFS= read -r cfg; do
            sed -i \
                -e "s/Welcome to Linux Mint [0-9.]* 64-bit/Welcome to ${BRAND_NAME} ${BRAND_VERSION} 64-bit/gI" \
                -e "s/Start Linux Mint in compatibility mode/Start ${BRAND_NAME} in compatibility mode/gI" \
                -e "s/Start Linux Mint/Start ${BRAND_NAME}/gI" \
                -e "s/Linux Mint [0-9.]* Cinnamon 64-bit/${BRAND_TITLE}/gI" \
                -e "s/Linux Mint/${BRAND_NAME}/gI" \
                -e "s/username=mint/username=${LIVE_USER}/gI" \
                -e "s/hostname=mint/hostname=${LIVE_HOST}/gI" \
                -e "s/locale=[^[:space:]]*//gI" \
                -e "s/boot=casper/boot=casper locale=${LIVE_LOCALE}/gI" \
                "$cfg"

            if $IS_DEBUG; then
                sed -i '/^[[:space:]]*APPEND/s/\bquiet\b//g; /^[[:space:]]*APPEND/s/\bsplash\b//g; /^[[:space:]]*append/s/\bquiet\b//g; /^[[:space:]]*append/s/\bsplash\b//g' "$cfg"
            else
                sed -i '/^[[:space:]]*append[[:space:]].*boot=casper/ {
                    /nomodeset/! {
                        s/\bquiet\b//g
                        s/\bsplash\b//g
                        s/[[:space:]]\+/ /g
                        s/[[:space:]]*--/ quiet splash --/
                    }
                }' "$cfg"
                sed -i '/^[[:space:]]*APPEND[[:space:]].*boot=casper/ {
                    /nomodeset/! {
                        s/\bquiet\b//g
                        s/\bsplash\b//g
                        s/[[:space:]]\+/ /g
                        s/[[:space:]]*--/ quiet splash --/
                    }
                }' "$cfg"
            fi

            ok "    Fixed: $(basename "$cfg")"
        done
    else
        warn "  → No isolinux/syslinux config found, skipping."
    fi

    local GRUB_FILES
    GRUB_FILES=$(find "$ISO_DIR" \
        -path "*/grub/*.cfg" -o \
        -path "*/EFI/boot/*.cfg" \
        2>/dev/null)

    if [ -n "$GRUB_FILES" ]; then
        info "  → Fixing GRUB config..."

        local GRUB_SPLASH="$SCRIPT_DIR/assets/boot-splash.png"
        if [ -f "$GRUB_SPLASH" ]; then
            mkdir -p "$ISO_DIR/boot/grub" 2>/dev/null || true
            cp "$GRUB_SPLASH" "$ISO_DIR/boot/grub/splash.png" 2>/dev/null || true
        fi

        echo "$GRUB_FILES" | while IFS= read -r cfg; do
            sed -i \
                -e "s/Start Linux Mint [0-9.]* Cinnamon 64-bit/Start ${BRAND_TITLE}/gI" \
                -e "s/Start Linux Mint/Start ${BRAND_NAME}/gI" \
                -e "s/Linux Mint [0-9.]* Cinnamon 64-bit/${BRAND_TITLE}/gI" \
                -e "s/Linux Mint/${BRAND_NAME}/gI" \
                -e "s/username=mint/username=${LIVE_USER}/gI" \
                -e "s/hostname=mint/hostname=${LIVE_HOST}/gI" \
                -e "s/locale=[^[:space:]]*//gI" \
                -e "s/boot=casper/boot=casper locale=${LIVE_LOCALE}/gI" \
                "$cfg"

            if [ -f "$ISO_DIR/boot/grub/splash.png" ] && ! grep -q "background_image" "$cfg"; then
                if basename "$cfg" | grep -qi "^grub.cfg$"; then
                    sed -i '1 a\insmod all_video\ninsmod gfxterm\ninsmod png\nset background_image=/boot/grub/splash.png' "$cfg"
                fi
            fi

            if $IS_DEBUG; then
                sed -i '/^[[:space:]]*linux/s/\bquiet\b//g; /^[[:space:]]*linux/s/\bsplash\b//g' "$cfg"
            fi

            ok "    Fixed: $(basename "$cfg")"
        done
    else
        warn "  → No GRUB config found, skipping."
    fi

    local BANNER_SRC="$SCRIPT_DIR/splash.png"
    if [ ! -f "$BANNER_SRC" ]; then
        BANNER_SRC="$SCRIPT_DIR/assets/boot-splash.png"
    fi
    local ISOLINUX_DIR
    ISOLINUX_DIR=$(find "$ISO_DIR" -maxdepth 3 -name "isolinux.bin" \
        -exec dirname {} \; 2>/dev/null | head -1)

    if [ ! -f "$BANNER_SRC" ]; then
        warn "  → splash.png/assets/boot-splash.png not found, skipping boot menu background."
    elif [ -z "$ISOLINUX_DIR" ]; then
        warn "  → isolinux directory not found, skipping splash."
    else
        info "  → Setting syslinux splash background..."

        cp "$BANNER_SRC" "$ISOLINUX_DIR/splash.png"
        ok "    Copied: splash.png → $ISOLINUX_DIR/"

        find "$ISOLINUX_DIR" -name "*.cfg" -type f -print0 | \
            xargs -0 sed -i '/^[[:space:]]*menu[[:space:]]\+background[[:space:]]/Id'

        local INSERT_CFG="$ISOLINUX_DIR/stdmenu.cfg"
        [ ! -f "$INSERT_CFG" ] && INSERT_CFG="$ISOLINUX_DIR/isolinux.cfg"

        if [ -f "$INSERT_CFG" ]; then
            sed -i '1i menu background splash.png' "$INSERT_CFG"
            ok "    Set MENU BACKGROUND in: $(basename "$INSERT_CFG")"
        else
            warn "    No suitable cfg found to add MENU BACKGROUND."
        fi

        local MAIN_CFG="$ISOLINUX_DIR/isolinux.cfg"
        if [ -f "$MAIN_CFG" ]; then
            if ! grep -qiE '^[[:space:]]*include[[:space:]]+stdmenu\.cfg' "$MAIN_CFG"; then
                sed -i '/^[[:space:]]*include[[:space:]]\+live\.cfg/i include stdmenu.cfg' "$MAIN_CFG"
                ok "    Included stdmenu.cfg in: isolinux.cfg"
            fi
            if ! grep -qiE '^[[:space:]]*menu[[:space:]]+background[[:space:]]+splash\.png' "$MAIN_CFG"; then
                sed -i '1i menu background splash.png' "$MAIN_CFG"
                ok "    Set MENU BACKGROUND directly in: isolinux.cfg"
            fi
        fi
    fi

    info "  → Keeping Plymouth for CaramOS loading screen."
    ok "[2.5/7] Boot config complete."
}

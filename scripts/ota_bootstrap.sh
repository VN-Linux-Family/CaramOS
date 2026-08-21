#!/bin/bash
# Build/install bundled CaramOS OTA inside the ISO rootfs and run migrations.

build_caramos_ota_deb() {
    local ota_dir="$SCRIPT_DIR/packages/caramos-ota"
    local dist_dir="$ota_dir/dist-testkit"

    if [ ! -x "$ota_dir/tools/caramos-ota-testkit.sh" ]; then
        error "OTA testkit not found: $ota_dir/tools/caramos-ota-testkit.sh"
    fi

    info "  → Building caramos-ota package for ISO embedding..." >&2
    if ! (cd "$ota_dir" && ./tools/caramos-ota-testkit.sh build-deb) >&2; then
        error "Failed to build caramos-ota .deb. Install build deps and retry: sudo apt install build-essential debhelper"
    fi

    if [ ! -d "$dist_dir" ]; then
        error "Build output directory not found: $dist_dir"
    fi

    local deb
    deb="$(find "$dist_dir" -maxdepth 1 -type f -name 'caramos-ota_*.deb' -print0 | sort -z | tail -z -n 1 | tr -d '\0')"
    if [ -z "$deb" ] || [ ! -f "$deb" ]; then
        error "Failed to build caramos-ota .deb: no file found in $dist_dir"
    fi

    printf '%s\n' "$deb"
}

packaged_caramos_product_version() {
    local pythonpath="$SCRIPT_DIR/packages/caramos-ota/usr/lib/python3/dist-packages"
    
    if [ ! -d "$pythonpath/caramos_ota" ]; then
        error "caramos_ota Python module not found at: $pythonpath"
    fi
    
    PYTHONPATH="$pythonpath" python3 - <<'PY'
from caramos_ota.release_metadata import PRODUCT_VERSION

print(PRODUCT_VERSION)
PY
}

install_caramos_ota_and_run_migrations() {
    local deb="$1"
    local target_version
    local from_version
    target_version="$(packaged_caramos_product_version)"
    from_version="${CARAMOS_MIGRATION_BASE_VERSION:-1.0.1}"

    # Validate version format
    if ! [[ "$target_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        error "Invalid target version format: $target_version"
    fi
    if ! [[ "$from_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        error "Invalid source version format: $from_version"
    fi

    info "  → Installing caramos-ota into ISO rootfs..."
    cp "$deb" "$WORK_DIR/squashfs/tmp/caramos-ota-local.deb"
    
    if ! chroot "$WORK_DIR/squashfs" /bin/bash -c '
        set -e
        export DEBIAN_FRONTEND=noninteractive
        APT_LOCK_TIMEOUT="${APT_LOCK_TIMEOUT:-600}"
        apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT" install -y /tmp/caramos-ota-local.deb
        rm -f /tmp/caramos-ota-local.deb
        command -v caramos-ota >/dev/null
        command -v caramos-ota-notifier >/dev/null
        command -v caramos-ota-update >/dev/null
    '; then
        rm -f "$WORK_DIR/squashfs/tmp/caramos-ota-local.deb" 2>/dev/null || true
        error "Failed to install caramos-ota in chroot"
    fi
    
    ok "caramos-ota installed into ISO rootfs."

    info "  → Running OTA migrations in ISO rootfs: $from_version -> $target_version"
    if ! CARAMOS_VERSION="$from_version" TARGET_VERSION="$target_version" \
    chroot "$WORK_DIR/squashfs" /bin/bash -c '
        set -e
        caramos-ota-update --from "$CARAMOS_VERSION" --target "$TARGET_VERSION" --dry-run
        caramos-ota-update --from "$CARAMOS_VERSION" --target "$TARGET_VERSION"
    '; then
        error "OTA migrations failed in chroot"
    fi
    
    ok "OTA migrations completed in ISO rootfs to version $target_version."
}

step_ota_bootstrap() {
    local deb
    deb="$(build_caramos_ota_deb)"
    install_caramos_ota_and_run_migrations "$deb"
}

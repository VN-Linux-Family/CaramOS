#!/bin/bash
# Build/install bundled CaramOS OTA inside the ISO rootfs and run migrations.

build_caramos_ota_deb() {
    local ota_dir="$SCRIPT_DIR/packages/caramos-ota"
    local dist_dir="$ota_dir/dist-testkit"

    if [ ! -x "$ota_dir/tools/caramos-ota-testkit.sh" ]; then
        error "Không tìm thấy OTA testkit: $ota_dir/tools/caramos-ota-testkit.sh"
    fi

    info "  → Build package caramos-ota để nhúng vào ISO..."
    (cd "$ota_dir" && ./tools/caramos-ota-testkit.sh build-deb)

    local deb
    deb="$(find "$dist_dir" -maxdepth 1 -type f -name 'caramos-ota_*.deb' | sort | tail -n 1)"
    if [ -z "$deb" ] || [ ! -f "$deb" ]; then
        error "Build caramos-ota .deb thất bại: không tìm thấy file trong $dist_dir"
    fi

    printf '%s\n' "$deb"
}

latest_caramos_ota_migration() {
    python3 - <<'PY'
import json
from pathlib import Path

path = Path("packages/caramos-ota/usr/lib/python3/dist-packages/caramos_ota_update/migrations/migration.json")
data = json.loads(path.read_text(encoding="utf-8"))
versions = data.get("versions")
if not isinstance(versions, list) or not versions:
    raise SystemExit("migration.json không có versions hợp lệ")
print(versions[-1])
PY
}

install_caramos_ota_and_run_migrations() {
    local deb="$1"
    local target_version
    local from_version
    target_version="$(latest_caramos_ota_migration)"
    from_version="${CARAMOS_MIGRATION_BASE_VERSION:-$CARAMOS_VERSION}"

    info "  → Cài caramos-ota vào ISO rootfs..."
    cp "$deb" "$WORK_DIR/squashfs/tmp/caramos-ota-local.deb"
    chroot "$WORK_DIR/squashfs" /bin/bash -c '
        set -e
        export DEBIAN_FRONTEND=noninteractive
        APT_LOCK_TIMEOUT="${APT_LOCK_TIMEOUT:-600}"
        apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT" install -y /tmp/caramos-ota-local.deb
        rm -f /tmp/caramos-ota-local.deb
        command -v caramos-ota
        command -v caramos-ota-notifier
        command -v caramos-ota-update
    '
    ok "Đã cài caramos-ota vào ISO rootfs."

    if [ "$target_version" = "$from_version" ]; then
        info "  → ISO đã ở target OTA $target_version, bỏ qua migration."
        return 0
    fi

    info "  → Chạy OTA migrations trong ISO rootfs: $from_version -> $target_version"
    CARAMOS_VERSION="$from_version" TARGET_VERSION="$target_version" \
    chroot "$WORK_DIR/squashfs" /bin/bash -c '
        set -e
        caramos-ota-update --from "$CARAMOS_VERSION" --target "$TARGET_VERSION" --dry-run
        caramos-ota-update --from "$CARAMOS_VERSION" --target "$TARGET_VERSION"
    '
    ok "OTA migrations đã chạy xong trong ISO rootfs tới $target_version."
}

step_ota_bootstrap() {
    local deb
    deb="$(build_caramos_ota_deb | tail -n 1)"
    install_caramos_ota_and_run_migrations "$deb"
}

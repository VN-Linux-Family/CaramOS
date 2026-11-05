#!/bin/bash
# Build/install bundled CaramOS OTA inside the ISO rootfs and run migrations.

build_caramos_ota_deb() {
    local ota_dir="$SCRIPT_DIR/packages/caramos-ota"
    local dist_dir="$ota_dir/dist-testkit"

    if [ ! -x "$ota_dir/tools/caramos-ota-testkit.sh" ]; then
        error "Không tìm thấy OTA testkit: $ota_dir/tools/caramos-ota-testkit.sh"
    fi

    info "  → Build package caramos-ota để nhúng vào ISO..." >&2
    if ! (cd "$ota_dir" && ./tools/caramos-ota-testkit.sh build-deb) >&2; then
        error "Build caramos-ota .deb thất bại. Cài build deps rồi chạy lại: sudo apt install build-essential debhelper"
    fi

    local deb
    deb="$(find "$dist_dir" -maxdepth 1 -type f -name 'caramos-ota_*.deb' | sort | tail -n 1)"
    if [ -z "$deb" ] || [ ! -f "$deb" ]; then
        error "Build caramos-ota .deb thất bại: không tìm thấy file trong $dist_dir"
    fi

    printf '%s\n' "$deb"
}

build_caramos_app_center_deb() {
    local app_dir="$SCRIPT_DIR/packages/caramos-app-center"

    # Repo riêng VN-Linux-Family/CaramOS-app-center, gắn vào đây bằng git submodule.
    if [ ! -f "$app_dir/Makefile" ]; then
        error "Thiếu App Center ($app_dir). Chạy: git submodule update --init packages/caramos-app-center"
    fi

    info "  → Build package caramos-app-center để nhúng vào ISO..." >&2
    if ! make -C "$app_dir" build >&2; then
        error "Build caramos-app-center .deb thất bại. Cài build deps rồi chạy lại: sudo apt install build-essential debhelper gettext"
    fi

    local deb
    deb="$(find "$app_dir/dist" -maxdepth 1 -type f -name 'caramos-app-center_*.deb' | sort | tail -n 1)"
    if [ -z "$deb" ] || [ ! -f "$deb" ]; then
        error "Build caramos-app-center .deb thất bại: không tìm thấy file trong $app_dir/dist"
    fi

    printf '%s\n' "$deb"
}

packaged_caramos_product_version() {
    PYTHONPATH="packages/caramos-ota/usr/lib/python3/dist-packages" python3 - <<'PY'
from caramos_ota.release_metadata import PRODUCT_VERSION

print(PRODUCT_VERSION)
PY
}

install_caramos_ota_and_run_migrations() {
    local deb="$1"
    local app_center_deb="$2"
    local target_version
    local from_version
    target_version="$(packaged_caramos_product_version)"
    from_version="${CARAMOS_MIGRATION_BASE_VERSION:-1.0.1}"

    # Cài hai gói cùng lúc để Recommends: caramos-app-center của caramos-ota dùng bản vừa build, không lấy từ PPA.
    info "  → Cài caramos-ota và caramos-app-center vào ISO rootfs..."
    cp "$deb" "$WORK_DIR/squashfs/tmp/caramos-ota-local.deb"
    cp "$app_center_deb" "$WORK_DIR/squashfs/tmp/caramos-app-center-local.deb"
    chroot "$WORK_DIR/squashfs" /bin/bash -c '
        set -e
        export DEBIAN_FRONTEND=noninteractive
        APT_LOCK_TIMEOUT="${APT_LOCK_TIMEOUT:-600}"
        apt-get -o DPkg::Lock::Timeout="$APT_LOCK_TIMEOUT" install -y /tmp/caramos-ota-local.deb /tmp/caramos-app-center-local.deb
        rm -f /tmp/caramos-ota-local.deb /tmp/caramos-app-center-local.deb
        command -v caramos-ota
        command -v caramos-ota-notifier
        command -v caramos-ota-update
        command -v caramos-app-center
    '
    ok "Đã cài caramos-ota và caramos-app-center vào ISO rootfs."

    # Always invoke updater: same-release timestamp migrations may still be pending.
    info "  → Chạy OTA migrations trong ISO rootfs: $from_version -> $target_version"
    CARAMOS_VERSION="$from_version" TARGET_VERSION="$target_version" \
    chroot "$WORK_DIR/squashfs" /bin/bash -c '
        set -e
        caramos-ota-update --from "$CARAMOS_VERSION" --target "$TARGET_VERSION" --dry-run
        caramos-ota-update --from "$CARAMOS_VERSION" --target "$TARGET_VERSION"
    '
    ok "OTA migrations đã chạy xong trong ISO rootfs tới $target_version."
}

# Hook 0170 tải Cinnamenu từ nhánh master của cinnamon-spices lúc build. Các bản vá Start Menu là migration, và
# migration để nguyên một Cinnamenu nó không nhận ra (đúng như phải làm trên máy người dùng), nên một Cinnamenu
# mới của upstream sẽ vào ISO mà không có bản vá. Dừng build thay vì phát hành Start Menu thiếu bản vá.
verify_start_menu_fixes() {
    local applet_dir="$WORK_DIR/squashfs/usr/share/cinnamon/applets/Cinnamenu@json"
    local cinnamon_version
    [ -d "$applet_dir" ] || return 0
    cinnamon_version="$(chroot "$WORK_DIR/squashfs" dpkg-query -W -f='${Version}' cinnamon 2>/dev/null || true)"
    info "  → Kiểm tra bản vá Start Menu (Cinnamenu) trong ISO rootfs..."
    if ! PYTHONPATH="$SCRIPT_DIR/packages/caramos-ota/usr/lib/python3/dist-packages" \
        python3 - "$applet_dir" "$cinnamon_version" <<'PY'
import importlib
import json
import re
import sys
from pathlib import Path

root, cinnamon = Path(sys.argv[1]), sys.argv[2]
FIXES = {
    "20261105120100_search_menu_while_composing": "search while an input method composes a word",
    "20261105120200_start_menu_file_search_without_freeze": "file search without freezing the desktop",
}


def version(text):
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])


# The folder Cinnamon loads for a multiversion applet: the highest version folder not newer than Cinnamon.
loaded = root
metadata = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
if metadata.get("multiversion"):
    folders = [path for path in root.iterdir()
               if path.is_dir() and re.fullmatch(r"[1-9]\d*\.\d+(\.\d+)?", path.name)
               and (not cinnamon or version(path.name) <= version(cinnamon))]
    if folders:
        loaded = max(folders, key=lambda path: version(path.name))
applet_path = loaded / "applet.js"
applet = applet_path.read_text(encoding="utf-8") if applet_path.is_file() else ""
missing = [f"{migration_id} ({what})" for migration_id, what in FIXES.items()
           if importlib.import_module(f"caramos_ota_update.migrations.{migration_id}.migration").MARKER not in applet]
if missing:
    print(f"{applet_path} (Cinnamon {cinnamon or '?'}) lacks: " + "; ".join(missing))
    sys.exit(1)
print(f"{applet_path} (Cinnamon {cinnamon or '?'}) has the CaramOS Start Menu fixes")
PY
    then
        error "Cinnamenu tải về không nhận bản vá Start Menu của CaramOS. Sửa hai migration trên cho bản Cinnamenu mới, hoặc ghim hook 0170 vào commit cinnamon-spices đã test."
    fi
    ok "Start Menu có đủ bản vá của CaramOS."
}

step_ota_bootstrap() {
    local deb app_center_deb
    deb="$(build_caramos_ota_deb)"
    app_center_deb="$(build_caramos_app_center_deb)"
    install_caramos_ota_and_run_migrations "$deb" "$app_center_deb"
    verify_start_menu_fixes
}

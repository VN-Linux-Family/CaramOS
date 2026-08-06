#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_DIR="$(cd "${PKG_DIR}/../.." && pwd)"
DIST_DIR="${PKG_DIR}/dist-testkit"
BUNDLE_NAME="caramos-ota-source-testkit.tar.gz"
BACKUP_DIR="/root/caramos-ota-test-backup"
TEST_RELEASE_FROM="${TEST_RELEASE_FROM:-1.0.12}"
if [[ -z "${TEST_RELEASE_TARGET:-}" ]]; then
  TEST_RELEASE_TARGET="$(PYTHONPATH="${PKG_DIR}/usr/lib/python3/dist-packages" python3 -c 'from caramos_ota.release_metadata import PRODUCT_VERSION; print(PRODUCT_VERSION)')"
fi

usage() {
  cat <<'EOF'
CaramOS OTA Test Toolkit

Usage:
  ./tools/caramos-ota-testkit.sh <command>

Commands on dev machine:
  clean-build      Remove local Debian build artifacts and Python cache
  compile          Compile all OTA Python files
  validate         Auto-discover and validate all bundled migrations
  test             Run OTA unit tests
  build-deb        Clean + validate + build caramos-ota binary .deb
  release-deb      Alias for build-deb
  build-source     Clean + validate + build source package for PPA upload
  bundle-source    Create dist-testkit/caramOS OTA source tarball for quick VM copy
  dist             Run compile + bundle-source

Commands on CaramOS test machine:
  install-deb <deb> Install built caramos-ota .deb
  backup            Backup files touched by migration tests
  smoke             Check installed commands and compile installed modules
  dry-run-target    Dry-run pending migrations to TEST_RELEASE_TARGET
  run-target        Run pending migrations to TEST_RELEASE_TARGET
  verify-target     Verify VERSION metadata and selected branding changes
  restore           Restore backup made by backup command

  # Dev machine
  ./tools/caramos-ota-testkit.sh release-deb
  sudo ./tools/ship-ota-to-vm.sh

  # PPA source upload build
  ./tools/caramos-ota-testkit.sh build-source
  dput ppa:vietnamlinuxfamily/caram-os ../caramos-ota_<version>_source.changes

  # CaramOS VM
  cd /tmp && tar -xzf caramos-ota-source-testkit.tar.gz
  cd caramos-ota
  sudo ./tools/caramos-ota-testkit.sh backup
  sudo TEST_RELEASE_FROM=1.0.16 TEST_RELEASE_TARGET=1.0.17 ./tools/caramos-ota-testkit.sh dry-run-target
  sudo TEST_RELEASE_FROM=1.0.16 TEST_RELEASE_TARGET=1.0.17 ./tools/caramos-ota-testkit.sh run-target
  sudo TEST_RELEASE_TARGET=1.0.17 ./tools/caramos-ota-testkit.sh verify-target
EOF
}

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    echo "Error: this command must run as root/sudo." >&2
    exit 2
  fi
}

compile_sources() {
  cd "${PKG_DIR}"
  local pycache_prefix
  pycache_prefix="$(mktemp -d)"
  trap 'rm -rf "${pycache_prefix}"' RETURN
  PYTHONPYCACHEPREFIX="${pycache_prefix}" python3 -m py_compile \
    usr/bin/caramos-ota \
    usr/bin/caramos-ota-audit \
    usr/bin/caramos-ota-notifier \
    usr/bin/caramos-ota-update \
    $(find usr/lib/python3/dist-packages -name '*.py' | sort)
  rm -rf "${pycache_prefix}"
  trap - RETURN
  echo "[OK] Python compile passed"
}

clean_build() {
  cd "${PKG_DIR}"
  rm -rf \
    debian/.debhelper \
    debian/caramos-ota \
    debian/debhelper-build-stamp \
    debian/files
  find debian -maxdepth 1 \( -name '*.substvars' -o -name '*.debhelper.log' \) -delete
  find usr/lib/python3/dist-packages -name __pycache__ -type d -prune -exec rm -rf {} +
  find usr/lib/python3/dist-packages -name '*.pyc' -delete
  rm -f "${PKG_DIR}/../caramos-ota_"*.buildinfo \
        "${PKG_DIR}/../caramos-ota_"*.changes \
        "${PKG_DIR}/../caramos-ota_"*.deb \
        "${PKG_DIR}/../caramos-ota_"*.dsc \
        "${PKG_DIR}/../caramos-ota_"*.tar.* 2>/dev/null || true
  echo "[OK] Cleaned local build artifacts"
}

validate_manifest() {
  cd "${PKG_DIR}"
  PYTHONPATH=usr/lib/python3/dist-packages python3 - <<'PY'
from caramos_ota.release_metadata import PRODUCT_VERSION
from caramos_ota_update.registry import discover_migrations

migrations = discover_migrations()
timestamps = [migration for migration in migrations if not migration.legacy]
legacy = [migration for migration in migrations if migration.legacy]
print(
    f"[OK] Discovered {len(migrations)} migration(s): "
    f"{len(legacy)} legacy, {len(timestamps)} timestamp; product target: {PRODUCT_VERSION}"
)
for migration in migrations:
    kind = f"legacy {migration.release}" if migration.legacy else "timestamp (ledger ordered)"
    print(f"  {migration.migration_id}: {kind}")
PY
}

run_tests() {
  cd "${PKG_DIR}"
  PYTHONPATH=usr/lib/python3/dist-packages python3 -m unittest discover -s tests -v
}

build_deb() {
  clean_build
  compile_sources
  validate_manifest
  cd "${PKG_DIR}"
  dpkg-buildpackage -us -uc -b
  mkdir -p "${DIST_DIR}"
  rm -f "${DIST_DIR}"/caramos-ota_*.deb
  find "${PKG_DIR}/.." -maxdepth 1 -type f -name 'caramos-ota_*.deb' -exec cp -f {} "${DIST_DIR}/" \;
  echo "[OK] Built deb(s):"
  find "${DIST_DIR}" -maxdepth 1 -type f -name 'caramos-ota_*.deb' -print
}

build_source() {
  clean_build
  compile_sources
  validate_manifest
  cd "${PKG_DIR}"
  dpkg-buildpackage -S -sa -us -uc
  echo "[OK] Built source upload files:"
  find "${PKG_DIR}/.." -maxdepth 1 -type f \( -name 'caramos-ota_*.dsc' -o -name 'caramos-ota_*_source.changes' -o -name 'caramos-ota_*.tar.*' \) -print | sort
}

bundle_source() {
  compile_sources
  mkdir -p "${DIST_DIR}"
  rm -f "${DIST_DIR}/${BUNDLE_NAME}"
  tar \
    --exclude='./dist-testkit' \
    --exclude='./**/__pycache__' \
    --exclude='./**/*.pyc' \
    -C "${PKG_DIR}/.." \
    -czf "${DIST_DIR}/${BUNDLE_NAME}" \
    caramos-ota
  echo "[OK] Source bundle: ${DIST_DIR}/${BUNDLE_NAME}"
}

install_deb() {
  require_root
  local deb="${1:-}"
  if [[ -z "${deb}" || ! -f "${deb}" ]]; then
    echo "Error: provide path to caramos-ota .deb" >&2
    exit 1
  fi
  apt install -y "${deb}"
  echo "[OK] Installed ${deb}"
}

backup_system() {
  require_root
  mkdir -p "${BACKUP_DIR}"
  cp -a /etc/caramos-release "${BACKUP_DIR}/caramos-release" 2>/dev/null || true
  cp -a /etc/xdg/autostart/mintWelcome.desktop "${BACKUP_DIR}/mintWelcome.desktop" 2>/dev/null || true
  tar -C / -czf "${BACKUP_DIR}/linuxmint-share-lib.tgz" usr/share/linuxmint usr/lib/linuxmint 2>/dev/null || true
  echo "[OK] Backup saved to ${BACKUP_DIR}"
}

restore_system() {
  require_root
  if [[ ! -d "${BACKUP_DIR}" ]]; then
    echo "Error: backup directory not found: ${BACKUP_DIR}" >&2
    exit 1
  fi
  cp -a "${BACKUP_DIR}/caramos-release" /etc/caramos-release 2>/dev/null || true
  cp -a "${BACKUP_DIR}/mintWelcome.desktop" /etc/xdg/autostart/mintWelcome.desktop 2>/dev/null || true
  if [[ -f "${BACKUP_DIR}/linuxmint-share-lib.tgz" ]]; then
    tar -C / -xzf "${BACKUP_DIR}/linuxmint-share-lib.tgz"
  fi
  echo "[OK] Backup restored"
}

smoke_installed() {
  command -v caramos-ota
  command -v caramos-ota-audit
  command -v caramos-ota-notifier
  command -v caramos-ota-update
  python3 -m py_compile \
    /usr/bin/caramos-ota \
    /usr/bin/caramos-ota-audit \
    /usr/bin/caramos-ota-notifier \
    /usr/bin/caramos-ota-update \
    $(find /usr/lib/python3/dist-packages/caramos_ota /usr/lib/python3/dist-packages/caramos_ota_audit /usr/lib/python3/dist-packages/caramos_ota_notifier /usr/lib/python3/dist-packages/caramos_ota_update -name '*.py' 2>/dev/null | sort)
  echo "[OK] Installed smoke test passed"
}

dry_run_target() {
  if command -v caramos-ota-update >/dev/null 2>&1; then
    caramos-ota-update --from "${TEST_RELEASE_FROM}" --target "${TEST_RELEASE_TARGET}" --dry-run
  else
    cd "${PKG_DIR}"
    PYTHONPATH=usr/lib/python3/dist-packages ./usr/bin/caramos-ota-update --from "${TEST_RELEASE_FROM}" --target "${TEST_RELEASE_TARGET}" --dry-run
  fi
}

run_target() {
  require_root
  if command -v caramos-ota-update >/dev/null 2>&1; then
    caramos-ota-update --from "${TEST_RELEASE_FROM}" --target "${TEST_RELEASE_TARGET}"
  else
    cd "${PKG_DIR}"
    PYTHONPATH=usr/lib/python3/dist-packages ./usr/bin/caramos-ota-update --from "${TEST_RELEASE_FROM}" --target "${TEST_RELEASE_TARGET}"
  fi
}

verify_1_0_2() {
  echo "== version metadata =="
  grep '^VERSION=' /etc/caramos-release || true
  grep -E '^(VERSION|VERSION_ID|PRETTY_NAME)=' /etc/os-release || true
  grep '^DISTRIB_RELEASE=' /etc/lsb-release || true
  grep -E '^(RELEASE|DESCRIPTION|GRUB_TITLE)=' /etc/linuxmint/info || true
  cat /etc/issue 2>/dev/null || true
  cat /etc/issue.net 2>/dev/null || true
  echo
  echo "== mintWelcome Exec =="
  grep '^Exec=' /etc/xdg/autostart/mintWelcome.desktop 2>/dev/null || true
  echo
  echo "== Remaining Linux Mint strings sample =="
  grep -RIn "Linux Mint" /usr/share/linuxmint /usr/lib/linuxmint \
    --include='*.py' \
    --include='*.desktop' \
    --include='*.json' \
    --include='*.xml' \
    --include='*.ui' 2>/dev/null | head -50 || true
}

cmd="${1:-}"
shift || true
case "${cmd}" in
  clean-build) clean_build ;;
  compile) compile_sources ;;
  validate) validate_manifest ;;
  test) run_tests ;;
  build-deb|release-deb) build_deb ;;
  build-source) build_source ;;
  bundle-source) bundle_source ;;
  dist) compile_sources; bundle_source ;;
  install-deb) install_deb "${1:-}" ;;
  backup) backup_system ;;
  smoke) smoke_installed ;;
  dry-run-target) dry_run_target ;;
  run-target) run_target ;;
  verify-target) verify_1_0_2 ;;
  restore) restore_system ;;
  -h|--help|help|"") usage ;;
  *) echo "Unknown command: ${cmd}" >&2; usage; exit 1 ;;
esac

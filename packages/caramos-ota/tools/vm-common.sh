#!/usr/bin/env bash
# Shared host-side helpers for talking to the CaramOS OTA test VM.
# Sourced by tools/vm-dev.sh and tools/ship-ota-to-vm.sh; not meant to be run directly.

VM_COMMON_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VM_PKG_DIR="$(cd "${VM_COMMON_DIR}/.." && pwd)"

# Per-developer overrides live in vm.local.env (git-ignored, KEY=value lines).
# Values already present in the environment win over the file.
vm_load_local_config() {
  local file="${VM_PKG_DIR}/vm.local.env" line key
  [[ -f "${file}" ]] || return 0
  while IFS= read -r line || [[ -n "${line}" ]]; do
    [[ "${line}" =~ ^[[:space:]]*([A-Za-z_][A-Za-z0-9_]*)[[:space:]]*=[[:space:]]*(.*)$ ]] || continue
    key="${BASH_REMATCH[1]}"
    [[ -n "${!key+x}" ]] || export "${key}=${BASH_REMATCH[2]}"
  done < "${file}"
}
vm_load_local_config

VIRSH_URI="${VIRSH_URI:-qemu:///system}"
BASE="${BASE:-1.0.16}"
VM_DOMAIN="${VM_DOMAIN:-caram${BASE}}"
VM_SNAPSHOT="${VM_SNAPSHOT:-clean}"
REMOTE_USER="${REMOTE_USER:-caram}"
# Empty REMOTE_HOST means "ask libvirt for the IP of VM_DOMAIN".
REMOTE_HOST="${REMOTE_HOST:-}"
REMOTE_PORT="${REMOTE_PORT:-22}"
# Only needed before `vm-dev.sh setup` has installed the SSH key (or for a throwaway live-boot VM).
REMOTE_PASSWORD="${REMOTE_PASSWORD:-}"

# The test VM is disposable and gets a new host key on every reinstall, so host keys are
# neither checked nor recorded. Do not point these tools at a machine you care about.
VM_SSH_OPTS=(
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o LogLevel=ERROR
  -o ConnectTimeout=5
)

vm_die() {
  echo "Error: $*" >&2
  exit 1
}

vm_virsh() {
  # LC_ALL=C keeps virsh output parseable on hosts with a non-English locale.
  LC_ALL=C virsh -c "${VIRSH_URI}" "$@"
}

_VM_IP_CACHE=""
vm_ip() {
  if [[ -n "${REMOTE_HOST}" ]]; then
    printf '%s\n' "${REMOTE_HOST}"
    return 0
  fi
  if [[ -n "${_VM_IP_CACHE}" ]]; then
    printf '%s\n' "${_VM_IP_CACHE}"
    return 0
  fi
  local source ip
  for source in lease agent arp; do
    ip="$(vm_virsh domifaddr "${VM_DOMAIN}" --source "${source}" 2>/dev/null \
      | awk '$3 == "ipv4" { split($4, a, "/"); if (a[1] !~ /^127\./) { print a[1]; exit } }')" || true
    if [[ -n "${ip}" ]]; then
      _VM_IP_CACHE="${ip}"
      printf '%s\n' "${ip}"
      return 0
    fi
  done
  return 1
}

vm_require_ip() {
  vm_ip >/dev/null || vm_die "cannot find an IP for libvirt domain '${VM_DOMAIN}' (${VIRSH_URI}).
  Is it running and booted?  ./tools/vm-dev.sh status
  Or point at a VM directly: REMOTE_HOST=<ip> REMOTE_PORT=<port>"
}

_vm_use_password() {
  [[ -n "${REMOTE_PASSWORD}" ]] && command -v sshpass >/dev/null 2>&1
}

vm_ssh() {
  local host
  host="$(vm_ip)" || vm_require_ip
  if _vm_use_password; then
    SSHPASS="${REMOTE_PASSWORD}" sshpass -e ssh "${VM_SSH_OPTS[@]}" -p "${REMOTE_PORT}" "${REMOTE_USER}@${host}" "$@"
    return
  fi
  ssh "${VM_SSH_OPTS[@]}" -o BatchMode=yes -p "${REMOTE_PORT}" "${REMOTE_USER}@${host}" "$@"
}

# vm_scp <local files...> <remote dir>
vm_scp() {
  local host
  host="$(vm_ip)" || vm_require_ip
  local remote_dir="${*: -1}"
  local -a files=("${@:1:$#-1}")
  if _vm_use_password; then
    SSHPASS="${REMOTE_PASSWORD}" sshpass -e scp "${VM_SSH_OPTS[@]}" -P "${REMOTE_PORT}" "${files[@]}" "${REMOTE_USER}@${host}:${remote_dir}"
    return
  fi
  scp "${VM_SSH_OPTS[@]}" -o BatchMode=yes -P "${REMOTE_PORT}" "${files[@]}" "${REMOTE_USER}@${host}:${remote_dir}"
}

vm_ssh_ok() {
  (vm_ssh true) >/dev/null 2>&1
}

# vm_wait_ssh [timeout_seconds]
vm_wait_ssh() {
  local timeout="${1:-90}" deadline
  deadline=$((SECONDS + timeout))
  while ((SECONDS < deadline)); do
    _VM_IP_CACHE=""
    if vm_ip >/dev/null 2>&1 && vm_ssh_ok; then
      return 0
    fi
    sleep 2
  done
  return 1
}

vm_require_sudo() {
  vm_ssh 'sudo -n true' 2>/dev/null || vm_die "passwordless sudo is not available for ${REMOTE_USER} in the VM.
  Run once: make vm-setup   (see VM_DEV_WORKFLOW.md)"
}

# Prefix that makes a remote command run inside the logged-in desktop session of REMOTE_USER.
# shellcheck disable=SC2016
# XDG_CURRENT_DESKTOP matters: Mint apps such as mintreport crash without it.
VM_GUI_ENV='export DISPLAY="${DISPLAY:-:0}" XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" XDG_RUNTIME_DIR="/run/user/$(id -u)" DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$(id -u)/bus" XDG_CURRENT_DESKTOP="${XDG_CURRENT_DESKTOP:-X-Cinnamon}" XDG_SESSION_DESKTOP="${XDG_SESSION_DESKTOP:-cinnamon}";'

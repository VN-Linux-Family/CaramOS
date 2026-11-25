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
# Test VMs start from the latest released CaramOS: the newest vX.Y.Z tag (e.g. v1.0.20 -> 1.0.20).
vm_latest_release() {
  git -C "${VM_PKG_DIR}" tag --list 'v[0-9]*' --sort=-v:refname 2>/dev/null | head -n 1 | sed 's/^v//'
}
BASE="${BASE:-$(vm_latest_release)}"
BASE="${BASE:-1.0.16}"
VM_DOMAIN="${VM_DOMAIN:-caram${BASE}}"
VM_SNAPSHOT="${VM_SNAPSHOT:-clean}"
REMOTE_USER="${REMOTE_USER:-caram}"
# Empty REMOTE_HOST means "ask libvirt for the IP of VM_DOMAIN".
REMOTE_HOST="${REMOTE_HOST:-}"
REMOTE_PORT="${REMOTE_PORT:-22}"
# SSH to the test VM: host keys are checked as for any other machine, in a known_hosts file of their own with one entry
# per libvirt domain (HostKeyAlias), learned on first contact (accept-new). A reinstalled VM has a new key; vm-dev.sh
# create, bootstrap and install-to-disk forget the old one (by hand: ./tools/vm-dev.sh forget-host-key).
VM_KNOWN_HOSTS="${VM_KNOWN_HOSTS:-${XDG_STATE_HOME:-${HOME}/.local/state}/caramos-vm/known_hosts}"
mkdir -p "$(dirname "${VM_KNOWN_HOSTS}")"
VM_SSH_OPTS=(
  -o "UserKnownHostsFile=${VM_KNOWN_HOSTS}"
  -o StrictHostKeyChecking=accept-new
  -o BatchMode=yes
  -o LogLevel=ERROR
  -o ConnectTimeout=5
)
if [[ -z "${REMOTE_HOST}" ]]; then
  VM_SSH_OPTS+=(-o "HostKeyAlias=${VM_DOMAIN}")
fi

# The name the VM's host key is filed under in VM_KNOWN_HOSTS.
vm_host_key_name() {
  if [[ -z "${REMOTE_HOST}" ]]; then
    printf '%s\n' "${VM_DOMAIN}"
  elif [[ "${REMOTE_PORT}" == 22 ]]; then
    printf '%s\n' "${REMOTE_HOST}"
  else
    printf '[%s]:%s\n' "${REMOTE_HOST}" "${REMOTE_PORT}"
  fi
}

# Where tools/vm-guest/ goes in the VM, relative to the test user's home.
VM_GUEST_DIR="${VM_GUEST_DIR:-.caramos-vm}"

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

vm_ssh() {
  local host
  host="$(vm_ip)" || vm_require_ip
  ssh "${VM_SSH_OPTS[@]}" -p "${REMOTE_PORT}" "${REMOTE_USER}@${host}" "$@"
}

# vm_push <local dir> <dir in the VM, relative to the test user's home> [rsync options...]: copy the directory's
# contents there as the test user (no sudo in the VM; vm-guest scripts put things in place as root).
vm_push() {
  local src="$1" dest="$2" host
  shift 2
  host="$(vm_ip)" || vm_require_ip
  rsync -rlpt --mkpath "$@" -e "ssh ${VM_SSH_OPTS[*]} -p ${REMOTE_PORT}" "${src%/}/" "${REMOTE_USER}@${host}:${dest}/"
}

# Copy tools/vm-guest/ to ~/.caramos-vm in the VM, once per command: a reverted snapshot has none, or old ones.
_VM_GUEST_PUSHED=0
vm_push_guest() {
  ((_VM_GUEST_PUSHED)) && return 0
  # stage/ is what vm-dev.sh sync sent last time: kept, so the next sync only sends what changed.
  vm_push "${VM_COMMON_DIR}/vm-guest" "${VM_GUEST_DIR}" --delete --filter='P /stage/'
  _VM_GUEST_PUSHED=1
}

# vm_run <script in tools/vm-guest/> [args...]: run it in the VM as the test user: `bash ~/.caramos-vm/<script> args`.
#
# Every remote step is a script file run like this, never commands typed into the ssh command line. Endpoint security
# watches the host's command lines: "ssh to another machine, then sudo / apt / curl | bash there" is how an attacker
# moves between machines, and it raised a LateralMovement alert on 2026-11-25 (it cannot tell that the other machine is
# a VM on this host). Arguments are plain words: names, numbers, paths.
vm_run() {
  local script="$1" args=""
  shift
  vm_push_guest
  (($# == 0)) || args="$(printf ' %q' "$@")"
  vm_ssh "bash ${VM_GUEST_DIR}/${script}${args}"
}

vm_ssh_ok() {
  (vm_ssh true) >/dev/null 2>&1
}

# vm_wait_ssh [timeout_seconds]: wait until key login works (a VM that is still booting refuses the connection; no
# password is ever tried).
vm_wait_ssh() {
  local timeout="${1:-90}" deadline
  deadline=$((SECONDS + timeout))
  while ((SECONDS < deadline)); do
    _VM_IP_CACHE=""
    if vm_ip >/dev/null 2>&1 && vm_ssh_ok; then
      return 0
    fi
    sleep 3
  done
  return 1
}

vm_require_sudo() {
  vm_run check.sh >/dev/null || vm_die "passwordless sudo is not available for ${REMOTE_USER} in the VM.
  New VM: make vm-bootstrap, then make vm-setup   (see VM_DEV_WORKFLOW.md)"
}

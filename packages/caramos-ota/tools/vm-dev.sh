#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
WORKSPACE_DIR="$(cd "${PKG_DIR}/../.." && pwd)"
DIST_DIR="${PKG_DIR}/dist-testkit"

# shellcheck source=tools/vm-common.sh
source "${SCRIPT_DIR}/vm-common.sh"

VM_ISO="${VM_ISO:-${WORKSPACE_DIR}/CaramOS-${BASE}-cinnamon-amd64.iso}"
VM_MEMORY_MB="${VM_MEMORY_MB:-6144}"
VM_CPUS="${VM_CPUS:-4}"
VM_DISK_GB="${VM_DISK_GB:-40}"
VM_SUDOERS_FILE="/etc/sudoers.d/90-caramos-vm-dev"
VM_E2E_DIR="${VM_E2E_DIR:-/tmp/caramos-ota-e2e}"

usage() {
  cat <<EOF
CaramOS OTA dev VM helper (libvirt/KVM golden VM + snapshot revert)

Usage:
  ./tools/vm-dev.sh <command> [args]

One-time setup:
  create              Create libvirt domain ${VM_DOMAIN} booting VM_ISO (then install or use live session)
  bootstrap           Type the host SSH key, passwordless sudo and openssh-server into the VM (virsh send-key)
  setup               Guest agent, rsync, no screen lock (over SSH, after bootstrap)
  install-to-disk [preseed]  Install the live session to disk (ubiquity + tools/vm-install-preseed.cfg), boot it
  snapshot [name]     Take a live snapshot (disk + RAM) of the prepared VM   [default: ${VM_SNAPSHOT}]

Every test round:
  reset [name]        Revert to the snapshot, fix the clock, wait for SSH    [default: ${VM_SNAPSHOT}]
  sync                rsync the working tree over the installed package (no .deb build)
  e2e <action> [NAME=value...]  Run tools/vm-run-ota-e2e.sh <action> as root (after make ship)
  logs                Collect OTA state/logs/journal into dist-testkit/vm-logs/<timestamp>/
  shot [file.png]     Screenshot the VM display into dist-testkit/vm-shots/

Access and debugging:
  status              Domain state, IP, snapshots, SSH and installed caramos-ota version
  ip                  Print the VM IP
  ssh                 Interactive shell in the VM (no commands: use run)
  run [--gui|--bg] <script> [args...]  Copy a local script into the VM and run it there with bash
                      (--gui: in the desktop session; --bg: the same, detached, output in /tmp/caramos-vm-gui.log)
  gui <program> [args...]     Run one program inside the logged-in desktop session
  gui-bg <program> [args...]  Same, detached; output goes to /tmp/caramos-vm-gui.log in the VM
  reload-applets      Ask Cinnamon to reload the applets shipped by this package
  key <combo...>      Send key combos, e.g. key ctrl+alt+t  /  key enter
  type <text>         Type text into the focused VM window (US layout)
  click <x> <y> [btn] Mouse click at screenshot pixel coordinates (btn: left|right|middle)
  agent-exec <cmd>    Run a root shell command through qemu-guest-agent (works without SSH/network)
  forget-host-key     Forget the VM's SSH host key (after reinstalling it)
  snapshots           List snapshots
  up | down           Start / gracefully shut down the domain

Commands in the VM always go through a script file (run, or the scripts in tools/vm-guest/), never through the ssh
command line: endpoint security reads "ssh to another machine, then sudo/apt/curl | bash there" as an attacker moving
between machines (see VM_DEV_WORKFLOW.md).

Current config (override via env or vm.local.env):
  VIRSH_URI=${VIRSH_URI}
  BASE=${BASE}  VM_DOMAIN=${VM_DOMAIN}  VM_SNAPSHOT=${VM_SNAPSHOT}
  REMOTE_USER=${REMOTE_USER}  REMOTE_HOST=${REMOTE_HOST:-<auto from libvirt>}  REMOTE_PORT=${REMOTE_PORT}
  VM_ISO=${VM_ISO}
  VM_MEMORY_MB=${VM_MEMORY_MB}  VM_CPUS=${VM_CPUS}  VM_DISK_GB=${VM_DISK_GB}
  VM_KNOWN_HOSTS=${VM_KNOWN_HOSTS}

Full guide: VM_DEV_WORKFLOW.md
EOF
}

log() {
  printf '%s\n' "$*" >&2
}

domain_state() {
  vm_virsh domstate "${VM_DOMAIN}" 2>/dev/null || true
}

require_domain() {
  vm_virsh dominfo "${VM_DOMAIN}" >/dev/null 2>&1 || vm_die "libvirt domain '${VM_DOMAIN}' not found on ${VIRSH_URI}.
  Create it: make vm-create   (or set VM_DOMAIN/BASE; existing domains: $(vm_virsh list --all --name | xargs))"
}

require_running() {
  require_domain
  [[ "$(domain_state)" == "running" ]] || vm_die "domain '${VM_DOMAIN}' is not running. Start it: ./tools/vm-dev.sh up"
}

snapshot_exists() {
  vm_virsh snapshot-info "${VM_DOMAIN}" --snapshotname "$1" >/dev/null 2>&1
}

host_pubkey() {
  local candidate
  for candidate in "${VM_SSH_PUBKEY:-}" "${HOME}/.ssh/id_ed25519.pub" "${HOME}/.ssh/id_ecdsa.pub" "${HOME}/.ssh/id_rsa.pub"; do
    if [[ -n "${candidate}" && -f "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

cmd_create() {
  command -v virt-install >/dev/null 2>&1 || vm_die "virt-install not found. Install: sudo apt install virtinst libvirt-daemon-system qemu-kvm"
  if vm_virsh dominfo "${VM_DOMAIN}" >/dev/null 2>&1; then
    vm_die "domain '${VM_DOMAIN}' already exists. Pick another name (VM_DOMAIN=...) or remove it:
  virsh -c ${VIRSH_URI} undefine ${VM_DOMAIN} --snapshots-metadata --remove-all-storage"
  fi
  [[ -f "${VM_ISO}" ]] || vm_die "ISO not found: ${VM_ISO}
  Build one (make build at the repo root) or pass VM_ISO=/path/to/CaramOS-x.y.z-cinnamon-amd64.iso"

  # BIOS firmware + qcow2 on purpose: libvirt internal snapshots (disk + RAM) need both.
  virt-install \
    --connect "${VIRSH_URI}" \
    --name "${VM_DOMAIN}" \
    --memory "${VM_MEMORY_MB}" \
    --vcpus "${VM_CPUS}" \
    --cpu host-passthrough \
    --os-variant ubuntu24.04 \
    --disk "size=${VM_DISK_GB},format=qcow2,bus=virtio" \
    --cdrom "${VM_ISO}" \
    --boot hd,cdrom \
    --network network=default,model=virtio \
    --graphics spice \
    --channel unix,target.type=virtio,target.name=org.qemu.guest_agent.0 \
    --channel spicevmc,target.type=virtio,target.name=com.redhat.spice.0 \
    --noautoconsole
  # A domain of this name that existed before had another SSH host key.
  cmd_forget_host_key >/dev/null

  cat <<EOF
[OK] Created and started ${VM_DOMAIN} from ${VM_ISO}

Next:
  1. Open the VM display:  virt-viewer -c ${VIRSH_URI} ${VM_DOMAIN}   (or virt-manager)
  2. make vm-bootstrap && make vm-setup   (SSH into the live session)
  3. Install to disk: ./tools/vm-dev.sh install-to-disk, then bootstrap + setup again on the installed system
     (VM_SUDO_PROMPT=1 make vm-bootstrap), and make vm-snapshot
EOF
}

# Prints the virsh send-key arguments for one printable US-ASCII character.
keys_for_char() {
  local ch="$1"
  case "${ch}" in
    [abcdefghijklmnopqrstuvwxyz0123456789]) echo "KEY_${ch^^}" ;;
    [ABCDEFGHIJKLMNOPQRSTUVWXYZ]) echo "KEY_LEFTSHIFT KEY_${ch}" ;;
    ' ') echo KEY_SPACE ;;
    '-') echo KEY_MINUS ;;
    '=') echo KEY_EQUAL ;;
    '[') echo KEY_LEFTBRACE ;;
    ']') echo KEY_RIGHTBRACE ;;
    ';') echo KEY_SEMICOLON ;;
    "'") echo KEY_APOSTROPHE ;;
    '`') echo KEY_GRAVE ;;
    '\') echo KEY_BACKSLASH ;;
    ',') echo KEY_COMMA ;;
    '.') echo KEY_DOT ;;
    '/') echo KEY_SLASH ;;
    '!') echo KEY_LEFTSHIFT KEY_1 ;;
    '@') echo KEY_LEFTSHIFT KEY_2 ;;
    '#') echo KEY_LEFTSHIFT KEY_3 ;;
    '$') echo KEY_LEFTSHIFT KEY_4 ;;
    '%') echo KEY_LEFTSHIFT KEY_5 ;;
    '^') echo KEY_LEFTSHIFT KEY_6 ;;
    '&') echo KEY_LEFTSHIFT KEY_7 ;;
    '*') echo KEY_LEFTSHIFT KEY_8 ;;
    '(') echo KEY_LEFTSHIFT KEY_9 ;;
    ')') echo KEY_LEFTSHIFT KEY_0 ;;
    '_') echo KEY_LEFTSHIFT KEY_MINUS ;;
    '+') echo KEY_LEFTSHIFT KEY_EQUAL ;;
    '{') echo KEY_LEFTSHIFT KEY_LEFTBRACE ;;
    '}') echo KEY_LEFTSHIFT KEY_RIGHTBRACE ;;
    ':') echo KEY_LEFTSHIFT KEY_SEMICOLON ;;
    '"') echo KEY_LEFTSHIFT KEY_APOSTROPHE ;;
    '~') echo KEY_LEFTSHIFT KEY_GRAVE ;;
    '|') echo KEY_LEFTSHIFT KEY_BACKSLASH ;;
    '<') echo KEY_LEFTSHIFT KEY_COMMA ;;
    '>') echo KEY_LEFTSHIFT KEY_DOT ;;
    '?') echo KEY_LEFTSHIFT KEY_SLASH ;;
    *) return 1 ;;
  esac
}

type_text() {
  local text="$1" i ch
  local -a keys
  for ((i = 0; i < ${#text}; i++)); do
    ch="${text:i:1}"
    read -r -a keys <<<"$(keys_for_char "${ch}")" || true
    ((${#keys[@]} > 0)) || vm_die "cannot type character '${ch}' (only printable US-ASCII is supported)"
    vm_virsh send-key "${VM_DOMAIN}" "${keys[@]}" >/dev/null
  done
}

send_combo() {
  local combo="$1" part
  local -a keys=()
  local -a parts
  IFS='+' read -r -a parts <<<"${combo}"
  for part in "${parts[@]}"; do
    case "${part,,}" in
      ctrl | control) keys+=(KEY_LEFTCTRL) ;;
      alt) keys+=(KEY_LEFTALT) ;;
      shift) keys+=(KEY_LEFTSHIFT) ;;
      super | win | meta) keys+=(KEY_LEFTMETA) ;;
      enter | return) keys+=(KEY_ENTER) ;;
      esc | escape) keys+=(KEY_ESC) ;;
      del | delete) keys+=(KEY_DELETE) ;;
      *) keys+=("KEY_${part^^}") ;;
    esac
  done
  vm_virsh send-key "${VM_DOMAIN}" "${keys[@]}" >/dev/null
}

cmd_key() {
  require_running
  (($# > 0)) || vm_die "usage: vm-dev.sh key <combo...>   e.g. key ctrl+alt+t"
  local combo
  for combo in "$@"; do
    send_combo "${combo}"
  done
}

cmd_type() {
  require_running
  (($# > 0)) || vm_die "usage: vm-dev.sh type <text>"
  type_text "$*"
}

# Screen size of the VM display, read from the IHDR chunk of a fresh screenshot.
screen_size() {
  local shot
  shot="$(mktemp --suffix=.png)"
  vm_virsh screenshot "${VM_DOMAIN}" "${shot}" >/dev/null
  python3 - "${shot}" <<'PY'
import struct
import sys

with open(sys.argv[1], "rb") as handle:
    header = handle.read(24)
if header[:8] != b"\x89PNG\r\n\x1a\n":
    sys.exit("screenshot is not a PNG")
print(*struct.unpack(">II", header[16:24]))
PY
  rm -f "${shot}"
}

qmp() {
  vm_virsh qemu-monitor-command "${VM_DOMAIN}" "$1" >/dev/null
}

# Click with the virtual USB tablet; X/Y are pixels of the screenshot from `vm-dev.sh shot`.
cmd_click() {
  require_running
  local x="${1:-}" y="${2:-}" button="${3:-left}" width height
  [[ "${x}" =~ ^[0-9]+$ && "${y}" =~ ^[0-9]+$ ]] || vm_die "usage: vm-dev.sh click <x> <y> [left|right|middle]"
  read -r width height < <(screen_size)
  ((x < width && y < height)) || vm_die "(${x},${y}) is outside the ${width}x${height} screen"
  local abs_x=$((x * 32767 / (width - 1))) abs_y=$((y * 32767 / (height - 1)))
  qmp "{\"execute\":\"input-send-event\",\"arguments\":{\"events\":[{\"type\":\"abs\",\"data\":{\"axis\":\"x\",\"value\":${abs_x}}},{\"type\":\"abs\",\"data\":{\"axis\":\"y\",\"value\":${abs_y}}}]}}"
  sleep 0.1
  qmp "{\"execute\":\"input-send-event\",\"arguments\":{\"events\":[{\"type\":\"btn\",\"data\":{\"down\":true,\"button\":\"${button}\"}}]}}"
  sleep 0.1
  qmp "{\"execute\":\"input-send-event\",\"arguments\":{\"events\":[{\"type\":\"btn\",\"data\":{\"down\":false,\"button\":\"${button}\"}}]}}"
}

cmd_bootstrap() {
  require_running
  local pubkey_file pubkey home="/home/${REMOTE_USER}"
  pubkey_file="$(host_pubkey)" || vm_die "no SSH public key found on this host. Create one: ssh-keygen -t ed25519"
  pubkey="$(<"${pubkey_file}")"
  [[ "${pubkey}" =~ ^[A-Za-z0-9@._+/=:\ -]+$ ]] || vm_die "cannot type ${pubkey_file} (unexpected characters)"

  if vm_ip >/dev/null 2>&1 && vm_ssh_ok; then
    log "[OK] SSH key login already works; nothing to bootstrap."
    return 0
  fi
  # A new sshd comes with a new host key.
  cmd_forget_host_key >/dev/null

  # Typed into a terminal in the VM, never sent over the network: the host's public key, passwordless sudo for the test
  # user, then openssh-server (it starts with the key already in place, so the host never tries a password).
  local line="sudo sh -c 'install -d -m 700 -o ${REMOTE_USER} -g ${REMOTE_USER} ${home}/.ssh"
  line+=" && echo \"${pubkey}\" >> ${home}/.ssh/authorized_keys"
  line+=" && chown ${REMOTE_USER}:${REMOTE_USER} ${home}/.ssh/authorized_keys && chmod 600 ${home}/.ssh/authorized_keys"
  line+=" && echo \"${REMOTE_USER} ALL=(ALL) NOPASSWD:ALL\" > ${VM_SUDOERS_FILE} && chmod 440 ${VM_SUDOERS_FILE}"
  line+=" && apt-get update; apt-get install -y openssh-server && systemctl enable --now ssh'"

  log "Typing the bootstrap command into ${VM_DOMAIN} (the desktop must be logged in and unlocked)."
  log "The VM's keyboard must type English: if the Lotus tray icon shows V, click it to A first (vm-dev.sh click)."
  log "To do it by hand instead, open a terminal in the VM and run:"
  log "  ${line}"
  send_combo ctrl+alt+t
  # Keys sent before the terminal window has focus are lost; a cold live session needs a while.
  sleep "${VM_TERMINAL_WAIT:-15}"
  type_text "${line}"
  send_combo enter
  if [[ "${VM_SUDO_PROMPT:-0}" == "1" ]]; then
    # Installed systems ask for the sudo password; the live session does not.
    sleep 2
    type_text "${REMOTE_PASSWORD:-caram123}"
    send_combo enter
  fi

  log "Waiting for sshd in the VM (apt needs network; up to 5 minutes)..."
  vm_wait_ssh 300 || vm_die "SSH key login did not start working. Check the VM screen: make vm-shot"
  log "[OK] SSH key login works at ${REMOTE_USER}@$(vm_ip). Next: make vm-setup"
}

cmd_setup() {
  require_running
  vm_require_ip
  vm_ssh_ok || vm_die "SSH key login to ${REMOTE_USER}@$(vm_ip) does not work yet. First: make vm-bootstrap"
  vm_run setup.sh || vm_die "setup failed in the VM (see above)"

  cat <<EOF
[OK] ${VM_DOMAIN} is ready: key login as ${REMOTE_USER}@$(vm_ip), passwordless sudo, guest agent.

Make sure the desktop is logged in and looks the way a fresh user would see it, then:
  make vm-snapshot
EOF
}

cmd_snapshot() {
  local name="${1:-${VM_SNAPSHOT}}"
  require_running
  if snapshot_exists "${name}"; then
    [[ "${FORCE:-0}" == "1" ]] || vm_die "snapshot '${name}' already exists on ${VM_DOMAIN}. Replace it with FORCE=1, or use another name."
    vm_virsh snapshot-delete "${VM_DOMAIN}" --snapshotname "${name}" >/dev/null
  fi
  if ! (vm_ip >/dev/null 2>&1 && vm_ssh_ok); then
    log "Warning: SSH key login does not work right now; the snapshot will not be usable by make ship/sync."
  fi
  log "Saving disk + RAM state (the VM pauses for a few seconds)..."
  vm_virsh snapshot-create-as "${VM_DOMAIN}" "${name}" \
    --description "caramos-ota dev baseline, created $(date -Is) by ${USER:-unknown}" --atomic >/dev/null
  log "[OK] Snapshot '${name}' created. Return to it any time with: make vm-reset"
}

sync_clock() {
  # tools/vm-guest/after-revert.sh says why (clock from the snapshot, the OTA check timer).
  vm_run after-revert.sh "$(date -u +%s)" "${VM_KEEP_OTA_TIMER:-0}" \
    || log "Warning: could not set the VM clock (passwordless sudo missing?)"
}

cmd_reset() {
  local name="${1:-${VM_SNAPSHOT}}"
  require_domain
  snapshot_exists "${name}" || vm_die "snapshot '${name}' not found on ${VM_DOMAIN}. Existing: $(vm_virsh snapshot-list "${VM_DOMAIN}" --name | xargs)
  Create the baseline first: make vm-snapshot"
  local started=${SECONDS}
  vm_virsh snapshot-revert "${VM_DOMAIN}" --snapshotname "${name}" --running >/dev/null
  if ! vm_wait_ssh 90; then
    vm_die "reverted to '${name}' but SSH did not answer within 90s. Check: make vm-shot / make vm-status"
  fi
  sync_clock
  log "[OK] ${VM_DOMAIN} reverted to '${name}' and reachable at $(vm_ip) ($((SECONDS - started))s)"
}

cmd_status() {
  require_domain
  local state ip
  state="$(domain_state)"
  echo "Domain:    ${VM_DOMAIN} (${state}) on ${VIRSH_URI}"
  echo "Snapshots: $(vm_virsh snapshot-list "${VM_DOMAIN}" --name 2>/dev/null | xargs || true)"
  [[ "${state}" == "running" ]] || return 0
  if ! ip="$(vm_ip)"; then
    echo "IP:        <none yet>"
    return 0
  fi
  echo "IP:        ${ip}"
  if vm_ssh_ok; then
    echo "SSH:       ok (${REMOTE_USER}@${ip}:${REMOTE_PORT})"
    vm_run status.sh
  else
    echo "SSH:       no key login (new VM: make vm-bootstrap; reinstalled VM: ./tools/vm-dev.sh forget-host-key)"
  fi
}

cmd_ssh() {
  require_running
  (($# == 0)) || vm_die "vm-dev.sh ssh only opens an interactive shell. Put commands in a script and run it:
  ./tools/vm-dev.sh run [--gui|--bg] <script> [args...]
  Commands typed into the ssh command line (sudo, apt, curl | bash, ...) look like an attacker moving between machines
  to endpoint security (VM_DEV_WORKFLOW.md)."
  VM_SSH_OPTS+=(-t)
  vm_ssh
}

cmd_gui() {
  require_running
  (($# > 0)) || vm_die "usage: vm-dev.sh gui <program> [args...]   (one program; anything more: run --gui <script>)"
  vm_run gui.sh "$@"
}

cmd_gui_bg() {
  require_running
  (($# > 0)) || vm_die "usage: vm-dev.sh gui-bg <program> [args...]   (one program; anything more: run --bg <script>)"
  vm_run gui.sh --bg "$@"
  log "[OK] Started in the VM desktop: $*   (output: /tmp/caramos-vm-gui.log, look with: make vm-shot)"
}

cmd_reload_applets() {
  require_running
  local dir
  local -a uuids=()
  for dir in "${PKG_DIR}"/usr/share/caramos-ota/applets/*@*/; do
    [[ -d "${dir}" ]] && uuids+=("$(basename "${dir}")")
  done
  ((${#uuids[@]} > 0)) || return 0
  vm_run reload-applets.sh "${uuids[@]}" >&2
}

cmd_sync() {
  require_running
  command -v rsync >/dev/null 2>&1 || vm_die "rsync not found on the host"
  local stage src dest target
  stage="$(mktemp -d)"
  # shellcheck disable=SC2064
  trap "rm -rf '${stage}'" EXIT

  # debian/install is the single source of truth for "which path goes where".
  : >"${stage}/.caramos-targets"
  while read -r src dest || [[ -n "${src}" ]]; do
    [[ -n "${src}" && "${src}" != \#* ]] || continue
    [[ -e "${PKG_DIR}/${src}" ]] || vm_die "debian/install lists a missing path: ${src}"
    dest="${dest%/}"
    mkdir -p "${stage}/${dest}"
    cp -a "${PKG_DIR}/${src}" "${stage}/${dest}/"
    target="${dest}/$(basename "${src}")"
    printf '%s\n' "${target}" >>"${stage}/.caramos-targets"
  done < "${PKG_DIR}/debian/install"

  # Into ~/.caramos-vm/stage as the test user (only what changed since the last sync), then
  # tools/vm-guest/sync-apply.sh puts it in place as root in the VM.
  vm_push_guest
  vm_push "${stage}" "${VM_GUEST_DIR}/stage" --delete --exclude='__pycache__/' --exclude='*.pyc'
  vm_run sync-apply.sh || vm_die "could not install the synced tree in the VM (see above)"
  cmd_reload_applets
  cat <<EOF >&2
[OK] Synced working tree into ${VM_DOMAIN} (no .deb, no maintainer scripts, dpkg version unchanged).
     A running notifier keeps the old code: close it in the VM (or vm-dev.sh reset) and open it again.
     Before a PR, verify with the real package: make vm-reset ship test
EOF
}

cmd_logs() {
  require_running
  local out_dir
  out_dir="${DIST_DIR}/vm-logs/$(date +%Y%m%d-%H%M%S)"
  mkdir -p "${out_dir}"
  vm_run collect-logs.sh | tar -xzf - -C "${out_dir}"

  echo "[OK] VM logs collected in ${out_dir}"
  (cd "${out_dir}" && find . -type f -size +0 | sort | sed 's|^\./|  |')
  local state="${out_dir}/var-lib-caramos-ota/state.json"
  if [[ -f "${state}" ]]; then
    python3 - "${state}" <<'PY2' || true
import json
import sys

state = json.load(open(sys.argv[1]))
update = state.get("available_update") or {}
transaction = state.get("transaction") or {}
print()
print(f"installed_release: {state.get('installed_release')}")
print(f"available_update:  {update.get('to_version') or ('yes' if update else 'none')}")
print(f"last transaction:  {transaction.get('status') or 'none'}")
PY2
  fi
}

cmd_shot() {
  require_running
  local out="${1:-${DIST_DIR}/vm-shots/$(date +%Y%m%d-%H%M%S).png}" mime
  mkdir -p "$(dirname "${out}")"
  vm_virsh screenshot "${VM_DOMAIN}" "${out}" >/dev/null
  mime="$(file --brief --mime-type "${out}")"
  if [[ "${mime}" != "image/png" ]]; then
    # Older QEMU returns PPM.
    if command -v pnmtopng >/dev/null 2>&1; then
      pnmtopng "${out}" > "${out}.tmp" 2>/dev/null && mv "${out}.tmp" "${out}"
    elif command -v convert >/dev/null 2>&1; then
      convert "ppm:${out}" "png:${out}.tmp" && mv "${out}.tmp" "${out}"
    else
      log "Warning: screenshot is ${mime}, not PNG (install netpbm or imagemagick to convert)"
    fi
  fi
  echo "${out}"
}

cmd_agent_exec() {
  require_running
  (($# > 0)) || vm_die "usage: vm-dev.sh agent-exec <shell command>"
  python3 - "${VIRSH_URI}" "${VM_DOMAIN}" "$*" <<'PY'
import base64
import json
import subprocess
import sys
import time

uri, domain, script = sys.argv[1:4]


def agent(payload):
    result = subprocess.run(
        ["virsh", "-c", uri, "qemu-agent-command", domain, json.dumps(payload)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"Error: guest agent call failed: {result.stderr.strip()}\n"
                 "Is qemu-guest-agent installed and running in the VM? (make vm-setup)")
    return json.loads(result.stdout)["return"]


pid = agent({
    "execute": "guest-exec",
    "arguments": {"path": "/bin/sh", "arg": ["-c", script], "capture-output": True},
})["pid"]
while True:
    status = agent({"execute": "guest-exec-status", "arguments": {"pid": pid}})
    if status["exited"]:
        break
    time.sleep(0.3)
sys.stdout.write(base64.b64decode(status.get("out-data", "")).decode(errors="replace"))
sys.stderr.write(base64.b64decode(status.get("err-data", "")).decode(errors="replace"))
sys.exit(status.get("exitcode", 1))
PY
}

cmd_run() {
  require_running
  local -a mode=()
  case "${1:-}" in
    --gui | --bg) mode=("$1"); shift ;;
  esac
  (($# > 0)) || vm_die "usage: vm-dev.sh run [--gui|--bg] <local script> [args...]"
  local script="$1" stage
  shift
  [[ -f "${script}" ]] || vm_die "no such script: ${script}"
  stage="$(mktemp -d)"
  cp "${script}" "${stage}/"
  vm_push_guest
  vm_push "${stage}" "${VM_GUEST_DIR}/run" --delete
  rm -rf "${stage}"
  vm_run run.sh "${mode[@]}" "$(basename "${script}")" "$@"
}

cmd_e2e() {
  require_running
  (($# > 0)) || vm_die "usage: vm-dev.sh e2e <action> [NAME=value...]   (actions of tools/vm-run-ota-e2e.sh; run make ship first)"
  vm_run e2e.sh "${VM_E2E_DIR}" "$@"
}

cmd_forget_host_key() {
  [[ -f "${VM_KNOWN_HOSTS}" ]] || return 0
  ssh-keygen -R "$(vm_host_key_name)" -f "${VM_KNOWN_HOSTS}" >/dev/null 2>&1 || true
  rm -f "${VM_KNOWN_HOSTS}.old"
  log "[OK] Forgot the SSH host key of $(vm_host_key_name)"
}

# Installs the live session to the VM's disk: ubiquity's automatic mode with a preseed, then the restart prompt, power
# off (virt-install's install-time config stops the VM at its first reboot), CD out, boot the installed system.
cmd_install_to_disk() {
  require_running
  local preseed="${1:-${SCRIPT_DIR}/vm-install-preseed.cfg}" stage rc=0
  [[ -f "${preseed}" ]] || vm_die "preseed not found: ${preseed}"
  vm_ssh_ok || vm_die "no SSH key login into the live session yet: make vm-bootstrap, make vm-setup"
  stage="$(mktemp -d)"
  cp "${preseed}" "${stage}/preseed.cfg"
  vm_push_guest
  vm_push "${stage}" "${VM_GUEST_DIR}/install" --delete
  rm -rf "${stage}"
  vm_run install-to-disk.sh || vm_die "could not start the installer (see above)"
  log "Waiting for the installer, in one SSH session (up to ${VM_INSTALL_MINUTES:-60} minutes)..."
  vm_run wait-installer.sh "${VM_INSTALL_MINUTES:-60}" || rc=$?
  # 255: the SSH session ended because the VM restarted at the end of the install (ubiquity/reboot in the preseed).
  ((rc == 0 || rc == 255)) || vm_die "the installer did not finish (exit ${rc}). Look: make vm-shot"
  sleep 20
  log "Pressing Enter at the 'remove the installation medium' prompt; waiting for the VM to stop..."
  send_combo enter
  local deadline=$((SECONDS + 300))
  while ((SECONDS < deadline)) && [[ "$(domain_state)" != "shut off" ]]; do
    sleep 5
  done
  [[ "$(domain_state)" == "shut off" ]] || vm_die "the VM did not stop after the install. Look: make vm-shot"
  vm_virsh change-media "${VM_DOMAIN}" sda --eject --config >/dev/null 2>&1 || true
  # The installed system makes its own SSH host key.
  cmd_forget_host_key >/dev/null
  vm_virsh start "${VM_DOMAIN}" >/dev/null
  cat <<EOF
[OK] ${VM_DOMAIN} is installed to disk and boots the installed system.
Next: log in on the VM screen and close the first-run windows, then
  VM_SUDO_PROMPT=1 make vm-bootstrap && make vm-setup && make vm-snapshot
EOF
}

cmd_up() {
  require_domain
  [[ "$(domain_state)" == "running" ]] || vm_virsh start "${VM_DOMAIN}" >/dev/null
  log "[OK] ${VM_DOMAIN} is running"
}

cmd_down() {
  require_domain
  [[ "$(domain_state)" != "running" ]] || vm_virsh shutdown "${VM_DOMAIN}" >/dev/null
  log "[OK] Shutdown requested for ${VM_DOMAIN}"
}

cmd="${1:-}"
shift || true
case "${cmd}" in
  create) cmd_create ;;
  bootstrap) cmd_bootstrap ;;
  setup) cmd_setup ;;
  snapshot) cmd_snapshot "$@" ;;
  snapshots) require_domain; vm_virsh snapshot-list "${VM_DOMAIN}" ;;
  reset) cmd_reset "$@" ;;
  status) cmd_status ;;
  ip) require_domain; vm_require_ip; vm_ip ;;
  ssh) cmd_ssh "$@" ;;
  run) cmd_run "$@" ;;
  e2e) cmd_e2e "$@" ;;
  forget-host-key) cmd_forget_host_key ;;
  install-to-disk) cmd_install_to_disk "$@" ;;
  gui) cmd_gui "$@" ;;
  gui-bg) cmd_gui_bg "$@" ;;
  reload-applets) cmd_reload_applets ;;
  sync) cmd_sync ;;
  logs) cmd_logs ;;
  shot) cmd_shot "$@" ;;
  key) cmd_key "$@" ;;
  type) cmd_type "$@" ;;
  click) cmd_click "$@" ;;
  agent-exec) cmd_agent_exec "$@" ;;
  up) cmd_up ;;
  down) cmd_down ;;
  -h | --help | help | "") usage ;;
  *)
    echo "Unknown command: ${cmd}" >&2
    usage >&2
    exit 1
    ;;
esac

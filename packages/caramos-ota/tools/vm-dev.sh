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

usage() {
  cat <<EOF
CaramOS OTA dev VM helper (libvirt/KVM golden VM + snapshot revert)

Usage:
  ./tools/vm-dev.sh <command> [args]

One-time setup:
  create              Create libvirt domain ${VM_DOMAIN} booting VM_ISO (then install or use live session)
  bootstrap           Type the SSH bootstrap command into the VM desktop via virsh send-key
  setup               Install host SSH key, passwordless sudo, guest agent; disable screen lock
  snapshot [name]     Take a live snapshot (disk + RAM) of the prepared VM   [default: ${VM_SNAPSHOT}]

Every test round:
  reset [name]        Revert to the snapshot, fix the clock, wait for SSH    [default: ${VM_SNAPSHOT}]
  sync                rsync the working tree over the installed package (no .deb build)
  logs                Collect OTA state/logs/journal into dist-testkit/vm-logs/<timestamp>/
  shot [file.png]     Screenshot the VM display into dist-testkit/vm-shots/

Access and debugging:
  status              Domain state, IP, snapshots, SSH and installed caramos-ota version
  ip                  Print the VM IP
  ssh [command...]    SSH into the VM (interactive shell without a command)
  gui <command...>    Run a command inside the logged-in desktop session (DISPLAY/DBus set)
  gui-bg <command...> Same, detached; output goes to /tmp/caramos-vm-gui.log in the VM
  reload-applets      Ask Cinnamon to reload the applets shipped by this package
  key <combo...>      Send key combos, e.g. key ctrl+alt+t  /  key enter
  type <text>         Type text into the focused VM window (US layout)
  click <x> <y> [btn] Mouse click at screenshot pixel coordinates (btn: left|right|middle)
  agent-exec <cmd>    Run a root shell command through qemu-guest-agent (works without SSH/network)
  snapshots           List snapshots
  up | down           Start / gracefully shut down the domain

Current config (override via env or vm.local.env):
  VIRSH_URI=${VIRSH_URI}
  BASE=${BASE}  VM_DOMAIN=${VM_DOMAIN}  VM_SNAPSHOT=${VM_SNAPSHOT}
  REMOTE_USER=${REMOTE_USER}  REMOTE_HOST=${REMOTE_HOST:-<auto from libvirt>}  REMOTE_PORT=${REMOTE_PORT}
  VM_ISO=${VM_ISO}
  VM_MEMORY_MB=${VM_MEMORY_MB}  VM_CPUS=${VM_CPUS}  VM_DISK_GB=${VM_DISK_GB}

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

  cat <<EOF
[OK] Created and started ${VM_DOMAIN} from ${VM_ISO}

Next:
  1. Open the VM display:  virt-viewer -c ${VIRSH_URI} ${VM_DOMAIN}   (or virt-manager)
  2. Either install CaramOS to disk and reboot (recommended), or stay in the live session.
  3. make vm-bootstrap && make vm-setup && make vm-snapshot
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
  local password="${REMOTE_PASSWORD:-caram123}"
  local line="sudo sh -c 'apt-get update; apt-get install -y openssh-server && echo ${REMOTE_USER}:${password} | chpasswd && systemctl enable --now ssh'"

  if vm_ip >/dev/null 2>&1 && vm_ssh_ok; then
    log "[OK] SSH key login already works; nothing to bootstrap."
    return 0
  fi

  log "Typing the bootstrap command into ${VM_DOMAIN} (the desktop must be logged in and unlocked)."
  log "If you prefer to do it by hand, open a terminal in the VM and run:"
  log "  ${line}"
  send_combo ctrl+alt+t
  # Keys sent before the terminal window has focus are lost; a cold live session needs a while.
  sleep "${VM_TERMINAL_WAIT:-15}"
  type_text "${line}"
  send_combo enter
  if [[ "${VM_SUDO_PROMPT:-0}" == "1" ]]; then
    # Installed systems ask for the sudo password; the live session does not.
    sleep 2
    type_text "${password}"
    send_combo enter
  fi

  log "Waiting for sshd in the VM (apt needs network; up to 5 minutes)..."
  local deadline=$((SECONDS + 300))
  while ((SECONDS < deadline)); do
    _VM_IP_CACHE=""
    if vm_ip >/dev/null 2>&1 && (REMOTE_PASSWORD="${password}" vm_ssh true) >/dev/null 2>&1; then
      log "[OK] SSH is up at ${REMOTE_USER}@$(vm_ip) (password: ${password}). Next: make vm-setup"
      return 0
    fi
    sleep 5
  done
  vm_die "SSH did not come up. Check the VM screen: make vm-shot"
}

cmd_setup() {
  require_running
  vm_require_ip
  local pubkey_file pubkey
  pubkey_file="$(host_pubkey)" || vm_die "no SSH public key found on this host. Create one: ssh-keygen -t ed25519"
  pubkey="$(<"${pubkey_file}")"

  if ! (REMOTE_PASSWORD='' vm_ssh true) >/dev/null 2>&1; then
    command -v sshpass >/dev/null 2>&1 || vm_die "sshpass is needed for the first login. Install: sudo apt install sshpass"
    if [[ -z "${REMOTE_PASSWORD}" ]]; then
      read -r -s -p "Password of ${REMOTE_USER}@$(vm_ip): " REMOTE_PASSWORD
      echo >&2
    fi
    vm_ssh true || vm_die "cannot SSH to ${REMOTE_USER}@$(vm_ip):${REMOTE_PORT}. Is openssh-server installed in the VM? (make vm-bootstrap)"
    log "== installing ${pubkey_file} into the VM =="
    vm_ssh "mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && { grep -qxF ${pubkey@Q} ~/.ssh/authorized_keys || printf '%s\n' ${pubkey@Q} >> ~/.ssh/authorized_keys; }"
  fi

  if ! vm_ssh 'sudo -n true' 2>/dev/null; then
    [[ -n "${REMOTE_PASSWORD}" ]] || {
      read -r -s -p "sudo password of ${REMOTE_USER}: " REMOTE_PASSWORD
      echo >&2
    }
    log "== enabling passwordless sudo for ${REMOTE_USER} =="
    local rule="${REMOTE_USER} ALL=(ALL) NOPASSWD:ALL"
    vm_ssh "printf '%s\n' ${REMOTE_PASSWORD@Q} | sudo -S -p '' sh -c 'printf \"%s\\n\" \"${rule}\" > ${VM_SUDOERS_FILE} && chmod 440 ${VM_SUDOERS_FILE} && visudo -cf ${VM_SUDOERS_FILE}'"
  fi

  # From here on everything must work with the key alone.
  REMOTE_PASSWORD=''
  vm_ssh_ok || vm_die "SSH key login still fails after installing the key"
  vm_require_sudo

  log "== installing guest packages =="
  vm_ssh "sudo -n sh -c '
    set -e
    for f in /etc/apt/sources.list /etc/apt/sources.list.d/*; do
      [ -f \"\$f\" ] && sed -i \"/^deb cdrom:/ s/^/#/\" \"\$f\"
    done
    apt-get update || true
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q -o Dpkg::Use-Pty=0 openssh-server qemu-guest-agent rsync
    systemctl enable --now ssh
    systemctl start qemu-guest-agent || true
  '"

  log "== disabling screen lock / blanking so screenshots show the desktop =="
  vm_ssh "${VM_GUI_ENV}"'
    gsettings set org.cinnamon.desktop.screensaver lock-enabled false
    gsettings set org.cinnamon.desktop.session idle-delay 0
    gsettings set org.cinnamon.settings-daemon.plugins.power sleep-display-ac 0
    gsettings set org.cinnamon.settings-daemon.plugins.power sleep-inactive-ac-timeout 0
  ' || log "Warning: could not change desktop settings (is ${REMOTE_USER} logged in to the desktop?)"

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
  # A reverted VM wakes up at the moment the snapshot was taken; apt rejects repos "from the future".
  # Jumping the clock forward also makes the daily caramos-ota-check.timer due at once. Installing a
  # .deb restarts that timer (postinst), the timer runs `caramos-ota --check`, and the check
  # self-updates caramos-ota from the PPA over the package under test while holding the OTA lock.
  # So the background check service is masked for this boot only (/run, gone after the next revert
  # or reboot). The CLI (`caramos-ota --check`) still works. VM_KEEP_OTA_TIMER=1 keeps it.
  local quiet_ota="systemctl mask --runtime --now caramos-ota-check.service >/dev/null 2>&1; systemctl stop caramos-ota-check.timer;"
  [[ "${VM_KEEP_OTA_TIMER:-0}" != "1" ]] || quiet_ota=""
  vm_ssh "sudo -n sh -c '${quiet_ota} date -u -s @$(date -u +%s) >/dev/null'" 2>/dev/null \
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
    vm_ssh '
      printf "sudo -n:   %s\n" "$(sudo -n true 2>/dev/null && echo ok || echo "needs password (run make vm-setup)")"
      printf "Release:   %s\n" "$(. /etc/caramos-release 2>/dev/null; echo "${VERSION:-unknown}")"
      printf "Package:   caramos-ota %s\n" "$(dpkg-query -W -f="\${Version} (\${db:Status-Abbrev})" caramos-ota 2>/dev/null || echo "not installed")"
      printf "Clock:     %s\n" "$(date -Is)"
    '
  else
    echo "SSH:       not reachable with the host key (run make vm-bootstrap / make vm-setup)"
  fi
}

cmd_ssh() {
  require_running
  if (($# == 0)); then
    VM_SSH_OPTS+=(-t)
  fi
  vm_ssh "$@"
}

cmd_gui() {
  require_running
  (($# > 0)) || vm_die "usage: vm-dev.sh gui <command...>"
  vm_ssh "${VM_GUI_ENV} $*"
}

cmd_gui_bg() {
  require_running
  (($# > 0)) || vm_die "usage: vm-dev.sh gui-bg <command...>"
  vm_ssh "${VM_GUI_ENV} nohup setsid $* >/tmp/caramos-vm-gui.log 2>&1 </dev/null &"
  log "[OK] Started in the VM desktop: $*   (output: /tmp/caramos-vm-gui.log, look with: make vm-shot)"
}

cmd_reload_applets() {
  require_running
  local dir uuid
  for dir in "${PKG_DIR}"/usr/share/caramos-ota/applets/*@*/; do
    [[ -d "${dir}" ]] || continue
    uuid="$(basename "${dir}")"
    if vm_ssh "${VM_GUI_ENV} dbus-send --session --print-reply --dest=org.Cinnamon /org/Cinnamon org.Cinnamon.ReloadXlet string:${uuid} string:APPLET >/dev/null"; then
      log "[OK] Reloaded applet ${uuid}"
    else
      log "Warning: could not reload applet ${uuid} (not logged in, or the applet is not on a panel)"
    fi
  done
}

cmd_sync() {
  require_running
  vm_require_sudo
  command -v rsync >/dev/null 2>&1 || vm_die "rsync not found on the host"
  local stage src dest target host
  local -a sources=()
  stage="$(mktemp -d)"
  # shellcheck disable=SC2064
  trap "rm -rf '${stage}'" EXIT

  # debian/install is the single source of truth for "which path goes where".
  while read -r src dest || [[ -n "${src}" ]]; do
    [[ -n "${src}" && "${src}" != \#* ]] || continue
    [[ -e "${PKG_DIR}/${src}" ]] || vm_die "debian/install lists a missing path: ${src}"
    dest="${dest%/}"
    mkdir -p "${stage}/${dest}"
    cp -a "${PKG_DIR}/${src}" "${stage}/${dest}/"
    target="${dest}/$(basename "${src}")"
    sources+=("${stage}/./${target}")
  done < "${PKG_DIR}/debian/install"

  host="$(vm_ip)"
  # --relative + --no-implied-dirs: only the listed files/dirs are touched, so --delete cannot
  # reach outside the package's own directories and parent dirs such as /usr keep their attributes.
  rsync -rlpt --relative --no-implied-dirs --delete \
    --exclude='__pycache__/' --exclude='*.pyc' \
    --chown=root:root --chmod=go-w \
    --rsync-path='sudo -n rsync' \
    -e "ssh ${VM_SSH_OPTS[*]} -o BatchMode=yes -p ${REMOTE_PORT}" \
    --itemize-changes \
    "${sources[@]}" "${REMOTE_USER}@${host}:/"

  vm_ssh 'sudo -n systemctl daemon-reload'
  cmd_reload_applets
  cat <<EOF >&2
[OK] Synced working tree into ${VM_DOMAIN} (no .deb, no maintainer scripts, dpkg version unchanged).
     A running notifier keeps the old code: ./tools/vm-dev.sh ssh pkill -f caramos-ota-notifier
     Before a PR, verify with the real package: make vm-reset ship test
EOF
}

cmd_logs() {
  require_running
  local out_dir
  out_dir="${DIST_DIR}/vm-logs/$(date +%Y%m%d-%H%M%S)"
  mkdir -p "${out_dir}"
  {
    printf '%s\n' "${VM_GUI_ENV}"
    cat <<'REMOTE'
set +e
exec 3>&1 1>/dev/null 2>&1
out="$(mktemp -d)"
run() { local name="$1"; shift; "$@" >"${out}/${name}" 2>&1; }
run release.txt sh -c 'for f in /etc/caramos-release /etc/os-release /etc/lsb-release; do echo "== $f"; cat "$f"; done'
run package.txt sh -c 'dpkg-query -W -f="\${Package} \${Version} \${db:Status-Abbrev}\n" caramos-ota; echo; apt-cache policy caramos-ota'
run systemd.txt systemctl status caramos-ota-check.timer caramos-ota-check.service --no-pager --lines=30
run failed-units.txt systemctl --failed --no-pager
run journal-ota.txt sh -c 'sudo -n journalctl -b --no-pager -o short-iso | grep -i "caramos[-_]ota"'
run journal-boot.txt sudo -n journalctl -b --no-pager -o short-iso -n 4000
run apt-history.txt sudo -n tail -n 200 /var/log/apt/history.log
run apt-term.txt sudo -n tail -n 500 /var/log/apt/term.log
run dpkg.txt tail -n 300 /var/log/dpkg.log
run xsession-errors.txt tail -n 1500 "${HOME}/.xsession-errors"
run enabled-applets.txt gsettings get org.cinnamon enabled-applets
run gui-command.txt cat /tmp/caramos-vm-gui.log
sudo -n cp -a /var/lib/caramos-ota "${out}/var-lib-caramos-ota"
sudo -n cp -a /var/log/caramos-ota "${out}/var-log-caramos-ota"
sudo -n chown -R "$(id -u):$(id -g)" "${out}"
chmod -R u+rwX "${out}"
tar -C "${out}" -czf - . >&3
rm -rf "${out}"
REMOTE
  } | vm_ssh 'bash -s' | tar -xzf - -C "${out_dir}"

  echo "[OK] VM logs collected in ${out_dir}"
  (cd "${out_dir}" && find . -type f -size +0 | sort | sed 's|^\./|  |')
  local state="${out_dir}/var-lib-caramos-ota/state.json"
  if [[ -f "${state}" ]]; then
    python3 - "${state}" <<'PY' || true
import json
import sys

state = json.load(open(sys.argv[1]))
update = state.get("available_update") or {}
transaction = state.get("transaction") or {}
print()
print(f"installed_release: {state.get('installed_release')}")
print(f"available_update:  {update.get('to_version') or ('yes' if update else 'none')}")
print(f"last transaction:  {transaction.get('status') or 'none'}")
PY
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

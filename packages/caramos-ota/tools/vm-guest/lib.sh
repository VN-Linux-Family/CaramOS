# Shared helpers for the scripts in this folder. They run inside the test VM, as the test user, from ~/.caramos-vm,
# where the host's tools/vm-dev.sh copies this folder before each remote step. Every remote step is one of these script
# files, never commands typed into the ssh command line: see "Lệnh trong VM" in VM_DEV_WORKFLOW.md.

need_sudo() {
  sudo -n true 2>/dev/null && return 0
  echo "Error: passwordless sudo is not set up for $(id -un) in this VM. On the host: make vm-bootstrap, then make vm-setup" >&2
  exit 3
}

# Take over the environment of the logged-in desktop session (Cinnamon, or Xfce): DISPLAY, the D-Bus session bus,
# XDG_DATA_DIRS, the language, the desktop name. A program started afterwards behaves like one started from the menu.
# Without a session (nobody logged in) only the usual defaults are set.
session_env() {
  local uid pid="" name entry
  uid="$(id -u)"
  # Process names as the kernel keeps them (at most 15 characters, so not cinnamon-session).
  for name in cinnamon xfce4-session xfce4-panel; do
    pid="$(pgrep -u "${uid}" -x "${name}" 2>/dev/null | head -n 1)" || pid=""
    [ -n "${pid}" ] && break
  done
  if [ -n "${pid}" ] && [ -r "/proc/${pid}/environ" ]; then
    while IFS= read -r -d '' entry; do
      case "${entry%%=*}" in
        '' | *[!A-Za-z0-9_]* | PWD | OLDPWD | SHLVL | _) continue ;;
      esac
      export "${entry?}"
    done <"/proc/${pid}/environ"
  fi
  unset SSH_CLIENT SSH_CONNECTION SSH_TTY
  export DISPLAY="${DISPLAY:-:0}"
  export XAUTHORITY="${XAUTHORITY:-${HOME}/.Xauthority}"
  export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/${uid}}"
  export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=/run/user/${uid}/bus}"
  # Mint apps such as mintreport crash without a desktop name.
  export XDG_CURRENT_DESKTOP="${XDG_CURRENT_DESKTOP:-X-Cinnamon}"
  export XDG_SESSION_DESKTOP="${XDG_SESSION_DESKTOP:-cinnamon}"
}

# SESSION_RUNNER: the prefix that starts a program outside this SSH login, in a scope of the user's systemd. logind and
# polkit then count it in the desktop session (active, local), like a program opened from the menu. Started from the SSH
# login itself, polkit treats it as a remote user: the Update Center's no-password check was refused ("Tài khoản này
# không được kiểm tra bản cập nhật"). Call session_env first.
session_runner() {
  SESSION_RUNNER=()
  if command -v systemd-run >/dev/null 2>&1 && systemd-run --user --scope --quiet true >/dev/null 2>&1; then
    SESSION_RUNNER=(systemd-run --user --scope --quiet --collect --)
  fi
}

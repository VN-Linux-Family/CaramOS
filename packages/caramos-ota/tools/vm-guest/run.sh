#!/bin/bash
# run.sh [--gui|--bg] <name> [args...]: run the script that vm-dev.sh run copied to ~/.caramos-vm/run/<name>, with bash.
# --gui: inside the desktop session (like gui.sh); --bg: the same, detached, output in /tmp/caramos-vm-gui.log.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "${here}/lib.sh"
mode=plain
case "${1:-}" in
  --gui) mode=gui; shift ;;
  --bg) mode=bg; shift ;;
esac
[ $# -gt 0 ] || { echo "usage: run.sh [--gui|--bg] <name> [args...]" >&2; exit 2; }
script="${here}/run/$1"
shift
[ -f "${script}" ] || { echo "run.sh: ${script} is missing" >&2; exit 2; }
if [ "${mode}" = plain ]; then
  exec bash "${script}" "$@"
fi
session_env
session_runner
cd "${HOME}"
if [ "${mode}" = bg ]; then
  nohup setsid "${SESSION_RUNNER[@]}" bash "${script}" "$@" >/tmp/caramos-vm-gui.log 2>&1 </dev/null &
  exit 0
fi
exec "${SESSION_RUNNER[@]}" bash "${script}" "$@"

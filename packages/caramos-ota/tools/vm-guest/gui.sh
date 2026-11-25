#!/bin/bash
# gui.sh [--bg] <program> [args...]: run one program in the logged-in desktop session, as if started from the menu
# (vm-dev.sh gui). --bg: detached, its output in /tmp/caramos-vm-gui.log (vm-dev.sh gui-bg).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "${here}/lib.sh"
background=0
if [ "${1:-}" = --bg ]; then
  background=1
  shift
fi
[ $# -gt 0 ] || { echo "usage: gui.sh [--bg] <program> [args...]" >&2; exit 2; }
session_env
cd "${HOME}"
session_runner
if [ "${background}" = 1 ]; then
  nohup setsid "${SESSION_RUNNER[@]}" "$@" >/tmp/caramos-vm-gui.log 2>&1 </dev/null &
  exit 0
fi
exec "${SESSION_RUNNER[@]}" "$@"

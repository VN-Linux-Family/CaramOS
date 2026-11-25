#!/bin/bash
# e2e.sh <dir> <action> [NAME=value...]: run vm-run-ota-e2e.sh <action> as root in <dir>, where ship.sh put it, with
# these environment variables (make test, make test-notifier).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "${here}/lib.sh"
need_sudo
[ $# -ge 2 ] || { echo "usage: e2e.sh <dir> <action> [NAME=value...]" >&2; exit 2; }
dir="$1" action="$2"
shift 2
for assignment in "$@"; do
  case "${assignment}" in
    [A-Za-z_]*=*) ;;
    *) echo "e2e.sh: expected NAME=value, got: ${assignment}" >&2; exit 2 ;;
  esac
done
[ -x "${dir}/vm-run-ota-e2e.sh" ] || { echo "e2e.sh: ${dir} has no vm-run-ota-e2e.sh: run make ship first" >&2; exit 2; }
cd "${dir}"
exec sudo -n env "$@" ./vm-run-ota-e2e.sh "${action}"

#!/bin/bash
# compare-renderers.sh stop|start|probe <program> <renderer>: the VM side of tools/compare-renderers.py.
#   stop   stop the program, remove its log for this renderer
#   start  start it with GSK_DEBUG=renderer (and GSK_RENDERER=<renderer> unless "auto"); run with vm-dev.sh run --bg
#   probe  print its memory (PSS) and the renderer GTK reports, then stop it
set -u
action="$1" program="$2" renderer="${3:-auto}"
log="/tmp/compare-renderers-${program}-${renderer}.log"
pattern="^python3 /usr/bin/${program}"
case "${action}" in
  stop)
    pkill -f "${pattern}"
    rm -f "${log}"
    ;;
  start)
    if [ "${renderer}" = auto ]; then
      exec env GSK_DEBUG=renderer "${program}" 2>"${log}"
    fi
    exec env GSK_DEBUG=renderer GSK_RENDERER="${renderer}" "${program}" 2>"${log}"
    ;;
  probe)
    pid="$(pgrep -n -f "${pattern}")"
    if [ -n "${pid}" ]; then
      awk '/^Pss:/ { s += $2 } END { printf "%d MB\n", s / 1024 }' "/proc/${pid}/smaps_rollup"
    fi
    grep -o "Using renderer of type .[A-Za-z]*" "${log}" | head -n 1
    pkill -f "${pattern}"
    ;;
  *)
    echo "usage: compare-renderers.sh stop|start|probe <program> <renderer>" >&2
    exit 2
    ;;
esac

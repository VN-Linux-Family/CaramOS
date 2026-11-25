#!/bin/bash
# reload-applets.sh <uuid...>: ask Cinnamon to reload these applets (vm-dev.sh reload-applets, after a sync).
here="$(cd "$(dirname "$0")" && pwd)"
. "${here}/lib.sh"
session_env
for uuid in "$@"; do
  if dbus-send --session --print-reply --dest=org.Cinnamon /org/Cinnamon org.Cinnamon.ReloadXlet \
    "string:${uuid}" string:APPLET >/dev/null 2>&1; then
    echo "[OK] Reloaded applet ${uuid}"
  else
    echo "Warning: could not reload applet ${uuid} (not logged in, or the applet is not on a panel)"
  fi
done

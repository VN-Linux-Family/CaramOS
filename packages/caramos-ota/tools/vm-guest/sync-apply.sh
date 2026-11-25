#!/bin/bash
# sync-apply.sh: put the tree that vm-dev.sh sync copied to ~/.caramos-vm/stage over the installed package (as root),
# then reload systemd. stage/.caramos-targets lists the installed paths, one per line (from debian/install).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
. "${here}/lib.sh"
need_sudo
stage="${here}/stage"
sources=()
while IFS= read -r target || [ -n "${target}" ]; do
  [ -n "${target}" ] && sources+=("${stage}/./${target}")
done <"${stage}/.caramos-targets"
[ "${#sources[@]}" -gt 0 ] || { echo "sync-apply.sh: nothing staged" >&2; exit 2; }
# --relative + --no-implied-dirs: only the listed files/dirs are touched, so --delete cannot reach outside the package's
# own directories and parent dirs such as /usr keep their attributes. usr/share/locale is listed whole but belongs to
# every package: deleting there removed all other translations (cinnamon.mo too, and without it GLib turns off every
# translation in Cinnamon).
sudo -n rsync -rlpt --relative --no-implied-dirs --delete \
  --filter='protect /usr/share/locale/**' \
  --exclude='__pycache__/' --exclude='*.pyc' \
  --chown=root:root --chmod=go-w \
  --itemize-changes \
  "${sources[@]}" /
sudo -n systemctl daemon-reload

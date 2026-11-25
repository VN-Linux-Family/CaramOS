#!/bin/bash
# wait-installer.sh [minutes]: wait until ubiquity is gone. With ubiquity/reboot in the preseed the VM restarts at the
# end of the install, which ends this SSH session too (vm-dev.sh install-to-disk takes both as "done").
limit="${1:-60}"
for ((second = 0; second < limit * 60; second += 20)); do
  if ! pgrep -f '[u]biquity' >/dev/null; then
    echo "installer finished"
    exit 0
  fi
  ((second % 60 == 0)) && echo "installer running ($((second / 60)) min)"
  sleep 20
done
echo "installer still running after ${limit} min" >&2
exit 1

#!/bin/bash
# In the test VM: stop Canon's daemon, restart the virtual printer (default status style) and
# print the CUPS test page through captdriver (queue CAPT, usb:// backend).
set -u
D=/tmp/vlbp2900
sudo /etc/init.d/ccpd stop >/dev/null
for i in $(seq 1 30); do pgrep -x ccpd >/dev/null || break; sleep 1; done
kill "$(cat $D/server.pid)" 2>/dev/null; sleep 2
n=$(ls $D/run*.log 2>/dev/null | wc -l); mv $D/vlbp2900.log "$D/run$((n + 1)).log"
setsid nohup python3 /tmp/vlbp2900.py serve > $D/serve.out 2>&1 < /dev/null &
echo $! > $D/server.pid; sleep 1
sudo python3 /tmp/vlbp2900.py attach >/dev/null; sleep 8
before=$(ls $D | grep -c '\.capt$')
lp -d CAPT -t "captdriver regress" /usr/share/cups/data/testprint
for i in $(seq 1 30); do sleep 3; [ "$(ls $D | grep -c '\.capt$')" -gt "$before" ] && break; done
sleep 6
echo "pages saved: $(( $(ls $D | grep -c '\.capt$') - before ))"
grep -E 'JOB|PAGE' $D/vlbp2900.log | awk '{$1=""; print}' | cut -c1-120
cat $(ls -t $D/*.decoded.json | head -1)

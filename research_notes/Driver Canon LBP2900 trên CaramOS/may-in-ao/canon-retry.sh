#!/bin/bash
# In the test VM: restart the virtual printer with the current vlbp2900.py, restart ccpd
# cleanly (wait for the old one to exit) and print a plain text file through Canon's driver.
set -u
D=/tmp/vlbp2900
sudo /etc/init.d/ccpd stop >/dev/null
for i in $(seq 1 30); do pgrep -x ccpd >/dev/null || break; sleep 1; done
pgrep -x ccpd >/dev/null && { echo "ccpd still running after 30 s, killing"; sudo pkill -x ccpd; sleep 1; }
kill "$(cat $D/server.pid)" 2>/dev/null
sleep 2
n=$(ls $D/run*.log 2>/dev/null | wc -l)
mv $D/vlbp2900.log "$D/run$((n + 1)).log"
VLBP_STATUS=${VLBP_STATUS:-specs} setsid nohup python3 /tmp/vlbp2900.py serve > $D/serve.out 2>&1 < /dev/null &
echo $! > $D/server.pid
sleep 1
sudo python3 /tmp/vlbp2900.py attach >/dev/null
sleep 8
ls -l /dev/usb/lp0 | cut -c1-60
sudo /etc/init.d/ccpd start >/dev/null
sleep 5
echo "ccpd processes: $(pgrep -c -x ccpd)"
before=$(ls $D | grep -c '\.capt$')
printf 'CaramOS - may in ao LBP2900\nIn bang driver Canon 2.71 (ccpd)\n' > /tmp/hello2.txt
lp -d CanonLBP2900 -t "hello canon 2" /tmp/hello2.txt
for i in $(seq 1 30); do
  sleep 4
  [ "$(ls $D | grep -c '\.capt$')" -gt "$before" ] && break
done
sleep 3
echo "waited $((i * 4)) s; pages saved: $(( $(ls $D | grep -c '\.capt$') - before ))"
grep -E 'H>D|PAGE|JOB|JUNK|NOTE|PROTO' $D/vlbp2900.log | grep -v 'GetPrinterInfo\|GetExtendedStatus len\|GetInputStatus len' \
  | awk '{$1=""; print}' | uniq -c | cut -c1-150 | head -n 40
ls $D | grep '\.decoded\.json$' | while read -r f; do echo "$f $(cat $D/$f)"; done

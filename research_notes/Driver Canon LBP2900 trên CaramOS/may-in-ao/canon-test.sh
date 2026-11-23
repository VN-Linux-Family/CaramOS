#!/bin/bash
# In the test VM: set up Canon's CAPT 2.71 queue on the virtual LBP2900 the way the
# community guides do (lpadmin ccp://, ccpdadmin, ccpd), print the CUPS test page and
# report what reached the printer. No aa-complain, no extra udev rules.
set -u
LOG=/tmp/vlbp2900/vlbp2900.log
PPD=$(ls /usr/share/cups/model/CNCUPSLBP2900CAPTK.ppd 2>/dev/null || find /usr/share -name 'CNCUPSLBP2900CAPTK.ppd*' | head -1)
echo "PPD: $PPD"
sudo lpadmin -p CanonLBP2900 -P "$PPD" -v ccp://localhost:59687 -E && echo "queue added"
sudo ccpdadmin -p CanonLBP2900 -o /dev/usb/lp0 | tail -n 4
L0=$(wc -l < "$LOG")
sudo /etc/init.d/ccpd start
sleep 8
echo "ccpd: $(pgrep -a ccpd | tr '\n' ' ')"
echo "ccpd systemd: $(systemctl is-active ccpd 2>&1) enabled: $(systemctl is-enabled ccpd 2>&1)"
echo "-- printer traffic after ccpd start:"
tail -n +"$L0" "$LOG" | grep -v 'control a1000000\|control 80080000' | cut -c1-170 | head -n 30
L1=$(wc -l < "$LOG")
lp -d CanonLBP2900 -t "testprint canon" /usr/share/cups/data/testprint
for i in $(seq 1 36); do
  sleep 5
  S=$(lpstat -l -p CanonLBP2900 | head -2 | tr '\n' ' ')
  case "$S" in *idle*) break ;; esac
done
echo "after $((i * 5)) s: $S"
lpstat -o
echo "-- printer traffic during the job:"
tail -n +"$L1" "$LOG" | grep -v 'control a1000000\|control 80080000\|OUT  ' | cut -c1-170 | head -n 80
echo "-- pages:"
ls -la /tmp/vlbp2900/ | grep page
cat /tmp/vlbp2900/page-*.decoded.json 2>/dev/null
echo "-- cups errors:"
sudo grep -a -E "^E |\[Job" /var/log/cups/error_log | grep -a -i -E "CanonLBP2900|ccp|captfilter|error" | tail -n 15 | cut -c1-220
echo "-- apparmor:"
sudo journalctl -k -b --no-pager | grep -i apparmor | grep -v 'capname="net_admin"\|capname="sys_admin"' | tail -n 5 | cut -c1-240

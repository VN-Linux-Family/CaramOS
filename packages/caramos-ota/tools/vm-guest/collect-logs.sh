#!/bin/bash
# collect-logs.sh: OTA state, logs and the journal of this boot, as a .tar.gz on stdout (vm-dev.sh logs).
here="$(cd "$(dirname "$0")" && pwd)"
. "${here}/lib.sh"
session_env
set +e
exec 3>&1 1>/dev/null 2>&1
out="$(mktemp -d)"
run() { local name="$1"; shift; "$@" >"${out}/${name}" 2>&1; }
run release.txt sh -c 'for f in /etc/caramos-release /etc/os-release /etc/lsb-release; do echo "== $f"; cat "$f"; done'
run package.txt sh -c 'dpkg-query -W -f="\${Package} \${Version} \${db:Status-Abbrev}\n" caramos-ota; echo; apt-cache policy caramos-ota'
run systemd.txt systemctl status caramos-ota-check.timer caramos-ota-check.service --no-pager --lines=30
run failed-units.txt systemctl --failed --no-pager
run journal-ota.txt sh -c 'sudo -n journalctl -b --no-pager -o short-iso | grep -i "caramos[-_]ota"'
run journal-boot.txt sudo -n journalctl -b --no-pager -o short-iso -n 4000
run apt-history.txt sudo -n tail -n 200 /var/log/apt/history.log
run apt-term.txt sudo -n tail -n 500 /var/log/apt/term.log
run dpkg.txt tail -n 300 /var/log/dpkg.log
run xsession-errors.txt tail -n 1500 "${HOME}/.xsession-errors"
run enabled-applets.txt gsettings get org.cinnamon enabled-applets
run gui-command.txt cat /tmp/caramos-vm-gui.log
sudo -n cp -a /var/lib/caramos-ota "${out}/var-lib-caramos-ota"
sudo -n cp -a /var/log/caramos-ota "${out}/var-log-caramos-ota"
sudo -n chown -R "$(id -u):$(id -g)" "${out}"
chmod -R u+rwX "${out}"
tar -C "${out}" -czf - . >&3
rm -rf "${out}"

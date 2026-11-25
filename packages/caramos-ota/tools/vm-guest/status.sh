#!/bin/bash
# status.sh: the inside of the VM, for vm-dev.sh status.
printf 'sudo -n:   %s\n' "$(sudo -n true 2>/dev/null && echo ok || echo 'needs password (run make vm-bootstrap)')"
printf 'Release:   %s\n' "$(. /etc/caramos-release 2>/dev/null; echo "${VERSION:-unknown}")"
# shellcheck disable=SC2016
printf 'Package:   caramos-ota %s\n' "$(dpkg-query -W -f='${Version} (${db:Status-Abbrev})' caramos-ota 2>/dev/null || echo 'not installed')"
printf 'Clock:     %s\n' "$(date -Is)"

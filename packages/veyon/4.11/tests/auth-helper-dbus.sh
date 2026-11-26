#!/bin/bash
# veyon-auth-helper as Veyon 4.11 uses it for logon authentication: a service on the system bus
# (io.veyon.AuthHelper), not setuid. In a test container where the veyon packages are installed, with a system
# dbus-daemon of its own. There is no systemd in the container, so the helper is started as systemd would start it
# (veyon-auth-helper.service), and the D-Bus activation file is only checked for what it names: activation on the
# system bus goes through systemd (SystemdService=).
set -euo pipefail

step() { printf '\n--- %s\n' "$*"; }
ok() { printf 'ok   %s\n' "$*"; }
fail() { printf 'FAIL %s\n' "$*" >&2; exit 1; }

step "veyon-auth-helper on the system bus (logon authentication)"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -q --no-install-recommends libglib2.0-bin procps > /dev/null

activation=/usr/share/dbus-1/system-services/io.veyon.AuthHelper.service
grep -qx 'Exec=/usr/bin/veyon-auth-helper' "$activation" || fail "Exec of $activation"
unit=$(sed -n 's/^SystemdService=//p' "$activation")
[ -f "/usr/lib/systemd/system/$unit" ] || fail "$activation names $unit, which is not installed"
grep -qx 'ExecStart=/usr/bin/veyon-auth-helper' "/usr/lib/systemd/system/$unit" || fail "ExecStart of $unit"
grep -qx 'BusName=io.veyon.AuthHelper' "/usr/lib/systemd/system/$unit" || fail "BusName of $unit"
ok "$activation starts $unit, which runs /usr/bin/veyon-auth-helper as io.veyon.AuthHelper"

mkdir -p /run/dbus
dbus-daemon --system --fork
id hocsinh > /dev/null 2>&1 || useradd --create-home hocsinh
echo 'hocsinh:Matkhau-123' | chpasswd
/usr/bin/veyon-auth-helper > /tmp/auth-helper.log 2>&1 &
helper=$!
for _ in $(seq 50); do
	gdbus introspect --system --dest io.veyon.AuthHelper --object-path /io/veyon/AuthHelper > /dev/null 2>&1 && break
	sleep 0.2
done
kill -0 "$helper" 2> /dev/null || { cat /tmp/auth-helper.log; fail "veyon-auth-helper exited"; }
ok "veyon-auth-helper owns io.veyon.AuthHelper (the bus policy lets root own it)"

call() {
	gdbus call --system --dest io.veyon.AuthHelper --object-path /io/veyon/AuthHelper \
		--method io.veyon.AuthHelper.Authenticate "$1" "$2" 2>&1
}

answer=$(call "'hocsinh'" "b'Matkhau-123'")
[ "$answer" = "(true,)" ] || fail "right password: $answer"
ok "the right password is accepted (PAM service login)"
answer=$(call "'hocsinh'" "b'sai-mat-khau'")
[ "$answer" = "(false,)" ] || fail "wrong password: $answer"
ok "a wrong password is refused"
answer=$(runuser -u hocsinh -- gdbus call --system --dest io.veyon.AuthHelper --object-path /io/veyon/AuthHelper \
	--method io.veyon.AuthHelper.Authenticate "'hocsinh'" "b'Matkhau-123'" 2>&1 || true)
grep -q 'AccessDenied' <<< "$answer" || fail "a user may call the helper: $answer"
ok "a non-root caller is refused by the bus policy"
kill "$helper" 2> /dev/null || true
pkill -x dbus-daemon || true
printf '\nPASS auth-helper-dbus\n'

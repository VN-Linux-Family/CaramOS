#!/bin/bash
# Veyon Server end to end on a virtual X display, in a test container where the veyon packages are installed and
# Veyon is set up with the lab's keys (key file authentication):
# - Veyon Server runs as veyon-service starts it on X11 (root, the session's DISPLAY) and starts x11vnc;
# - it listens on 11100, the port caramos-lab-veyon-check watches;
# - veyon-cli, as the teacher's Veyon Master would, authenticates with the private key and starts features
#   (TextMessage, ScreenLock) ROUNDS times on the same server, which must stay up.
# There is no logind in a container: Veyon refuses to lock a screen outside a user session, so this does not show
# the lock window itself (that needs a real session, e.g. a VM).
set -euo pipefail

ROUNDS=${1:-20}
step() { printf '\n--- %s\n' "$*"; }
ok() { printf 'ok   %s\n' "$*"; }
fail() { printf 'FAIL %s\n' "$*" >&2; exit 1; }

step "Veyon Server on a virtual X display, $ROUNDS feature starts with key authentication"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -q --no-install-recommends xvfb x11-utils procps >/dev/null

Xvfb :99 -screen 0 1280x800x24 -nolisten tcp > /tmp/xvfb.log 2>&1 &
export DISPLAY=:99
for _ in $(seq 50); do xdpyinfo > /dev/null 2>&1 && break; sleep 0.2; done
xdpyinfo > /dev/null 2>&1 || fail "Xvfb did not start"

veyon-cli config set Logging/LogLevel 5 > /dev/null
veyon-cli config set Logging/LogToStdErr true > /dev/null
veyon-server > /tmp/veyon-server.log 2>&1 &
server=$!
listening() { [ -n "$(ss -Hltn 'sport = :11100')" ]; }
for _ in $(seq 100); do listening && break; sleep 0.2; done
listening || { tail -30 /tmp/veyon-server.log; fail "nothing listens on 11100"; }
ok "veyon-server listens on 11100"
for _ in $(seq 50); do pgrep -x x11vnc > /dev/null && break; sleep 0.2; done
pgrep -a x11vnc || fail "x11vnc (external VNC server) did not start"
ok "x11vnc runs for the display"

started=0
for round in $(seq "$ROUNDS"); do
	if [ $((round % 2)) = 0 ]; then
		output=$(timeout 60 veyon-cli feature start 127.0.0.1 ScreenLock 2>&1) || true
	else
		output=$(timeout 60 veyon-cli feature start 127.0.0.1 TextMessage "{\"text\":\"Xin chào $round\"}" 2>&1) || true
	fi
	grep -q '\[OK\]' <<< "$output" && started=$((started + 1))
	kill -0 "$server" 2> /dev/null || { tail -40 /tmp/veyon-server.log; fail "veyon-server died after round $round"; }
done
[ "$started" = "$ROUNDS" ] || fail "only $started of $ROUNDS feature starts succeeded: $output"
ok "$started feature starts; veyon-server still runs"
successes=$(grep -c 'performKeyAuthentication.*SUCCESS' /tmp/veyon-server.log || true)
[ "$successes" -ge "$ROUNDS" ] || fail "key authentication: $successes successes in the server log"
ok "key file authentication succeeded $successes times (RSA through the QCA plugin)"
! grep -E 'tcache|double free|corrupted|Segmentation fault|Aborted' /tmp/veyon-server.log || fail "memory errors"
grep -m3 -E 'TextMessage|ScreenLock' /tmp/veyon-server.log | cut -c1-200 || true
kill "$server" 2> /dev/null || true
pkill -x x11vnc || true; pkill -x veyon-worker || true; pkill -x Xvfb || true
printf '\nPASS server-e2e\n'

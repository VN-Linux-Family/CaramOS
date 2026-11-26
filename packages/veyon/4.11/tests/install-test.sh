#!/bin/bash
# Install and upgrade test of the veyon packages, run by `make test` in a fresh ubuntu:24.04 container:
#   /debs         the .debs of `make deb`, served as a local APT repository (as the PPA will serve them)
#   /tests        this folder
#   /caramos-ota  the caramos-ota source tree (Phòng máy's code, for lab_cli_check.py)
#
#   install-test.sh fresh        install on plain noble (main + universe, no PPA): the dependencies resolve
#   install-test.sh from-ubuntu  Ubuntu's 4.7.5 set up as Phòng máy does, then the upgrade the OTA migration runs
#   install-test.sh from-ppa     the same from the Veyon the CaramOS PPA has now (4.7.5+repack1-1ubuntu5+caramos1
#                                until 4.11.5 is published there), the PPA enabled
# The version under test is the second argument (the recipe's), so a newer Veyon (tools/upstream.py bump) is tested
# the same way; the daily check (.github/workflows/veyon-upstream.yml) runs this through `make test`.
set -euo pipefail

scenario=$1
version=$2
export DEBIAN_FRONTEND=noninteractive UCF_FORCE_CONFFOLD=1
APT=(apt-get -y -q -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)
PACKAGES=(libveyon-core veyon-plugins veyon-service veyon-master veyon-configurator)
PPA_URL=https://ppa.launchpadcontent.net/vietnamlinuxfamily/caram-os/ubuntu
PPA_KEY=FE19170D8BF3174F9AFC3249CDAC57D9EB35115D
ROOM="Phòng máy 1"

step() { printf '\n--- %s\n' "$*"; }
ok() { printf 'ok   %s\n' "$*"; }
fail() { printf 'FAIL %s\n' "$*" >&2; exit 1; }

installed_version() { dpkg-query -W -f='${db:Status-Abbrev}${Version}' "$1" 2>/dev/null | sed -n 's/^ii *//p'; }

local_repo() {
	mkdir -p /tmp/repo
	cp /debs/*.deb /tmp/repo/
	(cd /tmp/repo && apt-ftparchive packages . > Packages)
	echo 'deb [trusted=yes] file:/tmp/repo ./' > /etc/apt/sources.list.d/local-veyon.list
	apt-get update -qq
}

caramos_ppa() {
	install -d /etc/apt/keyrings
	curl -fsSL --retry 3 --retry-all-errors "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x$PPA_KEY" \
		-o /etc/apt/keyrings/caramos-ppa.asc
	cat > /etc/apt/sources.list.d/caramos-ppa.sources <<-EOF
	Types: deb
	URIs: $PPA_URL
	Suites: noble
	Components: main
	Signed-By: /etc/apt/keyrings/caramos-ppa.asc
	EOF
	apt-get update -qq
}

# The configuration a Phòng máy teacher's computer had with Veyon 4.7.5 (caramos_lab.helper.veyon_teacher).
old_lab_setup() {
	veyon-cli authkeys create giaovien
	veyon-cli authkeys setaccessgroup giaovien/private cogiao
	veyon-cli config set Authentication/Method 1
	veyon-cli config set Master/AutoSelectCurrentLocation true
	veyon-cli networkobjects add location "$ROOM"
	veyon-cli networkobjects add computer may01 192.168.1.11 52:54:00:00:00:11 "$ROOM"
	veyon-cli authkeys export giaovien/public /tmp/old-public.pem
	sha256sum /etc/veyon/keys/private/giaovien/key /etc/veyon/keys/public/giaovien/key > /tmp/old-keys.sha256
}

old_lab_still_there() {
	sha256sum -c --quiet /tmp/old-keys.sha256 || fail "the lab's keys changed in the upgrade"
	local keys
	keys=$(veyon-cli authkeys list)
	grep -q 'giaovien/private' <<< "$keys" && grep -q 'giaovien/public' <<< "$keys" \
		|| fail "$version does not list the keys of $old: $keys"
	[ "$(veyon-cli config get Authentication/Method)" = 1 ] || fail "Authentication/Method lost"
	grep -q may01 <<< "$(veyon-cli networkobjects list)" || fail "the room of $old is gone"
	grep -q '"52:54:00:00:00:11"' <<< "$(veyon-cli config get BuiltinDirectory/NetworkObjects)" \
		|| fail "BuiltinDirectory/NetworkObjects of $old unreadable"
	ok "keys, authentication method and rooms of $old are read by $version"
}

# The upgrade of the OTA migration (20261125120100_veyon_lock_and_demo_show): the installed Veyon packages,
# --only-upgrade --no-install-recommends, dpkg asks nothing.
migration_upgrade() {
	local present=() package
	for package in "${PACKAGES[@]}"; do
		[ -n "$(installed_version "$package")" ] && present+=("$package")
	done
	step "upgrade (as the migration does): ${present[*]}"
	apt-get -s install --no-install-recommends --only-upgrade "${present[@]}" | grep -E '^(Inst|Remv|Conf) ' || true
	"${APT[@]}" install --no-install-recommends --only-upgrade "${present[@]}" 2>&1 | tee /tmp/upgrade.log
	grep -q ' 0 to remove' /tmp/upgrade.log || fail "the upgrade removes packages"
	! grep -q 'REMOVED' /tmp/upgrade.log || fail "the upgrade removes packages"
	ok "no package removed"
}

check_packages() {
	step "packages"
	local package v
	for package in "${PACKAGES[@]}"; do
		v=$(installed_version "$package")
		[ "$v" = "$version" ] || fail "$package is ${v:-not installed}, not $version"
	done
	ok "all five packages are $version"
	[ -z "$(dpkg --audit)" ] || fail "dpkg --audit: $(dpkg --audit)"
	apt-get check -qq || fail "apt-get check"
	ok "dpkg --audit and apt-get check are clean"
	[ -n "$(installed_version libqca-qt6-plugins)" ] || fail "libqca-qt6-plugins (RSA) missing"
	ok "libqca-qt6-plugins installed (a Depends of libveyon-core)"
}

check_files() {
	step "files"
	[ -f /usr/lib/systemd/system/veyon.service ] || fail "no /usr/lib/systemd/system/veyon.service"
	grep -q '^veyon-service:' <<< "$(dpkg -S /usr/lib/systemd/system/veyon.service)" || fail "veyon.service not owned"
	[ -f /usr/lib/systemd/system/veyon-auth-helper.service ] || fail "no veyon-auth-helper.service"
	grep -q '^ExecStart=/usr/bin/veyon-service$' /usr/lib/systemd/system/veyon.service || fail "veyon.service ExecStart"
	ok "veyon.service (same name, /usr/lib/systemd/system) and veyon-auth-helper.service"
	[ "$(stat -c %a /usr/bin/veyon-auth-helper)" = 755 ] || fail "veyon-auth-helper mode $(stat -c %a /usr/bin/veyon-auth-helper)"
	[ "$(stat -c %a /usr/bin/veyon-input-helper)" = 755 ] || fail "veyon-input-helper mode"
	! grep -q veyon <<< "$(dpkg-statoverride --list)" || fail "a veyon statoverride is left: $(dpkg-statoverride --list)"
	ok "no setuid helper, no statoverride left"
	local file missing=0
	for file in /usr/bin/veyon-* /usr/lib/x86_64-linux-gnu/veyon/*.so; do
		if grep -q 'not found' <<< "$(ldd "$file" 2>&1)"; then
			echo "$file:"; ldd "$file" | grep 'not found'; missing=1
		fi
	done
	[ "$missing" = 0 ] || fail "missing libraries"
	ok "every binary and plugin finds its libraries ($(ls /usr/bin/veyon-* /usr/lib/x86_64-linux-gnu/veyon/*.so | wc -l) files)"
}

check_cli() {
	step "veyon-cli"
	local about plugins upstream=${version%%+*}
	about=$(veyon-cli about 2>&1)
	head -5 <<< "$about"
	grep -qF "$upstream" <<< "$about" || fail "veyon-cli about does not say $upstream"
	ok "veyon-cli about reports $upstream"
	plugins=$(veyon-cli plugin list 2>&1)
	echo "$plugins"
	! grep -qiE 'incompatible|cannot load|could not load|not loaded|error' <<< "$plugins" || fail "plugin errors"
	local name
	for name in AuthKeys BuiltinDirectory ScreenLock Demo RemoteAccess LinuxPlatform; do
		grep -qi "$name" <<< "$plugins" || fail "plugin $name not listed"
	done
	ok "plugins load: $(grep -ciE '^[[:space:]]*[a-z]' <<< "$plugins") lines, no errors"
}

# No systemd in the container: a systemctl that says the system is running and logs what it is asked. Veyon 4.11
# calls /usr/bin/systemctl itself (Service/Autostart when it saves its configuration), the lab helper calls systemctl.
fake_systemctl() {
	cat > /usr/bin/systemctl <<-'EOF'
	#!/bin/sh
	[ "$1" = --no-pager ] && shift
	[ "$1" = -q ] && shift
	case "$1" in is-system-running) echo running; exit 0;; esac
	echo "systemctl $*" >> /tmp/systemctl.log
	EOF
	chmod 755 /usr/bin/systemctl
}

purge_check() {
	step "purge"
	"${APT[@]}" purge "${PACKAGES[@]}" 2>&1 | tail -2
	local package
	for package in "${PACKAGES[@]}"; do
		[ -z "$(installed_version "$package")" ] || fail "$package still installed"
	done
	[ ! -e /etc/veyon ] && [ ! -e "/etc/xdg/Veyon Solutions" ] || fail "configuration left after purge"
	[ ! -e /usr/lib/systemd/system/veyon.service ] || fail "veyon.service left after purge"
	[ -z "$(dpkg --audit)" ] || fail "dpkg --audit after purge: $(dpkg --audit)"
	ok "purge removes the packages, /etc/veyon and the Veyon configuration"
}

lab_check() {
	step "Phòng máy (caramos_lab.helper) against veyon-cli $version"
	# systemd may be installed (pkexec pulls it in) but does not run here
	[ ! -e /usr/bin/systemctl ] || mv /usr/bin/systemctl /usr/bin/systemctl.real
	fake_systemctl
	python3 -I /tests/lab_cli_check.py /caramos-ota cogiao
	rm -f /usr/bin/systemctl
	[ ! -e /usr/bin/systemctl.real ] || mv /usr/bin/systemctl.real /usr/bin/systemctl
}

step "scenario $scenario, expecting $version"
echo 'Acquire::Retries "3";' > /etc/apt/apt.conf.d/80retries
apt-get update -qq
"${APT[@]}" install --no-install-recommends apt-utils ca-certificates curl python3 iproute2 >/dev/null
useradd --create-home cogiao

case "$scenario" in
fresh)
	local_repo
	step "install veyon-service veyon-master veyon-configurator on plain noble"
	"${APT[@]}" install --no-install-recommends veyon-service veyon-master veyon-configurator 2>&1 | tail -3
	apt-cache policy "${PACKAGES[@]}" | grep -E '^[a-z]|Installed|Candidate'
	check_packages
	check_files
	check_cli
	veyon-cli authkeys create giaovien > /dev/null
	veyon-cli config set Authentication/Method 1 > /dev/null
	bash /tests/server-e2e.sh 20
	bash /tests/auth-helper-dbus.sh
	lab_check
	purge_check
	;;
from-ubuntu | from-ppa)
	if [ "$scenario" = from-ppa ]; then
		caramos_ppa
		old=$(apt-cache policy veyon-service | sed -n 's/^ *Candidate: //p')
		[ -n "$old" ] && [ "$old" != "(none)" ] || fail "the CaramOS PPA has no veyon-service"
		step "Veyon $old, the one of the CaramOS PPA, as Phòng máy installs it (teacher)"
		[ "$old" != "$version" ] || echo "note: the PPA has $version already; the upgrade has nothing to do"
		"${APT[@]}" install --no-install-recommends veyon-service="$old" veyon-master="$old" \
			veyon-configurator="$old" libveyon-core="$old" veyon-plugins="$old" libqca-qt5-2-plugins >/dev/null
	else
		step "Veyon 4.7.5 from Ubuntu 24.04, as Phòng máy installs it (teacher)"
		"${APT[@]}" install --no-install-recommends veyon-service veyon-master veyon-configurator \
			libqca-qt5-2-plugins >/dev/null
		old=$(installed_version libveyon-core)
	fi
	echo "installed: libveyon-core $(installed_version libveyon-core)"
	[ "$(stat -c %a /usr/bin/veyon-auth-helper)" = 4755 ] && ok "4.7.5: veyon-auth-helper is setuid (statoverride)"
	ls -l /lib/systemd/system/veyon.service
	old_lab_setup
	local_repo
	migration_upgrade
	check_packages
	check_files
	old_lab_still_there
	check_cli
	bash /tests/server-e2e.sh 20
	lab_check
	;;
*)
	fail "unknown scenario $scenario"
	;;
esac

printf '\nPASS %s\n' "$scenario"

SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

PACKAGE := printer-driver-captdriver
PPA ?= ppa:vietnamlinuxfamily/caram-os
GPG_KEY ?= ledungb11@gmail.com
BUILD_IMAGE ?= ubuntu:24.04

# Upstream captdriver, pinned by commit: changes upstream reach CaramOS only through make bump
# (README, "Bảo trì"). git archive + gzip -n give the same bytes on every run; the checksum checks that,
# because Launchpad refuses an orig tarball that differs from the one it already has for this version.
UPSTREAM_URL := https://github.com/mounaiban/captdriver.git
UPSTREAM_BRANCH := 0.2.1-pr
UPSTREAM_COMMIT := f2d2da812d8d5344030a1898a15d856d4f7a5c3b
ORIG_SHA256 := 68de01065349918b78fe3b22ae4a288bfa0baa50f448ab2d9d2b8d7a4871e7ce

VERSION := $(shell dpkg-parsechangelog -S Version)
UPSTREAM_VERSION := $(shell dpkg-parsechangelog -S Version | sed 's/-[^-]*$$//')
BUILD := build
ORIG := $(BUILD)/$(PACKAGE)_$(UPSTREAM_VERSION).orig.tar.gz
TREE := $(BUILD)/$(PACKAGE)-$(UPSTREAM_VERSION)
UID_GID := $(shell id -u):$(shell id -g)

.PHONY: help orig tree source deb test upload clean check-upstream record-upstream bump

help:
	@printf '%s\n' 'printer-driver-captdriver: captdriver for Canon CAPT printers (LBP2900...)' '' \
	  '  make orig     Fetch upstream at the pinned commit and make the orig tarball' \
	  '  make source   Build the source package for the PPA (build/*.dsc, build/*_source.changes)' \
	  '  make deb      Build the .deb in an Ubuntu 24.04 container (build/*.deb)' \
	  '  make test     Install the .deb in a container: PPD check and device ID matching' \
	  '  make upload   Sign and upload the source package to $(PPA)' \
	  '  make clean    Remove build/' '' \
	  '  make check-upstream   What changed upstream since the last review (upstream-refs.txt)' \
	  '  make record-upstream  Save the current upstream state as reviewed' \
	  '  make bump [COMMIT=<id>] [BRANCH=<branch>] [URL=<repo>] [NEW_VERSION=<version>]' \
	  '                        Move the pin to a new upstream commit, by default the head of $(UPSTREAM_BRANCH)'

orig: $(ORIG)

$(ORIG):
	mkdir -p $(BUILD)
	tmp="$$(mktemp -d)"; trap 'rm -rf "$$tmp"' EXIT; \
	  git -C "$$tmp" init -q; \
	  git -C "$$tmp" fetch -q --depth 1 '$(UPSTREAM_URL)' '$(UPSTREAM_COMMIT)'; \
	  test "$$(git -C "$$tmp" rev-parse FETCH_HEAD)" = '$(UPSTREAM_COMMIT)'; \
	  git -C "$$tmp" archive --format=tar --prefix='$(PACKAGE)-$(UPSTREAM_VERSION)/' FETCH_HEAD \
	    | gzip -n -9 > '$@.part'
	echo '$(ORIG_SHA256)  $@.part' | sha256sum -c --quiet
	mv '$@.part' '$@'

tree: $(ORIG)
	rm -rf '$(TREE)'
	tar -xzf '$(ORIG)' -C $(BUILD)
	cp -a debian '$(TREE)/'

source: tree
	cd '$(TREE)' && dpkg-buildpackage -S -sa -d -us -uc
	@ls -1 $(BUILD)/$(PACKAGE)_$(VERSION)*

deb: tree
	docker run --rm -v '$(CURDIR)/$(BUILD):/build' $(BUILD_IMAGE) bash -euo pipefail -c '\
	  trap "chown -R $(UID_GID) /build" EXIT; \
	  export DEBIAN_FRONTEND=noninteractive; \
	  apt-get update -qq; \
	  apt-get install -y -qq --no-install-recommends build-essential devscripts equivs fakeroot >/dev/null; \
	  cd /tmp && mk-build-deps -i -r -t "apt-get -y -qq --no-install-recommends" \
	    "/build/$(PACKAGE)-$(UPSTREAM_VERSION)/debian/control" >/dev/null; \
	  cd "/build/$(PACKAGE)-$(UPSTREAM_VERSION)" && dpkg-buildpackage -b -us -uc'
	@ls -1 $(BUILD)/$(PACKAGE)_$(VERSION)_*.deb

# cupstestppd on each PPD, then what the automatic printer setup asks: which PPD fits the device ID
# an LBP2900 reports (cupshelpers, as udev-add-printer and system-config-printer use it).
test:
	@test -f '$(BUILD)/$(PACKAGE)_$(VERSION)_amd64.deb' || { echo 'Run: make deb' >&2; exit 1; }
	docker run --rm -v '$(CURDIR)/$(BUILD):/build:ro' -v '$(CURDIR)/tests:/tests:ro' $(BUILD_IMAGE) bash -euo pipefail -c '\
	  export DEBIAN_FRONTEND=noninteractive; \
	  apt-get update -qq; \
	  apt-get install -y -qq --no-install-recommends cups cups-client python3-cupshelpers \
	    "/build/$(PACKAGE)_$(VERSION)_amd64.deb" >/dev/null; \
	  for ppd in /usr/share/ppd/captdriver/*.ppd; do cupstestppd -W translations "$$ppd"; done; \
	  /usr/sbin/cupsd; sleep 2; \
	  python3 /tests/match-device-id.py'

upload:
	changes='$(BUILD)/$(PACKAGE)_$(VERSION)_source.changes'; \
	  test -f "$$changes" || { echo 'Run: make source' >&2; exit 1; }; \
	  gpg --verify "$$changes" >/dev/null 2>&1 || debsign -k'$(GPG_KEY)' "$$changes"; \
	  dput '$(PPA)' "$$changes"

clean:
	rm -rf $(BUILD)

# Keeping up with upstream: README, "Bảo trì".
check-upstream:
	python3 -I tools/upstream.py check --url '$(UPSTREAM_URL)' --branch '$(UPSTREAM_BRANCH)' --commit '$(UPSTREAM_COMMIT)'

record-upstream:
	python3 -I tools/upstream.py record --url '$(UPSTREAM_URL)'

bump:
	python3 -I tools/upstream.py bump --url '$(or $(URL),$(UPSTREAM_URL))' --branch '$(or $(BRANCH),$(UPSTREAM_BRANCH))' \
	  $(if $(COMMIT),--commit '$(COMMIT)') $(if $(NEW_VERSION),--version '$(NEW_VERSION)')

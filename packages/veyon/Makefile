SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

PACKAGE := veyon
PPA ?= ppa:vietnamlinuxfamily/caram-os
GPG_KEY ?= ledungb11@gmail.com
BUILD_IMAGE ?= ubuntu:24.04
# Ubuntu 24.04's Veyon, and this package's version on top of it: higher, so that apt prefers the PPA's. An Ubuntu
# update of veyon (4.7.5+repack1-1ubuntu5.x) sorts higher again and replaces it; then this package has to be made
# again on top of that update (UBUNTU_VERSION, VERSION).
UBUNTU_VERSION := 4.7.5+repack1-1ubuntu5
VERSION := 4.7.5+repack1-1ubuntu5+caramos1
ORIG := $(PACKAGE)_4.7.5+repack1.orig.tar.xz
# Applied in this order (the last two change the same file).
PATCHES := caramos-lockwidget-show-after-raise.patch caramos-restart-crashed-server.patch \
	caramos-restart-server-after-session-closes.patch
BUILD := build
UID_GID := $(shell id -u):$(shell id -g)

.PHONY: help source deb upload

help:
	@printf '%s\n' 'veyon: Ubuntu 24.04 Veyon whose Lock and full-screen Demo show, and whose server comes back' '' \
	  '  make source      Build the source package for the PPA (build/*.dsc, build/*_source.changes)' \
	  '  make deb         Build the .debs from it in an Ubuntu 24.04 container (build/debs/)' \
	  '  make upload      Sign and upload the source package to $(PPA)'

# Ubuntu's source of UBUNTU_VERSION, the patches added to its debian/patches, a changelog entry for VERSION. Files of
# an earlier run in build/ are overwritten.
source:
	mkdir -p $(BUILD)
	docker run --rm -v '$(CURDIR)':/pkg:ro -v '$(CURDIR)/$(BUILD)':/out $(BUILD_IMAGE) bash -euo pipefail -c '\
	  export DEBIAN_FRONTEND=noninteractive; \
	  sed -i "s/^Types: deb$$/Types: deb deb-src/" /etc/apt/sources.list.d/ubuntu.sources; \
	  apt-get update -qq; apt-get install -y -qq dpkg-dev devscripts >/dev/null; \
	  cd /tmp; apt-get source -qq --download-only $(PACKAGE)=$(UBUNTU_VERSION) >/dev/null 2>&1; \
	  dpkg-source -x $(PACKAGE)_$(UBUNTU_VERSION).dsc src >/dev/null; cd src; \
	  test "$$(dpkg-parsechangelog -S Version)" = "$(UBUNTU_VERSION)"; \
	  test "$$(cat debian/source/format)" = "3.0 (quilt)"; \
	  for patch in $(PATCHES); do cp /pkg/patches/$$patch debian/patches/; echo $$patch >> debian/patches/series; done; \
	  { printf "$(PACKAGE) ($(VERSION)) noble; urgency=medium\n\n"; cat /pkg/changelog-entry.txt; \
	    printf "\n -- Vietnam Linux Family <developer@vietnamlinuxfamily.net>  %s\n\n" "$$(date -R)"; \
	    cat debian/changelog; } > /tmp/changelog; mv /tmp/changelog debian/changelog; \
	  dpkg-buildpackage -S -sa -d -us -uc -nc > /out/source.log 2>&1 || { tail -30 /out/source.log; exit 1; }; \
	  cp ../$(PACKAGE)_$(VERSION).dsc ../$(PACKAGE)_$(VERSION).debian.tar.xz ../$(PACKAGE)_$(VERSION)_source.* \
	     ../$(ORIG) /out/; \
	  chown -R $(UID_GID) /out'
	@ls -1 $(BUILD)

# The binary packages of build/'s source, for a test in a VM (Launchpad builds the PPA's).
deb:
	test -f $(BUILD)/$(PACKAGE)_$(VERSION).dsc
	mkdir -p $(BUILD)/debs
	docker run --rm -v '$(CURDIR)/$(BUILD)':/build $(BUILD_IMAGE) bash -euo pipefail -c '\
	  export DEBIAN_FRONTEND=noninteractive; \
	  sed -i "s/^Types: deb$$/Types: deb deb-src/" /etc/apt/sources.list.d/ubuntu.sources; \
	  apt-get update -qq; apt-get install -y -qq dpkg-dev >/dev/null; \
	  cd /tmp; dpkg-source -x /build/$(PACKAGE)_$(VERSION).dsc src >/dev/null; cd src; \
	  apt-get build-dep -y -qq . >/dev/null 2>&1; \
	  DEB_BUILD_OPTIONS="nocheck parallel=$$(nproc)" dpkg-buildpackage -b -uc -us > /build/deb.log 2>&1 \
	    || { tail -30 /build/deb.log; exit 1; }; \
	  cp ../*.deb /build/debs/; chown -R $(UID_GID) /build'
	@ls -1 $(BUILD)/debs

upload:
	test -f $(BUILD)/$(PACKAGE)_$(VERSION)_source.changes
	if ! gpg --verify $(BUILD)/$(PACKAGE)_$(VERSION)_source.changes >/dev/null 2>&1; then \
	  debsign -k'$(GPG_KEY)' $(BUILD)/$(PACKAGE)_$(VERSION)_source.changes; \
	fi
	dput '$(PPA)' $(BUILD)/$(PACKAGE)_$(VERSION)_source.changes

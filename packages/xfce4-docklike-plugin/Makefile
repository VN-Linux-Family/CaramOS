SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

PACKAGE := xfce4-docklike-plugin
PPA ?= ppa:vietnamlinuxfamily/caram-os
GPG_KEY ?= ledungb11@gmail.com
BUILD_IMAGE ?= ubuntu:24.04

# The upstream release tarball, pinned by its checksum. Its hand-written sources (src/) are the same as the git tag
# xfce4-docklike-plugin-0.4.2 on gitlab.xfce.org, whose archive has the SHA-256 that FreeBSD ports recorded
# (94229e9a1f96220c3be18269575c9a3b615fdd24ba939e74f613fb212a1b8950, ports commit 2f999a13).
UPSTREAM_URL := https://archive.xfce.org/src/panel-plugins/xfce4-docklike-plugin/0.4/xfce4-docklike-plugin-0.4.2.tar.bz2
ORIG_SHA256 := b6a40b976a78f2abb1bec057c48d45bfb317e00b12e05a7dfcbea4d183f8db71

VERSION := $(shell dpkg-parsechangelog -S Version)
UPSTREAM_VERSION := $(shell dpkg-parsechangelog -S Version | sed 's/-[^-]*$$//')
BUILD := build
ORIG := $(BUILD)/$(PACKAGE)_$(UPSTREAM_VERSION).orig.tar.bz2
TREE := $(BUILD)/$(PACKAGE)-$(UPSTREAM_VERSION)
UID_GID := $(shell id -u):$(shell id -g)

.PHONY: help orig tree source deb upload clean

help:
	@printf '%s\n' 'xfce4-docklike-plugin: the middle island (pinned and running apps) of the CaramOS Xfce taskbar' '' \
	  '  make orig     Download the pinned upstream tarball (build/*.orig.tar.bz2)' \
	  '  make source   Build the source package for the PPA (build/*.dsc, build/*_source.changes)' \
	  '  make deb      Build the .deb in an Ubuntu 24.04 container (build/*.deb)' \
	  '  make upload   Sign and upload the source package to $(PPA)' \
	  '  make clean    Remove build/'

orig: $(ORIG)

$(ORIG):
	mkdir -p $(BUILD)
	curl -fsSL -o '$@.part' '$(UPSTREAM_URL)'
	echo '$(ORIG_SHA256)  $@.part' | sha256sum -c --quiet
	mv '$@.part' '$@'

tree: $(ORIG)
	rm -rf '$(TREE)'
	tar -xjf '$(ORIG)' -C $(BUILD)
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

upload:
	changes='$(BUILD)/$(PACKAGE)_$(VERSION)_source.changes'; \
	  test -f "$$changes" || { echo 'Run: make source' >&2; exit 1; }; \
	  gpg --verify "$$changes" >/dev/null 2>&1 || debsign -k'$(GPG_KEY)' "$$changes"; \
	  dput '$(PPA)' "$$changes"

clean:
	rm -rf $(BUILD)

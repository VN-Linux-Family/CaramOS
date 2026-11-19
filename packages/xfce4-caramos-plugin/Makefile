SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

PACKAGE := xfce4-caramos-plugin
PPA ?= ppa:vietnamlinuxfamily/caram-os
GPG_KEY ?= ledungb11@gmail.com
BUILD_IMAGE ?= ubuntu:24.04

# A native package: its source is this folder. The build happens in a copy under build/, so this folder stays clean.
VERSION := $(shell dpkg-parsechangelog -S Version)
BUILD := build
TREE := $(BUILD)/$(PACKAGE)-$(VERSION)
UID_GID := $(shell id -u):$(shell id -g)

.PHONY: help tree source deb upload clean

help:
	@printf '%s\n' 'xfce4-caramos-plugin: the CaramOS Control Center button of the CaramOS Xfce taskbar' '' \
	  '  make source   Build the source package for the PPA (build/*.dsc, build/*_source.changes)' \
	  '  make deb      Build the .deb in an Ubuntu 24.04 container (build/*.deb)' \
	  '  make upload   Sign and upload the source package to $(PPA)' \
	  '  make clean    Remove build/'

tree:
	rm -rf '$(TREE)'
	mkdir -p '$(TREE)'
	cp -a debian src '$(TREE)/'

source: tree
	cd '$(TREE)' && dpkg-buildpackage -S -d -us -uc
	@ls -1 $(BUILD)/$(PACKAGE)_$(VERSION)*

deb: tree
	docker run --rm -v '$(CURDIR)/$(BUILD):/build' $(BUILD_IMAGE) bash -euo pipefail -c '\
	  trap "chown -R $(UID_GID) /build" EXIT; \
	  export DEBIAN_FRONTEND=noninteractive; \
	  apt-get update -qq; \
	  apt-get install -y -qq --no-install-recommends build-essential devscripts equivs fakeroot >/dev/null; \
	  cd /tmp && mk-build-deps -i -r -t "apt-get -y -qq --no-install-recommends" \
	    "/build/$(PACKAGE)-$(VERSION)/debian/control" >/dev/null; \
	  cd "/build/$(PACKAGE)-$(VERSION)" && dpkg-buildpackage -b -us -uc'
	@ls -1 $(BUILD)/$(PACKAGE)_$(VERSION)_*.deb

upload:
	changes='$(BUILD)/$(PACKAGE)_$(VERSION)_source.changes'; \
	  test -f "$$changes" || { echo 'Run: make source' >&2; exit 1; }; \
	  gpg --verify "$$changes" >/dev/null 2>&1 || debsign -k'$(GPG_KEY)' "$$changes"; \
	  dput '$(PPA)' "$$changes"

clean:
	rm -rf $(BUILD)

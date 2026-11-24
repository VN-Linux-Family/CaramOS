SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

PACKAGE := fastfetch
PPA ?= ppa:vietnamlinuxfamily/caram-os
GPG_KEY ?= ledungb11@gmail.com
BUILD_IMAGE ?= ubuntu:24.04
# `make deb` installs the build dependencies into this local image (with network), then builds the package in it with
# --network none, as on Launchpad, whose builders have no network.
DEPS_IMAGE ?= caramos-fastfetch-builddeps:noble
DEPS_CONTAINER := caramos-fastfetch-builddeps

VERSION := $(shell dpkg-parsechangelog -S Version)
UPSTREAM_VERSION := $(shell dpkg-parsechangelog -S Version | sed 's/-[^-]*$$//')

# The upstream release: GitHub's archive of the tag (upstream publishes no other source tarball), pinned by its
# checksum. Unlike Debian's +dfsg tarball it keeps src/3rdparty, whose yyjson this package builds (see debian/rules).
UPSTREAM_URL := https://github.com/fastfetch-cli/fastfetch/archive/refs/tags/$(UPSTREAM_VERSION).tar.gz
ORIG_SHA256 := e71d93de41e8e4b2554c36d2ae51758112a21ecf3a8c98605a2c689251e62987

BUILD := build
ORIG := $(BUILD)/$(PACKAGE)_$(UPSTREAM_VERSION).orig.tar.gz
TREE := $(BUILD)/$(PACKAGE)-$(UPSTREAM_VERSION)
UID_GID := $(shell id -u):$(shell id -g)

.PHONY: help orig tree source deps-image deb upload clean

help:
	@printf '%s\n' 'fastfetch: fastfetch for Ubuntu 24.04 with the CaramOS logo (ticket H-1203)' '' \
	  '  make orig        Download the pinned upstream tarball (build/*.orig.tar.gz)' \
	  '  make source      Build the source package for the PPA (build/*.dsc, build/*_source.changes)' \
	  '  make deb         Build the .deb in an Ubuntu 24.04 container without network (build/*.deb)' \
	  '  make upload      Sign and upload the source package to $(PPA)' \
	  '  make clean       Remove build/'

orig: $(ORIG)

$(ORIG):
	mkdir -p $(BUILD)
	curl -fsSL -o '$@.part' '$(UPSTREAM_URL)'
	echo '$(ORIG_SHA256)  $@.part' | sha256sum -c --quiet
	mv '$@.part' '$@'

# The upstream tarball has a debian/ of its own (the template of the upstream author's PPA): replace it, so that
# none of its files end up in our debian.tar.
tree: $(ORIG)
	rm -rf '$(TREE)'
	tar -xzf '$(ORIG)' -C $(BUILD)
	rm -rf '$(TREE)/debian'
	cp -a debian '$(TREE)/'

source: tree
	cd '$(TREE)' && dpkg-buildpackage -S -sa -d -us -uc
	@ls -1 $(BUILD)/$(PACKAGE)_$(VERSION)*

deps-image:
	docker rm -f $(DEPS_CONTAINER) >/dev/null 2>&1 || true
	docker run --name $(DEPS_CONTAINER) -v '$(CURDIR)/debian/control:/tmp/control:ro' $(BUILD_IMAGE) bash -euo pipefail -c '\
	  export DEBIAN_FRONTEND=noninteractive; \
	  apt-get update -qq; \
	  apt-get install -y -qq --no-install-recommends build-essential devscripts equivs fakeroot >/dev/null; \
	  cd /tmp && mk-build-deps -i -r -t "apt-get -y -qq --no-install-recommends" /tmp/control >/dev/null; \
	  apt-get clean; rm -rf /var/lib/apt/lists/*'
	docker commit $(DEPS_CONTAINER) '$(DEPS_IMAGE)' >/dev/null
	docker rm $(DEPS_CONTAINER) >/dev/null

deb: tree deps-image
	docker run --rm --network none -v '$(CURDIR)/$(BUILD):/build' '$(DEPS_IMAGE)' bash -euo pipefail -c '\
	  trap "chown -R $(UID_GID) /build" EXIT; \
	  cd "/build/$(PACKAGE)-$(UPSTREAM_VERSION)" && dpkg-buildpackage -b -us -uc'
	@ls -1 $(BUILD)/$(PACKAGE)_$(VERSION)_*.deb

upload:
	changes='$(BUILD)/$(PACKAGE)_$(VERSION)_source.changes'; \
	  test -f "$$changes" || { echo 'Run: make source' >&2; exit 1; }; \
	  gpg --verify "$$changes" >/dev/null 2>&1 || debsign -k'$(GPG_KEY)' "$$changes"; \
	  dput '$(PPA)' "$$changes"

clean:
	rm -rf $(BUILD)

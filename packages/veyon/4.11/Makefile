SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

PACKAGE := veyon
PPA ?= ppa:vietnamlinuxfamily/caram-os
GPG_KEY ?= ledungb11@gmail.com
BUILD_IMAGE ?= ubuntu:24.04
# `make deb` installs the build dependencies into this local image (with network), then builds the binary packages
# from the source package in it with --network none, as a non-root user whose home does not exist, in C.UTF-8: as on
# Launchpad.
DEPS_IMAGE ?= caramos-veyon-builddeps:noble
DEPS_CONTAINER := caramos-veyon-builddeps

VERSION := $(shell dpkg-parsechangelog -l debian/changelog -S Version)
UPSTREAM_VERSION := $(shell dpkg-parsechangelog -l debian/changelog -S Version | sed 's/+repack[0-9]*-[^-]*$$//')
ORIG_VERSION := $(UPSTREAM_VERSION)+repack1

# Upstream's release tarball, with the git submodules (3rdparty/), pinned by the SHA-256 that GitHub shows for the
# release asset (upstream signs neither the tarball nor the tag). It equals the tag's tree plus CONTRIBUTORS and
# re-serialized translations. mk-origtargz removes the Files-Excluded of debian/copyright from it.
UPSTREAM_TARBALL := $(PACKAGE)-$(UPSTREAM_VERSION)-src.tar.bz2
UPSTREAM_URL := https://github.com/veyon/veyon/releases/download/v$(UPSTREAM_VERSION)/$(UPSTREAM_TARBALL)
UPSTREAM_SHA256 := 3530b7ed47f22049981d4482e5a4517bf35d88261a12651d5c2fa3d983e5bd6c

BUILD := build
DOWNLOAD := $(BUILD)/upstream/$(UPSTREAM_TARBALL)
ORIG := $(BUILD)/$(PACKAGE)_$(ORIG_VERSION).orig.tar.xz
DSC := $(BUILD)/$(PACKAGE)_$(VERSION).dsc
DEBS := $(BUILD)/debs
UID_GID := $(shell id -u):$(shell id -g)
# e.g. DEB_BUILD_EXTRA=nocheck for a quicker build without upstream's unit tests (Launchpad runs them)
DEB_BUILD_EXTRA ?=
CARAMOS_OTA := $(abspath ../../caramos-ota)
# tests/install-test.sh: plain noble; upgrade from Ubuntu's 4.7.5; upgrade from the Veyon the PPA has now
SCENARIOS ?= fresh from-ubuntu from-ppa

.PHONY: help orig source deps-image deps-image-build deb test upload clean check-upstream bump test-tools

help:
	@printf '%s\n' 'veyon: Veyon $(UPSTREAM_VERSION) for Ubuntu 24.04 (CaramOS Phòng máy), packaging from Debian' '' \
	  '  make orig        Download the pinned upstream tarball and repack it (build/*.orig.tar.xz)' \
	  '  make source      Build the source package for the PPA (build/*.dsc, build/*_source.changes)' \
	  '  make deb         Build the .debs from that source package as Launchpad does (build/debs/)' \
	  '  make test        Upgrade from Ubuntu 4.7.5 and from the PPA'"'"'s Veyon, fresh install, Phòng máy CLI' \
	  '  make upload      Sign and upload the source package to $(PPA)' \
	  '  make clean       Remove build/' '' \
	  '  make check-upstream   Is there a newer stable Veyon release? (exit 1: yes)' \
	  '  make bump [NEW=x.y.z] Move the recipe to that release (the newest without NEW): changelog, sha256 pin' \
	  '  make test-tools       Unit tests of tools/upstream.py'

$(DOWNLOAD):
	mkdir -p $(dir $@)
	curl -fsSL -o '$@.part' '$(UPSTREAM_URL)'
	echo '$(UPSTREAM_SHA256)  $@.part' | sha256sum -c --quiet
	mv '$@.part' '$@'

orig: $(ORIG)

# Made once: the PPA keeps the first upload's orig tarball, and a different one under the same name is refused.
# mk-origtargz repacks reproducibly (sha256 52f69bbc… for 4.11.5+repack1); a change of Files-Excluded needs +repack2.
$(ORIG): | $(DOWNLOAD)
	docker run --rm -v '$(CURDIR)/debian/copyright:/tmp/copyright:ro' -v '$(CURDIR)/$(BUILD):/build' \
	  $(BUILD_IMAGE) bash -euo pipefail -c '\
	  trap "chown -R $(UID_GID) /build" EXIT; \
	  export DEBIAN_FRONTEND=noninteractive; \
	  apt-get update -qq; apt-get install -y -qq --no-install-recommends devscripts xz-utils bzip2 >/dev/null; \
	  mk-origtargz --package $(PACKAGE) --version $(UPSTREAM_VERSION) --repack --compression xz \
	    --repack-suffix +repack1 --copyright-file /tmp/copyright --directory /build --copy \
	    /build/upstream/$(UPSTREAM_TARBALL)'
	test -f '$@'

# dpkg-source applies debian/patches and packs debian/ (-nc: the fresh tree needs no clean).
source: $(ORIG)
	docker run --rm -v '$(CURDIR)/debian:/tmp/debian:ro' -v '$(CURDIR)/$(BUILD):/build' $(BUILD_IMAGE) \
	  bash -euo pipefail -c '\
	  trap "chown -R $(UID_GID) /build" EXIT; \
	  export DEBIAN_FRONTEND=noninteractive; \
	  apt-get update -qq; apt-get install -y -qq --no-install-recommends dpkg-dev xz-utils >/dev/null; \
	  mkdir -p /tmp/area/src; cp /build/$(notdir $(ORIG)) /tmp/area/; \
	  tar -xJf /tmp/area/$(notdir $(ORIG)) -C /tmp/area/src --strip-components=1; \
	  cp -a /tmp/debian /tmp/area/src/; cd /tmp/area/src; \
	  test "$$(dpkg-parsechangelog -S Version)" = "$(VERSION)"; \
	  dpkg-buildpackage -S -sa -d -us -uc -nc > /build/source.log 2>&1 || { tail -30 /build/source.log; exit 1; }; \
	  cp ../$(PACKAGE)_$(VERSION).dsc ../$(PACKAGE)_$(VERSION).debian.tar.xz ../$(PACKAGE)_$(VERSION)_source.* /build/'
	@ls -1 $(BUILD)/$(PACKAGE)_$(VERSION)*

# Rebuilt only when debian/control changed (the image carries the checksum of the control file it was made from).
deps-image:
	sum=$$(sha256sum debian/control | cut -d' ' -f1); \
	  if [ "$$(docker image inspect -f '{{index .Config.Labels "control-sha256"}}' '$(DEPS_IMAGE)' 2>/dev/null)" = "$$sum" ]; then \
	    echo '$(DEPS_IMAGE) is up to date'; exit 0; fi; \
	  docker rm -f $(DEPS_CONTAINER) >/dev/null 2>&1 || true; \
	  $(MAKE) --no-print-directory deps-image-build CONTROL_SHA256=$$sum

deps-image-build:
	docker rm -f $(DEPS_CONTAINER) >/dev/null 2>&1 || true
	docker run --name $(DEPS_CONTAINER) -v '$(CURDIR)/debian/control:/tmp/control:ro' $(BUILD_IMAGE) bash -euo pipefail -c '\
	  export DEBIAN_FRONTEND=noninteractive; \
	  apt-get update -qq; \
	  apt-get install -y -qq --no-install-recommends build-essential devscripts equivs >/dev/null; \
	  cd /tmp && mk-build-deps -i -r -t "apt-get -y -qq --no-install-recommends" /tmp/control >/dev/null; \
	  apt-get clean; rm -rf /var/lib/apt/lists/*'
	docker commit --change 'LABEL control-sha256=$(CONTROL_SHA256)' $(DEPS_CONTAINER) '$(DEPS_IMAGE)' >/dev/null
	docker rm $(DEPS_CONTAINER) >/dev/null

# From the .dsc, as Launchpad does: no network, a build user whose home (in passwd and $$HOME) does not exist,
# C.UTF-8, the tests on (no nocheck). build/deb.log is the build log.
deb: deps-image
	test -f '$(DSC)' || { echo 'Run: make source' >&2; exit 1; }
	rm -rf '$(DEBS)'; mkdir -p '$(DEBS)'
	docker run --rm --network none -v '$(CURDIR)/$(BUILD):/build' '$(DEPS_IMAGE)' bash -euo pipefail -c '\
	  trap "chown -R $(UID_GID) /build" EXIT; \
	  useradd --no-create-home --home-dir /sbuild-nonexistent --shell /bin/sh buildd; \
	  install -d -o buildd -g buildd /build-area; \
	  runuser -u buildd -- dpkg-source -x /build/$(notdir $(DSC)) /build-area/$(PACKAGE)-$(ORIG_VERSION) >/dev/null; \
	  cd /build-area/$(PACKAGE)-$(ORIG_VERSION); \
	  runuser -u buildd -- env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin HOME=/sbuild-nonexistent \
	    LANG=C.UTF-8 LC_ALL=C.UTF-8 DEB_BUILD_OPTIONS="parallel=$$(nproc) $(DEB_BUILD_EXTRA)" \
	    dpkg-buildpackage -us -uc -b > /build/deb.log 2>&1 || { tail -60 /build/deb.log; exit 1; }; \
	  cp /build-area/*.deb /build-area/*.buildinfo /build-area/*.changes /build/debs/; \
	  cp /build-area/*.ddeb /build/debs/ 2>/dev/null || true'
	@ls -1 $(DEBS)

# Each test starts from a fresh ubuntu:24.04 container (with network, for the archive and the PPA).
test:
	test -n "$$(ls $(DEBS)/*.deb 2>/dev/null)" || { echo 'Run: make deb' >&2; exit 1; }
	for scenario in $(SCENARIOS); do \
	  echo "=== $$scenario"; \
	  docker run --rm -v '$(CURDIR)/$(DEBS):/debs:ro' -v '$(CURDIR)/tests:/tests:ro' \
	    -v '$(CARAMOS_OTA):/caramos-ota:ro' $(BUILD_IMAGE) bash /tests/install-test.sh "$$scenario" '$(VERSION)' \
	    2>&1 | tee '$(BUILD)/test-'"$$scenario"'.log'; \
	done
	@echo 'all scenarios passed'

upload:
	changes='$(BUILD)/$(PACKAGE)_$(VERSION)_source.changes'; \
	  test -f "$$changes" || { echo 'Run: make source' >&2; exit 1; }; \
	  gpg --verify "$$changes" >/dev/null 2>&1 || debsign -k'$(GPG_KEY)' "$$changes"; \
	  dput '$(PPA)' "$$changes"

clean:
	rm -rf $(BUILD)

# The daily check of .github/workflows/veyon-upstream.yml runs the same; it builds, tests and reports in an issue,
# and never commits or uploads.
check-upstream:
	python3 -I tools/upstream.py check

bump:
	python3 -I tools/upstream.py bump $(if $(NEW),--version '$(NEW)')

test-tools:
	python3 -m unittest discover -s tests -p 'test_*.py'

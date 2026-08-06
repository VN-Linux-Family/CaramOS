SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c

PACKAGE := caramos-ota
PPA ?= ppa:vietnamlinuxfamily/caram-os
GPG_KEY ?= ledungb11@gmail.com
GPG_TTY ?= $(shell tty 2>/dev/null || true)
export GPG_TTY
REMOTE_USER ?= caram
REMOTE_HOST ?= 127.0.0.1
REMOTE_PORT ?= 2222
TEST_RELEASE_FROM ?= 1.0.12
TEST_RELEASE_TARGET ?= $(shell PYTHONPATH=usr/lib/python3/dist-packages python3 -c 'from caramos_ota.release_metadata import PRODUCT_VERSION; print(PRODUCT_VERSION)' 2>/dev/null || printf 'dev')
VERSION ?=

.PHONY: help clean compile validate build release-deb source release-source ship test test-cli test-notifier smoke inspect status prepare-release check-release setup-gpg gpg-unlock upload release

help:
	@printf '%s\n' 'CaramOS OTA package workflow'
	@printf '%s\n' ''
	@printf '%s\n' 'Common targets:'
	@printf '%s\n' '  make clean           Clean Debian/Python build artifacts'
	@printf '%s\n' '  make compile         Compile Python sources'
	@printf '%s\n' '  make validate        Validate migration JSON metadata'
	@printf '%s\n' '  make build           Build binary .deb for local/VM test'
	@printf '%s\n' '  make ship            Build and ship .deb to VM via SSH'
	@printf '%s\n' '  make test            Run VM CLI E2E after ship'
	@printf '%s\n' '  make test-notifier   Prepare state and launch notifier in VM desktop'
	@printf '%s\n' '  make source          Build source package for PPA upload'
	@printf '%s\n' '  make upload          Upload latest source changes to Launchpad PPA'
	@printf '%s\n' '  make setup-gpg       Configure local GPG agent/pinentry for release signing'
	@printf '%s\n' '  make release VERSION=x  Stamp version, test, build, sign, and upload'
	@printf '%s\n' ''
	@printf '%s\n' 'Variables:'
	@printf '%s\n' '  PPA=$(PPA)'
	@printf '%s\n' '  GPG_KEY=$(GPG_KEY)'
	@printf '%s\n' '  GPG_TTY=$(GPG_TTY)'
	@printf '%s\n' '  REMOTE_USER=$(REMOTE_USER) REMOTE_HOST=$(REMOTE_HOST) REMOTE_PORT=$(REMOTE_PORT)'
	@printf '%s\n' '  TEST_RELEASE_FROM=$(TEST_RELEASE_FROM) TEST_RELEASE_TARGET=$(TEST_RELEASE_TARGET)'

clean:
	./tools/caramos-ota-testkit.sh clean-build

compile:
	./tools/caramos-ota-testkit.sh compile

validate:
	./tools/caramos-ota-testkit.sh validate

build release-deb: clean compile validate
	./tools/caramos-ota-testkit.sh build-deb

source release-source: clean compile validate
	./tools/caramos-ota-testkit.sh build-source

inspect: build
	@deb="$$(find dist-testkit -maxdepth 1 -type f -name '$(PACKAGE)_*.deb' | sort | tail -n 1)"; \
	  test -n "$$deb"; \
	  dpkg-deb -c "$$deb" | sed -n '1,220p'

ship:
	REMOTE_USER='$(REMOTE_USER)' REMOTE_HOST='$(REMOTE_HOST)' REMOTE_PORT='$(REMOTE_PORT)' TEST_RELEASE_FROM='$(TEST_RELEASE_FROM)' TEST_RELEASE_TARGET='$(TEST_RELEASE_TARGET)' ./tools/ship-ota-to-vm.sh

test test-cli:
	ssh -p '$(REMOTE_PORT)' '$(REMOTE_USER)@$(REMOTE_HOST)' \
	  "cd /tmp/caramos-ota-e2e && sudo TEST_RELEASE_FROM='$(TEST_RELEASE_FROM)' TEST_RELEASE_TARGET='$(TEST_RELEASE_TARGET)' ./vm-run-ota-e2e.sh install-and-cli"

test-notifier:
	ssh -p '$(REMOTE_PORT)' '$(REMOTE_USER)@$(REMOTE_HOST)' \
	  "cd /tmp/caramos-ota-e2e && sudo TEST_RELEASE_FROM='$(TEST_RELEASE_FROM)' TEST_RELEASE_TARGET='$(TEST_RELEASE_TARGET)' ./vm-run-ota-e2e.sh install-shipped && sudo TEST_RELEASE_FROM='$(TEST_RELEASE_FROM)' TEST_RELEASE_TARGET='$(TEST_RELEASE_TARGET)' ./vm-run-ota-e2e.sh prepare-check && ./vm-run-ota-e2e.sh notifier"

smoke: compile validate
	PYTHONPATH=usr/lib/python3/dist-packages ./usr/bin/caramos-ota-update --help >/dev/null
	@printf '%s\n' '[OK] CLI smoke passed'

status:
	@git status --short
	@printf '\nLatest package changelog:\n'
	@dpkg-parsechangelog -S Version

prepare-release:
	@test -n '$(VERSION)' || { echo 'Usage: make prepare-release VERSION=1.0.17' >&2; exit 2; }
	./tools/prepare-release.py '$(VERSION)'

check-release:
	@test -n '$(VERSION)' || { echo 'Usage: make check-release VERSION=1.0.17' >&2; exit 2; }
	./tools/prepare-release.py --check '$(VERSION)'
	@version="$$(dpkg-parsechangelog -S Version)"; test "$$version" = '$(VERSION)-0caramos1' || { echo "Error: changelog version $$version does not match $(VERSION)-0caramos1" >&2; exit 1; }

setup-gpg:
	@echo '== Installing release signing tools =='
	@sudo apt-get update
	@sudo apt-get install -y devscripts dput gnupg2 pinentry-curses
	@echo '== Configuring ~/.gnupg/gpg-agent.conf =='
	@mkdir -p "$${HOME}/.gnupg"
	@chmod 700 "$${HOME}/.gnupg"
	@{ \
	  echo 'pinentry-program /usr/bin/pinentry-curses'; \
	  echo 'default-cache-ttl 86400'; \
	  echo 'max-cache-ttl 604800'; \
	} > "$${HOME}/.gnupg/gpg-agent.conf"
	@chmod 600 "$${HOME}/.gnupg/gpg-agent.conf"
	@profile="$${HOME}/.zshrc"; \
	  if [[ -n "$${BASH_VERSION:-}" ]]; then profile="$${HOME}/.bashrc"; fi; \
	  touch "$$profile"; \
	  if ! grep -Fq 'GPG signing for Debian/Launchpad releases' "$$profile"; then \
	    { \
	      echo ''; \
	      echo '# GPG signing for Debian/Launchpad releases'; \
	      echo 'export GPG_TTY=$$(tty)'; \
	      echo 'gpg-connect-agent updatestartuptty /bye >/dev/null 2>&1 || true'; \
	    } >> "$$profile"; \
	    echo "[OK] Added GPG_TTY setup to $$profile"; \
	  else \
	    echo "[OK] GPG_TTY setup already exists in $$profile"; \
	  fi
	@gpgconf --kill gpg-agent || true
	@echo '[OK] GPG agent configured. Open a new terminal or run: source ~/.zshrc'
	@echo 'Then run: make release'

gpg-unlock:
	@if [[ -z "$(GPG_TTY)" ]]; then \
	  echo 'Warning: GPG_TTY is empty; pinentry may not appear in this terminal.'; \
	else \
	  echo 'Using GPG_TTY=$(GPG_TTY)'; \
	fi
	@gpg-connect-agent updatestartuptty /bye >/dev/null 2>&1 || true
	@printf '%s\n' 'If this waits here, check for a GPG pinentry prompt or configure pinentry-curses.'
	@printf 'CaramOS OTA release signing preflight\n' | gpg --clearsign -u '$(GPG_KEY)' >/dev/null
	@echo '[OK] GPG signing key is unlocked: $(GPG_KEY)'

upload:
	@version="$$(dpkg-parsechangelog -S Version)"; \
	  changes="../$(PACKAGE)_$${version}_source.changes"; \
	  if [[ ! -f "$$changes" ]]; then \
	    echo "Error: source .changes not found for $$version. Run: make source"; \
	    exit 1; \
	  fi; \
	  if ! gpg --verify "$$changes" >/dev/null 2>&1; then \
	    echo "Signing $$changes with $(GPG_KEY)"; \
	    debsign -k'$(GPG_KEY)' "$$changes"; \
	  fi; \
	  echo "Uploading $$changes to $(PPA)"; \
	  dput '$(PPA)' "$$changes"

release:
	@test -n '$(VERSION)' || { echo 'Usage: make release VERSION=1.0.17' >&2; exit 2; }
	./tools/prepare-release.py '$(VERSION)'
	./tools/prepare-release.py --check '$(VERSION)'
	$(MAKE) compile
	$(MAKE) validate
	PYTHONPATH=usr/lib/python3/dist-packages python3 -m unittest discover -s tests -v
	$(MAKE) build
	$(MAKE) source
	$(MAKE) gpg-unlock
	$(MAKE) upload

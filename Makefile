# CaramOS 2.0 — Unified Rust Workspace Makefile (Debian 13 Trixie Hybrid ISO)
CARGO ?= cargo
CTL_BIN := target/release/caramos-ctl
UI_BIN := target/release/caramos-ui
WORK_DIR ?= ./build
UI_OVERLAY_DIR := $(WORK_DIR)/ui_overlay
WALLPAPER_DIR ?= ./config/includes.chroot/usr/share/backgrounds
ASSETS_DIR ?= ./assets

.PHONY: all check test build-bin stage-ui demo-installer prune dry-run build release clean distclean

all: check test build-bin

check:
	$(CARGO) clippy --workspace --all-targets -- -D warnings -D clippy::unwrap_used -D clippy::expect_used -D clippy::panic

test:
	$(CARGO) test --workspace

build-bin:
	$(CARGO) build --workspace --release

stage-ui: build-bin
	$(UI_BIN) bootloader \
		--output-root $(UI_OVERLAY_DIR) \
		--wallpaper-search-dir $(WALLPAPER_DIR) \
		--assets-dir $(ASSETS_DIR)

demo-installer: build-bin
	$(UI_BIN) installer --interactive --dry-run --target-root $(WORK_DIR)_dryrun/installer_target

prune: build-bin
	$(CTL_BIN) prune --repo-root . --execute

dry-run: build-bin
	$(CTL_BIN) build \
		--dry-run \
		--work-dir $(WORK_DIR)_dryrun \
		--stage-bin $(CTL_BIN) \
		--stage-bin $(UI_BIN)

build: stage-ui
	sudo $(CTL_BIN) build \
		--work-dir $(WORK_DIR) \
		--extra-overlay $(UI_OVERLAY_DIR) \
		--stage-bin $(CTL_BIN) \
		--stage-bin $(UI_BIN)

release: stage-ui
	sudo $(CTL_BIN) build \
		--release \
		--work-dir $(WORK_DIR) \
		--extra-overlay $(UI_OVERLAY_DIR) \
		--stage-bin $(CTL_BIN) \
		--stage-bin $(UI_BIN)

clean:
	sudo rm -rf $(WORK_DIR) $(WORK_DIR)_dryrun

distclean: clean
	$(CARGO) clean

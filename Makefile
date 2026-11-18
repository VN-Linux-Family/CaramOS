# CaramOS 2.0 — Rust Orchestrated Makefile (Debian Trixie Base)
CARGO ?= cargo
CTL_MANIFEST := crates/caramos-ctl/Cargo.toml
CTL_BIN := crates/caramos-ctl/target/release/caramos-ctl
WORK_DIR ?= ./build

.PHONY: all check test build-bin dry-run build release prune clean

all: check test build-bin

check:
	$(CARGO) clippy --manifest-path $(CTL_MANIFEST) --all-targets -- -D warnings -D clippy::unwrap_used -D clippy::expect_used -D clippy::panic

test:
	$(CARGO) test --manifest-path $(CTL_MANIFEST)

build-bin:
	$(CARGO) build --manifest-path $(CTL_MANIFEST) --release

prune: build-bin
	$(CTL_BIN) prune --repo-root . --execute

dry-run: build-bin
	$(CTL_BIN) build --dry-run --work-dir $(WORK_DIR)_dryrun

build: build-bin
	sudo $(CTL_BIN) build --work-dir $(WORK_DIR)

release: build-bin
	sudo $(CTL_BIN) build --release --work-dir $(WORK_DIR)

clean:
	sudo rm -rf $(WORK_DIR) $(WORK_DIR)_dryrun

#!/bin/sh
# Builds and tests caramos-business-agent in Docker: Ubuntu 24.04 with cargo-1.85 and rustc-1.85, the toolchain of
# the Launchpad PPA build, offline from vendor/ as there. No Rust toolchain is needed on the host.
#
#   ./build.sh           cargo test, then the release build: target/release/caramos-business-agent
#   ./build.sh vendor    fetches the crates of Cargo.lock into vendor/ again (needs the network)
#   ./build.sh shell     a shell in the build container
set -e

here=$(cd "$(dirname "$0")" && pwd)
image=caramos-business-agent-build

# Built once. The Dockerfile comes on stdin, so no build context (vendor/, target/) is sent.
if ! docker image inspect "$image" >/dev/null 2>&1; then
    docker build -t "$image" - < "$here/Dockerfile.build"
fi

# The package folder is mounted, so that the tests find ../tests/protocol-examples. Running as the calling user
# keeps target/ and vendor/ theirs; cargo's own files go to target/cargo-home.
run() {
    docker run --rm --user "$(id -u):$(id -g)" -e HOME=/tmp -e CARGO_HOME=/src/agent/target/cargo-home \
        -v "$here/..:/src" -w /src/agent "$@"
}

case "${1:-build}" in
    build)
        run --network none "$image" sh -c \
            'cargo-1.85 test --offline --locked && cargo-1.85 build --release --offline --locked'
        ls -l "$here/target/release/caramos-business-agent"
        ;;
    vendor)
        # cargo vendor ignores .cargo/config.toml's source replacement and downloads from crates.io.
        run "$image" cargo-1.85 vendor --locked vendor >/dev/null
        ;;
    shell)
        run -it "$image" bash
        ;;
    *)
        echo "usage: $0 [build | vendor | shell]" >&2
        exit 2
        ;;
esac

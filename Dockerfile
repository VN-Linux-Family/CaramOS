FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    CI=1 \
    APT_LOCK_TIMEOUT=600

# Dependencies required by build.sh, hooks, and Makefile targets.
# CI=1 skips the optional gum installer, but gnupg is kept for parity if enabled later.
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        apt-transport-https \
        ca-certificates \
        curl \
        file \
        fontconfig \
        git \
        gnupg \
        isolinux \
        locales \
        make \
        p7zip-full \
        rsync \
        sudo \
        squashfs-tools \
        syslinux \
        syslinux-common \
        syslinux-utils \
        unzip \
        wget \
        xorriso \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

CMD ["/bin/bash"]

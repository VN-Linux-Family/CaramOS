FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive \
    CI=1 \
    APT_LOCK_TIMEOUT=600

RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        apt-transport-https \
        build-essential \
        ca-certificates \
        curl \
        debhelper \
        dpkg-dev \
        file \
        fontconfig \
        git \
        gnupg \
        isolinux \
        jq \
        locales \
        make \
        p7zip-full \
        python3 \
        rsync \
        sudo \
        squashfs-tools \
        syslinux \
        syslinux-common \
        syslinux-utils \
        unzip \
        wget \
        xorriso \
        zstd \
    && locale-gen en_US.UTF-8 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US:en \
    LC_ALL=en_US.UTF-8

WORKDIR /app

CMD ["/bin/bash"]

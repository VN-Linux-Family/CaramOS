FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies required by build.sh
RUN apt-get update && \
    apt-get install -y \
    squashfs-tools \
    xorriso \
    rsync \
    wget \
    curl \
    isolinux \
    sudo \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

CMD ["/bin/bash"]

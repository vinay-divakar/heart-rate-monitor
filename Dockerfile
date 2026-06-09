FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Python virtual environment
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Zephyr SDK location
ENV ZEPHYR_SDK_INSTALL_DIR=/opt/zephyr-sdk-0.17.4
ENV PATH="$ZEPHYR_SDK_INSTALL_DIR/arm-zephyr-eabi/bin:$PATH"

# -----------------------------------------------------------------------------
# Install Ubuntu packages
# -----------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    cmake \
    ninja-build \
    gperf \
    ccache \
    device-tree-compiler \
    wget \
    curl \
    python3-dev \
    python3-venv \
    python3-pip \
    python3-setuptools \
    python3-wheel \
    xz-utils \
    file \
    make \
    gcc \
    gcc-multilib \
    g++-multilib \
    ca-certificates \
    ruby \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
# -----------------------------------------------------------------------------
# Install Zephyr SDK
# -----------------------------------------------------------------------------
RUN wget https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v0.17.4/zephyr-sdk-0.17.4_linux-x86_64_minimal.tar.xz \
    && tar xf zephyr-sdk-0.17.4_linux-x86_64_minimal.tar.xz -C /opt \
    && /opt/zephyr-sdk-0.17.4/setup.sh -t arm-zephyr-eabi \
    && rm zephyr-sdk-0.17.4_linux-x86_64_minimal.tar.xz

# -----------------------------------------------------------------------------
# Create Python virtual environment
# -----------------------------------------------------------------------------
RUN python3 -m venv $VIRTUAL_ENV

# -----------------------------------------------------------------------------
# Upgrade pip
# -----------------------------------------------------------------------------
RUN pip install --no-cache-dir --upgrade pip

# -----------------------------------------------------------------------------
# Install west + Zephyr/NCS/MCUboot Python dependencies
#
# IMPORTANT:
# - Versions are pinned to match NCS v3.2.0 / Zephyr 4.2.x
# - Dependencies are baked into IMAGE during docker build
# - No runtime pip installs needed
# -----------------------------------------------------------------------------
RUN pip install --no-cache-dir \
    west==1.5.0 \
    -r https://raw.githubusercontent.com/nrfconnect/sdk-nrf/v3.2.0/scripts/requirements.txt \
    -r https://raw.githubusercontent.com/nrfconnect/sdk-mcuboot/ncs-v3.2.0/scripts/requirements.txt \
    pyelftools \
    intelhex \
    tabulate \
    junitparser \
    psutil \
    pyyaml \
    pytest \
    pyserial \
    anytree \
    ply \
    natsort

# -----------------------------------------------------------------------------
# Create workspace directory
# -----------------------------------------------------------------------------
RUN mkdir -p /workdir

# -----------------------------------------------------------------------------
# Set working directory
# -----------------------------------------------------------------------------
WORKDIR /workdir

# -----------------------------------------------------------------------------
# Default shell
# -----------------------------------------------------------------------------
CMD ["/bin/bash"]
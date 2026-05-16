FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Python virtual environment
ENV VIRTUAL_ENV=/opt/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install required packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    cmake \
    ninja-build \
    gperf \
    ccache \
    dfu-util \
    device-tree-compiler \
    wget \
    python3-dev \
    python3-venv \
    python3-pip \
    python3-setuptools \
    python3-tk \
    python3-wheel \
    xz-utils \
    file \
    make \
    gcc \
    gcc-multilib \
    g++-multilib \
    libsdl2-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Zephyr SDK
RUN wget https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v0.17.4/zephyr-sdk-0.17.4_linux-x86_64_minimal.tar.xz \
    && tar xf zephyr-sdk-0.17.4_linux-x86_64_minimal.tar.xz -C /opt \
    && /opt/zephyr-sdk-0.17.4/setup.sh -t arm-zephyr-eabi \
    && rm zephyr-sdk-0.17.4_linux-x86_64_minimal.tar.xz

# Create Python virtual environment
RUN python3 -m venv $VIRTUAL_ENV

# Upgrade pip
RUN pip install --upgrade pip

# Install west
RUN pip install west

# Install pyelftools
RUN pip install pyelftools

# Create workspace directory
RUN mkdir -p /workdir

# Set working directory
WORKDIR /workdir

# Default shell
CMD ["/bin/bash"]
#!/bin/bash
set -e

echo "Initializing Zephyr environment..."

# Install Zephyr Python requirements if workspace exists
if [ -f /workdir/zephyr/scripts/requirements.txt ]; then
    pip install -r /workdir/zephyr/scripts/requirements.txt
fi

if [ -f /workdir/nrf/scripts/requirements.txt ]; then
    pip install -r /workdir/nrf/scripts/requirements.txt
fi

if [ -f /workdir/bootloader/mcuboot/scripts/requirements.txt ]; then
    pip install -r /workdir/bootloader/mcuboot/scripts/requirements.txt
fi

echo "Environment ready."

# Execute whatever command Docker passed
exec "$@"
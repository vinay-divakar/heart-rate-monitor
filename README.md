# Heart Rate Monitor

Firmware for a heart rate monitor built on the **nRF52840 DK**, using Nordic nRF Connect SDK (NCS) v3.2.0 / Zephyr RTOS 4.2.x.

The application reads photoplethysmography (PPG) data from the **XD58C** pulse sensor via ADC, applies a DC-offset removal filter, and streams AC samples over UART for host-side heart rate processing.

## Hardware

| Component | Detail |
|-----------|--------|
| SoC | nRF52840 |
| Board | nRF52840 DK (`nrf52840dk/nrf52840`) |
| Sensor | XD58C (PPG / heart rate) |
| Interface | ADC (async) + UART (async TX) |
| Logging | Segger RTT (deferred mode) |

## Repository layout

```
app/            Application entry point and Kconfig/prj.conf
lib/xd58c/      XD58C driver (ADC → DC filter → UART TX)
include/lib/    Public header for the xd58c driver
tests/xd58c/    Unit tests (Zephyr ZTEST / Unity, runs on native_sim)
keys/           Signing keys — gitignored, not committed
boards/         Custom board definitions (if any)
dts/bindings/   Custom devicetree bindings
```

## How it works

1. `xd58c_init()` — configures the ADC channel at 200 Hz (5 ms interval), registers an async UART callback, and starts continuous ADC sampling.
2. ADC callback — on each sample, subtracts a running DC estimate (single-pole IIR high-pass, shift = 5) to extract the AC pulse waveform, then enqueues the result.
3. `xd58c_process()` — dequeues one sample and transmits it as a decimal string (`"<value>\r\n"`) over UART0.
4. `main()` calls `xd58c_init()` once, then loops on `xd58c_process()`.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) — all build tooling is in the provided `Dockerfile`
- [west](https://docs.zephyrproject.org/latest/develop/west/index.html) — Zephyr meta-tool (installed inside the Docker image)

## Local development setup

Build the Docker image (one-time):

```bash
docker build -t heart-rate-build-env .
```

Start a shell inside the container, mounting the workspace:

```bash
docker run --rm -it \
  -v /path/to/heart-rate-workspace:/workdir \
  heart-rate-build-env
```

Inside the container, initialize the west workspace (one-time):

```bash
cd /workdir/heart-rate-monitor
west init -l .
west update --narrow
```

## Building

```bash
west build -p always \
  -b nrf52840dk/nrf52840 \
  --sysbuild \
  app \
  -- \
  -DSB_CONFIG_BOOT_SIGNATURE_KEY_FILE="/workdir/heart-rate-monitor/keys/heart-rate-ec-p256-dev.pem"
```

- `--sysbuild` builds MCUboot + the application together.
- The signing key path overrides the hardcoded path in `app/sysbuild.conf`.
- Compiled output lands in `build/`.

### Treat warnings as errors (recommended)

Add `-Dapp_CONFIG_COMPILER_WARNINGS_AS_ERRORS=y` to the build command. This is scoped to the app domain only and does not affect MCUboot.

## Flashing

```bash
west flash
```

## Unit tests

Tests live in `tests/xd58c/` and run on the `native_sim` platform — no hardware required.

```bash
west twister \
  -T tests/ \
  --platform native_sim \
  --inline-logs \
  --outdir twister-out/
```

Test results are written to `twister-out/twister.xml` (JUnit format).

### What is tested

| Test | Description |
|------|-------------|
| `test_xd58c_init_success` | Happy path: UART + ADC ready, init returns 0 |
| `test_xd58c_init_no_uart` | UART not ready → returns `-ENODEV` |
| `test_xd58c_init_no_adc` | ADC not ready → returns `-ENODEV` |
| `test_xd58c_init_adc_setup_error` | ADC channel setup fails → returns `-EINVAL` |
| `test_xd58c_uart_write_format` | Sample enqueued and transmitted as `"<value>\r\n"` |

## CI

GitHub Actions runs on every pull request and push to `main`.

| Job | What it does |
|-----|--------------|
| `docker` | Builds and pushes the build-env image to GHCR (layer-cached) |
| `build-and-test` | Runs inside the build-env container: initializes the west workspace (cached), builds firmware with warnings-as-errors, runs Twister unit tests, uploads `artifacts/` |

The signing key (`MCUBOOT_SIGNING_KEY_PEM`) must be set as a GitHub repository secret.

## Signing keys

Development keys live in `keys/` (gitignored). Generate a new EC P-256 key pair:

```bash
python3 $ZEPHYR_BASE/../bootloader/mcuboot/scripts/imgtool.py keygen \
  -k keys/heart-rate-ec-p256-dev.pem \
  -t ecdsa-p256
```

## License

Apache-2.0

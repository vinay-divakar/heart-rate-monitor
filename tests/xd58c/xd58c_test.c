/*
 * SPDX-License-Identifier: Apache-2.0
 *
 * Unity unit tests for heart‑rate-monitor/lib/xd58c/xd58c.c
 */

/*
 * 1. Define configuration flags FIRST.
 */
#define CONFIG_XD58C 1
#ifndef CONFIG_XD58C_LOG_LEVEL
#define CONFIG_XD58C_LOG_LEVEL 3
#endif

/*---------------------------------------------------------------------------
 *  2. Standard C & Zephyr System Headers
 *---------------------------------------------------------------------------*/
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include <zephyr/device.h>
#include <zephyr/drivers/adc.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/kernel.h> // for k_msgq
#include <zephyr/logging/log.h>

// Unity API
#include <unity.h>

/*---------------------------------------------------------------------------
 *  3. Mock state & Function prototypes
 *---------------------------------------------------------------------------*/
static bool _uart_ready = true;
static bool _adc_ready = true;
static bool _adc_setup_ok = true;
static int _last_uart_len = 0;
static char _last_uart_buf[64] = {0};
static void (*_rx_cb)(const struct device *, struct uart_event *,
                      void *) = NULL;

static struct device mock_uart_device;

bool mock_device_is_ready(const struct device *dev) {
  ARG_UNUSED(dev);
  return _uart_ready;
}

int mock_adc_is_ready_dt(const struct adc_dt_spec *spec) {
  ARG_UNUSED(spec);
  return _adc_ready ? 1 : 0;
}

int mock_adc_channel_setup_dt(const struct adc_dt_spec *spec) {
  ARG_UNUSED(spec);
  return _adc_setup_ok ? 0 : -EINVAL;
}

int mock_adc_sequence_init_dt(const struct adc_dt_spec *spec,
                              struct adc_sequence *seq) {
  ARG_UNUSED(spec);
  ARG_UNUSED(seq);
  return 0;
}

int mock_adc_read_async(const struct device *dev,
                        const struct adc_sequence *seq, void *user_data) {
  ARG_UNUSED(dev);
  ARG_UNUSED(seq);
  ARG_UNUSED(user_data);
  return 0;
}

/* Prototype for mock_uart_tx (defined below driver include) */
int mock_uart_tx(const struct device *dev, const uint8_t *data, size_t len,
                 int32_t timeout);

int mock_uart_callback_set(const struct device *dev,
                           void (*cb)(const struct device *,
                                      struct uart_event *, void *),
                           void *user_data) {
  ARG_UNUSED(dev);
  ARG_UNUSED(user_data);
  _rx_cb = cb;
  return 0;
}

/*---------------------------------------------------------------------------
 *  4. Macro API Mapping & Stubs (Constants only for global initializer pass)
 *---------------------------------------------------------------------------*/
#undef ADC_DT_SPEC_GET
#define ADC_DT_SPEC_GET(node)                                                  \
  {.dev = NULL, .channel_id = 0, .resolution = 0, .oversampling = 0}

#undef DEVICE_DT_GET
#define DEVICE_DT_GET(node) NULL

#undef device_is_ready
#define device_is_ready mock_device_is_ready
#define adc_is_ready_dt mock_adc_is_ready_dt
#define adc_channel_setup_dt mock_adc_channel_setup_dt
#define adc_sequence_init_dt mock_adc_sequence_init_dt
#define adc_read_async mock_adc_read_async

#undef uart_tx
#define uart_tx mock_uart_tx
#undef uart_callback_set
#define uart_callback_set mock_uart_callback_set

// Helper macro for Unity
#define TEST_ASSERT_OK(res) TEST_ASSERT_EQUAL_INT(0, (res))

/*---------------------------------------------------------------------------
 *  5. Driver API and Source Execution
 *---------------------------------------------------------------------------*/
#include <lib/xd58c.h>

#include <../lib/xd58c/xd58c.c>

/*---------------------------------------------------------------------------
 *  6. Mock Definitions Requiring Driver Internals
 *---------------------------------------------------------------------------*/
int mock_uart_tx(const struct device *dev, const uint8_t *data, size_t len,
                 int32_t timeout) {
  ARG_UNUSED(dev);
  ARG_UNUSED(timeout);
  _last_uart_len = (int)len;
  if (len <= sizeof(_last_uart_buf))
    memcpy(_last_uart_buf, data, len);

  /* Real '_this' structure from xd58c.c is naturally visible here */
  k_sem_give(&_this.tx_sem);

  return 0;
}

// Test setup state clearing and structural assignments
void setUp(void) {
  _uart_ready = true;
  _adc_ready = true;
  _adc_setup_ok = true;
  _last_uart_len = 0;
  memset(_last_uart_buf, 0, sizeof(_last_uart_buf));
  _rx_cb = NULL;

  /* Safe pointer assignment fixes the segmentation fault bug */
  mock_uart_device.name = "mock_uart0";

  // Cast away the const restriction on initialization pointers to swap them
  // dynamically
  struct device **uart_ptr = (struct device **)&_this.uart;
  *uart_ptr = &mock_uart_device;
}

void tearDown(void) {}

/*---------------------------------------------------------------------------
 *    Test cases
 *---------------------------------------------------------------------------*/
static void test_xd58c_init_success(void) { TEST_ASSERT_OK(xd58c_init()); }

static void test_xd58c_init_no_uart(void) {
  _uart_ready = false;
  TEST_ASSERT_EQUAL_INT(-ENODEV, xd58c_init());
}

static void test_xd58c_init_no_adc(void) {
  _adc_ready = false;
  TEST_ASSERT_EQUAL_INT(-ENODEV, xd58c_init());
}

static void test_xd58c_init_adc_setup_error(void) {
  _adc_setup_ok = false;
  TEST_ASSERT_EQUAL_INT(-EINVAL, xd58c_init());
}

static void test_xd58c_uart_write_format(void) {
  TEST_ASSERT_OK(xd58c_init());

  int16_t sample = 4660; // "4660" in decimal

  /* _this is accessible because xd58c.c is included directly in this
   * translation unit */
  TEST_ASSERT_OK(k_msgq_put(&_this.queue, &sample, K_NO_WAIT));
  TEST_ASSERT_OK(xd58c_process());
  _last_uart_buf[_last_uart_len] = '\0';
  TEST_ASSERT_EQUAL_STRING("4660\r\n", _last_uart_buf);
}

// Zephyr Unity Test Entry Point
void test_main(void) {
  UNITY_BEGIN();
  RUN_TEST(test_xd58c_init_success);
  RUN_TEST(test_xd58c_init_no_uart);
  RUN_TEST(test_xd58c_init_no_adc);
  RUN_TEST(test_xd58c_init_adc_setup_error);
  RUN_TEST(test_xd58c_uart_write_format);
  UNITY_END();
}

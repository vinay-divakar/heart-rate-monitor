/*
 * SPDX-License-Identifier: Apache-2.0
 */

#include <app_version.h>
#include <lib/xd58c.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(main, LOG_LEVEL_INF);

#define MESSAGE_QUEUE_SIZE 64

static struct {
  const struct device *uart;
  const int shift;
  int32_t dc;
  struct k_msgq queue;
  char buffer[MESSAGE_QUEUE_SIZE * sizeof(int16_t)];
  char tx_buf[8];
  struct k_sem tx_sem;
} _this = {.uart = DEVICE_DT_GET(DT_NODELABEL(uart0)), .shift = 5};

static enum adc_action _callback(const struct device *dev,
                                 const struct adc_sequence *sequence,
                                 uint16_t sampling_index) {

  int16_t raw = *(int16_t *)sequence->buffer;
  _this.dc = _this.dc - (_this.dc >> _this.shift) + raw;
  int16_t ac = raw - (int16_t)(_this.dc >> _this.shift);

  int err = k_msgq_put(&_this.queue, &ac, K_NO_WAIT);
  if (err) {
    LOG_ERR("enqueue (err %d)", err);
  }

  return ADC_ACTION_REPEAT;
}

static void uart_tx_callback(const struct device *dev, struct uart_event *evt,
                             void *user_data) {
  ARG_UNUSED(dev);
  ARG_UNUSED(user_data);

  if (evt->type == UART_TX_DONE || evt->type == UART_TX_ABORTED) {
    k_sem_give(&_this.tx_sem);
  }
}

static void uart_send_sample(int16_t raw) {
  int len = snprintk(_this.tx_buf, sizeof(_this.tx_buf), "%d\r\n", raw);
  if (len < 0 || !len || (size_t)len >= sizeof(_this.tx_buf)) {
    LOG_ERR("snprintk (err %d)", len);
    return;
  }

  int err = uart_tx(_this.uart, (const uint8_t *)_this.tx_buf, (size_t)len,
                    SYS_FOREVER_US);
  if (err) {
    LOG_ERR("uart_tx (err %d)", err);
    return;
  }

  err = k_sem_take(&_this.tx_sem, K_FOREVER);
  if (err) {
    LOG_ERR("uart tx wait (err %d)", err);
  }
}

int main(void) {
  LOG_INF("Heart Rate Monitor %s", APP_VERSION_STRING);

  if (!device_is_ready(_this.uart)) {
    LOG_ERR("uart0 not ready");
    return -ENODEV;
  }

  k_sem_init(&_this.tx_sem, 0, 1);

  int err = uart_callback_set(_this.uart, uart_tx_callback, NULL);
  if (err) {
    LOG_ERR("uart_callback_set (err %d)", err);
    return err;
  }

  k_msgq_init(&_this.queue, _this.buffer, sizeof(int16_t), MESSAGE_QUEUE_SIZE);

  err = xd58c_init();
  if (err) {
    LOG_ERR("init XD58C (err %d)", err);
    return err;
  }

  xd58c_callback_set(_callback, NULL);

  err = xd58c_start();
  if (err) {
    LOG_ERR("start XD58C (err %d)", err);
    return err;
  }

  while (1) {
    int16_t sample;
    err = k_msgq_get(&_this.queue, &sample, K_FOREVER);
    if (err) {
      LOG_ERR("dequeue (err %d)", err);
      continue;
    }

    uart_send_sample(sample);
  }

  return 0;
}
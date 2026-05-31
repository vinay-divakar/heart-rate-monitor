/*
 * SPDX-License-Identifier: Apache-2.0
 */

#include <app_version.h>
#include <lib/xd58c.h>
#include <zephyr/kernel.h>
#include <zephyr/logging/log.h>

LOG_MODULE_REGISTER(main, LOG_LEVEL_INF);

int main(void) {
  LOG_INF("Heart Rate Monitor %s", APP_VERSION_STRING);

  int err = xd58c_init();
  if (err) {
    LOG_ERR("init XD58C (err %d)", err);
    return err;
  }

  while (1) {
    xd58c_process();
  }

  return 0;
}
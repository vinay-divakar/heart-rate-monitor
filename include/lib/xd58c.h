/*
 * SPDX-License-Identifier: Apache-2.0
 */

#ifndef XD58C_H_
#define XD58C_H_

#include <zephyr/drivers/adc.h>

#if defined(CONFIG_XD58C)
int xd58c_init(void);
int xd58c_process(void);
#else
static inline int xd58c_init(void) { return -ENOTSUP; }
static inline int xd58c_process(void) { return -ENOTSUP; }
#endif /* CONFIG_XD58C */

#endif /* XD58C_H_ */
/* Classic CAN (TWAI) link to the DAQ: ENV payload split into 3 frames 0x206/0x207/0x208 (8 + 8 + 6 bytes). */
#ifndef TWAI_LINK_H
#define TWAI_LINK_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

bool twai_link_init(int tx_gpio, int rx_gpio);
/** Sends the 22-byte ENV payload as 3 frames; returns false if the bus is off / TX timed out. */
bool twai_link_send_env(const uint8_t *env, size_t len);
/** True when the controller is in bus-off or has had no successful TX for > 60 s (triggers the MQTT fallback). */
bool twai_link_unhealthy(void);
void twai_link_recover(void);

#endif

/* Sensirion SHT40/SHT45 over I2C (ESP-IDF new i2c_master driver). Datasheet conversion:
 *   T [°C] = -45 + 175 * raw_T / 65535 ;  RH [%] = -6 + 125 * raw_RH / 65535 (clamped 0..100) ; CRC-8 poly 0x31 init 0xFF */
#ifndef SHT4X_H
#define SHT4X_H
#include <stdbool.h>
#include <stdint.h>
#include "driver/i2c_master.h"

#define SHT4X_ADDR_A 0x44
#define SHT4X_ADDR_B 0x45
#define SHT4X_CMD_MEASURE_HIGH 0xFD
#define SHT4X_CMD_SERIAL       0x89
#define SHT4X_CMD_SOFT_RESET   0x94

typedef struct { i2c_master_dev_handle_t dev; uint8_t addr; uint32_t crc_errors; } sht4x_t;

bool sht4x_init(sht4x_t *s, i2c_master_bus_handle_t bus, uint8_t addr);
/** High-precision measurement (~9 ms). Returns false on bus or CRC error. */
bool sht4x_measure(sht4x_t *s, float *temp_c, float *rh_pct);
uint8_t sht4x_crc8(const uint8_t *data, int len);

#endif

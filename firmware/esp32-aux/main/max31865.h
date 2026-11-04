/* MAX31865 RTD-to-digital for the PT1000 pavement probe (4-wire, R_REF = 4.3 kΩ 0.1 %).
 * Registers: 0x00 config (write 0x80), 0x01/0x02 RTD MSB/LSB (15-bit ratio, bit0 = fault), 0x07 fault status.
 * Config 0xC3: VBIAS on, auto conversion, 2/4-wire, 50 Hz filter, clear fault.  T from the inverse Callendar-Van Dusen
 * (IEC 60751 A = 3.9083e-3, B = -5.775e-7) for T >= 0 °C and a 5-term polynomial below 0 °C (not expected in Kenya). */
#ifndef MAX31865_H
#define MAX31865_H
#include <stdbool.h>
#include <stdint.h>
#include "driver/spi_master.h"

#define MAX31865_RREF_OHM   4300.0f
#define MAX31865_R0_OHM     1000.0f
#define MAX31865_CFG        0xC3    /* VBIAS | AUTO | FAULTCLR | 50Hz  (bit4 3-wire = 0 for 2/4-wire) */

typedef struct { spi_device_handle_t dev; uint8_t last_fault; uint32_t fault_count; } max31865_t;

bool  max31865_init(max31865_t *m, spi_host_device_t host, int cs_gpio);
/** Reads the RTD ratio; returns false and sets last_fault on a sensor fault (open/short). */
bool  max31865_read(max31865_t *m, float *rtd_ohm, float *temp_c);
float max31865_ohm_to_c(float r);

#endif

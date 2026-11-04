#include "max31865.h"
#include <math.h>
#include <string.h>

static bool xfer(max31865_t *m, const uint8_t *tx, uint8_t *rx, int len)
{
    spi_transaction_t t = { .length = 8 * len, .tx_buffer = tx, .rx_buffer = rx };
    return spi_device_transmit(m->dev, &t) == ESP_OK;
}

bool max31865_init(max31865_t *m, spi_host_device_t host, int cs_gpio)
{
    spi_device_interface_config_t cfg = { .clock_speed_hz = 1000000, .mode = 1, .spics_io_num = cs_gpio, .queue_size = 2 };
    memset(m, 0, sizeof *m);
    if (spi_bus_add_device(host, &cfg, &m->dev) != ESP_OK) return false;
    uint8_t tx[2] = { 0x80, MAX31865_CFG }, rx[2];
    return xfer(m, tx, rx, 2);
}

float max31865_ohm_to_c(float r)
{
    const float A = 3.9083e-3f, B = -5.775e-7f, R0 = MAX31865_R0_OHM;
    float z = r / R0;
    if (z >= 1.0f) {                                         /* T >= 0: solve R = R0 (1 + A T + B T^2) */
        return (-A + sqrtf(A * A - 4.0f * B * (1.0f - z))) / (2.0f * B);
    }
    /* T < 0: polynomial approximation (Analog Devices AN-709 style), adequate to ±0.1 °C down to -50 °C */
    float rpoly = r / (R0 / 100.0f);                          /* scale to PT100-equivalent ohms */
    float t = -242.02f + 2.2228f * rpoly;
    float rp = rpoly * rpoly; t += 2.5859e-3f * rp; rp *= rpoly; t -= 4.8260e-6f * rp; rp *= rpoly; t -= 2.8183e-8f * rp; rp *= rpoly; t += 1.5243e-10f * rp;
    return t;
}

bool max31865_read(max31865_t *m, float *rtd_ohm, float *temp_c)
{
    uint8_t tx[3] = { 0x01, 0, 0 }, rx[3];
    if (!xfer(m, tx, rx, 3)) return false;
    uint16_t raw = (uint16_t)((rx[1] << 8) | rx[2]);
    if (raw & 0x0001) {                                       /* fault bit */
        uint8_t ftx[2] = { 0x07, 0 }, frx[2];
        if (xfer(m, ftx, frx, 2)) m->last_fault = frx[1];
        m->fault_count++;
        uint8_t ctx[2] = { 0x80, MAX31865_CFG }, crx[2]; xfer(m, ctx, crx, 2);   /* clear fault */
        return false;
    }
    float ratio = (float)(raw >> 1) / 32768.0f;
    *rtd_ohm = ratio * MAX31865_RREF_OHM;
    *temp_c = max31865_ohm_to_c(*rtd_ohm);
    return true;
}

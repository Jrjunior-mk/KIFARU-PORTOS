#include "sht4x.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

uint8_t sht4x_crc8(const uint8_t *data, int len)
{
    uint8_t crc = 0xFF;
    for (int i = 0; i < len; i++) {
        crc ^= data[i];
        for (int b = 0; b < 8; b++) crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ 0x31) : (uint8_t)(crc << 1);
    }
    return crc;
}

bool sht4x_init(sht4x_t *s, i2c_master_bus_handle_t bus, uint8_t addr)
{
    i2c_device_config_t cfg = { .dev_addr_length = I2C_ADDR_BIT_LEN_7, .device_address = addr, .scl_speed_hz = 100000 };
    s->addr = addr; s->crc_errors = 0;
    if (i2c_master_bus_add_device(bus, &cfg, &s->dev) != ESP_OK) return false;
    uint8_t cmd = SHT4X_CMD_SOFT_RESET;
    if (i2c_master_transmit(s->dev, &cmd, 1, 50) != ESP_OK) return false;
    vTaskDelay(pdMS_TO_TICKS(2));
    return true;
}

bool sht4x_measure(sht4x_t *s, float *temp_c, float *rh_pct)
{
    uint8_t cmd = SHT4X_CMD_MEASURE_HIGH, rx[6];
    if (i2c_master_transmit(s->dev, &cmd, 1, 50) != ESP_OK) return false;
    vTaskDelay(pdMS_TO_TICKS(10));
    if (i2c_master_receive(s->dev, rx, 6, 50) != ESP_OK) return false;
    if (sht4x_crc8(rx, 2) != rx[2] || sht4x_crc8(rx + 3, 2) != rx[5]) { s->crc_errors++; return false; }
    uint16_t t_raw = (uint16_t)((rx[0] << 8) | rx[1]), rh_raw = (uint16_t)((rx[3] << 8) | rx[4]);
    *temp_c = -45.0f + 175.0f * (float)t_raw / 65535.0f;
    float rh = -6.0f + 125.0f * (float)rh_raw / 65535.0f;
    *rh_pct = rh < 0 ? 0 : (rh > 100 ? 100 : rh);
    return true;
}

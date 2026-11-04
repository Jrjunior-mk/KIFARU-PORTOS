/**
 * KIFARU PORTOS — ESP32 auxiliary node (WIM-06). Reads: PT1000 pavement probe (MAX31865, SPI), SHT4x outside
 * (0x44) and inside (0x45) the cabinet (I2C), cabinet door switch, PSU AC-fail / battery-low / SPD-fault contacts,
 * 24 V bus and battery voltage (ADC1 via 11:1 dividers), and drives the circulation fan relay. Publishes an ENV
 * payload every CONFIG_KIFARU_ENV_PERIOD_S over classic CAN (TWAI) to the DAQ; when the CAN link is unhealthy for
 * > 60 s it brings up Wi-Fi and publishes the same data as JSON over MQTT (TLS) as a fallback.
 *
 * Pins (ESP32-WROOM-32E): I2C SDA 21 / SCL 22 ; SPI (MAX31865) SCLK 18, MISO 19, MOSI 23, CS 15 ; TWAI TX 5 / RX 4 ;
 * door 32 (input, pull-up, closed = low) ; ac_fail 33 ; batt_low 25 ; spd_fault 26 ; fan relay 27 ;
 * ADC1_CH6 (GPIO34) bus 24 V via 100k/10k ; ADC1_CH7 (GPIO35) battery via 100k/10k.
 *
 * NOT compiled here (no ESP-IDF on the authoring machine). Target ESP-IDF v5.2+.
 */
#include <string.h>
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_task_wdt.h"
#include "nvs_flash.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "driver/gpio.h"
#include "driver/i2c_master.h"
#include "driver/spi_master.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_adc/adc_cali.h"
#include "esp_adc/adc_cali_scheme.h"
#include "sdkconfig.h"
#include "sht4x.h"
#include "max31865.h"
#include "twai_link.h"
#include "mqtt_fallback.h"
#include "env_frame.h"

static const char *TAG = "aux";

#define PIN_SDA 21
#define PIN_SCL 22
#define PIN_SCLK 18
#define PIN_MISO 19
#define PIN_MOSI 23
#define PIN_RTD_CS 15
#define PIN_DOOR 32
#define PIN_AC_FAIL 33
#define PIN_BATT_LOW 25
#define PIN_SPD_FAULT 26
#define PIN_FAN 27
#define ADC_BUS_CH ADC_CHANNEL_6
#define ADC_BATT_CH ADC_CHANNEL_7
#define DIVIDER_RATIO 11.0f      /* 100k / 10k */
#define FAN_ON_C 35.0f
#define FAN_OFF_C 32.0f

static sht4x_t s_sht_out, s_sht_in;
static max31865_t s_rtd;
static adc_oneshot_unit_handle_t s_adc;
static adc_cali_handle_t s_cali;
static bool s_fan_on;
static bool s_fallback_active;

static uint16_t read_mv(adc_channel_t ch)
{
    int raw = 0, mv = 0, acc = 0;
    for (int i = 0; i < 16; i++) { adc_oneshot_read(s_adc, ch, &raw); acc += raw; }
    raw = acc / 16;
    if (s_cali) adc_cali_raw_to_voltage(s_cali, raw, &mv); else mv = raw * 3300 / 4095;
    float v = (float)mv * DIVIDER_RATIO;
    return (uint16_t)(v > 65535 ? 65535 : v);
}

static void hw_init(void)
{
    /* GPIO inputs with pull-ups (contacts close to GND), fan output */
    gpio_config_t in = { .pin_bit_mask = (1ULL << PIN_DOOR) | (1ULL << PIN_AC_FAIL) | (1ULL << PIN_BATT_LOW) | (1ULL << PIN_SPD_FAULT),
                         .mode = GPIO_MODE_INPUT, .pull_up_en = GPIO_PULLUP_ENABLE };
    gpio_config(&in);
    gpio_config_t out = { .pin_bit_mask = (1ULL << PIN_FAN), .mode = GPIO_MODE_OUTPUT };
    gpio_config(&out);
    gpio_set_level(PIN_FAN, 0);

    /* I2C */
    i2c_master_bus_config_t bc = { .i2c_port = I2C_NUM_0, .sda_io_num = PIN_SDA, .scl_io_num = PIN_SCL, .clk_source = I2C_CLK_SRC_DEFAULT, .glitch_ignore_cnt = 7, .flags.enable_internal_pullup = true };
    i2c_master_bus_handle_t bus;
    ESP_ERROR_CHECK(i2c_master_new_bus(&bc, &bus));
    if (!sht4x_init(&s_sht_out, bus, SHT4X_ADDR_A)) ESP_LOGE(TAG, "SHT4x outside not found");
    if (!sht4x_init(&s_sht_in, bus, SHT4X_ADDR_B)) ESP_LOGE(TAG, "SHT4x inside not found");

    /* SPI for MAX31865 */
    spi_bus_config_t sb = { .sclk_io_num = PIN_SCLK, .miso_io_num = PIN_MISO, .mosi_io_num = PIN_MOSI, .quadwp_io_num = -1, .quadhd_io_num = -1 };
    ESP_ERROR_CHECK(spi_bus_initialize(SPI2_HOST, &sb, SPI_DMA_DISABLED));
    if (!max31865_init(&s_rtd, SPI2_HOST, PIN_RTD_CS)) ESP_LOGE(TAG, "MAX31865 init failed");

    /* ADC */
    adc_oneshot_unit_init_cfg_t uc = { .unit_id = ADC_UNIT_1 };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&uc, &s_adc));
    adc_oneshot_chan_cfg_t cc = { .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_12 };
    adc_oneshot_config_channel(s_adc, ADC_BUS_CH, &cc);
    adc_oneshot_config_channel(s_adc, ADC_BATT_CH, &cc);
    adc_cali_line_fitting_config_t lc = { .unit_id = ADC_UNIT_1, .atten = ADC_ATTEN_DB_12, .bitwidth = ADC_BITWIDTH_12 };
    if (adc_cali_create_scheme_line_fitting(&lc, &s_cali) != ESP_OK) s_cali = NULL;

    if (!twai_link_init(CONFIG_KIFARU_CAN_TX_GPIO, CONFIG_KIFARU_CAN_RX_GPIO)) ESP_LOGE(TAG, "TWAI init failed");
}

static void sample_env(env_t *e)
{
    float t, rh, r;
    memset(e, 0, sizeof *e);
    e->t_us = (uint64_t)esp_timer_get_time();                /* µs since boot; the DAQ/gateway re-stamp on receipt */
    if (max31865_read(&s_rtd, &r, &t)) e->pavement_c_x100 = (int16_t)(t * 100.0f); else e->pavement_c_x100 = -32768;
    if (sht4x_measure(&s_sht_out, &t, &rh)) { e->ambient_c_x100 = (int16_t)(t * 100.0f); e->rh_x100 = (uint16_t)(rh * 100.0f); } else e->ambient_c_x100 = -32768;
    if (sht4x_measure(&s_sht_in, &t, &rh)) e->cabinet_c_x100 = (int16_t)(t * 100.0f); else e->cabinet_c_x100 = -32768;
    e->bus_mv = read_mv(ADC_BUS_CH);
    e->batt_mv = read_mv(ADC_BATT_CH);
    if (gpio_get_level(PIN_DOOR)) e->digital |= ENV_BIT_DOOR_OPEN;          /* contact open (high) = door open */
    if (!gpio_get_level(PIN_AC_FAIL)) e->digital |= ENV_BIT_AC_FAIL;        /* PSU relay closes on AC fail */
    if (!gpio_get_level(PIN_BATT_LOW)) e->digital |= ENV_BIT_BATT_LOW;
    if (!gpio_get_level(PIN_SPD_FAULT)) e->digital |= ENV_BIT_SPD_FAULT;

    /* fan hysteresis on cabinet temperature */
    if (e->cabinet_c_x100 != -32768) {
        float tc = e->cabinet_c_x100 / 100.0f;
        if (!s_fan_on && tc > FAN_ON_C) s_fan_on = true;
        if (s_fan_on && tc < FAN_OFF_C) s_fan_on = false;
        gpio_set_level(PIN_FAN, s_fan_on);
    }
    if (s_fan_on) e->digital |= ENV_BIT_FAN_ON;
}

void app_main(void)
{
    ESP_ERROR_CHECK(nvs_flash_init());
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_task_wdt_add(NULL);
    hw_init();
    ESP_LOGI(TAG, "KIFARU aux node %s/%s", CONFIG_KIFARU_STATION, CONFIG_KIFARU_LANE);

    env_t env; uint8_t payload[ENV_LEN]; char json[512];
    for (;;) {
        sample_env(&env);
        env_encode(&env, payload);
        bool can_ok = twai_link_send_env(payload, ENV_LEN);
        if (!can_ok) twai_link_recover();

        if (twai_link_unhealthy()) {
            if (!s_fallback_active) {
                ESP_LOGW(TAG, "CAN unhealthy > 60 s: starting Wi-Fi/MQTT fallback");
                s_fallback_active = mqtt_fallback_start(CONFIG_KIFARU_WIFI_SSID, CONFIG_KIFARU_WIFI_PASS, CONFIG_KIFARU_MQTT_URI, CONFIG_KIFARU_STATION, CONFIG_KIFARU_LANE);
            }
            env_to_json(&env, CONFIG_KIFARU_STATION, CONFIG_KIFARU_LANE, json, sizeof json);
            if (!mqtt_fallback_publish(json)) ESP_LOGW(TAG, "MQTT publish failed (not connected yet?)");
        } else if (s_fallback_active) {
            ESP_LOGI(TAG, "CAN healthy again: stopping fallback");
            mqtt_fallback_stop(); s_fallback_active = false;
        }
        ESP_LOGI(TAG, "pav %.2f C amb %.2f C %.1f %% cab %.2f C bus %.2f V batt %.2f V dig 0x%02X can %d",
                 env.pavement_c_x100 / 100.0, env.ambient_c_x100 / 100.0, env.rh_x100 / 100.0, env.cabinet_c_x100 / 100.0,
                 env.bus_mv / 1000.0, env.batt_mv / 1000.0, env.digital, can_ok);
        esp_task_wdt_reset();
        vTaskDelay(pdMS_TO_TICKS(CONFIG_KIFARU_ENV_PERIOD_S * 1000));
    }
}

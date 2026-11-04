#include "twai_link.h"
#include "driver/twai.h"
#include "esp_timer.h"
#include "esp_log.h"
#include <string.h>

static const char *TAG = "twai";
static int64_t s_last_ok_us;

bool twai_link_init(int tx_gpio, int rx_gpio)
{
    twai_general_config_t g = TWAI_GENERAL_CONFIG_DEFAULT(tx_gpio, rx_gpio, TWAI_MODE_NORMAL);
    g.tx_queue_len = 8; g.rx_queue_len = 8;
    twai_timing_config_t t = TWAI_TIMING_CONFIG_500KBITS();
    twai_filter_config_t f = TWAI_FILTER_CONFIG_ACCEPT_ALL();     /* we only transmit; accept-all keeps the ESP32 ACKing */
    if (twai_driver_install(&g, &t, &f) != ESP_OK) return false;
    if (twai_start() != ESP_OK) return false;
    s_last_ok_us = esp_timer_get_time();
    ESP_LOGI(TAG, "TWAI 500 kbit/s on TX %d RX %d", tx_gpio, rx_gpio);
    return true;
}

bool twai_link_send_env(const uint8_t *env, size_t len)
{
    if (len != 22) return false;
    static const uint32_t ids[3] = { 0x206, 0x207, 0x208 };
    static const uint8_t lens[3] = { 8, 8, 6 };
    for (int i = 0; i < 3; i++) {
        twai_message_t m = { 0 };
        m.identifier = ids[i]; m.data_length_code = lens[i];
        memcpy(m.data, env + 8 * i, lens[i]);
        if (twai_transmit(&m, pdMS_TO_TICKS(100)) != ESP_OK) { ESP_LOGW(TAG, "tx fail frame %d", i); return false; }
    }
    s_last_ok_us = esp_timer_get_time();
    return true;
}

bool twai_link_unhealthy(void)
{
    twai_status_info_t st;
    if (twai_get_status_info(&st) != ESP_OK) return true;
    if (st.state == TWAI_STATE_BUS_OFF || st.state == TWAI_STATE_STOPPED) return true;
    return (esp_timer_get_time() - s_last_ok_us) > 60 * 1000000LL;
}

void twai_link_recover(void)
{
    twai_status_info_t st;
    if (twai_get_status_info(&st) == ESP_OK && st.state == TWAI_STATE_BUS_OFF) { twai_initiate_recovery(); }
    else if (st.state == TWAI_STATE_STOPPED) twai_start();
}

#include "mqtt_fallback.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "mqtt_client.h"
#include <string.h>
#include <stdio.h>

static const char *TAG = "mqttfb";
static esp_mqtt_client_handle_t s_client;
static volatile bool s_connected;
static char s_topic[128];

/* Device certificate / key / CA are embedded at build time (EMBED_TXTFILES in main/CMakeLists.txt) in production; the
 * placeholders below keep the file self-contained. */
extern const uint8_t ca_pem_start[] asm("_binary_ca_pem_start") __attribute__((weak));
extern const uint8_t cert_pem_start[] asm("_binary_cert_pem_start") __attribute__((weak));
extern const uint8_t key_pem_start[] asm("_binary_key_pem_start") __attribute__((weak));

static void mqtt_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg; (void)base; (void)data;
    if (id == MQTT_EVENT_CONNECTED) { s_connected = true; ESP_LOGI(TAG, "connected"); }
    else if (id == MQTT_EVENT_DISCONNECTED) { s_connected = false; ESP_LOGW(TAG, "disconnected"); }
}

static void wifi_event(void *arg, esp_event_base_t base, int32_t id, void *data)
{
    (void)arg; (void)data;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) esp_wifi_connect();
    else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) esp_wifi_connect();
    else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) { if (s_client) esp_mqtt_client_start(s_client); }
}

bool mqtt_fallback_start(const char *ssid, const char *pass, const char *uri, const char *station, const char *lane)
{
    snprintf(s_topic, sizeof s_topic, "kifaru/stations/%s/lanes/%s/aux", station, lane);
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t wcfg = WIFI_INIT_CONFIG_DEFAULT();
    if (esp_wifi_init(&wcfg) != ESP_OK) return false;
    esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event, NULL);
    esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event, NULL);
    wifi_config_t sta = { 0 };
    strncpy((char *)sta.sta.ssid, ssid, sizeof sta.sta.ssid - 1);
    strncpy((char *)sta.sta.password, pass, sizeof sta.sta.password - 1);
    esp_wifi_set_mode(WIFI_MODE_STA);
    esp_wifi_set_config(WIFI_IF_STA, &sta);

    esp_mqtt_client_config_t m = { 0 };
    m.broker.address.uri = uri;
    m.broker.verification.certificate = (const char *)ca_pem_start;          /* NULL -> skip (dev only) */
    m.credentials.authentication.certificate = (const char *)cert_pem_start;  /* mTLS device cert */
    m.credentials.authentication.key = (const char *)key_pem_start;
    m.session.protocol_ver = MQTT_PROTOCOL_V_5;
    m.session.keepalive = 60;
    m.session.last_will.topic = s_topic; m.session.last_will.msg = "{\"status\":\"offline\"}"; m.session.last_will.qos = 1; m.session.last_will.retain = 1;
    s_client = esp_mqtt_client_init(&m);
    if (!s_client) return false;
    esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID, mqtt_event, NULL);
    return esp_wifi_start() == ESP_OK;
}

void mqtt_fallback_stop(void)
{
    if (s_client) esp_mqtt_client_stop(s_client);
    esp_wifi_stop();
    s_connected = false;
}

bool mqtt_fallback_publish(const char *json)
{
    if (!s_client || !s_connected) return false;
    return esp_mqtt_client_publish(s_client, s_topic, json, 0, 1, 1) >= 0;
}

bool mqtt_fallback_connected(void) { return s_connected; }

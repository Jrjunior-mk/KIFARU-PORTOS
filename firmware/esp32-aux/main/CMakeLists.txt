idf_component_register(
    SRCS "main.c" "sht4x.c" "max31865.c" "twai_link.c" "mqtt_fallback.c" "env_frame.c"
    INCLUDE_DIRS "."
    REQUIRES driver esp_wifi esp_event nvs_flash mqtt esp_timer esp_adc esp_netif esp-tls)

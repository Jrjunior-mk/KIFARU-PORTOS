/* Wi-Fi + MQTT (esp-mqtt, TLS) fallback: used only while the CAN link is unhealthy. Publishes the ENV JSON to
 * kifaru/stations/{station}/lanes/{lane}/aux (QoS 1, retained) so the gateway/cloud still see cabinet state. */
#ifndef MQTT_FALLBACK_H
#define MQTT_FALLBACK_H
#include <stdbool.h>

bool mqtt_fallback_start(const char *ssid, const char *pass, const char *uri, const char *station, const char *lane);
void mqtt_fallback_stop(void);
bool mqtt_fallback_publish(const char *json);
bool mqtt_fallback_connected(void);

#endif

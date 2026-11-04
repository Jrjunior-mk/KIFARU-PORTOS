#include "env_frame.h"
#include <stdio.h>
#include <inttypes.h>

static void put16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }

size_t env_encode(const env_t *e, uint8_t o[ENV_LEN])
{
    for (int i = 0; i < 8; i++) o[i] = (uint8_t)(e->t_us >> (8 * i));
    put16(o + 8, (uint16_t)e->pavement_c_x100);
    put16(o + 10, (uint16_t)e->ambient_c_x100);
    put16(o + 12, e->rh_x100);
    put16(o + 14, (uint16_t)e->cabinet_c_x100);
    put16(o + 16, e->bus_mv);
    put16(o + 18, e->batt_mv);
    o[20] = e->digital; o[21] = 0;
    return ENV_LEN;
}

int env_to_json(const env_t *e, const char *station, const char *lane, char *out, size_t cap)
{
    return snprintf(out, cap,
        "{\"type\":\"sensor.health\",\"producer\":\"esp32-aux-%s-%s\",\"schema_version\":1,\"t_us\":%" PRIu64 ","
        "\"pavement_temp_c\":%.2f,\"ambient_temp_c\":%.2f,\"ambient_rh_pct\":%.2f,\"cabinet_temp_c\":%.2f,"
        "\"bus_v\":%.3f,\"batt_v\":%.3f,\"door_open\":%s,\"ac_fail\":%s,\"batt_low\":%s,\"spd_fault\":%s,\"fan_on\":%s}",
        station, lane, e->t_us, e->pavement_c_x100 / 100.0, e->ambient_c_x100 / 100.0, e->rh_x100 / 100.0, e->cabinet_c_x100 / 100.0,
        e->bus_mv / 1000.0, e->batt_mv / 1000.0,
        (e->digital & ENV_BIT_DOOR_OPEN) ? "true" : "false", (e->digital & ENV_BIT_AC_FAIL) ? "true" : "false",
        (e->digital & ENV_BIT_BATT_LOW) ? "true" : "false", (e->digital & ENV_BIT_SPD_FAULT) ? "true" : "false",
        (e->digital & ENV_BIT_FAN_ON) ? "true" : "false");
}

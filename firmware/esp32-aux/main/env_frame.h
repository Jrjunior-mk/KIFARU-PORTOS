/* ENV payload (22 bytes) — byte-exact with docs/03-hardware/communications.md §1.5 and stm32-wim-daq/App/frames.h */
#ifndef ENV_FRAME_H
#define ENV_FRAME_H
#include <stdint.h>
#include <stddef.h>

#define ENV_LEN 22
#define ENV_BIT_DOOR_OPEN  (1u << 0)
#define ENV_BIT_AC_FAIL    (1u << 1)
#define ENV_BIT_BATT_LOW   (1u << 2)
#define ENV_BIT_SPD_FAULT  (1u << 3)
#define ENV_BIT_FAN_ON     (1u << 4)

typedef struct {
    uint64_t t_us;
    int16_t  pavement_c_x100;
    int16_t  ambient_c_x100;
    uint16_t rh_x100;
    int16_t  cabinet_c_x100;
    uint16_t bus_mv;
    uint16_t batt_mv;
    uint8_t  digital;
} env_t;

size_t env_encode(const env_t *e, uint8_t out[ENV_LEN]);
/* JSON for the MQTT fallback / retained health; returns chars written */
int    env_to_json(const env_t *e, const char *station, const char *lane, char *out, size_t cap);

#endif

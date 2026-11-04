#include "loop_detector.h"
#include <string.h>

static loop_state_t s_loops[LOOP_COUNT];
static loop_event_cb_t s_cb;

void loop_detector_init(loop_event_cb_t cb)
{
    memset(s_loops, 0, sizeof s_loops);
    s_cb = cb;
}

void loop_detector_isr(uint8_t i, bool level, uint64_t t_us)
{
    if (i >= LOOP_COUNT) return;
    loop_state_t *l = &s_loops[i];
    l->edges++;
    if (level == l->occupied) { l->t_last_raw_us = t_us; return; }          /* glitch back to same state */
    if ((t_us - l->t_change_us) < LOOP_DEBOUNCE_US && l->edges > 1) { l->bounces++; return; }
    l->occupied = level;
    l->t_change_us = t_us;
    l->t_last_raw_us = t_us;
    if (level) l->occupancy_count++;
    if (s_cb) s_cb((uint8_t)(i + 1), level, t_us);
}

const loop_state_t *loop_detector_state(uint8_t i) { return (i < LOOP_COUNT) ? &s_loops[i] : 0; }

float loop_detector_vehicle_length_m(uint64_t t_enter_us, uint64_t t_leave_us, float speed_mps, float loop_len_m)
{
    if (t_leave_us <= t_enter_us || speed_mps <= 0.0f) return 0.0f;
    float occ_s = (float)(t_leave_us - t_enter_us) * 1e-6f;
    float len = occ_s * speed_mps - loop_len_m;    /* occupancy covers vehicle length + loop length */
    return len > 0.0f ? len : 0.0f;
}

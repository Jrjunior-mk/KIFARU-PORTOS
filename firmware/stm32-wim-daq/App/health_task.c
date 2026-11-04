/**
 * @file health_task.c
 * @brief Sensor health (WIM-07): every HEALTH_PERIOD_MS snapshot the idle statistics kept by detect_task and compute
 *        per-row noise RMS, dead channel (max |x| < 50 kg-eq over the window AND no pass in progress is not enough: a
 *        quiet lane is also quiet — the dead flag is confirmed only when the partner rows saw axles while this row did
 *        not, which is done per pass in wim_fuse_pass; here we flag 'no_signal' as a hint), saturation count, 50 Hz hum
 *        (Goertzel magnitude), baseline drift between windows, and IR stuck beams. Also pulses the charge-amp reset
 *        when the idle baseline exceeds ±2 V equivalent with no vehicle present.
 */
#include "tasks.h"
#include "timebase.h"
#include "../Drivers/ir_beam.h"
#include "../Drivers/loop_detector.h"
#include <math.h>
#include <string.h>

#define BASELINE_RESET_KG  (2.0f / 0.1338e-3f)   /* 2 V at the ADC input, per wheel, in kg-eq (~15 t) */

void health_task(void *arg)
{
    (void)arg;
    chan_stats_t st[WIM_MAX_ROWS];
    bool idle;
    TickType_t last_health = xTaskGetTickCount();
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(1000));
        uint64_t now = timebase_now_us();
        bool any_loop = false;
        for (int l = 0; l < LOOP_COUNT; l++) { const loop_state_t *ls = loop_detector_state((uint8_t)l); any_loop |= (ls && ls->occupied); }
        ir_beam_poll(now, any_loop);
        wdg_checkin(WDG_HEALTH);

        if ((xTaskGetTickCount() - last_health) < pdMS_TO_TICKS(HEALTH_PERIOD_MS)) continue;
        last_health = xTaskGetTickCount();

        detect_get_stats(st, &idle);
        frm_health_t h; memset(&h, 0, sizeof h);
        h.t_us = timebase_to_utc_us(now);
        h.first_channel = 0; h.n_ch = 8;    /* rows reported as channel pairs: P1(0,1) P2(2,3) P3(4,5) BP(6,7) -> same value on both */
        bool need_reset = false;
        for (int r = 0; r < WIM_MAX_ROWS; r++) {
            float n = st[r].n ? (float)st[r].n : 1.0f;
            float mean = st[r].sum / n;
            float var = st[r].sum2 / n - mean * mean; if (var < 0) var = 0;
            float rms = sqrtf(var);
            /* Goertzel magnitude normalised to an rms-equivalent amplitude */
            float coeff = 1.9984590f;
            float mag2 = st[r].goertzel_s1 * st[r].goertzel_s1 + st[r].goertzel_s2 * st[r].goertzel_s2 - coeff * st[r].goertzel_s1 * st[r].goertzel_s2;
            float hum = sqrtf(mag2 > 0 ? mag2 : 0) * 2.0f / n / 1.41421356f;
            float drift_per_min = fabsf(mean - st[r].baseline_prev_kg) * (60000.0f / (float)HEALTH_PERIOD_MS);

            uint8_t flags = 0, status = WIM_HEALTH_OK;
            if (st[r].max_abs < HEALTH_DEAD_KG && st[r].n > 1000) flags |= 1u;              /* no signal hint */
            if (st[r].sat_count > 8) { flags |= 2u; status = WIM_HEALTH_FAULT; }
            if (rms > HEALTH_NOISE_DEGRADED_KG) { flags |= 4u; if (status == WIM_HEALTH_OK) status = WIM_HEALTH_DEGRADED; }
            if (drift_per_min > HEALTH_DRIFT_KG_PER_MIN) { flags |= 8u; if (status == WIM_HEALTH_OK) status = WIM_HEALTH_DEGRADED; }
            if (hum > HEALTH_HUM50_KG) { flags |= 16u; if (status == WIM_HEALTH_OK) status = WIM_HEALTH_DEGRADED; }
            if (fabsf(mean) > BASELINE_RESET_KG && r != WIM_ROW_BP) need_reset = true;

            for (int side = 0; side < 2; side++) {
                frm_health_ch_t *c = &h.ch[2 * r + side];
                float rx10 = rms * 10.0f; c->noise_rms_kg_x10 = (uint16_t)(rx10 > 65535.0f ? 65535.0f : rx10);
                float b = mean; if (b > 32767.0f) b = 32767.0f; if (b < -32768.0f) b = -32768.0f; c->baseline_kg = (int16_t)b;
                c->status = status; c->flags = flags;
            }
        }
        /* time-sync holdover and IR stuck beams are reported through the spare flag bits of channel 7 */
        if (!timebase_is_synced(now)) h.ch[7].flags |= 0x40u;
        for (int b = 0; b < IR_COUNT; b++) { const ir_state_t *s = ir_beam_state((uint8_t)b); if (s && s->stuck) h.ch[7].flags |= 0x80u; }

        uint8_t buf[FRM_MAX_PAYLOAD];
        comms_post(FRM_HEALTH, buf, frm_encode_health(&h, buf, sizeof buf), false);
        detect_reset_stats();

        if (need_reset && idle && !any_loop) afe_reset_pulse();
    }
}

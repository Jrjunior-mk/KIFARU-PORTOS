/**
 * @file detect_task.c
 * @brief Real-time port of kifaru_wim_dsp.pipeline.process_pass:
 *        per-row kg scaling (L+R), 4th-order IIR, baseline median of 0.2 s pre-trigger, streaming pulse detection with
 *        hysteresis and merging, pass state machine driven by pulses and loops, fusion (speed, loads, grouping,
 *        uncertainty, flags), AXLE_EVENT / PASS_SUMMARY emission. Also maintains idle channel statistics for health.
 */
#include "tasks.h"
#include "timebase.h"
#include "../Drivers/loop_detector.h"
#include <string.h>
#include <math.h>

/* ------------------------------------------------------------------ configuration */
static const uint8_t ROW_CH[WIM_MAX_ROWS][2] = { {CH_P1L, CH_P1R}, {CH_P2L, CH_P2R}, {CH_P3L, CH_P3R}, {CH_BPL, CH_BPR} };

static wim_pass_cfg_t s_cfg = {
    .row_pos_m = { GEO_P1_M, GEO_P2_M, GEO_P3_M, GEO_BP_M },
    .cal = { {1.0f, 0.0f, 0.0f, 25.0f, 0.02f}, {1.0f, 0.0f, 0.0f, 25.0f, 0.02f}, {1.0f, 0.0f, 0.0f, 25.0f, 0.02f}, {1.0f, 0.0f, 0.0f, 25.0f, 0.015f} },
    .fs = ACQ_FS_HZ,
    .rf_tau_s = AFE_RF_TAU_S,
};

/* ------------------------------------------------------------------ state */
typedef enum { PASS_IDLE = 0, PASS_ACTIVE = 1 } pass_state_t;

static wim_lp4_t        s_lp[WIM_MAX_ROWS];
static float            s_ring[WIM_MAX_ROWS][WIM_PRE_N];   /* filtered kg, pre-trigger history */
static float            s_scratch[WIM_PRE_N];
static int              s_ring_pos;
static float            s_baseline[WIM_MAX_ROWS];
static wim_pulse_det_t  s_det[WIM_MAX_ROWS];
static wim_pass_pulses_t s_pulses;
static pass_state_t     s_state;
static uint32_t         s_pass_id;
static uint32_t         s_pass_start_n, s_last_pulse_end_n;
static uint64_t         s_anchor_t_us; static uint32_t s_anchor_n;   /* t(n) = anchor_t + (n - anchor_n) * 125 */
static bool             s_l3_seen;
static volatile bool    s_loop_occ[LOOP_COUNT];
static volatile float   s_pavement_c = 30.0f;
static chan_stats_t     s_stats[WIM_MAX_ROWS];
static float            s_exc_ratio = 1.0f;
static uint32_t         s_loop_vehicles, s_pass_vehicles;

static inline uint64_t t_of_n(uint32_t n) { return s_anchor_t_us + (uint64_t)(n - s_anchor_n) * 125u; }

/* ------------------------------------------------------------------ shared-state API */
void detect_set_pavement_temp(float c) { s_pavement_c = c; }
float detect_get_pavement_temp(void) { return s_pavement_c; }
bool detect_is_idle(void) { return s_state == PASS_IDLE; }

void detect_loop_event(uint8_t loop_id, bool occupied, uint64_t t_us)
{
    frm_loop_event_t e = { .t_us = timebase_to_utc_us(t_us), .id = loop_id, .state = occupied ? 1 : 0 };
    uint8_t buf[FRM_LOOP_EVENT_LEN];
    comms_post(FRM_LOOP_EVENT, buf, frm_encode_loop_event(&e, buf, sizeof buf), true);
    if (loop_id >= 1 && loop_id <= LOOP_COUNT) s_loop_occ[loop_id - 1] = occupied;
    if (loop_id == 1 && occupied) s_loop_vehicles++;
    if (loop_id == 3) s_l3_seen = occupied ? true : s_l3_seen;
}

void detect_ir_event(uint8_t beam_id, bool blocked, uint64_t t_us)
{
    frm_loop_event_t e = { .t_us = timebase_to_utc_us(t_us), .id = beam_id, .state = blocked ? 1 : 0 };
    uint8_t buf[FRM_LOOP_EVENT_LEN];
    comms_post(FRM_IR_EVENT, buf, frm_encode_loop_event(&e, buf, sizeof buf), true);
}

void detect_get_stats(chan_stats_t out[WIM_MAX_ROWS], bool *idle)
{
    xSemaphoreTake(m_stats, portMAX_DELAY);
    memcpy(out, s_stats, sizeof s_stats);
    *idle = (s_state == PASS_IDLE);
    xSemaphoreGive(m_stats);
}

void detect_reset_stats(void)
{
    xSemaphoreTake(m_stats, portMAX_DELAY);
    for (int r = 0; r < WIM_MAX_ROWS; r++) {
        float mean = s_stats[r].n ? s_stats[r].sum / (float)s_stats[r].n : 0.0f;
        memset(&s_stats[r], 0, sizeof s_stats[r]);
        s_stats[r].baseline_prev_kg = mean;
    }
    xSemaphoreGive(m_stats);
}

/* ------------------------------------------------------------------ helpers */
static float row_kg(const int32_t *raw, int r)
{
    float k = (r == WIM_ROW_BP) ? AFE_PLATE_KG_PER_LSB : AFE_PIEZO_KG_PER_LSB;
    float v = ((float)raw[ROW_CH[r][0]] + (float)raw[ROW_CH[r][1]]) * k;
    if (r == WIM_ROW_BP) v *= s_exc_ratio;        /* ratiometric: nominal / measured excitation */
    return v;
}

static void update_idle_stats(int r, float x_kg, bool raw_sat)
{
    chan_stats_t *s = &s_stats[r];
    s->sum += x_kg; s->sum2 += x_kg * x_kg; s->n++;
    float a = fabsf(x_kg); if (a > s->max_abs) s->max_abs = a;
    if (raw_sat) s->sat_count++;
    /* Goertzel at 50 Hz, fs 8 kHz: coeff = 2 cos(2*pi*50/8000) = 1.9984590 */
    float s0 = x_kg + 1.9984590f * s->goertzel_s1 - s->goertzel_s2;
    s->goertzel_s2 = s->goertzel_s1; s->goertzel_s1 = s0;
}

static void start_pass(uint32_t n_now)
{
    s_state = PASS_ACTIVE;
    s_pass_id++;
    s_pass_start_n = n_now;
    s_last_pulse_end_n = n_now;
    s_l3_seen = false;
    memset(&s_pulses, 0, sizeof s_pulses);
    for (int r = 0; r < WIM_MAX_ROWS; r++) {
        /* baseline = median of the 0.2 s pre-trigger window (same statistic as remove_baseline) */
        memcpy(s_scratch, s_ring[r], sizeof s_scratch);
        s_baseline[r] = wim_median(s_scratch, WIM_PRE_N);
        /* pre-trigger rms about that baseline, for health */
        double acc = 0.0; for (int i = 0; i < WIM_PRE_N; i++) { double d = s_ring[r][i] - s_baseline[r]; acc += d * d; }
        s_pulses.noise_rms[r] = (float)sqrt(acc / WIM_PRE_N);
        wim_pulse_det_init(&s_det[r], DET_THRESHOLD_KG, DET_MIN_GAP_S, ACQ_FS_HZ,
                           (r == WIM_ROW_BP) ? AFE_PLATE_SAT_KG * 2.0f : AFE_PIEZO_SAT_KG * 2.0f);
    }
}

static void emit_pass(void)
{
    wim_pass_result_t res;
    wim_fuse_pass(&s_cfg, &s_pulses, &res);
    s_pass_vehicles++;

    /* loop/axle-train consistency (per hour): more than 5 % mismatch => degraded */
    if (s_loop_vehicles > 20) {
        int diff = (int)s_loop_vehicles - (int)s_pass_vehicles; if (diff < 0) diff = -diff;
        if ((float)diff / (float)s_loop_vehicles > 0.05f) res.quality_flags |= WIM_QF_LOOP_INCONSISTENT;
    }
    if (s_pavement_c > 60.0f) res.quality_flags |= WIM_QF_PAVEMENT_HOT;

    uint8_t buf[FRM_MAX_PAYLOAD];
    uint64_t t_first = 0;
    for (int i = 0; i < res.axle_count; i++) {
        frm_axle_event_t a; memset(&a, 0, sizeof a);
        a.pass_id = s_pass_id; a.axle_index = (uint8_t)i;
        for (int r = 0; r < WIM_MAX_ROWS; r++) {
            if (!res.axles[i].rows[r].present) continue;
            a.rows_valid |= (uint8_t)(1u << r);
            a.t_row_us[r] = timebase_to_utc_us(t_of_n(res.axles[i].rows[r].peak_n));
            float L = res.axles[i].rows[r].load_kg; a.load_row_kg[r] = (uint16_t)(L < 0 ? 0 : (L > 65535.0f ? 65535.0f : L));
            if (s_pulses.p[r][i].saturated) a.flags |= 1u;
        }
        if (i == 0) t_first = a.t_row_us[WIM_ROW_P1] ? a.t_row_us[WIM_ROW_P1] : timebase_to_utc_us(t_of_n(s_pass_start_n));
        a.speed_cmps = (uint16_t)(res.speed_mps * 100.0f);
        if (i > 0 && res.axles[i - 1].spacing_next_m >= 0.0f) { float mm = res.axles[i - 1].spacing_next_m * 1000.0f; a.spacing_prev_mm = (uint16_t)(mm > 65535.0f ? 65535.0f : mm); }
        comms_post(FRM_AXLE_EVENT, buf, frm_encode_axle_event(&a, buf, sizeof buf), false);
    }

    frm_pass_summary_t s; memset(&s, 0, sizeof s);
    s.pass_id = s_pass_id; s.t_first_axle_us = t_first ? t_first : timebase_to_utc_us(t_of_n(s_pass_start_n));
    s.axle_count = res.axle_count; s.n_groups = res.n_groups; s.quality_flags = res.quality_flags;
    s.speed_cmps = (uint16_t)(res.speed_mps * 100.0f); s.speed_u_cmps = (uint16_t)(res.speed_u_mps * 100.0f);
    s.gvm_kg = (uint32_t)(res.gvm_kg < 0 ? 0 : res.gvm_kg); s.gvm_u_kg = (uint32_t)res.gvm_u_kg;
    s.pavement_temp_c_x10 = (int16_t)(s_pavement_c * 10.0f);
    for (int r = 0; r < WIM_MAX_ROWS; r++) s.sensor_health[r] = res.health[r];
    for (int l = 0; l < LOOP_COUNT; l++) s.sensor_health[4 + l] = WIM_HEALTH_OK;   /* loop card faults arrive via EXTI fault line (not modelled) */
    s.sensor_health[7] = WIM_HEALTH_NA;
    s.n_axles_included = res.axle_count;
    for (int i = 0; i < res.axle_count; i++) {
        s.axles[i].load_kg = (uint16_t)res.axles[i].load_kg;
        float u = res.axles[i].u_kg; s.axles[i].u_kg = (uint16_t)(u > 65535.0f ? 65535.0f : u);
        s.axles[i].spacing_next_mm = res.axles[i].spacing_next_m < 0 ? 0xFFFFu : (uint16_t)(res.axles[i].spacing_next_m * 1000.0f);
        s.axles[i].group_no = res.axles[i].group_no;
    }
    comms_post(FRM_PASS_SUMMARY, buf, frm_encode_pass_summary(&s, buf, sizeof buf, true), false);
}

/* ------------------------------------------------------------------ task */
void detect_task(void *arg)
{
    (void)arg;
    acq_block_t blk;
    for (int r = 0; r < WIM_MAX_ROWS; r++) wim_lp4_init(&s_lp[r]);
    memset(s_ring, 0, sizeof s_ring);
    s_state = PASS_IDLE;

    for (;;) {
        if (xQueueReceive(q_blocks, &blk, pdMS_TO_TICKS(500)) != pdTRUE) { wdg_checkin(WDG_DETECT); continue; }
        if (s_state == PASS_IDLE) { s_anchor_t_us = blk.t_first_us; s_anchor_n = blk.n_first; }
        /* excitation ratio for the plate (ADC B ch0 through a 4:1 divider) */
        float exc = (float)blk.raw[0][CH_EXC_MON] * (1.2f / 8388608.0f) * AFE_EXC_DIVIDER;
        if (exc > 4.0f && exc < 6.0f) s_exc_ratio = AFE_EXC_NOMINAL_V / exc;

        for (int k = 0; k < blk.n; k++) {
            uint32_t n = blk.n_first + (uint32_t)k;
            bool any_trigger = false;
            for (int r = 0; r < WIM_MAX_ROWS; r++) {
                const int32_t *raw = blk.raw[k];
                bool raw_sat = (raw[ROW_CH[r][0]] >= 0x7FFFF0 || raw[ROW_CH[r][1]] >= 0x7FFFF0 || raw[ROW_CH[r][0]] <= -0x7FFFF0 || raw[ROW_CH[r][1]] <= -0x7FFFF0);
                float y = wim_lp4_step(&s_lp[r], row_kg(raw, r));
                if (s_state == PASS_IDLE) {
                    s_ring[r][s_ring_pos] = y;
                    update_idle_stats(r, y - s_baseline[r], raw_sat);
                    /* trigger on a threshold crossing of the baseline-corrected signal (baseline = running median proxy: last) */
                    if ((y - s_baseline[r]) > DET_THRESHOLD_KG) any_trigger = true;
                } else {
                    float x = wim_apply_cal(&s_cfg.cal[r], y - s_baseline[r], s_pavement_c);
                    float ax = fabsf(x); if (ax > s_pulses.peak_abs[r]) s_pulses.peak_abs[r] = ax;
                    if (raw_sat) s_pulses.saturated[r] = true;
                    wim_pulse_t p;
                    if (wim_pulse_det_step(&s_det[r], n, x, &p) && s_pulses.n[r] < WIM_MAX_AXLES) {
                        s_pulses.p[r][s_pulses.n[r]++] = p;
                        if (p.saturated) s_pulses.saturated[r] = true;
                        s_last_pulse_end_n = p.end;
                    }
                    if (s_det[r].in_pulse) s_last_pulse_end_n = n;
                }
            }
            if (s_state == PASS_IDLE) {
                if (++s_ring_pos >= WIM_PRE_N) s_ring_pos = 0;
                /* idle baseline proxy: slow mean so the trigger test uses a sane reference between passes */
                if ((n & 0x3FFu) == 0) for (int r = 0; r < WIM_MAX_ROWS; r++) { memcpy(s_scratch, s_ring[r], sizeof s_scratch); s_baseline[r] = wim_median(s_scratch, WIM_PRE_N); }
                if (any_trigger || (s_loop_occ[0] && GEO_LOOP_LEN_M > 0.0f)) {
                    start_pass(n);
                    /* re-run this sample through the detectors so the triggering sample is not lost */
                    for (int r = 0; r < WIM_MAX_ROWS; r++) {
                        float x = wim_apply_cal(&s_cfg.cal[r], s_ring[r][(s_ring_pos + WIM_PRE_N - 1) % WIM_PRE_N] - s_baseline[r], s_pavement_c);
                        wim_pulse_t p; (void)wim_pulse_det_step(&s_det[r], n, x, &p);
                    }
                }
            } else {
                bool l3_cleared = s_l3_seen && !s_loop_occ[2];
                bool quiet = (n - s_last_pulse_end_n) > (uint32_t)(DET_PASS_TIMEOUT_MS * 8u);
                bool too_long = (n - s_pass_start_n) > (uint32_t)(DET_MAX_PASS_MS * 8u);
                bool any_in_pulse = false; for (int r = 0; r < WIM_MAX_ROWS; r++) any_in_pulse |= s_det[r].in_pulse;
                if (!any_in_pulse && ((l3_cleared && (n - s_last_pulse_end_n) > 8u * 300u) || quiet || too_long)) {
                    for (int r = 0; r < WIM_MAX_ROWS; r++) { wim_pulse_t p; if (wim_pulse_det_flush(&s_det[r], &p) && s_pulses.n[r] < WIM_MAX_AXLES) s_pulses.p[r][s_pulses.n[r]++] = p; }
                    emit_pass();
                    s_state = PASS_IDLE;
                    for (int r = 0; r < WIM_MAX_ROWS; r++) wim_lp4_reset(&s_lp[r]);   /* avoid carrying a tail into the ring */
                }
            }
        }
        wdg_checkin(WDG_DETECT);
    }
}

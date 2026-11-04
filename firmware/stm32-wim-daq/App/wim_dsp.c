/**
 * @file wim_dsp.c
 * @brief Portable WIM DSP core — see wim_dsp.h. No HAL, no RTOS, no malloc.
 */
#include "wim_dsp.h"
#include <math.h>
#include <string.h>

/* ------------------------------------------------------------------ 4th-order Butterworth 1 kHz @ 8 kHz
 * scipy.signal.butter(4, 1000/4000, output='sos'):
 *   section 0: b = [0.010209480791, 0.020418961582, 0.010209480791]  a = [1, -0.855397932775, 0.209715357757]
 *   section 1: b = [1,              2,              1             ]  a = [1, -1.113029854163, 0.574061915084]
 * (scipy puts the whole gain in section 0.)  Analog check: -3.01 dB @ 1 kHz, -30.6 dB @ 2 kHz, -61 dB @ 3 kHz.
 */
void wim_lp4_init(wim_lp4_t *f)
{
    f->sec[0].b0 = 0.010209480791f; f->sec[0].b1 = 0.020418961582f; f->sec[0].b2 = 0.010209480791f;
    f->sec[0].a1 = -0.855397932775f; f->sec[0].a2 = 0.209715357757f;
    f->sec[1].b0 = 1.0f; f->sec[1].b1 = 2.0f; f->sec[1].b2 = 1.0f;
    f->sec[1].a1 = -1.113029854163f; f->sec[1].a2 = 0.574061915084f;
    wim_lp4_reset(f);
}

void wim_lp4_reset(wim_lp4_t *f)
{
    for (int i = 0; i < 2; i++) { f->sec[i].s1 = 0.0f; f->sec[i].s2 = 0.0f; }
}

static inline float biquad_step(wim_biquad_t *b, float x)
{
    /* transposed direct form II */
    float y = b->b0 * x + b->s1;
    b->s1 = b->b1 * x - b->a1 * y + b->s2;
    b->s2 = b->b2 * x - b->a2 * y;
    return y;
}

float wim_lp4_step(wim_lp4_t *f, float x)
{
    return biquad_step(&f->sec[1], biquad_step(&f->sec[0], x));
}

/* ------------------------------------------------------------------ median (quickselect, Hoare partition) */
static float select_kth(float *a, int n, int k)
{
    int lo = 0, hi = n - 1;
    while (lo < hi) {
        float pivot = a[(lo + hi) / 2];
        int i = lo, j = hi;
        while (i <= j) {
            while (a[i] < pivot) i++;
            while (a[j] > pivot) j--;
            if (i <= j) { float t = a[i]; a[i] = a[j]; a[j] = t; i++; j--; }
        }
        if (k <= j) hi = j;
        else if (k >= i) lo = i;
        else break;
    }
    return a[k];
}

float wim_median(float *scratch, int n)
{
    if (n <= 0) return 0.0f;
    if (n & 1) return select_kth(scratch, n, n / 2);
    float hi = select_kth(scratch, n, n / 2);
    /* lower median = max of the lower half (elements [0, n/2) are all <= a[n/2] after selection) */
    float lo = scratch[0];
    for (int i = 1; i < n / 2; i++) if (scratch[i] > lo) lo = scratch[i];
    return 0.5f * (lo + hi);
}

/* ------------------------------------------------------------------ pulse detector */
void wim_pulse_det_init(wim_pulse_det_t *d, float threshold_kg, float min_gap_s, float fs, float sat_level_kg)
{
    memset(d, 0, sizeof(*d));
    d->threshold = threshold_kg;
    d->min_gap = (uint32_t)(min_gap_s * fs);
    d->dt = 1.0f / fs;
    d->sat_level = sat_level_kg;
}

static void merge_into_pending(wim_pulse_det_t *d)
{
    /* same tyre, noisy edge: extend the pending pulse (Python keeps the larger peak and the new end) */
    if (d->cur.peak_val > d->pending.peak_val) { d->pending.peak = d->cur.peak; d->pending.peak_val = d->cur.peak_val; }
    d->pending.end = d->cur.end;
    d->pending.integral += d->cur.integral;
    d->pending.saturated |= d->cur.saturated;
}

bool wim_pulse_det_step(wim_pulse_det_t *d, uint32_t n, float x, wim_pulse_t *out)
{
    bool emitted = false;

    /* 1. emit a pending pulse once min_gap has elapsed with no re-trigger */
    if (d->has_pending && !d->in_pulse && (n - d->pending.end) >= d->min_gap) {
        *out = d->pending;
        d->has_pending = false;
        emitted = true;
    }

    /* 2. state machine with 50 % hysteresis */
    if (!d->in_pulse) {
        if (x > d->threshold) {
            d->in_pulse = true;
            d->cur.start = n; d->cur.peak = n; d->cur.peak_val = x;
            d->cur.integral = (double)x * d->dt;
            d->cur.saturated = false; d->sat_run = 0;
        }
    } else {
        if (x > 0.5f * d->threshold) {
            d->cur.integral += (double)x * d->dt;
            if (x > d->cur.peak_val) { d->cur.peak_val = x; d->cur.peak = n; }
            if (d->sat_level > 0.0f && fabsf(x) >= d->sat_level) { if (++d->sat_run >= 8) d->cur.saturated = true; }
            else d->sat_run = 0;
        } else {
            d->cur.end = n;
            d->in_pulse = false;
            if (d->has_pending && (d->cur.start - d->pending.end) < d->min_gap) {
                merge_into_pending(d);
            } else {
                if (d->has_pending) { /* cannot happen: pending would have been emitted in step 1 */ }
                d->pending = d->cur;
                d->has_pending = true;
            }
        }
    }
    return emitted;
}

bool wim_pulse_det_flush(wim_pulse_det_t *d, wim_pulse_t *out)
{
    if (d->in_pulse) {              /* pass ended mid-pulse: close it at the current sample */
        d->cur.end = d->cur.peak + 1;
        d->in_pulse = false;
        if (d->has_pending && (d->cur.start - d->pending.end) < d->min_gap) merge_into_pending(d);
        else { d->pending = d->cur; d->has_pending = true; }
    }
    if (d->has_pending) { *out = d->pending; d->has_pending = false; return true; }
    return false;
}

/* ------------------------------------------------------------------ load from pulse */
float wim_pulse_load_kg(double integral_kg_s, float speed_mps, float contact_len_m, float rf_tau_s)
{
    if (speed_mps <= 0.0f) return 0.0f;
    float T = contact_len_m / speed_mps;
    float A = (float)(integral_kg_s * 3.14159265358979 / (2.0 * (double)T));
    if (rf_tau_s > 0.0f) A *= (1.0f + T / (2.0f * rf_tau_s));
    return A;
}

/* ------------------------------------------------------------------ health (mirror channel_health) */
uint8_t wim_row_health(float noise_rms_kg, float peak_abs_kg, bool saturated, int pulses, int expected_axles)
{
    if (peak_abs_kg < 50.0f) return WIM_HEALTH_FAULT;                     /* dead channel */
    bool degraded = false;
    if (noise_rms_kg > 800.0f) degraded = true;
    if (saturated) return WIM_HEALTH_FAULT;
    if (expected_axles >= 0 && pulses != expected_axles) {
        degraded = true;
        int diff = pulses - expected_axles; if (diff < 0) diff = -diff;
        if (diff > 1) return WIM_HEALTH_FAULT;
    }
    return degraded ? WIM_HEALTH_DEGRADED : WIM_HEALTH_OK;
}

/* ------------------------------------------------------------------ fusion (mirror process_pass) */
static int mode_count(const int *counts, int n)
{
    /* np.bincount(counts).argmax(): smallest value among the most frequent */
    int best = 0, best_f = -1;
    for (int i = 0; i < n; i++) {
        if (counts[i] <= 0) continue;
        int f = 0;
        for (int j = 0; j < n; j++) if (counts[j] == counts[i]) f++;
        if (f > best_f || (f == best_f && counts[i] < best)) { best_f = f; best = counts[i]; }
    }
    return best;
}

void wim_fuse_pass(const wim_pass_cfg_t *cfg, const wim_pass_pulses_t *pp, wim_pass_result_t *out)
{
    memset(out, 0, sizeof(*out));
    const float fs = cfg->fs;

    int counts[WIM_MAX_ROWS];
    for (int r = 0; r < WIM_MAX_ROWS; r++) counts[r] = pp->n[r];
    int axle_count = mode_count(counts, WIM_MAX_ROWS);
    if (axle_count <= 0) {
        for (int r = 0; r < WIM_MAX_ROWS; r++) out->health[r] = wim_row_health(pp->noise_rms[r], pp->peak_abs[r], pp->saturated[r], pp->n[r], -1);
        out->quality_flags |= WIM_QF_NO_AXLES;
        return;
    }
    if (axle_count > WIM_MAX_AXLES) axle_count = WIM_MAX_AXLES;
    out->axle_count = (uint8_t)axle_count;

    bool good[WIM_MAX_ROWS];
    int n_good = 0;
    for (int r = 0; r < WIM_MAX_ROWS; r++) {
        out->health[r] = wim_row_health(pp->noise_rms[r], pp->peak_abs[r], pp->saturated[r], pp->n[r], axle_count);
        good[r] = (out->health[r] != WIM_HEALTH_FAULT) && (pp->n[r] == axle_count);
        if (good[r]) n_good++;
        if (out->health[r] == WIM_HEALTH_FAULT) out->quality_flags |= WIM_QF_SENSOR_FAULT;
        if (out->health[r] == WIM_HEALTH_DEGRADED) out->quality_flags |= WIM_QF_SENSOR_DEGRADED;
        if (pp->saturated[r]) out->quality_flags |= WIM_QF_SATURATION;
    }

    /* --- speed from the two good piezo rows with the largest separation */
    int ra = -1, rb = -1;
    for (int r = WIM_ROW_P1; r <= WIM_ROW_P3; r++) if (good[r]) { if (ra < 0) ra = r; rb = r; }
    float speed = 15.0f, speed_u = 5.0f;
    if (ra >= 0 && rb > ra) {
        float dx = cfg->row_pos_m[rb] - cfg->row_pos_m[ra];
        float v[WIM_MAX_AXLES]; int nv = 0;
        for (int i = 0; i < axle_count; i++) {
            float dt = (float)((int32_t)(pp->p[rb][i].peak - pp->p[ra][i].peak)) / fs;
            if (dt > 0.0f) v[nv++] = dx / dt;
        }
        if (nv > 0) {
            float m = 0.0f; for (int i = 0; i < nv; i++) m += v[i]; m /= (float)nv;
            speed = m;
            if (nv > 1) {
                float ss = 0.0f; for (int i = 0; i < nv; i++) ss += (v[i] - m) * (v[i] - m);
                speed_u = 2.0f * sqrtf(ss / (float)(nv - 1)) / sqrtf((float)nv);
            } else speed_u = 0.5f;
        } else out->quality_flags |= WIM_QF_SPEED_UNAVAILABLE;
    } else out->quality_flags |= WIM_QF_SPEED_UNAVAILABLE;
    if (speed < 3.0f || speed > 30.0f) out->quality_flags |= WIM_QF_SPEED_OUT_OF_RANGE;
    out->speed_mps = speed; out->speed_u_mps = speed_u;

    /* --- spacings from the first good row (fallback: P1) */
    int ref = -1; for (int r = 0; r < WIM_MAX_ROWS; r++) if (good[r]) { ref = r; break; }
    if (ref < 0) ref = WIM_ROW_P1;
    for (int i = 0; i < axle_count; i++) {
        out->axles[i].spacing_next_m = -1.0f;
        if (i + 1 < axle_count && i + 1 < pp->n[ref])
            out->axles[i].spacing_next_m = ((float)(pp->p[ref][i + 1].peak - pp->p[ref][i].peak) / fs) * speed;
    }

    /* --- per-row loads and fusion */
    for (int i = 0; i < axle_count; i++) {
        wim_axle_t *ax = &out->axles[i];
        float wsum = 0.0f, wv = 0.0f; int nvals = 0;
        for (int r = 0; r < WIM_MAX_ROWS; r++) {
            ax->rows[r].present = false;
            if (!good[r]) continue;
            bool piezo = (r != WIM_ROW_BP);
            float contact = piezo ? (WIM_TYRE_CONTACT_LEN_M + WIM_STRIP_WIDTH_M) : (WIM_PLATE_LEN_M + WIM_TYRE_CONTACT_LEN_M);
            float L = wim_pulse_load_kg(pp->p[r][i].integral, speed, contact, piezo ? cfg->rf_tau_s : 0.0f);
            ax->rows[r].present = true; ax->rows[r].peak_n = pp->p[r][i].peak; ax->rows[r].load_kg = L;
            float w = (r == WIM_ROW_BP) ? 3.0f : 1.0f;
            wsum += w; wv += w * L; nvals++;
        }
        if (nvals == 0) { out->quality_flags |= WIM_QF_AXLE_LOAD_MISSING; ax->load_kg = 0.0f; ax->u_kg = 1e9f; ax->group_no = 1; continue; }
        float mean = wv / wsum;
        float type_a, type_b2 = 0.0f;
        if (nvals > 1) {
            float s = 0.0f;
            for (int r = 0; r < WIM_MAX_ROWS; r++) if (ax->rows[r].present) {
                float w = (r == WIM_ROW_BP) ? 3.0f : 1.0f, d = ax->rows[r].load_kg - mean; s += w * d * d; }
            type_a = sqrtf(s / wsum / (float)(nvals - 1));
        } else type_a = 0.05f * mean;
        for (int r = 0; r < WIM_MAX_ROWS; r++) if (ax->rows[r].present) type_b2 += cfg->cal[r].type_b_rel_u * cfg->cal[r].type_b_rel_u;
        float type_b = sqrtf(type_b2 / (float)nvals) * mean;
        ax->load_kg = mean;
        ax->u_kg = 2.0f * sqrtf(type_a * type_a + type_b * type_b);
    }

    /* --- grouping */
    uint8_t group = 1;
    for (int i = 0; i < axle_count; i++) {
        out->axles[i].group_no = group;
        if (out->axles[i].spacing_next_m >= WIM_GROUP_GAP_M) group++;
    }
    out->n_groups = group;

    /* --- GVM */
    float gvm = 0.0f, u2 = 0.0f;
    for (int i = 0; i < axle_count; i++) { gvm += out->axles[i].load_kg; float u1 = out->axles[i].u_kg * 0.5f; u2 += u1 * u1; }
    out->gvm_kg = gvm; out->gvm_u_kg = 2.0f * sqrtf(u2);
    if (n_good < 2) out->quality_flags |= WIM_QF_INSUFFICIENT_ROWS;
    if (gvm > 0.0f && out->gvm_u_kg / gvm > 0.10f) out->quality_flags |= WIM_QF_HIGH_UNCERTAINTY;
}

/**
 * @file test_wim_dsp.c
 * @brief Host unit test for the portable DSP and frame codec (no HAL, no RTOS). Build with any C99/C11 compiler:
 *
 *   gcc  -std=c11 -O2 -DHOST_TEST -I../App -o test_wim_dsp test_wim_dsp.c ../App/wim_dsp.c ../App/frames.c -lm
 *   cl   /std:c11 /O2 /DHOST_TEST /I..\App test_wim_dsp.c ..\App\wim_dsp.c ..\App\frames.c
 *   ./test_wim_dsp     -> prints PASS/FAIL per check, exit code = number of failures
 *
 * Synthesises the same half-sine pulses as kifaru_wim_dsp.signal_gen for a 4-axle 1+1+2 truck at 20 m/s and checks:
 *   1. biquad cascade DC gain = 1, -3 dB at 1 kHz (within 0.2 dB), half-sine integral preserved (< 0.1 %)
 *   2. median of even/odd arrays
 *   3. streaming pulse detector finds 4 pulses per row, merges a split pulse, flags saturation
 *   4. integral-method load within 1 % of the synthetic amplitude (no noise); wim_fuse_pass speed within 1 %,
 *      spacings within 2 cm, grouping "1+1+2", GVM within 2 %, flags == 0
 *   5. dead row -> health FAULT and WIM_QF_SENSOR_FAULT, axle count still 4
 *   6. frame codec round-trips AXLE_EVENT / PASS_SUMMARY / HEALTH / ENV; CRC-32 of "123456789" == 0xCBF43926;
 *      CRC-16/CCITT-FALSE of "123456789" == 0x29B1; CRC-16/MODBUS of "123456789" == 0x4B37; UDP unwrap rejects a
 *      corrupted byte.
 */
#define HOST_TEST 1
#include "../App/wim_dsp.h"
#include "../App/frames.h"
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <stdlib.h>

static int fails = 0;
#define CHECK(cond, ...) do { if (cond) printf("PASS  " __VA_ARGS__); else { fails++; printf("FAIL  " __VA_ARGS__); } printf("\n"); } while (0)

/* ------------------------------------------------------------------ synthetic pass (mirror of signal_gen.generate_pass) */
#define FS 8000.0f
#define MAXN 60000
static float sig[WIM_MAX_ROWS][MAXN];
static int   nsamp;
static const float ROW_POS[WIM_MAX_ROWS] = { 4.0f, 7.0f, 16.0f, 10.0f };   /* P1 P2 P3 BP */

static void synth(const float *loads, const float *spacings, int naxles, float v, float noise_rms, bool dead_row2, bool split_first)
{
    float offs[WIM_MAX_AXLES]; offs[0] = 0; for (int i = 1; i < naxles; i++) offs[i] = offs[i - 1] + spacings[i - 1];
    float lane_len = 19.0f + 2.0f, total = lane_len + offs[naxles - 1];
    float dur = total / v + 0.6f; nsamp = (int)(dur * FS); if (nsamp > MAXN) nsamp = MAXN;
    float t0 = 0.3f;
    srand(1);
    for (int r = 0; r < WIM_MAX_ROWS; r++) {
        bool piezo = (r != WIM_ROW_BP);
        float contact = (piezo ? (WIM_TYRE_CONTACT_LEN_M + WIM_STRIP_WIDTH_M) : (WIM_PLATE_LEN_M + WIM_TYRE_CONTACT_LEN_M)) / v;
        for (int n = 0; n < nsamp; n++) {
            float t = n / FS, y = 0;
            for (int i = 0; i < naxles; i++) {
                float tc = t0 + (ROW_POS[r] + offs[i]) / v;
                float x = (t - tc) / contact + 0.5f;
                if (x >= 0 && x <= 1) {
                    float a = loads[i] * sinf(3.14159265f * x);
                    if (split_first && r == 0 && i == 0 && x > 0.45f && x < 0.55f) a *= 0.05f;  /* notch below 0.5*threshold: forces a merge */
                    y += a;
                }
            }
            /* gaussian-ish noise via sum of uniforms */
            float u = 0; for (int k = 0; k < 12; k++) u += (float)rand() / RAND_MAX; u -= 6.0f;
            y += noise_rms * u;
            if (dead_row2 && r == WIM_ROW_P2) y = 5.0f * u;
            sig[r][n] = y;
        }
    }
}

/* run the streaming pipeline the way detect_task does */
static void run_pipeline(const wim_pass_cfg_t *cfg, wim_pass_pulses_t *pp, float sat_kg)
{
    memset(pp, 0, sizeof *pp);
    static float scratch[WIM_PRE_N];
    for (int r = 0; r < WIM_MAX_ROWS; r++) {
        wim_lp4_t lp; wim_lp4_init(&lp);
        static float filt[MAXN];
        for (int n = 0; n < nsamp; n++) filt[n] = wim_lp4_step(&lp, sig[r][n]);
        memcpy(scratch, filt, sizeof scratch);
        float base = wim_median(scratch, WIM_PRE_N);
        double acc = 0; for (int i = 0; i < WIM_PRE_N; i++) { double d = filt[i] - base; acc += d * d; }
        pp->noise_rms[r] = (float)sqrt(acc / WIM_PRE_N);
        wim_pulse_det_t det; wim_pulse_det_init(&det, WIM_THRESHOLD_KG, WIM_MIN_GAP_S, FS, sat_kg);
        for (int n = 0; n < nsamp; n++) {
            float x = wim_apply_cal(&cfg->cal[r], filt[n] - base, 30.0f);
            float ax = fabsf(x); if (ax > pp->peak_abs[r]) pp->peak_abs[r] = ax;
            wim_pulse_t p;
            if (wim_pulse_det_step(&det, (uint32_t)n, x, &p) && pp->n[r] < WIM_MAX_AXLES) { pp->p[r][pp->n[r]++] = p; if (p.saturated) pp->saturated[r] = true; }
        }
        wim_pulse_t p; if (wim_pulse_det_flush(&det, &p) && pp->n[r] < WIM_MAX_AXLES) pp->p[r][pp->n[r]++] = p;
    }
}

static wim_pass_cfg_t default_cfg(void)
{
    wim_pass_cfg_t c; memset(&c, 0, sizeof c);
    for (int r = 0; r < WIM_MAX_ROWS; r++) { c.row_pos_m[r] = ROW_POS[r]; c.cal[r].gain = 1; c.cal[r].reference_temp_c = 25; c.cal[r].type_b_rel_u = 0.02f; }
    c.fs = FS; c.rf_tau_s = 0.0f;   /* synthetic data has no droop */
    return c;
}

int main(void)
{
    /* ---- 1. filter */
    {
        wim_lp4_t f; wim_lp4_init(&f);
        float y = 0; for (int i = 0; i < 4000; i++) y = wim_lp4_step(&f, 1.0f);
        CHECK(fabsf(y - 1.0f) < 1e-4f, "lp4 DC gain = %.6f", y);
        /* -3 dB at 1 kHz: steady-state amplitude of a 1 kHz sine */
        wim_lp4_reset(&f); float mx = 0;
        for (int i = 0; i < 8000; i++) { float o = wim_lp4_step(&f, sinf(2 * 3.14159265f * 1000.0f * i / FS)); if (i > 4000 && fabsf(o) > mx) mx = fabsf(o); }
        float db = 20 * log10f(mx);
        CHECK(fabsf(db + 3.01f) < 0.2f, "lp4 gain at 1 kHz = %.2f dB (expect -3.01)", db);
        wim_lp4_reset(&f); double in = 0, out = 0;
        for (int i = 0; i < 800; i++) { float t = i / FS, x = (t > 0.01f && t < 0.0125f) ? 10000.0f * sinf(3.14159265f * (t - 0.01f) / 0.0025f) : 0.0f; in += x; out += wim_lp4_step(&f, x); }
        CHECK(fabs(in - out) / in < 1e-3, "lp4 preserves half-sine integral: in %.1f out %.1f", in, out);
    }
    /* ---- 2. median */
    {
        float a[] = { 5, 1, 4, 2, 3 }; float b[] = { 7, 1, 4, 2, 3, 9 };
        CHECK(wim_median(a, 5) == 3.0f, "median odd = %.1f", wim_median(a, 5));
        CHECK(wim_median(b, 6) == 3.5f, "median even = %.1f", wim_median(b, 6));
    }
    /* ---- 3/4. full pass: 1+1+2 truck at 20 m/s */
    const float loads[4] = { 6500, 9000, 8500, 8500 }, spac[3] = { 3.6f, 5.8f, 1.35f };
    {
        synth(loads, spac, 4, 20.0f, 20.0f, false, true);
        wim_pass_cfg_t cfg = default_cfg(); wim_pass_pulses_t pp; run_pipeline(&cfg, &pp, 0.0f);
        CHECK(pp.n[0] == 4 && pp.n[1] == 4 && pp.n[2] == 4 && pp.n[3] == 4, "pulse counts P1 %d P2 %d P3 %d BP %d (expect 4, incl. merged notch)", pp.n[0], pp.n[1], pp.n[2], pp.n[3]);
        float L = wim_pulse_load_kg(pp.p[1][1].integral, 20.0f, WIM_TYRE_CONTACT_LEN_M + WIM_STRIP_WIDTH_M, 0.0f);
        CHECK(fabsf(L - 9000.0f) / 9000.0f < 0.015f, "integral-method load axle 2 on P2 = %.0f kg (truth 9000)", L);
        wim_pass_result_t res; wim_fuse_pass(&cfg, &pp, &res);
        CHECK(res.axle_count == 4, "axle_count = %d", res.axle_count);
        CHECK(fabsf(res.speed_mps - 20.0f) / 20.0f < 0.01f, "speed = %.3f m/s (truth 20)", res.speed_mps);
        CHECK(fabsf(res.axles[0].spacing_next_m - 3.6f) < 0.02f && fabsf(res.axles[2].spacing_next_m - 1.35f) < 0.02f, "spacings %.3f %.3f %.3f", res.axles[0].spacing_next_m, res.axles[1].spacing_next_m, res.axles[2].spacing_next_m);
        CHECK(res.axles[0].group_no == 1 && res.axles[1].group_no == 2 && res.axles[2].group_no == 3 && res.axles[3].group_no == 3 && res.n_groups == 3, "grouping 1+1+2 (groups %d %d %d %d)", res.axles[0].group_no, res.axles[1].group_no, res.axles[2].group_no, res.axles[3].group_no);
        float gvm_t = 32500.0f;
        CHECK(fabsf(res.gvm_kg - gvm_t) / gvm_t < 0.02f, "GVM = %.0f kg +/- %.0f (truth %.0f)", res.gvm_kg, res.gvm_u_kg, gvm_t);
        CHECK(res.quality_flags == 0, "quality_flags = 0x%04X", res.quality_flags);
        CHECK(res.gvm_u_kg > 0 && res.gvm_u_kg < 0.1f * gvm_t, "GVM U(k=2) = %.0f kg is positive and < 10 %%", res.gvm_u_kg);
    }
    /* ---- saturation flag */
    {
        synth(loads, spac, 4, 20.0f, 20.0f, false, false);
        wim_pass_cfg_t cfg = default_cfg(); wim_pass_pulses_t pp; run_pipeline(&cfg, &pp, 8000.0f);
        CHECK(pp.saturated[1], "saturation detected on P2 with sat level 8000 kg (peak 9000)");
    }
    /* ---- 5. dead row */
    {
        synth(loads, spac, 4, 18.0f, 20.0f, true, false);
        wim_pass_cfg_t cfg = default_cfg(); wim_pass_pulses_t pp; run_pipeline(&cfg, &pp, 0.0f);
        wim_pass_result_t res; wim_fuse_pass(&cfg, &pp, &res);
        CHECK(res.health[WIM_ROW_P2] == WIM_HEALTH_FAULT, "dead P2 -> health FAULT (%d)", res.health[WIM_ROW_P2]);
        CHECK((res.quality_flags & WIM_QF_SENSOR_FAULT) != 0, "sensor_fault flag set (0x%04X)", res.quality_flags);
        CHECK(res.axle_count == 4 && fabsf(res.speed_mps - 18.0f) / 18.0f < 0.01f, "still 4 axles, speed %.2f from P1/P3", res.speed_mps);
    }
    /* ---- 6. frames */
    {
        CHECK(frm_crc32((const uint8_t *)"123456789", 9) == 0xCBF43926u, "CRC-32 check value 0x%08X", frm_crc32((const uint8_t *)"123456789", 9));
        CHECK(frm_crc16_ccitt((const uint8_t *)"123456789", 9, 0xFFFF) == 0x29B1u, "CRC-16/CCITT-FALSE 0x%04X", frm_crc16_ccitt((const uint8_t *)"123456789", 9, 0xFFFF));
        CHECK(frm_crc16_modbus((const uint8_t *)"123456789", 9) == 0x4B37u, "CRC-16/MODBUS 0x%04X", frm_crc16_modbus((const uint8_t *)"123456789", 9));

        frm_axle_event_t a = { .pass_id = 1234, .axle_index = 2, .rows_valid = 0x0F, .flags = 1, .t_row_us = { 1ull << 40, 2, 3, 4 }, .load_row_kg = { 6500, 6400, 6600, 6450 }, .speed_cmps = 2000, .spacing_prev_mm = 1350 };
        uint8_t buf[FRM_MAX_PAYLOAD]; size_t n = frm_encode_axle_event(&a, buf, sizeof buf);
        frm_axle_event_t b; bool ok = frm_decode_axle_event(buf, n, &b);
        CHECK(n == 52 && ok && b.pass_id == 1234 && b.t_row_us[0] == (1ull << 40) && b.load_row_kg[3] == 6450 && b.spacing_prev_mm == 1350, "AXLE_EVENT round trip (%u bytes)", (unsigned)n);

        frm_pass_summary_t s; memset(&s, 0, sizeof s); s.pass_id = 7; s.t_first_axle_us = 1700000000000000ull; s.axle_count = 2; s.n_groups = 2; s.quality_flags = 0x42; s.speed_cmps = 1850; s.speed_u_cmps = 12; s.gvm_kg = 15500; s.gvm_u_kg = 700; s.pavement_temp_c_x10 = 345; s.sensor_health[3] = 1; s.sensor_health[7] = 255; s.n_axles_included = 2;
        s.axles[0].load_kg = 6500; s.axles[0].u_kg = 400; s.axles[0].spacing_next_mm = 4200; s.axles[0].group_no = 1; s.axles[1].load_kg = 9000; s.axles[1].u_kg = 500; s.axles[1].spacing_next_mm = 0xFFFF; s.axles[1].group_no = 2;
        n = frm_encode_pass_summary(&s, buf, sizeof buf, true); frm_pass_summary_t s2; ok = frm_decode_pass_summary(buf, n, &s2);
        CHECK(n == 38 + 16 && ok && s2.n_axles_included == 2 && s2.axles[1].spacing_next_mm == 0xFFFF && s2.gvm_kg == 15500 && s2.pavement_temp_c_x10 == 345 && s2.sensor_health[7] == 255, "PASS_SUMMARY round trip (%u bytes)", (unsigned)n);
        n = frm_encode_pass_summary(&s, buf, sizeof buf, false); CHECK(n == 38, "PASS_SUMMARY CAN-FD fixed part = %u bytes", (unsigned)n);

        frm_env_t e = { .t_us = 99, .pavement_c_x100 = -150, .ambient_c_x100 = 3120, .rh_x100 = 7800, .cabinet_c_x100 = 4210, .bus_mv = 24100, .batt_mv = 26400, .digital = 0x05 };
        n = frm_encode_env(&e, buf, sizeof buf); frm_env_t e2; ok = frm_decode_env(buf, n, &e2);
        CHECK(n == 22 && ok && e2.pavement_c_x100 == -150 && e2.digital == 5 && e2.batt_mv == 26400, "ENV round trip, negative temperature preserved");

        uint8_t frame[FRM_MAX_FRAME]; size_t fl = frm_udp_wrap(FRM_ENV, 77, 123456, buf, n, frame, sizeof frame);
        uint8_t type; uint16_t seq; const uint8_t *pl; size_t plen;
        CHECK(fl == 12 + 22 + 4 && frm_udp_unwrap(frame, fl, &type, &seq, &pl, &plen) && type == FRM_ENV && seq == 77 && plen == 22, "UDP wrap/unwrap (%u bytes)", (unsigned)fl);
        frame[15] ^= 0x01;
        CHECK(!frm_udp_unwrap(frame, fl, &type, &seq, &pl, &plen), "UDP unwrap rejects corrupted payload (CRC)");
    }
    printf("\n%d failure(s)\n", fails);
    return fails;
}

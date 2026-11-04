/**
 * @file wim_dsp.h
 * @brief Portable (host-testable) WIM signal-processing core.
 *
 * C port of packages/wim_dsp/kifaru_wim_dsp/pipeline.py. Differences from the Python reference, all deliberate:
 *   - The low-pass is applied causally (one pass of two biquads, transposed direct form II) instead of
 *     scipy.sosfiltfilt (zero-phase, two passes). Group delay (~0.5 ms at DC) is identical on all channels, so
 *     peak-time differences (speed) and pulse integrals (load) are unaffected. The host test checks that the
 *     causal filter preserves the half-sine integral to < 0.1 %.
 *   - Baseline is the median of the 0.2 s pre-trigger ring buffer, taken when a pass starts (same statistic as
 *     the Python `remove_baseline`), then held for the whole pass.
 *   - Pulse detection is streaming: the detector emits a pulse `min_gap` samples after it ended so that a late
 *     re-trigger can be merged exactly like the Python `detect_pulses`.
 *   - All arithmetic is single-precision float except pulse integrals (double accumulators), which is ample
 *     for 18-bit data. No dynamic memory. No libm beyond sqrtf/fabsf/sinf (sinf only in the host test).
 */
#ifndef WIM_DSP_H
#define WIM_DSP_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ------------------------------------------------------------------ constants (mirror signal_gen.py) */
#define WIM_FS_HZ                 8000.0f
#define WIM_STRIP_WIDTH_M         0.05f
#define WIM_TYRE_CONTACT_LEN_M    0.25f
#define WIM_PLATE_LEN_M           0.50f
#define WIM_GROUP_GAP_M           2.0f      /* axles closer than this belong to one group */
#define WIM_MIN_GAP_S             0.03f     /* pulses closer than this are the same tyre */
#define WIM_THRESHOLD_KG          800.0f
#define WIM_PRE_TRIGGER_S         0.2f
#define WIM_MAX_AXLES             12
#define WIM_MAX_ROWS              4         /* P1, P2, P3, BP */
#define WIM_PRE_N                 ((int)(WIM_PRE_TRIGGER_S * WIM_FS_HZ))  /* 1600 */

enum wim_row { WIM_ROW_P1 = 0, WIM_ROW_P2 = 1, WIM_ROW_P3 = 2, WIM_ROW_BP = 3 };

/* quality_flags bitmask: see docs/03-hardware/communications.md §1.9 */
#define WIM_QF_SENSOR_FAULT        (1u << 0)
#define WIM_QF_SENSOR_DEGRADED     (1u << 1)
#define WIM_QF_SPEED_UNAVAILABLE   (1u << 2)
#define WIM_QF_SPEED_OUT_OF_RANGE  (1u << 3)
#define WIM_QF_INSUFFICIENT_ROWS   (1u << 4)
#define WIM_QF_AXLE_LOAD_MISSING   (1u << 5)
#define WIM_QF_HIGH_UNCERTAINTY    (1u << 6)
#define WIM_QF_NO_AXLES            (1u << 7)
#define WIM_QF_SATURATION          (1u << 8)
#define WIM_QF_LOOP_INCONSISTENT   (1u << 9)
#define WIM_QF_SPEED_INCONSISTENT  (1u << 10)
#define WIM_QF_PAVEMENT_HOT        (1u << 11)

enum wim_health { WIM_HEALTH_OK = 0, WIM_HEALTH_DEGRADED = 1, WIM_HEALTH_FAULT = 2, WIM_HEALTH_NA = 255 };

/* ------------------------------------------------------------------ IIR low-pass */
typedef struct {
    float b0, b1, b2, a1, a2;   /* a0 normalised to 1 */
    float s1, s2;               /* transposed DF-II state */
} wim_biquad_t;

typedef struct {
    wim_biquad_t sec[2];
} wim_lp4_t;

/** 4th-order Butterworth, fc = 1 kHz at fs = 8 kHz (coefficients from scipy.signal.butter(4, 0.25, output='sos')). */
void  wim_lp4_init(wim_lp4_t *f);
float wim_lp4_step(wim_lp4_t *f, float x);
void  wim_lp4_reset(wim_lp4_t *f);

/* ------------------------------------------------------------------ baseline */
/** Median of n floats (quickselect on a scratch copy the caller provides, length n). */
float wim_median(float *scratch, int n);

/* ------------------------------------------------------------------ calibration (mirror ChannelCalibration) */
typedef struct {
    float gain;
    float offset;
    float temp_coeff_per_c;
    float reference_temp_c;
    float type_b_rel_u;     /* k = 1 relative uncertainty from the certificate (uncertainty_pct / 200) */
} wim_cal_t;

static inline float wim_apply_cal(const wim_cal_t *c, float x_kg, float pavement_temp_c)
{
    float temp_factor = 1.0f + c->temp_coeff_per_c * (pavement_temp_c - c->reference_temp_c);
    return (x_kg - c->offset) * c->gain / temp_factor;
}

/* ------------------------------------------------------------------ streaming pulse detector */
typedef struct {
    uint32_t start;         /* sample index of first sample above threshold */
    uint32_t peak;          /* sample index of the maximum */
    uint32_t end;           /* first sample index at/below 0.5*threshold after the pulse */
    float    peak_val;
    double   integral;      /* sum(x) * dt over [start, end) — rectangle rule, dt = 1/fs */
    bool     saturated;
} wim_pulse_t;

typedef struct {
    float    threshold;
    uint32_t min_gap;       /* samples */
    float    dt;
    float    sat_level;     /* |x| above this counts as saturation (kg-eq of ADC full scale) */
    bool     in_pulse;
    bool     has_pending;
    wim_pulse_t cur;
    wim_pulse_t pending;
    int      sat_run;
} wim_pulse_det_t;

void wim_pulse_det_init(wim_pulse_det_t *d, float threshold_kg, float min_gap_s, float fs, float sat_level_kg);
/** Feed one calibrated sample. Returns true and fills *out when a pulse is finalised (min_gap after its end). */
bool wim_pulse_det_step(wim_pulse_det_t *d, uint32_t n, float x, wim_pulse_t *out);
/** Flush a pending pulse at end of pass (returns true if one was emitted). */
bool wim_pulse_det_flush(wim_pulse_det_t *d, wim_pulse_t *out);

/* ------------------------------------------------------------------ load from pulse (integral method) */
/**
 * Half-sine of amplitude A and duration T has integral 2AT/pi  =>  A = integral*pi/(2T), T = contact_len / v.
 * rf_tau_s > 0 applies the charge-amp droop correction (1 + T/(2 tau)); pass 0 for the bending plate.
 */
float wim_pulse_load_kg(double integral_kg_s, float speed_mps, float contact_len_m, float rf_tau_s);

/* ------------------------------------------------------------------ pass-level fusion */
typedef struct {
    bool   present;         /* this row saw this axle */
    uint32_t peak_n;        /* sample index of peak */
    float  load_kg;
} wim_axle_row_t;

typedef struct {
    float load_kg;
    float u_kg;             /* expanded, k = 2 */
    float spacing_next_m;   /* < 0 => none */
    uint8_t group_no;
    wim_axle_row_t rows[WIM_MAX_ROWS];
} wim_axle_t;

typedef struct {
    uint8_t  axle_count;
    uint8_t  n_groups;
    uint16_t quality_flags;
    float    speed_mps, speed_u_mps;
    float    gvm_kg, gvm_u_kg;
    uint8_t  health[WIM_MAX_ROWS];
    wim_axle_t axles[WIM_MAX_AXLES];
} wim_pass_result_t;

typedef struct {
    float    row_pos_m[WIM_MAX_ROWS];                  /* P1, P2, P3, BP positions */
    wim_cal_t cal[WIM_MAX_ROWS];
    float    fs;
    float    rf_tau_s;                                 /* charge-amp Rf*Cf for piezo rows */
} wim_pass_cfg_t;

typedef struct {
    int         n[WIM_MAX_ROWS];
    wim_pulse_t p[WIM_MAX_ROWS][WIM_MAX_AXLES];
    float       noise_rms[WIM_MAX_ROWS];               /* pre-trigger rms, kg-eq, for health */
    float       peak_abs[WIM_MAX_ROWS];                /* max |x| over pass */
    bool        saturated[WIM_MAX_ROWS];
} wim_pass_pulses_t;

/** Fuse per-row pulses into axle loads/speed/grouping/flags exactly like process_pass(). */
void wim_fuse_pass(const wim_pass_cfg_t *cfg, const wim_pass_pulses_t *pp, wim_pass_result_t *out);

/** Row health, mirrors channel_health(). expected_axles < 0 => unknown. */
uint8_t wim_row_health(float noise_rms_kg, float peak_abs_kg, bool saturated, int pulses, int expected_axles);

#ifdef __cplusplus
}
#endif
#endif /* WIM_DSP_H */

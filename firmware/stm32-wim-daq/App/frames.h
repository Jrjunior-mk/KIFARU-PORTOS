/**
 * @file frames.h
 * @brief Wire payloads shared by CAN-FD and UDP — byte-exact with docs/03-hardware/communications.md §1–2 and with
 *        edge/gateway/kifaru_gateway/daq_client.py. Little-endian, packed by hand (no struct packing pragmas) so the
 *        same code is correct on Cortex-M7 and on any host.
 */
#ifndef FRAMES_H
#define FRAMES_H

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

#define FRM_MAGIC            0x4B57u
#define FRM_VERSION          1u
#define FRM_HDR_LEN          12u
#define FRM_CRC_LEN          4u
#define FRM_MAX_PAYLOAD      136u
#define FRM_MAX_FRAME        (FRM_HDR_LEN + FRM_MAX_PAYLOAD + FRM_CRC_LEN)

enum frm_type {
    FRM_AXLE_EVENT   = 0x01,
    FRM_PASS_SUMMARY = 0x02,
    FRM_HEALTH       = 0x03,
    FRM_LOOP_EVENT   = 0x04,
    FRM_IR_EVENT     = 0x05,
    FRM_ENV          = 0x06,
    FRM_TIME_SYNC    = 0x07,
    FRM_HEARTBEAT    = 0x08,
};

#define FRM_AXLE_EVENT_LEN    52u
#define FRM_PASS_FIXED_LEN    38u
#define FRM_PASS_AXLE_LEN     8u
#define FRM_HEALTH_HDR_LEN    10u
#define FRM_HEALTH_CH_LEN     6u
#define FRM_LOOP_EVENT_LEN    12u
#define FRM_ENV_LEN           22u
#define FRM_TIME_SYNC_LEN     12u
#define FRM_HEARTBEAT_LEN     17u

/* CAN identifiers: ID = base + 0x20*lane + type */
#define CAN_BASE_DAQ_TO_GW    0x100u
#define CAN_BASE_GW_TO_DAQ    0x180u
#define CAN_BASE_AUX          0x200u

typedef struct {
    uint32_t pass_id;
    uint8_t  axle_index;
    uint8_t  rows_valid;      /* bit0 P1 bit1 P2 bit2 P3 bit3 BP */
    uint8_t  flags;           /* bit0 saturation bit1 lr_asym bit2 merged */
    uint64_t t_row_us[4];     /* P1, P2, P3, BP peak times; 0 = not detected */
    uint16_t load_row_kg[4];
    uint16_t speed_cmps;
    uint16_t spacing_prev_mm;
} frm_axle_event_t;

typedef struct {
    uint16_t load_kg, u_kg, spacing_next_mm; /* 0xFFFF = none */
    uint8_t  group_no;
} frm_pass_axle_t;

typedef struct {
    uint32_t pass_id;
    uint64_t t_first_axle_us;
    uint8_t  axle_count, n_groups;
    uint16_t quality_flags;
    uint16_t speed_cmps, speed_u_cmps;
    uint32_t gvm_kg, gvm_u_kg;
    int16_t  pavement_temp_c_x10;
    uint8_t  sensor_health[8];  /* P1 P2 P3 BP L1 L2 L3 IR */
    uint8_t  n_axles_included;  /* axle records appended (UDP) — 0 on CAN-FD */
    frm_pass_axle_t axles[12];
} frm_pass_summary_t;

typedef struct {
    uint16_t noise_rms_kg_x10;
    int16_t  baseline_kg;
    uint8_t  status;            /* 0 ok 1 degraded 2 fault */
    uint8_t  flags;             /* bit0 dead bit1 saturated bit2 noisy bit3 drift bit4 hum50 */
} frm_health_ch_t;

typedef struct {
    uint64_t t_us;
    uint8_t  first_channel, n_ch;
    frm_health_ch_t ch[16];
} frm_health_t;

typedef struct { uint64_t t_us; uint8_t id, state; } frm_loop_event_t;   /* also IR_EVENT */

typedef struct {
    uint64_t t_us;
    int16_t  pavement_c_x100, ambient_c_x100;
    uint16_t rh_x100;
    int16_t  cabinet_c_x100;
    uint16_t bus_mv, batt_mv;
    uint8_t  digital;           /* bit0 door bit1 ac_fail bit2 batt_low bit3 spd_fault bit4 fan_on */
} frm_env_t;

typedef struct { uint64_t utc_us_at_pps; uint32_t pps_count; } frm_time_sync_t;
typedef struct { uint64_t t_us; uint32_t uptime_s, fw_version; uint8_t state; } frm_heartbeat_t;

/* ---- little-endian helpers */
void     frm_put_u16(uint8_t *p, uint16_t v);
void     frm_put_u32(uint8_t *p, uint32_t v);
void     frm_put_u64(uint8_t *p, uint64_t v);
uint16_t frm_get_u16(const uint8_t *p);
uint32_t frm_get_u32(const uint8_t *p);
uint64_t frm_get_u64(const uint8_t *p);

/* ---- CRCs */
uint32_t frm_crc32(const uint8_t *data, size_t len);                  /* IEEE 802.3 (zlib.crc32 compatible) */
uint16_t frm_crc16_ccitt(const uint8_t *data, size_t len, uint16_t init); /* poly 0x1021, used by ADS131M08 */
uint16_t frm_crc16_modbus(const uint8_t *data, size_t len);           /* poly 0xA001 reflected, init 0xFFFF */

/* ---- payload encoders: return bytes written (0 on error) */
size_t frm_encode_axle_event(const frm_axle_event_t *a, uint8_t *out, size_t cap);
size_t frm_encode_pass_summary(const frm_pass_summary_t *s, uint8_t *out, size_t cap, bool include_axles);
size_t frm_encode_health(const frm_health_t *h, uint8_t *out, size_t cap);
size_t frm_encode_loop_event(const frm_loop_event_t *e, uint8_t *out, size_t cap);
size_t frm_encode_env(const frm_env_t *e, uint8_t *out, size_t cap);
size_t frm_encode_heartbeat(const frm_heartbeat_t *h, uint8_t *out, size_t cap);

/* ---- payload decoders (used by host test and by the DAQ for TIME_SYNC / ENV) */
bool frm_decode_axle_event(const uint8_t *in, size_t len, frm_axle_event_t *a);
bool frm_decode_pass_summary(const uint8_t *in, size_t len, frm_pass_summary_t *s);
bool frm_decode_time_sync(const uint8_t *in, size_t len, frm_time_sync_t *t);
bool frm_decode_env(const uint8_t *in, size_t len, frm_env_t *e);

/* ---- UDP framing */
size_t frm_udp_wrap(uint8_t type, uint16_t seq, uint32_t t_tx_us_low, const uint8_t *payload, size_t plen, uint8_t *out, size_t cap);
/** Validates magic/version/length/CRC; on success sets *type, *seq, *payload (pointer into buf), *plen. */
bool   frm_udp_unwrap(const uint8_t *buf, size_t len, uint8_t *type, uint16_t *seq, const uint8_t **payload, size_t *plen);

#ifdef __cplusplus
}
#endif
#endif /* FRAMES_H */

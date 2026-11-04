/**
 * @file frames.c
 * @brief Byte-exact payload codec, CRCs and UDP framing (see frames.h).
 */
#include "frames.h"
#include <string.h>

/* ------------------------------------------------------------------ LE helpers */
void frm_put_u16(uint8_t *p, uint16_t v) { p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8); }
void frm_put_u32(uint8_t *p, uint32_t v) { for (int i = 0; i < 4; i++) p[i] = (uint8_t)(v >> (8 * i)); }
void frm_put_u64(uint8_t *p, uint64_t v) { for (int i = 0; i < 8; i++) p[i] = (uint8_t)(v >> (8 * i)); }
uint16_t frm_get_u16(const uint8_t *p) { return (uint16_t)(p[0] | ((uint16_t)p[1] << 8)); }
uint32_t frm_get_u32(const uint8_t *p) { uint32_t v = 0; for (int i = 3; i >= 0; i--) v = (v << 8) | p[i]; return v; }
uint64_t frm_get_u64(const uint8_t *p) { uint64_t v = 0; for (int i = 7; i >= 0; i--) v = (v << 8) | p[i]; return v; }

/* ------------------------------------------------------------------ CRCs */
uint32_t frm_crc32(const uint8_t *data, size_t len)
{
    uint32_t crc = 0xFFFFFFFFu;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int k = 0; k < 8; k++) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1u)));
    }
    return crc ^ 0xFFFFFFFFu;
}

uint16_t frm_crc16_ccitt(const uint8_t *data, size_t len, uint16_t init)
{
    uint16_t crc = init;
    for (size_t i = 0; i < len; i++) {
        crc ^= (uint16_t)data[i] << 8;
        for (int k = 0; k < 8; k++) crc = (crc & 0x8000u) ? (uint16_t)((crc << 1) ^ 0x1021u) : (uint16_t)(crc << 1);
    }
    return crc;
}

uint16_t frm_crc16_modbus(const uint8_t *data, size_t len)
{
    uint16_t crc = 0xFFFFu;
    for (size_t i = 0; i < len; i++) {
        crc ^= data[i];
        for (int k = 0; k < 8; k++) crc = (crc & 1u) ? (uint16_t)((crc >> 1) ^ 0xA001u) : (uint16_t)(crc >> 1);
    }
    return crc;
}

/* ------------------------------------------------------------------ encoders */
size_t frm_encode_axle_event(const frm_axle_event_t *a, uint8_t *o, size_t cap)
{
    if (cap < FRM_AXLE_EVENT_LEN) return 0;
    frm_put_u32(o + 0, a->pass_id);
    o[4] = a->axle_index; o[5] = a->rows_valid; o[6] = a->flags; o[7] = 0;
    for (int r = 0; r < 4; r++) frm_put_u64(o + 8 + 8 * r, a->t_row_us[r]);
    for (int r = 0; r < 4; r++) frm_put_u16(o + 40 + 2 * r, a->load_row_kg[r]);
    frm_put_u16(o + 48, a->speed_cmps);
    frm_put_u16(o + 50, a->spacing_prev_mm);
    return FRM_AXLE_EVENT_LEN;
}

size_t frm_encode_pass_summary(const frm_pass_summary_t *s, uint8_t *o, size_t cap, bool include_axles)
{
    uint8_t n = include_axles ? s->n_axles_included : 0;
    if (n > 12) n = 12;
    size_t len = FRM_PASS_FIXED_LEN + (size_t)n * FRM_PASS_AXLE_LEN;
    if (cap < len) return 0;
    frm_put_u32(o + 0, s->pass_id);
    frm_put_u64(o + 4, s->t_first_axle_us);
    o[12] = s->axle_count; o[13] = s->n_groups;
    frm_put_u16(o + 14, s->quality_flags);
    frm_put_u16(o + 16, s->speed_cmps);
    frm_put_u16(o + 18, s->speed_u_cmps);
    frm_put_u32(o + 20, s->gvm_kg);
    frm_put_u32(o + 24, s->gvm_u_kg);
    frm_put_u16(o + 28, (uint16_t)s->pavement_temp_c_x10);
    memcpy(o + 30, s->sensor_health, 8);
    for (uint8_t i = 0; i < n; i++) {
        uint8_t *p = o + FRM_PASS_FIXED_LEN + i * FRM_PASS_AXLE_LEN;
        frm_put_u16(p + 0, s->axles[i].load_kg);
        frm_put_u16(p + 2, s->axles[i].u_kg);
        frm_put_u16(p + 4, s->axles[i].spacing_next_mm);
        p[6] = s->axles[i].group_no; p[7] = 0;
    }
    return len;
}

size_t frm_encode_health(const frm_health_t *h, uint8_t *o, size_t cap)
{
    uint8_t n = h->n_ch > 16 ? 16 : h->n_ch;
    size_t len = FRM_HEALTH_HDR_LEN + (size_t)n * FRM_HEALTH_CH_LEN;
    if (cap < len) return 0;
    frm_put_u64(o, h->t_us);
    o[8] = h->first_channel; o[9] = n;
    for (uint8_t i = 0; i < n; i++) {
        uint8_t *p = o + FRM_HEALTH_HDR_LEN + i * FRM_HEALTH_CH_LEN;
        frm_put_u16(p + 0, h->ch[i].noise_rms_kg_x10);
        frm_put_u16(p + 2, (uint16_t)h->ch[i].baseline_kg);
        p[4] = h->ch[i].status; p[5] = h->ch[i].flags;
    }
    return len;
}

size_t frm_encode_loop_event(const frm_loop_event_t *e, uint8_t *o, size_t cap)
{
    if (cap < FRM_LOOP_EVENT_LEN) return 0;
    frm_put_u64(o, e->t_us); o[8] = e->id; o[9] = e->state; o[10] = 0; o[11] = 0;
    return FRM_LOOP_EVENT_LEN;
}

size_t frm_encode_env(const frm_env_t *e, uint8_t *o, size_t cap)
{
    if (cap < FRM_ENV_LEN) return 0;
    frm_put_u64(o, e->t_us);
    frm_put_u16(o + 8, (uint16_t)e->pavement_c_x100);
    frm_put_u16(o + 10, (uint16_t)e->ambient_c_x100);
    frm_put_u16(o + 12, e->rh_x100);
    frm_put_u16(o + 14, (uint16_t)e->cabinet_c_x100);
    frm_put_u16(o + 16, e->bus_mv);
    frm_put_u16(o + 18, e->batt_mv);
    o[20] = e->digital; o[21] = 0;
    return FRM_ENV_LEN;
}

size_t frm_encode_heartbeat(const frm_heartbeat_t *h, uint8_t *o, size_t cap)
{
    if (cap < FRM_HEARTBEAT_LEN) return 0;
    frm_put_u64(o, h->t_us); frm_put_u32(o + 8, h->uptime_s); frm_put_u32(o + 12, h->fw_version); o[16] = h->state;
    return FRM_HEARTBEAT_LEN;
}

/* ------------------------------------------------------------------ decoders */
bool frm_decode_axle_event(const uint8_t *i, size_t len, frm_axle_event_t *a)
{
    if (len < FRM_AXLE_EVENT_LEN) return false;
    a->pass_id = frm_get_u32(i); a->axle_index = i[4]; a->rows_valid = i[5]; a->flags = i[6];
    for (int r = 0; r < 4; r++) a->t_row_us[r] = frm_get_u64(i + 8 + 8 * r);
    for (int r = 0; r < 4; r++) a->load_row_kg[r] = frm_get_u16(i + 40 + 2 * r);
    a->speed_cmps = frm_get_u16(i + 48); a->spacing_prev_mm = frm_get_u16(i + 50);
    return true;
}

bool frm_decode_pass_summary(const uint8_t *i, size_t len, frm_pass_summary_t *s)
{
    if (len < FRM_PASS_FIXED_LEN) return false;
    memset(s, 0, sizeof(*s));
    s->pass_id = frm_get_u32(i); s->t_first_axle_us = frm_get_u64(i + 4);
    s->axle_count = i[12]; s->n_groups = i[13]; s->quality_flags = frm_get_u16(i + 14);
    s->speed_cmps = frm_get_u16(i + 16); s->speed_u_cmps = frm_get_u16(i + 18);
    s->gvm_kg = frm_get_u32(i + 20); s->gvm_u_kg = frm_get_u32(i + 24);
    s->pavement_temp_c_x10 = (int16_t)frm_get_u16(i + 28);
    memcpy(s->sensor_health, i + 30, 8);
    size_t n = (len - FRM_PASS_FIXED_LEN) / FRM_PASS_AXLE_LEN;
    if (n > 12) n = 12;
    s->n_axles_included = (uint8_t)n;
    for (size_t k = 0; k < n; k++) {
        const uint8_t *p = i + FRM_PASS_FIXED_LEN + k * FRM_PASS_AXLE_LEN;
        s->axles[k].load_kg = frm_get_u16(p); s->axles[k].u_kg = frm_get_u16(p + 2);
        s->axles[k].spacing_next_mm = frm_get_u16(p + 4); s->axles[k].group_no = p[6];
    }
    return true;
}

bool frm_decode_time_sync(const uint8_t *i, size_t len, frm_time_sync_t *t)
{
    if (len < FRM_TIME_SYNC_LEN) return false;
    t->utc_us_at_pps = frm_get_u64(i); t->pps_count = frm_get_u32(i + 8);
    return true;
}

bool frm_decode_env(const uint8_t *i, size_t len, frm_env_t *e)
{
    if (len < FRM_ENV_LEN) return false;
    e->t_us = frm_get_u64(i);
    e->pavement_c_x100 = (int16_t)frm_get_u16(i + 8); e->ambient_c_x100 = (int16_t)frm_get_u16(i + 10);
    e->rh_x100 = frm_get_u16(i + 12); e->cabinet_c_x100 = (int16_t)frm_get_u16(i + 14);
    e->bus_mv = frm_get_u16(i + 16); e->batt_mv = frm_get_u16(i + 18); e->digital = i[20];
    return true;
}

/* ------------------------------------------------------------------ UDP framing */
size_t frm_udp_wrap(uint8_t type, uint16_t seq, uint32_t t_tx_us_low, const uint8_t *payload, size_t plen, uint8_t *o, size_t cap)
{
    size_t len = FRM_HDR_LEN + plen + FRM_CRC_LEN;
    if (plen > FRM_MAX_PAYLOAD || cap < len) return 0;
    frm_put_u16(o, FRM_MAGIC); o[2] = FRM_VERSION; o[3] = type;
    frm_put_u16(o + 4, seq); frm_put_u16(o + 6, (uint16_t)plen); frm_put_u32(o + 8, t_tx_us_low);
    memcpy(o + FRM_HDR_LEN, payload, plen);
    frm_put_u32(o + FRM_HDR_LEN + plen, frm_crc32(o, FRM_HDR_LEN + plen));
    return len;
}

bool frm_udp_unwrap(const uint8_t *b, size_t len, uint8_t *type, uint16_t *seq, const uint8_t **payload, size_t *plen)
{
    if (len < FRM_HDR_LEN + FRM_CRC_LEN) return false;
    if (frm_get_u16(b) != FRM_MAGIC || b[2] != FRM_VERSION) return false;
    size_t n = frm_get_u16(b + 6);
    if (len != FRM_HDR_LEN + n + FRM_CRC_LEN) return false;
    if (frm_crc32(b, FRM_HDR_LEN + n) != frm_get_u32(b + FRM_HDR_LEN + n)) return false;
    *type = b[3]; *seq = frm_get_u16(b + 4); *payload = b + FRM_HDR_LEN; *plen = n;
    return true;
}

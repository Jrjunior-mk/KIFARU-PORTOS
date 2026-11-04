/**
 * @file comms_task.c
 * @brief Transmit every comms_msg_t on FDCAN1 (CAN-FD, BRS) and, when WITH_LWIP is defined, on UDP 5010; receive
 *        TIME_SYNC (CAN or UDP 5011) and ENV frames from the ESP32 (FDCAN2, classic CAN segment) and forward ENV.
 */
#include "tasks.h"
#include "timebase.h"
#include "stm32h7xx_hal.h"
#include <string.h>

extern FDCAN_HandleTypeDef hfdcan1, hfdcan2;   /* main.c */
#ifdef WITH_LWIP
#include "lwip/api.h"
static struct netconn *s_udp_tx, *s_udp_rx;
static ip_addr_t s_gw_addr;
#endif

static uint16_t s_udp_seq;
static uint8_t  s_env_buf[FRM_ENV_LEN]; static uint8_t s_env_mask;   /* reassembly of 3 classic frames */

/* ------------------------------------------------------------------ post from any context */
bool comms_post(uint8_t type, const uint8_t *payload, size_t len, bool from_isr)
{
    if (len == 0 || len > FRM_MAX_PAYLOAD) return false;
    comms_msg_t m; m.type = type; m.len = (uint8_t)len; memcpy(m.payload, payload, len);
    if (from_isr) { BaseType_t w = pdFALSE; BaseType_t ok = xQueueSendFromISR(q_comms, &m, &w); portYIELD_FROM_ISR(w); return ok == pdTRUE; }
    return xQueueSend(q_comms, &m, pdMS_TO_TICKS(10)) == pdTRUE;
}

/* ------------------------------------------------------------------ CAN-FD helpers */
static uint32_t dlc_for(size_t n, size_t *padded)
{
    static const struct { size_t len; uint32_t dlc; } tab[] = {
        {0, FDCAN_DLC_BYTES_0}, {1, FDCAN_DLC_BYTES_1}, {2, FDCAN_DLC_BYTES_2}, {3, FDCAN_DLC_BYTES_3}, {4, FDCAN_DLC_BYTES_4},
        {5, FDCAN_DLC_BYTES_5}, {6, FDCAN_DLC_BYTES_6}, {7, FDCAN_DLC_BYTES_7}, {8, FDCAN_DLC_BYTES_8}, {12, FDCAN_DLC_BYTES_12},
        {16, FDCAN_DLC_BYTES_16}, {20, FDCAN_DLC_BYTES_20}, {24, FDCAN_DLC_BYTES_24}, {32, FDCAN_DLC_BYTES_32}, {48, FDCAN_DLC_BYTES_48}, {64, FDCAN_DLC_BYTES_64} };
    for (size_t i = 0; i < sizeof tab / sizeof tab[0]; i++) if (n <= tab[i].len) { *padded = tab[i].len; return tab[i].dlc; }
    *padded = 64; return FDCAN_DLC_BYTES_64;
}

static bool can_send(uint32_t id, const uint8_t *payload, size_t len)
{
    uint8_t buf[64]; size_t padded; uint32_t dlc = dlc_for(len, &padded);
    memset(buf, 0, sizeof buf); memcpy(buf, payload, len);
    FDCAN_TxHeaderTypeDef hdr = {0};
    hdr.Identifier = id; hdr.IdType = FDCAN_STANDARD_ID; hdr.TxFrameType = FDCAN_DATA_FRAME; hdr.DataLength = dlc;
    hdr.ErrorStateIndicator = FDCAN_ESI_ACTIVE; hdr.BitRateSwitch = FDCAN_BRS_ON; hdr.FDFormat = FDCAN_FD_CAN;
    hdr.TxEventFifoControl = FDCAN_NO_TX_EVENTS; hdr.MessageMarker = 0;
    for (int tries = 0; tries < 3; tries++) {
        if (HAL_FDCAN_AddMessageToTxFifoQ(&hfdcan1, &hdr, buf) == HAL_OK) return true;
        vTaskDelay(1);
    }
    return false;
}

/* ------------------------------------------------------------------ TX task */
void comms_task(void *arg)
{
    (void)arg;
#ifdef WITH_LWIP
    s_udp_tx = netconn_new(NETCONN_UDP);
    netconn_bind(s_udp_tx, IP_ADDR_ANY, UDP_PORT_TX);
    IP4_ADDR(&s_gw_addr, 192, 168, 10, 1);     /* gateway IPC; overridden by DHCP option / config in production */
#endif
    HAL_FDCAN_Start(&hfdcan1);
    HAL_FDCAN_Start(&hfdcan2);
    HAL_FDCAN_ActivateNotification(&hfdcan1, FDCAN_IT_RX_FIFO0_NEW_MESSAGE, 0);
    HAL_FDCAN_ActivateNotification(&hfdcan2, FDCAN_IT_RX_FIFO0_NEW_MESSAGE, 0);

    comms_msg_t m;
    TickType_t last_hb = xTaskGetTickCount();
    for (;;) {
        if (xQueueReceive(q_comms, &m, pdMS_TO_TICKS(200)) == pdTRUE) {
            /* CAN-FD: PASS_SUMMARY is sent as its fixed 38-byte part (axles already went out as AXLE_EVENTs) */
            size_t can_len = (m.type == FRM_PASS_SUMMARY) ? FRM_PASS_FIXED_LEN : m.len;
            if (m.type == FRM_HEALTH && m.len > 64) {
                /* split 16-channel health into two 8-channel frames */
                uint8_t part[FRM_HEALTH_HDR_LEN + 8 * FRM_HEALTH_CH_LEN];
                for (int half = 0; half < 2; half++) {
                    memcpy(part, m.payload, FRM_HEALTH_HDR_LEN); part[8] = (uint8_t)(m.payload[8] + 8 * half); part[9] = 8;
                    memcpy(part + FRM_HEALTH_HDR_LEN, m.payload + FRM_HEALTH_HDR_LEN + half * 8 * FRM_HEALTH_CH_LEN, 8 * FRM_HEALTH_CH_LEN);
                    can_send(CAN_BASE_DAQ_TO_GW + 0x20u * LANE_NO + m.type, part, sizeof part);
                }
            } else can_send(CAN_BASE_DAQ_TO_GW + 0x20u * LANE_NO + m.type, m.payload, can_len);
#ifdef WITH_LWIP
            uint8_t frame[FRM_MAX_FRAME];
            size_t n = frm_udp_wrap(m.type, s_udp_seq++, (uint32_t)timebase_now_us(), m.payload, m.len, frame, sizeof frame);
            if (n) { struct netbuf *nb = netbuf_new(); if (nb) { void *d = netbuf_alloc(nb, (u16_t)n); if (d) { memcpy(d, frame, n); netconn_sendto(s_udp_tx, nb, &s_gw_addr, UDP_PORT_TX); } netbuf_delete(nb); } }
#endif
        }
        if ((xTaskGetTickCount() - last_hb) >= pdMS_TO_TICKS(HEARTBEAT_PERIOD_MS)) {
            last_hb = xTaskGetTickCount();
            frm_heartbeat_t hb = { .t_us = timebase_to_utc_us(timebase_now_us()), .uptime_s = (uint32_t)(xTaskGetTickCount() / configTICK_RATE_HZ), .fw_version = FW_VERSION, .state = detect_is_idle() ? 1 : 2 };
            uint8_t buf[FRM_HEARTBEAT_LEN];
            comms_post(FRM_HEARTBEAT, buf, frm_encode_heartbeat(&hb, buf, sizeof buf), false);
            wdg_checkin(WDG_COMMS);
        }
    }
}

/* ------------------------------------------------------------------ RX: CAN (ISR callback) */
static void handle_rx_payload(uint8_t type, const uint8_t *p, size_t len)
{
    if (type == FRM_TIME_SYNC) { frm_time_sync_t t; if (frm_decode_time_sync(p, len, &t)) timebase_apply_sync(t.utc_us_at_pps, t.pps_count); }
    else if (type == FRM_ENV) { frm_env_t e; if (frm_decode_env(p, len, &e)) { detect_set_pavement_temp(e.pavement_c_x100 / 100.0f); comms_post(FRM_ENV, p, FRM_ENV_LEN, true); } }
}

void HAL_FDCAN_RxFifo0Callback(FDCAN_HandleTypeDef *hfdcan, uint32_t its)
{
    if (!(its & FDCAN_IT_RX_FIFO0_NEW_MESSAGE)) return;
    FDCAN_RxHeaderTypeDef hdr; uint8_t data[64];
    if (HAL_FDCAN_GetRxMessage(hfdcan, FDCAN_RX_FIFO0, &hdr, data) != HAL_OK) return;
    uint32_t id = hdr.Identifier;
    if (hfdcan == &hfdcan1 && (id & ~0x1Fu) == (CAN_BASE_GW_TO_DAQ + 0x20u * LANE_NO)) {
        handle_rx_payload((uint8_t)(id & 0x1Fu), data, 64);
    } else if (hfdcan == &hfdcan2 && id >= 0x206 && id <= 0x208) {
        /* ESP32 ENV in 3 classic frames of 8 bytes: 0x206 -> bytes 0-7, 0x207 -> 8-15, 0x208 -> 16-21 */
        unsigned part = id - 0x206; size_t off = 8 * part, n = (part == 2) ? 6 : 8;
        memcpy(s_env_buf + off, data, n); s_env_mask |= (uint8_t)(1u << part);
        if (s_env_mask == 7u) { s_env_mask = 0; handle_rx_payload(FRM_ENV, s_env_buf, FRM_ENV_LEN); }
    }
}

/* ------------------------------------------------------------------ RX: UDP */
void comms_rx_task(void *arg)
{
    (void)arg;
#ifdef WITH_LWIP
    s_udp_rx = netconn_new(NETCONN_UDP);
    netconn_bind(s_udp_rx, IP_ADDR_ANY, UDP_PORT_RX);
    netconn_set_recvtimeout(s_udp_rx, 1000);
    for (;;) {
        struct netbuf *nb = NULL;
        if (netconn_recv(s_udp_rx, &nb) == ERR_OK && nb) {
            void *d; u16_t len; netbuf_data(nb, &d, &len);
            uint8_t type; uint16_t seq; const uint8_t *pl; size_t plen;
            if (frm_udp_unwrap((const uint8_t *)d, len, &type, &seq, &pl, &plen)) {
                taskENTER_CRITICAL();
                if (type == FRM_TIME_SYNC) { frm_time_sync_t t; if (frm_decode_time_sync(pl, plen, &t)) timebase_apply_sync(t.utc_us_at_pps, t.pps_count); }
                taskEXIT_CRITICAL();
            }
            netbuf_delete(nb);
        }
    }
#else
    for (;;) vTaskDelay(pdMS_TO_TICKS(1000));
#endif
}

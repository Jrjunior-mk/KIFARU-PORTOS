/**
 * @file tasks.h
 * @brief Inter-task types and entry points. Data flow:
 *
 *   DRDY ISR -> ads131m08 DMA x2 -> acq_task (assembles 16-ch sample blocks) --q_blocks--> detect_task
 *   detect_task (baseline, IIR, pulses, fusion) --q_comms--> comms_task (CAN-FD + UDP)
 *   health_task (noise/saturation/dead/drift, IR stuck, charge-amp reset) --q_comms--> comms_task
 *   loop/IR EXTI ISRs --q_comms (LOOP_EVENT/IR_EVENT) and -> detect_task state (presence)
 *   comms_task RX: TIME_SYNC -> timebase ; ENV (from ESP32 via CAN) -> forwarded + pavement temp cached
 *   wdg_task kicks IWDG only if every task has checked in during the last second.
 */
#ifndef TASKS_H
#define TASKS_H

#include <stdint.h>
#include <stdbool.h>
#include "app_config.h"
#include "frames.h"
#include "wim_dsp.h"

#ifndef HOST_TEST
#include "FreeRTOS.h"
#include "queue.h"
#include "task.h"
#include "semphr.h"
#endif

typedef struct {
    uint64_t t_first_us;                 /* mono timestamp of the first sample (DRDY capture) */
    uint32_t n_first;                    /* absolute sample counter of the first sample */
    uint8_t  n;                          /* samples in block (ACQ_BLOCK) */
    uint8_t  crc_err_mask;               /* bit0 ADC A, bit1 ADC B: frame had CRC error (samples repeated) */
    int32_t  raw[ACQ_BLOCK][ACQ_N_CH];
} acq_block_t;

typedef struct {
    uint8_t type;                        /* frm_type */
    uint8_t len;
    uint8_t payload[FRM_MAX_PAYLOAD];
} comms_msg_t;

/* per-channel idle statistics maintained by detect_task, read by health_task */
typedef struct {
    float   sum, sum2;                   /* for mean/rms over the window */
    float   max_abs;
    float   goertzel_s1, goertzel_s2;    /* 50 Hz Goertzel state */
    uint32_t n;
    uint32_t sat_count;
    float   baseline_prev_kg;            /* last window mean, for drift */
} chan_stats_t;

#ifndef HOST_TEST
extern QueueHandle_t q_blocks;           /* acq -> detect, depth 8 */
extern QueueHandle_t q_comms;            /* * -> comms, depth 32 */
extern SemaphoreHandle_t m_stats;

void acq_task(void *arg);
void detect_task(void *arg);
void health_task(void *arg);
void comms_task(void *arg);
void comms_rx_task(void *arg);
void wdg_task(void *arg);

/* watchdog check-in bits */
enum { WDG_ACQ = 1, WDG_DETECT = 2, WDG_HEALTH = 4, WDG_COMMS = 8, WDG_ALL = 15 };
void wdg_checkin(uint32_t bit);

/* shared state accessors */
void   detect_get_stats(chan_stats_t out[WIM_MAX_ROWS], bool *idle);
void   detect_reset_stats(void);
void   detect_set_pavement_temp(float c);
float  detect_get_pavement_temp(void);
void   detect_loop_event(uint8_t loop_id, bool occupied, uint64_t t_us);
void   detect_ir_event(uint8_t beam_id, bool blocked, uint64_t t_us);
bool   detect_is_idle(void);
bool   comms_post(uint8_t type, const uint8_t *payload, size_t len, bool from_isr);
void   afe_reset_pulse(void);            /* charge-amp reset relays, 20 ms */
#endif

#endif /* TASKS_H */

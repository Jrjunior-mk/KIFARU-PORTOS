/**
 * @file app_config.h
 * @brief Lane / rig configuration: channel map, geometry, AFE constants, task parameters.
 *
 * Build with -DKIFARU_RIG=1 for the 1:10 laboratory rig (docs/03-hardware/lab-rig-build-guide.md §4).
 */
#ifndef APP_CONFIG_H
#define APP_CONFIG_H

#include <stdint.h>

#define FW_VERSION          0x00010000u   /* 0xMMmmpppp -> 0.1.0 */
#define LANE_NO             0u            /* CAN id offset 0x20 * LANE_NO */

/* ---------------------------------------------------------------- acquisition */
#define ACQ_FS_HZ           8000.0f
#define ACQ_N_ADC           2
#define ACQ_N_CH            (8 * ACQ_N_ADC)
#define ACQ_BLOCK           16            /* samples per block handed to the detect task (2 ms) */

/* ADC A channels */
#define CH_P1L 0
#define CH_P1R 1
#define CH_P2L 2
#define CH_P2R 3
#define CH_P3L 4
#define CH_P3R 5
#define CH_BPL 6
#define CH_BPR 7
/* ADC B channels */
#define CH_EXC_MON   8
#define CH_AFE_TEMP  9
#define CH_SPARE0    10
#define CH_NEG12_MON 14
#define CH_POS12_MON 15

/* ---------------------------------------------------------------- AFE scale factors (docs/03-hardware/analog-front-end.md)
 * Piezo: S = 1.8 pC/N (certificate value replaces this), Cf = 22 nF, attenuator 1/6
 *   V_adc per kg per wheel = 1.8e-12 * 9.81 / 22e-9 / 6 = 0.1338 mV/kg   ->  kg per LSB = 143 nV / 0.1338 mV = 1.07e-3
 * Plate: 2 mV/V @ 15 t, 5 V exc, G = 101.2  ->  67.5 µV/kg per half-plate  ->  kg per LSB = 143 nV / 67.5 µV = 2.12e-3
 * These are nominal; per-channel `gain` from calibration multiplies them. */
#define AFE_PIEZO_KG_PER_LSB   (1.07e-3f)
#define AFE_PLATE_KG_PER_LSB   (2.12e-3f)
#define AFE_PIEZO_SAT_KG       (8500.0f)   /* per wheel, ~95 % of ADC full scale (8970 kg) */
#define AFE_PLATE_SAT_KG       (17000.0f)
#define AFE_RF_TAU_S           (150e6f * 22e-9f)   /* 3.3 s charge-amp time constant for droop correction */
#define AFE_EXC_NOMINAL_V      5.0f
#define AFE_EXC_DIVIDER        4.0f

/* ---------------------------------------------------------------- geometry */
#ifdef KIFARU_RIG
#define GEO_P1_M  0.40f
#define GEO_P2_M  0.70f
#define GEO_BP_M  1.00f
#define GEO_P3_M  1.30f
#define GEO_LOOP_LEN_M 0.0f
#else
#define GEO_P1_M  4.0f
#define GEO_P2_M  7.0f
#define GEO_BP_M  10.0f
#define GEO_P3_M  16.0f
#define GEO_LOOP_LEN_M 2.0f
#endif

/* ---------------------------------------------------------------- detection */
#define DET_THRESHOLD_KG     800.0f
#define DET_MIN_GAP_S        0.03f
#define DET_PASS_TIMEOUT_MS  2000u      /* pass closes 2 s after the last pulse if L3 never clears */
#define DET_MAX_PASS_MS      20000u

/* ---------------------------------------------------------------- health */
#define HEALTH_PERIOD_MS     10000u
#define HEALTH_IDLE_WINDOW_N 8000       /* 1 s */
#define HEALTH_NOISE_DEGRADED_KG 800.0f
#define HEALTH_DEAD_KG       50.0f
#define HEALTH_HUM50_KG      100.0f
#define HEALTH_DRIFT_KG_PER_MIN 2000.0f

/* ---------------------------------------------------------------- comms */
#define UDP_PORT_TX          5010u
#define UDP_PORT_RX          5011u
#define CAN_NOMINAL_BPS      500000u
#define CAN_DATA_BPS         2000000u
#define HEARTBEAT_PERIOD_MS  1000u
#define TIME_SYNC_HOLDOVER_S 600u

/* ---------------------------------------------------------------- RTOS */
#define TASK_PRIO_ACQ        6   /* highest application priority */
#define TASK_PRIO_DETECT     5
#define TASK_PRIO_COMMS      4
#define TASK_PRIO_HEALTH     3
#define TASK_PRIO_WDG        2
#define STACK_ACQ            1024
#define STACK_DETECT         4096
#define STACK_COMMS          2048
#define STACK_HEALTH         2048
#define STACK_WDG            256

#endif /* APP_CONFIG_H */

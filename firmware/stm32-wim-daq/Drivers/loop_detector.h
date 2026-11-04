/**
 * @file loop_detector.h
 * @brief Inductive-loop presence inputs (TTL from detector cards) — EXTI edge timestamping with debounce.
 */
#ifndef LOOP_DETECTOR_H
#define LOOP_DETECTOR_H
#include <stdint.h>
#include <stdbool.h>

#define LOOP_COUNT        3
#define LOOP_DEBOUNCE_US  2000u

typedef struct {
    bool     occupied;
    uint64_t t_change_us;      /* timestamp of last accepted edge */
    uint64_t t_last_raw_us;
    uint32_t edges, bounces;
    uint32_t occupancy_count;  /* rising edges accepted */
} loop_state_t;

typedef void (*loop_event_cb_t)(uint8_t loop_id /*1..3*/, bool occupied, uint64_t t_us);

void loop_detector_init(loop_event_cb_t cb);
/** Call from the EXTI ISR with the hardware timestamp and the pin level (true = occupied). */
void loop_detector_isr(uint8_t loop_index /*0..2*/, bool level, uint64_t t_us);
const loop_state_t *loop_detector_state(uint8_t loop_index);
/** Vehicle length estimate from occupancy time at a given speed (m). */
float loop_detector_vehicle_length_m(uint64_t t_enter_us, uint64_t t_leave_us, float speed_mps, float loop_len_m);

#endif

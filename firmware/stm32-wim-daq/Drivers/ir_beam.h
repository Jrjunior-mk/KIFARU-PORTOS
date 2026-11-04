/**
 * @file ir_beam.h
 * @brief IR beam pairs (opto-isolated 24 V PNP inputs) — timestamped blocked/clear edges, stuck detection.
 */
#ifndef IR_BEAM_H
#define IR_BEAM_H
#include <stdint.h>
#include <stdbool.h>

#define IR_COUNT          4          /* P1 low, P1 high, P3 low, P3 high */
#define IR_MIN_PULSE_US   1000u      /* a tyre at 25 m/s blocks a beam for >= 300 mm / 25 m/s = 12 ms; 1 ms rejects glitches */
#define IR_STUCK_S        30u

typedef struct {
    bool     blocked;
    uint64_t t_change_us;
    uint32_t blocks;            /* accepted block events (tyres for the low beams) */
    uint32_t glitches;
    bool     stuck;
} ir_state_t;

typedef void (*ir_event_cb_t)(uint8_t beam_id /*1..4*/, bool blocked, uint64_t t_us);

void ir_beam_init(ir_event_cb_t cb);
void ir_beam_isr(uint8_t beam_index, bool blocked_level, uint64_t t_us);
/** Periodic (1 s) check: flags beams blocked for > IR_STUCK_S while no loop is occupied. */
void ir_beam_poll(uint64_t now_us, bool any_loop_occupied);
const ir_state_t *ir_beam_state(uint8_t beam_index);
/** Tyre width estimate from low-beam block duration (m). */
float ir_beam_tyre_width_m(uint64_t t_block_us, uint64_t t_clear_us, float speed_mps);

#endif

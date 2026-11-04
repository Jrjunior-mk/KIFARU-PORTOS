#include "ir_beam.h"
#include <string.h>

static ir_state_t s_ir[IR_COUNT];
static ir_event_cb_t s_cb;

void ir_beam_init(ir_event_cb_t cb) { memset(s_ir, 0, sizeof s_ir); s_cb = cb; }

void ir_beam_isr(uint8_t i, bool blocked, uint64_t t_us)
{
    if (i >= IR_COUNT) return;
    ir_state_t *b = &s_ir[i];
    if (blocked == b->blocked) return;
    if (!blocked && (t_us - b->t_change_us) < IR_MIN_PULSE_US) {      /* too short to be a tyre: undo the block */
        b->blocked = false; b->glitches++; if (b->blocks) b->blocks--;
        return;
    }
    b->blocked = blocked;
    b->t_change_us = t_us;
    if (blocked) b->blocks++;
    b->stuck = false;
    if (s_cb) s_cb((uint8_t)(i + 1), blocked, t_us);
}

void ir_beam_poll(uint64_t now_us, bool any_loop_occupied)
{
    for (int i = 0; i < IR_COUNT; i++) {
        ir_state_t *b = &s_ir[i];
        b->stuck = b->blocked && !any_loop_occupied && (now_us - b->t_change_us) > (uint64_t)IR_STUCK_S * 1000000u;
    }
}

const ir_state_t *ir_beam_state(uint8_t i) { return (i < IR_COUNT) ? &s_ir[i] : 0; }

float ir_beam_tyre_width_m(uint64_t t_block_us, uint64_t t_clear_us, float speed_mps)
{
    if (t_clear_us <= t_block_us || speed_mps <= 0.0f) return 0.0f;
    /* the beam is blocked for the tyre contact length (viewed from the side, ~ tyre diameter chord at 150 mm) */
    return (float)(t_clear_us - t_block_us) * 1e-6f * speed_mps;
}

/**
 * @file timebase.h
 * @brief 64-bit microsecond time base: TIM2 (32-bit, 1 MHz) + overflow counter, GPS PPS capture, UTC offset.
 */
#ifndef TIMEBASE_H
#define TIMEBASE_H
#include <stdint.h>
#include <stdbool.h>

void     timebase_init(void);                     /* configures TIM2 @ 1 MHz, CH1 = PPS capture, CH2 = DRDY capture */
uint64_t timebase_now_us(void);                   /* monotonic since boot, ISR-safe */
uint64_t timebase_to_utc_us(uint64_t mono_us);    /* applies the TIME_SYNC offset; == mono if unsynced */
bool     timebase_is_synced(uint64_t now_us);     /* false if no TIME_SYNC for TIME_SYNC_HOLDOVER_S */
/** Called by comms when a TIME_SYNC frame arrives: UTC at PPS edge #pps_count. */
void     timebase_apply_sync(uint64_t utc_us_at_pps, uint32_t pps_count);
/* ISR hooks */
void     timebase_isr_overflow(void);
void     timebase_isr_pps_capture(uint32_t ccr);
void     timebase_isr_drdy_capture(uint32_t ccr);
uint64_t timebase_last_drdy_us(void);
uint32_t timebase_pps_count(void);

#endif

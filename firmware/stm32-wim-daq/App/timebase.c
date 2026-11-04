/**
 * @file timebase.c
 * @brief TIM2-based 64-bit µs clock with PPS discipline (STM32H7 HAL).
 */
#include "timebase.h"
#include "app_config.h"
#ifndef HOST_TEST
#include "stm32h7xx_hal.h"
TIM_HandleTypeDef htim2;
#endif

static volatile uint32_t s_overflows;          /* TIM2 wraps every 2^32 µs = 71.6 min */
static volatile uint64_t s_pps_mono_us[2];     /* last two PPS capture times (mono) */
static volatile uint32_t s_pps_count;
static volatile uint64_t s_last_drdy_us;
static volatile int64_t  s_utc_offset_us;      /* utc = mono + offset */
static volatile uint64_t s_last_sync_mono_us;
static volatile bool     s_synced;

#ifndef HOST_TEST
static inline uint32_t tim_cnt(void) { return TIM2->CNT; }
#else
static uint32_t s_fake_cnt; static inline uint32_t tim_cnt(void) { return s_fake_cnt; }
#endif

uint64_t timebase_now_us(void)
{
    uint32_t hi1, lo, hi2;
    do { hi1 = s_overflows; lo = tim_cnt(); hi2 = s_overflows; } while (hi1 != hi2);   /* wrap-safe read */
    return ((uint64_t)hi1 << 32) | lo;
}

static uint64_t extend(uint32_t ccr)
{
    /* a capture taken just before an overflow that has already been counted must use the previous epoch */
    uint64_t now = timebase_now_us();
    uint32_t hi = (uint32_t)(now >> 32);
    if (ccr > (uint32_t)now && hi > 0) hi--;
    return ((uint64_t)hi << 32) | ccr;
}

void timebase_isr_overflow(void) { s_overflows++; }

void timebase_isr_pps_capture(uint32_t ccr)
{
    s_pps_mono_us[1] = s_pps_mono_us[0];
    s_pps_mono_us[0] = extend(ccr);
    s_pps_count++;
}

void timebase_isr_drdy_capture(uint32_t ccr) { s_last_drdy_us = extend(ccr); }
uint64_t timebase_last_drdy_us(void) { return s_last_drdy_us; }
uint32_t timebase_pps_count(void) { return s_pps_count; }

void timebase_apply_sync(uint64_t utc_us_at_pps, uint32_t pps_count)
{
    /* the gateway labels the most recent PPS; if its count matches ours, the capture is the anchor */
    uint64_t anchor = s_pps_mono_us[0];
    if (pps_count + 1 == s_pps_count) anchor = s_pps_mono_us[1];     /* gateway one PPS behind */
    else if (pps_count != s_pps_count && s_pps_count != 0) return;    /* ambiguous: ignore */
    if (s_pps_count == 0) anchor = timebase_now_us();                 /* no GPS: coarse NTP-level sync */
    s_utc_offset_us = (int64_t)utc_us_at_pps - (int64_t)anchor;
    s_last_sync_mono_us = timebase_now_us();
    s_synced = true;
}

uint64_t timebase_to_utc_us(uint64_t mono_us) { return s_synced ? (uint64_t)((int64_t)mono_us + s_utc_offset_us) : mono_us; }

bool timebase_is_synced(uint64_t now_us)
{
    return s_synced && (now_us - s_last_sync_mono_us) < (uint64_t)TIME_SYNC_HOLDOVER_S * 1000000u;
}

#ifndef HOST_TEST
void timebase_init(void)
{
    /* TIM2: 32-bit, APB1 timer clock 240 MHz (480 MHz core, D2PPRE1 = /2, timer x2) -> prescaler 240 -> 1 MHz */
    __HAL_RCC_TIM2_CLK_ENABLE();
    htim2.Instance = TIM2;
    htim2.Init.Prescaler = 240 - 1;
    htim2.Init.CounterMode = TIM_COUNTERMODE_UP;
    htim2.Init.Period = 0xFFFFFFFFu;
    htim2.Init.ClockDivision = TIM_CLOCKDIVISION_DIV1;
    htim2.Init.AutoReloadPreload = TIM_AUTORELOAD_PRELOAD_DISABLE;
    HAL_TIM_Base_Init(&htim2);
    HAL_TIM_IC_Init(&htim2);

    TIM_IC_InitTypeDef ic = {0};
    ic.ICPolarity = TIM_INPUTCHANNELPOLARITY_RISING;   /* PPS rising edge */
    ic.ICSelection = TIM_ICSELECTION_DIRECTTI;
    ic.ICPrescaler = TIM_ICPSC_DIV1;
    ic.ICFilter = 0;
    HAL_TIM_IC_ConfigChannel(&htim2, &ic, TIM_CHANNEL_1);
    ic.ICPolarity = TIM_INPUTCHANNELPOLARITY_FALLING;  /* DRDY falling edge */
    HAL_TIM_IC_ConfigChannel(&htim2, &ic, TIM_CHANNEL_2);

    /* PA0 = TIM2_CH1 (PPS), PA1 = TIM2_CH2 (DRDY copy) — AF1 */
    __HAL_RCC_GPIOA_CLK_ENABLE();
    GPIO_InitTypeDef g = {0};
    g.Pin = GPIO_PIN_0 | GPIO_PIN_1; g.Mode = GPIO_MODE_AF_PP; g.Pull = GPIO_NOPULL; g.Speed = GPIO_SPEED_FREQ_HIGH; g.Alternate = GPIO_AF1_TIM2;
    HAL_GPIO_Init(GPIOA, &g);

    HAL_NVIC_SetPriority(TIM2_IRQn, 4, 0);
    HAL_NVIC_EnableIRQ(TIM2_IRQn);
    HAL_TIM_Base_Start_IT(&htim2);
    HAL_TIM_IC_Start_IT(&htim2, TIM_CHANNEL_1);
    HAL_TIM_IC_Start_IT(&htim2, TIM_CHANNEL_2);
}

/* HAL callbacks (TIM2_IRQHandler in stm32h7xx_it.c calls HAL_TIM_IRQHandler) */
void HAL_TIM_PeriodElapsedCallback(TIM_HandleTypeDef *htim) { if (htim->Instance == TIM2) timebase_isr_overflow(); }
void HAL_TIM_IC_CaptureCallback(TIM_HandleTypeDef *htim)
{
    if (htim->Instance != TIM2) return;
    if (htim->Channel == HAL_TIM_ACTIVE_CHANNEL_1) timebase_isr_pps_capture(HAL_TIM_ReadCapturedValue(htim, TIM_CHANNEL_1));
    else if (htim->Channel == HAL_TIM_ACTIVE_CHANNEL_2) timebase_isr_drdy_capture(HAL_TIM_ReadCapturedValue(htim, TIM_CHANNEL_2));
}
#else
void timebase_init(void) {}
#endif

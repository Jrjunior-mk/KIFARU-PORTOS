/**
 * @file acq_task.c
 * @brief Acquisition: two ADS131M08 on SPI1/SPI2 with DMA, started from the shared DRDY EXTI, blocks of 16 samples
 *        to the detect task. 8 kSPS x 16 channels; each frame read takes ~24 µs at 10 MHz SCLK, well inside 125 µs.
 */
#include "tasks.h"
#include "timebase.h"
#include "../Drivers/ads131m08.h"
#include "stm32h7xx_hal.h"
#include <string.h>

extern SPI_HandleTypeDef hspi1, hspi2;            /* configured in main.c (MX_SPI1_Init / MX_SPI2_Init) */
extern void acq_fault(const char *what);           /* main.c: log + fault LED */

static ads131m08_t s_adc[ACQ_N_ADC];
static ads131m08_hal_t s_hal[ACQ_N_ADC];
static TaskHandle_t s_acq_handle;
static volatile uint32_t s_dma_done_mask;           /* set by SPI DMA complete callbacks */
static acq_block_t s_block;
static uint32_t s_sample_counter;
static uint32_t s_drdy_overruns;

/* ------------------------------------------------------------------ HAL glue */
static void cs_a(ads131m08_hal_t *h, bool a) { (void)h; HAL_GPIO_WritePin(GPIOD, GPIO_PIN_14, a ? GPIO_PIN_RESET : GPIO_PIN_SET); }
static void cs_b(ads131m08_hal_t *h, bool a) { (void)h; HAL_GPIO_WritePin(GPIOD, GPIO_PIN_15, a ? GPIO_PIN_RESET : GPIO_PIN_SET); }
static void rst_shared(ads131m08_hal_t *h, bool a) { (void)h; HAL_GPIO_WritePin(GPIOF, GPIO_PIN_12, a ? GPIO_PIN_RESET : GPIO_PIN_SET); }
static void delay_ms(uint32_t ms) { if (xTaskGetSchedulerState() == taskSCHEDULER_RUNNING) vTaskDelay(pdMS_TO_TICKS(ms)); else HAL_Delay(ms); }
static bool xfer_blocking(ads131m08_hal_t *h, const uint8_t *tx, uint8_t *rx, size_t len)
{ return HAL_SPI_TransmitReceive((SPI_HandleTypeDef *)h->spi, (uint8_t *)tx, rx, (uint16_t)len, 10) == HAL_OK; }
static bool xfer_dma(ads131m08_hal_t *h, const uint8_t *tx, uint8_t *rx, size_t len)
{ return HAL_SPI_TransmitReceive_DMA((SPI_HandleTypeDef *)h->spi, (uint8_t *)tx, rx, (uint16_t)len) == HAL_OK; }

void HAL_SPI_TxRxCpltCallback(SPI_HandleTypeDef *hspi)
{
    BaseType_t woken = pdFALSE;
    if (hspi == &hspi1) s_dma_done_mask |= 1u;
    if (hspi == &hspi2) s_dma_done_mask |= 2u;
    if ((s_dma_done_mask & 3u) == 3u && s_acq_handle) {
        vTaskNotifyGiveFromISR(s_acq_handle, &woken);
        portYIELD_FROM_ISR(woken);
    }
}

/* DRDY falling edge (PF13, EXTI13; also wired to PA1 for the TIM2 capture timestamp) */
void acq_drdy_isr(void)
{
    if (s_adc[0].busy || s_adc[1].busy) { s_drdy_overruns++; return; }   /* previous frame still in flight */
    s_dma_done_mask = 0;
    ads131m08_start_frame_dma(&s_adc[0]);
    ads131m08_start_frame_dma(&s_adc[1]);
}

/* ------------------------------------------------------------------ task */
void acq_task(void *arg)
{
    (void)arg;
    s_acq_handle = xTaskGetCurrentTaskHandle();

    s_hal[0].spi = &hspi1; s_hal[0].cs = cs_a; s_hal[0].reset = rst_shared; s_hal[0].delay_ms = delay_ms; s_hal[0].xfer = xfer_blocking; s_hal[0].xfer_dma = xfer_dma;
    s_hal[1].spi = &hspi2; s_hal[1].cs = cs_b; s_hal[1].reset = rst_shared; s_hal[1].delay_ms = delay_ms; s_hal[1].xfer = xfer_blocking; s_hal[1].xfer_dma = xfer_dma;

    /* both ADCs share SYNC/RESET: reset once through dev 0, then configure each (dev 1's init re-pulses reset,
       which re-synchronises the modulators — acceptable because conversions have not started being consumed) */
    for (int i = 0; i < ACQ_N_ADC; i++) {
        if (!ads131m08_init(&s_adc[i], &s_hal[i])) { acq_fault(i == 0 ? "ADS131M08 A init" : "ADS131M08 B init"); vTaskDelay(pdMS_TO_TICKS(1000)); i--; continue; }
    }
    afe_reset_pulse();                               /* discharge Cf after the rails are up */

    memset(&s_block, 0, sizeof s_block);
    s_block.n = 0;

    /* enable DRDY interrupt now that both devices stream */
    HAL_NVIC_SetPriority(EXTI15_10_IRQn, 5, 0);
    HAL_NVIC_EnableIRQ(EXTI15_10_IRQn);

    for (;;) {
        /* wait for both DMA completions (one DRDY period = 125 µs; 10 ms timeout => ADC/clock fault) */
        if (ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(10)) == 0) {
            acq_fault("DRDY timeout");
            continue;
        }
        int32_t raw_a[ADS_NCH], raw_b[ADS_NCH];
        bool ok_a = ads131m08_parse_frame(&s_adc[0], raw_a);
        bool ok_b = ads131m08_parse_frame(&s_adc[1], raw_b);

        if (s_block.n == 0) {
            s_block.t_first_us = timebase_last_drdy_us();
            s_block.n_first = s_sample_counter;
            s_block.crc_err_mask = 0;
        }
        int32_t *dst = s_block.raw[s_block.n];
        if (ok_a) memcpy(dst, raw_a, sizeof raw_a); else { s_block.crc_err_mask |= 1u; if (s_block.n) memcpy(dst, s_block.raw[s_block.n - 1], 8 * sizeof(int32_t)); }
        if (ok_b) memcpy(dst + 8, raw_b, sizeof raw_b); else { s_block.crc_err_mask |= 2u; if (s_block.n) memcpy(dst + 8, s_block.raw[s_block.n - 1] + 8, 8 * sizeof(int32_t)); }
        s_block.n++;
        s_sample_counter++;

        if (s_block.n == ACQ_BLOCK) {
            if (xQueueSend(q_blocks, &s_block, 0) != pdTRUE) { /* detect task fell behind: drop block, count */ s_drdy_overruns++; }
            s_block.n = 0;
            wdg_checkin(WDG_ACQ);
        }
    }
}

/**
 * @file stm32h7xx_it.c
 * @brief Interrupt handlers: DRDY, loops, IR beams, DMA, SPI, FDCAN, TIM2. SysTick/PendSV/SVC are FreeRTOS's.
 */
#include "stm32h7xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"
#include "../../App/timebase.h"
#include "../../Drivers/loop_detector.h"
#include "../../Drivers/ir_beam.h"

extern SPI_HandleTypeDef hspi1, hspi2;
extern DMA_HandleTypeDef hdma_spi1_tx, hdma_spi1_rx, hdma_spi2_tx, hdma_spi2_rx;
extern FDCAN_HandleTypeDef hfdcan1, hfdcan2;
extern TIM_HandleTypeDef htim2;
extern void acq_drdy_isr(void);
extern void xPortSysTickHandler(void);

void NMI_Handler(void) { for (;;) {} }
void HardFault_Handler(void) { for (;;) {} }
void MemManage_Handler(void) { for (;;) {} }
void BusFault_Handler(void) { for (;;) {} }
void UsageFault_Handler(void) { for (;;) {} }
void DebugMon_Handler(void) {}

void SysTick_Handler(void)
{
    HAL_IncTick();
    if (xTaskGetSchedulerState() != taskSCHEDULER_NOT_STARTED) xPortSysTickHandler();
}

/* ---- DRDY (PF13) */
void EXTI15_10_IRQHandler(void)
{
    if (__HAL_GPIO_EXTI_GET_IT(GPIO_PIN_13)) { __HAL_GPIO_EXTI_CLEAR_IT(GPIO_PIN_13); acq_drdy_isr(); }
}

/* ---- loops PG0..PG2, IR PG3..PG6 : timestamp from the 1 MHz time base */
static inline void edge(uint16_t pin, int idx, bool is_loop)
{
    __HAL_GPIO_EXTI_CLEAR_IT(pin);
    bool level = HAL_GPIO_ReadPin(GPIOG, pin) == GPIO_PIN_SET;
    uint64_t t = timebase_now_us();
    if (is_loop) loop_detector_isr((uint8_t)idx, level, t); else ir_beam_isr((uint8_t)idx, level, t);
}
void EXTI0_IRQHandler(void) { if (__HAL_GPIO_EXTI_GET_IT(GPIO_PIN_0)) edge(GPIO_PIN_0, 0, true); }
void EXTI1_IRQHandler(void) { if (__HAL_GPIO_EXTI_GET_IT(GPIO_PIN_1)) edge(GPIO_PIN_1, 1, true); }
void EXTI2_IRQHandler(void) { if (__HAL_GPIO_EXTI_GET_IT(GPIO_PIN_2)) edge(GPIO_PIN_2, 2, true); }
void EXTI3_IRQHandler(void) { if (__HAL_GPIO_EXTI_GET_IT(GPIO_PIN_3)) edge(GPIO_PIN_3, 0, false); }
void EXTI4_IRQHandler(void) { if (__HAL_GPIO_EXTI_GET_IT(GPIO_PIN_4)) edge(GPIO_PIN_4, 1, false); }
void EXTI9_5_IRQHandler(void)
{
    if (__HAL_GPIO_EXTI_GET_IT(GPIO_PIN_5)) edge(GPIO_PIN_5, 2, false);
    if (__HAL_GPIO_EXTI_GET_IT(GPIO_PIN_6)) edge(GPIO_PIN_6, 3, false);
}

/* ---- DMA / SPI / FDCAN / TIM2 */
void DMA1_Stream0_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_spi1_rx); }
void DMA1_Stream1_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_spi1_tx); }
void DMA1_Stream2_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_spi2_rx); }
void DMA1_Stream3_IRQHandler(void) { HAL_DMA_IRQHandler(&hdma_spi2_tx); }
void SPI1_IRQHandler(void) { HAL_SPI_IRQHandler(&hspi1); }
void SPI2_IRQHandler(void) { HAL_SPI_IRQHandler(&hspi2); }
void FDCAN1_IT0_IRQHandler(void) { HAL_FDCAN_IRQHandler(&hfdcan1); }
void FDCAN2_IT0_IRQHandler(void) { HAL_FDCAN_IRQHandler(&hfdcan2); }
void TIM2_IRQHandler(void) { HAL_TIM_IRQHandler(&htim2); }

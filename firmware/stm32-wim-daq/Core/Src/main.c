/**
 * @file main.c
 * @brief KIFARU PORTOS WIM DAQ — STM32H743, FreeRTOS. Peripheral bring-up, task creation, watchdog.
 *
 * Clock: HSE 8 MHz (Nucleo: ST-LINK MCO) -> PLL1 -> 480 MHz SYSCLK (VOS0), AHB 240 MHz, APB 120 MHz.
 * SPI1 (ADC A) PA5/PA6/PB5, CS PD14 ; SPI2 (ADC B) PB13/PB14/PB15, CS PD15 ; DRDY PF13 (EXTI13) + PA1 (TIM2 CH2)
 * SYNC/RESET PF12 ; AFE reset relays PF11 ; PPS PA0 (TIM2 CH1) ; FDCAN1 PD0/PD1 ; FDCAN2 PB12/PB13? -> use PB5/PB6 on
 * real board (Nucleo conflicts noted in README) ; loops PG0..PG2 (EXTI0..2) ; IR PG3..PG6 ; fault LED PB14.
 * Pin assignments are the design intent; they must be reconciled with the final PCB in CubeMX.
 */
#include "stm32h7xx_hal.h"
#include "FreeRTOS.h"
#include "task.h"
#include "queue.h"
#include "semphr.h"
#include "../../App/tasks.h"
#include "../../App/timebase.h"
#include "../../Drivers/loop_detector.h"
#include "../../Drivers/ir_beam.h"
#include <string.h>

SPI_HandleTypeDef hspi1, hspi2;
DMA_HandleTypeDef hdma_spi1_tx, hdma_spi1_rx, hdma_spi2_tx, hdma_spi2_rx;
FDCAN_HandleTypeDef hfdcan1, hfdcan2;
IWDG_HandleTypeDef hiwdg1;
UART_HandleTypeDef huart3;

QueueHandle_t q_blocks, q_comms;
SemaphoreHandle_t m_stats;
static volatile uint32_t s_wdg_bits;

/* ------------------------------------------------------------------ fault reporting */
void acq_fault(const char *what)
{
    HAL_GPIO_WritePin(GPIOB, GPIO_PIN_14, GPIO_PIN_SET);
    HAL_UART_Transmit(&huart3, (uint8_t *)"FAULT: ", 7, 10);
    HAL_UART_Transmit(&huart3, (uint8_t *)what, (uint16_t)strlen(what), 10);
    HAL_UART_Transmit(&huart3, (uint8_t *)"\r\n", 2, 10);
}

void afe_reset_pulse(void)
{
    HAL_GPIO_WritePin(GPIOF, GPIO_PIN_11, GPIO_PIN_SET);     /* reed relays close, 1 kΩ discharge, tau 22 µs */
    vTaskDelay(pdMS_TO_TICKS(20));
    HAL_GPIO_WritePin(GPIOF, GPIO_PIN_11, GPIO_PIN_RESET);
}

void wdg_checkin(uint32_t bit) { s_wdg_bits |= bit; }

void wdg_task(void *arg)
{
    (void)arg;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(500));
        if ((s_wdg_bits & WDG_ALL) == WDG_ALL) { HAL_IWDG_Refresh(&hiwdg1); s_wdg_bits = 0; }
        /* otherwise the IWDG (2 s) resets the MCU: a hung task is a fault, and the gateway sees HEARTBEAT stop */
    }
}

/* ------------------------------------------------------------------ clocks */
static void SystemClock_Config(void)
{
    HAL_PWREx_ConfigSupply(PWR_LDO_SUPPLY);
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE0);          /* VOS0 for 480 MHz (rev V silicon) */
    while (!__HAL_PWR_GET_FLAG(PWR_FLAG_VOSRDY)) {}

    RCC_OscInitTypeDef osc = {0};
    osc.OscillatorType = RCC_OSCILLATORTYPE_HSE | RCC_OSCILLATORTYPE_LSI;
    osc.HSEState = RCC_HSE_BYPASS;             /* Nucleo: 8 MHz from ST-LINK MCO; set RCC_HSE_ON with a crystal */
    osc.LSIState = RCC_LSI_ON;                 /* IWDG */
    osc.PLL.PLLState = RCC_PLL_ON; osc.PLL.PLLSource = RCC_PLLSOURCE_HSE;
    osc.PLL.PLLM = 1; osc.PLL.PLLN = 120; osc.PLL.PLLP = 2; osc.PLL.PLLQ = 20; osc.PLL.PLLR = 2;   /* 8/1*120 = 960 MHz VCO */
    osc.PLL.PLLRGE = RCC_PLL1VCIRANGE_3; osc.PLL.PLLVCOSEL = RCC_PLL1VCOWIDE; osc.PLL.PLLFRACN = 0;
    if (HAL_RCC_OscConfig(&osc) != HAL_OK) for (;;) {}

    RCC_ClkInitTypeDef clk = {0};
    clk.ClockType = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2 | RCC_CLOCKTYPE_D3PCLK1 | RCC_CLOCKTYPE_D1PCLK1;
    clk.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
    clk.SYSCLKDivider = RCC_SYSCLK_DIV1; clk.AHBCLKDivider = RCC_HCLK_DIV2;
    clk.APB3CLKDivider = RCC_APB3_DIV2; clk.APB1CLKDivider = RCC_APB1_DIV2; clk.APB2CLKDivider = RCC_APB2_DIV2; clk.APB4CLKDivider = RCC_APB4_DIV2;
    if (HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_4) != HAL_OK) for (;;) {}

    /* FDCAN kernel clock from PLL1Q (960/20 = 48 MHz) */
    RCC_PeriphCLKInitTypeDef p = {0};
    p.PeriphClockSelection = RCC_PERIPHCLK_FDCAN | RCC_PERIPHCLK_SPI1 | RCC_PERIPHCLK_SPI2;
    p.FdcanClockSelection = RCC_FDCANCLKSOURCE_PLL;
    p.Spi123ClockSelection = RCC_SPI123CLKSOURCE_PLL;      /* 48 MHz? PLL1Q -> prescaler /4 => 12 MHz SCLK; verify */
    HAL_RCCEx_PeriphCLKConfig(&p);
}

/* ------------------------------------------------------------------ peripherals */
static void MX_GPIO_Init(void)
{
    __HAL_RCC_GPIOA_CLK_ENABLE(); __HAL_RCC_GPIOB_CLK_ENABLE(); __HAL_RCC_GPIOD_CLK_ENABLE(); __HAL_RCC_GPIOF_CLK_ENABLE(); __HAL_RCC_GPIOG_CLK_ENABLE();
    GPIO_InitTypeDef g = {0};
    /* outputs: CS A/B, SYNC/RESET, AFE reset, fault LED */
    g.Mode = GPIO_MODE_OUTPUT_PP; g.Pull = GPIO_NOPULL; g.Speed = GPIO_SPEED_FREQ_HIGH;
    g.Pin = GPIO_PIN_14 | GPIO_PIN_15; HAL_GPIO_Init(GPIOD, &g); HAL_GPIO_WritePin(GPIOD, GPIO_PIN_14 | GPIO_PIN_15, GPIO_PIN_SET);
    g.Pin = GPIO_PIN_11 | GPIO_PIN_12; HAL_GPIO_Init(GPIOF, &g); HAL_GPIO_WritePin(GPIOF, GPIO_PIN_12, GPIO_PIN_SET); HAL_GPIO_WritePin(GPIOF, GPIO_PIN_11, GPIO_PIN_RESET);
    g.Pin = GPIO_PIN_14; HAL_GPIO_Init(GPIOB, &g);
    /* DRDY: EXTI13 falling */
    g.Mode = GPIO_MODE_IT_FALLING; g.Pull = GPIO_PULLUP; g.Pin = GPIO_PIN_13; HAL_GPIO_Init(GPIOF, &g);
    /* loops PG0..2 and IR PG3..6: both edges */
    g.Mode = GPIO_MODE_IT_RISING_FALLING; g.Pull = GPIO_PULLDOWN; g.Pin = GPIO_PIN_0 | GPIO_PIN_1 | GPIO_PIN_2 | GPIO_PIN_3 | GPIO_PIN_4 | GPIO_PIN_5 | GPIO_PIN_6; HAL_GPIO_Init(GPIOG, &g);
    HAL_NVIC_SetPriority(EXTI0_IRQn, 6, 0); HAL_NVIC_EnableIRQ(EXTI0_IRQn);
    HAL_NVIC_SetPriority(EXTI1_IRQn, 6, 0); HAL_NVIC_EnableIRQ(EXTI1_IRQn);
    HAL_NVIC_SetPriority(EXTI2_IRQn, 6, 0); HAL_NVIC_EnableIRQ(EXTI2_IRQn);
    HAL_NVIC_SetPriority(EXTI3_IRQn, 6, 0); HAL_NVIC_EnableIRQ(EXTI3_IRQn);
    HAL_NVIC_SetPriority(EXTI4_IRQn, 6, 0); HAL_NVIC_EnableIRQ(EXTI4_IRQn);
    HAL_NVIC_SetPriority(EXTI9_5_IRQn, 6, 0); HAL_NVIC_EnableIRQ(EXTI9_5_IRQn);
}

static void spi_common(SPI_HandleTypeDef *h, SPI_TypeDef *inst)
{
    h->Instance = inst;
    h->Init.Mode = SPI_MODE_MASTER; h->Init.Direction = SPI_DIRECTION_2LINES; h->Init.DataSize = SPI_DATASIZE_8BIT;
    h->Init.CLKPolarity = SPI_POLARITY_LOW; h->Init.CLKPhase = SPI_PHASE_2EDGE;    /* ADS131M08: SPI mode 1 */
    h->Init.NSS = SPI_NSS_SOFT; h->Init.BaudRatePrescaler = SPI_BAUDRATEPRESCALER_8;  /* kernel clk / 8 -> ~10 MHz; verify kernel clock */
    h->Init.FirstBit = SPI_FIRSTBIT_MSB; h->Init.TIMode = SPI_TIMODE_DISABLE; h->Init.CRCCalculation = SPI_CRCCALCULATION_DISABLE;
    h->Init.NSSPMode = SPI_NSS_PULSE_DISABLE; h->Init.FifoThreshold = SPI_FIFO_THRESHOLD_01DATA;
    h->Init.MasterKeepIOState = SPI_MASTER_KEEP_IO_STATE_ENABLE;
    if (HAL_SPI_Init(h) != HAL_OK) for (;;) {}
}

static void dma_link(DMA_HandleTypeDef *d, DMA_Stream_TypeDef *stream, uint32_t request, uint32_t dir, SPI_HandleTypeDef *spi, bool tx)
{
    d->Instance = stream; d->Init.Request = request; d->Init.Direction = dir;
    d->Init.PeriphInc = DMA_PINC_DISABLE; d->Init.MemInc = DMA_MINC_ENABLE;
    d->Init.PeriphDataAlignment = DMA_PDATAALIGN_BYTE; d->Init.MemDataAlignment = DMA_MDATAALIGN_BYTE;
    d->Init.Mode = DMA_NORMAL; d->Init.Priority = DMA_PRIORITY_HIGH; d->Init.FIFOMode = DMA_FIFOMODE_DISABLE;
    if (HAL_DMA_Init(d) != HAL_OK) for (;;) {}
    if (tx) __HAL_LINKDMA(spi, hdmatx, *d); else __HAL_LINKDMA(spi, hdmarx, *d);
}

static void MX_SPI_DMA_Init(void)
{
    __HAL_RCC_SPI1_CLK_ENABLE(); __HAL_RCC_SPI2_CLK_ENABLE(); __HAL_RCC_DMA1_CLK_ENABLE();
    GPIO_InitTypeDef g = {0};
    g.Mode = GPIO_MODE_AF_PP; g.Pull = GPIO_NOPULL; g.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    g.Alternate = GPIO_AF5_SPI1; g.Pin = GPIO_PIN_5 | GPIO_PIN_6; HAL_GPIO_Init(GPIOA, &g); g.Pin = GPIO_PIN_5; HAL_GPIO_Init(GPIOB, &g);
    g.Alternate = GPIO_AF5_SPI2; g.Pin = GPIO_PIN_13 | GPIO_PIN_14 | GPIO_PIN_15; HAL_GPIO_Init(GPIOB, &g);
    spi_common(&hspi1, SPI1); spi_common(&hspi2, SPI2);
    dma_link(&hdma_spi1_rx, DMA1_Stream0, DMA_REQUEST_SPI1_RX, DMA_PERIPH_TO_MEMORY, &hspi1, false);
    dma_link(&hdma_spi1_tx, DMA1_Stream1, DMA_REQUEST_SPI1_TX, DMA_MEMORY_TO_PERIPH, &hspi1, true);
    dma_link(&hdma_spi2_rx, DMA1_Stream2, DMA_REQUEST_SPI2_RX, DMA_PERIPH_TO_MEMORY, &hspi2, false);
    dma_link(&hdma_spi2_tx, DMA1_Stream3, DMA_REQUEST_SPI2_TX, DMA_MEMORY_TO_PERIPH, &hspi2, true);
    HAL_NVIC_SetPriority(DMA1_Stream0_IRQn, 5, 0); HAL_NVIC_EnableIRQ(DMA1_Stream0_IRQn);
    HAL_NVIC_SetPriority(DMA1_Stream1_IRQn, 5, 0); HAL_NVIC_EnableIRQ(DMA1_Stream1_IRQn);
    HAL_NVIC_SetPriority(DMA1_Stream2_IRQn, 5, 0); HAL_NVIC_EnableIRQ(DMA1_Stream2_IRQn);
    HAL_NVIC_SetPriority(DMA1_Stream3_IRQn, 5, 0); HAL_NVIC_EnableIRQ(DMA1_Stream3_IRQn);
    HAL_NVIC_SetPriority(SPI1_IRQn, 5, 0); HAL_NVIC_EnableIRQ(SPI1_IRQn);
    HAL_NVIC_SetPriority(SPI2_IRQn, 5, 0); HAL_NVIC_EnableIRQ(SPI2_IRQn);
}

static void fdcan_common(FDCAN_HandleTypeDef *h, FDCAN_GlobalTypeDef *inst, bool fd)
{
    /* kernel clock 48 MHz: nominal 500 kbit/s = 48e6 / (prescaler 6 * (1 + 11 + 4)) ; data 2 Mbit/s = 48e6 / (2 * (1 + 8 + 3)) */
    h->Instance = inst;
    h->Init.FrameFormat = fd ? FDCAN_FRAME_FD_BRS : FDCAN_FRAME_CLASSIC;
    h->Init.Mode = FDCAN_MODE_NORMAL; h->Init.AutoRetransmission = ENABLE; h->Init.TransmitPause = DISABLE; h->Init.ProtocolException = DISABLE;
    h->Init.NominalPrescaler = 6; h->Init.NominalSyncJumpWidth = 4; h->Init.NominalTimeSeg1 = 11; h->Init.NominalTimeSeg2 = 4;
    h->Init.DataPrescaler = 2; h->Init.DataSyncJumpWidth = 3; h->Init.DataTimeSeg1 = 8; h->Init.DataTimeSeg2 = 3;
    h->Init.MessageRAMOffset = (inst == FDCAN1) ? 0 : 1280;
    h->Init.StdFiltersNbr = 2; h->Init.ExtFiltersNbr = 0;
    h->Init.RxFifo0ElmtsNbr = 8; h->Init.RxFifo0ElmtSize = FDCAN_DATA_BYTES_64;
    h->Init.RxFifo1ElmtsNbr = 0; h->Init.RxBuffersNbr = 0;
    h->Init.TxEventsNbr = 0; h->Init.TxBuffersNbr = 0; h->Init.TxFifoQueueElmtsNbr = 16; h->Init.TxFifoQueueMode = FDCAN_TX_FIFO_OPERATION; h->Init.TxElmtSize = FDCAN_DATA_BYTES_64;
    if (HAL_FDCAN_Init(h) != HAL_OK) for (;;) {}
}

static void MX_FDCAN_Init(void)
{
    __HAL_RCC_FDCAN_CLK_ENABLE();
    GPIO_InitTypeDef g = {0};
    g.Mode = GPIO_MODE_AF_PP; g.Pull = GPIO_NOPULL; g.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    g.Alternate = GPIO_AF9_FDCAN1; g.Pin = GPIO_PIN_0 | GPIO_PIN_1; HAL_GPIO_Init(GPIOD, &g);
    g.Alternate = GPIO_AF9_FDCAN2; g.Pin = GPIO_PIN_5 | GPIO_PIN_6; HAL_GPIO_Init(GPIOB, &g);   /* NOTE: PB5 conflicts with SPI1_MOSI on Nucleo; final PCB uses PB12/PB13 for FDCAN2 */
    fdcan_common(&hfdcan1, FDCAN1, true);
    fdcan_common(&hfdcan2, FDCAN2, false);
    FDCAN_FilterTypeDef f = {0};
    f.IdType = FDCAN_STANDARD_ID; f.FilterIndex = 0; f.FilterType = FDCAN_FILTER_RANGE; f.FilterConfig = FDCAN_FILTER_TO_RXFIFO0;
    f.FilterID1 = CAN_BASE_GW_TO_DAQ + 0x20u * LANE_NO; f.FilterID2 = f.FilterID1 + 0x1Fu; HAL_FDCAN_ConfigFilter(&hfdcan1, &f);
    f.FilterID1 = 0x200; f.FilterID2 = 0x27F; HAL_FDCAN_ConfigFilter(&hfdcan2, &f);
    HAL_FDCAN_ConfigGlobalFilter(&hfdcan1, FDCAN_REJECT, FDCAN_REJECT, FDCAN_FILTER_REMOTE, FDCAN_FILTER_REMOTE);
    HAL_FDCAN_ConfigGlobalFilter(&hfdcan2, FDCAN_REJECT, FDCAN_REJECT, FDCAN_FILTER_REMOTE, FDCAN_FILTER_REMOTE);
    HAL_NVIC_SetPriority(FDCAN1_IT0_IRQn, 7, 0); HAL_NVIC_EnableIRQ(FDCAN1_IT0_IRQn);
    HAL_NVIC_SetPriority(FDCAN2_IT0_IRQn, 7, 0); HAL_NVIC_EnableIRQ(FDCAN2_IT0_IRQn);
}

static void MX_USART3_Init(void)
{
    __HAL_RCC_USART3_CLK_ENABLE();
    GPIO_InitTypeDef g = {0};
    g.Mode = GPIO_MODE_AF_PP; g.Pull = GPIO_NOPULL; g.Speed = GPIO_SPEED_FREQ_LOW; g.Alternate = GPIO_AF7_USART3; g.Pin = GPIO_PIN_8 | GPIO_PIN_9; HAL_GPIO_Init(GPIOD, &g);
    huart3.Instance = USART3; huart3.Init.BaudRate = 921600; huart3.Init.WordLength = UART_WORDLENGTH_8B; huart3.Init.StopBits = UART_STOPBITS_1;
    huart3.Init.Parity = UART_PARITY_NONE; huart3.Init.Mode = UART_MODE_TX_RX; huart3.Init.HwFlowCtl = UART_HWCONTROL_NONE; huart3.Init.OverSampling = UART_OVERSAMPLING_16;
    HAL_UART_Init(&huart3);
}

static void MX_IWDG_Init(void)
{
    hiwdg1.Instance = IWDG1; hiwdg1.Init.Prescaler = IWDG_PRESCALER_32; hiwdg1.Init.Reload = 2000; hiwdg1.Init.Window = 4095;   /* 32 kHz/32 = 1 kHz -> 2 s */
    HAL_IWDG_Init(&hiwdg1);
}

/* ------------------------------------------------------------------ main */
int main(void)
{
    SCB_EnableICache(); SCB_EnableDCache();
    HAL_Init();
    SystemClock_Config();
    MX_GPIO_Init();
    MX_USART3_Init();
    MX_SPI_DMA_Init();
    MX_FDCAN_Init();
    timebase_init();
    MX_IWDG_Init();
#ifdef WITH_LWIP
    extern void MX_LWIP_Init(void);   /* CubeMX-generated (LWIP/App/lwip.c) — see README §4 */
#endif

    q_blocks = xQueueCreate(8, sizeof(acq_block_t));
    q_comms  = xQueueCreate(32, sizeof(comms_msg_t));
    m_stats  = xSemaphoreCreateMutex();

    loop_detector_init(detect_loop_event);
    ir_beam_init(detect_ir_event);

    xTaskCreate(acq_task,    "acq",    STACK_ACQ,    NULL, TASK_PRIO_ACQ,    NULL);
    xTaskCreate(detect_task, "detect", STACK_DETECT, NULL, TASK_PRIO_DETECT, NULL);
    xTaskCreate(health_task, "health", STACK_HEALTH, NULL, TASK_PRIO_HEALTH, NULL);
    xTaskCreate(comms_task,  "comms",  STACK_COMMS,  NULL, TASK_PRIO_COMMS,  NULL);
    xTaskCreate(comms_rx_task, "commsrx", STACK_COMMS, NULL, TASK_PRIO_COMMS, NULL);
    xTaskCreate(wdg_task,    "wdg",    STACK_WDG,    NULL, TASK_PRIO_WDG,    NULL);

    HAL_UART_Transmit(&huart3, (uint8_t *)"KIFARU WIM DAQ boot\r\n", 21, 10);
    vTaskStartScheduler();
    for (;;) {}
}

/* FreeRTOS static hooks */
void vApplicationStackOverflowHook(TaskHandle_t t, char *name) { (void)t; acq_fault(name); for (;;) {} }
void vApplicationMallocFailedHook(void) { acq_fault("malloc"); for (;;) {} }
void HAL_MspInit(void) { __HAL_RCC_SYSCFG_CLK_ENABLE(); }

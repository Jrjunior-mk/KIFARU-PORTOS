/**
 * @file ads131m08.h
 * @brief ADS131M08 (TI) 8-channel simultaneous 24-bit delta-sigma ADC driver — SPI + DMA, DRDY-driven.
 *
 * Register map and command encodings follow the ADS131M0x datasheet as understood by the authors; every value is
 * marked for verification on the bench (`README.md` §9). Word length is fixed at 24 bits (MODE.WLENGTH = 01), so a
 * full frame is 10 words = 30 bytes: [STATUS][CH0..CH7][CRC].
 */
#ifndef ADS131M08_H
#define ADS131M08_H

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- register addresses */
#define ADS_REG_ID            0x00u   /* [15:8] = 0x24 for M08? -> read-only ID; verify on bench */
#define ADS_REG_STATUS        0x01u
#define ADS_REG_MODE          0x02u
#define ADS_REG_CLOCK         0x03u
#define ADS_REG_GAIN1         0x04u   /* PGA ch0..3, 3 bits each (0 = gain 1) */
#define ADS_REG_GAIN2         0x05u   /* PGA ch4..7 */
#define ADS_REG_CFG           0x06u
#define ADS_REG_THRSHLD_MSB   0x07u
#define ADS_REG_THRSHLD_LSB   0x08u
#define ADS_REG_CH0_CFG       0x09u   /* then OCAL_MSB, OCAL_LSB, GCAL_MSB, GCAL_LSB: 5 regs per channel */
#define ADS_REG_CHn_CFG(n)    (0x09u + 5u * (n))
#define ADS_REG_CHn_OCAL_MSB(n) (0x0Au + 5u * (n))
#define ADS_REG_CHn_OCAL_LSB(n) (0x0Bu + 5u * (n))
#define ADS_REG_CHn_GCAL_MSB(n) (0x0Cu + 5u * (n))
#define ADS_REG_CHn_GCAL_LSB(n) (0x0Du + 5u * (n))
#define ADS_REG_REGMAP_CRC    0x3Eu

/* ---- commands (16-bit, sent MSB-first in a 24-bit word, lower byte zero) */
#define ADS_CMD_NULL          0x0000u
#define ADS_CMD_RESET         0x0011u
#define ADS_CMD_STANDBY       0x0022u
#define ADS_CMD_WAKEUP        0x0033u
#define ADS_CMD_LOCK          0x0555u
#define ADS_CMD_UNLOCK        0x0655u
#define ADS_CMD_RREG(addr, n) (0xA000u | (((addr) & 0x3Fu) << 7) | (((n) - 1u) & 0x7Fu))
#define ADS_CMD_WREG(addr, n) (0x6000u | (((addr) & 0x3Fu) << 7) | (((n) - 1u) & 0x7Fu))

/* ---- MODE register bits */
#define ADS_MODE_REG_CRC_EN   (1u << 13)
#define ADS_MODE_RX_CRC_EN    (1u << 12)
#define ADS_MODE_CRC_TYPE_ANSI (1u << 11)      /* 0 = CCITT (0x1021) */
#define ADS_MODE_RESET        (1u << 10)
#define ADS_MODE_WLEN_16      (0u << 8)
#define ADS_MODE_WLEN_24      (1u << 8)
#define ADS_MODE_WLEN_32_ZERO (2u << 8)
#define ADS_MODE_WLEN_32_SIGN (3u << 8)
#define ADS_MODE_TIMEOUT      (1u << 4)
#define ADS_MODE_DRDY_SEL_MOST_LAGGING (0u << 2)
#define ADS_MODE_DRDY_HIZ     (1u << 1)
#define ADS_MODE_DRDY_FMT_PULSE (1u << 0)

/* ---- CLOCK register */
#define ADS_CLOCK_CH_EN_ALL   (0xFFu << 8)
#define ADS_CLOCK_OSR_128     (0u << 2)
#define ADS_CLOCK_OSR_256     (1u << 2)
#define ADS_CLOCK_OSR_512     (2u << 2)   /* 8192 MHz/2/512 = 8000 SPS */
#define ADS_CLOCK_OSR_1024    (3u << 2)   /* power-on default: 4000 SPS */
#define ADS_CLOCK_OSR_2048    (4u << 2)
#define ADS_CLOCK_PWR_VLP     0u
#define ADS_CLOCK_PWR_LP      1u
#define ADS_CLOCK_PWR_HR      2u

#define ADS_NCH               8
#define ADS_WORD_BYTES        3
#define ADS_FRAME_WORDS       (1 + ADS_NCH + 1)
#define ADS_FRAME_BYTES       (ADS_FRAME_WORDS * ADS_WORD_BYTES)   /* 30 */
#define ADS_FSR_V             1.2f                                  /* ±1.2 V at gain 1 */
#define ADS_LSB_V             (ADS_FSR_V / 8388608.0f)              /* 1.2 / 2^23 = 143 nV */

/* ---- platform hooks the application must provide (HAL glue lives in acq_task.c) */
typedef struct ads131m08_hal {
    void *spi;                                         /* SPI_HandleTypeDef* */
    void (*cs)(struct ads131m08_hal *h, bool assert);  /* chip select */
    void (*reset)(struct ads131m08_hal *h, bool assert);
    void (*delay_ms)(uint32_t ms);
    /* blocking full-duplex transfer (used during init only) */
    bool (*xfer)(struct ads131m08_hal *h, const uint8_t *tx, uint8_t *rx, size_t len);
    /* non-blocking DMA transfer; completion is signalled via ads131m08_dma_complete() */
    bool (*xfer_dma)(struct ads131m08_hal *h, const uint8_t *tx, uint8_t *rx, size_t len);
} ads131m08_hal_t;

typedef struct {
    ads131m08_hal_t *hal;
    uint8_t  tx_frame[ADS_FRAME_BYTES];   /* NULL command + zeros, constant during streaming */
    uint8_t  rx_frame[ADS_FRAME_BYTES];
    uint16_t last_status;
    uint32_t crc_errors;
    uint32_t frames;
    bool     busy;
} ads131m08_t;

/** Reset, verify ID, program MODE (24-bit words, RX CRC on), CLOCK (OSR 512, HR, all channels), gain 1. */
bool ads131m08_init(ads131m08_t *dev, ads131m08_hal_t *hal);
bool ads131m08_read_reg(ads131m08_t *dev, uint8_t addr, uint16_t *value);
bool ads131m08_write_reg(ads131m08_t *dev, uint8_t addr, uint16_t value);
/** Kick a DMA frame read (call from the DRDY ISR). */
bool ads131m08_start_frame_dma(ads131m08_t *dev);
/**
 * Parse the received frame after DMA completion: checks CRC-16/CCITT over the 9 data words, sign-extends the 8
 * channel values into out[8] (raw LSB counts). Returns false on CRC error.
 */
bool ads131m08_parse_frame(ads131m08_t *dev, int32_t out[ADS_NCH]);
static inline float ads131m08_lsb_to_volts(int32_t raw) { return (float)raw * ADS_LSB_V; }

#ifdef __cplusplus
}
#endif
#endif /* ADS131M08_H */

/**
 * @file ads131m08.c
 * @brief ADS131M08 driver — platform-independent part (HAL via function pointers in ads131m08_hal_t).
 */
#include "ads131m08.h"
#include "../App/frames.h"   /* frm_crc16_ccitt */
#include <string.h>

static void put_word(uint8_t *p, uint16_t cmd) { p[0] = (uint8_t)(cmd >> 8); p[1] = (uint8_t)cmd; p[2] = 0; }
static uint16_t get_word16(const uint8_t *p) { return (uint16_t)(((uint16_t)p[0] << 8) | p[1]); }

static int32_t sign_extend_24(const uint8_t *p)
{
    uint32_t v = ((uint32_t)p[0] << 16) | ((uint32_t)p[1] << 8) | p[2];
    if (v & 0x800000u) v |= 0xFF000000u;
    return (int32_t)v;
}

/* A command frame is as long as a data frame (device shifts out data while we shift in the command). The
 * CRC of our outgoing words is appended in the last word because RX_CRC_EN is set after init; during init
 * (RX CRC disabled by default) the device ignores it. */
static bool send_cmd_frame(ads131m08_t *dev, uint16_t cmd, uint16_t data_word, uint8_t *rx)
{
    uint8_t tx[ADS_FRAME_BYTES];
    memset(tx, 0, sizeof tx);
    put_word(tx, cmd);
    put_word(tx + ADS_WORD_BYTES, data_word);
    uint16_t crc = frm_crc16_ccitt(tx, (ADS_FRAME_WORDS - 1) * ADS_WORD_BYTES, 0xFFFF);
    put_word(tx + (ADS_FRAME_WORDS - 1) * ADS_WORD_BYTES, crc);
    dev->hal->cs(dev->hal, true);
    bool ok = dev->hal->xfer(dev->hal, tx, rx, ADS_FRAME_BYTES);
    dev->hal->cs(dev->hal, false);
    return ok;
}

bool ads131m08_read_reg(ads131m08_t *dev, uint8_t addr, uint16_t *value)
{
    uint8_t rx[ADS_FRAME_BYTES];
    if (!send_cmd_frame(dev, ADS_CMD_RREG(addr, 1), 0, rx)) return false;
    /* response to a command arrives in the NEXT frame */
    if (!send_cmd_frame(dev, ADS_CMD_NULL, 0, rx)) return false;
    *value = get_word16(rx);
    return true;
}

bool ads131m08_write_reg(ads131m08_t *dev, uint8_t addr, uint16_t value)
{
    uint8_t rx[ADS_FRAME_BYTES];
    if (!send_cmd_frame(dev, ADS_CMD_WREG(addr, 1), value, rx)) return false;
    if (!send_cmd_frame(dev, ADS_CMD_NULL, 0, rx)) return false;
    /* acknowledgement word: 0x4000 | addr<<7 | (n-1)  (per datasheet WREG response) — verify on bench */
    uint16_t ack = get_word16(rx);
    return (ack & 0xE000u) == 0x4000u;
}

bool ads131m08_init(ads131m08_t *dev, ads131m08_hal_t *hal)
{
    memset(dev, 0, sizeof *dev);
    dev->hal = hal;
    /* hardware reset: SYNC/RESET low >= 2048 CLKIN cycles (0.25 ms at 8.192 MHz); we hold 20 ms, then wait 5 ms */
    hal->reset(hal, true);  hal->delay_ms(20);
    hal->reset(hal, false); hal->delay_ms(5);

    uint16_t id = 0;
    if (!ads131m08_read_reg(dev, ADS_REG_ID, &id)) return false;
    if ((id >> 8) != 0x24u) return false;      /* CHANCNT nibble = 8 -> expect 0x24xx; verify */

    uint16_t mode = ADS_MODE_WLEN_24 | ADS_MODE_TIMEOUT | ADS_MODE_DRDY_SEL_MOST_LAGGING | ADS_MODE_RX_CRC_EN;
    if (!ads131m08_write_reg(dev, ADS_REG_MODE, mode)) return false;

    uint16_t clock = ADS_CLOCK_CH_EN_ALL | ADS_CLOCK_OSR_512 | ADS_CLOCK_PWR_HR;   /* 8 kSPS, high resolution */
    if (!ads131m08_write_reg(dev, ADS_REG_CLOCK, clock)) return false;

    if (!ads131m08_write_reg(dev, ADS_REG_GAIN1, 0x0000)) return false;             /* gain 1 on all */
    if (!ads131m08_write_reg(dev, ADS_REG_GAIN2, 0x0000)) return false;

    /* streaming TX frame: NULL command, zero data, then CRC of the 9 words so RX_CRC_EN is satisfied */
    memset(dev->tx_frame, 0, sizeof dev->tx_frame);
    uint16_t crc = frm_crc16_ccitt(dev->tx_frame, (ADS_FRAME_WORDS - 1) * ADS_WORD_BYTES, 0xFFFF);
    put_word(dev->tx_frame + (ADS_FRAME_WORDS - 1) * ADS_WORD_BYTES, crc);

    uint16_t rb = 0;
    if (!ads131m08_read_reg(dev, ADS_REG_CLOCK, &rb) || rb != clock) return false;
    return true;
}

bool ads131m08_start_frame_dma(ads131m08_t *dev)
{
    if (dev->busy) return false;
    dev->busy = true;
    dev->hal->cs(dev->hal, true);
    if (!dev->hal->xfer_dma(dev->hal, dev->tx_frame, dev->rx_frame, ADS_FRAME_BYTES)) { dev->busy = false; dev->hal->cs(dev->hal, false); return false; }
    return true;
}

bool ads131m08_parse_frame(ads131m08_t *dev, int32_t out[ADS_NCH])
{
    dev->hal->cs(dev->hal, false);
    dev->busy = false;
    dev->frames++;
    const uint8_t *f = dev->rx_frame;
    uint16_t crc_rx = get_word16(f + (ADS_FRAME_WORDS - 1) * ADS_WORD_BYTES);
    uint16_t crc_calc = frm_crc16_ccitt(f, (ADS_FRAME_WORDS - 1) * ADS_WORD_BYTES, 0xFFFF);
    if (crc_rx != crc_calc) { dev->crc_errors++; return false; }
    dev->last_status = get_word16(f);
    for (int ch = 0; ch < ADS_NCH; ch++) out[ch] = sign_extend_24(f + (1 + ch) * ADS_WORD_BYTES);
    return true;
}

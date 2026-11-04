# `stm32-wim-daq` — Lane Data-Acquisition Firmware (STM32H743, FreeRTOS)

**Status: written, NOT compiled.** The authoring environment (Windows 11) had no Arm GNU toolchain, no STM32CubeIDE and
no host C compiler (`gcc`, `clang`, `cl`, `zig` all absent), so neither the firmware nor `host_test/` has been built or
run. The code is written to be buildable as-is once the dependencies in §3 are present; expect the usual first-build
corrections (header paths, HAL version differences) and read §9 before trusting any register constant.

This README is also the firmware-architecture deliverable (MP §10 item 12; `hardware-architecture.md` §6).

---

## 1. What it does

16 analog channels (two ADS131M08) at 8 kSPS each, hardware-timestamped, processed in real time into axle events and
pass summaries, plus sensor health, over CAN-FD (primary) and UDP (secondary). It is the embedded mirror of the Python
reference `packages/wim_dsp/kifaru_wim_dsp/pipeline.py`; the gateway (`edge/gateway`) consumes its frames.

```
 ADS131M08 A (P1L P1R P2L P2R P3L P3R BPL BPR)  ─SPI1+DMA─┐           ┌─> FDCAN1 (CAN-FD 500k/2M) ─> gateway
 ADS131M08 B (EXC, AFE temp, spares, rail mon)  ─SPI2+DMA─┤ DRDY EXTI │
                                                          v           │
 ┌──────────┐  blocks   ┌────────────┐  frames  ┌──────────────┐      │
 │ acq_task │ ────────> │detect_task │ ───────> │  comms_task  │ ─────┤
 └──────────┘ 16×16 s   └────────────┘          └──────────────┘      └─> UDP 5010 (lwIP netconn, optional)
       ^                      ^      \ idle stats         ^
  TIM2 CH2 DRDY capture   loop/IR EXTI  \                 │ HEALTH every 10 s
  TIM2 CH1 GPS PPS           (1 µs)      └> health_task ──┘   + AFE reset relay decision
  TIME_SYNC (CAN/UDP) ─> timebase.c ─> UTC µs on every frame
 ESP32 aux (FDCAN2, classic CAN) ─ENV─> pavement temperature cache + forwarded ENV frame
 wdg_task: IWDG 2 s, refreshed only when acq+detect+health+comms all checked in within the last second
```

## 2. Directory layout

```
firmware/stm32-wim-daq/
├── CMakeLists.txt                  CMake project (STM32 HAL + FreeRTOS; options KIFARU_RIG, WITH_LWIP)
├── cmake/arm-gcc-toolchain.cmake   arm-none-eabi toolchain file
├── STM32H743ZITX_FLASH.ld          linker script (AXI SRAM for DMA-reachable .bss, DTCM for stack)
├── Core/Inc/FreeRTOSConfig.h       kernel configuration (1 kHz tick, 8 priorities, 96 KB heap_4)
├── Core/Src/main.c                 clocks (480 MHz), GPIO/SPI/DMA/FDCAN/UART/IWDG init, task creation
├── Core/Src/stm32h7xx_it.c         ISRs: DRDY (EXTI13), loops (EXTI0-2), IR (EXTI3-6), DMA, SPI, FDCAN, TIM2
├── App/app_config.h                channel map, geometry (lane / rig), AFE scale factors, thresholds, RTOS params
├── App/wim_dsp.[ch]                PORTABLE DSP: biquads, median, pulse detector, integral load, fusion, health
├── App/frames.[ch]                 PORTABLE wire codec: payloads, CRC-32 / CRC-16, UDP framing
├── App/timebase.[ch]               TIM2 64-bit µs clock, PPS + DRDY capture, UTC offset from TIME_SYNC
├── App/acq_task.c                  ADS131M08 ×2 via SPI+DMA, DRDY-driven, 16-sample blocks
├── App/detect_task.c               pass state machine, baseline, filter, pulses, fusion, AXLE_EVENT/PASS_SUMMARY
├── App/health_task.c               noise RMS, saturation, dead/drift/50 Hz hum, IR stuck, AFE reset
├── App/comms_task.c                CAN-FD + UDP TX, TIME_SYNC/ENV RX, heartbeat
├── App/tasks.h                     queues, shared types, task prototypes
├── Drivers/ads131m08.[ch]          register map, commands, init (OSR 512 -> 8 kSPS), DMA frame, CRC check
├── Drivers/loop_detector.[ch]      debounced presence edges, vehicle length
├── Drivers/ir_beam.[ch]            beam edges, glitch rejection, stuck detection, tyre width
└── host_test/                      plain-C unit test of wim_dsp + frames (any compiler), CMake, make_frame.py
```

Files that must be **copied from vendor packages** (not in the repo, standard practice): `Core/Src/system_stm32h7xx.c`
and `Core/Src/startup_stm32h743xx.s` from `STM32CubeH7/Drivers/CMSIS/Device/ST/STM32H7xx/Source/Templates/`,
`Core/Inc/stm32h7xx_hal_conf.h` from the HAL template (enable HAL modules: GPIO, DMA, SPI, FDCAN, TIM, UART, IWDG,
PWR, RCC, CORTEX, FLASH), and, when `WITH_LWIP=ON`, a CubeMX-generated `LWIP/` + `Middlewares/Third_Party/LwIP` with
`ethernetif.c` for the LAN8742 PHY (RMII) and `LWIP_SO_RCVTIMEO 1`, `LWIP_NETCONN 1`.

## 3. Build (not performed here)

Requirements: CMake ≥ 3.22, Ninja, Arm GNU Toolchain 12+ (`arm-none-eabi-gcc`), STM32CubeH7 (HAL v1.11+) and
FreeRTOS-Kernel (V10.5+ or V11) checked out under `third_party/` (or point `STM32_HAL_DIR`, `CMSIS_*_DIR`,
`FREERTOS_DIR` elsewhere).

```powershell
git clone --depth 1 https://github.com/STMicroelectronics/STM32CubeH7 third_party/STM32CubeH7
git clone --depth 1 --branch V11.1.0 https://github.com/FreeRTOS/FreeRTOS-Kernel third_party/FreeRTOS-Kernel
# copy the three template files listed above into Core/
cmake -B build -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/arm-gcc-toolchain.cmake -DCMAKE_BUILD_TYPE=Release
cmake --build build                      # -> build/kifaru_wim_daq.elf/.hex/.bin
# lab rig geometry:   add -DKIFARU_RIG=ON
# Ethernet/UDP path:  add -DWITH_LWIP=ON (after generating the LwIP middleware with CubeMX)
```

Flash with STM32CubeProgrammer or `openocd -f board/st_nucleo_h743zi.cfg -c "program build/kifaru_wim_daq.elf verify reset exit"`.

Host test (any C compiler):

```powershell
cd host_test
gcc -std=c11 -O2 -DHOST_TEST -I../App -o test_wim_dsp test_wim_dsp.c ../App/wim_dsp.c ../App/frames.c -lm
./test_wim_dsp          # exit code = number of failed checks
# or: cmake -B build && cmake --build build && ctest --test-dir build
```

## 4. Task design

| Task | Priority | Stack | Period / trigger | Responsibility |
|---|---|---|---|---|
| `acq_task` | 6 | 1 KB | DRDY (8 kHz) via DMA-complete notification | parse 2 frames, CRC check, assemble 16-sample blocks (2 ms), queue (depth 8 = 16 ms of slack) |
| `detect_task` | 5 | 4 KB | each block | per-row kg scaling (L+R, ratiometric for BP), IIR LP, idle ring + stats, pass state machine, pulse detection, fusion, frame emission |
| `comms_task` | 4 | 2 KB | queue / 1 s heartbeat | CAN-FD TX with DLC padding, UDP TX, heartbeat |
| `comms_rx_task` | 4 | 2 KB | UDP RX | TIME_SYNC from gateway |
| `health_task` | 3 | 2 KB | 1 s / 10 s | HEALTH frames, IR stuck poll, AFE reset decision |
| `wdg_task` | 2 | 256 B | 500 ms | IWDG refresh if all tasks checked in |

CPU budget (C): per sample per row: 2 biquads (10 MAC) + detector (~10 ops) + stats (~10) ≈ 40 flops × 4 rows × 8 kHz ≈
1.3 MFLOP/s; the H743 FPU does > 100 MFLOP/s at 480 MHz — < 2 % load. The pass-end fusion runs once per vehicle
(< 50 µs). The 0.2 s median at pass start is a quickselect over 1600 floats × 4 rows ≈ 50 µs. Memory: ring buffers
4 × 1600 × 4 B = 25.6 KB; block queue 8 × 1 KB; comms queue 32 × 138 B.

ISR priorities (NVIC, 4 bits): TIM2 capture 4 (above `configMAX_SYSCALL_INTERRUPT_PRIORITY` = 5, so it never calls
RTOS APIs — it only writes the time base), DRDY/DMA/SPI 5, loops/IR 6, FDCAN 7. All ISRs are short; the DRDY ISR
only starts two DMA transfers.

## 5. DSP pipeline (mirror of `pipeline.py`)

| Python | Firmware | Note |
|---|---|---|
| `remove_baseline` (median of 0.2 s pre-trigger) | ring buffer + `wim_median` at pass start | same statistic |
| `lowpass` 4th-order Butterworth 1 kHz, `sosfiltfilt` | `wim_lp4_step`, two biquads causal | coefficients: b0=0.010209480791, b1=0.020418961582, b2=b0, a1=−0.855397932775, a2=0.209715357757 ; b=[1,2,1], a1=−1.113029854163, a2=0.574061915084 (scipy `butter(4, 0.25, output='sos')`); causal single pass → 0.5 ms group delay, identical on all rows, hence no effect on speed or integrals |
| `(x − offset)·gain / (1 + α(T − T_ref))` | `wim_apply_cal` | per row (the API stores per sensor; L and R share the row calibration — documented simplification) |
| `detect_pulses` threshold 800 kg, 50 % hysteresis, 30 ms merge | `wim_pulse_det_step` streaming, emits 30 ms after pulse end | merge keeps the larger peak and the later end |
| `pulse_load` = ∫x·π/(2T), T = L_contact/v | `wim_pulse_load_kg` + droop correction (1 + T/2τ), τ = R_f C_f = 3.3 s | droop term is new (analog effect absent in the synthetic model) |
| consensus axle count (mode), speed from outermost good piezo rows, spacings, 3:1 plate weighting, Type A/B, k=2, grouping at 2.0 m, flags | `wim_fuse_pass` | same formulas; `class_code` is derived by the gateway from `axle_count` |
| `channel_health` | `wim_row_health` + `health_task` idle statistics | adds 50 Hz hum, drift, saturation run-length, IR stuck, time-unsynced |

Trigger: a pass starts when any row exceeds 800 kg-eq above its idle baseline **or** loop L1 becomes occupied (lane
build). It ends 300 ms after the last pulse once L3 has cleared, or 2 s after the last pulse, or after 20 s.

## 6. ADS131M08 configuration

CLKIN 8.192 MHz external oscillator (shared), `CLOCK = 0xFF0A` (all channels, OSR 512, high-resolution) → 8000 SPS;
`MODE = 0x1510` (24-bit words, RX CRC enabled, timeout on, DRDY most-lagging); PGA gain 1 on all channels; frame =
STATUS + 8 × 24-bit + CRC-16/CCITT (init 0xFFFF). The SPI runs mode 1 (CPOL 0 / CPHA 1), 8-bit transfers, ~10 MHz.
Both devices share SYNC/RESET so their conversions are aligned; DRDY of device A triggers both reads (B's DRDY is
within a CLKIN period). A frame with a bad CRC is replaced by the previous sample and counted (`crc_err_mask` in the
block, surfaced in HEALTH).

## 7. Frames and transports

Byte layouts: `docs/03-hardware/communications.md` §1–2 (implemented in `App/frames.c`, tested by `host_test` and by the
gateway's `tests/test_frames.py`). CAN-FD IDs `0x100 + 0x20·lane + type`; PASS_SUMMARY on CAN carries the fixed 38
bytes (axles arrive as AXLE_EVENTs), on UDP the full record. HEALTH for 16 channels is split into two CAN frames.
TIME_SYNC arrives from the gateway on CAN `0x187` or UDP 5011 and anchors the TIM2 PPS capture to UTC.

## 8. Bench verification plan (to be executed on Nucleo-H743ZI2 + ADS131M08EVM)

1. DRDY period 125.0 µs ± 25 ppm on a scope; ID register read 0x24xx; CLOCK read-back 0xFF0A.
2. Shorted inputs: noise < 20 LSB_rms per channel (ADC alone) — compare with the datasheet noise table.
3. Signal generator half-sine (2.5 ms, 0.5 V) into one channel: AXLE_EVENT appears on CAN with a load equal to
   0.5 V / 0.1338 mV/kg ≈ 3737 kg-eq × π/2 scaling, UDP frame CRC validates in the gateway, latency < 50 ms after the pulse.
4. Two channels with a 150 ms delayed copy → speed 20.00 m/s ± 0.05.
5. Pull the ADC clock → DRDY timeout fault logged within 10 ms, HEARTBEAT continues, IWDG does not fire.
6. Stop the detect task in the debugger → IWDG reset within 2 s.
7. PPS from a GPS module on PA0 + TIME_SYNC from the gateway → `t_us` of a loop edge agrees with the gateway's
   timestamp of the same edge (second input) within 100 µs.

## 9. Known uncertainties to verify on first build/bench

* ADS131M08 register bit positions and command encodings (`Drivers/ads131m08.h`) — re-check against the datasheet
  revision in hand; the WREG acknowledgement mask `0x4000` and the ID `0x24xx` in particular.
* ADS131M08 noise at OSR 512 (we assumed ~10 µV_RMS); the attenuator value may be revisited after the measurement.
* SPI kernel clock source/prescaler for ~10 MHz SCLK (main.c `spi_common`); the HAL macro names for PLL ranges.
* FDCAN bit timing assumes a 48 MHz kernel clock (PLL1Q); verify with the actual RCC configuration.
* FDCAN2 pin assignment conflicts with SPI1_MOSI on the Nucleo (PB5); use the final PCB pin-out or a Nucleo jumper table.
* VOS0/480 MHz requires STM32H743 revision V silicon; use 400 MHz (VOS1) on rev Y.
* DMA buffers must not be in DTCM (linker script puts `.bss` in AXI SRAM — keep it that way) and D-cache must be
  handled: the SPI DMA buffers are 30-byte statics; either place them in a non-cacheable MPU region or add
  `SCB_InvalidateDCache_by_Addr` after RX / `SCB_CleanDCache_by_Addr` before TX in `acq_task.c` (not yet added).
* lwIP netconn API requires `LWIP_NETCONN` and `LWIP_SO_RCVTIMEO`.
* FreeRTOS port folder name (`ARM_CM7/r0p1`) for the kernel version used.

# KIFARU PORTOS — Hardware and Electronics Architecture (overview)

Detailed designs, calculations and simulation instructions live in `docs/03-hardware/`. This page fixes the architecture.

## 1. Lane layout (high-speed WIM pre-screen lane, one direction)

```
 traffic -->
 +------+--------+--------+--------+----------+--------+------+
 | Loop | Piezo  | Piezo  | Bending|  Loop    | Piezo  | Loop |   pavement
 |  L1  | row P1 | row P2 | plate  |   L2     | row P3 |  L3  |   (sensors flush)
 +--+---+---+----+---+----+---+----+----+-----+---+----+--+---+
    0 m    4 m      7 m     10 m      12 m      16 m    19 m
  ^ ANPR camera (front plate) at ~25 m before P1; rear-plate camera after L3
  ^ UHF RFID reader gantry at ~15 m before P1; radar speed sensor on gantry
  ^ IR beam pairs at P1 and P3 (wheel/axle count cross-check, tyre position)
  ^ Pavement temperature probe embedded at P2; ambient T/RH on cabinet
  ^ Roadside cabinet (IP66) within 30 m: DAQ, gateway, power, surge, comms
```

Two piezo rows (P1, P2, 3 m apart) give axle speed (v = dx / dt) and axle spacing; the bending plate gives a lower-noise
reference load per axle; P3 provides a third sample for averaging the dynamic (bouncing) component. Loops give presence and
vehicle length; the combination yields classification. This mirrors standard ASTM E1318 Type-I/II lane practice; the
bending plate is what makes a ±5 % GVM target credible. Piezo-polymer alone is typically ±10–15 %.

## 2. Hardware block diagram

```
 +--------------- Roadside sensors ----------------+      +---------- Cabinet ------------------------------------------+
 | Piezo-quartz strips x3 rows (charge output)     |----->| Charge amps (x6) -> AA filters -> ADS131M08 x2 (24-bit)     |
 | Bending plate (full-bridge strain, 2 halves)    |----->| Bridge excitation + INA -> AA filter -> ADS131M08           |
 | Inductive loops x3                              |----->| Loop detector cards (TTL presence) -> STM32 GPIO/EXTI       |
 | IR beam pairs x2                                |----->| Opto-isolated inputs -> STM32 EXTI (timestamped)            |
 | Radar speed sensor (RS-485)                     |----->| STM32 UART (RS-485)                                         |
 | Pavement temp (PT1000), ambient T/RH (SHT4x)    |----->| ESP32 aux node -> CAN                                       |
 | ANPR cameras x2 (PoE, H.264/ONVIF)              |----->| PoE switch -> Edge gateway (IPC): OCR                       |
 | UHF RFID reader (PoE, LLRP)                     |----->| PoE switch -> Edge gateway                                  |
 +-------------------------------------------------+      | STM32H743 DAQ - CAN/Ethernet -> Edge gateway (IPC)          |
                                                          | Edge gateway -> LTE/fibre router -> cloud (MQTT mTLS)       |
                                                          | VMS / lane signal driver (relay + RS-485)                   |
                                                          | Power: 230 V -> surge -> 24 V PSU -> UPS/LiFePO4 -> rails   |
                                                          +-------------------------------------------------------------+
```

## 3. Signal chain summary (full derivations in `docs/03-hardware/analog-front-end.md`)

| Stage | Choice | Headline numbers |
|---|---|---|
| Piezo sensor | Piezo-quartz WIM strip (Kistler Lineas-class), charge output about 1.8 pC/N typical | 10 t axle, 0.1 s dwell: about 90 nC peak |
| Charge amplifier | Op-amp integrator, C_f = 22 nF gives 45 mV/nC, R_f sets LF cut-off about 0.05 Hz | about 4 V peak at 10 t, 5 V headroom |
| Bending plate | 350 ohm full bridge, 2 mV/V, 5 V excitation | 10 mV full scale; INA gain 200 gives 2 V full scale |
| Anti-alias | 4th-order Butterworth (two Sallen-Key stages), f_c = 1 kHz | at least −48 dB at the 4 kHz Nyquist frequency for 8 kSPS |
| ADC | ADS131M08, 8 channels simultaneous, 24-bit delta-sigma, 8 kSPS/ch | ENOB about 18 bits at this rate; LSB about 0.3 µV at ±2.4 V |
| MCU | STM32H743 (480 MHz, DMA, 2x SPI, CAN-FD, Ethernet) | ample for 16 ch x 8 kSPS = 128 kS/s DSP |
| Timing | 1 µs timestamp counter, GPS PPS discipline on gateway | speed error from timing far below 0.1 % |

## 4. Why not HX711

The HX711 is a 24-bit delta-sigma ADC for static scales: maximum 80 SPS, single multiplexed channel, no simultaneous sampling.
A tyre crosses a 50 mm piezo strip at 80 km/h in about 2–3 ms; at 80 SPS you get at most one sample per axle, which cannot
reconstruct the load pulse. It is explicitly excluded from the lane (WIM-03) and permitted only on the laboratory bench rig
for static tare checks.

## 5. Laboratory-scale demonstration rig (Phase 6)

A 1:10 moving-platform rig: a 2 m linear rail with a motorised carriage carrying a two- or three-axle model truck, running over
a row of thin-film piezo (PVDF) strips and a small bending plate built from a 3 mm aluminium bar with foil strain gauges.
It demonstrates axle detection, spacing, speed, dynamic load pulses and calibration against a reference bench scale.
**It is a demonstration of signal-processing principles, not a certified WIM instrument** (OIML R134 / ASTM E1318 certification
requires full-scale installation and type approval).

## 6. Deliverable map (MP §10)

| # | Deliverable | Location |
|---|---|---|
| 1 | Block diagram | this document §2 |
| 2 | Sensor architecture | §1, `docs/03-hardware/sensor-architecture.md` |
| 3–6 | AFE schematic, charge amp, filters, ADC interface | `docs/03-hardware/analog-front-end.md` |
| 7–9 | Power, surge, grounding/shielding | `docs/03-hardware/power-and-protection.md` |
| 10 | Enclosure | `docs/03-hardware/enclosure-and-installation.md` |
| 11 | Comms interfaces | `docs/03-hardware/communications.md` |
| 12 | Firmware architecture | `firmware/stm32-wim-daq/README.md` |
| 13 | Calibration procedure | `docs/03-hardware/calibration-procedure.md` |
| 14 | Prototype build guide | `docs/03-hardware/lab-rig-build-guide.md` |
| 15 | Component selection | `docs/03-hardware/bom.md` |

# Bill of Materials — One High-Speed WIM Lane (HW-15)

Prices are **indicative estimates** (USD, Q4 2026 distributor list pricing from memory; KES at an assumed 130 KES/USD)
and must be re-quoted. Part numbers marked (D) are specific orderable parts the design depends on; items marked (A) are
class descriptions where the exact vendor/model is a procurement choice. Quantities are per lane; "spare" rows are
recommended site spares.

**HX711 is explicitly excluded from the lane (WIM-03).** It is a single-channel, 10/80 SPS static-scale ADC and cannot
sample a 12–37 ms load pulse; it appears only on the laboratory bench for static tare checks (`lab-rig-build-guide.md`).

---

## 1. Road sensors

| # | Item | Part / class | Qty | Est. USD each | Justification / alternative |
|---|---|---|---|---|---|
| 1.1 | Piezo-quartz WIM strip, 1.75 m, 50 mm, with 30 m low-noise cable | Kistler Lineas 9195G-class (A: exact model/length per vendor quote) | 6 (+1 spare) | 3 500 | Quartz: low tempco, linear, long life; 2 per row × 3 rows. Alt: polymer piezo cable (Roadtrax BL-class) at ~1/5 the price but ±10–15 % and strong tempco — acceptable only as a degraded fallback |
| 1.2 | Epoxy grout + primer for 6 strips | vendor-specified (A) | 60 L | 60/L | per `enclosure-and-installation.md` §3 |
| 1.3 | Bending-plate WIM scale, 2 half-plates 1.75 × 0.5 m, 350 Ω full bridges, 2 mV/V, frames | established WIM vendor (A) | 1 set | 18 000 | Lower-noise load reference, weighted 3:1 in fusion; alt: a second quartz row (cheaper, but then no independent sensor technology) |
| 1.4 | Inductive loop wire 1.5 mm² XLPE | | 120 m | 0.8/m | 3 loops × (3 turns × 8 m + 10 m lead) |
| 1.5 | Loop sealant | hot-pour, 2 cartons | 2 | 90 | |
| 1.6 | Loop detector card, 2-channel, TTL + relay out | A: standard traffic-detector class | 2 | 180 | 3 loops; alt: 4-channel single card |
| 1.7 | IR through-beam/retro-reflective sensor, 24 V PNP, modulated, 4 m range | Sick/Banner/Omron class (A) | 4 (+1) | 90 | axle-count cross-check |
| 1.8 | Traffic radar speed sensor, 24 GHz, RS-485 | A | 1 | 450 | speed plausibility |
| 1.9 | ANPR-class IP camera, 1/1.8", IR, motorised 12–40 mm, PoE | Axis P1455-LE / Hikvision iDS-2CD7A26G0/P class (A) | 2 | 900 | front and rear plate |
| 1.10 | UHF RFID fixed reader, 4-port, LLRP, PoE+ | Impinj R700 / Zebra FX9600 class (A) | 1 | 1 600 | ISO 18000-63 |
| 1.11 | UHF RFID antenna, 9 dBic circular, IP67 | A | 2 | 180 | |
| 1.12 | PT1000 Class A probe, 4-wire, stainless, 10 m cable | Heraeus/Omega class (A) | 1 (+1) | 60 | pavement temperature |
| 1.13 | Ambient T/RH sensor | Sensirion SHT40-AD1B (D) on a breakout, in a radiation shield | 2 | 8 | outside + inside cabinet |
| 1.14 | Low-noise coax, armoured duct, pull cords | | lot | 400 | |

## 2. DAQ board (STM32H743 + 2× ADS131M08 + AFE), one custom 4-layer PCB set

| # | Item | Part | Qty | Est. USD each | Justification / alternative |
|---|---|---|---|---|---|
| 2.1 | MCU | STM32H743ZIT6 (D) | 1 | 14 | 480 MHz Cortex-M7, 2 MB flash, 1 MB RAM, FDCAN, Ethernet MAC, 6 SPI, DMA — the pipeline needs ~128 kS/s × ~60 ops = 8 MOPS, < 5 % of one core. Alt: STM32H723ZGT6 (cheaper, 550 MHz, less RAM) |
| 2.2 | 24-bit 8-ch simultaneous ΔΣ ADC | ADS131M08IPBSR (D) | 2 (+1) | 12 | 8 kSPS/ch, CRC, PGA; alt: ADS131M04 ×4 (4-ch) or AD7771 (ADI, 8-ch) |
| 2.3 | 8.192 MHz oscillator 3.3 V ±25 ppm | SiT8008 / ASE class (A) | 1 | 1.5 | ADC CLKIN |
| 2.4 | Charge-amp / filter op-amp, dual JFET | OPA2140AIDR (D) | 11 (+4) | 6 | 6 charge amps + 16 filter stages = 22 op-amps; 5.1 nV/√Hz, 10 pA max I_b. Alt: ADA4610-2ARZ, OPA1642AIDR |
| 2.5 | Instrumentation amplifier | INA828IDR (D) | 2 (+2) | 4 | bending plate, G = 101 with R_G 499 Ω; alt: INA333 (lower power, slower), AD8422 |
| 2.6 | Precision reference 5.000 V | REF5050AIDR (D) | 1 | 4 | bridge excitation |
| 2.7 | Excitation buffer op-amp | OPA2991IDR (D) | 1 | 1.5 | 14 mA per bridge |
| 2.8 | Feedback capacitor 22 nF C0G 50 V 1206 ±5 % | Murata GRM31C5C1H223JA01-class (A) | 8 | 0.6 | charge amp C_f |
| 2.9 | High-ohmic resistor 150 MΩ, 1 %, 1206/2010 | Ohmite HVC / Vishay MOX class (A) | 8 | 2 | R_f |
| 2.10 | Reed relay, SPST, 5 V coil | Coto 9007-05-00 (D) | 8 | 4 | charge-amp reset (pA leakage); alt: 2N4117A JFET |
| 2.11 | Low-leakage dual diode | BAV199 (D) | 16 | 0.2 | input clamps |
| 2.12 | Series protection resistor 4.7 kΩ 0.5 W pulse-rated thick film | | 16 | 0.1 | |
| 2.13 | Filter capacitors 10 nF / 12 nF / 68 nF C0G ±5 % | Murata/TDK class | 16 / 8 / 8 | 0.3–1.2 | Sallen-Key |
| 2.14 | Filter resistors 14.3 kΩ / 6.04 kΩ 0.1 % 25 ppm | Vishay TNPW class | 16 / 16 | 0.15 | |
| 2.15 | Attenuator resistors 10.0 kΩ / 2.00 kΩ 0.1 % | | 8 / 8 | 0.15 | |
| 2.16 | Analog LDO 3.3 V for ADC AVDD | TPS7A2033PDBVR (D) | 2 | 1 | low noise |
| 2.17 | ±12 V LDOs | TPS7A4901DGNR (+), TPS7A3001DGNR (−) (D) | 1 + 1 | 3 | |
| 2.18 | Isolated DC-DC 24 → ±15 V 10 W | Traco TEN 10-2423 (D class) | 1 | 35 | analog rails |
| 2.19 | Buck 24 → 5 V 3 A | Traco TSR 3-2450 (D) | 1 | 12 | |
| 2.20 | Buck 5 → 3.3 V digital | TPS62912 (D) or TLV62569 | 1 | 1.5 | |
| 2.21 | CAN-FD isolated transceiver | ISO1042BDWR (D) | 1 (+1) | 4 | 5 kV isolation, 5 Mbit/s |
| 2.22 | Isolated 5 V for the CAN side | SN6505B + transformer or Murata NXE1 class | 1 | 4 | |
| 2.23 | Ethernet PHY | LAN8742A-CZ-TR (D) | 1 | 2 | RMII to STM32 ETH |
| 2.24 | RJ45 with magnetics | HanRun HR911105A class | 1 | 2 | |
| 2.25 | RS-485 isolated transceiver | ISO3082DW (D) | 2 | 6 | radar, VMS |
| 2.26 | Optocouplers for IR/loop inputs | TLP291(GB) (D) | 8 | 0.3 | |
| 2.27 | Board temperature sensor | LMT87LP (D) | 1 | 0.6 | |
| 2.28 | 25 MHz crystal (MCU), 32.768 kHz, SWD header, decoupling, connectors (SMA/BNC × 6, pluggable terminals) | | lot | 40 | |
| 2.29 | 4-layer PCB, 160 × 100 mm, ENIG, 5 pcs | JLC/PCBWay class | 1 lot | 120 | |
| 2.30 | Assembly | | 1 | 200 | |
| 2.31 | GDT 90 V SMD, 1 pF | Bourns 2027-09-SM (D) | 12 | 1 | at the entry panel adaptor board |
| 2.32 | Shielded sub-enclosure for the DAQ/AFE | Hammond 1455-class extruded or sheet steel | 1 | 45 | |

Development-stage substitute for 2.1/2.2: **STM32 Nucleo-H743ZI2 + ADS131M08EVM** (≈ USD 30 + 175) — the same firmware.

## 3. Auxiliary node

| # | Item | Part | Qty | Est. USD each | Justification |
|---|---|---|---|---|---|
| 3.1 | ESP32 module | ESP32-WROOM-32E-N8 (D) or ESP32-S3-WROOM-1 | 1 | 4 | TWAI (CAN), Wi-Fi fallback, I2C, SPI |
| 3.2 | RTD-to-digital | MAX31865ATP+ (D), R_REF 4.3 kΩ 0.1 % | 1 | 6 | PT1000 4-wire |
| 3.3 | CAN transceiver 3.3 V | SN65HVD230DR (D) or TJA1051T/3 | 1 | 1.5 | classic CAN on the FD bus (FD frames tolerated? no — see `communications.md` §1.8: the DAQ transmits CAN-FD frames; the ESP32 node must be on a classic-CAN segment or the DAQ must send its ESP32-bound traffic as classic frames. Design choice: the ESP32 only transmits; its controller will flag FD frames as errors unless FD-passive. Use a separate 500 kbit/s classic CAN segment on the DAQ's FDCAN2 for the aux node) |
| 3.4 | SHT40 breakout ×2, door switch, 24 V inputs (AC-fail, batt-low, SPD fault) with TLP291 | | lot | 20 | |
| 3.5 | Custom 2-layer PCB + 24 → 5 V buck (TSR 1-2450) | | 1 | 40 | |

## 4. Cabinet, power, protection

| # | Item | Part / class | Qty | Est. USD each | Justification |
|---|---|---|---|---|---|
| 4.1 | IP66 cabinet 800×600×300, 316L or C5-M coated, double-skin sun shield, plinth | Rittal AE/CS-class or local fabrication (A) | 1 | 900 | |
| 4.2 | SPD Type 1+2, 1P+N | Phoenix VAL-MS-T1/T2 335/12.5/1+1 class (A) | 1 | 220 | gantry with LPS |
| 4.3 | SPD Type 3 at PSU | Phoenix PLT-SEC-T3 class (A) | 1 | 60 | coordination |
| 4.4 | MCB 16 A C, RCD 30 mA type A, isolator | | 1 set | 60 | |
| 4.5 | EMI filter 6 A | Schaffner FN2030-6 (D) | 1 | 30 | |
| 4.6 | 24 V 240 W PSU with UPS/charger function | Mean Well DRS-240-24 class (A) | 1 | 190 | |
| 4.7 | LiFePO4 battery 24 V (8S) 50 Ah with BMS, 1280 Wh | A | 1 | 550 | 8 h at 120 W |
| 4.8 | 24 → 48 V 150 W for PoE | Mean Well SD-150B-48 class (A) | 1 | 70 | |
| 4.9 | Electronic fuses 24 V, 6 channels | Phoenix CBMC E4 24DC/1-10A class (A) | 1 | 160 | |
| 4.10 | Signal SPDs: 2-wire RS-485/24 V | Phoenix PT-IQ-2X2 / DEHN BXT class (A) | 6 | 70 | loops, plate, IR, radar, VMS |
| 4.11 | PoE++ surge protectors Cat6A | Ubiquiti ETH-SP-G2 / DEHN class (A) | 6 | 25 | 3 runs × 2 ends |
| 4.12 | Coax SPD for GPS | | 1 | 40 | |
| 4.13 | Earth bar, 25/16/50 mm² conductors, electrode rods, clamps | | lot | 250 | |
| 4.14 | Anti-condensation heater 50 W + hygrostat, circulation fan 24 V, pressure vent | Stego class (A) | 1 set | 120 | |
| 4.15 | Field-cable entry panel with EMC glands | | 1 | 150 | |

## 5. Edge computing and network

| # | Item | Part / class | Qty | Est. USD each | Justification |
|---|---|---|---|---|---|
| 5.1 | Fanless industrial PC, Intel Core i5 / Ryzen class, 16 GB, 512 GB NVMe, 2× LAN, TPM 2.0, 12–24 V | Advantech/OnLogic class (A) | 1 | 1 100 | gateway + OCR; Linux |
| 5.2 | Industrial PoE+ managed switch, 8 ports, 48 V input | A | 1 | 350 | |
| 5.3 | LTE Cat-6 industrial router with dual SIM, GNSS | Teltonika RUTX11 class (A) | 1 | 300 | |
| 5.4 | GNSS timing receiver with PPS output + antenna | u-blox NEO-M8T/ZED-F9T class (A) | 1 | 120 | |
| 5.5 | USB-CAN-FD adapter (if the IPC has no CAN) | PEAK PCAN-USB FD class | 1 | 250 | |
| 5.6 | VMS (full-matrix LED, RS-485 Modbus) + lane signal head | A | 1 + 1 | 2 500 + 400 | |
| 5.7 | Cables Cat6A S/FTP outdoor, 24 V/RS-485 shielded, ducts | | lot | 600 | |

## 6. Excluded / not permitted on the lane

| Item | Reason |
|---|---|
| **HX711** | 10/80 SPS single-channel static-scale ADC — cannot resolve a 12–37 ms load pulse (WIM-02/03). Bench static tare checks only. |
| Polymer piezo cable as the primary load sensor | ±10–15 % class, strong temperature dependence (A) — allowed only as a degraded fallback row |
| Filter fans | downgrade IP66 to IP54 in a salt/dust environment |
| VRLA batteries | life halves per +10 °C over 25 °C; cabinet runs at 40–48 °C |

## 7. Lane cost roll-up (estimate)

| Block | USD |
|---|---|
| Road sensors incl. bending plate (§1) | ≈ 48 000 |
| DAQ + AFE (§2) | ≈ 1 100 |
| Aux node (§3) | ≈ 100 |
| Cabinet, power, protection (§4) | ≈ 3 900 |
| Edge computing, network, VMS (§5) | ≈ 6 900 |
| Civil works (saw cuts, plate pit, ducts, gantry) — not estimated here | site quote |
| **Equipment total** | **≈ USD 60 000 (≈ KES 7.8 M), ± 30 %** |

The bending plate and quartz strips are ~80 % of the equipment cost; a piezo-only lane (no plate) saves ~USD 18 000
but, per the uncertainty budget, cannot credibly claim ±5 % GVM.

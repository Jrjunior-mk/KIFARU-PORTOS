# Sensor Architecture — High-Speed WIM Lane (Mariakani / Mombasa)

Status: design document (Phase 6 hardware). Nothing here has been measured on a real lane; every figure is either a
**datasheet-class value (D)**, a **calculation (C)** shown with its formula, or an **assumption (A)** to be confirmed.
Standards referred to by name: ASTM E1318 (WIM performance classes), OIML R134 (automatic instruments for weighing
road vehicles in motion), COST 323 (European WIM specification). Where a number is attributed to one of these it is
our reading of the standard and must be checked against the current edition before any certification claim.

Lane geometry, block diagram and the HX711 exclusion are fixed in `docs/02-architecture/hardware-architecture.md`.
This document specifies each sensor, why it is where it is, what signal it produces, how it fails and how the DAQ
detects that failure (WIM-01, WIM-07).

---

## 1. Lane layout and channel map

```
traffic -->   L1      P1      P2      BP      L2      P3      L3
position [m]  0.0     4.0     7.0    10.0    12.0    16.0    19.0
```

| Sensor | Position (m) | Channels | Signal type | Cabinet termination |
|---|---|---|---|---|
| Inductive loop L1 (entry presence) | 0.0 (2 m long) | 1 digital | Presence TTL from detector card | STM32 EXTI (timestamped) |
| Piezo-quartz row P1 (2 strips, one per wheel path) | 4.0 | 2 analog | Charge (pC) | Charge amp -> AA filter -> ADS131M08 #A ch0/ch1 |
| Piezo-quartz row P2 | 7.0 | 2 analog | Charge | ADS131M08 #A ch2/ch3 |
| Bending plate BP (2 half-plates, left/right) | 10.0 | 2 analog + 1 excitation monitor | mV/V strain bridge | INA -> AA filter -> ADS131M08 #A ch6/ch7; excitation on #B ch0 |
| Inductive loop L2 (over-plate presence) | 12.0 | 1 digital | Presence TTL | STM32 EXTI |
| Piezo-quartz row P3 | 16.0 | 2 analog | Charge | ADS131M08 #A ch4/ch5 |
| Inductive loop L3 (exit presence / length) | 19.0 | 1 digital | Presence TTL | STM32 EXTI |
| IR beam pairs (at P1 and P3, 2 beams each at 150 mm and 450 mm height) | 4.0 / 16.0 | 4 digital | Opto-isolated 24 V | STM32 EXTI |
| Radar speed sensor (gantry, -15 m) | -15 | serial | RS-485 ASCII/Modbus | STM32 UART4 |
| ANPR cameras x2 (front at -25 m, rear after L3) | -25 / +22 | Ethernet | H.264 RTSP / ONVIF | PoE switch -> gateway |
| UHF RFID reader (gantry, -15 m, 2 antennas) | -15 | Ethernet | LLRP (ISO 18000-63 tags) | PoE switch -> gateway |
| PT1000 pavement probe (embedded beside P2) | 7.0 | analog | 4-wire RTD | ESP32 aux (MAX31865) -> CAN |
| SHT4x ambient T/RH (cabinet exterior, shaded) | cabinet | I2C | digital | ESP32 aux -> CAN |

ADS131M08 #B spare channels (ch1..ch7) are reserved for a 4th piezo row, a second bending plate and AFE board
temperature; the firmware channel map (`firmware/stm32-wim-daq/App/app_config.h`) mirrors this table.

### 1.1 Why two strips per row (per wheel path) rather than one full-width strip

* A full 3.5 m strip would see the full axle load at once (10 t axle -> ~176 nC at 1.8 pC/N), roughly doubling the
  charge-amp dynamic range needed and losing left/right information.
* Two 1.75 m strips give the wheel load on each side: lateral position, tyre-pair asymmetry (a cross-check for a
  flat or missing dual tyre) and a built-in redundancy pair inside each row.
* Standard sensitivity figure used throughout: **1.8 pC/N (A, typical of Kistler Lineas-class quartz strips; the
  actual value is on the per-sensor calibration certificate and is entered as the per-channel gain)**.

Per-wheel charge at the design points (C):

| Axle load | Wheel load (half) | Force | Charge Q = S·F (S = 1.8 pC/N) |
|---|---|---|---|
| 10 t | 5 t | 49.05 kN | 88.3 nC |
| 12 t (single-axle design maximum) | 6 t | 58.9 kN | 106 nC |
| 15 t (overload, clipping check) | 7.5 t | 73.6 kN | 132 nC |

### 1.2 Why 3 m between P1 and P2 and 9 m to P3

* Speed from two rows: v = dx / dt. With dx = 3.000 m and a 1 µs timestamp resolution, the timing contribution to
  speed error is dt_err/dt. At 25 m/s, dt = 120 ms; even a 50 µs peak-location error gives 0.04 % — negligible against
  the ±5 mm installation tolerance on dx (0.17 %) (C).
* Rows closer than ~2.5 m risk both rows being under the same tandem group at once, which complicates pulse
  pairing with 1.3 m axle spacings; rows further apart than ~4 m let the vehicle speed change between rows.
* P3 at +9 m from P2 samples the suspension bounce at a different phase. Typical truck body-bounce is 1.5–4 Hz (A,
  commonly quoted in WIM literature); at 20 m/s, 9 m is 0.45 s, i.e. ~0.7–1.8 bounce periods. Averaging three rows plus
  the plate reduces the dynamic component (COST 323 reasons the same way for multi-sensor arrays).

### 1.3 Why a bending plate at all

Piezo polymer/quartz strips measure a 50 mm slice of the tyre contact patch (~250 mm long) and are sensitive to
pavement coupling. The bending plate (typically 500 mm in the travel direction, see §3) carries the entire wheel on a
metal structure with foil strain gauges, giving a lower-noise, lower-temperature-sensitivity load reference. It is
weighted 3:1 against each piezo row in the fusion step of `kifaru_wim_dsp.pipeline.process_pass`. ASTM E1318 Type-I
performance (±10 % axle group, ±6 % GVM at 95 %, as we read the standard; verify) is normally reached with bending
plates or quartz strips on a smooth Class-I site; our ±5 % GVM internal target is slightly tighter and depends more
on the site than on the electronics (see uncertainty budget in `analog-front-end.md` §9).

---

## 2. Piezo-quartz strips (P1, P2, P3)

| Item | Value | Basis |
|---|---|---|
| Sensing element | Quartz discs preloaded in an aluminium profile, 50 mm wide (travel direction), 1.75 m long | A (Lineas-class) |
| Charge sensitivity | 1.8 pC/N | A — certificate value to be entered per channel |
| Temperature coefficient of sensitivity | about −0.02 %/°C (quartz) | A; the Python model default is −0.2 %/°C to exercise compensation; the lane value comes from calibration (`calibration-procedure.md` §5) |
| Capacitance (sensor + 30 m low-noise cable) | 2–5 nF | A (cable ~100 pF/m, sensor 1–2 nF) |
| Insulation resistance | > 10^13 Ω new; > 10^11 Ω end-of-life | A; monitored via baseline drift health check |
| Max load | 12 t single axle design, 15 t without damage | A |
| Output at 12 t axle (6 t wheel) | 106 nC | C above |
| Pulse duration at v | T = (L_contact + strip width) / v = (0.25 + 0.05) m / v: 15 ms at 20 m/s, 37.5 ms at 8 m/s, 12 ms at 25 m/s | C |
| Pulse shape | approximately half-sine; integral method used (robust to speed) | A, mirrors `signal_gen._pulse` |

Spectral content: a half-sine of duration T has its first null at 1.5/T; for T = 12 ms the energy above 1 kHz is
negligible (<< −60 dB), so a 1 kHz low-pass preserves the pulse. The 1 kHz corner is set by the lab rig (shorter
pulses at 1:10 scale) and by wanting flat response to the 3–4 ms pulses of a car tyre at 25 m/s on the 50 mm strip
without a plate (T = (0.15 + 0.05)/25 = 8 ms); it is not a limiting factor.

Failure modes and detection (WIM-07):

| Failure | Symptom | Health check (firmware `health_task`) |
|---|---|---|
| Open cable / dead sensor | No pulses while partner strip and plate show axles | `dead_channel`: per-pass peak < 50 kg-eq while consensus axle count > 0 |
| Insulation breakdown (water ingress) | Baseline wanders, LF noise, reduced charge | Baseline drift > 20 % of the reset range per minute; noise RMS > 800 kg-eq |
| Debonded grout / strip rocking | Double-peaked pulses, left/right mismatch > 30 % | Pulse-shape ratio (integral/peak·T) outside 0.5–0.8; L/R asymmetry flag |
| Cable shield lifted | 50 Hz hum, radio pickup | 50 Hz bin of baseline PSD > 100 kg-eq |
| Saturation (overload or amp fault) | Flat top at ADC full scale | ≥ 8 consecutive samples within 0.1 % of full scale |

Any `fault` sets `sensor_fault` in `quality_flags`, which blocks GREEN in the clearance engine.

---

## 3. Bending plate (BP)

| Item | Value | Basis |
|---|---|---|
| Construction | Two half-plates, each ~1.75 m × 0.5 m, steel, in a frame bonded into a pavement recess | A (industry typical) |
| Strain sensing | 4 foil gauges per half-plate, full Wheatstone bridge, 350 Ω, gauge factor ~2.1 | A |
| Rated output | 2 mV/V at rated load | A (assumed on certificate) |
| Rated load per half-plate | 15 t | A; the design must accept a 10 t wheel with margin |
| Excitation | 5.000 V DC from REF5050, buffered; bridge current 5 V/350 Ω = 14.3 mA per half-plate | C |
| Full-scale output | 2 mV/V × 5 V = 10 mV at 15 t -> 0.667 µV/kg | C |
| After INA gain 100 | 1.00 V at 15 t -> 66.7 µV/kg | C |
| Temperature | Steel modulus change ~ −0.025 %/°C partly cancelled by self-compensating gauges; residual gain tempco assumed ±0.01 %/°C; zero drift removed per pass by baseline median | A |
| Pulse duration | T = (0.5 m + 0.25 m)/v = 37.5 ms at 20 m/s | C |

Excitation is measured on ADC #B ch0 (through a 4:1 divider) so the load computation is **ratiometric**: load ∝
V_bridge / V_exc, which removes excitation drift. Failure modes: gauge open (bridge output rails: detected as
saturation on one polarity), moisture in the gauge cavity (slow zero drift, flagged by baseline trend), plate frame
loose (ringing after the pulse: detected by post-pulse RMS > 3× pre-pulse RMS).

---

## 4. Inductive loops (L1, L2, L3)

Purpose: vehicle presence, start/end of the "pass" context, vehicle length (L1 occupancy time × speed), and a
gross check that an axle train belongs to one vehicle. Loops are read by commercial 2-channel loop detector cards
(e.g. a 10–200 kHz self-tuning oscillator type) with TTL/relay presence outputs; the STM32 only timestamps the edges.

Winding specification (full derivation in `enclosure-and-installation.md` §5): 2.0 m × 2.0 m, 3 turns of 1.5 mm²
loop wire, calculated inductance ≈ 95 µH (C, Grover rectangular-loop formula with a 0.9 spacing factor) plus ≈ 30 µH
for a 30 m twisted feeder, total ≈ 125 µH, inside the 50–700 µH window typical detector cards accept (A). Sensitivity
setting: detector cards express sensitivity as −ΔL/L; a truck chassis at 0.3–0.5 m above the loop gives ΔL/L of a few
percent (A) so the medium setting (−0.1 %) is adequate and avoids adjacent-lane crosstalk.

Failure modes: open loop (detector card fault output), shorted turns (frequency jump, card fault), water in the saw
cut (drift/retuning, seen as spurious presence). Health: the DAQ compares L1 count with the axle-train count per
hour; mismatch > 5 % sets `loop_inconsistent` (degraded).

---

## 5. Radar speed sensor

A 24 GHz K-band Doppler traffic radar on the gantry (RS-485, 10 Hz updates). Role: independent speed estimate used
when only one piezo row is healthy (`speed_unavailable` fallback) and as a plausibility check (|v_radar − v_piezo| > 5 %
sets `speed_inconsistent`, degraded). It does not feed the load computation directly. Typical accuracy ±1 km/h or
±3 % (A, class-typical). Failure: no frames for > 2 s -> `radar_offline` (degraded only; the piezo pair remains primary).

---

## 6. IR beam pairs

Two retro-reflective or through-beam IR pairs at each of P1 and P3, at 150 mm and 450 mm above the road, mounted on
short posts outside the lane edge. The low beam is broken by each tyre; the high beam by the body. Edge timestamps
(1 µs) give an axle count independent of the load sensors and a tyre-position check (dual vs single, from the low-beam
blocking duration × speed = tyre width + something). Outputs are 24 V PNP, taken through opto-isolators to the STM32.
Interference from sunlight is handled by modulated-beam sensors (A: standard for outdoor photoelectrics). Failure: dirty
lens (permanently "blocked") -> `ir_stuck` if blocked for > 30 s with no loop presence.

---

## 7. ANPR cameras

Two PoE IP cameras (1/1.8" sensor, 1920×1080, global or fast rolling shutter, IR illuminator, 850 nm cut filter
switchable). Front camera 25 m before P1 at 6 m height on the gantry, looking down ~15°, 12–40 mm motorised lens
framing one lane at 25–40 m. Rear camera after L3 for the trailer plate. Exposure ≤ 1/1000 s to freeze a plate at
25 m/s (motion blur = v × t_exp = 25 mm at 1/1000 s on a 520 mm Kenyan plate, acceptable; A for plate size).
Streams: RTSP H.264 to the gateway, ONVIF for configuration and event triggering. OCR runs on the gateway
(YOLOv8 detect + PaddleOCR text, per `docs/02-architecture/tech-stack.md`). The camera is not part of the metrological
chain; its output is `anpr_plate` + `anpr_confidence` in `EdgeIngestIn`.

---

## 8. UHF RFID reader and tags

ISO/IEC 18000-63 (EPC Gen2) passive tags, windscreen type on the vehicle. Reader: 4-port fixed reader on the gantry
15 m before P1, two circularly polarised 9 dBic antennas angled at the lane; ETSI band 865–868 MHz, 2 W ERP, which is
our understanding of the band allowed by the Communications Authority of Kenya (A — verify licence conditions). Read
zone ~8–10 m; at 25 m/s a vehicle is in the zone ~0.35 s, enough for tens of inventory rounds (A). Protocol LLRP
over Ethernet (PoE+). Output: EPC + RSSI + read count -> `rfid_epc`, `rfid_confidence` (confidence derived from read
count and RSSI consistency; see `edge/gateway/kifaru_gateway/identity.py`). Cloned-tag detection is the clearance
engine's IDENTITY_CONFLICT rule, not the reader's job.

---

## 9. Pavement temperature probe (PT1000)

Class A PT1000 (IEC 60751, ±(0.15 + 0.002·|t|) °C) in a stainless sheath, embedded 30 mm below the surface in a
20 mm drilled hole beside P2, bonded with the same epoxy grout, 4-wire connection to a MAX31865 on the ESP32 aux
node (reference resistor 4.3 kΩ for PT1000; resolution 15 bits ≈ 0.03 °C). PT1000 is preferred to PT100 because the
4-wire lead resistance (10 m, ~0.3 Ω) is 0.03 % of R0 instead of 0.3 %. Temperature is used (a) for sensor temperature
compensation (`temp_coeff_per_c` per channel) and (b) to flag pavement softening (> 60 °C -> `pavement_hot`, degraded,
because asphalt stiffness changes sensor coupling).

## 10. Ambient T/RH (SHT4x)

Sensirion SHT40/SHT45 (±0.2 °C / ±1.8 %RH class, I2C) in a louvred radiation shield on the cabinet's north face
(shade in the southern hemisphere tropics is not simply "north"; mount under the sun-shield roof). Second SHT4x
inside the cabinet gives the enclosure thermal state. Both are read by the ESP32 and sent on CAN every 10 s and
published as the retained MQTT health message.

---

## 11. Sensor health states (shared vocabulary)

`ok` | `degraded` | `fault` per sensor, with reasons, exactly as `kifaru_wim_dsp.SensorHealth` and the API's
`core.sensors.status` column. Mapping to the clearance engine: any `fault` on a load sensor -> `sensor_fault` (blocks
GREEN); any `degraded` -> `sensor_degraded` (AMBER). The firmware computes per-channel noise RMS, saturation
and dead-channel flags on every pass and every 10 s in idle (`firmware/stm32-wim-daq/App/health_task.c`); the gateway
publishes them retained on `kifaru/stations/{station}/lanes/{lane}/health`.

# Laboratory Demonstration Rig — Build Guide (HW-14, Phase 6)

> **This rig demonstrates signal-processing principles (axle detection, spacing, speed, dynamic load pulses, integral
> method, calibration, uncertainty reporting). It is NOT a certified weighing instrument and nothing measured on it may
> be presented as WIM accuracy for the highway lane.** OIML R134 / ASTM E1318 performance can only be established on a
> full-scale installation with type approval.

Legend: (D) datasheet-class, (C) calculation, (A) assumption/estimate. Prices are indicative estimates (Nairobi
electronics suppliers and international distributors, Q4 2026; 1 USD ≈ 130 KES assumed) and will vary.

---

## 1. Concept (1:10 scale)

```
   stepper + GT2 belt                     carriage with model truck (2–3 axles, adjustable mass)
   [M]====================================[ 🚚 ]=================================== [end stop]
   |<------------------------- 2.0 m 2040 V-slot aluminium rail ------------------------>|
            track plate (aluminium, 150 mm wide) screwed to the rail, with flush sensors:
            ---- PVDF strip S1 ---- PVDF strip S2 ---- mini bending plate ---- PVDF strip S3 ----
            x =  0.40 m             0.70 m             1.00 m                  1.30 m          (1:10 of 4/7/10/16 m... scaled layout, see §4)
   reference: bench scale (0–5 kg, 1 g) for the static axle loads; tape for spacings; optical end-stop pair for speed truth
```

The model truck's wheels run on a flat aluminium track; the sensors are flush with the track surface so a wheel rolling
across produces a load pulse analogous to the lane. The carriage is belt-driven, so speed is known from the step rate
(truth) and also measured by the DSP from two strips (as on the lane).

Scaled quantities (C):

| Quantity | Lane | Rig (1:10 geometry) |
|---|---|---|
| Axle spacing | 1.35–6 m | 0.135–0.6 m |
| Strip width | 50 mm | 12 mm (PVDF DT-series film width) ≈ 1:4 (the film is what exists; pulses are relatively longer) |
| Tyre contact length | 0.25 m | ~0.02 m (rubber model tyre, 40 mm dia) |
| Speed | 8–25 m/s | 0.2–1.5 m/s (stepper-limited; 1:10 speed would be 0.8–2.5 m/s) |
| Pulse duration T = (L_c + w)/v | 12–37 ms | (0.02 + 0.012)/v = 21–160 ms |
| Axle load | 3–12 t | 0.5–3 kg per axle (5–30 N) |

The pulse durations overlap the lane's range, so the same 1 kHz filter and 8 kSPS sampling are used — one DSP code
path for both (`firmware/stm32-wim-daq/App/wim_dsp.c`).

---

## 2. Bill of materials (rig)

| # | Item | Spec | Qty | Est. USD | Est. KES | Note |
|---|---|---|---|---|---|---|
| 1 | Aluminium extrusion 2040 V-slot | 2000 mm, black anodised | 2 | 2 × 22 | 5 700 | one rail + one for the track support |
| 2 | 2020 extrusion | 500 mm | 4 | 4 × 6 | 3 100 | legs / end plates |
| 3 | V-slot gantry plate + 4 × Delrin V-wheels, eccentric spacers | | 1 set | 25 | 3 300 | carriage |
| 4 | NEMA 17 stepper | 1.8°, 1.5–1.7 A, 0.45 N·m (D class) | 1 | 14 | 1 800 | |
| 5 | Stepper driver | TMC2209 (or DRV8825) | 1 | 8 | 1 000 | 16× microstep, StealthChop |
| 6 | GT2 belt 6 mm | 5 m open loop | 1 | 6 | 800 | |
| 7 | GT2 pulley 20T + idler | 5 mm bore | 1 + 1 | 6 | 800 | 40 mm travel/rev |
| 8 | Motor controller | Arduino Nano / STM32 Blue Pill or spare Nucleo pins (AccelStepper) | 1 | 8 | 1 000 | speed profile, triggers |
| 9 | 24 V 5 A PSU | | 1 | 18 | 2 300 | motor + rig |
| 10 | Optical end-stop / slotted sensors | TCST2103 class | 4 | 4 × 1.5 | 800 | limits + 2 for truth speed |
| 11 | Track plate | aluminium 1.5 mm × 150 mm × 2000 mm (or 3 × 700 mm) | 1 | 25 | 3 300 | flush sensor cut-outs |
| 12 | PVDF piezo film strips | TE Connectivity DT4-028K (171 × 12 mm active, 28 µm, Ag) or DT2-028K | 4 | 4 × 10 | 5 200 | 3 rows + 1 spare; d33 ≈ −33 pC/N (D), bending-mode output much larger (A) |
| 13 | Model truck chassis | 1:10 scale truck/trailer kit or laser-cut acrylic chassis with 3 axles on bearings | 1 | 60 | 7 800 | axle spacing adjustable in slots |
| 14 | Rubber wheels 40 mm | hard rubber, 10 mm wide | 6 | 6 × 2 | 1 600 | |
| 15 | Mass set | steel plates/nuts 50 g–500 g, M4 studs | 1 | 15 | 2 000 | per-axle ballast |
| 16 | Mini bending plate | Al 6061 bar 3 × 40 × 200 mm, two knife-edge supports (M6 rods) | 1 | 8 | 1 000 | §5 |
| 17 | Foil strain gauges | 350 Ω, 3–6 mm, GF ≈ 2.1, e.g. BF350-3AA (D class) | 4 (+4 spare) | 8 × 1.5 | 1 600 | full bridge |
| 18 | Strain-gauge adhesive, solder terminals, coating | cyanoacrylate (M-Bond 200 class) | 1 kit | 20 | 2 600 | |
| 19 | STM32 Nucleo-H743ZI2 | | 1 | 28 | 3 600 | DAQ |
| 20 | ADS131M08EVM | TI evaluation module | 1 | 175 | 22 800 | the lane ADC (A: price) |
| 21 | AFE prototype board | OPA2140 × 4, INA828 × 1, REF5050, passives per `analog-front-end.md` (C_f selectable 100 pF/1 nF/10 nF/22 nF via DIP switch) | 1 | 45 | 5 900 | breadboard-free: perfboard or a small 2-layer PCB (JLC/PCBWay) |
| 22 | ±12 V lab supply or TEN 5-2423 module + LDOs | | 1 | 25 | 3 300 | |
| 23 | HX711 module | **bench static tare check only — not in the signal path** | 1 | 2 | 300 | WIM-03 |
| 24 | Reference bench scale | 0–5 kg × 1 g (and a 0–500 g × 0.1 g pocket scale) | 1 + 1 | 20 + 8 | 3 600 | |
| 25 | ESP32-DevKitC + SHT40 breakout + MAX31865 + PT1000 probe | | 1 set | 30 | 3 900 | aux node demo |
| 26 | USB–CAN-FD adapter (e.g. CANable 2.0 / PEAK) + TJA1443 breakout | | 1 | 40 | 5 200 | DAQ ↔ laptop |
| 27 | Laptop / mini-PC as gateway (existing) | runs `edge/gateway` | — | 0 | 0 | |
| 28 | Cables, connectors, SMA/BNC, shielded wire, heat-shrink, fasteners | | — | 40 | 5 200 | |
| | **Total (estimate)** | | | **≈ USD 790** | **≈ KES 103 000** | ± 25 % |

---

## 3. Mechanical assembly

1. Bolt the two 2040 rails parallel 100 mm apart on the 2020 cross-members (a flat 2 m × 0.2 m frame), level on a bench.
2. Mount the track plate on top (M5 T-nuts every 150 mm). Before mounting, machine/cut the sensor pockets: three slots
   14 × 175 mm × 0.3 mm deep (just the film + tape thickness; a 0.3 mm recess with a 0.1 mm stainless or PET cover
   strip keeps the film flush and protects it) at x = 0.40, 0.70, 1.30 m, and a 42 × 160 mm rectangular cut-out at
   x = 1.00 m for the bending plate (the plate top sits flush with the track; see §5).
3. Carriage: V-wheel gantry plate riding on one rail; the model truck hangs below/beside it so its wheels bear on the
   track plate — the carriage only provides traction via a vertical pin through a slot in the truck chassis (the truck's
   own weight loads the wheels; the carriage must not carry the truck's weight, otherwise the sensors see nothing).
   Alternative: the carriage tows the truck with a thin cord + 20 mm slack (then the truck's pitch dynamics are visible).
4. Belt: motor at one end, idler at the other, belt clamped to the carriage; tension so that 1 kg lateral pull deflects
   < 10 mm.
5. End-stops at both ends (safety) and two slotted optical sensors 1.000 m apart straddling the sensor zone (truth speed
   = 1.000 m / Δt, independent of the stepper).
6. Model truck: three axles on 3 mm steel shafts in flanged bearings; spacing adjustable 135–600 mm via slotted chassis
   rails; ballast studs above each axle so the axle load can be set independently 0.3–3 kg. Add a soft foam block
   between chassis and axle carrier on one axle to emulate suspension bounce (optional).

Speed range (C): 20-tooth GT2 pulley = 40 mm/rev. Full-step 200 steps/rev. With TMC2209 at 16× microsteps and a step
rate up to 40 kHz: v_max = 40 kHz / 3200 steps/rev × 0.040 m = 0.5 m/s at full microstepping; at 4× microstepping and
25 kHz, v = 25 kHz/800 × 0.04 = 1.25 m/s. Torque falls with speed; expect a practical **0.1–1.2 m/s** with a 24 V supply
and a 3 kg total moving mass (A). Acceleration ramp 2 m/s² over 0.3 m reaches 1.1 m/s before the first sensor at 0.4 m.

---

## 4. Sensor layout on the rig

| Sensor | x (m) | Why |
|---|---|---|
| S1 (PVDF) | 0.40 | after the acceleration ramp |
| S2 (PVDF) | 0.70 | S1–S2 = 0.300 m → speed; ≥ 2× the shortest axle spacing (0.135 m) so pairing is unambiguous |
| BP (mini plate) | 1.00 | |
| S3 (PVDF) | 1.30 | third row for dynamic averaging |
| Optical truth gates | 0.35 and 1.35 | 1.000 m apart |

(The lane's 4/7/10/16 m becomes 0.4/0.7/1.0/1.6 m; S3 is pulled in to 1.3 m to leave braking distance on a 2 m rail.)
The `LaneGeometry.positions_m` used by the gateway's simulator and by the firmware config for the rig is
`{"L1": 0.0, "P1": 0.40, "P2": 0.70, "BP": 1.00, "P3": 1.30}` with `loop_length_m` irrelevant (no loops on the rig; the
optical gates play L1/L3).

PVDF mounting: film glued (thin double-sided acrylic tape) to a 0.5 mm spring-steel or FR-4 backing strip that
spans the pocket; the wheel rolling over the cover flexes the backing by ~10–50 µm, and the film produces charge in
bending mode (much higher than d33 — PVDF strain sensitivity is high; expect nC-level charges per N (A), which is why
C_f is switchable). Shield: the pocket floor is grounded aluminium; the film's top electrode faces the grounded cover
strip (cover strip is the shield; the signal electrode faces the backing). Coax to the AFE, ≤ 1 m.

---

## 5. Mini bending plate — design (C)

Simply-supported aluminium bar, span L = 150 mm between knife edges, width b = 40 mm, thickness h = 3 mm, centre load
F from one wheel (the wheel sits on the bar's centre line when the truck is centred; off-centre loads split between two
bars if two bars are used side by side — one bar per wheel track, 100 mm apart, exactly like the two half-plates).

```
I = b h³ / 12 = 0.040 × 0.003³ / 12 = 9.0 × 10⁻¹¹ m⁴
Centre load F = 5 kg × 9.81 = 49 N (the heaviest single wheel we expect):
  M_max = F L / 4 = 1.84 N·m ; σ_max = M (h/2) / I = 30.7 MPa  (6061-T6 yield ≈ 240 MPa (D) → safety 7.8)
  ε_max = σ / E = 30.7 MPa / 69 GPa = 444 µε
  δ_centre = F L³ / (48 E I) = 0.56 mm
Full bridge (2 gauges top at mid-span in compression, 2 bottom in tension, GF = 2.1):
  V_out / V_exc = GF · ε = 2.1 × 444e-6 = 0.93 mV/V  → 4.7 mV at 5 V ; with INA828 G = 101 → 0.47 V at the ADC
For a 1 kg wheel: 89 µε, 0.19 mV/V, 0.94 mV → 95 mV at the ADC ; ADC noise 10 µV → 0.1 g equivalent (electronics)
```

The 0.56 mm deflection at 5 kg is a visible "step" for a 40 mm wheel; to keep the step small, the plate is set 0.1 mm
below the track (as on the lane: 0–1 mm) and heavy loads are limited to 3 kg per wheel in the protocol (δ = 0.34 mm).
Natural frequency check (C): f₁ ≈ (π/2L²)·√(EI/(ρA)) = (π/(2·0.0225))·√(69e9·9e-11/(2700·1.2e-4)) ≈ 69.8 × 4.38 ≈ 306 Hz
for the bare bar — within the 1 kHz band, so plate ringing after a wheel leaves will be visible, exactly the
phenomenon the lane's `post-pulse RMS` health check looks for. Add a small damping pad under the bar if it obscures the
next axle.

Gauge installation: abrade (400 grit), degrease (IPA), mark the mid-span line, bond with cyanoacrylate under thumb
pressure 60 s, solder 0.1 mm leads to terminals, verify each gauge 350 ± 1 Ω and > 1 GΩ to the bar, coat with
polyurethane. Wire as a full bridge: top gauges in opposite arms.

---

## 6. Electronics and wiring

### 6.1 AFE prototype board (lane circuit, lab values)

Same topology as `analog-front-end.md` with these substitutions:

| Element | Lane | Rig | Reason |
|---|---|---|---|
| C_f | 22 nF | DIP-selectable 100 pF / 1 nF / 10 nF / 22 nF (C0G) | PVDF charge per N is unknown until measured; choose the setting that gives 1–4 V at 3 kg |
| R_f | 150 MΩ | 1 GΩ for 100 pF–1 nF (f_L = 1.6 Hz / 0.16 Hz), 150 MΩ for 10/22 nF | keep f_L ≤ 0.1 × 1/T_pulse |
| Attenuator | 6:1 | 6:1 (same board) | |
| Filters | identical | identical | |
| INA828 gain | 101 | 101 | |
| Bridge excitation | REF5050 5 V | REF5050 5 V | |

### 6.2 Wiring table — AFE board to ADS131M08EVM

| AFE output | EVM input (J-connector, AINxP / AINxN) | Channel in firmware |
|---|---|---|
| S1 (P1) | AIN0P / AIN0N (to AGND) | 0 (P1 left; P1 right unused on the rig unless two films per row) |
| S2 (P2) | AIN2P / AIN2N | 2 |
| S3 (P3) | AIN4P / AIN4N | 4 |
| BP bar | AIN6P / AIN6N | 6 |
| EXC monitor (5 V/4) | second EVM or AIN7P if only one ADC: set `WIM_EXC_CH = 7` | 7 (rig map) |

### 6.3 Wiring table — ADS131M08EVM to Nucleo-H743ZI2 (CN7/CN10 Arduino/Morpho headers; pins are ST Zio names)

| EVM signal | Nucleo pin | STM32 function | Note |
|---|---|---|---|
| SCLK | PA5 (D13) | SPI1_SCK | ≤ 10 MHz |
| DIN (MOSI) | PB5 (D11) | SPI1_MOSI | |
| DOUT (MISO) | PA6 (D12) | SPI1_MISO | |
| CS | PD14 (D10) | GPIO out | active low |
| DRDY | PF13 (D7) | EXTI13 + TIM2 CH? (route DRDY also to PA0 for TIM2_CH1 capture if timestamping is tested) | falling edge |
| SYNC/RESET | PF12 (D8) | GPIO out | 20 ms low at boot |
| CLKIN | PA8 (D? — MCO1 on PA8) | MCO1 = HSE/… set to 8.192 MHz? | Simplest: use the EVM's on-board 8.192 MHz oscillator (jumper) and leave CLKIN unconnected on the MCU (A: EVM has this option; verify) |
| AVDD/DVDD 3.3 V, GND | 3V3, GND | | EVM may be powered from its own USB; share GND |
| Optical gate 1/2 | PE9 / PE11 | TIM1 CH1/CH2 input capture | truth speed |
| Stepper STEP/DIR/EN (to TMC2209) | PB8 / PB9 / PB10 | TIM4 PWM for STEP | or a separate Arduino |
| CAN-FD TX/RX | PD1 / PD0 | FDCAN1 | via TJA1443 breakout to the USB-CAN-FD adapter |
| ESP32 CAN | TWAI TX GPIO5 / RX GPIO4 | | same bus, 500 kbit/s classic frames |
| UART debug | ST-LINK VCP (PD8/PD9) | USART3 | 921600 baud |

Power: ±12 V bench supply to the AFE; Nucleo via USB; EVM via its USB or the Nucleo 3V3 (check the EVM's current).

---

## 7. Step-by-step assembly and bring-up

1. Build the frame, track, carriage and truck (§3). Run the carriage by hand; wheels must roll on the track without the
   carriage carrying weight (verify: bench scale under the track reads the truck's full weight).
2. Install the PVDF films and the plate bar (§4, §5). Measure bridge resistance (350 Ω each arm, balanced within 0.5 Ω),
   PVDF capacitance (DT4-028K ≈ 11 nF (D class figure for the DT4; measure)).
3. AFE board: power up, check ±12 V, 5.000 V excitation, zero output on all channels; connect sensors; press a wheel by
   hand on S1 — a clean pulse of 1–4 V on the scope with C_f = 10 nF (adjust the DIP switch).
4. Flash the Nucleo with `firmware/stm32-wim-daq` built with `-DKIFARU_RIG=1` (rig geometry and channel map). Verify
   DRDY at 8 kHz, ADC IDs, zero-input noise (expect < 20 LSB_rms at the ADC ≈ 3 µV; log it).
5. Start the gateway: `python -m kifaru_gateway.main --udp 0.0.0.0:5010 --station LAB --lane L1` (or `--can can0`).
   Confirm HEARTBEAT and HEALTH frames.
6. Static calibration of the plate: place 0.5, 1, 2, 3 kg at the bar's centre (bench scale as reference) → linear fit
   (expect 67 µV/kg × 1000 ≈ 0.095 V/kg at the ADC with the lab bar, C). Enter `gain` for BP.
7. Dynamic calibration (as on the lane, `calibration-procedure.md` §2): weigh each axle on the bench scale (truth),
   run 5 passes at 3 speeds, fit gains for S1–S3 and BP, compute s(ε).
8. Temperature: warm the track with a hair dryer to ~45 °C (PT1000 under S2) and repeat 5 passes → temp coefficient of
   the PVDF (expected large, several 0.1 %/°C (A) — a vivid demonstration of why quartz is used on the lane).

---

## 8. Test protocol → accuracy table

Design: 3 axle-mass sets × 3 speeds × 10 runs = 90 passes with the 3-axle truck (spacings 0.35 m and 0.135 m, i.e. a
1+2 configuration at 1:10).

| Set | Axle 1 | Axle 2 | Axle 3 | "GVM" |
|---|---|---|---|---|
| A | 0.60 kg | 0.90 kg | 0.90 kg | 2.40 kg |
| B | 0.80 kg | 1.40 kg | 1.40 kg | 3.60 kg |
| C | 1.00 kg | 2.00 kg | 2.00 kg | 5.00 kg |

Speeds: 0.3, 0.6, 1.0 m/s (truth from the optical gates).

For each pass the gateway logs `measurement.to_dict()`; the analysis script (`edge/gateway/tools/accuracy_table.py`,
run with `--input runs.jsonl --truth truth.csv`) produces:

```
| set | v (m/s) | n | axle | truth (kg) | mean meas (kg) | s (kg) | mean err (%) | U reported (kg, k=2) | frac |err| ≤ U |
| A   | 0.6     | 10| 1    | 0.600      | 0.611          | 0.018  | +1.8         | 0.052                | 0.90           |
| ... |
| A   | 0.6     | 10| GVM  | 2.400      | 2.431          | 0.041  | +1.3         | 0.120                | 1.00           |
```

Pass/fail for the **demonstration** (not a metrological claim): axle count 100 %, spacing within ±10 mm, speed within
±3 % of the gates, GVM 95 % within ±5 % at the calibration speed and within ±10 % across speeds, and ≥ 90 % of passes with
|error| ≤ reported U (honesty of the uncertainty). Record the table and the raw `.jsonl` in `docs/05-report/` when the rig
is built; until then there are no results, only this protocol.

---

## 9. Safety

24 V and ±12 V only on the rig; the stepper can pinch — end-stops wired to the driver enable; the 5 kg truck at 1.2 m/s
carries 3.6 J — the end bumper is a 20 mm foam block; the plate bar edges are deburred.

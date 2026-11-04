# Analog Front End — Charge Amplifiers, Bridge Amplifier, Anti-Alias Filters, ADS131M08 Interface

Status: design with calculations (HW-03..06, WIM-02, WIM-04). Legend used throughout: **(D)** datasheet-class fact,
**(C)** calculation shown here, **(A)** assumption to be confirmed on hardware. No figure in this document is a
measured result; nothing here has been built or simulated yet (LTspice and Proteus instructions are in §10–11 so that
the first bench session is reproducible).

Signal chain per load channel:

```
sensor --(30 m low-noise coax)--> [GDT @ cabinet entry] --> Rs 4.7k --> charge amp (OPA2140, Cf 22 nF, Rf 150 MΩ, reset)
      --> Sallen-Key stage 1 (Q 0.54) --> Sallen-Key stage 2 (Q 1.31) --> 6:1 attenuator + RC --> ADS131M08 AINxP (AINxN = AGND)
```

Bending plate: bridge (350 Ω, 2 mV/V) --> INA828 G=101 --> the same two Sallen-Key stages --> 1:1 (no attenuator) --> ADC.

---

## 1. Charge amplifier

### 1.1 Why a charge amplifier, not a voltage amplifier

A piezo-quartz strip is a charge source Q = S·F in parallel with its capacitance C_s (1–2 nF) and the cable
capacitance C_c (≈100 pF/m, 30 m -> 3 nF). A voltage amplifier would read V = Q/(C_s + C_c), making the gain depend on
cable length and humidity. A charge amplifier is an op-amp integrator whose inverting input is a virtual ground: all
the sensor charge is forced onto the feedback capacitor C_f, so the output is independent of C_s + C_c (to first
order, see §1.5 for the second-order effect on noise gain and bandwidth).

### 1.2 Transfer function (derivation)

Inverting input at virtual ground; Kirchhoff at that node with sensor current i_s = dQ/dt:

```
i_s = -C_f · dV_out/dt  - V_out / R_f
```

Integrating with R_f -> ∞:  **V_out = −Q / C_f**.  With R_f finite, in the Laplace domain:

```
V_out(s) / Q(s) = − s / (C_f · (s + 1/(R_f C_f)))  =  −(1/C_f) · s·τ/(1 + s·τ),   τ = R_f C_f
```

i.e. a first-order high-pass with corner f_L = 1/(2π R_f C_f) below which the charge "leaks" away. Above f_L the gain is
1/C_f volts per coulomb.

### 1.3 Choosing C_f for 5 V at a 12 t single axle

Design sensitivity S = 1.8 pC/N **(A, Lineas-class typical; the certificate value is entered per channel at
commissioning)**. Two strips per row, so each strip carries one wheel = half the axle load.

```
F_wheel(12 t)  = 6000 kg × 9.81 m/s² = 58.9 kN
Q_wheel        = 1.8 pC/N × 58.9 kN  = 106 nC
C_f            = Q / V_target = 106 nC / 4.8 V = 22 nF  -> standard value 22 nF (C0G/NP0, 50 V, ±5 %)
Gain           = 1/C_f = 45.5 mV/nC    (C)
V_out(10 t axle) = 88.3 nC / 22 nF = 4.0 V ;  V_out(12 t) = 4.82 V ;  V_out(15 t) = 6.0 V
Sensitivity at the amplifier output: 1.8 pC/N × 9.81 N/kg / 22 nF = 0.803 mV/kg (per wheel)
```

On ±12 V analog rails the OPA2140 swings to about ±10.5 V (D: rail-to-rail output, ~0.5 V from the rail with 2 kΩ
load), so the amplifier itself does not clip until a wheel load of 10.5 V / 0.803 mV/kg ≈ 13 t, i.e. a 26 t single
axle. The ADC, after the 6:1 attenuator in §4, clips first at 1.2 V × 6 / 0.803 mV/kg = 8.97 t per wheel = **17.9 t
axle**, which is far above any legal limit; a clipped pulse is flagged `saturation` (fault) and the vehicle goes to the
static scale (AMBER), which is the right outcome for such an axle anyway.

C_f dielectric: C0G/NP0 (±30 ppm/°C, no piezoelectric or voltage coefficient; D for the dielectric class). Over a
+40 °C swing the gain changes by 0.12 % — it enters the Type-B budget in §9. Do not use X7R (±15 % over temperature,
and it is itself piezoelectric).

### 1.4 Choosing R_f for a 0.05 Hz low-frequency corner

```
R_f = 1 / (2π f_L C_f) = 1 / (2π × 0.05 Hz × 22 nF) = 145 MΩ  -> standard 150 MΩ (f_L = 0.048 Hz, τ = 3.3 s)
```

Why 0.05 Hz and not lower: the amplifier must recover from a vehicle-to-vehicle baseline step in a few seconds and
must not integrate the op-amp input bias current indefinitely. Why not higher: the pulse integral loses roughly
T/(2τ) of its value through R_f during a pulse of duration T:

```
T = 37.5 ms (8 m/s):  loss = 0.0375 / (2 × 3.3) = 0.57 %
T = 15 ms (20 m/s):   loss = 0.23 %
T = 12 ms (25 m/s):   loss = 0.18 %
```

This is deterministic and speed-dependent, so the firmware multiplies each pulse integral by (1 + T/(2τ)) with
τ = R_f·C_f from the channel configuration (`App/wim_dsp.c`, `WIM_RF_TAU_S`). The residual after correction (R_f
tolerance ±10 %, thick-film high-ohmic resistor) is < 0.06 % and is dropped from the budget.

Input bias current offset: V_os,out = I_b × R_f. OPA2140: I_b = ±0.5 pA typ, 10 pA max at 25 °C (D). At 10 pA:
1.5 mV. JFET bias current roughly doubles every 10 °C; at a 65 °C board (+40 °C) ×16: 24 mV; at a hypothetical 85 °C
×64: 96 mV — still < 1 % of the output span and removed by the per-pass baseline median. R_f thick-film resistors
have poor voltage coefficient; the voltage across R_f is at most 10 V so this is irrelevant here, but the resistor must
be a dedicated high-ohmic type (e.g. Ohmite SM or Vishay MOX-type), cleaned, not hand-soldered with activated flux.

### 1.5 Op-amp selection criteria

| Criterion | Requirement | Why | OPA2140 (D) |
|---|---|---|---|
| Input bias current | < 20 pA at 25 °C | I_b × R_f offset and drift during reset-off periods | 0.5 pA typ / 10 pA max |
| Input type | JFET or CMOS | pA-level bias; bipolar inputs (nA) would give 150 mV offsets and dominate noise via R_f | JFET |
| Voltage noise | < 10 nV/√Hz | noise gain is 1 + (C_s + C_c)/C_f ≈ 1.23, see below | 5.1 nV/√Hz |
| Current noise | < 10 fA/√Hz | flows into C_f, integrated | 0.8 fA/√Hz |
| Supply | ±12 V operation | 10 V swing | ±2.25 to ±18 V |
| GBW | > 5 MHz | the integrator loop with C_f = 22 nF and C_in ≈ 5 nF must be stable with margin; with GBW 11 MHz the loop closes at ~ GBW·C_f/(C_f + C_in) ≈ 9 MHz where the op-amp is still single-pole | 11 MHz |
| Offset drift | < 2 µV/°C | not critical (baseline removed per pass) | 1 µV/°C |

Alternatives: ADA4610-2 (JFET, 25 pA max, 7.3 nV/√Hz), OPA1642 (JFET audio, 20 pA max, 5.1 nV/√Hz), LTC6240
(CMOS, 1 pA, single supply only). The OPA2140 is the default in `bom.md`.

Noise gain: the sensor and cable capacitance form the "input resistor" of the integrator; the op-amp voltage noise
appears at the output multiplied by 1 + (C_s + C_c)/C_f = 1 + 5 nF/22 nF = 1.23 (C). Longer cables raise this; at 100 m
(10 nF + 2 nF) the noise gain becomes 1.55 — still fine, but cable length is capped at 50 m in the installation guide.

### 1.6 Reset switch

Needed at power-up (C_f charged by the start-up transient) and when the health task sees the idle baseline outside
±2 V with no vehicle on the loops. Requirements: leakage ≪ I_b when open (otherwise it defeats the JFET op-amp),
on-resistance irrelevant (series 1 kΩ discharge resistor sets the reset time constant 22 µs). An ordinary CMOS analog
switch leaks 0.1–1 nA (D, class-typical) — 100× the op-amp. Options, in order of preference:

1. Miniature reed relay (e.g. Coto 9007-05-00, SPST, 5 V coil, 1 kΩ in series with the contact): leakage limited by
   PCB insulation (fA–pA), coil driven from a 3.3 V GPIO via a MOSFET; 1 ms operate time; 10^8 operations.
2. Low-leakage JFET as a switch (e.g. 2N4117A, I_GSS < 1 pA at 25 °C (D)), gate driven −10 V off / 0 V on.
3. Photo-MOS relay (TLP3123-class, 1 nA max off-state leakage at 25 °C (D)) — acceptable only if the reset is used
   rarely and the leak is budgeted (1 nA × 150 MΩ = 150 mV offset, still removable).

Firmware: `ads131m08`/`acq_task` asserts RESET_n for 20 ms at boot, and the health task may assert it between
vehicles (never while L1..L3 report presence).

### 1.7 Input protection

```
cable core --> [GDT 90 V, cabinet entry panel] --> R_s 4.7 kΩ (thick film 0.5 W, pulse rated) --> node "inn"
                                                   BAV199 dual diode from "inn" to +12 V / −12 V analog rails
```

* R_s with the ~5 nF source capacitance forms a low-pass at f = 1/(2π·4.7 kΩ·5 nF) = 6.8 kHz (C), above the 1 kHz
  band, and limits a 90 V GDT let-through to 19 mA into the clamp diodes (within BAV199 150 mA rating (D)).
* Diode leakage: the "inn" node sits at 0 V and the diodes see 12 V reverse; BAV199 I_R ≈ 5 nA at 75 V/25 °C (D), a
  few 100 pA at 12 V (A, by extrapolation) — comparable with I_b, acceptable because the two diodes cancel to first
  order and the residual is a static offset removed by baseline subtraction. For ultra-low leakage substitute two
  2N4117A gate-source junctions or the diode-connected inputs of a spare JFET. Guarding (§7) keeps board leakage below
  this.

---

## 2. Bending-plate bridge excitation and instrumentation amplifier

```
REF5050 (5.000 V, 3 ppm/°C, ±0.05 %)  -> OPA2991 unity buffer (one per half-plate, 14.3 mA each)
    -> bridge EXC+ ; EXC- to analog ground star
bridge SIG+/SIG- -> RFI filter (1 kΩ / 1 nF each leg, 10 nF common) -> INA828, R_G = 499 Ω  -> AA filter -> ADC
EXC+ -> 15 kΩ / 5 kΩ divider -> ADS131M08 #B ch0 (excitation monitor, ratiometric correction)
```

Gain calculation (INA828: G = 1 + 50 kΩ / R_G, (D)):

```
Bridge full-scale output: 2 mV/V × 5.000 V = 10.0 mV at the 15 t rated load (per half-plate) -> 0.667 µV/kg
Target 1.0 V at ADC (ADC FSR ±1.2 V, keep 17 % margin for overload and dynamic peaks)
G = 1.0 V / 10 mV = 100  -> R_G = 50 kΩ / 99 = 505 Ω -> E96 499 Ω  -> G = 101.2
Sensitivity at ADC input: 0.667 µV/kg × 101.2 = 67.5 µV/kg
ADC clips at 1.2 V / 67.5 µV/kg = 17.8 t per half-plate (= 35.6 t axle) -> plate never clips before the piezo channels
```

Ratiometric: load ∝ V_sig / V_exc. The firmware divides by the measured excitation (ADC #B ch0 × 4), so the REF5050
tempco (3 ppm/°C) and buffer drop out; only the divider ratio (two 0.1 % 25 ppm/°C resistors) remains in the budget.

INA828 (D): G set by one resistor, 7 nV/√Hz input noise at G ≥ 100, input bias 150 pA, offset drift 0.4 µV/°C,
CMRR > 100 dB at G = 100 for 50 Hz pickup rejection. Gain-error contribution: INA828 0.1 % + R_G 0.1 % (25 ppm/°C) — the
total 0.2 % is calibrated out; its drift (≈0.1 %/40 °C) enters Type B.

Bridge thermal budget: 14.3 mA × 5 V = 72 mW per bridge in the plate — negligible self-heating in a steel plate.

---

## 3. Anti-alias filter: 4th-order Butterworth, two Sallen-Key stages, f_c = 1 kHz

Butterworth 4th order = two second-order sections with Q_1 = 1/(2cos(22.5°)) = 0.5412 and Q_2 = 1/(2cos(67.5°)) =
1.3066, both at the same f_c. Unity-gain Sallen-Key with equal resistors R_1 = R_2 = R:

```
f_c = 1 / (2π R √(C_1 C_2))          Q = (1/2) √(C_1 / C_2)   =>   C_1 = 4 Q² C_2
```

(C_1 is the capacitor from the first R junction to the op-amp output; C_2 is from the second R junction to ground.)

| Stage | Q target | C_2 (choose) | C_1 = 4Q²C_2 | C_1 standard | Q obtained | R ideal | R (E96) | f_c obtained |
|---|---|---|---|---|---|---|---|---|
| 1 | 0.5412 | 10 nF | 11.72 nF | 12 nF | 0.5477 | 14.53 kΩ | 14.3 kΩ | 1016 Hz |
| 2 | 1.3066 | 10 nF | 68.29 nF | 68 nF | 1.3038 | 6.097 kΩ | 6.04 kΩ | 1010 Hz |

Capacitors C0G/NP0 ±5 % (68 nF C0G exists in 1210; alternatively a PPS film 68 nF), resistors 0.1 % thin film. Op-amps:
OPA2140 again (same ±12 V rails; GBW 11 MHz ≫ 100 × f_c, so the finite-GBW Q error is < 1 % (A)). Keep unity gain:
the Sallen-Key with gain > 1 makes Q depend on resistor matching.

Computed cascade response with the E96 values (C, exact RC transfer functions):

| f | 100 Hz | 500 Hz | 1 kHz | 2 kHz | 4 kHz (Nyquist @ 8 kSPS) | 8 kHz |
|---|---|---|---|---|---|---|
| |H| | 0.00 dB | +0.06 dB | −2.70 dB | −23.6 dB | **−47.7 dB** | −71.8 dB |

Ideal 4th-order Butterworth: −3.01 dB at 1 kHz, −24.1 dB at 2 kHz, −48.2 dB at 4 kHz (|H|² = 1/(1 + (f/f_c)^8)).
The E96 values deviate by < 0.5 dB.

Note on what this filter actually does with a ΔΣ ADC: the ADS131M08 samples at f_MOD = 4.096 MHz (CLKIN/2, D) and
decimates with a sinc³ filter; signals near f_MOD alias, but the analog filter is at ≈ −290 dB there. The −47.7 dB at
4 kHz is what the architecture quotes; it mainly limits the noise bandwidth and rejects RFI, and defines the pulse
shape identically on all channels so that peak-time differences (speed) carry no channel-dependent delay. The ADC's
own digital filter has a −3 dB point around 0.26 × f_DATA ≈ 2.1 kHz at 8 kSPS (D, to verify in the datasheet's filter
section); its small droop at 1 kHz is a fixed gain factor absorbed by calibration.

Group delay of the analog filter at DC: for a Butterworth 4th order, τ_g(0) = Σ 1/(2π f_c Q_i) ... ≈ 0.52 ms (A,
from the normalised Butterworth group delay 2.61/ω_c); identical on all channels, hence irrelevant for speed.

---

## 4. ADC driver and ADS131M08 interface

### 4.1 Driver / attenuator (piezo channels)

```
stage-2 output (0 … +7.2 V useful, ±10.5 V max) -> R_a 10.0 kΩ -> node ADCIN -> R_b 2.00 kΩ -> AGND
ADCIN -> 100 Ω -> AINxP ; 1 nF from AINxP to AGND ; AINxN -> AGND (via 100 Ω)
```

Attenuation K = R_b/(R_a + R_b) = 1/6 (0.1 % resistors). Sensitivity at the ADC input: 0.803 mV/kg / 6 = **0.134 mV/kg**
per wheel; ADC full scale 1.2 V ≡ 8.97 t per wheel. The 100 Ω / 1 nF network isolates the ADC's switched-capacitor
input kick-back from the filter op-amp and follows the input-network class recommended by TI for the ADS131M0x (A:
the exact RC should be checked against the datasheet "input impedance" figure, ~1 MΩ differential at gain 1 (D,
approximate)). The attenuator's source impedance (1.67 kΩ) against a ~1 MΩ ADC input gives a −0.17 % gain error — a
constant, calibrated out. Charge-amp polarity is chosen so that a wheel load produces a positive output; the ADC is
therefore used from 0 to +1.2 V (one polarity), costing one bit of the 24 — irrelevant at the noise floor in §8.

Absolute input range: the ADS131M0x inputs tolerate AGND −1.3 V to AVDD +0.3 V (D, to verify) so a negative baseline
undershoot of a few hundred mV after a pulse is not clipped.

### 4.2 ADS131M08 facts used (D)

| Parameter | Value |
|---|---|
| Channels | 8, simultaneous sampling, each with its own ΔΣ modulator |
| Resolution | 24-bit |
| Reference | internal 1.2 V (±0.1 %, 15 ppm/°C typ); external reference possible on REFIN |
| Full-scale input | ±1.2 V / Gain differential; PGA gain 1, 2, 4, ..., 128 (we use 1) |
| Clock | CLKIN 8.192 MHz (we drive it from an STM32 timer/MCO or a dedicated 8.192 MHz oscillator); f_MOD = CLKIN/2 = 4.096 MHz |
| Data rate | f_DATA = f_MOD / OSR; OSR 512 -> 8000 SPS (OSR 1024 is the power-on default: 4 kSPS) |
| SPI | mode 1 (CPOL 0, CPHA 1), SCLK ≤ 25 MHz, word length 16/24/32 bits (24 default), frame = status word + 8 data words + CRC word |
| CRC | CRC-16 CCITT (poly 0x1021, init 0xFFFF) on output frames by default; optional input CRC (we enable it) |
| DRDY | active-low pulse every conversion; all channels aligned |
| Supplies | AVDD 2.7–3.6 V (we use 3.3 V analog LDO), DVDD 1.65–3.6 V (3.3 V), ~ 3 mA/channel |
| Noise | tens of µV_RMS at 8 kSPS, gain 1 is the order of magnitude from the noise tables; we budget 10 µV_RMS (A — read the datasheet table for OSR 512 and confirm) |

### 4.3 Timing budget per sample (C)

```
Sample period at 8 kSPS:                125 µs
Frame length (24-bit words): (1 + 8 + 1) × 24 = 240 bits
At SCLK = 10 MHz:                        24 µs  (19 % of the period)   -> two ADCs on SPI1 and SPI2 with DMA, in parallel
DRDY-to-frame latency (EXTI -> DMA start): ~2 µs on STM32H743 at 480 MHz (A)
```

Both ADCs share one CLKIN and one SYNC/RESET line, so their DRDY edges coincide and the 16 channels are aligned to
within the CLKIN period (122 ns) (D: SYNC resets the modulators).

### 4.4 Resolution, quantisation step and ENOB (C)

```
LSB = 2.4 V / 2^24 = 143 nV at the ADC input
      referred to the charge-amp output (×6): 0.86 µV = 0.0011 kg per wheel
With 10 µV_RMS noise (A): SNR = 20·log10(1.2 V/√2 / 10 µV) = 98.6 dB  -> ENOB = (98.6 − 1.76)/6.02 ≈ 16.1 bits (sine-wave definition)
      "noise-free bits" relative to the 2.4 V span: log2(2.4 V / (6.6 × 10 µV)) ≈ 15.1 ; rms-noise bits: log2(2.4 V / 10 µV) = 17.9
```

The architecture overview's "ENOB about 18 bits" corresponds to the rms-noise definition; the sine-SNR ENOB is ~16.
Either way the ADC contributes 10 µV × 6 / 0.803 mV/kg = **0.075 kg_rms per wheel**, three orders of magnitude below
the mechanical uncertainty.

---

## 5. Second ADC (#B) channel plan

| Ch | Signal | Conditioning |
|---|---|---|
| 0 | Bridge excitation monitor (5 V → 1.25 V) | 15 kΩ/5 kΩ 0.1 % divider, 100 Ω/1 nF |
| 1 | AFE board temperature (LMT87, 13.6 mV/°C) | direct |
| 2–3 | Spare piezo channels (4th row), identical AFE populated | charge amp + filter |
| 4–5 | Spare bridge channels (second plate) | INA828 + filter |
| 6 | −12 V rail monitor (via inverting divider) | health |
| 7 | +12 V rail monitor | health |

---

## 6. Reference and clocking

* ADS131M08 internal 1.2 V reference is used (D: 15 ppm/°C typ): 40 °C -> 0.06 % gain, inside the budget. An external
  REF3312 (1.25 V) is a footprint option if the bench shows otherwise.
* CLKIN 8.192 MHz from a 3.3 V crystal oscillator (±25 ppm) buffered to both ADCs; the sample rate accuracy is thus
  ±25 ppm, i.e. 0.0025 % on every time interval — speed error contribution negligible. The STM32 time base is separately
  disciplined by GPS PPS (see `communications.md` §7); the DAQ timestamps DRDY edges, not nominal sample counts.

---

## 7. Layout: guard rings and grounding on the charge-amp PCB

* The "inn" net (sensor core, R_s, C_f, R_f, reset switch, op-amp inverting input) is the only high-impedance node.
  It is kept < 15 mm long, on the top layer only, surrounded by a **guard ring** connected to analog ground on both
  layers (the inverting input sits at ground potential, so a ground guard is a driven guard here). Solder mask is
  removed over the guard ring and the node is cleaned with IPA after assembly; the board is conformal-coated.
* No ground plane directly under C_f/R_f pads (stray capacitance to ground on "inn" does not matter, but surface
  leakage across flux residue does); keep > 2 mm clearance from any other net.
* Cable shield lands on the chassis/entry panel, not on the AFE board (see `power-and-protection.md` §6).
* ±12 V decoupling: 100 nF + 10 µF per op-amp pair; the ADS131M08 AVDD from its own 3.3 V LDO (TPS7A20) fed from +5 V,
  with 1 µF + 100 nF at AVDD and 1 µF at REFOUT... (D: datasheet decoupling section) — verify the exact values.
* Analog ground and digital ground meet only at the ADC (single point star), see `power-and-protection.md` §6.

---

## 8. Noise budget (per wheel channel, referred to the charge-amp output; all (C) with (A) inputs where marked)

Sensitivity reference: 0.803 mV/kg at the charge-amp output. Noise bandwidth ≈ 1 kHz (filter), LF corner 0.05 Hz.

| Source | Formula | Value | kg-eq (rms) |
|---|---|---|---|
| Op-amp voltage noise | e_n · (1 + C_in/C_f) · √B = 5.1 nV × 1.23 × √1000 | 0.20 µV | 0.0002 |
| R_f thermal current noise into C_f | i_n = √(4kT/R_f) = 10.5 fA/√Hz; V = (i_n/(2πC_f)) · √(1/f_L − 1/f_H) | 0.34 µV | 0.0004 |
| Op-amp current noise | 0.8 fA/√Hz → same integration | 0.03 µV | 0.0000 |
| Sallen-Key resistor noise (14.3 kΩ, 6.04 kΩ) | √(4kTR·B) ≈ 15 nV/√Hz · √1000 | 0.5 µV | 0.0006 |
| ADS131M08 (10 µV_RMS (A)) referred ×6 | | 60 µV | 0.075 |
| Supply ripple through PSRR (A: 1 mV ripple, 100 dB PSRR at 100 kHz → 10 µV, filtered) | | < 10 µV | 0.012 |
| EMI/50 Hz pickup on 30 m cable after shielding and 0.05 Hz–1 kHz filtering (A, budget) | | 1 mV | 1.2 |
| **Electronics total (rss)** | | ≈ 1.0 mV | **≈ 1.3 kg** per wheel (0.026 % of a 5 t wheel) |

Conclusion: electronics noise is irrelevant to the ±5 % target; the budget is spent on mechanics and dynamics (§9). The
Python reference model's default `noise_rms_frac = 0.01` (100 kg_rms) is a deliberately pessimistic stand-in for
pavement/mechanical noise, not an electronics figure.

---

## 9. Measurement uncertainty budget (GUM) for GVM, per pass

Model: GVM = Σ_axles L_i, L_i = (1/N_rows) Σ_r k_r · g_r(T) · I_{i,r} · π/(2 T_c) (integral method per row, fused with
plate weight 3). Relative standard uncertainties (k = 1) for one pass of a 5-axle truck at 20 m/s on a Class-I-smooth
site; "A/B" is the GUM type:

| # | Component | Type | Basis | u (%, k=1) |
|---|---|---|---|---|
| 1 | Dynamic (bouncing) load not fully averaged over 4 load rows | A | bounce amplitude 3 % rms-ish of static (A, literature range 1–6 %), averaged across 4 rows with partial correlation; GVM sums 5 axles with partial pitch correlation | 1.5 |
| 2 | Pavement coupling / strip–pavement stiffness variation along the strip and with temperature | B | COST 323 site-class reasoning; our assumption for a good site after grouting | 1.5 |
| 3 | Sensor sensitivity (calibration certificate, per strip) | B | 2 % expanded (k=2) typical on a certificate (A) → 1 % | 1.0 |
| 4 | Contact-length model in the integral method (0.25 m assumed vs real tyre; speed-invariant but tyre-dependent) | B | ±10 % contact length variability, partly calibrated out by reference vehicles | 1.0 |
| 5 | Speed (two-row timing, dx tolerance ±5 mm over 3 m) | B | 0.17 % + timing 0.04 % | 0.2 |
| 6 | Temperature compensation residual (quartz −0.02 %/°C, ±20 °C, 50 % residual after compensation) | B | 0.2 % | 0.2 |
| 7 | C_f tempco (C0G 30 ppm/°C × 40 °C) | B | 0.12 % | 0.12 |
| 8 | ADC reference + attenuator drift (15 ppm/°C + 25 ppm/°C, 40 °C) | B | 0.16 % → rectangular, /√3 | 0.1 |
| 9 | Electronics noise (§8) | A | 1.3 kg per wheel, /5000 kg | 0.03 |
| 10 | R_f droop after correction | B | < 0.06 % | 0.05 |

```
u_c = √(1.5² + 1.5² + 1.0² + 1.0² + 0.2² + 0.2² + 0.12² + 0.1² + 0.03² + 0.05²) = √6.60 = 2.57 %
U (k = 2, ≈ 95 %) = 5.1 %
```

What dominates: rows 1 and 2 (vehicle dynamics and pavement coupling) account for 68 % of the variance; the entire
electronics chain (rows 7–10) is below 0.05 % of the variance. To get comfortably under ±5 %:

* Site: meet an ASTM E1318 Type-I site smoothness (we read the standard as specifying a tight longitudinal profile
  tolerance over ~60 m before the sensors; verify numeric criteria in the current edition). This attacks row 1.
* Plate weighting 3:1 and averaging three piezo rows (already in the pipeline) attack row 1.
* Calibrate with reference vehicles at three speeds (`calibration-procedure.md`) and fit a speed-dependent
  correction; this attacks row 4 (contact-length model) and reduces it to ~0.5 %, giving u_c ≈ 2.4 %, U ≈ 4.8 %.
* The clearance engine consumes `gvm_u_kg` directly: a GREEN requires GVM + U + 250 kg < limit, so an honest 5 % U
  simply converts into a slightly larger AMBER band; it is never hidden.

Per-axle group uncertainty is larger (no averaging over axles): ≈ 2 × √(1.5²·2 + 1² + 1² + ...) ≈ 7–8 % (k = 2), which
is why axle-group rules use their own u_kg in the engine.

---

## 10. LTspice simulation instructions (charge amp + anti-alias filter)

Save the following as `kifaru_afe.net` (LTspice XVII/24: File → Open, then Simulate → Run; or paste into a `.asc` as a
SPICE directive). It uses LTspice's built-in `UniversalOpAmp2` level-2 behavioural model so no vendor library is needed;
substitute the TI OPA2140 PSpice model (`.lib OPA2140.lib`, `XU1 ... OPA2140`) for a final check of bias current and noise.

```
* KIFARU PORTOS - piezo charge amplifier + 4th-order Sallen-Key Butterworth 1 kHz + 6:1 ADC attenuator
.lib UniversalOpAmps2.sub
.param Cf=22n Rf=150Meg Csens=4n S=1.8p
* --- force stimulus: half-sine, 58.9 kN peak (6 t wheel), duration T = 2.5 ms  (SINE: Voff Vamp Freq Td Theta Phi Ncycles)
Vf    f    0    SINE(0 58.9k 200 1m 0 0 0.5)
* --- piezo strip: charge source i = S*dF/dt in parallel with sensor+cable capacitance
Bsens 0    in   I = {S}*ddt(V(f))
Csens in   0    {Csens}
* --- for AC analysis: comment Bsens/Vf, uncomment the next line (1 nA -> V(out) in V per nA/sqrt... see text)
*Iac   0    in   AC 1n
* --- input protection and charge amplifier
Rs    in   inn  4.7k
D1    inn  vp   BAV199
D2    vn   inn  BAV199
Cf    out  inn  {Cf}
Rf    out  inn  {Rf}
Rrst  out  rst  1k
S1    rst  inn  rstctl 0 SWRST
Vrst  rstctl 0  PULSE(5 0 0 1u 1u 0.5m 1)     ; reset closed for first 0.5 ms, then open
.model SWRST SW(Ron=10 Roff=1T Vt=2.5 Vh=0.1)
XU1   0    inn  vp vn out level.2 Avol=1Meg GBW=11Meg Slew=20Meg ilimit=25m rail=0 Vos=0 phimargin=60 en=5.1n enk=10 in=0.8f ink=1 Rin=1T
* --- Sallen-Key stage 1: Q = 0.54 (C1 to output, C2 to ground, R1 = R2)
R11   out  a1   14.3k
R12   a1   b1   14.3k
C11   a1   o1   12n
C12   b1   0    10n
XU2   b1   o1   vp vn o1 level.2 Avol=1Meg GBW=11Meg Slew=20Meg ilimit=25m rail=0 Vos=0 phimargin=60 en=5.1n enk=10 in=0.8f ink=1 Rin=1T
* --- Sallen-Key stage 2: Q = 1.31
R21   o1   a2   6.04k
R22   a2   b2   6.04k
C21   a2   o2   68n
C22   b2   0    10n
XU3   b2   o2   vp vn o2 level.2 Avol=1Meg GBW=11Meg Slew=20Meg ilimit=25m rail=0 Vos=0 phimargin=60 en=5.1n enk=10 in=0.8f ink=1 Rin=1T
* --- 6:1 attenuator and ADC input RC
Ra    o2   adc  10k
Rb    adc  0    2k
Rk    adc  ain  100
Ck    ain  0    1n
* --- supplies
Vp    vp   0    12
Vn    vn   0    -12
.model BAV199 D(Is=1p Rs=1 N=1 Cjo=1.5p)
* --- analyses (enable one at a time)
.tran 0 20m 0 5u
*.ac dec 100 10m 10Meg
*.noise V(o2) Iac dec 50 0.01 10k
.end
```

What to plot and what to expect:

1. **Transient** (`.tran 0 20m 0 5u`): plot `V(out)`, `V(o2)`, `V(ain)`, and `V(f)/1k` on a second axis. Expected: `V(out)`
   is a half-sine of peak ≈ +4.8 V (106 nC / 22 nF; sign depends on the ddt orientation, flip Bsens nodes to taste),
   returning to within 0.6 % of zero after 2.5 ms (the droop T/(2τ) is only 0.04 % here because T is short); `V(o2)` is the
   same pulse delayed ≈ 0.5 ms with < 0.5 % peak loss (a 2.5 ms pulse has its spectral null at 600 Hz, so the 1 kHz filter
   barely touches it); `V(ain)` peaks at ≈ 0.80 V. Check the integral: `.meas TRAN qint INTEG V(out) FROM 1m TO 4m` should
   equal 2·A·T/π = 2 × 4.8 × 2.5 ms / π = 7.6 mV·s, which is the quantity the firmware uses.
2. **AC** (`.ac dec 100 10m 10Meg`, with `Iac` enabled and Bsens/Vf commented): plot `V(out)` in dB. Expected: a flat
   plateau above 0.05 Hz equal to |1/(jωC_f)| × 1 nA ... i.e. the charge-to-voltage gain 45.5 mV/nC appears as 45.5 µV per
   nA·s; the −3 dB corner at 0.048 Hz; the roll-off above 1 kHz from the filter: −2.7 dB at 1 kHz, −47.7 dB at 4 kHz on
   `V(o2)`. Also plot `V(ain)/V(o2)` = −15.6 dB (1/6).
3. **Noise** (`.noise V(o2) Iac dec 50 0.01 10k`): plot `V(onoise)` and `.meas NOISE vrms INTEG V(onoise)`: expected
   ≈ 0.4–0.6 µV_RMS (0.01 Hz–10 kHz) from the amplifier chain; multiply by 1.25 mV/kg... i.e. divide by 0.803 mV/kg for
   the kg-equivalent (≈ 0.0007 kg).
4. **Stability check**: inject a 1 µs, 1 nA current step at `in` and look for ringing on `V(out)`; with `phimargin=60` there
   must be none. Then switch to the vendor OPA2140 model and repeat; add 10 pF across R_s if the loop rings.
5. **Reset**: observe `V(out)` from 0 to 0.5 ms (held near 0 V) and the recovery after S1 opens.

## 11. Proteus (digital side) simulation steps

Proteus VSM has no ADS131M08 model and no STM32H7 model; the following is what can honestly be simulated:

1. Create a new project with an **STM32F401/F407** (Cortex-M4, available in Proteus VSM) and compile the portable DSP
   and framing sources (`firmware/stm32-wim-daq/App/wim_dsp.c`, `App/frames.c`, `host_test/`) for it with a small
   bare-metal `main` that feeds the DSP from a lookup table (the synthetic pulse exported from
   `kifaru_wim_dsp.generate_pass` as a C array). Use the Proteus "Virtual Terminal" on USART2 to print axle events
   and the frame hex dump; compare the CRC-32 printed with `python -c "import zlib,...; print(zlib.crc32(...))"`.
2. For the SPI protocol, place an **SPI Debugger** instrument on SCK/MOSI/MISO/CS and a **Digital Pattern Generator** on
   the DRDY pin at 8 kHz; drive the slave side with a Proteus "SPI slave" VSM script or a second MCU model that returns a
   fixed 10-word frame with a valid CRC-16 (python helper `firmware/stm32-wim-daq/host_test/make_frame.py`) — this
   verifies `ads131m08.c` frame parsing and CRC, and the DRDY-to-DMA timing.
3. Loop detector and IR beam inputs: use **Logic State** switches and a **Pulse Generator** on the EXTI pins and check the
   timestamps printed on the terminal (resolution: the F4 timer clock; the H7 design uses TIM2 at 1 MHz).
4. RS-485 to the radar and VMS: a **COMPIM** component bridges a real/virtual COM port so a PC-side Python Modbus RTU
   simulator (`edge/gateway/kifaru_gateway/vms.py` mock in loopback mode) can answer the firmware's requests.
5. CAN-FD and Ethernet cannot be simulated in Proteus; those paths are verified with the host test (`host_test/`) and on
   the Nucleo-H743 with a USB-CAN-FD adapter (see `firmware/stm32-wim-daq/README.md` §8).

Explicitly: none of this has been run here (no LTspice/Proteus on the authoring machine).

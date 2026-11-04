# Power, Surge Protection, Grounding and Shielding (HW-07..09)

Legend: (D) datasheet/standard-class fact, (C) calculation, (A) assumption. Site: Mariakani weighbridge, coastal
Kenya — 230 V/50 Hz single-phase utility with frequent interruptions and a high keraunic level (A: coastal East Africa is
generally reported as 50–100 thunderstorm-days/year; treat the gantry as a lightning-exposed structure).

```
230 V AC utility --> main isolator + 16 A MCB (C-curve) --> RCD 30 mA --> SPD Type 1+2 (gantry has an LPS) 
   --> EMI filter --> 24 V DIN-rail PSU/UPS controller (240 W) <--> LiFePO4 24 V 50 Ah (8S, BMS)
   --> 24 V distribution (electronic fuses per branch)
        |-- DAQ board:  24 -> +5 V (3 A buck)  -> 3.3 V digital (buck) ; 3.3 V analog LDO (ADC AVDD)
        |               24 -> ±15 V isolated DC-DC -> ±12 V LDOs (analog rails, charge amps/filters/INA)
        |-- ESP32 aux node: 24 -> 5 V -> 3.3 V
        |-- Loop detector cards (24 V), IR sensors (24 V), radar (24 V), VMS driver (24 V)
        |-- 24 -> 48 V boost (120 W) -> industrial PoE+ switch -> cameras x2, RFID reader
        |-- Edge gateway IPC (12–24 V DC input), LTE router (24 V)
```

---

## 1. Load inventory and UPS sizing

Base load as given by the master plan plus the small items that are easy to forget:

| Load | Power | Note |
|---|---|---|
| Edge gateway IPC (fanless, OCR on CPU/iGPU) | 25 W | average while processing; peaks 40 W (A) |
| DAQ (STM32H743 board, 2× ADS131M08, 16 analog channels, Ethernet PHY, CAN) | 5 W | (C) below |
| PoE cameras 2 × 12 W | 24 W | PoE class 3 budget; IR illuminator at night |
| UHF RFID reader (4-port, PoE+) | 15 W | |
| LTE/fibre router | 10 W | |
| VMS / lane signal | 20 W | LED matrix average; 40 W peak |
| **Specified base total** | **99 W** | |
| Loop detector cards 2 × 1.5 W, IR sensors 4 × 1 W, radar 3 W, ESP32 1 W, cabinet fan 2 W | 11.5 W | |
| PoE PSE and switch overhead (≈ 15 % of 39 W delivered + 5 W switch) | 11 W | |
| **Design load P_load** | **≈ 120 W** | |

DAQ 5 W check (C): STM32H743 at 480 MHz ≈ 1.2 W; 2 × ADS131M08 ≈ 2 × 0.09 W; 11 OPA2140 duals × 2 × 1.8 mA × 24 V ≈
0.95 W; INA/REF/buffers 0.25 W; bridge excitation 2 × 72 mW; LAN8742 PHY 0.25 W; CAN/RS-485 0.3 W; DC-DC losses 20 %:
≈ 4.2 W. 5 W is a fair allocation.

Autonomy requirement: 8 h (CLD-04: the lane must keep weighing and queuing events during an outage).

```
E_load   = P_load × t = 120 W × 8 h = 960 Wh      (99 W base alone: 792 Wh)
E_batt   = E_load / (η_conv × DoD) = 960 / (0.90 × 0.80) = 1333 Wh
24 V LiFePO4 (8S, 25.6 V nominal): 1333 Wh / 25.6 V = 52 Ah  ->  choose 24 V / 50 Ah (1280 Wh)  -> 7.7 h at 120 W,
                                                                  9.3 h at the 99 W base load
Low-temperature capacity derating is not an issue at Mombasa (minimum ~20 °C); high temperature (cabinet 45 °C) halves
LiFePO4 cycle life relative to 25 °C (A, chemistry-typical), so the battery sits at the bottom of the cabinet in the
coolest zone and the charger float is set to 27.2 V (3.40 V/cell) rather than 29.2 V to extend life.
```

Why LiFePO4 and not VRLA: at 45 °C a VRLA bank loses ~50 % of its life per +10 °C above 25 °C (A, the usual Arrhenius
rule) and would need 2× the Wh for the same usable energy (50 % DoD); LiFePO4 tolerates 80 % DoD and 2000+ cycles (D).

Charger/PSU: 24 V, 240 W DIN-rail PSU with battery management (Mean Well DRS-240-24 class: 24 V output, built-in
charger, UPS switch-over, dry contacts for AC-fail/battery-low (A: verify model specifics)). Recharge time after a
full 8 h outage: available charge power = 240 − 120 = 120 W -> 1333 Wh / 120 W ≈ 11 h. If faster recovery is needed,
use a 480 W PSU. The AC-fail and battery-low contacts go to the ESP32 aux node (CAN -> DAQ -> gateway -> retained MQTT
health), so the operations dashboard sees `station.failure` before the battery is empty; the gateway can shed the VMS
and the rear camera at 30 % state of charge (`edge/gateway/kifaru_gateway/config.py`, `load_shed_soc_pct`).

Solar option (not sized here): a 400 W PV array with a 24 V MPPT charger would roughly cover the daytime load and
extend autonomy indefinitely in the dry season; it needs a separate study of shading on the gantry.

---

## 2. DC rails

| Rail | Consumer | Current | Source | Noise requirement |
|---|---|---|---|---|
| +24 V bus | all field devices | ≤ 6 A | PSU/UPS | — ; protected by electronic fuses 2 A/4 A/1 A per branch |
| +48 V | PoE switch | 2.5 A | 24→48 V boost 120 W (Mean Well SD-150B-48 class (A)) | — |
| +5 V | ADC boards, ESP32, PHY, CAN | 1.2 A | 24→5 V synchronous buck 3 A (Traco TSR 3-2450 class, 500 kHz) | ripple < 20 mV (goes only to the digital section and the analog LDO inputs) |
| +3.3 V digital | STM32H743, PHY, CAN-FD transceiver | 0.6 A | 5→3.3 V buck (TPS62912 class) | — |
| +3.3 V analog | ADS131M08 AVDD, REF | 0.1 A | 5→3.3 V LDO TPS7A2033 (D: 7 µV_RMS noise, 70 dB PSRR at 100 kHz) | ADC AVDD; separate LDO per ADC |
| ±15 V isolated | pre-regulators | 0.3 A | 24→±15 V isolated DC-DC 10 W (Traco TEN 10-2423 class, 1.5 kV isolation) | — |
| ±12 V analog | charge amps, filters, INA828, REF5050 | ≈ 0.12 A each rail (C: 11 duals × 3.6 mA + INA 2 × 0.7 mA + REF 1 mA + bridges 29 mA on +12) | +12 V: TPS7A4901 LDO (15.6 µV_RMS); −12 V: TPS7A3001 LDO (D: same family) | ripple < 50 µV in band |

Post-regulation reasoning (C): the charge amplifier has PSRR ≈ 100 dB at DC falling to ~60 dB at 100 kHz (A, OPA2140
class); the isolated DC-DC switches at ~100–300 kHz with ~50 mV ripple; the LDO adds ≥ 40 dB at 100 kHz; residual
after the op-amp PSRR: 50 mV × 10^(−4) × 10^(−3) = 5 nV — negligible even before the 1 kHz filter. The 1 kHz anti-alias
filter removes anything that does alias in the ADC's sinc³ passband.

Sequencing: ADC AVDD and DVDD can power up in any order (D: ADS131M08 has no sequencing requirement, but a RESET
after both rails are stable is required; the firmware pulses SYNC/RESET for 20 ms at boot). The ±12 V rails come up
before the ADC reads anything meaningful; the charge-amp reset switch is held closed for the first 500 ms.

---

## 3. AC surge protection

* **SPD class:** the gantry (RFID, cameras, radar) is a 7 m steel structure and will carry an air-termination rod; the
  cabinet is at its base. Under IEC 62305 reasoning (we read it as: direct-strike partial lightning currents enter the
  installation via the bonded structure), the service entrance needs a **Type 1+2 combined SPD** (I_imp 12.5 kA
  10/350 µs per pole, I_n 20 kA 8/20 µs, U_p ≤ 1.5 kV), e.g. Phoenix Contact VAL-MS-T1/T2 or DEHNshield class (A for
  model numbers). If the site survey shows the gantry has no LPS and the cabinet feed comes from an underground
  distribution > 10 m away, a Type 2 SPD (I_n 20 kA, U_p ≤ 1.2 kV) is enough, as the original plan assumed.
* **Coordination:** SPD → ≥ 10 m cable or a decoupling inductor → the PSU's own input varistor (Type 3 equivalent).
  Because the PSU is within 1 m of the SPD, add a Type 3 SPD (U_p ≤ 1 kV) at the PSU terminals or a 10 µH decoupling choke.
* **EMI filter** 230 V 6 A (Schaffner FN2030-class) between the SPD and the PSU, cutting conducted emissions and
  ring-wave let-through.
* **RCD 30 mA type A** for personnel protection at the cabinet; the SPD is connected upstream of the RCD (CT1 layout) so
  that surge currents to PE do not trip it.
* **MCB 16 A C**; a surge-rated fuse in series with the SPD per its datasheet (typically 125 A gL, or the main breaker if
  smaller).

Fault indication: the SPD's remote contact goes to the ESP32 (digital input `spd_fault`), published in health.

---

## 4. Lightning and surge protection of field cables

Field cables leave the cabinet and run in the pavement or up the gantry; they are the main surge entry path.

| Cable | Protection at cabinet entry panel | Rationale |
|---|---|---|
| Piezo strips (6 × low-noise coax) | 90 V GDT core-to-shield (Bourns 2027-09-SM class, 1 pF, 5 kA 8/20 (D)); then the on-board 4.7 kΩ + BAV199 clamps (see `analog-front-end.md` §1.7) | GDT capacitance ≪ C_s so no signal effect; the series R limits the 90 V let-through to 19 mA |
| Bending plate (2 × 6-core shielded) | 24 V-class 3-stage SPD per pair (GDT 90 V → 10 Ω → TVS 6 V bidirectional on SIG±, TVS 12 V on EXC±) e.g. Phoenix PT 2X2-BE/… or DEHN BXT ML4 BD 24 class | bridge sees 5 V excitation, signal in mV |
| Loop feeders (3 × twisted pair) | GDT 90 V line-to-line and line-to-earth (loop detector cards usually have this (A)); 2 × 1 Ω series | loops are large antennas |
| IR sensors, radar, VMS (24 V + RS-485) | 24 V SPD + RS-485 2-wire SPD (Phoenix PT-IQ-2X2 class / DEHN BXT ML2 BD HF 5) | |
| Ethernet (gantry: cameras, RFID) | PoE++ surge protector Cat6 (shielded, IEC 61643-21 class D1 C2) at the gantry foot and at the cabinet entry; shielded Cat6A, armoured | PoE+ passes 50 V; protectors must be PoE+ rated |
| GPS antenna coax | coaxial SPD with DC pass (antenna bias 3.3 V) | |

All field-cable SPDs mount on a bonded aluminium entry panel (the "shield barrier") whose connection to the cabinet
earth bar is ≤ 0.3 m of 16 mm² copper. Surge current therefore reaches earth without passing through the DAQ ground.

---

## 5. Isolation barriers

| Interface | Barrier | Why |
|---|---|---|
| DAQ ↔ gateway CAN-FD | ISO1042 isolated CAN-FD transceiver (5 kV_RMS (D)), isolated 5 V supply (TI SN6505 + transformer or a 1 W isolated DC-DC) | breaks the ground loop between the analog star and the IPC chassis |
| DAQ ↔ gateway Ethernet | magnetics 1.5 kV (standard RJ45 with integrated magnetics) | inherent |
| RS-485 (radar, VMS) | ISO3082 isolated transceiver or THVD1450 + 1 W isolated DC-DC | long external runs |
| IR / loop detector TTL inputs | optocouplers (TLP291, CTR 50–600 %), 24 V inputs through 4.7 kΩ + TVS | 24 V field domain |
| Analog ±12 V | isolated DC-DC (1.5 kV) from the 24 V bus | the analog star is referenced only at the ADC |
| ESP32 aux ↔ CAN | same ISO1042 class | |

---

## 6. Grounding and shielding scheme

Single-point ("star") grounding with one chassis reference:

```
Earth electrode (≤ 10 Ω target (A: common roadside-telecom requirement; confirm against the Kenyan wiring code))
   |
   +-- cabinet main earth bar (MET), 25 mm² to electrode, 16 mm² to door, back-plate, entry panel, gantry bonding
         |
         +-- PE of 230 V installation (TN-S inside the cabinet; no PEN beyond the entrance)
         +-- SPD earth terminals (shortest path, ≤ 0.5 m)
         +-- Field-cable entry panel (shield barrier) — ALL cable shields bonded 360° here with EMC glands
         +-- PSU 24 V negative (bus 0 V) bonded here, once
         +-- DAQ chassis / digital ground via the mounting plate
         +-- Analog ground (AGND) of the AFE: connected to the DAQ digital ground at ONE point, under the ADS131M08
```

Rules:

1. **Shields**: piezo coax shields and bending-plate cable shields are bonded at the cabinet entry panel only. At the
   sensor, the sensor body sits in grout and is electrically floating (A: Lineas-class sensors are isolated from the
   pavement; confirm with the vendor), so there is no second ground and no loop current in the shield. If a vendor
   sensor is grounded at the road, use a 10 nF/100 Ω "hybrid" shield termination at the cabinet end instead of a hard bond.
2. **Loop feeders** are twisted (≥ 20 twists/m) and, if shielded, the shield is earthed at the cabinet end only.
3. **Guard rings** on the charge-amp PCB (`analog-front-end.md` §7) tie to AGND; the AFE sits in a sheet-metal
   sub-enclosure bonded to the DAQ chassis, with the analog connectors on the entry side.
4. **No daisy-chained 0 V**: every DC consumer gets its own 0 V return to the distribution block; the 0 V block is
   bonded to the MET at one point.
5. **Ethernet** to the gantry is shielded; the shield is bonded at both ends (standard for Cat6A) **but** the gantry
   foot is also bonded to the same earthing system with a 50 mm² ring conductor so that the shield never carries the
   potential difference during a strike (the surge protectors at both ends do the rest).
6. **Equipotential bonding**: the pavement sensor frames (bending plate steel frame) are bonded to the gantry/cabinet
   ring conductor by a 16 mm² conductor in the sensor duct; this prevents a step-potential difference from arriving at
   the AFE via the plate cable shield.

---

## 7. EMC notes

* Design intent: **IEC/EN 61000-6-2** (immunity, industrial) and **IEC/EN 61000-6-4** (emissions, industrial), plus
  **IEC 61000-4-5** surge at 2 kV line-earth on signal ports (the values above are chosen with these in mind; the
  design is not tested).
* Keep the 24→5 V and 24→48 V switchers and the LTE router at the opposite end of the cabinet from the AFE
  sub-enclosure; route field analog cables along the entry-panel side, power along the other side; cross at 90°.
* LTE and Wi-Fi antennas are outside the cabinet (bulkhead N/SMA connectors on the roof plate); 800 MHz–2.6 GHz
  fields of ~3 V/m at the AFE are expected (A); the 1 kHz filter plus the ferrite + 1 nF RC at every connector pin
  keep demodulated RF below the 50 µV budget line in `analog-front-end.md` §8.
* Relay outputs for the lane signal/VMS carry RC snubbers (100 Ω + 100 nF) or drive solid-state relays.
* CAN-FD at 2 Mbit/s data phase and 100 Mbit/s Ethernet are the only fast digital lines leaving the DAQ; both are
  differential and shielded.
* Every PCB: 4-layer with solid ground, 100 nF per IC, series ferrites on the ±12 V entering the AFE compartment.

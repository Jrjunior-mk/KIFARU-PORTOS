# Enclosure, Thermal Design, Pavement Installation and Commissioning (HW-10)

Legend: (D) datasheet/standard-class fact, (C) calculation, (A) assumption.

---

## 1. Roadside cabinet

* **Rating:** IP66 (IEC 60529), IK10 impact, 316L stainless steel 1.5 mm or hot-dip-galvanised steel with a marine-grade
  C5-M polyester coating (A: Mombasa's coastal air is corrosivity category C5-M under ISO 9223 reasoning — salt fog).
* **Size:** 800 mm H × 600 mm W × 300 mm D single-door, on a 300 mm concrete plinth with cable duct entries from below
  (keeps the door sill above splash and allows ducts to sweep in). Surface area A = 2(0.8·0.6 + 0.8·0.3 + 0.6·0.3) = 1.80 m² (C).
* **Sun shield:** a second skin (ventilated double roof and south/west side panels, 30 mm air gap). (At 4 °S latitude the sun
  is overhead most of the year; the roof is the dominant solar surface.)
* **Door:** 3-point lock, door-open switch to the ESP32 (`door_open` in health), gasket replaceable, document pocket.
* **Internal layout (front view):**

```
+------------------------------------------------------------------+
| roof plate: LTE/GPS/Wi-Fi bulkhead connectors, cable glands (none) |
| [ 24 V distribution + e-fuses ] [ LTE router ] [ PoE switch 48 V ] |  <- top: warm zone, digital
| [ SPD T1/T2 ][ MCB ][ RCD ][ EMI ][ 230 V -> 24 V PSU/UPS ctrl ]  |
| [ STM32 DAQ + AFE sub-enclosure (shielded, analog side left) ]     |  <- middle: AFE on the entry-panel side
| [ Edge gateway IPC (fanless, fins to the back-plate) ]             |
| [ Loop detector cards ][ VMS relay/RS-485 driver ][ ESP32 aux ]    |
| [ field-cable entry panel: SPDs, EMC glands, shield bonding ]      |  <- bottom left
| [ LiFePO4 24 V 50 Ah battery + BMS (bottom, coolest) ]             |  <- bottom: battery
| MET earth bar along the bottom edge, 25 mm² to electrode           |
+------------------------------------------------------------------+
```

---

## 2. Thermal calculation for Mombasa/Mariakani

Design ambient: 35 °C shade (A: Mombasa's hottest months peak ~33–35 °C; 35 °C is a reasonable envelope), direct sun.

Internal dissipation (loads that physically sit in the cabinet, from `power-and-protection.md` §1):

| Item | W |
|---|---|
| IPC | 25 |
| DAQ | 5 |
| PSU losses (90 % efficient at 120 W out) | 13 |
| PoE switch + PSE overhead | 11 (the 39 W delivered to cameras/RFID dissipates outside) |
| LTE router | 10 |
| UPS charger losses, e-fuses, relays, fan | 6 |
| **P_int** | **≈ 70 W** |

Solar gain (C): irradiance G = 1000 W/m² on the roof (0.18 m²) plus ~0.5 × 1000 on one side wall (0.24 m²):
absorbed without shield = α × (1000 × 0.18 + 500 × 0.24) = 0.35 × 300 = 105 W for a light-grey finish (α ≈ 0.35 (A)).
With a ventilated double skin the transferred fraction is of order 25–30 % (A, common cabinet-vendor figure) ->
P_sun ≈ 30 W.

Heat rejection from a sealed cabinet by natural convection + radiation: h ≈ 6–8 W/(m²·K) (A, textbook range for a
vertical plate in still air plus radiation to surroundings at similar temperature). Taking h = 7:

```
ΔT_mean = (P_int + P_sun) / (h × A) = (70 + 30) / (7 × 1.80) = 7.9 K   ->   mean internal air ≈ 43 °C
Stratification top-to-bottom in an unstirred cabinet: +5 K at the top  ->  hot zone ≈ 48 °C ; battery zone ≈ 40 °C
Night-time with no sun and 25 °C ambient: 70 / 12.6 = 5.6 K  ->  ≈ 31 °C
```

Component limits (D, class-typical): IPC 60 °C (fanless, derated), PSU 70 °C (derate above 50 °C), router 70 °C,
LiFePO4 charge ≤ 45 °C, AFE op-amps 85 °C (but drift budget assumed +40 °C board rise). Everything is inside its rating
with ~10 K margin; the battery is the tightest constraint and justifies the bottom placement.

**Decision:** sealed IP66 cabinet with double-skin sun shield **and** an internal circulating fan (24 V, 2 W, 60 m³/h, run
by the ESP32 above 35 °C internal) to kill stratification — no filter fan (would downgrade to IP54 and ingest salt and
dust; filter maintenance on the Mariakani road is unrealistic) and no air-conditioner (power during outages). Provision a
mounting cut-out and 24 V feed for an **air-to-air heat exchanger** (Rittal/Pfannenberg class, IP66 preserved, ~40 W
fan power, ~2 W/K) to be fitted if commissioning shows the hot zone above 55 °C.

Humidity: at night the cabinet cools faster than its air -> condensation on the AFE. Fit a 50 W anti-condensation heater
(hygrostat 65 %RH, thermostat 15 °C) and a Gore-type pressure-compensation vent so the gaskets do not pump moist air.
The internal SHT4x reports %RH; > 70 %RH for 30 min raises `cabinet_humid` (degraded).

---

## 3. Pavement works — piezo strips (P1, P2, P3)

Site precondition (ASTM E1318 reasoning, our reading: a Type-I site requires a smooth, rut-free, stiff pavement over
roughly 60 m upstream and 30 m downstream): longitudinal grade ≤ 2 %, cross-slope ≤ 2 %, rutting ≤ 3 mm, no joints or
patches within 30 m upstream, asphalt or (preferably) a concrete slab at the sensor rows (A). Survey with a straight
edge and a profilograph if available; record it in the commissioning file because row 2 of the uncertainty budget
depends on it.

Procedure per strip (2 strips per row, each 1.75 m, aligned on one straight line across the lane):

1. Mark the row line perpendicular to the lane axis (±0.1°: over 1.75 m that is ±3 mm); mark P1→P2 spacing 3.000 m
   ±5 mm and P2→P3 9.000 m ±5 mm centre-to-centre (speed accuracy depends on it; see `sensor-architecture.md` §1.2).
2. Cut the slot with a diamond saw: 72 mm wide × 55 mm deep for a 50 mm-wide, ~45 mm-high Lineas-class profile (A — use
   the sensor vendor's drawing); plus the lead-out slot 20 mm wide × 50 mm deep to the kerb and a 50 mm duct to the
   cabinet.
3. Clean: compressed air, then dry with a hot-air lance; the slot must be dust-free and bone dry (moisture is the main
   cause of debonding). Do not install in rain or when the pavement is below 10 °C or above 50 °C (A: epoxy pot life).
4. Prime the slot walls with the grout vendor's primer. Position the strip on its setting spacers so the top face is
   0.5–1.0 mm below the pavement surface; check with a straight edge across the lane that the strip follows the
   pavement crown (the strip tolerates ≤ 1 mm deviation, A).
5. Pour the two-component epoxy grout from one end, letting it flow to avoid voids (~10 L per 1.75 m strip at this slot
   size (C: 0.072 × 0.055 × 1.75 ≈ 6.9 L minus the sensor volume ≈ 3 L -> ~4 L; order 10 L to cover the lead-out slot and
   waste)). Vibrate lightly with a rod. Overfill 2 mm.
6. Cure: 4–6 h at 30 °C before traffic (A, grout-dependent; verify on the datasheet). Grind the surface flush (grout
   is designed to be ground; the sensor top must not be ground).
7. Measure sensor capacitance and insulation (> 10^12 Ω at 100 V (A)) at the cabinet end before and after grouting;
   record.
8. Roll a known vehicle over and look at the pulse shape on the DAQ debug stream: clean single half-sine per wheel;
   a double hump means a void or a step at the grout edge.

Lead-out cables: low-noise coax (e.g. RG-58-class with conductive-polymer anti-triboelectric layer, as supplied with
the sensor), in the duct with gentle bends ≥ 10× diameter, total length ≤ 50 m (`analog-front-end.md` §1.5).

## 4. Pavement works — bending plate

1. Excavate a pit 3.6 m (lane width) × 0.9 m × 0.35 m deep; cast a reinforced concrete foundation 250 mm thick with the
   vendor's frame anchors, level within 1 mm/m, with a drain to the kerb (A, vendor-typical).
2. Set the two half-plate frames flush with the pavement (0 to −1 mm), 5 mm gap between the halves sealed with a
   compressible joint; approach and departure slabs ≥ 1.0 m of concrete each side so that the tyre arrives on a surface
   as stiff as the plate (otherwise a step excites the suspension).
3. Cable to the cabinet in its own 50 mm duct (shielded 6-core per half-plate), bonding conductor 16 mm² alongside.
4. Static check with a known axle (reference vehicle parked on the plate): output within ±2 % of the certificate value
   at 5 V excitation; zero returns within 0.1 % of full scale after the vehicle leaves (friction/hysteresis check).

## 5. Inductive loops — winding specification

Geometry: 2.0 m (along the lane) × 2.0 m (across; centred in the 3.5 m lane, ≥ 0.6 m from the lane edge to limit
adjacent-lane detection). Slot: 6–8 mm wide × 50 mm deep, corners chamfered at 45° (no right-angle cuts, they break the
insulation); lead-in slot to the kerb, feeder in a 25 mm duct to the cabinet.

Inductance estimate (C, Grover's formula for a rectangular single-turn loop of sides a, b and wire radius r, scaled by
N² and a 0.9 turn-spacing factor (A)):

```
L_1 = (µ0/π) [ a·ln(2ab/(r(a+d))) + b·ln(2ab/(r(b+d))) − 2(a+b−d) + (a+b)/4 ],  d = √(a²+b²), r = 0.75 mm
a = b = 2.0 m  ->  L_1 ≈ 11.7 µH ;  L_N ≈ 0.9 · N² · L_1
N = 2: 42 µH   |   N = 3: 95 µH   |   N = 4: 170 µH
Feeder: twisted pair, ≈ 1 µH/m (A) × 30 m = 30 µH
Total at N = 3: ≈ 125 µH   -> inside the 50–700 µH window of typical detector cards (A)
```

Choose **N = 3** (standard for 2 × 2 m). Wire: 1.5 mm² stranded copper, XLPE or PE insulation rated for direct burial
(loop wire), one continuous length including the lead-in — no joints in the road. Twist the lead-in pair ≥ 20 twists/m.
Fill the slot with hot-pour or two-part loop sealant; no sealant voids (water → drift).

Acceptance at the cabinet end: inductance within 100–160 µH, series resistance < 3 Ω, insulation > 100 MΩ at 500 V DC
(A, standard detector practice), Q > 5 at the detector frequency. Record all four.

Detector frequency assignment: adjacent loops on different frequencies (e.g. L1 high, L2 low, L3 high) to avoid
crosstalk; detector cards in the cabinet, TTL presence to the DAQ, RS-485 health (if available) to the gateway.

## 6. IR beams, radar, cameras, RFID (gantry and posts)

* IR posts: 0.5 m outside the lane edge at P1 and P3, 24 V modulated sensors with retro-reflectors across the lane
  (span 4 m), beams at 150 mm and 450 mm height; sunlight shield hoods; cables in the kerb duct.
* Gantry at −15 m: 7 m clear height, RFID antennas 5 m high angled 45° down-lane, radar at 5.5 m aimed at P1, front
  ANPR camera at 6 m aimed to frame the lane at 25–40 m ahead... i.e. at P1 ±8 m; cable tray down the leg to the gantry
  foot junction box with the PoE surge protectors; 50 mm² bonding ring.
* Rear camera on a 6 m post after L3 looking back at the trailer plate.

## 7. Cable routing summary

| Cable | Type | Route | Length (typ.) |
|---|---|---|---|
| Piezo × 6 | low-noise coax (vendor) | sensor slot → kerb → 50 mm duct → entry panel | 20–40 m |
| Bending plate × 2 | 6-core shielded 0.5 mm² | pit → own duct → entry panel | 25–35 m |
| Loop feeders × 3 | twisted 1.5 mm² | slot → 25 mm duct → entry panel | 10–40 m |
| IR × 4, radar, VMS | 24 V + RS-485 (shielded 2 × 2 × 0.5) | kerb duct / gantry tray | 20–60 m |
| Ethernet × 3 (2 cameras, RFID) | Cat6A S/FTP, armoured outdoor | gantry tray → duct → entry panel | 40–60 m |
| GPS antenna | LMR-240 coax | roof bulkhead | 2 m |
| Earth | 25 mm² / 16 mm² / 50 mm² ring | per `power-and-protection.md` §6 | — |

Separation: analog sensor ducts ≥ 300 mm from the 230 V feed; crossings at 90°.

---

## 8. Commissioning checklist (sign-off per lane)

Mechanical / civil
- [ ] Row spacing P1–P2 = 3.000 ± 0.005 m, P2–P3 = 9.000 ± 0.005 m, rows perpendicular ± 0.1° (recorded)
- [ ] Strips flush −0.5…−1.0 mm, no step at grout edges (straight-edge check photographed)
- [ ] Plate frames flush 0…−1 mm, gap sealed, approach slabs cured
- [ ] Loops: L, R, insulation, Q recorded; sealant complete
- [ ] Cabinet plinth, door seal, sun shield, glands torqued; IP66 water-spray test passed (hose test 10 min, dry inside)

Electrical / earthing
- [ ] Earth electrode ≤ 10 Ω measured (fall-of-potential), ring conductor continuity to gantry < 0.1 Ω
- [ ] SPD installed, fault contact wired, PSU AC-fail/battery-low contacts wired to ESP32
- [ ] Battery: 8 h discharge test at the design load with AC off (or a 1 h test extrapolated and logged)
- [ ] Rails: +24 V, +48 V, +5 V, +3.3 V D, +3.3 V A, ±12 V measured and logged (ripple on ±12 V < 1 mV_pp at the AFE)
- [ ] Insulation of each piezo core to shield > 10^12 Ω; capacitance recorded (baseline for the health trend)

DAQ / firmware
- [ ] ADS131M08 ×2 detected (ID register 0x24xx (D: ID register value for the M08 variant; verify)), 8 kSPS confirmed via DRDY period 125.0 µs
- [ ] Idle noise RMS per channel < 5 kg-eq (electronics) — if > 50 kg-eq, chase pickup before anything else
- [ ] Charge-amp reset and baseline recovery verified (scope)
- [ ] GPS PPS locked; DAQ timestamp vs gateway time < 100 µs after 10 min
- [ ] Loop and IR edges time-stamped and matching axle pulses (drive a van over at 20 km/h)
- [ ] Pulse-shape check at 3 speeds (ratio integral/(peak·T) within 0.55–0.75)

Gateway / cloud
- [ ] Gateway receives AXLE_EVENT / PASS_SUMMARY / HEALTH frames with CRC OK, no gaps for 1 h
- [ ] ANPR reads ≥ 95 % of plates on 50 test passes in daylight and 50 at night; RFID reads 100 % of equipped vehicles
- [ ] MQTT mTLS connect, retained health visible in the cloud; outbox replay test (disconnect LTE 15 min, reconnect, 0 lost)
- [ ] VMS/lane signal shows GREEN/AMBER/RED from a test decision within 1.5 s of the last axle

Metrology
- [ ] Initial calibration per `calibration-procedure.md` completed; `CalibrationRecord` posted for each load sensor
- [ ] Acceptance table (truth vs measured ± U) filed; lane status set to `active` only if acceptance passes

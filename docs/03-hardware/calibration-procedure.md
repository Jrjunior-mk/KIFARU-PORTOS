# Calibration Procedure (HW-13)

Scope: the WIM lane as a pre-screening instrument. The numbers it produces are measurements with a stated uncertainty;
the legal weight is always the certified static scale's. This procedure keeps the WIM's gain, temperature coefficient
and uncertainty statement current and produces the records the API stores (`core.calibration_records`: `method`,
`reference_mass_kg`, `gain`, `offset`, `temp_coeff_per_c`, `reference_temp_c`, `uncertainty_pct`, `valid_from/valid_to`
(from `valid_days`), `performed_by`, `notes`).

Standards referred to by name: OIML R134 (the structure of initial verification / in-service checks with reference
vehicles at several speeds is modelled on it); ASTM E1318 (performance classes and the idea of a Type-I site);
COST 323 (repeatability/reproducibility test conditions). Exact tolerance values quoted below are **our targets**, not a
claim of conformity to those documents.

---

## 1. Measurement model and what gets calibrated

Per load channel r (P1, P2, P3, BP), per axle i, the firmware/pipeline computes a raw load L_raw from the pulse integral
(`kifaru_wim_dsp.pipeline.pulse_load`), then applies

```
L_i,r = (L_raw,i,r − offset_r) · gain_r / (1 + temp_coeff_per_c_r · (T_pav − reference_temp_c_r))
```

exactly as `ChannelCalibration` in `pipeline.py` and `firmware/stm32-wim-daq/App/wim_dsp.c`. The calibration determines,
per channel: `gain`, `offset`, `temp_coeff_per_c`, `reference_temp_c` (fixed at 25 °C), and a `uncertainty_pct` (expanded,
k = 2, relative) that the fusion uses as `type_b_rel_u = uncertainty_pct / 200`.

Hierarchy: each piezo channel's gain is initially the certificate sensitivity (pC/N → kg via the AFE constants); the
procedure below replaces it with the in-situ gain, which also absorbs pavement coupling and the AFE constants.

---

## 2. Initial calibration (at commissioning, and after any sensor/AFE replacement)

### 2.1 Reference vehicles

Two reference vehicles, chosen to span the fleet:

| Vehicle | Configuration | Target GVM | Loading |
|---|---|---|---|
| RV-A | 2-axle rigid (1+1) | ~16 t | sealed ballast (concrete blocks), fixed suspension pressure |
| RV-B | 5- or 6-axle semi (1+2+2 or 1+2+3) | ~40–48 t | sealed ballast |

Each vehicle's axle loads are measured **statically** on the Mariakani static scale immediately before and after the
runs (fuel use and ballast shifts). Static-scale expanded uncertainty, from its certificate, is expected to be ≤ 0.5 %
(A: Class III/IIII-class road vehicle scales, OIML R76 reasoning); record the certificate number in `notes`. Axle loads
are taken on a multi-deck static scale or by the axle-by-axle method with the vehicle level (a ±2 % axle-load
uncertainty is typical for axle-by-axle weighing on a single-deck scale (A); state which was used).

### 2.2 Runs

Speed set: 30, 60, 80 km/h (8.3, 16.7, 22.2 m/s) — the lane's expected operating range; vehicles hold a steady speed
(no braking/accelerating within 100 m of the sensors: dynamic load transfer between axles would bias the result).

Runs: **3 speeds × 5 runs × 2 vehicles = 30 passes**, lateral position varied naturally (the driver is told to drive
normally within the lane). Repeat the whole set at two pavement temperatures on the same day — early morning
(T_pav ≈ 25–30 °C) and mid-afternoon (T_pav ≈ 45–55 °C in Mariakani sun, A) — giving **60 passes**. If the morning/afternoon
spread is < 15 °C, do a third session on another day or use a propane heater over the sensor rows with care (vendor
guidance needed; A).

For each pass record: `pass_id`, timestamp, vehicle, speed (radar + two-row), T_pav (PT1000), T_amb, per-channel raw
axle loads (`per_row_kg` with gain = 1), the DAQ health frame.

### 2.3 Gain and offset estimation (per channel)

With raw loads x_{k} (channel r, axle k over all axles and runs of the first temperature session) and static reference
loads y_k:

```
gain_r   = Σ_k y_k · x_k / Σ_k x_k²          (least-squares through the origin; a WIM load channel has no physical offset
                                              because the per-pass baseline median removes it)
offset_r = 0  for piezo channels; for the bending plate use the static zero measured with no vehicle after the session if
           it differs from the pre-session zero by more than 0.1 % of full scale (hysteresis), otherwise 0.
```

Residuals e_k = gain_r·x_k − y_k, relative ε_k = e_k / y_k. Report mean(ε) (bias, should be ≈ 0 after the fit), s(ε)
(repeatability + lateral position + dynamics), per speed group. Check for a speed dependence: fit ε vs speed; if the
slope exceeds 0.5 % per 10 km/h, apply the integral-method contact-length correction (`TYRE_CONTACT_LENGTH_M`) per vehicle
class in the firmware config rather than bending the gain.

### 2.4 Temperature coefficient

Using both temperature sessions, with gain_r from §2.3 fixed and relative error ε_k and pavement temperature T_k:

```
temp_coeff_per_c_r = slope of linear regression of (gain_r·x_k / y_k − 1) on (T_k − 25 °C)
```

Expected magnitudes: piezo-quartz |α| < 0.0005 /°C (A, quartz); polymer piezo 0.002–0.01 /°C (A); bending plate < 0.0002
/°C (A). Note the sign convention: `temp_factor = 1 + α (T − T_ref)` divides the measured load, so α is the sensor's
sensitivity coefficient (positive if it reads high when hot). With fewer than two well-separated temperature points,
set `temp_coeff_per_c = 0` and `notes = "temp coefficient not determined"`, and plan the sweep within 30 days.

### 2.5 Uncertainty statement per channel

```
u_A  = s(ε) / √1          (standard deviation of a single pass — the quantity relevant to a single-vehicle decision, not
                           the standard error of the mean)
u_B  = √( u_static² + u_temp² + u_speed² )  with u_static = 0.25 % (0.5 % cert, k=2), u_temp = |α|·ΔT_residual·0.5,
                                            u_speed = 0.2 %
uncertainty_pct = 2 · √(u_A² + u_B²) · 100
```

Typical expectation with a good site: s(ε) ≈ 2–3 % per piezo channel per axle, ≈ 1.5 % for the plate → `uncertainty_pct`
≈ 5–6 % (piezo), ≈ 3–4 % (plate), per axle, per channel. The fusion across four channels then gives the GVM figure
targeted at ≤ 5 % (k=2); see `analog-front-end.md` §9.

### 2.6 Acceptance criteria (initial)

Evaluated on the 60 passes, using the full pipeline with the new calibration:

| Quantity | Criterion (our target, k = 2 / 95 %) |
|---|---|
| Axle count | 100 % correct |
| Axle configuration (grouping) | 100 % correct |
| Speed vs radar | 95 % within ±2 km/h or ±3 % |
| Axle spacing vs tape measurement | 95 % within ±0.15 m |
| Single axle load | 95 % within ±10 % of static |
| Axle group load | 95 % within ±8 % |
| GVM | 95 % within ±5 %; mean bias within ±1.5 % |
| Reported `gvm_u_kg` | at least 90 % of passes have |measured − static| ≤ gvm_u_kg (the uncertainty must be honest, not optimistic) |

(For reference, our reading of ASTM E1318 Type I is ±6 % GVM / ±15 % single axle at 95 %; of OIML R134 accuracy class
5: ±5 % GVM in-service. We do not claim either; the lane is a pre-screen.)

If the GVM criterion fails but the plate alone passes, the lane is placed in `degraded` mode (plate-only, piezo rows used
for timing) with `lane_degraded` flag and a 60-day validity while the piezo installation is investigated.

Validity: `valid_days = 180` for a passed initial calibration.

---

## 3. Routine verification (monthly) using AMBER/RED diversions

Every AMBER/RED vehicle is weighed statically anyway; this is free reference data. Monthly, the gateway/cloud job
(`apps/api` calibration report, outside the scope of this document) computes over the month:

```
ratio_j = GVM_WIM,j / GVM_static,j  for all j with matching identity (plate/RFID) and |t_static − t_wim| < 2 h,
          excluding vehicles flagged sensor_fault, speed_out_of_range, or that stopped between the two scales (fuel/cargo change)
n ≥ 100 per month expected at Mariakani (A)
bias = mean(ratio) − 1 ; spread = 2 · s(ratio)
```

Note the selection bias: diverted vehicles are the heavy/uncertain ones; the ratio is still an unbiased gain check
because the WIM error does not depend on which side of the limit the vehicle is on (verify with a quarterly sample of
10 GREEN vehicles directed to the static scale as a control group, logged with `method = static_scale_comparison`).

Actions:

| Result | Action |
|---|---|
| |bias| ≤ 1.5 % and spread ≤ 6 % | Record `static_scale_comparison` with the observed numbers; extend `valid_to` by 30 days (`valid_days = 30`) |
| 1.5 % < |bias| ≤ 3 % | Re-estimate gains per channel from the month's data (same least squares as §2.3 but on GVM, scaled to channels by their per-row ratios); new record; 30 days |
| |bias| > 3 % or spread > 8 % | Lane flagged `calibration_expired` (blocks GREEN), full §2 recalibration within 14 days |
| any channel's health history shows > 10 % passes degraded | investigate sensor before recalibrating |

Also monthly: a static zero/shunt check of the bending plate (`method = shunt`: insert a 350 kΩ shunt resistor across one
bridge arm → expected ΔV = V_exc·R/(4(R+R_shunt)) ≈ 5 V × 350/(4·350350) = 1.25 mV → reads as 1.25 mV/10 mV × 15 t =
1.87 t; tolerance ±0.5 %) and a capacitance/insulation check of the piezo cables (`method = bench`).

---

## 4. Temperature-coefficient re-estimation in service

Over a month, the ratio_j data span the daily temperature cycle. Regress ratio on T_pav; if the slope differs from the
stored `temp_coeff_per_c` by more than 0.0005 /°C with n ≥ 100, update the coefficient in the next record and `notes`
the regression (n, slope, r²). This keeps the compensation honest without closing the lane.

---

## 5. Record format

One `CalibrationRecord` per sensor per calibration, posted to the API (`POST /api/v1/stations/.../calibrations`, body
fields as `apps/api/kifaru/routers/stations.py`). Example for the P1 channel after an initial calibration:

```json
{
  "sensor_id": "01J9ZK4Q8W1N3M5R7T9V2X4Z6B",
  "method": "reference_vehicle",
  "reference_mass_kg": 40250,
  "gain": 1.0372,
  "offset": 0.0,
  "temp_coeff_per_c": -0.00031,
  "reference_temp_c": 25.0,
  "uncertainty_pct": 5.4,
  "valid_days": 180,
  "notes": "Initial cal 2026-11-20. RV-A 16.12 t, RV-B 40.25 t static (Mariakani static scale cert MS-2026-0142, U=0.4%). 60 passes, 30/60/80 km/h, Tpav 27-51 C. s(eps)=2.6%, bias after fit +0.1%. Temp slope from 2 sessions, r2=0.71. Performed by ... ."
}
```

`uncertainty_pct` is what the pipeline turns into `type_b_rel_u = uncertainty_pct / 200` (k=2 → k=1, % → fraction) for
that channel. The lane is considered calibrated (`_lane_calibration_valid` in `weighing_service.py`) only while every load
sensor has a record with `valid_to` in the future; otherwise `calibration_expired` blocks GREEN.

---

## 6. Worked example of the acceptance table (format only — synthetic numbers from the simulator, NOT measurements)

| Pass | Vehicle | v (km/h) | T_pav (°C) | GVM static (kg) | GVM WIM (kg) | U (k=2, kg) | error (%) | within U |
|---|---|---|---|---|---|---|---|---|
| 1 | RV-B | 30 | 28 | 40 250 | 40 610 | 1 790 | +0.9 | yes |
| 2 | RV-B | 60 | 29 | 40 250 | 39 480 | 1 760 | −1.9 | yes |
| ... | | | | | | | | |
| 60 | RV-A | 80 | 51 | 16 120 | 16 540 | 820 | +2.6 | yes |

Summary rows: n, mean error, s, 95 % half-width, fraction within U, pass/fail per §2.6. The lab rig produces the same
table at 1:10 scale (`lab-rig-build-guide.md` §8).

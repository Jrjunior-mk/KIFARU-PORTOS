# KIFARU PORTOS — Environmental (Emissions) Model

| Field | Value |
|---|---|
| Document | `docs/06-operations/emissions-model.md` |
| Version | 0.1 — 2026-11-04 |
| Implements | RTM ENV-01, BKH-05 (Master Prompt Module 8 and Module 4) |
| Code of record | `packages/ai_agents/kifaru_ai_agents/environmental.py` (`FACTORS`, `EnvironmentalAgent`), `packages/ai_agents/kifaru_ai_agents/backhaul_matcher.py` (`DEFAULT_ECON`, `BackhaulMatchingAgent`), `packages/ai_agents/kifaru_ai_agents/base.py` (`ROAD_FACTOR`, `haversine_km`), `apps/api/kifaru/routers/environment.py` |
| API | `GET /api/v1/environment/report`, `POST /api/v1/environment/what-if`, `GET /api/v1/environment/factors` |

> **Modelled, not measured.** Every quantity produced by this model is a *modelled estimate* derived from counts of platform events multiplied by typical published factors. No fuel flow, no tailpipe emission and no odometer reading has been measured. The API labels every output `"modelled estimate — not a measured result"` (`environmental.py`) and the stats endpoint carries `source` on every record. These figures must not be reported as environmental achievements until the factors in §3 are replaced with fleet-measured values (§8) and the counts come from `source=live` passes.

## 1. Purpose

The model answers one question for operators, transporters and regulators: *compared with a baseline in which every truck stops and queues at the weighbridge and every return trip is driven empty, how much fuel, cost and CO₂ does the platform's behaviour avoid?* It is deliberately simple, transparent and reproducible by hand so that any stakeholder can check a number.

## 2. Definitions and symbols

| Symbol | Meaning | Unit | Source in platform |
|---|---|---|---|
| N_avoid | Trucks cleared GREEN (did not stop) in the period | count | `clearance_decisions.decision='GREEN'` |
| N_stop | Trucks that stopped (AMBER + RED) | count | `decision in ('AMBER','RED')` |
| t_wait | Average queue wait per stopping truck | s (converted to h) | mean of `queue_records.avg_wait_s` where `kind='observed'`; **900 s default if no observations** |
| K_empty | Empty kilometres in the baseline | km | sum of `km_loaded` over assigned/delivered backhaul matches (see §5.3 for why) |
| K_avoided | Empty kilometres avoided by backhaul matches | km | same sum |
| K_detour | Unnecessary detour kilometres | km | `0` in the report today (field reserved; `what-if` accepts it) |
| f_idle | Idle fuel consumption | L/h | `FACTORS["idle_l_per_h"]` |
| f_stop | Stop–start penalty | L per stop | `FACTORS["stop_penalty_l"]` |
| f_empty | Fuel consumption running empty | L/km | `FACTORS["fuel_l_per_km_empty"]` |
| f_loaded | Fuel consumption running loaded | L/km | `FACTORS["fuel_l_per_km_loaded"]` |
| e_CO2 | CO₂ emission factor for diesel | kg CO₂/L | `FACTORS["co2_kg_per_l"]` |
| p_diesel | Diesel pump price | KES/L | `FACTORS["diesel_kes_per_l"]` |
| v_avg | Average corridor speed | km/h | `DEFAULT_ECON["avg_speed_kmh"]` |
| h_drv | Driver hours available per day | h | `DEFAULT_ECON["driver_max_remaining_h"]` |
| ρ_road | Road-distance / great-circle ratio | — | `ROAD_FACTOR` |

## 3. Factors (exactly as in code)

### 3.1 `environmental.FACTORS`

| Key | Value | What it represents | Type of source | Typical published range (for orientation only) |
|---|---|---|---|---|
| `idle_l_per_h` | **2.5** | Fuel burned by a heavy diesel truck idling in a queue, air-conditioning off | Engineering estimate within published fleet-guidance ranges | Heavy-duty diesel idle consumption is commonly quoted in the 2–4 L/h band (the code docstring states "range 2–4"); varies with engine size, auxiliaries, ambient temperature |
| `stop_penalty_l` | **0.35** | Extra fuel for one decelerate-from-60 km/h / creep / re-accelerate cycle at a weighbridge, excluding idling | Engineering estimate | Stop–go penalty for a loaded articulated truck is of the order of a few tenths of a litre per event; strongly dependent on mass and speed |
| `fuel_l_per_km_empty` | **0.30** | Running consumption, empty, 6–7 axle articulated truck, Northern Corridor | Engineering estimate | Articulated trucks typically consume ~25–35 L/100 km empty on mixed roads |
| `fuel_l_per_km_loaded` | **0.42** | Running consumption, loaded, same truck class | Engineering estimate | ~35–50 L/100 km loaded on mixed/hilly roads (Mombasa–Nairobi climbs from sea level to ~1 700 m) |
| `co2_kg_per_l` | **2.68** | Tank-to-wheel CO₂ from burning one litre of diesel | Derived from published inventory factors | IPCC 2006 Guidelines default for gas/diesel oil ≈ 74 100 kg CO₂/TJ; at a typical net calorific content of ~36 MJ/L this gives ≈ 2.67 kg CO₂/L. UK DEFRA/BEIS conversion factors for diesel are ≈ 2.7 kg CO₂/L (combustion only). The code comment states "IPCC/DEFRA order of magnitude". |
| `diesel_kes_per_l` | **170.0** | Pump price used for cost estimates | **Configuration placeholder** | Must be set from the current EPRA-published Mombasa pump price each month; the agent accepts a `factors` override per call |

### 3.2 `backhaul_matcher.DEFAULT_ECON`

| Key | Value | Note |
|---|---|---|
| `fuel_l_per_km_loaded` | **0.42** | Identical to `FACTORS` |
| `fuel_l_per_km_empty` | **0.30** | Identical to `FACTORS` |
| `diesel_kes_per_l` | **170.0** | Identical to `FACTORS` |
| `co2_kg_per_l` | **2.68** | Identical to `FACTORS` |
| `avg_speed_kmh` | **45.0** | Corridor average including stops; used only for ETA/driver-hours feasibility |
| `driver_max_remaining_h` | **9.0** | Daily driving-hours budget assumed when `driver_hours_used_h` is not supplied; advisory |

### 3.3 `base.ROAD_FACTOR`

`ROAD_FACTOR = 1.25`: all distances in the platform's mock routing are great-circle (haversine, R = 6 371.0088 km) multiplied by 1.25 to approximate road distance on the Northern Corridor. Check: Nairobi (−1.29, 36.82) → Mombasa (−4.04, 39.67) gives 440.1 km great-circle, 550.1 km "road" — the signed road distance is about 480–490 km, so the factor **over-estimates** this particular pair by ~12 %. When the `maps` integration is in `real` mode (`routers/integrations.py route`) routed distances replace this approximation.

The five values shared by both modules are intentionally identical so that marketplace figures and environment reports cannot disagree. Any change must be made in both dictionaries (or `DEFAULT_ECON` made to import from `FACTORS`) and recorded in §9.

## 4. Formulas — environmental report

For a scenario with `stops` stopping trucks, `idle_h` total idle hours, `e_km` empty kilometres and `d_km` detour kilometres (`EnvironmentalAgent._run.bundle`):

```
idle_l    = idle_h × f_idle
stop_l    = stops  × f_stop
empty_l   = e_km   × f_empty
detour_l  = d_km   × f_loaded
litres    = idle_l + stop_l + empty_l + detour_l
co2_kg    = litres × e_CO2
cost_kes  = litres × p_diesel
```

Two scenarios are evaluated with the same factors:

| Scenario | stops | idle_h | e_km | d_km | Meaning |
|---|---|---|---|---|---|
| **Baseline** | N_avoid + N_stop | (N_avoid + N_stop) × t_wait/3600 | K_empty | K_detour | Every truck stops and waits the observed average; all empty km are driven; detours happen |
| **Platform** | N_stop | N_stop × t_wait/3600 | max(0, K_empty − K_avoided) | 0 | Only AMBER/RED trucks stop; matched empty km are removed; detours assumed eliminated |

```
savings_x = baseline_x − platform_x      for x ∈ {litres, co2_kg, cost_kes}
```

All intermediate litres are rounded to 0.1 L, CO₂ to 0.1 kg, cost to 1 KES (so totals may differ from unrounded sums by rounding).

### 4.1 How the report builds its inputs (`routers/environment.py report`)

| Input | Query | Caveat |
|---|---|---|
| `stops_avoided` | count GREEN decisions in the last `hours` (optionally per `station_id`) | Includes `source=simulated` decisions unless the deployment contains only live data — the report does **not** filter by source today |
| `stops_made` | count AMBER + RED | same |
| `avg_queue_wait_s` | mean `avg_wait_s` of observed queue records in the window | defaults to **900 s** when there are no observations — a modelling assumption, not data |
| `empty_km` and `empty_km_avoided` | Σ `explanation.km_loaded` over `BackhaulMatch` rows with status assigned/delivered created in the window | Both set equal, so platform empty km = 0 for matched loads (see §5.3) |
| `detour_km` | 0 | reserved |

## 5. Formulas — backhaul match economics (`BackhaulMatchingAgent`)

For an offer with origin O, destination D, and a truck at position T with home base H (all distances great-circle × ρ_road):

```
km_to_pickup  = dist(T, O)
km_loaded     = dist(O, D)
km_dest_home  = dist(D, H)
km_direct     = dist(T, H)                       # what the truck would drive anyway (empty return)
with_cargo    = km_to_pickup + km_loaded + km_dest_home
extra_km      = max(0, with_cargo − km_direct)

fuel_l        = km_to_pickup × f_empty + km_loaded × f_loaded + km_dest_home × f_empty
fuel_direct_l = km_direct × f_empty
fuel_extra_l  = max(0, fuel_l − fuel_direct_l)   # marginal fuel to carry the cargo
fuel_cost_kes = fuel_extra_l × p_diesel
margin_kes    = offered_price_kes − fuel_cost_kes

dedicated_l   = km_loaded × f_loaded + km_loaded × f_empty     # a dedicated truck: loaded out, empty back
co2_avoided_kg = max(0, dedicated_l − fuel_extra_l) × e_CO2
```

Time feasibility: `hours_needed = with_cargo / v_avg + 1.5` (1.5 h loading/unloading); `eta = max(available_from, ready_from) + hours_needed`; the match is infeasible if `eta > deadline`, if `mass_kg > payload_capacity_kg`, or if the body type is incompatible. Driver hours are advisory (`reasons` carries "requires a rest period").

### 5.1 Interpretation of `co2_avoided_kg`

The counterfactual is a **dedicated vehicle** making a round trip for this cargo (loaded out, empty return). The matched truck's marginal fuel is subtracted. This is the standard "avoided dedicated trip" framing; it is favourable to the platform because it assumes the cargo would otherwise have moved by a dedicated truck rather than being consolidated some other way. State this assumption whenever the figure is quoted.

### 5.2 Score (for completeness; not an emissions quantity)

`score = 0.35·s_dist + 0.20·s_fit + 0.25·s_margin + 0.10·s_time + 0.10·s_hours`, with `s_dist = max(0, 1 − extra_km/300)`, `s_fit = 1 − |0.85 − min(fit,1)|/0.85`, `s_margin = clamp(margin/revenue, 0, 1)`, `s_time ∈ {0,1}`, `s_hours ∈ {0.5, 1}`; infeasible matches are multiplied by 0.1.

### 5.3 Why `empty_km = empty_km_avoided` in the report

The report has no independent source for the baseline empty kilometres of the whole fleet (that requires telematics or trip logs, Phase 3/5). It therefore counts only the loaded kilometres of *matched* backhauls as "empty km that would have been driven" and treats them as fully avoided. This is a **lower bound on baseline empty km** and an **upper bound on the share avoided**; the resulting `empty_l` saving should be read as "fuel for the matched return legs, assuming they would otherwise have run empty".

## 6. Worked examples (reproduced from the agents)

### 6.1 Environmental report — `what-if` inputs

`POST /api/v1/environment/what-if` with `{"stops_avoided": 100, "stops_made": 20, "avg_queue_wait_s": 1800, "empty_km": 500, "empty_km_avoided": 200}` (this is the case in `packages/ai_agents/tests/test_agents.py::test_environmental_savings_positive_and_labelled`).

| Quantity | Baseline | Platform | Saving |
|---|---|---|---|
| Stops | 120 | 20 | 100 |
| Idle hours | 120 × 0.5 h = 60 h | 20 × 0.5 h = 10 h | 50 h |
| `idle_l` | 60 × 2.5 = **150.0** | 10 × 2.5 = **25.0** | 125.0 |
| `stop_l` | 120 × 0.35 = **42.0** | 20 × 0.35 = **7.0** | 35.0 |
| `empty_l` | 500 × 0.30 = **150.0** | (500 − 200) × 0.30 = **90.0** | 60.0 |
| `detour_l` | 0 | 0 | 0 |
| `litres` | **342.0** | **122.0** | **220.0** |
| `co2_kg` | 342.0 × 2.68 = **916.6** | 122.0 × 2.68 = **327.0** | **589.6** |
| `cost_kes` | 342.0 × 170 = **58 140** | 122.0 × 170 = **20 740** | **37 400** |

Agent output (verified by running the agent on 2026-11-04): `savings = {"litres": 220.0, "co2_kg": 589.6, "cost_kes": 37400}`, confidence 0.6, label "modelled estimate — not a measured result".

### 6.2 Backhaul match — Nairobi ICD → Mombasa

From `test_backhaul_matcher_ranks_feasible_first_and_explains`: offer 20 000 kg general cargo, origin (−1.29, 36.82), destination (−4.04, 39.67), price KES 120 000, deadline +2 days; truck `near_ok` at (−1.30, 36.80), home Mombasa (−4.04, 39.67), payload 28 000 kg, flatbed.

| Step | Value |
|---|---|
| `km_to_pickup` | 3.1 km |
| `km_loaded` | 550.1 km (440.1 km great-circle × 1.25) |
| `km_dest_home` | 0.0 km |
| `km_direct` | 551.2 km |
| `extra_km` | max(0, 553.2 − 551.2) = **2.1 km** (rounding of intermediates) |
| `fuel_l` | 3.1×0.30 + 550.1×0.42 + 0 = 0.93 + 231.04 = 231.97 L |
| `fuel_direct_l` | 551.2 × 0.30 = 165.36 L |
| `fuel_extra_l` | **66.6 L** |
| `fuel_cost_kes` | 66.6 × 170 = **11 328** |
| `margin_kes` | 120 000 − 11 328 = **108 672** |
| `dedicated_l` | 550.1 × (0.42 + 0.30) = 396.1 L |
| `co2_avoided_kg` | (396.1 − 66.6) × 2.68 = **883** |
| `hours_needed` | 553.2 / 45 + 1.5 = 13.8 h → "requires a rest period" (advisory) |
| `score` | 0.35×0.99 + 0.20×0.84 + 0.25×0.91 + 0.10×1.0 + 0.10×0.5 = **0.892** |

Agent output (verified): `extra_km 2.1, fuel_litres 66.6, fuel_cost_kes 11328.38, co2_avoided_kg 883.0, score 0.8921`.

Reading: the truck was going home to Mombasa empty anyway, so carrying the cargo costs ~67 L of extra fuel while a dedicated round trip would have burned ~396 L; the model credits ~883 kg CO₂ avoided.

## 7. Limitations

1. **Factors are generic.** None of the six factors has been measured on Kenyan fleets; consumption depends on engine, load, gradient (the Mombasa–Nairobi climb), road condition, driver behaviour and ambient temperature.
2. **Baseline is stylised.** "Every truck stops and waits the average observed wait" ignores that some trucks would be exempt or routed elsewhere; the average wait is applied uniformly.
3. **Default wait of 900 s** is used when no queue observations exist; such reports are pure assumption and should be discarded.
4. **Simulated passes are counted** unless the deployment contains only live data. Until the report filters by `source`, environment figures from a database containing simulator output are meaningless as operational claims.
5. **Empty-km baseline is a lower bound** (§5.3).
6. **Distances are great-circle × 1.25** in mock mode; for Nairobi–Mombasa this over-estimates by ~12 %, inflating backhaul `km_loaded` and therefore `co2_avoided_kg`.
7. **Tank-to-wheel only.** Upstream (well-to-tank) emissions, non-CO₂ gases (CH₄, N₂O), black carbon and the health effects of idling in queues are excluded.
8. **No rebound effects** (e.g. faster clearance inducing more trips) are modelled.
9. **Price is a placeholder.** Cost figures are only as current as `diesel_kes_per_l`.
10. **Rounding** of intermediate litres to 0.1 L can make savings differ from `baseline − platform` by ≤ 0.1.
11. **Confidence** reported by the agent (0.6 for the environmental agent, 0.8/0.3 for the matcher) is a fixed heuristic, not a statistical interval.

## 8. Replacing the factors with measured values (validation plan)

| Factor | Measurement method | Minimum sample | Owner | Phase |
|---|---|---|---|---|
| `idle_l_per_h` | CAN-bus fuel-rate (J1939 PGN 65266) or fuel-flow meter on ≥ 10 trucks during real queue waits at Mariakani | 50 queue episodes | Telematics partner / transporter | 5–7 |
| `stop_penalty_l` | Fuel-rate integration over deceleration/creep/acceleration envelope at the weighbridge, same trucks | 100 stop events | same | 5–7 |
| `fuel_l_per_km_empty`, `fuel_l_per_km_loaded` | Fuel-card litres ÷ odometer km per trip, classified loaded/empty using platform shipment status; or CAN total-fuel counters | 200 trips per class | Transporters via `fleet` adapter | 5 |
| `co2_kg_per_l` | Keep inventory factor; cite the exact published source and vintage in §9 when the owner selects one | — | Technical writer | 3 |
| `diesel_kes_per_l` | Monthly EPRA maximum pump price for Mombasa; set via `factors` override or configuration | monthly | Ops | 3 |
| `ROAD_FACTOR` | Replace with routed distances (`maps` adapter in `real` mode) | — | Backend | 5 |
| `avg_queue_wait_s` | Observed from queue records (`source=live`) rather than the 900 s default | continuous | Ops | 3 |

Once measured values exist, publish them as a versioned factor set (e.g. `FACTORS_VERSION = "ke-nc-2027Q2"`) and record the version in every report, as the clearance engine already does with `limits_version`.

## 9. Change log of factors

| Date | Change | Reason | Changed in |
|---|---|---|---|
| 2026-11-04 | Initial values 2.5 / 0.35 / 0.30 / 0.42 / 2.68 / 170 ; 45 km/h ; 9 h ; ρ = 1.25 | Engineering estimates for Phase 2 | `environmental.py`, `backhaul_matcher.py`, `base.py` |

## 10. Disclaimer (to be shown wherever figures are displayed)

> Fuel, cost and CO₂ figures are **modelled estimates** produced by multiplying platform event counts by typical published factors (idle 2.5 L/h, 0.35 L per stop, 0.30/0.42 L/km empty/loaded, 2.68 kg CO₂/L, diesel KES 170/L). They are **not measured** and have not been validated on Kenyan fleets. They are intended to compare scenarios, not to report achieved environmental outcomes.

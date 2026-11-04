# KIFARU PORTOS — scenario comparison (modelled)

Generated 2026-11-04T05:33:06.758950+00:00 · horizon 12 h · 5 replications per scenario · base seed 1000 · 95 % confidence intervals (Student t) · runtime 151.2 s

> **MODELLED RESULTS — synthetic arrivals and assumed service-time distributions; not measured field data.** Fuel and CO2 are modelled estimates from the Environmental agent factors (idle 2.5 L/h, 0.35 L per stop-start cycle, 2.68 kg CO2/L) and must not be reported as measured savings. Baseline data is to be collected in Phase 7 before any claim is made.

## Comparison table

| Scenario | Trucks | Mean time in system (min) | P90 time in system (min) | Mean static queue | Max static queue | % trucks stopped | Static-scale utilisation (%) | Stops avoided vs baseline | Fuel, modelled (L) | CO2, modelled (kg) | GREEN / AMBER / RED (%) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `baseline_all_stop` | 922 ± 41 | 47.1 ± 15.4 | 79.5 ± 30.0 | 47.4 ± 18.0 | 101 ± 37 | 100.0 ± 0.0 | 99 ± 1 | 0 ± 0 | 1934 ± 661 | 5183 ± 1772 | 79 / 19 / 2 |
| `rolling_clearance` | 922 ± 41 | 2.3 ± 0.5 | 4.5 ± 0.4 | 0.0 ± 0.0 | 1 ± 1 | 21.6 ± 2.9 | 22 ± 2 | 723 ± 43 | 70 ± 10 | 187 ± 26 | 79 / 18 / 2 |
| `arrivals_+20` | 1114 ± 46 | 2.4 ± 0.9 | 4.6 ± 0.3 | 0.0 ± 0.0 | 2 ± 2 | 21.2 ± 0.6 | 28 ± 0 | 686 ± 37 | 83 ± 2 | 222 ± 6 | 80 / 18 / 2 |
| `arrivals_+30` | 1212 ± 43 | 2.7 ± 1.5 | 4.5 ± 0.2 | 0.0 ± 0.0 | 1 ± 1 | 21.4 ± 1.7 | 28 ± 3 | 663 ± 42 | 91 ± 7 | 243 ± 19 | 79 / 19 / 2 |
| `arrivals_+50` | 1396 ± 38 | 3.2 ± 1.5 | 4.8 ± 0.2 | 0.0 ± 0.0 | 3 ± 1 | 21.4 ± 1.4 | 33 ± 2 | 623 ± 39 | 105 ± 7 | 282 ± 19 | 79 / 18 / 2 |
| `station_lane_failure` | 922 ± 41 | 2.4 ± 0.4 | 5.1 ± 0.3 | 0.0 ± 0.0 | 4 ± 2 | 27.5 ± 2.2 | 29 ± 3 | 669 ± 34 | 90 ± 9 | 241 ± 24 | 79 / 19 / 2 |
| `inspection_rate_x2` | 922 ± 41 | 2.9 ± 0.5 | 4.9 ± 0.5 | 0.0 ± 0.0 | 1 ± 1 | 22.9 ± 2.5 | 24 ± 3 | 711 ± 48 | 74 ± 7 | 198 ± 19 | 78 / 19 / 2 |
| `static_capacity_-1` | 922 ± 41 | 2.1 ± 0.4 | 4.8 ± 0.4 | 0.0 ± 0.0 | 2 ± 1 | 22.4 ± 2.5 | 31 ± 4 | 716 ± 42 | 72 ± 9 | 194 ± 23 | 78 / 19 / 2 |
| `delayed_cargo_release` | 922 ± 41 | 5.2 ± 1.7 | 17.0 ± 1.5 | 0.0 ± 0.0 | 1 ± 1 | 34.8 ± 2.1 | 24 ± 3 | 601 ± 17 | 112 ± 11 | 301 ± 30 | 79 / 19 / 2 |
| `dynamic_slot_allocation` | 922 ± 41 | 2.3 ± 0.7 | 4.7 ± 0.4 | 0.0 ± 0.0 | 2 ± 1 | 22.1 ± 2.9 | 20 ± 2 | 718 ± 38 | 72 ± 11 | 193 ± 29 | 79 / 19 / 2 |
| `queue_policy_priority` | 922 ± 41 | 2.3 ± 0.5 | 4.5 ± 0.4 | 0.0 ± 0.0 | 1 ± 1 | 21.6 ± 2.9 | 22 ± 2 | 723 ± 43 | 70 ± 10 | 187 ± 26 | 79 / 18 / 2 |

Values are mean ± half-width of the 95 % CI across replications. P90 of a heavy-tailed distribution can be below the mean when a few inspected trucks dominate the mean.

## Secondary metrics

| Scenario | Mean WIM queue | Max WIM queue | Mean static wait of stopped trucks (s) | Inspection-bay utilisation (%) | P90 time in system, priority cargo (min) | Fuel saved vs baseline, modelled (L) | CO2 saved vs baseline, modelled (kg) | Drain after last arrival (min) |
|---|---|---|---|---|---|---|---|---|
| `baseline_all_stop` | 0.00 ± 0.00 | 0 ± 0 | 2498 ± 946 | 51 | 76.4 ± 31.7 | 0 ± 0 | 0 ± 0 | 89 ± 33 |
| `rolling_clearance` | 0.00 ± 0.00 | 0 ± 1 | 0 ± 0 | 61 | 4.1 ± 0.4 | 1864 ± 660 | 4996 ± 1769 | 27 ± 28 |
| `arrivals_+20` | 0.00 ± 0.00 | 0 ± 1 | 2 ± 3 | 66 | 4.8 ± 0.8 | 1851 ± 659 | 4961 ± 1767 | 15 ± 22 |
| `arrivals_+30` | 0.00 ± 0.00 | 0 ± 1 | 1 ± 1 | 67 | 4.3 ± 1.0 | 1843 ± 662 | 4939 ± 1774 | 61 ± 51 |
| `arrivals_+50` | 0.00 ± 0.00 | 1 ± 1 | 4 ± 4 | 81 | 4.7 ± 0.9 | 1829 ± 659 | 4901 ± 1766 | 62 ± 22 |
| `station_lane_failure` | 0.00 ± 0.00 | 0 ± 1 | 7 ± 5 | 53 | 5.0 ± 0.8 | 1844 ± 658 | 4942 ± 1763 | 38 ± 31 |
| `inspection_rate_x2` | 0.00 ± 0.00 | 1 ± 1 | 1 ± 1 | 70 | 5.1 ± 1.1 | 1860 ± 661 | 4984 ± 1772 | 34 ± 31 |
| `static_capacity_-1` | 0.00 ± 0.00 | 0 ± 1 | 2 ± 1 | 56 | 4.5 ± 0.9 | 1861 ± 659 | 4989 ± 1767 | 10 ± 10 |
| `delayed_cargo_release` | 0.00 ± 0.00 | 1 ± 1 | 0 ± 1 | 56 | 15.7 ± 5.9 | 1821 ± 651 | 4882 ± 1744 | 36 ± 14 |
| `dynamic_slot_allocation` | 0.00 ± 0.00 | 1 ± 1 | 5 ± 3 | 47 | 4.4 ± 0.7 | 1862 ± 654 | 4990 ± 1752 | 166 ± 35 |
| `queue_policy_priority` | 0.00 ± 0.00 | 0 ± 1 | 0 ± 0 | 61 | 4.0 ± 0.6 | 1864 ± 660 | 4996 ± 1769 | 27 ± 28 |

## Scenario definitions

- `baseline_all_stop` — Pre-platform situation: every truck queues for the static scale; no WIM pre-screen (engine decision is shadow only). (policy=all_stop, arrivals/h=60.0×1.0, WIM lanes=2, static bays=5, inspection bays=2, inspection rate=0.01, audit rate=0.02, slot cap/15 min=None, priority queue=False, hold prob=0.0, lane failures=())
- `rolling_clearance` — Platform: WIM pre-screen, GREEN continues, AMBER to static scale, RED to static + inspection. (policy=rolling, arrivals/h=60.0×1.0, WIM lanes=2, static bays=5, inspection bays=2, inspection rate=0.01, audit rate=0.02, slot cap/15 min=None, priority queue=False, hold prob=0.0, lane failures=())
- `arrivals_+20` — Rolling clearance with +20 % demand. (policy=rolling, arrivals/h=60.0×1.2, WIM lanes=2, static bays=5, inspection bays=2, inspection rate=0.01, audit rate=0.02, slot cap/15 min=None, priority queue=False, hold prob=0.0, lane failures=())
- `arrivals_+30` — Rolling clearance with +30 % demand. (policy=rolling, arrivals/h=60.0×1.3, WIM lanes=2, static bays=5, inspection bays=2, inspection rate=0.01, audit rate=0.02, slot cap/15 min=None, priority queue=False, hold prob=0.0, lane failures=())
- `arrivals_+50` — Rolling clearance with +50 % demand. (policy=rolling, arrivals/h=60.0×1.5, WIM lanes=2, static bays=5, inspection bays=2, inspection rate=0.01, audit rate=0.02, slot cap/15 min=None, priority queue=False, hold prob=0.0, lane failures=())
- `station_lane_failure` — One of two WIM lanes down for 2 h mid-run; its trucks fall back to the static scale. (policy=rolling, arrivals/h=60.0×1.0, WIM lanes=2, static bays=5, inspection bays=2, inspection rate=0.01, audit rate=0.02, slot cap/15 min=None, priority queue=False, hold prob=0.0, lane failures=((18000.0, 7200.0, 1),))
- `inspection_rate_x2` — Physical inspection sampling and random audit rate doubled. (policy=rolling, arrivals/h=60.0×1.0, WIM lanes=2, static bays=5, inspection bays=2, inspection rate=0.02, audit rate=0.04, slot cap/15 min=None, priority queue=False, hold prob=0.0, lane failures=())
- `static_capacity_-1` — One static bay fewer (maintenance). (policy=rolling, arrivals/h=60.0×1.0, WIM lanes=2, static bays=4, inspection bays=2, inspection rate=0.01, audit rate=0.02, slot cap/15 min=None, priority queue=False, hold prob=0.0, lane failures=())
- `delayed_cargo_release` — 15 % of trucks held at the gate (median 15 min) awaiting cargo release. (policy=rolling, arrivals/h=60.0×1.0, WIM lanes=2, static bays=5, inspection bays=2, inspection rate=0.01, audit rate=0.02, slot cap/15 min=None, priority queue=False, hold prob=0.15, lane failures=())
- `dynamic_slot_allocation` — Arrivals smoothed by a booking cap of ~110 % of mean demand per 15-min window. (policy=rolling, arrivals/h=60.0×1.0, WIM lanes=2, static bays=5, inspection bays=2, inspection rate=0.01, audit rate=0.02, slot cap/15 min=16, priority queue=False, hold prob=0.0, lane failures=())
- `queue_policy_priority` — Perishable / hazardous cargo (12 %) gets priority at the static scale. (policy=rolling, arrivals/h=60.0×1.0, WIM lanes=2, static bays=5, inspection bays=2, inspection rate=0.01, audit rate=0.02, slot cap/15 min=None, priority queue=True, hold prob=0.0, lane failures=())

## Method and limitations

- Discrete-event model (SimPy): non-homogeneous Poisson arrivals with a synthetic hour-of-day profile; lognormal service times (WIM median 6 s, static scale median 4 min, inspection median 25 min); truck masses from `kifaru_wim_dsp.signal_gen.random_truck`; decisions from the deterministic clearance engine `kifaru.services.clearance_engine.decide` (same code as the platform).
- The baseline scenario is a modelled all-stop station, not an observed one. No field baseline data exists yet (Phase 7).
- Identity confidence, sensor-fault rates and the overload share are assumptions (see config of each scenario).
- Replications differ only by random seed; CIs describe simulation variance, not model-structure uncertainty.

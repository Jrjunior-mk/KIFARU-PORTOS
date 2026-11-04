# Simulation guide — `packages/simulation` (RTM DT-02)

**Status: modelled results only.** Every number produced by `kifaru-sim` comes from a discrete-event model with
synthetic arrivals and assumed service-time distributions. Nothing in it is a measurement of Mariakani, Athi River or
the Port of Mombasa. The platform must collect baseline data in Phase 7 (observed arrivals, static-scale service times,
queue lengths, GREEN/AMBER/RED mix from live passes) before any saving is claimed. Until then the reports answer
"what does the model predict if these assumptions hold", not "what will happen".

## 1. What is modelled

```
arrivals ──► [WIM pre-screen, N lanes] ──GREEN──► exit
                        │── AMBER ──► [static scale, M bays] ──► exit
                        │── RED   ──► [static scale] ──► [inspection bay] ──► exit
                        (optional gate hold for a share of trucks = delayed cargo release)
```

| Element | Model | Default |
|---|---|---|
| Arrivals | Non-homogeneous Poisson (thinning) with a 24-value hour-of-day profile (`model.DEFAULT_TOD_PROFILE`, synthetic) | 60 trucks/h mean, one direction; peak ×1.45 at 08:00 and 16:00 |
| WIM pre-screen | `N` lanes, lognormal service, median 6 s | 2 lanes |
| Static scale | `M` bays, lognormal, median 4 min (σ 0.4) ≈ 13.8 trucks/h/bay | 5 bays (≈ 69/h) |
| Inspection | lognormal, median 25 min; RED trucks + a random sample (`inspection_rate`) | 2 bays, 1 % sample |
| Trucks | `kifaru_wim_dsp.signal_gen.random_truck` (EAC configurations, overload probability) | 15 % overload draw |
| Measurement | k=2 relative uncertainty per axle, sensor fault → `sensor_fault` quality flag, degraded → `sensor_degraded` | 2.5 %, 3 %, 2 % |
| Identity | RFID+ANPR / RFID / ANPR / low confidence; unregistered share | 80/10/8/2 %, 5 % unregistered |
| Decision | `kifaru.services.clearance_engine.decide` — the same deterministic engine the API uses, seeded audit sampler | audit 2 %, identity threshold 0.90 |
| Baseline | `policy="all_stop"`: no pre-screen, every truck queues for the static scale; engine decision computed as a shadow | — |

Collected per truck: arrival, wait at WIM, wait at static, wait at inspection, hold, exit, decision, `stopped`,
`stop_reason`, priority flag, GVM, axle config, rules fired. Per station: queue length of each resource every minute.

## 2. Running scenarios

```bash
# from the repo root, with the venv active (packages/simulation is installed editable)
kifaru-sim list
kifaru-sim run --scenarios all --hours 12 --reps 5 --out packages/simulation/reports/
kifaru-sim run --scenarios rolling_clearance,arrivals_+50 --hours 24 --reps 10 --seed 7 --out /tmp/sim
kifaru-sim run --scenarios all --set arrivals_per_hour=75 --set static_bays=4 --set overload_prob=0.25 --out /tmp/sim
kifaru-sim sumo-export --out /tmp/sumo --hours 12
```

`--set key=value` overrides any `SimConfig` field for every scenario (use `python -c "from kifaru_sim.model import
SimConfig; help(SimConfig)"` for the list). The run always includes `baseline_all_stop` so "stops avoided" can be computed.
Replication `k` uses seed `--seed + k`; the same seed gives byte-identical results (tested).

Programmatic use:

```python
from kifaru_sim import build, run_model
from kifaru_sim.report import compare, to_markdown
res = run_model(build("arrivals_+30", hours=12, seed=1))
print(res.metrics())
print(to_markdown(compare(["rolling_clearance", "static_capacity_-1"], hours=12, reps=5)))
```

### Scenarios

| Name | Meaning |
|---|---|
| `baseline_all_stop` | Pre-platform: every truck stops at the static scale. |
| `rolling_clearance` | Platform policy with default assumptions. |
| `arrivals_+20` / `+30` / `+50` | Demand growth under rolling clearance. |
| `station_lane_failure` | One of two WIM lanes down for 2 h mid-run; trucks in that lane cannot be pre-screened and fall back to the static scale. |
| `inspection_rate_x2` | Physical-inspection sampling and random-audit rate doubled. |
| `static_capacity_-1` | One static bay fewer. |
| `delayed_cargo_release` | 15 % of trucks held at the gate (median 15 min) awaiting cargo release. |
| `dynamic_slot_allocation` | Booking cap of ~110 % of mean demand per 15-min window; excess arrivals are shifted to the next window (booking delay is **not** counted as time in system). |
| `queue_policy_priority` | Perishable / hazardous cargo (12 %) served first at the static scale (`simpy.PriorityResource`). |

Add a scenario by appending to `kifaru_sim/scenarios.py::SCENARIOS` (base config + overrides) and `DESCRIPTIONS`.

## 3. Reading the comparison table

The report (`<out>/<stem>.md` and `.json`; example: `packages/simulation/reports/example-report.md`) has one row per
scenario; cells are **mean ± half-width of the 95 % confidence interval across replications** (Student t).

| Column | Interpretation | Caveats |
|---|---|---|
| Trucks | arrivals over the horizon | depends only on arrival settings; identical across scenarios with the same demand |
| Mean / P90 time in system | arrival → exit, minutes | P90 can be *below* the mean when a few inspected trucks dominate the mean; under rolling clearance the P90 sits inside the stopped 20 %, so it is ≈ static-scale time, not GREEN pass time |
| Mean / max static queue | trucks waiting (not in service), sampled every minute | the main congestion indicator for the all-stop baseline |
| % trucks stopped | share with `stopped=True` (static, inspection, lane fallback or gate hold) | 100 % by definition in the baseline |
| Static-scale utilisation | busy time / (bays × run length) | run length includes the drain after the last arrival |
| Stops avoided vs baseline | paired difference (same seed) in stopped trucks | the primary modelled benefit; not a measured saving |
| Fuel / CO2 (modelled) | `EnvironmentalAgent` factors: 0.35 L per stop-start cycle, 2.5 L/h idling in queue, 2.68 kg CO2/L | **modelled, never report as measured** |
| GREEN / AMBER / RED | engine decision mix | in the baseline this is the shadow decision |

Secondary table: WIM queue, inspection-bay utilisation (watch it under `arrivals_+50` and `inspection_rate_x2` — the
model's bottleneck moves from the static scale to inspection once rolling clearance is in place), priority-cargo P90,
fuel/CO2 saved vs baseline (paired, modelled), drain time after the last arrival.

JSON output contains every replication's metrics, the full scenario configuration, decision mix and the mean static
queue by minute (for plotting).

## 4. Attaching SUMO (optional)

SUMO adds the approach road (platooning, merging of two lanes into the weighbridge exit) that the queueing model abstracts
away. `kifaru_sim/sumo_adapter.py`:

1. `kifaru-sim sumo-export --out dir/` writes `mariakani_trucks.rou.xml` (truck departures from the arrival profile,
   shifted by free-flow travel time), `mariakani.nod.xml` + `mariakani.edg.xml` (netconvert inputs), a minimal
   hand-written `mariakani.net.xml` (2 km two-lane approach, 300 m weighbridge exit lane, through lanes) and `mariakani.sumocfg`.
   For a geometrically faithful network run `netconvert -n mariakani.nod.xml -e mariakani.edg.xml -o mariakani.net.xml`
   or import OSM for the A109 at Mariakani.
2. With SUMO installed (`sumo` on PATH, `SUMO_HOME` set, `pip install traci sumolib`): `run_sumo(sumocfg)` produces
   `tripinfo.xml`; `read_sumo_arrivals(tripinfo)` extracts arrival times on the `weigh_exit` edge; `replay_into_model(cfg, arrivals)`
   runs the SimPy station with those arrivals. `run_with_sumo(cfg, work_dir)` chains all three.
3. Without SUMO (the normal developer case) `sumo_status().message` explains what is missing, the export still works
   and `run_sumo` raises `SumoUnavailable` with the same message. Nothing else in the package depends on SUMO.

## 5. Limitations

- **Synthetic arrivals.** The hour-of-day profile and the 60 trucks/h default are engineering assumptions, not counts.
- **No measured baseline.** The all-stop baseline is itself a model. Phase 7 must record observed queue lengths, static
  service times and the live decision mix; those feed `SimConfig` (service medians/sigmas, overload share, identity mix,
  `tod_profile`) and replace the defaults.
- Service times are lognormal with assumed sigmas; inspection outcomes (offloading, fines) are not modelled beyond bay time.
- The WIM array is never a bottleneck at 6 s median service; lane failure matters through lost pre-screening, not capacity.
- Identity confidence and sensor-fault probabilities are independent draws; correlated failures (weather, power) are not modelled.
- `dynamic_slot_allocation` shifts arrivals; the booking delay borne by transporters is reported only indirectly (drain time).
- Fuel/CO2 use fixed emission factors; vehicle mix, gradient and ambient conditions are ignored. Labelled modelled everywhere.
- Confidence intervals reflect seed-to-seed variance only, not uncertainty in the model structure or its parameters.
- Runtime: ~2.5 ms per truck (dominated by the clearance engine's evidence hashing); 11 scenarios × 5 reps × 12 h ≈ 90 s.

## 6. Tests

```bash
cd packages/simulation && python -m pytest -q
```
Covers: conservation (every truck exits), baseline stops 100 % vs rolling < 50 %, +50 % arrivals raises P90 in the
saturated configuration, lane failure raises the static queue, capacity −1 raises utilisation, hold/priority scenarios
run, determinism with a fixed seed, time-of-day and slot-cap behaviour, report rendering (Markdown + JSON), CLI, and the
SUMO adapter's export/replay/graceful degradation.

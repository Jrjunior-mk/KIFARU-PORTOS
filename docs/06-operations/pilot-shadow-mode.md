# Phase 7 — Pilot Readiness: Shadow-Mode Operation, Fault Testing and Accuracy Benchmarking

Purpose: define how KIFARU PORTOS moves from a verified prototype to a regulator-acceptable pilot without ever letting an
unproven WIM measurement release a truck. Nothing in this document is a result; it is the procedure by which results will
be obtained.

## 1. Shadow mode (mandatory first pilot stage)

| Aspect | Rule |
|---|---|
| Decision enforcement | **None.** The lane signal/VMS is disabled or shows "PRE-SCREEN TEST — FOLLOW NORMAL PROCEDURE". Every truck continues to the static scale exactly as today. |
| Data capture | Every pass produces a full WIM record, identity record, GREEN/AMBER/RED decision and evidence hash, stored with `source=live`. |
| Static pairing | The operator records the static-scale result against the WIM event (`POST /weighing/events/{id}/static-verify`). The ledger stores `wim_error_pct`. |
| Duration | Minimum 4 weeks or 5 000 paired passes per lane, whichever is later, covering wet/dry and day/night pavement temperatures. |
| Exit criteria | See §4. Only after exit criteria are met and the regulator agrees in writing may GREEN decisions be enforced, initially with a reduced GREEN threshold margin. |

## 2. Fault-injection test plan (executed on the lab rig and in shadow mode)

| # | Fault | Injection method | Expected system behaviour | Verified by |
|---|---|---|---|---|
| F1 | Dead piezo channel | Disconnect P1 | `sensor_fault` flag; lane status degraded; decision never GREEN; incident recommended | `test_sensor_fault_never_green`, gateway tests |
| F2 | Noisy channel | Inject 50 Hz / broadband noise on P2 | `sensor_degraded`; AMBER; health reason recorded | DSP tests |
| F3 | Saturation | Over-drive charge amp input | flat-top detection → fault | DSP health check |
| F4 | Loop failure | Short loop L1 | presence missing; speed from piezo rows still valid; `speed_unavailable` only if both rows lost | gateway |
| F5 | RFID reader offline | Power off reader | identity from ANPR only (capped 0.95) → GREEN still possible if ≥ threshold, else AMBER | identity tests |
| F6 | ANPR camera blinded | Cover lens | RFID-only identity | identity tests |
| F7 | Cloned tag | Present a duplicated EPC on a different truck | `conflict` → RED; SecurityAnomalyAgent impossible-travel alert | engine + agent tests |
| F8 | Cloud link down | Pull WAN | gateway keeps deciding; outbox grows; replay on reconnect with no duplicates | gateway outbox tests |
| F9 | Gateway reboot mid-pass | Power cycle | pass discarded safely; next pass normal; outbox intact (SQLite WAL) | gateway |
| F10 | Calibration expiry | Set `valid_to` in the past | QUALITY_BLOCKING → no GREEN | `test_calibration_expiry_blocks_green` |
| F11 | Time drift | Skew gateway clock 5 min | events carry occurred_at and received_at; ledger ordering by seq unaffected | ingest |
| F12 | Database failover | Trigger RDS Multi-AZ failover | API `/ready` fails briefly; ECS keeps tasks; no event loss (gateway outbox) | infra runbook |

## 3. Accuracy benchmark procedure (WIM vs static reference)

1. Population: all shadow-mode passes with a paired static result, excluding passes with any quality flag (reported separately).
2. Per pass: relative GVM error `e = (GVM_wim − GVM_static) / GVM_static`; per axle-group error likewise.
3. Statistics per lane, per speed band (≤ 40, 40–60, 60–80 km/h) and per pavement-temperature band:
   mean error (bias), standard deviation, 95 % interval (empirical 2.5th–97.5th percentiles), and the share of passes within ±5 %.
4. Uncertainty validation: compare the engine's reported expanded uncertainty U with the observed error distribution;
   U must cover ≥ 95 % of observed errors or the Type-B calibration uncertainty is increased until it does.
5. False-clear rate: among GREEN decisions, share whose static GVM or any axle group exceeded the legal limit (with the
   regulator's tolerance). Target ≤ 1 % (engineering target, Master Prompt §12). Also report false-divert rate (AMBER/RED that
   were legal) because it drives the stop-reduction benefit.
6. Identity match rate: share of passes with `confidence ≥ 0.90` and correct vehicle vs operator-confirmed plate. Target ≥ 97 %.
7. Decision latency: `latency_ms` distribution at the gateway (edge) — target ≤ 2 000 ms at P99.
8. Report format: `docs/07-pilot/accuracy-report-<station>-<date>.md` with the tables above and the raw CSV in object storage.

## 4. Exit criteria for enforcing GREEN

All of the following, demonstrated in the shadow report and accepted by the regulator:

- GVM 95 % error interval within ±5 % (or the regulator-agreed band) on unflagged passes, per lane.
- False-clear rate ≤ 1 % with at least 2 000 GREEN-eligible paired passes.
- Identity match ≥ 97 %.
- No unresolved critical security or safety findings from the review (`docs/04-security/`).
- Fault tests F1–F12 passed and documented.
- Operators trained; override procedure (MFA) exercised; incident response plan rehearsed.

## 5. KPIs reported weekly during the pilot

| KPI | Source | Target (engineering, not yet demonstrated) |
|---|---|---|
| Unnecessary stops avoided | GREEN count vs baseline all-stop | ≥ 50 % of baseline stops |
| Mean/P90 time in system | SimPy model calibrated with pilot data, then measured | reported |
| Queue length at peak | `queue_records` observed | reported |
| Modelled fuel/CO2 avoided | environmental agent, labelled modelled | reported |
| Availability (API) | CloudWatch | 99.9 % |

## 6. Baseline data collection (pre-pilot)

Because no measured baseline exists yet, the first two weeks of shadow mode double as baseline measurement: arrival
counts per 15 minutes, static-scale service times, queue length (manual or loop counts), and stop durations. These feed
`packages/simulation` and replace the synthetic arrival profiles.

# KIFARU PORTOS — Maintenance Guide

| Field | Value |
|---|---|
| Document | `docs/06-operations/maintenance.md` |
| Version | 0.1 — 2026-11-04 |
| Scope | Roadside lane hardware, edge gateway, cloud platform (API, PostgreSQL, Redis, S3), cryptographic keys, logs, on-call |
| References | `docs/02-architecture/hardware-architecture.md` (lane layout, signal chain), `docs/02-architecture/cloud-architecture.md`, `docs/04-security/security-controls.md`, `docs/04-security/incident-response-plan.md`, `apps/api/kifaru/routers/stations.py` (calibration API), `packages/wim_dsp/kifaru_wim_dsp/pipeline.py` (health thresholds) |
| Status | Hardware items are **planned procedures** for the Phase 6 lane; nothing has been installed. Software items apply to the current code. AWS items are **designed**, not deployed. |

## 1. Principles

1. **The static scale is the legal reference.** Any WIM maintenance action that could affect accuracy puts the lane in AMBER-only or offline mode first; compliance enforcement never waits on WIM maintenance.
2. **Fail-safe by design.** The DSP pipeline flags unhealthy channels and the clearance engine never issues GREEN with a blocking flag or expired calibration (`clearance_engine.BLOCKING_QUALITY_FLAGS`, `weighing_service._lane_calibration_valid`). Maintenance therefore mostly *restores GREEN capacity*, not safety.
3. **Everything is recorded.** Calibration → `core.calibration_records` (audited); station/lane state → `core.incidents` and `station.failure`/`sensor.health` events; key changes → ledger `signer_key_id`; database work → change log in this file's §11.

## 2. Lane hardware — routine schedule

Component references follow `hardware-architecture.md` §1–§3: loops L1–L3, piezo-quartz rows P1–P3, bending plate BP, IR beam pairs at P1/P3, radar on gantry, ANPR cameras ×2, UHF RFID reader, PT1000 pavement probe at P2, SHT4x ambient T/RH on cabinet, IP66 cabinet with charge amplifiers, anti-alias filters, 2× ADS131M08, STM32H743 DAQ, ESP32 aux node, PoE switch, edge gateway IPC, LTE/fibre router, VMS/lane signal driver, 230 V → surge → 24 V PSU → UPS/LiFePO4.

| Frequency | Task | Component | Acceptance | Record |
|---|---|---|---|---|
| Continuous (automatic) | Channel health per pass: dead (< 50 kg-eq peak), baseline RMS > 800 kg-eq, saturation flat-top, pulse count ≠ consensus (`pipeline.channel_health`) | P1–P3, BP | `sensor_health` all `ok` on ≥ 98 % of passes per day | `weighing_events.sensor_health`; `sensor.health` events |
| Continuous (automatic) | WIM-vs-static error on every AMBER/RED that is statically weighed | Whole lane | Rolling 7-day mean of `wim_error_pct` within ±2 %, P95 within ±5 % | ledger `static.verified` |
| Daily (remote) | Review station dashboard: decisions by class, `method='none'`/`conflict` share, quality-flag rates, heartbeat | Gateway, cameras, RFID | No lane with > 10 % blocking flags; no heartbeat gap > 15 min | Ops log |
| Daily (remote) | Camera image spot-check (exposure, focus, obstruction) for both cameras per lane | ANPR | Plate legible day and night | Ops log |
| Weekly (site) | Visual inspection of pavement around sensors: debris, rutting, cracking, water ponding, sensor flush with surface | P1–P3, BP, loops | No debris; no visible lift; grout intact | Site checklist |
| Weekly (site) | Clean camera housings and IR beam optics; check RFID antenna alignment and cabling | ANPR, IR, RFID | — | Site checklist |
| Weekly (site) | Cabinet: door seal, humidity/temperature (SHT4x log), fans/filters, no condensation, surge-protector status LEDs | Cabinet, PSU, SPD | Internal RH < 70 %; SPD green | ESP32 telemetry (`ts.sensor_readings`), checklist |
| Monthly | UPS/LiFePO4 test discharge (≥ 10 min on battery, record voltage curve); check 24 V rails | Power | Hold-up ≥ specified autonomy; rails within ±2 % | Checklist |
| Monthly | Loop detector sensitivity check with a reference vehicle; IR beam alignment; radar speed vs piezo-derived speed comparison (`speed_mps` from P1/P2 timing vs radar) | L1–L3, IR, radar | Speed agreement within 2 % | Ops log |
| Monthly | Pavement temperature probe vs portable reference thermometer | PT1000 | Within ±1 °C | Calibration note |
| Quarterly | Charge-amplifier offset/drift check (short-circuit input, read baseline); anti-alias filter response spot-check with signal generator at 1 kHz / 4 kHz | AFE | Baseline drift < 0.5 % FS; ≥ −48 dB at 4 kHz | Bench record |
| Quarterly | Firmware/gateway software version audit against release list; verify firmware hash (planned signed firmware) | DAQ, ESP32, gateway | Versions match release | Ops log |
| Semi-annual (≤ 180 days) | **Calibration validity**: perform reference-vehicle calibration before `lane.calibration_valid_to` lapses (§4) | P1–P3, BP | New `CalibrationRecord` per load sensor; lane validity recomputed | `calibration_records` |
| Annual | Full lane survey: sensor profile/levelness relative to pavement (ASTM E1318 pavement smoothness criteria apply to WIM accuracy), grout/sealant renewal, cable insulation resistance, earth-bond resistance, surge protector replacement if indicated | All | Survey report | Site report |
| Annual | Device certificate renewal (§6.3); router firmware; replace cabinet filters | Gateway, router | — | Ops log |
| As needed | Sensor replacement → immediately lane AMBER-only; new calibration record required for the lane to regain GREEN | P*, BP | — | Incident + calibration |

Weather triggers: after heavy rain or flooding inspect sensor grout and cabinet; after resurfacing or pothole repair within 50 m of the rows, treat as "pavement works" and recalibrate (§4.3).

## 3. Sensor health thresholds and what they do

From `packages/wim_dsp/kifaru_wim_dsp/pipeline.py`:

| Condition | Health | Quality flag | Engine effect |
|---|---|---|---|
| Peak |x| < 50 kg-eq on a load channel | `fault` ("no signal (dead channel)") | `sensor_fault` | Blocks GREEN |
| Baseline RMS (first 10 % of window) > 800 kg-eq | `degraded` | `sensor_degraded` | AMBER (`QUALITY_DEGRADED`) |
| > 8 samples at the maximum (flat top) | `fault` (saturation) | `sensor_fault` | Blocks GREEN |
| Pulse count differs from consensus by > 1 | `fault` | `sensor_fault` | Blocks GREEN |
| Pulse count differs by exactly 1 | `degraded` | `sensor_degraded` | AMBER |
| Fewer than 2 good load rows | — | `insufficient_rows` | Blocks GREEN |
| Speed unavailable or outside 3–30 m/s | — | `speed_unavailable` / `speed_out_of_range` | Blocks GREEN |
| GVM expanded uncertainty > 10 % of GVM | — | `high_uncertainty` | AMBER |
| `lane.calibration_valid_to` missing or past | — | `calibration_expired` | Blocks GREEN |

Operators may also set `Sensor.status` through `POST /stations/sensors/{id}/health`; this changes the lane status shown on dashboards and emits `sensor.health`, but it does **not** change decisions — the decision uses the per-pass health computed on the gateway.

## 4. Calibration cadence

### 4.1 Methods supported by the platform (`CalibrationIn.method`)

| Method | When | Notes |
|---|---|---|
| `reference_vehicle` | Commissioning; every ≤ 180 days; after sensor replacement or pavement works | Pre-weighed trucks (ideally two configurations, e.g. 1+1+2 and 1+2+3, loaded near 80 % of limit) make ≥ 10 passes each at low, typical and high lane speeds; gain/offset per channel from the regression against static axle loads; record `reference_mass_kg`, `gain`, `offset`, `uncertainty_pct` |
| `static_scale_comparison` | Continuous (every AMBER/RED weighed statically) and formal quarterly review | Uses `static.verified` ledger entries; no new record unless drift is corrected |
| `shunt` | Quarterly bench check of the bending-plate bridge chain | Shunt resistor across one bridge arm; verifies INA gain and ADC scale, not the sensor |
| `bench` | Laboratory rig (Phase 6) and charge-amplifier checks | Not accepted alone for a highway lane's validity |

### 4.2 Validity window and lane status

`POST /api/v1/stations/sensors/{sensor_id}/calibrations` creates a `CalibrationRecord` with `valid_from = now` and `valid_to = now + valid_days` (default **180**, maximum 730). After each record the lane's `calibration_valid_to` is recomputed as the **minimum** `valid_to` across all load sensors (`piezo_quartz`, `piezo_polymer`, `bending_plate`, `strain_gauge`) on the lane; if any load sensor has no record at all, the lane validity becomes `None` and the engine treats it as expired (`routers/stations.py _recompute_lane_validity`; tested in `test_calibration_expiry_blocks_green`). Consequence: **every load sensor on a lane must have a current record**, and the lane turns AMBER-only automatically on expiry.

Recommended cadence: 180 days maximum; **90 days during the first year** of a new lane (pavement settlement, seasonal temperature extremes); extra reference-vehicle run after the first hot season and the first long rains.

### 4.3 Recalibration triggers

| Trigger | Threshold / event | Action |
|---|---|---|
| Drift | 7-day rolling mean `wim_error_pct` outside ±2 %, or P95 outside ±5 % | Investigate temperature coefficient, cross-row bias (`WeighingIntelligenceAgent.row_bias`), then reference-vehicle calibration |
| Cross-row bias | `row_bias` > 8 % on one row for > 50 passes | Inspect that row; recalibrate or replace |
| Sensor replacement | Any P*/BP replaced | Mandatory before GREEN |
| Pavement works | Any works within 50 m | Mandatory |
| Temperature compensation | Ambient–pavement probe disagreement implausible (> 25 °C) or probe fault | Fix probe; verify `temp_coeff_per_c` (quartz ≈ −0.002/°C in the simulator/calibration defaults; confirm with sensor datasheet) |
| Expiry | `calibration_valid_to` within 14 days | Schedule reference vehicle |

### 4.4 Uncertainty bookkeeping

The DSP combines Type A (spread across rows) and Type B (calibration certificate, `ChannelCalibration.type_b_rel_u`, default 2 % at k = 1) in quadrature and expands with k = 2 (`pipeline.process_pass`). The `uncertainty_pct` entered on a calibration record should be the **expanded** uncertainty of the reference procedure; it is stored for audit and is the intended future source of `type_b_rel_u` per channel (today the simulator uses a fixed 0.02).

## 5. Software patching

| Layer | Cadence | Procedure | Rollback |
|---|---|---|---|
| Python dependencies (`apps/api`, `packages/*`) | Monthly; critical CVEs within 72 h | `pip-audit`/Dependabot (planned in CI); commit a lockfile (`uv.lock`); run all three test suites (`pytest` in `apps/api`, `packages/wim_dsp`, `packages/ai_agents`); deploy to staging; smoke `/health`, `/ready`, `/admin/ledger/verify` | Previous container image tag |
| Database schema | With releases | `alembic upgrade head` in a maintenance window (or online when additive); migrations are forward-only in production; take an RDS snapshot first **(AWS, designed)** | `alembic downgrade` only in staging; production uses snapshot restore |
| Container base images | Monthly | Rebuild from pinned base; scan (Trivy/ECR scan, planned) | Previous tag |
| Edge gateway OS and Python | Quarterly, or 72 h for critical | Staged rollout: one lane first, shadow-mode 50 passes, then fleet | A/B partitions (Phase 6 design) |
| DAQ / ESP32 firmware | On release | Bench test on lab rig; HIL; one lane in shadow mode; signed image (planned) | Keep previous image; DAQ supports dual-bank update (design) |
| Dashboards (SPA) | With releases | CloudFront invalidation; cache-busting hashes | Previous build in S3 |
| Managed services (RDS minor versions, Redis) | Maintenance window monthly **(AWS, designed)** | Auto minor upgrade enabled on staging first | Managed |

Every production deployment records: image digest, Alembic head, `KIFARU_SIGNING_KEY_ID`, limits version (`services/limits.py DEFAULT_LIMITS.version`), engine version (`clearance_engine.ENGINE_VERSION`), DSP version (`pipeline.PIPELINE_VERSION`). Decisions store `limits_version` and `engine_version`, so a release can be correlated with its decisions.

## 6. Key and secret rotation

| Secret | Where | Cadence | Compromise response |
|---|---|---|---|
| `KIFARU_JWT_SECRET` | Secrets Manager → ECS env (designed); `.env` locally | 6 months | Immediately |
| `KIFARU_SIGNING_SEED_B64` (+ `KIFARU_SIGNING_KEY_ID`) | Same | 12 months, **only after the key registry exists** (§6.2) | Immediately, with key registry and re-anchoring |
| Device X.509 certificates | IoT Core (designed) | 12 months | Revoke cert; change `Lane.device_id` as interim |
| RDS credentials | Secrets Manager rotation / IAM auth (designed) | 90 days / none with IAM | Immediately |
| Integration tokens `KIFARU_INT_<NAME>_TOKEN`, `KIFARU_AT_API_KEY` | Env from Secrets Manager | Per provider, ≤ 12 months | Immediately |
| User TOTP secrets | `users.mfa_secret` | On user request / device loss | Admin disables MFA → user re-enrols |
| Demo seed password | `seed.py DEMO_PASSWORD` | Never used in production; production users created via `/admin/users` | n/a |

### 6.1 Rotating the JWT secret

1. Generate: `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
2. Store the new value in Secrets Manager; update the ECS task definition; deploy all API/realtime tasks together (they share the secret).
3. Effect: every outstanding **access token** fails validation immediately (`jwt.InvalidTokenError` → 401). **Refresh tokens are unaffected** — they are random strings whose SHA-256 is stored in `core.refresh_sessions`, not JWTs. Clients call `POST /auth/refresh`, receive a new access token signed with the new secret, and continue. Users therefore see at most one transparent refresh, and WebSocket clients reconnect with the new token.
4. Verify: login works; `GET /auth/me` with an old token returns 401; WS reconnects.
5. Record in the ops change log (not the ledger — the JWT secret does not sign ledger data).

Note: in `dev`/`test` with no `KIFARU_SIGNING_SEED_B64`, the signing key is **derived from the JWT secret** (`security.get_signing_key`), so rotating the dev JWT secret also rotates the dev signing key. This is why staging/prod must set the seed explicitly (the code refuses to start otherwise).

### 6.2 Rotating the Ed25519 signing seed — read before doing this

What the key signs: ticket payloads (`services/tickets.py`), decision summaries `{"evidence_hash", "decision"}` (`weighing_service.py`) and ledger rows `{"hash": h}` (`services/ledger.py`). Each ticket and ledger row stores `signer_key_id`; ticket payloads additionally embed `public_key`.

Current verification behaviour (code as reviewed):

| Artefact | How it is verified | After rotation |
|---|---|---|
| Tickets | `tickets.verify()` uses the **public key embedded in the payload** | Old tickets still verify — but this also means the verifier trusts whatever key the document names (`threat-model.md` F1) |
| Ledger | `ledger.verify_chain()` uses the **current** process key for every row | **Old rows fail** (`signature invalid at seq N`) — rotation would make the chain look tampered |
| Decisions | Signature stored; no verify endpoint yet | n/a |

Therefore, **before the first rotation**, implement a key registry: a table or configuration mapping `signer_key_id → {public_key_b64, valid_from, valid_to, status}`; `verify_chain` and `tickets.verify` look up the row's `signer_key_id` and use that public key, rejecting unknown or revoked IDs; the embedded `public_key` in tickets becomes informational and must equal the registry value. Keep old public keys **forever** (tickets may be presented years later; ledger rows are retained 7 years). Only the private seed of the retired key is destroyed.

Rotation procedure (once the registry exists):

1. Record the current chain head: `GET /admin/ledger/verify` → `head_hash`, `total`, `signer_key_id`. Anchor externally (S3 Object Lock / e-mail to regulator — planned).
2. Generate: `python -c "import os,base64; print(base64.b64encode(os.urandom(32)).decode())"`; derive and publish the public key; add a registry row with a new `signer_key_id` (e.g. `platform-2027-01`) and `valid_from = now`.
3. Set `KIFARU_SIGNING_SEED_B64` and `KIFARU_SIGNING_KEY_ID` together in Secrets Manager; deploy **all** API tasks in one rolling update (mixed keys for a few minutes are acceptable because every row records its key id).
4. Mark the old key `status=retired, valid_to=now` in the registry; destroy the old seed from Secrets Manager after 30 days.
5. Verify: `GET /admin/ledger/verify` → `ok:true` across the boundary; verify a pre-rotation and a post-rotation ticket via `/tickets/verify/{token}`; `signer_key_id` in `/admin/system/health` shows the new ID.
6. Append a ledger note `key.rotated {old_id, new_id, new_public_key}` (ledger type to be added) so the rotation itself is in the chain.

If a rotation is forced **before** the registry exists (compromise), expect `verify_chain` to fail for all pre-rotation rows; export and anchor the chain first, and document the boundary `seq` in the incident record (`incident-response-plan.md` IR-05 step 3).

### 6.3 Device certificates (designed)

Per lane gateway: generate key on device, CSR to the platform PKI/IoT Core, 12-month validity, renewal 30 days before expiry, revocation list consumed by IoT Core. Interim without IoT Core: `Lane.device_id` is the only binding; rotate it on suspicion.

## 7. Database maintenance (PostgreSQL 16)

| Task | Cadence | Detail |
|---|---|---|
| Autovacuum tuning | At go-live, review quarterly | Append-heavy tables `core.ledger_events`, `core.weighing_events`, `core.axle_measurements`, `core.audit_events`, `core.identity_events`: lower `autovacuum_vacuum_scale_factor` (e.g. 0.02) and `autovacuum_analyze_scale_factor` (0.01) so statistics stay fresh for the time-ordered indexes (`ix_ledger_type_ts`, `occurred_at`, `decided_at`) |
| Manual `VACUUM (ANALYZE)` | After bulk purges (§8 retention jobs) | Prevent bloat after deletes of `notifications`, `refresh_sessions`, evidence references |
| Bloat and index health | Monthly | `pgstattuple` / `pg_stat_user_tables`; `REINDEX CONCURRENTLY` indexes with > 30 % bloat |
| Partitioning `ts.sensor_readings` | Monthly partitions via `pg_partman` once available on RDS (`alembic/versions/0001_initial.py` comment) | Pre-create 3 months ahead; detach/drop partitions older than 24 months (DPIA §8); until `pg_partman` is confirmed on the target instance, use native `PARTITION BY RANGE (ts)` with a monthly cron |
| Yearly partitions for `weighing_events`/`ledger_events` | Design decision before pilot | Keeps 7-year retention manageable; archive detached partitions to S3 Glacier |
| Growth monitoring | Weekly | Each lane pass writes 1 `weighing_events`, N `axle_measurements`, 1 `identity_events`, 1 `clearance_decisions`, 1 `digital_tickets`, 2 `ledger_events`. At an assumed 3 000 passes/day that is roughly 7 000 ledger rows/day (~2.5 M/year) with JSON payloads — plan storage accordingly (estimate, not measured) |
| Identity lookup performance | Before pilot | `services/identity.resolve` scans **all** vehicles and normalises plates in Python on every pass. Add a stored `plate_normalised` column with a unique index and query it directly (code change; tracked as engineering debt) |
| Ledger append serialisation | Before pilot | Wrap `ledger.append` in `pg_advisory_xact_lock` to prevent duplicate `seq` under concurrency (`threat-model.md` F2) |
| Integrity check | Hourly | `GET /admin/ledger/verify` (automate; alarm on `ok=false`) |
| Backups (designed) | Daily automated (35 days) + PITR; daily `pg_dump` to S3 cross-region | Verify backup job completion daily |
| Restore drill | Quarterly | Restore latest snapshot to an isolated instance; run `verify_chain`; time against RTO 4 h / RPO 15 min |
| Statistics for forecasting | Monthly | Ensure `queue_records` retains ≥ 48 observations per station so `TrafficForecastAgent` can use gradient boosting rather than Holt/persistence |
| SQLite (dev only) | — | `PRAGMA journal_mode=WAL` is set by `db.py`; delete `kifaru_dev.db` and re-run `python -m kifaru.seed` to reset |

## 8. Log and data retention

| Stream | Hot retention | Archive | Notes |
|---|---|---|---|
| Application logs (structlog JSON) | 90 days (CloudWatch Logs, designed) | 1 year S3 | No request bodies logged; **WS tokens may appear in ALB access logs via query string** — set ALB access-log retention to 30 days and treat as sensitive until `routers/ws.py` moves to first-message auth |
| Audit stream (`audit_events`) | In DB 7 years (DPIA §8) | S3 Glacier yearly | Export yearly partition |
| Ledger (`ledger_events`) | 7 years | Glacier + Object Lock | Never purge; archive detached partitions with head-hash manifest |
| ALB/WAF/CloudFront access logs | 30 days | — | Designed |
| IoT Core / MQTT logs | 30 days | — | Designed |
| Gateway local logs | 14 days rolling | — | Disk budget |
| ANPR evidence images | 30 days (2 years if linked to AMBER/RED/dispute) | — | S3 lifecycle (DPIA §8) |
| Raw signal windows | 90 days | — | S3 lifecycle |
| Backups | 35 days (RDS), 12 monthly dumps | — | Designed |

The authoritative retention schedule is proposed in `docs/04-security/dpia.md` §8 and must be ratified in `docs/02-architecture/database-erd.md` §3 (file not yet in the repository).

## 9. On-call

| Item | Arrangement |
|---|---|
| Coverage | Platform: 24×7 for SEV-1/2 (`incident-response-plan.md` §2); business hours for SEV-3/4. Stations: weighbridge staff on site per KeNHA shift pattern; platform on-call supports remotely |
| Rota | Primary + secondary engineer, weekly rotation; hand-over Monday 09:00 EAT with checklist (§9.1) |
| Paging | Alarms → SNS → phone/SMS (designed); until then, e-mail + WhatsApp group monitored by the primary |
| Response targets | SEV-1 acknowledge 15 min; SEV-2 30 min; SEV-3 next business day |
| Escalation | Primary → secondary (15 min no-ack) → platform lead → owner |
| Runbooks | `incident-response-plan.md` §5 (IR-01…IR-06); this document §4 (recalibration), §6 (rotation), §7 (DB) |
| Station fallback authority | The weighbridge operator on shift may set any lane to AMBER-only/offline (`POST /stations/{id}/status`) without approval; restoring `operational` after a sensor fault requires a current calibration record and 50 shadow-mode passes |

### 9.1 Hand-over checklist

- [ ] Open incidents (`GET /admin/incidents?status=open`) reviewed
- [ ] `GET /admin/ledger/verify` → `ok:true`, head hash noted
- [ ] `GET /admin/system/health` → database ok, Redis/MQTT configured as expected for the environment
- [ ] Lanes with `calibration_valid_to` within 30 days listed and scheduled
- [ ] Quality-flag and `method='conflict'` rates per lane within normal range
- [ ] Backup job success for the last 7 days (designed)
- [ ] Pending patches / CVEs noted
- [ ] Secrets or certificates expiring within 60 days noted

## 10. Maintenance calendar (summary)

| When | What |
|---|---|
| Daily | Dashboard review; camera spot-check; backup success |
| Weekly | Site visual inspection; cabinet climate; hand-over checklist |
| Monthly | UPS test; loop/IR/radar checks; pavement probe check; dependency patching; DB bloat check; EPRA diesel price update for the emissions model |
| Quarterly | AFE bench checks; firmware/version audit; autovacuum review; restore drill; threat-model review of changed modules |
| Semi-annual | Reference-vehicle calibration (≤ 180 days); JWT secret rotation |
| Annual | Lane survey; device certificates; signing-key rotation (after key registry); DPIA review |

## 11. Change log

| Date | Change | By |
|---|---|---|
| 2026-11-04 | Initial version aligned with Phase 2 code (`clr-1.2.0`, `wim-dsp-0.3`, API 0.1.0) | Technical writer |

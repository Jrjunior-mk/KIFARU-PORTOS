# KIFARU PORTOS — Requirements Traceability Matrix (RTM)

Legend — **Disp.**: P = Preserve (from original RCS), E = Enhance, R = Replace, N = New.
**Phase**: implementation phase per `docs/02-architecture/roadmap.md`. **Status**: Planned / In progress / Done / Blocked (reason).
Source "MP §n" = Master Prompt section n. "RCS" = original Rolling Clearance System concept (reconstructed, see `00-source-review.md`).

## A. Core rolling clearance (original concept)

| ID | Requirement | Source | Disp. | Phase | Component | Acceptance criteria | Status |
|---|---|---|---|---|---|---|---|
| RCS-01 | Identify approaching trucks automatically (ANPR + RFID) | RCS; MP §2 | P | 2 (sim), 6 (hw) | `kifaru/identity`, `ai_agents/vehicle_identity` | Identity event with plate, RFID, confidence produced for every lane pass | Done (simulated identity; hardware Phase 6) |
| RCS-02 | Measure axle loads and GVM while moving | RCS; MP §2, M1 | E | 2 (sim), 6 (hw) | `packages/wim_dsp`, firmware | Axle loads, spacing, speed, GVM, uncertainty produced per pass | Done (simulated signals through DSP; hardware Phase 6) |
| RCS-03 | Evaluate measurement confidence and compliance | MP §2, M2 | E | 2 | `kifaru/clearance` | Every decision carries expanded uncertainty U (k=2) and quality flags | Done |
| RCS-04 | Clear eligible trucks without stops (GREEN) | RCS; MP §2 | P | 2 | `kifaru/clearance` | GREEN only when GVM+U and each axle-group+U are within legal limit, identity above threshold, sensors healthy, not watch-listed, not audit-sampled | Done |
| RCS-05 | Direct uncertain trucks to static verification (AMBER) | RCS; MP §2 | P | 2 | `kifaru/clearance` | AMBER when limits within margin, identity low, or quality degraded | Done |
| RCS-06 | Flag suspected non-compliance (RED) | RCS; MP §2 | P | 2 | `kifaru/clearance` | RED when measured minus U still exceeds limit, or watch-list / seal / declaration mismatch | Done |
| RCS-07 | Static weighing remains legal authority | RCS; MP §3 M2 | P | all | policy + `clearance` | No API path issues a legally binding certificate from WIM alone; ticket type `prescreen` vs `static_certified` | Done |
| RCS-08 | Complete evidence record per decision | MP §3 M2 | E | 2 | `kifaru/clearance`, `kifaru/ledger` | Decision row links weighing event, identity, rules fired, thresholds, sensor health, signed hash | Done |
| RCS-09 | Never auto-clear when quality insufficient | MP §3 M2 | E | 2 | `kifaru/clearance` | Unit test: any quality flag means not GREEN | Done (tested) |
| RCS-10 | Random audit selection | MP §3 M2 | N | 2 | `kifaru/clearance` | Configurable audit rate; selection logged with seed | Done |
| RCS-11 | Digital weighing ticket | RCS; MP §3 M5 | E | 2 | `kifaru/tickets` | Signed JSON + QR; verifiable via public endpoint | Done |
## B. Module 1 — WIM infrastructure

| ID | Requirement | Source | Disp. | Phase | Component | Acceptance criteria | Status |
|---|---|---|---|---|---|---|---|
| WIM-01 | Multi-sensor lane: piezo, bending plate/strain gauge, loops, radar, IR, ANPR, RFID, pavement temp, ambient T/RH, axle/wheel detectors | MP M1 | R | 6 | `docs/03-hardware`, firmware | Sensor architecture doc + BOM; firmware channel map | Planned |
| WIM-02 | 5–10 kHz/channel acquisition, anti-alias, 24-bit ADC | MP M1 | R | 6 | firmware `stm32-wim-daq` | ADS131M08 at 8 kSPS/ch verified on bench | Planned |
| WIM-03 | No HX711 on highway lane | MP M1 | R | 6 | hardware doc | BOM excludes HX711 for lane; allowed only on lab aux | Planned |
| WIM-04 | Charge amplifier for piezo-quartz | MP M1 | N | 6 | `docs/03-hardware/analog-front-end.md` | LTspice sim + bench noise floor | Planned |
| WIM-05 | DSP: axle detection, spacing, speed, GVM, classification, temperature and dynamic compensation, uncertainty, sensor health | MP M1 | E | 2 (python), 6 (fw) | `packages/wim_dsp` | Unit tests on synthetic + recorded signals; error vs reference reported | Done (Python reference, 24 tests) |
| WIM-06 | STM32 primary, ESP32 auxiliary | MP M1 | N | 6 | firmware | Build passes; HIL test | Planned |
| WIM-07 | Sensor health monitoring | MP M1 | N | 2/6 | `wim_dsp.health`, `kifaru/stations` | Health states OK/DEGRADED/FAULT with reasons | Done (health flags + sensor status API) |
## C. Module 3 — Traffic and queue intelligence

| ID | Requirement | Source | Disp. | Phase | Component | Acceptance | Status |
|---|---|---|---|---|---|---|---|
| TRQ-01 | Forecast arrivals, queue length, utilisation, processing time at 15/30/60/120 min | MP M3 | N | 4 | `ai_agents/traffic_forecast` | Forecast endpoint returns 4 horizons with intervals; backtest MAE reported | Done (HGB/Holt/persistence by data volume; backtest on real data pending) |
| TRQ-02 | Dynamic weighing-slot allocation | MP M3 | N | 3 | `kifaru/queue` | Slot assigned to appointment; conflicts rejected | Done |
| TRQ-03 | Recommend authorised alternative stations | MP M3 | N | 4 | `ai_agents/queue_optimizer` | Only stations flagged `alt_allowed` recommended | Done (agent; alt_allowed enforced) |
| TRQ-04 | Notify transporters/dispatchers of slot and wait | MP M3 | N | 3 | `kifaru/notifications` | Notification record + WS push + SMS adapter | Done (WS + inbox; SMS adapter mock) |
## D. Module 4 — Backhaul

| ID | Requirement | Source | Disp. | Phase | Component | Acceptance | Status |
|---|---|---|---|---|---|---|---|
| BKH-01 | Identify empty trucks / completing deliveries / return cargo | MP M4 | N | 4 | `kifaru/backhaul` | Query returns candidate trucks with capacity and location | Done |
| BKH-02 | Matching optimisation (payload, dims, type, compatibility, destination, extra km, deadline, fuel, driver hours, revenue) | MP M4 | N | 4 | `ai_agents/backhaul_matcher` | Deterministic score with explanation; unit tests | Done (tested) |
| BKH-03 | Offer, match, accept/reject, assign, track | MP M4 | N | 4 | `kifaru/backhaul` | State machine enforced in API | Done |
| BKH-04 | No automatic commercial assignment without user approval | MP M4 | N | 4 | `kifaru/backhaul` | Assignment requires acceptance by both parties | Done (tested) |
| BKH-05 | Report extra km, fuel cost, revenue, emissions avoided | MP M4 | N | 4 | `kifaru/backhaul`, `environment` | Fields present with formula reference | Done |
## E. Module 5 — Digital cargo passport

| ID | Requirement | Source | Disp. | Phase | Component | Acceptance | Status |
|---|---|---|---|---|---|---|---|
| DCP-01 | Unique shipment identity linking truck, trailer, container, RFID, declaration, seal, VGM, weighings, tickets, status, history | MP M5 | N | 2 | `kifaru/shipments` | Passport endpoint aggregates all links | Done |
| DCP-02 | QR verification | MP M5 | N | 2 | `kifaru/tickets` | Public verify endpoint validates signature | Done (public verify + QR) |
| DCP-03 | Signed, tamper-evident event ledger (no blockchain) | MP M5 | N | 2 | `kifaru/ledger` | Hash-chained events; chain verification endpoint | Done (chain verify endpoint, tested) |
## F. Module 6 — Predictive release

| ID | Requirement | Source | Disp. | Phase | Component | Acceptance | Status |
|---|---|---|---|---|---|---|---|
| PRL-01 | Predict processing/release time with confidence range and reasons | MP M6 | N | 4 | `ai_agents/release_predictor` | Prediction with P10/P50/P90 and stage reasons | Done (priors; learns from platform history) |
| PRL-02 | No claim of government data without authorised integration | MP M6 | N | all | adapters | All government adapters default to `mode=mock` and label output | Done (adapters mock by default) |
## G. Module 7 — Small cargo owner

| ID | Requirement | Source | Disp. | Phase | Component | Acceptance | Status |
|---|---|---|---|---|---|---|---|
| SCO-01 | Mobile-first register/track/notify | MP M7 | N | 3 | `apps/web` (PWA), `apps/mobile` | Lighthouse mobile pass; PWA installable | Planned |
| SCO-02 | Low-bandwidth, SMS/USSD-compatible notifications | MP M7 | N | 3 | `kifaru/notifications` SMS adapter | 160-char templates; USSD menu spec | Planned |

## H. Module 8 — Environmental

| ID | Requirement | Source | Disp. | Phase | Component | Acceptance | Status |
|---|---|---|---|---|---|---|---|
| ENV-01 | Estimate idling fuel, empty km, detours, queue emissions, savings, CO2 | MP M8 | N | 4 | `kifaru/environment` | Formulas and factors in `docs/.../emissions-model.md`; outputs labelled *modelled* | Done (labelled modelled) |
## I. Module 9 — Multi-agent AI

| ID | Requirement | Source | Disp. | Phase | Component | Acceptance | Status |
|---|---|---|---|---|---|---|---|
| AGT-01 | Ten agents + orchestrator with responsibilities, I/O, API, confidence, errors, logging, tests, explainability | MP M9 | N | 4 | `packages/ai_agents` | Each agent implements the `Agent` protocol; orchestrator runs pipeline; tests | Done (10 agents + orchestrator, tests) |
| AGT-02 | AI never overrides deterministic legal/safety rules | MP M9 | N | 2 | `kifaru/clearance` | Agent outputs are advisory inputs; rule engine is final | Done (engine is rule-based) |
## J. Cloud, real-time, integrations

| ID | Requirement | Source | Disp. | Phase | Component | Acceptance | Status |
|---|---|---|---|---|---|---|---|
| CLD-01 | Provider evaluation and selection documented | MP §4 | N | 1 | `docs/02-architecture/cloud-architecture.md` | Done in this phase | Done |
| CLD-02 | Terraform for dev/staging/prod; ECS Fargate, RDS, Redis, IoT Core, S3, CloudFront, Route53, ACM, CloudWatch, Secrets, WAF, SQS | MP §4 | N | 2 | `infra/terraform` | `terraform validate` passes; plan documented | Done (12 Terraform modules, 3 env roots + bootstrap; fmt and validate pass; no apply without owner AWS account) |
| CLD-03 | Actual deployment verified | MP §4 | N | 2 | — | **Blocked: requires owner's AWS account credentials** | Blocked: requires owner's AWS account; deployment guide ready |
| CLD-04 | Edge store-and-forward during outage | MP §4 | N | 3/6 | `edge/gateway` | Outage test: no event loss | In progress (gateway outbox in edge/gateway; HIL test Phase 6) |
| CLD-05 | Docker + CI/CD (GitHub Actions) | MP §4 | N | 2 | `infra/docker`, `.github` | CI green on push | Done (Dockerfiles, Compose, GitHub Actions ci.yml + deploy.yml with OIDC; images not built locally — no Docker) |
| RTC-01 | MQTT (devices), WebSocket (dashboards), REST, queue, webhooks, Redis | MP §5 | N | 2/3 | `kifaru/realtime` | Dashboards update without refresh | Done (REST, WS, Redis fan-in/out, MQTT and SQS ingest workers) |
| RTC-02 | 13 event categories | MP §5 | N | 2 | `kifaru/events` | Enum + schema per event | Done |
| INT-01 | Adapters: KeNHA, KPA, KRA, NTSA, customs, fleet mgmt, WMS, payments, SMS/email, maps, telematics — mock by default | MP §5 | N | 5 | `kifaru/integrations` | Adapter interface; health endpoint; no fabricated endpoints | Done (12 adapters registered, mock by default, mode switch + health endpoint; no real endpoints fabricated) |
## K. Applications, database, twin, hardware, security, testing, docs

| ID | Requirement | Source | Disp. | Phase | Component | Acceptance | Status |
|---|---|---|---|---|---|---|---|
| APP-01..07 | Port control, weighbridge operator, transporter, driver, cargo owner, warehouse, admin dashboards — all wired to real APIs | MP §7 | N | 2–5 | `apps/web` | No decorative controls; every action hits an API | Planned |
| APP-08 | Driver app: no phone interaction while driving (voice/large-tile, auto-advance) | MP §7 | N | 3 | `apps/mobile` | UX review checklist | Planned |
| DB-01 | Normalised schema for all 30 listed entities, PII separated, indexes, migrations, retention | MP §8 | N | 2 | `apps/api/alembic`, `docs/.../database-erd.md` | Alembic upgrade head clean; PII in `pii` schema | Done (Alembic 0001 verified up/down on SQLite; PostgreSQL run pending) |
| DT-01 | Three.js port twin bound to live events; simulation-mode banner | MP §9 | N | 5 | `apps/web/twin` | Banner when source is not live | Planned |
| DT-02 | SimPy/SUMO scenarios (+20/30/50 %, failure, inspection rate, capacity, release delay, slot policies) with comparative reports | MP §9 | N | 5 | `packages/simulation` | CLI produces comparison table | Done (SimPy, 11 scenarios, comparison report with CIs; SUMO adapter degrades gracefully) |
| HW-01..15 | 15 hardware deliverables with real calculations; lab rig distinguished from certified equipment | MP §10 | N | 1 (arch), 6 (detail) | `docs/03-hardware` | Calculations reproducible | Planned |
| SEC-01 | RBAC, MFA (privileged), Argon2, TLS, encryption at rest, device certs, audit, rate limit, validation, sessions, backup encryption, retention, privacy-by-design, DPA 2019 | MP §11 | N | 2+ | `kifaru/auth`, docs | Threat model doc; tests | Done for Phase 2 (threat model, controls catalogue, DPIA, IR plan; PII encryption, key pinning, MFA enrolment, deployment guard); TLS/KMS/device certs in Terraform |
| TST-01 | Unit/integration/API/E2E/DB/load/security/fault/outage/sync/AI validation | MP §12 | N | 2+ | `apps/api/tests`, CI | CI matrix | In progress (57 API/security/worker, 24 DSP, 8 agent, 15 simulation tests; migrations on SQLite+PostgreSQL; load harness; E2E/outage/HIL pending) |
| TST-02 | Targets: latency 2 s, WIM ±5 % at 95 %, false-clear 1 %, identity 97 %, availability 99.9 %, stops −50 % — remain targets until measured | MP §12 | N | 7 | benchmarks | Reported with evidence only | Planned |
| DOC-01 | 42-section engineering report | MP §13 | N | 7 (draft from 1) | `docs/05-report` | All sections present | Done (draft: 42-section engineering report, docs/05-report) |
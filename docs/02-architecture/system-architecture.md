# KIFARU PORTOS — System Architecture

## 1. Architectural style

KIFARU PORTOS is an **event-driven, edge-plus-cloud platform**. Measurement and the time-critical clearance decision happen at
the **roadside edge** (deterministic, ≤ 2 s, works offline). Everything else — fleet, cargo, queues, prediction, marketplace,
dashboards — runs in the **cloud core**. The two are joined by an **event bus** (MQTT at the edge, SQS/Redis streams in the cloud)
and a **signed event ledger** so that every operational fact has one authoritative, auditable record.

The cloud backend starts as a **modular monolith** (one FastAPI deployable, strictly separated bounded contexts) and is split into
services only where load or isolation demands it (ingest, realtime gateway, AI workers). This is deliberate: a 10-person team
cannot operate 30 microservices, and bounded-context discipline inside one process gives the same later-extraction path at a
fraction of the operational cost.

## 2. Layered view

```
┌──────────────────────────────── PRESENTATION ────────────────────────────────┐
│ Port Control │ Weighbridge Op │ Transporter │ Driver (mobile) │ Cargo Owner │ Warehouse │ Admin │ Digital Twin (Three.js) │
└───────────────▲──────────────────────────▲─────────────────────────▲────────┘
                │ REST (JSON)              │ WebSocket (live)          │ Webhooks / SMS
┌───────────────┴──────────────────────────┴─────────────────────────┴────────┐
│                               CLOUD CORE (AWS af-south-1)                     │
│  API (FastAPI)  ── bounded contexts: auth · fleet · stations · weighing ·     │
│                    clearance · tickets · shipments · queue · backhaul ·        │
│                    notifications · environment · integrations · ledger · admin │
│  Realtime gateway (WS fan-out from Redis pub/sub)                              │
│  Workers (SQS consumers): forecasting · release prediction · backhaul matching │
│  AI Orchestrator (packages/ai_agents) — advisory only                          │
│  PostgreSQL (RDS) · Redis (ElastiCache) · S3 · IoT Core · SQS · Secrets        │
└───────────────▲──────────────────────────────────────────────────────────────┘
                │ MQTT/TLS (mutual, X.509 device certs), store-and-forward
┌───────────────┴──────────────────────────────────────────────────────────────┐
│                              ROADSIDE EDGE (per lane)                          │
│  Edge gateway (Linux IPC, Python): local clearance engine mirror, ANPR/OCR,   │
│  RFID, local DB (SQLite WAL), sync agent, VMS/signal driver                    │
│  WIM DAQ (STM32H7 + ADS131M08): piezo/bending-plate/loop/IR/radar acquisition, │
│  axle detection, speed, raw-to-engineering units, health, CAN/Ethernet uplink  │
│  ESP32 aux nodes: pavement/ambient temperature, humidity, enclosure monitoring  │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 3. Bounded contexts (API modules)

| Context | Owns | Key invariants |
|---|---|---|
| `auth` | users, roles, orgs, sessions, MFA, device identities | Argon2id hashes; privileged roles require MFA; JWT access (15 min) + rotating refresh |
| `fleet` | vehicles, trailers, drivers, RFID tags, fleets | Plate + RFID uniqueness; axle configuration declared per vehicle |
| `stations` | weighing stations, lanes, sensors, calibration records, health | Station capacity; `alt_allowed` flag; calibration validity window |
| `weighing` | weighing events, axle measurements, raw-signal references | Immutable once committed; links to lane + sensor set + calibration |
| `identity` | identity events (ANPR, RFID), fusion & confidence | Confidence ∈ [0,1]; evidence images in S3 |
| `clearance` | decisions GREEN/AMBER/RED, rules fired, evidence | **Deterministic rule engine; AI inputs advisory; no GREEN under degraded quality** |
| `tickets` | digital weighing tickets (prescreen / static_certified), QR, signatures | Ed25519 signed; public verify |
| `shipments` | shipments, containers, declarations, seals, VGM, cargo passport, processing events | Passport aggregates; stage machine |
| `queue` | queue records, appointments/slots, station load | Slot capacity per 15-min window |
| `backhaul` | offers, matches, assignments, deliveries | Human acceptance required for assignment |
| `notifications` | templates, channels (WS, SMS, email, webhook), delivery log | Idempotent sends |
| `environment` | emissions model runs, reports | Outputs labelled *modelled* |
| `integrations` | adapters + health, mock/real mode | No real endpoint without config + credentials |
| `ledger` | hash-chained signed event log | Append-only; chain verify |
| `realtime` | event publication, WS subscriptions | Topic ACL by role/org |
| `admin` | audit queries, system health, config | Audit on every privileged write |

## 4. End-to-end rolling clearance flow (happy path, ≤ 2 s budget)

```
t0      loop/IR: TRUCK_DETECTED  ──► edge gateway opens a "pass" context
t0+Δ    DAQ streams axle pulses; ANPR triggers on loop; RFID read on approach
t0+~1s  last axle leaves sensor row → DAQ emits WimMeasurement{axles[], spacing[], speed, gvm, U, quality, health}
        gateway fuses identity (RFID⊕ANPR) → IdentityResult{vehicle_id?, confidence, evidence}
        gateway runs ClearanceEngine.decide(measurement, identity, vehicle_profile, limits, watchlist, audit_rng)
        → Decision{GREEN|AMBER|RED, rules_fired[], margins, evidence_hash}
t0+~1.3s signal/VMS shows lane instruction; local ledger append; ticket drafted
t0+…    MQTT publish (QoS1): truck.detected, truck.identified, weighing.completed, clearance.decided
cloud   ingest → persist → ledger append → Redis publish → WS fan-out → dashboards; SQS jobs (forecast, env, passport update)
```
Offline: identical path; events queue in SQLite outbox; sync on reconnect with idempotency keys (`event_id` ULID).

## 5. Event catalogue (RTC-02)

`truck.detected`, `truck.identified`, `weighing.started`, `weighing.completed`, `clearance.decided`, `truck.diverted`,
`truck.released`, `cargo.verified`, `cargo.status_changed`, `queue.updated`, `station.failure`, `backhaul.opportunity`,
`shipment.delivered`. Every event: `{event_id (ULID), type, occurred_at, station_id?, org_id?, payload, producer, schema_version, prev_hash, hash, signature}`.

## 6. AI placement

All agents in `packages/ai_agents` implement one `Agent` protocol (`run(inputs) -> AgentResult{output, confidence, explanation, warnings}`).
The orchestrator composes them per trigger (e.g. `weighing.completed` → identity agent → anomaly agent → clearance engine (not an agent)).
**The clearance engine is not an AI agent.** It is a rule engine whose inputs may include agent outputs (identity confidence,
anomaly score) but whose thresholds are configuration, not learned.

## 7. Key cross-cutting decisions

| Decision | Choice | Reason |
|---|---|---|
| IDs | ULIDs (sortable, offline-safe) | Edge must create IDs without the cloud |
| Time | UTC in storage; `Africa/Nairobi` in UI | Audit consistency |
| Units | SI (kg, m, m/s, °C) in storage; tonnes in UI | Avoid unit bugs in the legal path |
| Signing | Ed25519 per-station keys (edge) + platform key (cloud) | Tamper-evidence without blockchain |
| Multi-tenancy | `org_id` on every commercial row; row-level filters in repository layer | Transporters/cargo owners never see each other |
| PII | `pii` schema, separate role, column-level encryption for ID numbers/phones | Kenya DPA 2019 |

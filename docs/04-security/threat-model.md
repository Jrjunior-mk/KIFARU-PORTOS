# KIFARU PORTOS — Threat Model (STRIDE)

| Field | Value |
|---|---|
| Document | `docs/04-security/threat-model.md` |
| Version | 0.1 (Phase 2 code baseline, API `0.1.0`, engine `clr-1.2.0`, DSP `wim-dsp-0.3`) |
| Date | 2026-11-04 |
| Scope | Roadside lane (DAQ, gateway, sensors, cameras, RFID), MQTT uplink, cloud API and data stores, dashboards and driver app, human accounts, CI/CD |
| Method | STRIDE per asset; likelihood (L) and impact (I) scored 1–5; risk = L × I (≥ 15 Critical, 10–14 High, 5–9 Medium, < 5 Low) |
| Basis | Code in `apps/api/kifaru/`, `packages/wim_dsp/`, `packages/ai_agents/`; architecture in `docs/02-architecture/`; no cloud deployment has been performed, so every AWS control is *designed*, not verified |

## 1. Purpose and limits

This document records the threats to the rolling-clearance platform, the controls that exist **in the code as reviewed**, the gaps, and the mitigations planned by phase (`docs/02-architecture/roadmap.md`). It is an engineering artefact, not a certification. Three constraints shape it:

1. The static weighbridge remains the legal reference (RTM RCS-07). A fraudulent GREEN therefore defeats a *pre-screen*, not a legal certificate; the harm is that an overloaded or non-compliant truck is not stopped.
2. The clearance engine is deterministic and AI is advisory (`services/clearance_engine.py`, AGT-02). Attacks on AI components cannot by themselves change a decision; attacks on the engine's *inputs* (measurement, identity, vehicle record, cargo record, calibration validity, limits configuration) can.
3. Everything the platform asserts is signed or hash-chained (`services/ledger.py`, `services/tickets.py`), so most tampering is *detectable after the fact* even where it is not *preventable*. The model therefore gives as much weight to detection as to prevention.

## 2. System context and trust boundaries

```
 TB0 physical world                TB1 roadside cabinet (IP66)                 TB2 WAN             TB3 AWS af-south-1 (designed)        TB4 users
 ─────────────────────────────     ────────────────────────────────────────    ─────────────────   ──────────────────────────────────    ──────────────
 piezo rows P1 P2 P3 ──charge──►  charge amps ► AA filter ► ADS131M08 ──SPI──► STM32H743 DAQ
 bending plate ──bridge──────►                                                     │ CAN / Ethernet
 loops L1 L2 L3, IR, radar ──►   detector cards / RS-485 ─────────────────────────┤
 pavement/ambient T ─────────►   ESP32 aux ──CAN──────────────────────────────────┤
 ANPR cameras x2 ──PoE/ONVIF─►   PoE switch ─────────────────────────────────► Edge gateway (IPC, Linux, Python)
 UHF RFID reader ──PoE/LLRP──►                                                  · OCR, identity fusion mirror
 VMS / lane signal ◄──relay──                                                   · clearance engine mirror
                                                                                · SQLite WAL outbox, GPS/NTP
                                                                                └──MQTT 5 / TLS 1.2+ mTLS (X.509)──► IoT Core ► SQS ► ingest worker
                                                                                                                                       │ service JWT
                                                                                                                      WAF ► ALB ► FastAPI (ECS Fargate) ◄──HTTPS/WSS── dashboards (React), driver PWA/Flutter
                                                                                                                                       │
                                                                                                                      RDS PostgreSQL 16 (core | pii | ts) · ElastiCache Redis · S3 (tickets, evidence, backups)
                                                                                                                      Secrets Manager · CloudWatch · GitHub Actions (OIDC) ──► ECR / Terraform
```

Figure 1 — Trust boundaries. Today only the FastAPI service, the DSP package and the agents exist as code; the edge gateway, firmware, Terraform and dashboards are architecture (`docs/02-architecture/system-architecture.md` §2).

Crossing a boundary is where authentication happens: TB1→TB2 by device certificate (designed), TB2→TB3 by IoT Core policy and a service JWT (designed; today `POST /weighing/ingest` accepts an operator/admin JWT, `routers/weighing.py`), TB4→TB3 by Argon2id password + TOTP + 15-minute JWT (`security.py`, `routers/auth.py`).

## 3. Scoring conventions

| Score | Likelihood (per year, pilot scale) | Impact |
|---|---|---|
| 1 | Remote (< 5 %) | Cosmetic; no decision or data affected |
| 2 | Unlikely (5–20 %) | Single wrong AMBER/RED (false stop) or minor data exposure |
| 3 | Possible (20–50 %) | Single fraudulent GREEN, or tenant-level data exposure |
| 4 | Likely (50–80 %) | Repeated fraudulent GREENs, or regulated personal data breach |
| 5 | Almost certain (> 80 %) | Systemic loss of trust in tickets/ledger, or safety incident |

Residual risk is given after *existing* controls only. Planned controls are listed separately so the reader can see what the code does today.

## 4. STRIDE tables per asset

Legend for *Existing control* column: a path means the control is in the code base; "arch" means it is specified in `docs/02-architecture/` only. *Detect* column maps to the `SecurityAnomalyAgent` (`packages/ai_agents/kifaru_ai_agents/agents_misc.py`) alert kinds — `repeated_identity_conflict`, `impossible_travel`, `override_burst`, `credential_stuffing` — and to `core.audit_events` / `core.ledger_events`.

### 4.1 Lane DAQ (STM32H743 + ADS131M08, charge amplifiers, loop/IR cards)

| STRIDE | Threat | L | I | Risk | Existing control | Gap | Planned (phase) | Detect |
|---|---|---|---|---|---|---|---|---|
| S | Replacement DAQ board streams fabricated axle pulses to the gateway | 2 | 4 | 8 M | Cabinet IP66 lock (arch); DSP cross-row consensus flags pulse-count mismatch (`pipeline.py channel_health`) | No DAQ→gateway authentication on CAN/Ethernet | Signed DAQ frames or physically sealed DAQ–gateway link; tamper switch on cabinet door (6) | `sensor.health` events; `WeighingIntelligenceAgent row_bias` |
| T | Firmware modified to apply a gain factor < 1 | 2 | 5 | 10 H | Calibration records with `gain` and validity window (`routers/stations.py add_calibration`); `static.verified` ledger entries record WIM-vs-static error | No secure boot / firmware signature | Signed firmware, read-out protection, firmware hash in `station.failure`/health telemetry (6) | Drift in `wim_error_pct` across `static.verified` ledger entries; random audit (`RANDOM_AUDIT`, 2 %) |
| R | Operator denies a measurement happened | 1 | 2 | 2 L | Every pass is ledgered with `producer=lane:<id>` | — | Per-station Ed25519 key (arch §7) | Ledger |
| I | Raw 8 kHz windows (`raw_ref`) disclosed | 1 | 1 | 1 L | Raw data stays at edge / S3 (arch) | — | S3 bucket policy (2) | — |
| D | Sensor cable cut, charge amp saturated with injected signal | 3 | 2 | 6 M | `channel_health` → `fault`; any blocking flag forbids GREEN (`BLOCKING_QUALITY_FLAGS`) | None beyond fail-safe to AMBER | Surge/ESD protection (6); lane → AMBER-only mode | `sensor.health`, `OperationalIncidentAgent` |
| E | — | | | | n/a (no privilege model on DAQ) | | | |

### 4.2 Edge gateway (IPC: OCR, identity fusion, engine mirror, outbox)

| STRIDE | Threat | L | I | Risk | Existing control | Gap | Planned | Detect |
|---|---|---|---|---|---|---|---|---|
| S | Attacker on the cabinet LAN impersonates the gateway to the cloud | 2 | 5 | 10 H | mTLS X.509 per device at IoT Core (arch §3) | Not deployed; the local path `POST /weighing/ingest` is protected only by an operator/admin JWT and a `device_id` → lane lookup (`routers/weighing.py ingest`) | Device cert + IoT policy restricting topic to `stations/<thing>/…`; ingest worker service token scoped to `device_id` (2/6) | Mismatch between IoT `clientId` and payload `device_id` (planned rule) |
| T | Outbox (SQLite) edited while offline to change GVM before replay | 2 | 4 | 8 M | Cloud re-runs the engine on ingest (`weighing_service.process_lane_pass`), so the *decision* is recomputed from the submitted measurement; idempotency on `edge_event_id` | The *measurement* itself is trusted as submitted | Gateway signs each outbox row with the station key; cloud verifies before ingest (6) | Divergence between gateway-local decision and cloud decision (planned comparison) |
| R | Gateway denies emitting an event | 1 | 2 | 2 L | ULID `edge_event_id` unique; ledger | — | Station signature | Ledger |
| I | Plate images / OCR text leak from the gateway disk | 2 | 3 | 6 M | Evidence images to S3 (arch) | No disk encryption spec | LUKS full-disk encryption; image retention ≤ 30 days (3/6) | — |
| D | Ransomware or disk-full stops the lane | 3 | 3 | 9 M | Decision never depends on cloud (arch §4); fail-safe: no measurement → no GREEN | No gateway hardening baseline | Immutable OS image, A/B partitions, outbound-only firewall, offline backup of config (6); playbook IR-03 | `station.failure`, heartbeat loss |
| E | Local console access gives root | 2 | 4 | 8 M | — | No hardening spec | Disable local login, SSH by certificate only via bastion (6) | OS audit log → CloudWatch |

### 4.3 MQTT link (gateway → IoT Core/EMQX)

| STRIDE | Threat | L | I | Risk | Existing control | Gap | Planned | Detect |
|---|---|---|---|---|---|---|---|---|
| S | Rogue client publishes `weighing.completed` for a real lane | 2 | 5 | 10 H | mTLS + per-device IoT policy (arch); `config.py` has `mqtt_tls_*` settings | Not deployed; no message-level signature | Topic ACL bound to certificate CN; ingest rejects topic/`device_id` mismatch (2) | IoT Core auth failures → CloudWatch alarm |
| T | Message altered in transit | 1 | 5 | 5 M | TLS 1.2+ | — | Payload signature (6) | — |
| I | Plates observed in transit | 1 | 2 | 2 L | TLS | — | — | — |
| D | LTE jamming / fibre cut | 3 | 2 | 6 M | Store-and-forward outbox, idempotent replay (`edge_event_id`) | — | Dual uplink (LTE + fibre) (6) | Heartbeat gap alarm |

### 4.4 Cloud API (FastAPI)

| STRIDE | Threat | L | I | Risk | Existing control | Gap | Planned | Detect |
|---|---|---|---|---|---|---|---|---|
| S | Forged / stolen JWT | 2 | 4 | 8 M | HS256 with `min_length=16` secret, 15-min expiry, `type=access` check, user `is_active` re-checked per request (`deps.get_current_principal`); tested in `tests/test_security.py::test_tampered_and_expired_tokens_rejected` | Default dev secret `CHANGE-ME…` is **not rejected** when `env` is staging/prod (`config.py`); no `iss`/`aud` claims | Startup assertion on secret entropy; asymmetric RS256/EdDSA with JWKS for multi-service (2) | `credential_stuffing` alert (requires `login_failed` events — see §6) |
| T | Parameter tampering (e.g. `max_gvm_kg` 90 000) | 2 | 3 | 6 M | Pydantic bounds on every body (`VehicleIn.max_gvm_kg ≤ 56000`, `tare_kg`, ISO 6346 check digit, regex patterns) | — | — | 422 rate in logs |
| R | Privileged write without trace | 1 | 4 | 4 L | `deps.audit()` on privileged writes; ledger on legal-path writes | `audit_events` rows are not hash-chained | Chain audit rows or mirror into ledger (3) | `/admin/audit` |
| I | Error messages / stack traces | 1 | 2 | 2 L | Generic 500 handler (`main.py`) | — | — | — |
| I | Tenant data via IDOR | 2 | 4 | 8 M | `org_scope()` filter in every tenant router; tested (`test_tenant_isolation_*`) | `GET /admin/incidents` and `/admin/agents` require only authentication (`CurrentUser`) — any tenant sees station incident details | Restrict to OPS/auditor roles (2) | — |
| D | Credential-stuffing / flood | 3 | 3 | 9 M | Per-IP 300 req/min on `/auth/*` only (`deps.rate_limit`), lockout after 5 failures for 15 min (`routers/auth.py login`) | Limiter is in-process memory (not shared across tasks), not applied to other routers, not to `GET /tickets/verify/{token}` | WAF rate rules at ALB; Redis-backed limiter (2) | 429/423 counts; `credential_stuffing` |
| E | Role escalation | 1 | 5 | 5 M | Roles come from DB at login and are embedded in the JWT; `has_role` grants `platform_admin` everything; `require_roles` per endpoint; matrix tested (`test_role_gates_matrix`) | Roles in JWT are stale until expiry (≤ 15 min) after an admin demotes a user | Role-version claim checked against DB (3) | `/admin/audit` `update user` |
| E | Self-registration creates a *transporter* org and `transporter_admin` without vetting | 3 | 3 | 9 M | `RegisterIn.role` whitelist excludes platform roles | Any stranger can register a transporter/dispatcher org and post positions, book slots | KYC step before org `status=active`; `status` is already modelled on `Organization` (3) | Audit `register` |

### 4.5 Database (PostgreSQL 16: `core`, `pii`, `ts`)

| STRIDE | Threat | L | I | Risk | Existing control | Gap | Planned | Detect |
|---|---|---|---|---|---|---|---|---|
| T | Direct SQL edit of `clearance_decisions` or `weighing_events` | 2 | 5 | 10 H | `evidence_hash` = SHA-256 over all engine inputs and rules (`clearance_engine.decide`); decision signed (`weighing_service` → `sign_payload`); ledger rows hash-chained and signed (`ledger.append`); `verify_chain` endpoint | The ledger and the signing key material are in the same trust domain as the data (API task has both); `verify_chain` uses only the *current* key (§8 F2); appends are not serialised (concurrent `append` can issue duplicate `seq`) | Anchor ledger head hash daily to S3 Object Lock and publish to regulator (3); `pg_advisory_xact_lock` on append (2); HSM/KMS-held signing key with sign-only API (3) | `GET /admin/ledger/verify` scheduled hourly → alarm on `ok=false` |
| I | Dump of `pii` schema | 2 | 5 | 10 H | Separate schema; `REVOKE ALL ON SCHEMA pii FROM PUBLIC` (`alembic/versions/0001_initial.py`); `pgcrypto` extension created | Columns named `*_enc` **hold plaintext today** (`routers/auth.py register`, `routers/fleet.py create_driver`, `seed.py`); application role is the same for `core` and `pii`; `users.mfa_secret` plaintext | `pgcrypto`/KMS envelope encryption in a `pii` service layer; separate DB role for PII access; RDS storage encryption (2/3) | RDS audit logging of `pii.*` access (planned) |
| D | Deletion / ransomware on RDS | 1 | 5 | 5 M | Multi-AZ, 35-day automated backups + PITR, daily `pg_dump` to cross-region S3 (arch §3 #10) | Not deployed | Terraform + restore drill (2/7) | Backup job alarms |
| E | App role has DDL rights | 2 | 3 | 6 M | — | Alembic uses the same role | Migration role separate from runtime role (2) | — |

### 4.6 Object storage (S3: tickets, evidence images, backups)

| STRIDE | Threat | L | I | Risk | Existing control | Gap | Planned | Detect |
|---|---|---|---|---|---|---|---|---|
| T | Ticket PDF/JSON replaced | 1 | 3 | 3 L | Ticket payload + signature live in DB; S3 copy is secondary (`DigitalTicket.object_key`) | — | Versioning + Object Lock (arch) | Signature check on read |
| I | Public bucket exposes plate images | 2 | 4 | 8 M | Private bucket, CloudFront OAC (arch) | Not deployed | Block Public Access, bucket policy, SSE-KMS (2) | S3 access logs, Access Analyzer |
| D | Backups deleted | 1 | 5 | 5 M | Cross-region replication (arch) | — | Object Lock compliance mode on backups (2) | — |

### 4.7 Dashboards (React SPA, 7 roles)

| STRIDE | Threat | L | I | Risk | Existing control | Gap | Planned | Detect |
|---|---|---|---|---|---|---|---|---|
| S | Phishing of operator credentials | 3 | 4 | 12 H | TOTP MFA available (`/auth/mfa/*`); privileged roles listed in `mfa_required_roles` | MFA gating only applies **if the user has enrolled** (`deps.require_roles`: `needs_mfa and p.user.mfa_enabled`) — an un-enrolled operator is never challenged | Force enrolment at first login for `mfa_required_roles`; WebAuthn (3) | `credential_stuffing`; login audit |
| T | XSS → token theft | 2 | 4 | 8 M | `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, HSTS in staging/prod (`main.py`); CORS origins list | No Content-Security-Policy; tokens held in JS memory/storage (SPA) | CSP with nonce; refresh token in HttpOnly cookie (3) | — |
| I | WS token in query string logged by proxies | 2 | 3 | 6 M | 15-min expiry | `routers/ws.py` requires `?token=` | First-message auth or short-lived WS ticket (3) | — |
| D | Dashboard unavailable | 2 | 2 | 4 L | S3 + CloudFront (arch) | — | — | — |

### 4.8 Mobile / driver app (PWA interim, Flutter Phase 3)

| STRIDE | Threat | L | I | Risk | Existing control | Gap | Planned | Detect |
|---|---|---|---|---|---|---|---|---|
| S | Fake position updates to appear "near" a backhaul pickup | 3 | 2 | 6 M | `POST /fleet/vehicles/{id}/position` scoped to own org; matches need two-party acceptance (`routers/backhaul.py`) | No plausibility check on jumps | Reuse `impossible_travel` logic for GPS (4) | `impossible_travel` (today EPC-based) |
| I | Driver phone number exposed | 2 | 4 | 8 M | PII in `pii.driver_pii`; SMS sends via server only | Plaintext (§4.5) | Encryption (3) | — |
| E | Driver books slots for other orgs' trucks | 1 | 2 | 2 L | `org_scope` check in `book` (tested) | — | — | — |

### 4.9 RFID tags (UHF EPC Gen2)

| STRIDE | Threat | L | I | Risk | Existing control | Gap | Planned | Detect |
|---|---|---|---|---|---|---|---|---|
| S | **Cloned tag** on another truck | 4 | 4 | 16 C | Identity fusion: ANPR ≠ RFID → `method=conflict` → `IDENTITY_CONFLICT` RED (`services/identity.py`, `clearance_engine.py`); single-source confidence capped at 0.95 so RFID-only never satisfies `identity_min_confidence=0.90`? — **note**: 0.95 > 0.90, so RFID-only *can* reach GREEN when ANPR is absent (see scenario T-01) | Tag registry has no cryptographic binding (EPC is a static identifier); revocation exists (`RfidTag.revoked_at`) but no revocation workflow | Tags with TID lock + authenticated reads (ISO/IEC 29167) in Phase 6 hardware selection; require `rfid+anpr` for GREEN (config) | `repeated_identity_conflict`, `impossible_travel` |
| T | Tag re-programmed to another EPC | 3 | 3 | 9 M | Unique EPC constraint | — | Locked EPC memory bank | As above |
| D | Tag shielded (foil) to force "unregistered" | 3 | 1 | 3 L | Fail-safe: no tag → ANPR-only (cap 0.95) or `VEHICLE_UNKNOWN` AMBER | — | — | `rfid_missing` rate per fleet |

### 4.10 ANPR cameras

| STRIDE | Threat | L | I | Risk | Existing control | Gap | Planned | Detect |
|---|---|---|---|---|---|---|---|---|
| S | **Plate spoofing** (fake plate matching a registered, lighter truck) | 3 | 4 | 12 H | Fusion with RFID → conflict RED; `AXLE_CONFIG_MISMATCH` AMBER when detected axle groups differ from the registered configuration; declared-mass and VGM cross-checks | ANPR-only confidence capped at 0.95 still ≥ 0.90 threshold | Require two independent identity sources for GREEN; NTSA registry adapter in `real` mode (5) | `repeated_identity_conflict`; `AXLE_CONFIG_MISMATCH` frequency per plate |
| D | **Camera blinding** (IR flood, laser, mud, cover) | 4 | 2 | 8 M | OCR confidence low → `IDENTITY_LOW_CONFIDENCE` AMBER or `none`; simulator models misreads (`services/simulator.py`) | Camera health not yet in `SENSOR_KINDS` telemetry path | Camera health (exposure/blur metric) → `sensor.health`; second camera (rear plate) per lane (6) | Sudden rise in `method=none` share on one lane |
| T | ONVIF stream substitution | 1 | 4 | 4 L | PoE LAN inside cabinet | No camera auth spec | ONVIF with TLS + credentials, MAC pinning on switch (6) | — |

### 4.11 Operator accounts (`weighbridge_operator`, `port_controller`)

| STRIDE | Threat | L | I | Risk | Existing control | Gap | Planned | Detect |
|---|---|---|---|---|---|---|---|---|
| E | **Override abuse** to release an overloaded truck | 3 | 4 | 12 H | `override-release` requires MFA claim (`require_roles(..., mfa=True)`), a prior `static_verified_gvm_kg`, a reason ≥ 10 chars; original decision kept; `clearance.overridden` ledger + audit (`routers/weighing.py`) | MFA conditional on enrolment (§4.7); no second approver | Two-person rule for override; daily override report to auditor (3) | `override_burst` (≥ 3 per user per window), ledger query |
| T | Operator enters a false static result to make a RED look legal | 3 | 4 | 12 H | `static.verified` ledger entry records `wim_gvm_kg` vs `static_gvm_kg` and `wim_error_pct` | No link to the static scale's own indicator | Static-scale integration (serial/ethernet) so the value is read, not typed (6) | Outliers in `wim_error_pct` per operator |
| T | Operator extends calibration validity without calibrating | 2 | 3 | 6 M | Audit `calibrate`; `CalibrationRecord.performed_by` | Any operator can add a record with arbitrary `gain`/`valid_days` ≤ 730 | Two-person approval; reference-vehicle evidence attached (6) | Audit review |
| T | Operator marks a faulty sensor `ok` | 2 | 2 | 4 L | Cloud decision uses `measurement.sensor_health` from the gateway, **not** the DB `Sensor.status`, so this cannot unblock GREEN | — | — | `sensor.health` event |
| S | Shared operator login | 3 | 3 | 9 M | `RefreshSession` records IP and user-agent | No concurrent-session limit | Per-shift accounts, session cap (3) | Multiple IPs per user in `refresh_sessions` |

### 4.12 Admin accounts (`platform_admin`)

| STRIDE | Threat | L | I | Risk | Existing control | Gap | Planned | Detect |
|---|---|---|---|---|---|---|---|---|
| E | Admin sets an integration `base_url` to an internal address (SSRF) or hostile host | 2 | 3 | 6 M | `set_mode` requires `platform_admin`, audited; tokens come from environment not DB (`routers/integrations.py`) | `_call_real` will request any URL | Allowlist of hostnames per adapter; egress proxy (5) | Audit `integration_mode` |
| E | Admin clears a watch-list entry | 2 | 4 | 8 M | Audit with `before`/`after` | — | Watch-list changes mirrored to ledger; regulator read-only view (3) | Audit |
| T | Admin changes limits | 1 | 5 | 5 M | Limits are **code + version string**, not DB (`services/limits.py`); every decision stores `limits_version` | — | Signed config bundle (3) | `limits_version` change in decisions |
| S | Admin account takeover | 2 | 5 | 10 H | MFA available; lockout | Enrolment not forced | Hardware key for admins (3) | `credential_stuffing` |

### 4.13 CI/CD (GitHub Actions → ECR → Terraform)

| STRIDE | Threat | L | I | Risk | Existing control | Gap | Planned | Detect |
|---|---|---|---|---|---|---|---|---|
| T | Malicious dependency (`pyproject.toml` ranges `>=`) | 3 | 4 | 12 H | — | Unpinned upper bounds; no lockfile committed; no SBOM | `uv.lock`, Dependabot, `pip-audit` in CI, SBOM (2) | CI failure |
| S | Stolen long-lived AWS key | 1 | 5 | 5 M | OIDC trust, no static keys (arch) | Not deployed | Terraform with OIDC role, least privilege (2) | CloudTrail |
| E | PR merges without review deploy to prod | 2 | 4 | 8 M | Prod apply requires manual approval (arch §3 #15) | Not deployed | Branch protection, signed commits, environment protection rules (2) | — |

## 5. Named threat scenarios

Each scenario below is the "deep dive" the brief requires. Controls cite the module that implements them.

### T-01 RFID cloning

**Attack.** A transporter copies the EPC of a light, compliant truck onto a tag fitted to an overloaded truck, expecting the platform to apply the light truck's profile and clear it.

**What actually happens in the code.** `services/identity.resolve()` reads both sources. If ANPR reads the real plate, the two resolve to different vehicles → `method="conflict"`, confidence 0 → rule `IDENTITY_CONFLICT` (RED). If the plate is also spoofed to match (combined with T-02) the identity is `rfid+anpr` with high confidence and the **limits are still applied to the measured axle groups**: `gvm_limit_for_config()` derives the legal limit from the *detected* axle configuration, and `min(gvm_limit, vehicle.max_gvm_kg)` only tightens. So cloning cannot raise the limit; it can only (a) hide a watch-list status, (b) defeat `DECLARATION_MISMATCH`/`VGM_MISMATCH` by borrowing another truck's shipment context, and (c) misattribute the pass. If ANPR is unavailable (blinded, T-02b), RFID-only confidence is capped at 0.95 (`SINGLE_SOURCE_CAP`) which is **above** `identity_min_confidence = 0.90`, so a cloned tag alone can pass identity when the truck is within limits.

| Item | Assessment |
|---|---|
| Likelihood / Impact | 4 / 4 → **16 Critical** (before planned controls) |
| Existing controls | Fusion + conflict RED (`identity.py`, `clearance_engine.py` `IDENTITY_CONFLICT`); `AXLE_CONFIG_MISMATCH`; limits from detected configuration; `RfidTag.revoked_at`; simulator exercises `clone_prob` (`simulator.py`) |
| Gaps | RFID-only can satisfy the identity threshold; EPC is a static, copyable identifier; no field revocation workflow; `impossible_travel` needs `lat/lon` on events, which the lane pass does not currently attach |
| Planned mitigations | Config: require `rfid+anpr` (or ANPR ≥ 0.97) for GREEN at pilot; authenticated-read tags (TID lock, ISO/IEC 29167 crypto suite) in the Phase 6 BOM; station coordinates attached to identity events so `impossible_travel` works from `weighing.completed`; revocation API with reason and ledger entry |
| Detection | `SecurityAnomalyAgent.repeated_identity_conflict` (≥ 2 conflicts per plate), `impossible_travel` (same EPC > 120 km/h apparent speed between stations); ledger `clearance.decided` with `IDENTITY_CONFLICT` in `rules_fired`; `identity_events.method='conflict'` query |

### T-02 ANPR manipulation

**T-02a Plate spoofing.** Fake plate of a registered truck. Controls as T-01; additionally `AXLE_CONFIG_MISMATCH` (AMBER) fires when the detected `axle_config` differs from the registration, which defeats the common case of a 7-axle truck carrying a 4-axle truck's plate. Residual: same-configuration spoof with no tag present → ANPR-only at ≤ 0.95 ≥ 0.90 passes identity. **L 3 / I 4 → 12 High.**

**T-02b Camera blinding.** IR flood, laser, mud, cover. OCR fails or returns low confidence → `IDENTITY_LOW_CONFIDENCE` / `VEHICLE_UNKNOWN` → AMBER (never GREEN). Impact is operational (more static weighings), not fraud. **L 4 / I 2 → 8 Medium.** Gap: camera health is not telemetered; planned: image quality metric to `sensor.health`, front + rear cameras (`hardware-architecture.md` §1).

Detection for both: share of `method in ('anpr','none')` per lane per hour vs baseline; `repeated_identity_conflict`.

### T-03 Unauthorised access (external)

| Item | Assessment |
|---|---|
| L / I | 3 / 4 → **12 High** |
| Existing | Argon2id (t=3, m=64 MiB, p=2, `security.py`); passwords ≥ 10 chars; generic 401 (no user enumeration on login — but `register` returns 409 on duplicate e-mail, which enumerates); lockout 5/15 min; TOTP (`pyotp`, `valid_window=1`); 15-min access JWT; refresh rotation with SHA-256-only storage (`new_refresh_token`), revoked on use/logout; `is_active` re-check per request; tests `test_security.py` |
| Gaps | MFA enrolment optional; default JWT secret accepted in prod; refresh-token reuse rejected but does not revoke the whole session family; no `iss`/`aud`; e-mail enumeration via `/auth/register`; failed logins not emitted as events |
| Planned | Forced MFA for `mfa_required_roles` (2); secret strength check at startup (2); family revocation on reuse (3); WAF managed rules (2); WebAuthn for admins (3) |
| Detection | `credential_stuffing` (≥ 10 `login_failed` in window — **requires emitting `login_failed` events, which `routers/auth.py` does not do yet**); `audit_events.action='login'`; 423 counts |

### T-04 Database compromise

| Item | Assessment |
|---|---|
| L / I | 2 / 5 → **10 High** |
| Existing | Tamper-evidence: `evidence_hash`, decision signature, hash-chained signed ledger, `verify_chain`; schema separation; `REVOKE … pii FROM PUBLIC`; parameterised SQLAlchemy everywhere (no raw SQL except `SELECT 1`) |
| Gaps | Attacker with DB write **and** the signing seed (both reachable from the API task) can rewrite history consistently; PII plaintext; ledger verification depends on current key only; no external anchor |
| Planned | KMS/HSM sign-only key (API never holds the seed) (3); daily head-hash anchor to S3 Object Lock + e-mail to regulator (3); pgcrypto column encryption (2/3); RDS IAM auth, no password (2) |
| Detection | Hourly `GET /admin/ledger/verify` → alarm on `ok=false` or unexpected `head_hash` change vs anchor; RDS Performance Insights anomalies; CloudTrail for snapshot export |

### T-05 API abuse

| Item | Assessment |
|---|---|
| L / I | 3 / 3 → **9 Medium** |
| Existing | Rate limit on `/auth/*` (300/min/IP, `deps.rate_limit`, tested); bounds on `count ≤ 50` for `/weighing/simulate`, `limit ≤ 1000` for admin lists, `hours`/`limit` query caps; Pydantic validation; `qr_token` is 24 random bytes (`secrets.token_urlsafe(24)`, ~192 bits) so enumeration of `/tickets/verify/{token}` is infeasible |
| Gaps | Limiter per-process and auth-only; `GET /tickets/verify` unauthenticated and unthrottled (information oracle for plate ↔ decision if a token leaks); `/weighing/simulate` reachable in production (writes `source=simulated` rows into the live DB); `identity.resolve` scans all vehicles per pass (performance under load) |
| Planned | WAF rate rules + Redis limiter (2); disable `simulate` unless `env in (dev,test,staging)` (2); normalised-plate index (2) |
| Detection | 429 metrics; CloudWatch alarms on 4xx/5xx ratio; `by_source` in `/weighing/stats` showing `simulated` in prod |

### T-06 Insider tampering (operator override abuse)

See §4.11. Summary: **12 High**. The code already (a) requires MFA claim + prior static verification + reason, (b) never deletes the original decision, (c) writes `clearance.overridden` to the ledger with user ID, (d) audits. Gaps: MFA enrolment optional; single approver; static result typed by hand; `static_verify` **deletes** the pre-screen ticket (`routers/weighing.py static_verify`: `db.delete(d.ticket)`), which removes evidence the operator might want to hide — the ledger still holds `clearance.decided` with the old `ticket_id`, but the ticket row itself is gone. Planned: supersede (`superseded_by`) instead of delete; two-person override; static-scale integration; daily override report. Detection: `override_burst`; ledger query `type='clearance.overridden'`; `audit_events` by `actor_user_id`.

### T-07 Device impersonation

Covered in §4.2–4.3. **10 High.** Today the only thing binding a measurement to a lane is the `device_id` string in the ingest body plus an operator/admin JWT. In the designed topology, the X.509 certificate CN must equal the IoT thing name and the ingest worker must copy the authenticated thing name into `device_id` rather than trusting the payload. Detection: IoT auth failures; `device_id` not matching certificate CN; measurement rate per lane outside physical plausibility (> 1 pass per 2 s).

### T-08 Sensor manipulation (physical and signal injection)

| Vector | Effect in DSP | Engine outcome | Residual |
|---|---|---|---|
| Driving on the shoulder / straddling the strip edge | Fewer pulses on one row → `channel_health` pulse-count mismatch → `sensor_degraded`/`sensor_fault`; `insufficient_rows` if < 2 good rows | AMBER (blocking flags) | Low; detectable by IR beam tyre-position check (hardware §1) |
| Very slow or very fast pass | `speed_out_of_range` (< 3 or > 30 m/s) | AMBER | Low |
| Braking/accelerating over the rows ("bouncing") to lower apparent load | Dynamic component increases Type-A spread across rows → larger `u_kg`; `GVM_OVER_POSSIBLE` uses `gvm + U + 250 kg` | More AMBER, not GREEN; a determined driver may reduce a *marginal* overload below `limit − U` on average only by luck | Medium; mitigated by three rows + bending plate averaging and `WeighingIntelligenceAgent.high_speed_dynamic_effect` |
| Electrical injection into charge amp (coupled interference) | Baseline RMS > 800 kg-eq → `degraded`; saturation flat-top → `fault` | AMBER | Low–Medium; shielding/grounding spec in `docs/03-hardware` (pending) |
| Heating/cooling the pavement probe to skew temperature compensation | Compensation factor `1 + k·ΔT` with `k ≈ −0.002/°C` for quartz: a 20 °C error ≈ 4 % | Could shift GVM ~4 % — inside the ±5 % target but could flip a marginal case | Medium; planned: ambient vs pavement plausibility check, redundant probe |
| Physical damage / replacement of a strip | Gain change | Detected by `static.verified` error drift and cross-row bias | Medium |

Overall **L 3 / I 3 → 9 Medium**. The fail-safe design (quality deficiency → never GREEN, RTM RCS-09, tested in `test_clearance_engine.py::test_quality_flag_blocks_green` and `test_api_flow.py::test_sensor_fault_never_green`) converts most sensor attacks into *denial of GREEN*, not fraudulent GREEN.

### T-09 Ransomware

| Target | L | I | Risk | Existing | Gap | Planned | Detect |
|---|---|---|---|---|---|---|---|
| Edge gateway | 3 | 3 | 9 M | Decision continues locally? **No** — if the gateway is encrypted the lane stops; static scale continues (legal path unaffected) | No hardening baseline, no image rebuild procedure | Immutable image, 15-min rebuild from signed image, config in Secrets Manager, outbound-only firewall (6); playbook IR-03 | Heartbeat loss → `station.failure` incident |
| Cloud (RDS/S3) | 1 | 5 | 5 M | Managed backups, cross-region copy (arch) | Not deployed | Object Lock, separate backup account (2) | GuardDuty, backup alarms |
| Operator workstations | 3 | 2 | 6 M | Platform is browser-based; no local data | — | EDR per owner policy | — |

### T-10 Data leakage

| Channel | L | I | Risk | Existing | Gap | Planned |
|---|---|---|---|---|---|---|
| Public ticket verify returns `plate` | 3 | 2 | 6 M | Only non-sensitive fields (`VerifyOut`, tested `test_public_verify_leaks_no_pii`); token unguessable | Plate is an indirect identifier under the DPA; token printed on QR could be photographed | Mask plate (`KDA ***B`) on public verify (3) |
| Cross-tenant leakage | 2 | 4 | 8 M | `org_scope`; WS filter by `org_id` (`routers/ws.py`); tested | Station-level events (`org_id=None`) carry `plate` in payload and are visible to every authenticated user (`weighing.completed` payload includes `plate`) | Strip `plate` from non-platform WS payloads (3) |
| Logs | 2 | 3 | 6 M | structlog JSON; no bodies logged | WS token in URL may be logged by ALB | Header/first-message auth (3) |
| PII at rest | 2 | 5 | 10 H | Schema separation | Plaintext | Encryption (2/3) |
| Backups | 1 | 5 | 5 M | — | — | SSE-KMS, Object Lock (2) |

## 6. Detection: what the SecurityAnomalyAgent can see today

`SecurityAnomalyAgent` (`agents_misc.py`) consumes a list of events `{type, ts, station_id?, plate?, epc?, user_id?, lat?, lon?}` and emits:

| Alert kind | Rule | Severity | Feed required | Feed status |
|---|---|---|---|---|
| `repeated_identity_conflict` | ≥ 2 events `type=identity_conflict` for one plate | high | `identity_events.method='conflict'` → event | **Not wired**: no code converts identity events to agent input |
| `impossible_travel` | same `epc` seen at two positions with apparent speed > 120 km/h | critical | lane pass events with station `lat/lon` | **Not wired**: `weighing.completed` payload has no coordinates |
| `override_burst` | ≥ 3 `type=override` per `user_id` in window | high | ledger `clearance.overridden` | **Not wired** |
| `credential_stuffing` | ≥ 10 `type=login_failed` in window | medium | failed-login events | **Not emitted** by `routers/auth.py` |

The agent is unit-tested (`packages/ai_agents/tests/test_agents.py`) and listed in the orchestrator `security` pipeline, but **no scheduler or endpoint runs it against live data**. Planned (Phase 3): a worker that every 5 minutes builds the event window from `identity_events`, `ledger_events`, `audit_events` (with a new `login_failed` audit action) and station coordinates, runs the pipeline, and opens `Incident(category='security')` rows (model exists in `models/misc.py`) which publish `incident.opened` to dashboards.

Independent of the agent, these queries are available now: `GET /admin/audit?entity=clearance_decision`, `GET /admin/ledger?type=clearance.overridden`, `GET /admin/ledger/verify`, `GET /weighing/events?decision=RED`.

## 7. Attack trees

### 7.1 Fraudulent GREEN clearance for an overloaded truck

```
GOAL: Overloaded truck receives GREEN at the WIM lane (not sent to static scale)
│
├─[AND] Measurement understates load below (limit_with_tolerance − U − 250 kg)
│   ├─[OR] 7.1.1 Physical sensor manipulation ............................ mitigated: fail-safe flags → AMBER (§T-08)
│   ├─[OR] 7.1.2 Firmware/gain tamper on DAQ ............................. gap: no secure boot; detected by static.verified drift, 2 % random audit
│   ├─[OR] 7.1.3 Edit outbox before replay (gateway) ....................... gap: measurement trusted; decision recomputed in cloud (same inputs)
│   ├─[OR] 7.1.4 Impersonate gateway, post fabricated measurement ........... needs operator/admin JWT today; mTLS planned (§T-07)
│   ├─[OR] 7.1.5 Skew temperature compensation ~4 % ......................... partial; redundant probe planned
│   └─[OR] 7.1.6 Insider edits weighing_events after the fact ............... detected: evidence_hash, decision signature, ledger chain
│
├─[AND] Identity does not trigger RED/AMBER
│   ├─[OR] 7.1.7 Genuine identity of a registered truck ..................... normal case
│   ├─[OR] 7.1.8 Cloned tag + blinded camera (RFID-only ≤ 0.95 ≥ 0.90) ....... GAP (§T-01); planned: two-source rule
│   ├─[OR] 7.1.9 Spoofed plate, no tag, same axle configuration ............. GAP (§T-02a); AXLE_CONFIG_MISMATCH covers different configurations
│   └─[AND-NOT] 7.1.10 Vehicle on watch-list ................................ WATCHLIST → RED regardless of measurement
│
├─[AND] Quality/calibration not blocking
│   ├─ 7.1.11 Lane calibration valid (lane.calibration_valid_to ≥ now) ........ else AMBER (test_calibration_expiry_blocks_green)
│   └─ 7.1.12 No blocking or degrading flags ............................... else AMBER (test_quality_flag_blocks_green)
│
├─[AND] Cargo context not blocking
│   ├─ 7.1.13 No active shipment, or declaration within 15 % and seal armed .. else AMBER/RED (DECLARATION_MISMATCH*, SEAL_BREACH)
│
└─[AND-NOT] 7.1.14 Selected for random audit (2 %, seeded, logged) ............ AMBER; cannot be predicted (SystemRandom seed) nor removed without audit trail

ALTERNATIVE ROOT: bypass the engine
├─ 7.1.15 Operator override-release ........................................ requires MFA claim + static_verified_gvm_kg + reason; ledgered; override_burst detection (§T-06)
├─ 7.1.16 Change limits ...................................................... limits are code with version string; visible in every decision
└─ 7.1.17 Modify engine code via CI/CD ....................................... GAP: unpinned deps, no SBOM; planned branch protection, reviews
```

Minimum-effort path today: **7.1.2 or 7.1.3 combined with 7.1.7** (a corrupt installer or gateway admin) — this is why Phase 6 prioritises signed firmware, signed outbox rows and the static-scale comparison loop. Second path: **7.1.8/7.1.9** — closed by the two-source identity rule for GREEN, which is a one-line configuration change and is recommended for pilot.

### 7.2 Cargo passport forgery

```
GOAL: Present a Digital Cargo Passport / weighing ticket that the platform (or a verifier) accepts but that does not reflect reality
│
├─[OR] 7.2.1 Forge a ticket outside the platform and present its QR
│   ├─ needs a DB row: /tickets/verify looks up qr_token in digital_tickets .............. cannot verify a ticket that is not stored → valid=false
│   └─ so requires DB write access (→ 7.2.3)
│
├─[OR] 7.2.2 Alter an existing ticket's payload in DB
│   └─ signature over canonical JSON (Ed25519) fails ....................................... detected on every read (TicketOut.signature_valid, verify_public)
│
├─[OR] 7.2.3 Insert a self-consistent forged ticket with DB write access
│   ├─ generate own Ed25519 keypair, sign payload, embed own public key in payload.public_key
│   └─ tickets.verify() uses payload["public_key"] ........................................ **GAP F1: verifier trusts the key named in the document**
│       mitigation: verify against trusted registry {signer_key_id → public_key}; reject unknown key ids
│
├─[OR] 7.2.4 Forge the ledger to back-date or insert events
│   ├─ needs prev_hash chain recomputation from the forged point to head ................... detectable if head hash is anchored externally (planned)
│   └─ needs platform signing seed (in API environment) ................................... GAP: move to KMS sign-only (planned)
│
├─[OR] 7.2.5 Legitimate-looking passport with false *content*
│   ├─ false declaration (declared_mass_kg) ................................................ DECLARATION_MISMATCH vs measured GVM (±15 % → AMBER, ±30 % → RED)
│   ├─ false container number ............................................................. ISO 6346 check digit; KRA/KPA adapters mock until authorised (PRL-02)
│   ├─ seal status spoofed via /shipments/{id}/seal ....................................... STAGE_WRITE roles, ledgered `seal.status`; real seal provider adapter planned
│   └─ stage advanced without the step happening (e.g. customs_processing) ................ STAGE_WRITE roles; ledgered `cargo.status_changed` with actor; no external confirmation until adapters are real → **label as self-reported**
│
└─[OR] 7.2.6 Replay a genuine ticket for a different truck/load
    └─ ticket binds plate, vehicle_id, shipment_id, occurred_at, station, evidence_hash ..... verifier must compare with the truck in front of them; prescreen tickets state "not a legal weight certificate"
```

Conclusion: cryptographic forgery requires DB write access **and** either the platform key or exploitation of F1. Content forgery (7.2.5) is the realistic threat and is addressed by cross-checks and by the policy that all stage data is "self-reported" until government adapters run in `real` mode.

## 8. Code-review findings (ordered by priority)

| ID | Finding | Location | Severity | Recommendation |
|---|---|---|---|---|
| F1 | Ticket verification trusts the public key embedded in the ticket payload | `services/tickets.py verify()` → `verify_signature(..., t.payload.get("public_key"))` | High | Verify against a key registry keyed by `signer_key_id`; treat embedded key as informational |
| F2 | Ledger verification uses only the current signing key; rotating the key makes historical entries fail; appends not serialised | `services/ledger.py verify_chain`, `append` | High | Key registry lookup by `signer_key_id`; `pg_advisory_xact_lock` around `append` |
| F3 | MFA is enforced only if the user has enrolled | `deps.require_roles` (`needs_mfa and p.user.mfa_enabled`) | High | Force enrolment for `mfa_required_roles`; deny privileged endpoints until enrolled |
| F4 | Default JWT secret accepted in staging/prod | `config.py` | High | Raise at startup if `jwt_secret` equals default or entropy is low when `env in (staging, prod)` |
| F5 | PII `*_enc` columns and `mfa_secret` are plaintext | `routers/auth.py`, `routers/fleet.py`, `seed.py`, `models/auth.py` | High | pgcrypto/KMS envelope encryption in a PII service; separate DB role |
| F6 | Ingest trusts payload `device_id`; any operator token can post for any lane | `routers/weighing.py ingest` | High (until mTLS) | Bind `device_id` to authenticated thing name; service token scoped per station |
| F7 | Rate limiter per-process, auth-only; public verify unthrottled | `deps.rate_limit`, `routers/tickets.py` | Medium | Redis/WAF limiter on all routes incl. `/tickets/verify` |
| F8 | WebSocket token in query string | `routers/ws.py` | Medium | First-message auth or one-time WS ticket |
| F9 | `static_verify` deletes the prescreen ticket | `routers/weighing.py` | Medium | Mark superseded; keep row |
| F10 | SecurityAnomalyAgent not scheduled; `login_failed` not emitted; no coordinates on identity events | `routers/auth.py`, `weighing_service.py` | Medium | Phase 3 security worker |
| F11 | `/weighing/simulate` available in all environments | `routers/weighing.py` | Medium | Guard by `env` |
| F12 | Admin-settable `base_url` enables SSRF | `routers/integrations.py _call_real` | Medium | Hostname allowlist; egress proxy |
| F13 | No CSP; CORS `allow_methods=*`, `allow_headers=*` with credentials | `main.py` | Low | CSP nonce; enumerate methods/headers |
| F14 | `audit_events` not tamper-evident | `models/misc.py` | Low | Mirror privileged actions into ledger or chain audit rows |
| F15 | `/admin/incidents` (GET) and `/admin/agents` visible to any authenticated user | `routers/admin.py` | Low | Restrict to OPS/auditor |
| F16 | Refresh-token reuse does not revoke the session family | `routers/auth.py refresh` | Low | Revoke all sessions of the user on reuse detection |
| F17 | Self-registration of transporter orgs without vetting | `routers/auth.py register` | Low–Medium | `Organization.status='pending'` until verified |
| F18 | Dependencies unpinned, no lockfile/SBOM | `pyproject.toml` | Medium | `uv.lock`, `pip-audit`, SBOM in CI |

## 9. Residual risk summary

| Threat | Inherent | After existing controls | After planned (Phase 2–3) | After Phase 6 hardware |
|---|---|---|---|---|
| RFID cloning | 16 C | 12 H (conflict RED when ANPR present) | 8 M (two-source rule) | 4 L (authenticated tags) |
| ANPR spoofing | 12 H | 9 M | 6 M | 4 L (dual cameras + NTSA real) |
| Unauthorised access | 12 H | 8 M | 4 L (forced MFA, WAF) | — |
| DB compromise | 10 H | 8 M (tamper-evident) | 4 L (KMS key, anchor, encryption) | — |
| API abuse | 9 M | 6 M | 3 L | — |
| Operator override abuse | 12 H | 8 M | 4 L (two-person, reports) | 3 L (static-scale integration) |
| Device impersonation | 10 H | 10 H (local path) | 4 L (mTLS, scoped tokens) | 3 L (signed frames) |
| Sensor manipulation | 9 M | 6 M (fail-safe) | 6 M | 3 L |
| Ransomware (edge) | 9 M | 9 M | 6 M | 3 L (immutable image) |
| Data leakage | 10 H | 8 M | 4 L | — |

## 10. Review cadence

Re-run this model at each phase gate (`roadmap.md`), after any change to `clearance_engine.py`, `security.py`, `deps.py`, `ledger.py`, `tickets.py`, and after the Phase 7 external security review. Owner: Cybersecurity engineer; approver: project owner.

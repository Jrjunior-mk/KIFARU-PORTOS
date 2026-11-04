# KIFARU PORTOS — Incident Response Plan

| Field | Value |
|---|---|
| Document | `docs/04-security/incident-response-plan.md` |
| Version | 0.1 — 2026-11-04 |
| Applies to | Cloud platform (API, data stores), roadside stations (gateway, DAQ, sensors), dashboards and driver app, accounts, CI/CD |
| Framework | Preparation → Detection & analysis → Containment → Eradication → Recovery → Lessons learned (NIST SP 800-61 structure) |
| Legal | Data Protection Act, 2019 s.43: notify the Data Commissioner within **72 hours** of becoming aware of a personal-data breach, and notify affected data subjects where there is a real risk of harm **[counsel to confirm thresholds and the subject-notification timeline]** |
| Reality check | No cloud deployment exists yet; the platform runs locally on SQLite. Steps that depend on AWS tooling are marked **(AWS, designed)**. Everything else can be executed against the current code. |

## 1. Roles

| Role | Responsibility | Who (pilot) | Backup |
|---|---|---|---|
| Incident Commander (IC) | Declares the incident and severity, runs the bridge, owns decisions and the timeline | Platform lead | Cybersecurity engineer |
| Security Lead | Technical investigation, containment actions, evidence preservation | Cybersecurity engineer | Backend lead |
| Operations Lead | Station/lane operations: AMBER-only or offline mode, static-scale fallback, communication with weighbridge staff | Weighbridge operations manager | Port control officer |
| Data Protection Officer (DPO) / designate | Breach assessment under the Act, ODPC and data-subject notifications | To be appointed (`dpia.md` §10) | Project owner |
| Communications | Internal updates, transporter/cargo-owner notices, regulator liaison (KeNHA/KPA) | Project owner | IC |
| Scribe | Timeline, decisions, evidence log | Technical writer | Any engineer |
| Legal counsel | Notification wording, law-enforcement liaison | External | — |

Contacts, phone numbers and escalation paths are kept in the operations contact sheet (outside the repository). The `Incident` model (`apps/api/kifaru/models/misc.py`) and `POST /api/v1/admin/incidents` are the system of record for platform incidents; security incidents use `category="security"`.

## 2. Severity levels

| Level | Definition | Examples | Response target | Who is paged |
|---|---|---|---|---|
| **SEV-1 Critical** | Integrity of clearance decisions or legal records in doubt, or confirmed personal-data breach, or platform-wide outage | Ledger `verify` returns `ok=false`; evidence of fraudulent GREEN; signing key or JWT secret exposed; DB dump exfiltrated; ransomware on cloud data | IC on bridge ≤ 15 min; containment ≤ 1 h; status updates hourly | IC, Security Lead, Ops Lead, DPO, owner |
| **SEV-2 High** | Single-station compromise, privileged account compromise, cloned-tag wave, loss of a station for > 2 h | Operator account used from a new country; `override_burst`; `repeated_identity_conflict` on several plates in one day; gateway ransomware at one site | IC ≤ 30 min; containment ≤ 4 h; updates every 4 h | IC, Security Lead, Ops Lead |
| **SEV-3 Medium** | Attempted attack contained by controls, degraded sensor, suspected but unconfirmed misuse | Credential stuffing hitting lockouts; `sensor_fault` on one row; rate-limit storms | Next business day triage; updates daily | Security Lead or Ops Lead |
| **SEV-4 Low** | Hygiene findings, single false positive | Vulnerability report with no exploit; policy deviation | Tracked in backlog | — |

Severity is set by the IC and may be raised at any time. Any incident involving personal data starts the DPA clock (§7) regardless of severity.

## 3. Detection sources

| Source | What it reveals | Available today |
|---|---|---|
| `GET /api/v1/admin/ledger/verify` | Chain break, hash mismatch, invalid signature (`services/ledger.py verify_chain`) | Yes — run hourly by cron until CloudWatch exists |
| `GET /api/v1/admin/audit` | Privileged actions with actor, before/after, IP | Yes |
| `GET /api/v1/admin/ledger?type=clearance.overridden` | Every override with user and reason | Yes |
| `GET /api/v1/weighing/events?decision=RED` and `identity.method='conflict'` | Identity conflicts (possible cloning) | Yes |
| `SecurityAnomalyAgent` alerts (`repeated_identity_conflict`, `impossible_travel`, `override_burst`, `credential_stuffing`) | Pattern-level anomalies | Agent exists and is tested; **scheduler and event feeds planned (Phase 3)** — until then run ad hoc via the orchestrator with a manually built event list |
| `station.failure`, `sensor.health`, `incident.opened` events (`events.py`) | Station/lane problems | Yes (WebSocket, `/admin/incidents`) |
| `GET /api/v1/admin/system/health` | DB/Redis/MQTT configured state, weighings per hour, WS subscribers | Yes |
| CloudWatch alarms, GuardDuty, IoT auth failures, WAF logs | Cloud-side attacks | **(AWS, designed)** |
| Reports from operators, transporters, regulator | Field observation (e.g. truck cleared GREEN visibly overloaded) | Yes — report via Ops Lead |

## 4. Standard response procedure

1. **Record.** Scribe opens an incident via `POST /admin/incidents` (`category=security`, severity) and a timeline file `incidents/<ULID>/timeline.md` (outside the repo). Note the `incident_id`, time of detection, who detected it.
2. **Triage.** Security Lead confirms the signal, assigns severity with the IC, identifies affected assets (`threat-model.md` §4 asset list) and whether personal data is involved (→ §7).
3. **Preserve evidence** (§6) *before* containment actions that change state.
4. **Contain** per playbook (§5). Prefer actions that keep the legal path (static scale) running; the WIM pre-screen can always be set to AMBER-only or offline.
5. **Eradicate**: rotate credentials/keys (`maintenance.md` §6), patch, rebuild from known-good images.
6. **Recover**: restore service, verify with `ledger/verify`, `system/health`, test passes on a lane with `source=simulated` **only in non-production**; in production, verify with the first live passes compared against the static scale.
7. **Close**: `POST /admin/incidents/{id}/close`; post-incident review within 5 business days; update `threat-model.md` §8 findings and this plan.

## 5. Playbooks

### IR-01 Compromised operator (or admin) account

**Indicators:** `credential_stuffing` alert or many 401/423 on one e-mail; login from unusual IP/user-agent in `core.refresh_sessions`; `override_burst`; audit actions the operator denies; MFA enable/disable the user did not perform.

| Step | Action | How (today) | Notes |
|---|---|---|---|
| 1 | Preserve | Export `audit_events` and `refresh_sessions` for the user; export ledger range (§6) | Before any change |
| 2 | Contain — disable account | `PATCH /api/v1/admin/users/{id}` `{"is_active": false}` | Takes effect on the next request: `get_current_principal` re-checks `is_active`, so **access tokens die immediately**, not at expiry |
| 3 | Contain — kill sessions | No "revoke all" endpoint yet (`security-controls.md` C-11). Interim: SQL `UPDATE core.refresh_sessions SET revoked_at = now() WHERE user_id = :id` by the Security Lead, logged in the timeline | Add endpoint in Phase 3 |
| 4 | Contain — scope of damage | Query `audit_events` by `actor_user_id` for the window; query ledger `clearance.overridden`, `static.verified` with `operator = user_id`; list `watchlist` changes and `calibrate` actions | Overrides and static entries are the high-value targets |
| 5 | Operational fallback | If overrides or false static results are suspected: Ops Lead re-weighs affected trucks if still on site; notifies KeNHA liaison of affected ticket IDs | Static scale is the legal reference; WIM tickets are pre-screen |
| 6 | Eradicate | Reset password (admin-issued temporary), require MFA enrolment, review e-mail account security with the user's employer | If admin account: rotate `KIFARU_JWT_SECRET` (forces all users to re-authenticate within 15 min, §`maintenance.md` 6.1) |
| 7 | Recover | Re-enable account only after MFA is enabled; monitor for 7 days | — |
| 8 | Report | If any PII was viewed/exported (e.g. `/fleet/drivers` listing by a platform-wide role) → §7 | — |

### IR-02 Cloned-tag wave

**Indicators:** several `identity_events.method='conflict'` within hours; `repeated_identity_conflict` for the same plate; `impossible_travel` for one EPC across stations; a transporter reports a truck flagged RED that was not at the station.

| Step | Action | How |
|---|---|---|
| 1 | Preserve | Export `identity_events`, `weighing_events`, `clearance_decisions` for the window and the EPCs; export ANPR evidence images (S3 keys in `identity_events.evidence_keys`, designed) |
| 2 | Contain — revoke tags | For each suspect EPC set `core.rfid_tags.revoked_at = now()` (no API yet; SQL by Security Lead, audit note in timeline). Revoked tags stop resolving in `services/identity.resolve`, so the next pass becomes `anpr`-only (≤ 0.95) or `VEHICLE_UNKNOWN` → AMBER, never a borrowed identity |
| 3 | Contain — tighten identity policy | Raise `KIFARU_IDENTITY_MIN_CONFIDENCE` to `0.96` so single-source identity (cap 0.95) can no longer reach GREEN while the wave lasts (`config.py`); restart API tasks | Reversible; increases AMBER rate — inform Ops |
| 4 | Contain — watch-list | `POST /fleet/vehicles/{id}/watchlist` with reason `"cloned tag investigation <incident_id>"` for the *victim* vehicles so every pass is RED and checked statically until re-tagged | Audited |
| 5 | Investigate | Build the agent event list from `identity_events` + station coordinates and run `Orchestrator().run("security_anomaly", ...)` to list `impossible_travel` pairs; correlate with transporter dispatch records | Manual until the worker exists |
| 6 | Eradicate | Issue new tags to victims; if Phase 6 hardware supports TID-locked tags, migrate the affected fleet first | — |
| 7 | Report | Notify KeNHA liaison with ticket IDs and plates; notify the affected transporter(s). Personal data is not normally exposed in this scenario, but wrongful RED attribution to a driver is a fairness issue — record it in the DPIA log | — |
| 8 | Lessons | Feed into `threat-model.md` T-01; decide on permanent two-source rule | — |

### IR-03 Ransomware on an edge gateway

**Indicators:** heartbeat loss from `gw-<station>-l<n>`; `station.failure`; operator sees ransom note or encrypted filesystem on the IPC; MQTT connection drops while the DAQ still shows traffic.

| Step | Action | How |
|---|---|---|
| 1 | Safety first | Ops Lead sets the lane to **offline** (`POST /stations/{id}/status` `{"status":"offline"}` creates an incident automatically, `routers/stations.py`) and switches the VMS to "ALL VEHICLES TO STATIC SCALE". The legal weighing path is unaffected |
| 2 | Isolate | Pull the WAN uplink from the cabinet router; leave the IPC powered for forensics if a forensic image is feasible, otherwise power off (document the choice) |
| 3 | Preserve | Photograph screen; image the disk if tooling is available; note the last `edge_event_id` received in the cloud (`weighing_events` filter by `lane_id`, latest `occurred_at`) — anything after that is lost unless the outbox is recoverable |
| 4 | Assess spread | Check other gateways' connectivity; check whether the gateway's device credentials were used from another IP (**AWS IoT logs, designed**); check `POST /weighing/ingest` audit for unexpected `device_id` use |
| 5 | Eradicate | Revoke the gateway's device certificate (**AWS, designed**) or, today, change the lane's `device_id` so stale credentials cannot map to the lane; wipe and re-image the IPC from the signed base image (Phase 6 deliverable); restore config from Secrets Manager/offline copy |
| 6 | Recover | Re-provision certificate; verify clock (GPS/NTP); run the lane in **shadow mode** (decisions logged but VMS still sends all trucks to static) for the first 50 passes; compare WIM vs static via `static.verified` entries; then `status=operational` |
| 7 | Data | Gateway disks hold plate images and OCR text (≤ 30 days by policy). Encryption-only ransomware is a loss of availability; if exfiltration is suspected treat as a personal-data breach → §7 |
| 8 | Lessons | Confirm immutable-image and outbound-only firewall items in `threat-model.md` §4.2 |

### IR-04 Personal-data breach (DPA 72-hour procedure)

Applies to any confirmed or reasonably suspected unauthorised access, disclosure, alteration or loss of personal data (`dpia.md` §2 inventory D1–D15). The clock starts when the controller becomes aware.

| T+ | Action | Owner | Artefact |
|---|---|---|---|
| 0 h | Declare SEV-1/2; open incident; start breach log | IC / Scribe | `incidents/<id>/breach-log.md` |
| 0–4 h | Preserve evidence (§6); contain (disable accounts, rotate secrets, restrict DB access, block egress) | Security Lead | Evidence manifest |
| 4–12 h | Determine: categories and approximate number of data subjects and records; data elements (plates? phones? IDs?); likely consequences; measures taken | Security Lead + DPO | Breach assessment form (Annex A) |
| 12–24 h | Legal review of notification duty and wording; identify whether the platform is controller or processor for the affected data (`dpia.md` §3). **If processor**, notify the controller (transporter/cargo owner) *without undue delay* so their 72-hour clock can be met [counsel] | DPO + counsel | Draft notice |
| ≤ 72 h | Notify the Office of the Data Protection Commissioner using the ODPC breach-notification form (content per s.43(3): nature of the breach, data affected, likely consequences, measures taken, contact point) | DPO | Submission receipt |
| ≤ 72 h (or as soon as reasonably practicable where delay would increase harm) | Notify affected data subjects **where there is a real risk of harm** (e.g. phone numbers and names exposed) in plain language, by SMS/e-mail via the platform or through the transporter; include protective steps and contact | DPO + Communications | Sent-message log |
| Ongoing | Update ODPC if facts change; keep the breach register (s.43 record-keeping duty) even for breaches not notified, with reasons | DPO | Breach register |
| ≤ 5 business days after closure | Post-incident review; DPIA update | IC | Review report |

Decision aid for "real risk of harm" [counsel]: exposure of names+phones of drivers → likely yes (harassment, fraud); exposure of plates and weights only → assess case-by-case (indirect identifiers, operational data); exposure of password hashes → yes (force resets).

### IR-05 Ledger or ticket integrity alarm

**Indicator:** `GET /admin/ledger/verify` returns `ok:false` with `prev_hash mismatch`, `hash mismatch` or `signature invalid at seq N`; a ticket shows `signature_valid:false`.

1. **Do not "repair" the chain.** Export the full `ledger_events` table and the latest anchored head hash (when anchoring exists) to immutable storage.
2. Identify `seq N` and the surrounding rows; compare with the application logs of the same time; check `audit_events` for DB-level actors; check for duplicate `seq` values (concurrency gap, `threat-model.md` F2) — a duplicate `seq` with otherwise valid hashes indicates a race, not an attack.
3. Check whether the signing key was rotated without a key registry (`maintenance.md` §6.2): `signature invalid` on **all** rows before a date with valid hashes indicates rotation, not tampering.
4. If tampering is plausible: SEV-1; set stations to AMBER-only; treat all decisions from `seq N` onward as unverified until reconciled against static-scale records; notify KeNHA liaison.
5. Rebuild trust: restore from backup to a forensic instance, diff against production, document the delta; rotate signing seed and JWT secret; re-anchor.

### IR-06 Fraudulent GREEN suspected (field report)

1. Record ticket ID / plate / time; pull `GET /weighing/events/{id}` (full `rules_fired`, `margins`, `quality_flags`, `sensor_health`, identity method and confidence, `evidence_hash`).
2. If the truck is still available, weigh statically and record via `POST /weighing/events/{id}/static-verify` — this writes `static.verified` with `wim_error_pct` to the ledger.
3. If `wim_error_pct` beyond −5 %: suspect calibration/gain tampering or sensor issue → lane to AMBER-only; schedule reference-vehicle calibration (`maintenance.md` §4); inspect DAQ/cabinet seals.
4. If identity method was `rfid`-only or `anpr`-only: suspect cloning/spoofing → IR-02.
5. If an override exists on the decision: IR-01 for the operator.

## 6. Evidence preservation using the ledger

The ledger (`core.ledger_events`) is the platform's primary forensic record because every row is hash-chained to the previous one and signed (`services/ledger.py`). Preservation steps:

1. **Snapshot the chain head.** `GET /api/v1/admin/ledger/verify` → record `head_hash`, `total`, `checked`, `signer_key_id`, `public_key` and the UTC time in the timeline. This fixes the state at detection; any later alteration of earlier rows changes the head hash.
2. **Export.** `GET /api/v1/admin/ledger?limit=1000&type=...` paged, or a read-only DB export (`COPY core.ledger_events TO ...`) run by the Security Lead with a second person present. Compute SHA-256 of the export file; record it. Store on write-once media / S3 Object Lock (designed).
3. **Export related tables** for the window: `weighing_events`, `axle_measurements`, `identity_events`, `clearance_decisions` (includes `evidence_hash`, `signature`, `override_reason`), `digital_tickets` (payload + signature), `audit_events`, `refresh_sessions`. Hash each file.
4. **Re-verify independently.** Any party holding the public key (printed in every ticket payload and in `/admin/ledger/verify`) can recompute `sha256(canonical_json(core))` for each row and check the Ed25519 signature over `{"hash": h}` — the canonicalisation is `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` (`security.canonical_json`). Document the verification result.
5. **Chain of custody.** Who exported, when, hash, storage location, who accessed since. Keep in the timeline.
6. **Do not delete or "fix" rows.** If the chain is broken, the break itself is evidence. Note that `static_verify` currently deletes the prescreen ticket row (`threat-model.md` F9) — the ledger entry `clearance.decided` retains the original `ticket_id`, so cite the ledger, not the ticket table, for pre-screen evidence.
7. **Decision evidence.** `clearance_decisions.evidence_hash` is a SHA-256 over all engine inputs and all rule results (`clearance_engine.decide`). If the original inputs are available (measurement JSON from the gateway outbox), the hash can be recomputed to prove the decision was derived from them.
8. **Logs.** Preserve structlog JSON output for the window (CloudWatch export, designed; locally the container stdout).

## 7. Notification matrix

| Party | When | Channel | Owner |
|---|---|---|---|
| Project owner | All SEV-1/2 immediately; SEV-3 daily digest | Phone + e-mail | IC |
| ODPC | Personal-data breach ≤ 72 h (§5 IR-04) | ODPC breach form | DPO |
| Affected data subjects | Real risk of harm | SMS/e-mail/transporter | DPO |
| Controllers we process for (transporters, cargo owners) | Any breach of their data, without undue delay | E-mail + platform notification (`POST /notifications/send`) | DPO/Comms |
| KeNHA / KPA liaison | Integrity incidents affecting clearance decisions or tickets; station offline > 2 h | Agreed liaison channel | Comms |
| AWS Support | Suspected infrastructure compromise **(AWS, designed)** | Support case | Security Lead |
| Law enforcement (DCI) | Confirmed fraud or extortion, on counsel's advice | Via counsel | Owner |

## 8. Preparation checklist (before pilot)

- [ ] Names in §1 filled and contact sheet distributed
- [ ] DPO/designate appointed; ODPC registration done (`dpia.md` §10)
- [ ] Hourly `ledger/verify` job and alarm in place
- [ ] "Revoke all sessions" and "revoke tag" endpoints implemented (today SQL)
- [ ] Signed gateway image and re-provisioning procedure (Phase 6)
- [ ] Key registry so that key rotation does not look like tampering (`maintenance.md` §6.2)
- [ ] Table-top exercise of IR-01, IR-02, IR-04 with weighbridge staff
- [ ] Breach register and Annex A form created
- [ ] This plan reviewed by counsel for §5 IR-04 and §7

## Annex A — Breach assessment form (fields)

Incident ID · Date/time aware · Date/time occurred (if known) · Description · Systems affected · Data categories (map to `dpia.md` §2 D-numbers) · Approximate number of data subjects · Approximate number of records · Controller/processor role for this data · Likely consequences · Measures taken / proposed · Cross-border element · Notified ODPC (Y/N, date, reference) · Notified subjects (Y/N, date, method) · Notified controllers (Y/N) · Reason if not notified · Reviewer · Sign-off.

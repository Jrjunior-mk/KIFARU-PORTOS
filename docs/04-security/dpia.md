# KIFARU PORTOS — Data Protection Impact Assessment (DPIA)

| Field | Value |
|---|---|
| Document | `docs/04-security/dpia.md` |
| Version | 0.1 (draft for counsel review) — 2026-11-04 |
| Legal framework | Data Protection Act, 2019 (Kenya, No. 24 of 2019) ("the Act"); Data Protection (General) Regulations, 2021; Data Protection (Registration of Data Controllers and Data Processors) Regulations, 2021; Data Protection (Complaints Handling Procedure and Enforcement) Regulations, 2021 |
| Assessor | Cybersecurity engineer / Technical writer (engineering view) |
| Status of legal statements | **Every statement of law or legal interpretation in this document is an engineering reading and is marked "[counsel]" where it requires confirmation by qualified Kenyan counsel before reliance.** |
| Trigger | Section 31 of the Act requires a DPIA where processing is likely to result in high risk to the rights and freedoms of data subjects. Systematic monitoring of vehicles and drivers on public roads, processing of national ID numbers, and cross-border transfer meet that threshold in the assessor's view [counsel]. |

## 1. Description of the processing

### 1.1 Purpose

KIFARU PORTOS pre-screens heavy goods vehicles at weigh-in-motion lanes (Mariakani, Athi River, Gilgil, Port of Mombasa Gate 18 in the seed data), issues GREEN/AMBER/RED clearance decisions, produces signed digital weighing tickets and cargo passports, forecasts queues and allocates slots, operates a backhaul marketplace, and notifies drivers, dispatchers and cargo owners. The static weighbridge remains the legal reference; the platform's decisions are pre-screening (`docs/01-requirements/requirements-traceability-matrix.md` RCS-07).

### 1.2 Nature and scope

| Property | Value |
|---|---|
| Data subjects | Drivers (employees/contractors of transporters); platform users (operators, dispatchers, cargo owners, warehouse staff, regulators); indirectly, vehicle owners identifiable through plates |
| Scale (pilot) | Seed data: 4 stations, 8 vehicles, 10 users. Pilot estimate: 1 000–3 000 lane passes per day at Mariakani (engineering assumption, not measured) |
| Geography | Collection in Kenya (roadside); storage designed for AWS `af-south-1` (Cape Town, South Africa); DR copies in `eu-west-1` (Ireland) |
| Automation | Clearance decision is fully automated (deterministic rules); AI agents are advisory (`packages/ai_agents`, `AGT-02`). Release prediction and backhaul matching are automated *recommendations* requiring human acceptance (BKH-04). |
| Monitoring | Continuous capture of plate images and RFID reads on public roads at fixed lanes |

### 1.3 Data flow

```
 Lane (ANPR image, plate text, RFID EPC, axle loads, speed, time) ──mTLS──► cloud ingest ──► core.weighing_events / core.identity_events
                                                                                           │
 Registration (driver name, phone, licence no., national ID; user name, e-mail, phone) ───► pii.driver_pii / pii.user_pii (separate schema)
                                                                                           │
 Telematics (vehicle lat/lon) ───────────────────────────────────────────────────────────► core.vehicles.last_lat/lon
                                                                                           │
                        Outputs: tickets (plate), passports, SMS to driver phone, WS events (plate), audit/ledger (user IDs), S3 evidence images
```

## 2. Data inventory

| # | Data element | Category under the Act | Where stored (code) | Source | Necessity |
|---|---|---|---|---|---|
| D1 | Driver full name | Personal data | `pii.driver_pii.full_name` (`models/fleet.py`) | Transporter (`POST /fleet/drivers`) | Identify driver on shipment, delivery record |
| D2 | Driver phone | Personal data | `pii.driver_pii.phone_enc` | Transporter | SMS notifications (Module 7) |
| D3 | Driver licence number | Personal data | `pii.driver_pii.license_no_enc` (column exists; no API writes it yet) | — | Future NTSA validation; **not currently collected** |
| D4 | National ID number | Personal data (identifier; high sensitivity in practice) | `pii.driver_pii.national_id_enc`, `pii.user_pii.national_id_enc` (columns exist; **no API writes them**) | — | **Not currently collected**; retain column only if a lawful purpose is confirmed [counsel] |
| D5 | User name, e-mail, phone | Personal data | `core.users.email`, `pii.user_pii` (`models/auth.py`) | Self-registration / admin | Account, notifications |
| D6 | Password hash, TOTP secret | Security credentials | `core.users.password_hash` (Argon2id), `core.users.mfa_secret` | User | Authentication |
| D7 | Login IP, user agent, timestamps | Personal data (online identifiers) | `core.refresh_sessions`, `core.audit_events.ip` | System | Security, audit |
| D8 | Vehicle registration plate | **Indirect identifier** (links to registered keeper via NTSA; treated as personal data in the assessor's view [counsel]) | `core.vehicles.plate`, `core.identity_events.anpr_plate`, ticket payloads, WS payloads, public verify response | ANPR, registration | Identity for clearance; legal record |
| D9 | ANPR image (evidence) | Personal data (may show driver face/cab) | S3 `evidence` (designed; `identity_events.evidence_keys`) | Camera | Evidence for disputes |
| D10 | RFID EPC | Pseudonymous identifier (tag → vehicle) | `core.rfid_tags`, `identity_events.rfid_epc` | Reader | Identity |
| D11 | Vehicle position (lat/lon, time) | Location data; personal data where vehicle is attributable to a driver | `core.vehicles.last_lat/lon/last_seen_at` (`routers/fleet.py update_position`) | Driver app / telematics adapter | Backhaul matching, ETA |
| D12 | Weighing results, decisions, tickets | Operational data linked to D8 | `core.weighing_events`, `core.clearance_decisions`, `core.digital_tickets` | Lane | Legal/compliance record |
| D13 | Shipment, declaration, seal, container numbers | Commercial data (organisational, not personal) | `core.shipments` etc. | Cargo owner | Cargo passport |
| D14 | Audit and ledger entries containing `user_id` | Personal data (pseudonymous) | `core.audit_events`, `core.ledger_events` (e.g. `clearance.overridden.by`) | System | Accountability |
| D15 | Notification bodies | May contain plate, reference | `core.notifications` | System | Delivery log |

**Special categories** (s.2 of the Act — race, health, biometrics, etc.): none are intended. ANPR images could incidentally capture faces; the platform does not perform facial recognition. Images are to be cropped to the plate region where feasible (planned, Phase 6) [engineering].

**Children's data**: none expected (drivers are licensed adults).

## 3. Controller and processor roles [counsel]

| Processing | Controller | Processor | Basis of the view |
|---|---|---|---|
| Platform user accounts (D5–D7) | KIFARU PORTOS operating entity | AWS (infrastructure) | Operator determines purpose and means |
| Lane capture and clearance (D8–D12) | KIFARU PORTOS operating entity **jointly with** the enforcement authority (KeNHA) where the lane is operated under its mandate | AWS | Purpose (axle-load control) is set by the authority; means by the platform. Joint-controller arrangement under s.2/s.26 to be documented [counsel] |
| Transporter fleet and driver data (D1–D4, D11) | Transporter (customer) | KIFARU PORTOS operating entity | Transporter uploads its employees' data and determines purposes; platform processes on instruction (`cloud-architecture.md` §1 states this split) |
| Cargo owner commercial data (D13) | Cargo owner | KIFARU PORTOS | Same |
| Sub-processors | — | AWS (hosting, af-south-1 and eu-west-1), Africa's Talking (SMS, Kenya), SES (e-mail) | Written processor terms required (s.42) [counsel] |

Consequences: the operating entity must register with the ODPC **both** as a data controller and as a data processor (Registration Regulations 2021, thresholds and exemptions to be checked [counsel]); must sign processor agreements with each transporter/cargo owner (recommended: standard terms embedded in the platform T&Cs); and must have a processor agreement with AWS (AWS Data Processing Addendum) and Africa's Talking.

## 4. Lawful basis (s.30) [counsel]

| Processing | Proposed basis | Reasoning | Alternatives considered |
|---|---|---|---|
| Lane capture, clearance decision, tickets, ledger (D8–D12) | s.30(1)(b)(iii) public interest / exercise of official authority **when operated for KeNHA under the EAC Vehicle Load Control Act 2016**; otherwise s.30(1)(b)(vi) legitimate interests of the controller (road safety, infrastructure protection) | Overload control is a statutory function; consent is not realistic for a vehicle passing a lane | Consent (rejected: no genuine choice); contract (only for registered transporters) |
| Driver registration by transporter (D1–D3) | s.30(1)(b)(i) performance of a contract (transporter–platform) and the transporter's own employment basis | Platform acts as processor | — |
| Platform accounts (D5–D7) | Contract with the user | — | — |
| SMS notifications to drivers (D2) | Contract / legitimate interest, with opt-out (`SMS_TEMPLATES` include "Reply STOP to opt out") | Operational messages, not marketing | Consent for any marketing use (none planned) |
| Vehicle positions (D11) | Contract with transporter; legitimate interest for backhaul matching | Driver informed via transporter; positions are coarse and only the *last* position is stored | — |
| Public ticket verification revealing plate (D8) | Legitimate interest (verifiability of a compliance document) | Tokens are unguessable (192-bit); only the holder of the QR can query | Mask plate (planned) reduces exposure further |
| National ID numbers (D4) | **No basis identified today** | Columns exist but nothing writes them | Remove columns or document purpose before use |

## 5. Necessity and proportionality

| Principle (s.25) | Assessment | Measure |
|---|---|---|
| Lawfulness, fairness, transparency | Drivers on public roads cannot reasonably be asked for consent; transparency must come from signage at lanes and a published privacy notice | Lane signage ("Vehicles are weighed and photographed for axle-load control; see kifaru…/privacy"); privacy notice; transporter obligation to inform drivers (contract) |
| Purpose limitation | Lane data used for clearance, compliance, queue statistics, modelled emissions. Backhaul uses positions, not lane data | Purpose list in privacy notice; no sale of data; no profiling of drivers |
| Data minimisation | Only `last_lat/lon` kept for vehicles (no track history); SMS ≤ 160 chars; public verify returns 10 fixed fields (`routers/tickets.py VerifyOut`, tested); national ID and licence columns unused | Remove D3/D4 columns unless justified; crop ANPR images to plate; strip `plate` from tenant-wide WS payloads (threat-model F-list) |
| Accuracy | Identity has a confidence score; low confidence routes to human verification (AMBER); static scale corrects WIM | Correction channel for wrongly attributed passes (dispute via transporter) |
| Storage limitation | No retention enforced in code today | Retention schedule §8 |
| Integrity and confidentiality | Argon2id, TLS (designed), schema separation, signed records; **PII columns currently plaintext** | `security-controls.md` C-05 plan |
| Accountability | Audit log, ledger, this DPIA, ODPC registration | DPO/designate appointment |

Automated decision-making (s.35): the clearance decision is automated but (a) it is a *pre-screen* with the legal weight determined by a human-operated static scale, (b) every decision carries `rules_fired`, `margins` and `explanation` (`clearance_engine.py`), and (c) `override-release` provides human intervention. In the assessor's view the "right not to be subject to a decision based solely on automated processing" is satisfied by the AMBER/RED → human path and by the explanation record [counsel].

## 6. Cross-border transfer (ss.48–49) [counsel]

| Item | Position |
|---|---|
| Transfer | Storage and processing in AWS `af-south-1` (Cape Town, South Africa); backups replicated to `eu-west-1` (Ireland); CloudFront edge caches in Nairobi hold only static web assets, not personal data |
| Why | No AWS region in Kenya; af-south-1 is the nearest with managed IoT, PostgreSQL, KMS (`docs/02-architecture/cloud-architecture.md` §1). Decision is reversible: the stack is plain PostgreSQL/Redis/S3-compatible |
| Conditions under s.48 | (a) proof of appropriate safeguards — AWS DPA with standard contractual clauses, ISO/IEC 27001/27017/27018 certifications, encryption at rest and in transit [counsel to confirm sufficiency]; (b) alternatively consent — not practicable for lane data; (c) necessity for contract — applicable to transporter/cargo-owner data |
| s.50 sensitive personal data | The Act allows the Cabinet Secretary to prescribe that certain processing be performed in Kenya only. The Data Protection (General) Regulations, 2021 contain a data-localisation provision for processing of *strategic interest to the state* (reg. 26 in the assessor's reading) which lists categories such as civil registration and national security systems. Whether axle-load enforcement records fall within this is a question for counsel and the regulator **[counsel — potentially decisive for architecture]**. Mitigation path: keep a Kenya-resident copy (e.g. on-premises PostgreSQL replica at the owner's data centre) of `core.weighing_events`, `clearance_decisions`, `digital_tickets`, `ledger_events` and all of `pii`. |
| Safeguards in design | TLS in transit; KMS encryption at rest (designed); PII schema with planned column encryption so that AWS staff cannot read identifiers; access only from the platform's VPC; audit of all PII access (planned) |
| Transfer record | To be entered in the register of processing activities (§11) |

## 7. Data-subject rights (ss.26, 32–40) handling

| Right | Current capability | Gap | Planned |
|---|---|---|---|
| To be informed (s.26(a)) | None published | Privacy notice, lane signage | Phase 3 (owner approval required) |
| Access (s.26(b)) | `GET /auth/me`; transporter can list own drivers; weighing events filterable by vehicle | No self-service export; drivers are not platform users unless given the `driver` role | Export endpoint `GET /me/data` (JSON) and manual process via DPO within 7 days (reg. timelines [counsel]) |
| Rectification (s.26(d)) | Admin/transporter can edit most records; `PATCH /admin/users` | No driver self-service | Process via transporter; audit trail exists |
| Erasure (s.26(e)) | None | Legal/compliance records (tickets, ledger) must be **retained** — erasure applies to PII fields, not to the ledger. Ledger entries reference `user_id` ULIDs only | Pseudonymisation routine: null `pii.*` rows and e-mail → `deleted-<ulid>`; keep ULID so ledger integrity holds |
| Objection (s.26(c)) | SMS opt-out text in templates; no mechanism | — | STOP keyword handler via SMS adapter |
| Portability (s.38) | — | — | JSON export covers it |
| Not subject to solely automated decisions (s.35) | AMBER/RED → human; explanations stored | — | Dispute channel documented in privacy notice |
| Complaints | — | — | DPO contact; ODPC complaints procedure reference |

## 8. Retention schedule (proposed)

> **Reference note.** The Master Prompt asks that retention be cited from `database-erd.md` §3. That file is referenced by RTM DB-01 and by `alembic/versions/0001_initial.py` but **does not yet exist in the repository** at the time of this assessment. The schedule below is therefore a *proposal* to be ratified in `docs/02-architecture/database-erd.md` §3 when it is written; it is not yet implemented in code (`security-controls.md` C-15).

| Data | Retention | Justification | Mechanism |
|---|---|---|---|
| `static_certified` tickets, `ledger_events`, `clearance_decisions`, `weighing_events` (without images) | 7 years from `occurred_at` [counsel: align with enforcement/limitation periods and KeNHA records policy] | Legal evidence of compliance; audit | Partition by year; archive to S3 Glacier with Object Lock after 2 years |
| `prescreen` tickets | 2 years | Operational and dispute window | Purge job |
| ANPR evidence images (S3) | 30 days unless linked to an AMBER/RED decision, dispute or incident (then 2 years) | Minimisation | S3 lifecycle rule + legal hold tag |
| Raw signal windows (`raw_ref`) | 90 days | Calibration and DSP validation | S3 lifecycle |
| `identity_events` | Same as weighing events, but `anpr_plate`/`rfid_epc` pseudonymised after 2 years | Minimisation | Scheduled update |
| `pii.driver_pii`, `pii.user_pii` | Life of the relationship + 12 months after deactivation | Contract, disputes | Pseudonymisation routine |
| `refresh_sessions` | 90 days after expiry | Security forensics | Purge |
| `audit_events` | 7 years | Accountability | Archive |
| `vehicles.last_lat/lon` | Overwritten on each update (no history) | Minimisation | By design |
| `notifications` | 12 months | Delivery disputes | Purge |
| `queue_records`, `ts.sensor_readings` | 2 years (aggregates indefinitely) | Forecasting models; not personal | `pg_partman` partition drop |
| Backups | 35 days rolling (RDS); monthly `pg_dump` 12 months | DR | Lifecycle rules |

## 9. Risk assessment

Likelihood/severity on a 3-point scale (Low/Medium/High) as is customary for DPIAs; residual after planned measures.

| # | Risk to data subjects | Source | L | S | Existing measures (code) | Planned measures | Residual |
|---|---|---|---|---|---|---|---|
| R1 | Unauthorised disclosure of driver names/phones/IDs from DB | Breach, insider | M | H | Separate `pii` schema; `REVOKE … FROM PUBLIC`; RBAC; Argon2id; MFA available | Column-level encryption (pgcrypto/KMS), dedicated PII DB role, forced MFA, RDS encryption | L |
| R2 | Tracking of individual drivers' movements via plate/EPC history | Function creep, insider query | M | M | Only last position stored; weighing events are per lane pass (inherently a location) | Purpose limitation in notice; auditor review of `weighing/events?vehicle_id=` queries; pseudonymise `anpr_plate` after 2 years | L–M |
| R3 | Plate exposed via public QR verify or station-wide WS feed | Design | M | L | Unguessable token; fixed field set; WS tenant filter | Plate masking on public verify; strip plate from non-platform WS payloads | L |
| R4 | Wrong attribution (ANPR misread, cloned tag) leading to a driver/transporter being wrongly flagged RED | Accuracy | M | M | Confidence scores; conflict → RED → **human** static check (so no penalty is issued from WIM alone); explanations | Dispute channel; two-source rule | L |
| R5 | Cross-border access by foreign authorities / cloud staff | Transfer | L | M | TLS; designed KMS | Column encryption with Kenya-controlled keys; Kenya-resident replica if localisation applies | L (pending counsel) |
| R6 | Excessive collection (national ID, licence) | Design drift | L | H | No code writes these columns | Remove or justify columns | L |
| R7 | SMS to wrong/stale number revealing shipment movements | Data quality | M | L | Phone held by transporter; templates minimal | Confirmation on first SMS; STOP handling | L |
| R8 | Images capture faces / bystanders | Collection | M | M | Not yet implemented (Phase 6) | Plate-region crop; 30-day retention; no facial recognition policy | L |
| R9 | Inability to honour erasure because of immutable ledger | Design | M | M | Ledger holds ULIDs, not names | Pseudonymisation of PII rows; documented in notice | L |
| R10 | Loss of availability of compliance records (ransomware) | Security | L | M | Designed backups | Object Lock, restore drills | L |

## 10. Measures summary and owner actions

| Measure | Owner | Phase | Status |
|---|---|---|---|
| ODPC registration (controller + processor) | Project owner | before prod | Not started (requires entity details) |
| Appoint DPO or designated contact | Project owner | before pilot | Not started |
| Privacy notice + lane signage text | Technical writer → counsel | 3 | Draft pending |
| Processor terms in platform T&Cs; AWS DPA; Africa's Talking terms | Counsel | 3 | Not started |
| Joint-controller arrangement with KeNHA | Owner + KeNHA | 6/7 | Depends on regulator engagement |
| Column-level PII encryption; PII DB role | Backend | 3 | Planned (`security-controls.md` C-05) |
| Plate masking on public verify; WS payload minimisation | Backend | 3 | Planned |
| Remove/justify `national_id_enc`, `license_no_enc` | Backend + owner | 2 | Decision required |
| Data-subject export/erasure routines | Backend | 3 | Planned |
| Retention jobs; ratify schedule in `database-erd.md` §3 | Backend + DBA | 3 | Planned; ERD document missing |
| Localisation determination (reg. 26) | Counsel | before prod | **Open — may require Kenya-resident replica** |
| Register of processing activities | DPO | 3 | Template §11 |

## 11. Register of processing activities (template, to be maintained)

| Activity | Purpose | Categories of subjects | Categories of data | Recipients | Transfers | Retention | Security |
|---|---|---|---|---|---|---|---|
| Rolling clearance | Axle-load pre-screening | Drivers/keepers | D8–D12 | KeNHA (when integrated), transporter of the vehicle | af-south-1, eu-west-1 (backup) | §8 | TLS, signed records, RBAC |
| Account management | Platform access | Users | D5–D7 | None | af-south-1 | §8 | Argon2id, MFA |
| Fleet/driver management (as processor) | Transporter operations | Drivers | D1–D3, D11 | Transporter | af-south-1 | §8 | Schema separation |
| Notifications | Operational messaging | Drivers, users | D2, D5, D15 | Africa's Talking, SES | Kenya (SMS), af-south-1 | 12 months | TLS |
| Backhaul marketplace | Match return cargo | Dispatchers, cargo owners | D11, D13 | Counter-party org (after match) | af-south-1 | §8 | org scoping |

## 12. Sign-off

| Role | Name | Date | Decision |
|---|---|---|---|
| Assessor (engineering) | — | 2026-11-04 | Draft complete |
| Counsel (Kenya DPA) | — | — | Pending: items marked [counsel], especially §3, §4, §6 (localisation) |
| Data Protection Officer / designate | — | — | Pending appointment |
| Project owner | — | — | Pending |

This DPIA must be reviewed before pilot (Phase 7), on any change to the data inventory, on activation of any government adapter in `real` mode, and at least annually.

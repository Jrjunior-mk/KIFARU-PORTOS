# KIFARU PORTOS — Security Control Catalogue

| Field | Value |
|---|---|
| Document | `docs/04-security/security-controls.md` |
| Version | 0.1 — 2026-11-04 |
| Maps to | Master Prompt §11 control list; RTM `SEC-01`; `threat-model.md` findings F1–F18 |
| Status vocabulary | **Implemented** = present in the reviewed code and exercised by a test; **Partial** = present but with a documented gap; **Designed** = specified in `docs/02-architecture/` only; **Planned (n)** = scheduled for roadmap phase *n* |

## 1. How to read this catalogue

Each control states what the Master Prompt asks for, what the code does today (with file references), what is only designed, and the concrete action the project owner must take. The honesty rule of this project applies: nothing marked *Implemented* lacks a code path, and nothing that exists only in Terraform plans or architecture text is called implemented. No cloud deployment has been performed, so every AWS-side control is at best *Designed*.

Evidence of implemented controls: `apps/api/tests/test_security.py` (8 tests), `tests/test_api_flow.py` (22), `tests/test_clearance_engine.py` (15) — 45 passing on SQLite locally at the time of writing; `packages/wim_dsp` 24, `packages/ai_agents` 8.

## 2. Control catalogue

### C-01 Role-based access control (RBAC)

| Aspect | Detail |
|---|---|
| Requirement | Seven dashboards / ten roles; every action authorised by role; tenants isolated |
| Implemented | Ten roles in `models/auth.py ROLE_NAMES`; roles stored in `core.user_roles` and embedded in the access token at login; `deps.require_roles(*roles)` dependency per endpoint; `platform_admin` is a superset (`Principal.has_role`); tenant scoping via `deps.org_scope()` applied in fleet, weighing, shipments, queue, backhaul routers; WebSocket filter by `org_id` (`routers/ws.py`). Tests: `test_role_gates_matrix`, `test_rbac_blocks_cargo_owner_from_admin_and_simulator`, `test_tenant_isolation_*`, `test_websocket_tenant_filter`. |
| Partial | Roles in JWT are stale for up to 15 min after demotion; `/admin/incidents` and `/admin/agents` require only authentication (F15); self-registration can create transporter/dispatcher orgs (F17) |
| Designed | Row-level filters "in repository layer" (`system-architecture.md` §7) — today they are in routers |
| Owner action | Approve the role matrix in `api-documentation.md` §3; decide KYC policy for self-registered organisations |

### C-02 Multi-factor authentication for privileged roles

| Aspect | Detail |
|---|---|
| Requirement | MFA for privileged roles |
| Implemented | TOTP (RFC 6238) via `pyotp`: `/auth/mfa/setup`, `/auth/mfa/enable`, `/auth/mfa/verify`; `valid_window=1` (`security.py verify_totp`); `mfa` claim in the access token; `mfa_required_roles = [platform_admin, weighbridge_operator, port_controller, auditor]` (`config.py`); `override-release` explicitly `mfa=True`. Test: `test_mfa_setup_and_privileged_override_requires_mfa`. |
| Partial | Enforcement is conditional on `user.mfa_enabled` (`deps.require_roles`), so an un-enrolled privileged user is never challenged (F3). `mfa_secret` stored in plaintext column (F5). No recovery codes. |
| Planned (2) | Force enrolment on first privileged login; deny MFA-gated endpoints when `mfa_enabled=False` for a required role; encrypt `mfa_secret`; recovery codes |
| Planned (3) | WebAuthn/FIDO2 for `platform_admin` |
| Owner action | Confirm which roles are "privileged" for the pilot (recommend adding `regulator_readonly` since it reads audit/ledger) |

### C-03 Password hashing

| Aspect | Detail |
|---|---|
| Requirement | Argon2 |
| Implemented | Argon2id, `time_cost=3`, `memory_cost=64 MiB`, `parallelism=2` (`security.py`), via `argon2-cffi`; min length 10 (`RegisterIn`, `UserIn`); lockout after 5 failures for 15 min (`routers/auth.py`); generic "Invalid credentials" (no user enumeration on login). Test: `test_login_rejects_bad_password_and_locks_after_5`. |
| Partial | No breached-password check; `/auth/register` returns 409 for existing e-mail (enumeration) |
| Planned (3) | Password policy aligned to NIST SP 800-63B (length over complexity, deny-list); uniform response on register |
| Owner action | None |

### C-04 Transport security (TLS)

| Aspect | Detail |
|---|---|
| Requirement | TLS everywhere |
| Implemented | HSTS header (`max-age=63072000; includeSubDomains`) emitted when `env in (staging, prod)` (`main.py`); MQTT client settings for CA/cert/key (`config.py mqtt_tls_*`) |
| Designed | ACM certificates on ALB/CloudFront; HTTPS-only listeners; MQTT 5 over TLS 1.2+ with mutual authentication at IoT Core; EMQX with TLS locally (`cloud-architecture.md` §3 #4, #7) |
| Planned (2) | Terraform: ALB redirect 80→443, TLS 1.2 minimum policy; `Secure`/`HttpOnly` cookies if refresh tokens move to cookies |
| Owner action | Provide domain and Route 53 hosted zone (`cloud-architecture.md` §5) |

### C-05 Encryption at rest

| Aspect | Detail |
|---|---|
| Requirement | Encryption at rest, including PII |
| Implemented | **Schema separation only**: `pii.user_pii`, `pii.driver_pii` (`models/auth.py`, `models/fleet.py`); `REVOKE ALL ON SCHEMA pii FROM PUBLIC` and `CREATE EXTENSION pgcrypto` in `alembic/versions/0001_initial.py`. Column names `phone_enc`, `national_id_enc`, `license_no_enc` **currently hold plaintext** — the write paths pass raw values. |
| Designed | RDS storage encryption with KMS; S3 SSE-KMS; EBS encryption on Fargate ephemeral storage; column-level encryption "for ID numbers/phones" (`system-architecture.md` §7) |
| Planned (2) | Terraform: KMS CMK, RDS `storage_encrypted`, S3 bucket encryption, Secrets Manager |
| Planned (3) | PII service: `pgp_sym_encrypt`/KMS data keys for `*_enc` columns; dedicated `kifaru_pii` DB role granted only to the PII service path; `mfa_secret` encrypted |
| Owner action | Approve KMS key policy and who holds key-admin rights |

### C-06 API authentication

| Aspect | Detail |
|---|---|
| Requirement | Authenticated APIs |
| Implemented | Bearer JWT (HS256, 15 min, `type=access`, `sub`, `roles`, `org`, `mfa`) (`security.py`, `deps.get_current_principal`); refresh tokens 14 days, random 48 bytes, stored as SHA-256 only, rotated on use, revocable (`/auth/logout`); user `is_active` re-checked per request; one deliberately public endpoint `GET /tickets/verify/{qr_token}` returning non-PII fields. Tests: `test_tampered_and_expired_tokens_rejected`, `test_refresh_rotation_and_me`, `test_public_verify_leaks_no_pii`. |
| Partial | Default dev secret not rejected in prod (F4); no `iss`/`aud`; reuse of a rotated refresh token is rejected but does not revoke the family (F16); WS token in query string (F8) |
| Planned (2) | Startup guard on secret; `iss`/`aud`; Redis denylist for emergency access-token revocation |
| Planned (3) | Asymmetric signing (EdDSA/RS256 + JWKS) once realtime gateway and workers are separate services |
| Owner action | Generate production `KIFARU_JWT_SECRET` (48+ bytes) into Secrets Manager; never reuse dev values |

### C-07 Device certificates

| Aspect | Detail |
|---|---|
| Requirement | Device certificates for station hardware |
| Implemented | None in code beyond MQTT TLS settings and the `Lane.device_id` (IoT thing name) field; `POST /weighing/ingest` accepts an operator/admin JWT and trusts payload `device_id` (F6); idempotency by `edge_event_id` |
| Designed | Per-device X.509 at AWS IoT Core, policy restricting publish to the device's own topic; EMQX fallback (`cloud-architecture.md` §1, §3 #7); per-station Ed25519 signing keys (`system-architecture.md` §7) |
| Planned (2) | Terraform IoT things/policies; ingest worker authenticates to API with a service token and sets `device_id` from the authenticated thing name, not the payload |
| Planned (6) | Gateway provisioning procedure (CSR on device, cert install, rotation every 12 months); outbox row signing with station key |
| Owner action | Approve AWS account creation (blocked, RTM CLD-03) |

### C-08 Audit logging

| Aspect | Detail |
|---|---|
| Requirement | Audit of privileged actions |
| Implemented | `core.audit_events` with actor, action, entity, before/after, IP, timestamp (`models/misc.py AuditEvent`, `deps.audit`); written on: register, login, mfa_enable, user create/update, vehicle/fleet/driver create, watchlist, station create/status, lane create, calibrate, appointment book, shipment create/stage/assign, backhaul create/decisions, static_verify, override, incident close, integration mode change. Read via `GET /admin/audit` (admin, auditor, regulator_readonly). Legal-path actions additionally appended to the signed ledger (`services/ledger.py`): `weighing.completed`, `clearance.decided`, `static.verified`, `clearance.overridden`, `shipment.*`, `cargo.status_changed`, `seal.status`, `backhaul.*`. |
| Partial | Failed logins increment a counter but produce no audit row (F10); audit rows are not hash-chained (F14); sensor health changes, warehouse readiness, appointment status changes and position updates are not audited |
| Planned (3) | `login_failed` audit action; nightly mirror of audit digest into ledger; structured log shipping to CloudWatch with 400-day retention for audit stream |
| Owner action | Define who reviews the audit log and how often (recommend weekly by `auditor`, see `incident-response-plan.md`) |

### C-09 Rate limiting

| Aspect | Detail |
|---|---|
| Requirement | Rate limiting |
| Implemented | Sliding 60-s window per client IP, `rate_limit_per_minute=300`, applied as a router dependency on `/auth/*` (`deps.rate_limit`, `routers/auth.py`). Test: `test_rate_limit_enforced`. Account lockout complements it. |
| Partial | In-process memory (not shared across ECS tasks, lost on restart); only `/auth/*`; `GET /tickets/verify/{token}` and `/weighing/simulate` unthrottled (F7, F11) |
| Designed | AWS WAF managed rules + rate-based rules at the ALB (`cloud-architecture.md` §3 #4) |
| Planned (2) | Redis-backed limiter (ElastiCache) on all routers with per-route budgets; WAF rules; disable `simulate` outside dev/test/staging |
| Owner action | Approve per-tenant quotas for the public API |

### C-10 Input validation

| Aspect | Detail |
|---|---|
| Requirement | Validation of all inputs |
| Implemented | Pydantic v2 models on every request body and typed query parameters; numeric bounds (`tare_kg 1000–30000`, `max_gvm_kg ≤ 56000`, `mass_kg 100–45000`, `count ≤ 50`, `limit ≤ 1000`); regex-constrained enumerations (roles, cargo types, statuses, `axle_config ^\d(\+\d)*$`); ISO 6346 container check digit (`routers/shipments.py iso6346_check_digit`, tested); plate normalisation and duplicate check (`services/identity.normalise_plate`); e-mail syntax (`schemas/common.py`); `edge_event_id` exactly 26 chars; ORM parameterisation (no string SQL with user input). |
| Partial | Measurement dict on `/weighing/ingest` is an untyped `dict` validated only by key access in `process_lane_pass` (a malformed payload yields a 500 via the generic handler rather than a 422) |
| Planned (2) | Typed `WimMeasurementIn` schema mirroring `WimMeasurement.to_dict()`; JSON schema published for gateway developers |
| Owner action | None |

### C-11 Session management

| Aspect | Detail |
|---|---|
| Requirement | Secure sessions |
| Implemented | Short access tokens (15 min); `core.refresh_sessions` with `token_hash`, `expires_at`, `revoked_at`, `ip`, `user_agent`, `mfa_verified`; rotation on refresh; logout revokes; `last_login_at`, `failed_logins`, `locked_until` on user (`models/auth.py`, `routers/auth.py`). |
| Partial | No concurrent-session limit; no "log out everywhere"; no idle timeout beyond access-token expiry; refresh token returned in JSON body (SPA storage) |
| Planned (3) | Session list and revoke-all endpoints; HttpOnly cookie option for browsers; idle timeout policy for operator consoles (recommend 30 min) |
| Owner action | Approve operator console idle-timeout policy |

### C-12 Backup encryption

| Aspect | Detail |
|---|---|
| Requirement | Encrypted backups |
| Implemented | None (no deployment; SQLite locally) |
| Designed | RDS automated backups (35 days, PITR), daily `pg_dump` to S3 with cross-region replication to `eu-west-1`, Redis snapshots; SSE-KMS; Object Lock for ticket objects (`cloud-architecture.md` §3 #2, #6, #10, #11) |
| Planned (2) | Terraform resources; `pg_dump` job container with KMS-encrypted output; restore test documented in `dr-runbook.md` (not yet written) |
| Planned (7) | Quarterly restore drill with timing against RTO 4 h / RPO 15 min |
| Owner action | Approve separate backup AWS account (recommended) |

### C-13 Access monitoring

| Aspect | Detail |
|---|---|
| Requirement | Monitoring of access and anomalies |
| Implemented | structlog JSON logs (`main.py`); `X-Response-Time-ms`; `GET /admin/system/health`; `Incident` model and `incident.opened` event; `SecurityAnomalyAgent` with four alert kinds, unit-tested |
| Partial | Agent not scheduled against live data; no `login_failed` feed; identity events lack coordinates (F10) |
| Designed | CloudWatch Logs/metrics/alarms → SNS; Container Insights; RDS Performance Insights; Sentry optional (`cloud-architecture.md` §3 #12–14) |
| Planned (3) | Security worker (5-min cadence) producing `Incident(category='security')`; alarms: ledger verify failure, 401/403/429 spikes, override count, `method='conflict'` rate, heartbeat loss |
| Owner action | Name the on-call rota (see `maintenance.md` §9) |

### C-14 Incident response

| Aspect | Detail |
|---|---|
| Requirement | Incident response capability |
| Implemented | Incident records and API (`/admin/incidents`), station status → incident auto-creation (`routers/stations.py set_station_status`), `OperationalIncidentAgent` recommendations |
| Documented | `incident-response-plan.md` (this phase): roles, severities, playbooks, DPA 72-hour notification, ledger-based evidence preservation |
| Planned (7) | Table-top exercise before pilot; external security review |
| Owner action | Appoint Incident Commander and Data Protection Officer (or designate) |

### C-15 Data retention

| Aspect | Detail |
|---|---|
| Requirement | Defined retention |
| Implemented | None enforced in code; `created_at`/`occurred_at` on all rows allow time-based purging; `ts.sensor_readings` designed for monthly partitions (`models/stations.py` docstring) |
| Documented | Proposed schedule in `dpia.md` §8 — **note**: `docs/02-architecture/database-erd.md` is referenced by RTM DB-01 and by the Alembic migration but does not yet exist in the repository; the retention schedule must be ratified there |
| Planned (3) | Purge jobs (PII minimisation after driver/user deactivation; evidence images 30 days; raw windows 90 days); `pg_partman` partition drop for `ts` |
| Owner action | Confirm statutory retention for weighing records with KeNHA (recommended working assumption 7 years for `static_certified` tickets and ledger) |

### C-16 Privacy by design

| Aspect | Detail |
|---|---|
| Requirement | Privacy by design and by default; Kenya DPA 2019 |
| Implemented | PII isolated in `pii` schema; public verify endpoint returns a fixed non-PII field set (tested); drivers/users referenced by ULID elsewhere; SMS content minimal (`SMS_TEMPLATES` ≤ 160 chars, opt-out text); `source` labelling prevents simulated data being presented as real |
| Partial | Plate (indirect identifier) in public verify response and in station-wide WS payloads; plaintext PII columns |
| Documented | `dpia.md` (controller/processor roles, lawful bases, cross-border transfer to af-south-1, data-subject rights) |
| Planned (3) | Plate masking on public verify; PII encryption; data-subject request endpoints (export/erase) |
| Owner action | ODPC registration as controller and processor before production (`cloud-architecture.md` §1); appoint DPO/designate; approve privacy notice |

## 3. Additional controls present in code (not in the §11 list)

| Control | Where | Note |
|---|---|---|
| Security response headers | `main.py` middleware: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, HSTS (staging/prod) | CSP missing (F13); tested by `test_security_headers_present` |
| Generic error handler | `main.py` | No stack traces to clients |
| Deterministic legal-path engine | `services/clearance_engine.py` | Pure function; evidence hash; AI advisory only (AGT-02) |
| Signed tickets and ledger | `services/tickets.py`, `services/ledger.py`, `security.py` (Ed25519 via PyNaCl) | Finding F1/F2 on key handling |
| Idempotent edge ingest | `weighing_service.process_lane_pass` (`edge_event_id`) | Tested |
| Secrets from environment only | `config.py`, `.env.example`; integration tokens read from `os.environ` | Default dev secret guard needed (F4) |
| Secure random | `secrets.token_urlsafe` for refresh and QR tokens; `random.SystemRandom` for audit seed | — |
| Signing seed mandatory outside dev | `security.get_signing_key` raises if `KIFARU_SIGNING_SEED_B64` unset in staging/prod | Good; extend same rule to JWT secret |

## 4. Control gaps by roadmap phase (owner view)

| Phase | Controls to close | Blocking dependency |
|---|---|---|
| 2 (now) | C-02 forced enrolment, C-06 secret guard, C-09 Redis/WAF + simulate guard, C-10 typed measurement schema, F1/F2 key registry + append lock, F6 device binding, F9 ticket supersede, C-05/C-12 Terraform (validate only) | AWS account for anything beyond `terraform validate` |
| 3 | C-05 column encryption + PII role, C-08 failed-login audit + ledger mirror, C-11 session controls, C-13 security worker, C-15 purge jobs, C-16 masking/DSR endpoints, F8 WS auth, F17 org vetting | — |
| 5 | F12 integration allowlist; real-mode adapters | Government authorisations |
| 6 | C-07 device provisioning, signed firmware/outbox, static-scale integration, gateway hardening | Site access |
| 7 | External security review, restore drill, table-top exercise | Pilot approval |

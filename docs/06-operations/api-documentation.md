# KIFARU PORTOS — API Documentation

| Field | Value |
|---|---|
| Document | `docs/06-operations/api-documentation.md` |
| API | KIFARU PORTOS API v0.1.0 — base path `/api/v1` (except `/health`, `/ready`, `/ws/events`) |
| Generated from | `docs/06-operations/openapi.json`, exported on 2026-11-04 with `app.openapi()` from `apps/api/kifaru/main.py`; roles and side effects read from `apps/api/kifaru/routers/*.py` |
| Interactive docs | `/docs` (Swagger UI), `/redoc`, `/openapi.json` when the API is running |
| Conventions | `*` = required field; roles list the `require_roles(...)` dependency — `platform_admin` is always permitted (`Principal.has_role`); side effects: **A** audit row, **L** ledger row, **E** WebSocket event, **I** incident row |
| Honesty note | All data produced by `/weighing/simulate` is tagged `source=simulated`; adapters return `MOCK` labels until authorised; environment figures are modelled |

The API exposes **80 paths / 90 operations** across 13 tags plus one WebSocket endpoint.

## 1. Authentication and conventions

1. Obtain tokens: `POST /api/v1/auth/login` with `{email, password, totp_code?}` → `{access_token, refresh_token, expires_in, mfa_required, roles, org_id, user_id, full_name}`.
2. Send `Authorization: Bearer <access_token>` on every call (except public routes). Tokens expire after 15 minutes; call `POST /api/v1/auth/refresh` with the refresh token to obtain a new pair (the used refresh token is revoked — rotation).
3. Privileged roles (`platform_admin`, `weighbridge_operator`, `port_controller`, `auditor`) that have enrolled in MFA must present a token obtained via `/auth/login` with `totp_code` or via `/auth/mfa/verify`; otherwise MFA-gated endpoints return 403 "MFA verification required for this role".
4. Errors: 401 unauthenticated/expired; 403 role or MFA; 404 for resources outside the caller's tenant (deliberately indistinguishable from non-existence); 409 state conflicts; 422 validation (Pydantic); 423 locked account; 429 rate limit; 500 generic.
5. IDs are 26-character ULIDs. Timestamps are ISO-8601 UTC. Masses are kilograms, speeds m/s, distances km (routing) or m (lane geometry).
6. Every record that can be simulated carries `source` ∈ {`live`, `simulated`, `replay`, `static`, `forecast`}.
7. Response headers: `X-Response-Time-ms`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and HSTS in staging/prod.

## 2. Roles

| Role | Typical user | Platform-wide (sees all tenants) | MFA required when enrolled |
|---|---|---|---|
| `platform_admin` | Platform operator | yes | yes |
| `port_controller` | KPA / port control officer | yes | yes |
| `weighbridge_operator` | KeNHA weighbridge staff | yes | yes |
| `auditor` | Compliance auditor | yes (read) | yes |
| `regulator_readonly` | KeNHA/KRA observer | yes (audit/ledger read) | no (recommended: yes) |
| `transporter_admin` | Transport company admin | no — own org | no |
| `dispatcher` | Transport dispatcher | no — own org | no |
| `driver` | Truck driver | no — own org | no |
| `cargo_owner` | Importer / small trader | no — own org | no |
| `warehouse_manager` | Destination warehouse | no — own org (+ shipments to own warehouse) | no |

Source: `apps/api/kifaru/models/auth.py ROLE_NAMES`, `apps/api/kifaru/deps.py org_scope`, `apps/api/kifaru/config.py mfa_required_roles`.

## 3. Endpoints by tag

### 3.1 `ops`

Liveness/readiness for load balancers and ECS health checks (`apps/api/kifaru/main.py`).

| Method | Path | Roles | Request | Response | Notes | Effects |
|---|---|---|---|---|---|---|
| `GET` | `/health` | public (no authentication) | — | 200 JSON | Liveness | — |
| `GET` | `/ready` | public (no authentication) | — | 200 JSON | Readiness (SELECT 1) | — |

### 3.2 `auth`

Registration, login, token refresh/rotation, logout, TOTP MFA. All routes in this group are rate-limited per client IP (`deps.rate_limit`, default 300/min). Access tokens are HS256 JWTs valid 15 min with claims `sub, roles, org, mfa, type=access`; refresh tokens are opaque 48-byte strings valid 14 days (`apps/api/kifaru/routers/auth.py`, `security.py`).

| Method | Path | Roles | Request | Response | Notes | Effects |
|---|---|---|---|---|---|---|
| `POST` | `/api/v1/auth/register` | public (no authentication); rate-limited | `RegisterIn` (email*, password*, full_name*, phone, org_name, org_type, role) | 201 `TokenOut` | Creates a new organisation (transporter | cargo_owner | warehouse) and its first user; role whitelist transporter_admin, cargo_owner, warehouse_manager, driver, dispatcher | A |
| `POST` | `/api/v1/auth/login` | public (no authentication); rate-limited | `LoginIn` (email*, password*, totp_code) | 200 `TokenOut` | 5 failures lock the account 15 min (423); `totp_code` optional — without it `mfa_required=true` for enrolled users | A |
| `POST` | `/api/v1/auth/refresh` | public (no authentication); rate-limited | `RefreshIn` (refresh_token*) | 200 `TokenOut` | Rotates the refresh token (old one revoked); carries forward `mfa_verified` | — |
| `POST` | `/api/v1/auth/logout` | public (no authentication); rate-limited | `RefreshIn` (refresh_token*) | 204 no content | Revokes the given refresh token | — |
| `GET` | `/api/v1/auth/me` | any authenticated user | — | 200 `MeOut` |  | — |
| `POST` | `/api/v1/auth/mfa/setup` | any authenticated user | — | 200 `MfaSetupOut` | Generates a TOTP secret (not yet enabled) | — |
| `POST` | `/api/v1/auth/mfa/enable` | any authenticated user | `MfaCodeIn` (code*) | 204 no content | Enables MFA after a valid code | A |
| `POST` | `/api/v1/auth/mfa/verify` | any authenticated user | `MfaCodeIn` (code*) | 200 `TokenOut` | Issues a new token pair with `mfa=true` | — |

### 3.3 `fleet`

Organisations, fleets, vehicles (with axle configuration and RFID tags), trailers, drivers, telematics positions and the enforcement watch-list (`routers/fleet.py`). Non-platform roles are scoped to their own organisation by `deps.org_scope`.

| Method | Path | Roles | Request | Response | Notes | Effects |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/fleet/orgs` | any authenticated user | query: type | 200 `list[OrgOut]` | Tenant-scoped: non-platform roles see only their own organisation | — |
| `GET` | `/api/v1/fleet/fleets` | any authenticated user | — | 200 `list[FleetOut]` | Tenant-scoped | — |
| `POST` | `/api/v1/fleet/fleets` | transporter_admin, dispatcher, platform_admin | `FleetIn` (name*) | 201 `FleetOut` | Fleet created in caller's org | A |
| `GET` | `/api/v1/fleet/vehicles` | any authenticated user | query: org_id | 200 `list[VehicleOut]` | Tenant-scoped; platform roles may filter by `org_id` | — |
| `POST` | `/api/v1/fleet/vehicles` | transporter_admin, dispatcher, platform_admin | `VehicleIn` (plate*, fleet_id, make, model, axle_config, tare_kg*, max_gvm_kg, payload_capacity_kg, body_type, rfid_epc) | 201 `VehicleOut` | Plate uniqueness checked on normalised form; optional RFID EPC registered | A |
| `GET` | `/api/v1/fleet/vehicles/{vehicle_id}` | any authenticated user | — | 200 `VehicleOut` | 404 outside caller's org | — |
| `POST` | `/api/v1/fleet/vehicles/{vehicle_id}/position` | transporter_admin, dispatcher, driver, platform_admin | `PositionIn` (lat*, lon*) | 200 `VehicleOut` | Telematics position; tenant-scoped | — |
| `POST` | `/api/v1/fleet/vehicles/{vehicle_id}/watchlist` | platform_admin, port_controller, auditor | `WatchlistIn` (reason) | 200 `VehicleOut` | Null reason clears the watch-list; watch-listed vehicles are RED at the lane | A |
| `GET` | `/api/v1/fleet/trailers` | any authenticated user | — | 200 `list[TrailerOut]` | Tenant-scoped | — |
| `POST` | `/api/v1/fleet/trailers` | transporter_admin, dispatcher, platform_admin | `TrailerIn` (plate*, axle_config, tare_kg*) | 201 `TrailerOut` |  | — |
| `GET` | `/api/v1/fleet/drivers` | any authenticated user | — | 200 `list[DriverOut]` | Tenant-scoped; returns name only (PII schema) | — |
| `POST` | `/api/v1/fleet/drivers` | transporter_admin, dispatcher, platform_admin | `DriverIn` (full_name*, phone, license_class, fleet_id) | 201 `DriverOut` | Name/phone stored in `pii.driver_pii` | A |

### 3.4 `stations`

Weighing stations, lanes, sensors, sensor health and calibration records (`routers/stations.py`). Calibration validity drives the engine's `calibration_expired` flag.

| Method | Path | Roles | Request | Response | Notes | Effects |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/stations` | any authenticated user | — | 200 `list[StationOut]` | Includes lanes, sensors, latest queue, decisions last hour | — |
| `POST` | `/api/v1/stations` | platform_admin | `StationIn` (code*, name*, lat*, lon*, capacity_per_hour, static_capacity_per_hour, alt_allowed) | 201 `StationOut` |  | A |
| `GET` | `/api/v1/stations/{station_id}` | any authenticated user | — | 200 `StationOut` |  | — |
| `POST` | `/api/v1/stations/{station_id}/status` | platform_admin, weighbridge_operator, port_controller | `StationStatusIn` (status*, reason) | 200 `StationOut` | degraded/offline opens an Incident and emits `station.failure` | A E I |
| `POST` | `/api/v1/stations/{station_id}/lanes` | platform_admin | `LaneIn` (lane_no*, type, direction, device_id) | 201 `LaneOut` | Non-static lanes get the 13 default sensors | A |
| `POST` | `/api/v1/stations/sensors/{sensor_id}/health` | platform_admin, weighbridge_operator, port_controller | `SensorHealthIn` (status*, reason) | 200 `SensorOut` | Updates lane status; does not affect decisions (per-pass health comes from the gateway) | E |
| `POST` | `/api/v1/stations/sensors/{sensor_id}/calibrations` | platform_admin, weighbridge_operator | `CalibrationIn` (method*, reference_mass_kg, gain, offset, temp_coeff_per_c, reference_temp_c, uncertainty_pct, valid_days, notes) | 201 `CalibrationOut` | Recomputes `lane.calibration_valid_to` = min over load sensors | A |
| `GET` | `/api/v1/stations/sensors/{sensor_id}/calibrations` | any authenticated user | — | 200 `list[CalibrationOut]` |  | — |
| `GET` | `/api/v1/stations/meta/sensor-kinds` | public (no authentication) | — | 200 JSON | Static list | — |

### 3.5 `weighing`

Lane passes (live ingest and simulator), decisions, static verification, MFA-gated override, and the published legal limits (`routers/weighing.py`, `services/weighing_service.py`, `services/clearance_engine.py`, `services/limits.py`).

| Method | Path | Roles | Request | Response | Notes | Effects |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/weighing/events` | any authenticated user | query: station_id, vehicle_id, decision, limit | 200 `list[WeighingOut]` | Tenant-scoped to own vehicles for non-platform roles; filters station_id, vehicle_id, decision, limit ≤ 500 | — |
| `GET` | `/api/v1/weighing/events/{event_id}` | any authenticated user | — | 200 `WeighingOut` | 404 outside caller's org | — |
| `GET` | `/api/v1/weighing/stats` | any authenticated user | query: station_id | 200 `StatsOut` | Counts by decision and by `source`; mean engine latency | — |
| `POST` | `/api/v1/weighing/ingest` | platform_admin, weighbridge_operator (service token in cloud design) | `EdgeIngestIn` (device_id*, edge_event_id*, occurred_at*, measurement*, anpr_plate, anpr_confidence, rfid_epc, rfid_confidence, raw_ref, ambient_temp_c) | 201 `WeighingOut` | Live gateway measurement; idempotent on `edge_event_id`; `source=live` | L E |
| `POST` | `/api/v1/weighing/simulate` | platform_admin, weighbridge_operator, port_controller | `SimulateIn` (lane_id*, count, overload_prob, sensor_fault_prob, anpr_misread_prob, rfid_missing_prob, clone_prob, unregistered_prob, pavement_temp_c, vehicle_id, force_gvm_kg, seed) | 201 `list[WeighingOut]` | Synthetic passes through the full pipeline; `source=simulated`; count ≤ 50 | L E |
| `POST` | `/api/v1/weighing/events/{event_id}/static-verify` | platform_admin, weighbridge_operator | `StaticVerifyIn` (static_gvm_kg*, axle_loads_kg, notes) | 200 `WeighingOut` | Records static-scale GVM; issues `static_certified` ticket (replaces prescreen ticket); ledger records WIM error % | A L E |
| `POST` | `/api/v1/weighing/events/{event_id}/override-release` | platform_admin, weighbridge_operator — **MFA required** | `OverrideIn` (reason*) | 200 `WeighingOut` | Only after static verification; original decision kept; reason ≥ 10 chars | A L |
| `GET` | `/api/v1/weighing/limits` | public (no authentication) | — | 200 JSON | Current `LimitSet` and engine configuration (identity threshold, audit rate) | — |

### 3.6 `tickets`

Signed digital weighing tickets (`prescreen` | `static_certified`) with QR; public verification endpoint (`routers/tickets.py`, `services/tickets.py`).

| Method | Path | Roles | Request | Response | Notes | Effects |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/tickets/{ticket_id}` | any authenticated user | — | 200 `TicketOut` | Includes `signature_valid` | — |
| `GET` | `/api/v1/tickets/{ticket_id}/qr.svg` | any authenticated user | — | 200 JSON | SVG QR encoding `{public_base_url}/verify/{qr_token}` | — |
| `GET` | `/api/v1/tickets/verify/{qr_token}` *(public tag)* | public (no authentication) | — | 200 `VerifyOut` | Returns only non-PII fields; `valid=false` for unknown tokens | — |

### 3.7 `shipments`

Digital Cargo Passport: shipments, containers (ISO 6346), declarations, electronic seals, processing stages, warehouses (`routers/shipments.py`).

| Method | Path | Roles | Request | Response | Notes | Effects |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/shipments` | any authenticated user | query: stage, warehouse_id | 200 `list[PassportOut]` | Visible if caller is owner org, transporter org, or warehouse_manager of the destination warehouse | — |
| `POST` | `/api/v1/shipments` | cargo_owner, transporter_admin, dispatcher, platform_admin | `ShipmentIn` (description*, cargo_type, origin*, destination*, origin_lat, origin_lon, dest_lat, dest_lon, declared_mass_kg*, vgm_kg, transporter_org_id, vehicle_id, warehouse_id, containers, declaration_reference, seal_id) | 201 `PassportOut` | Reference `KP-XXXXXXXX`; ISO 6346 check digit on containers; optional declaration and seal | A L E |
| `GET` | `/api/v1/shipments/{shipment_id}` | any authenticated user | — | 200 `PassportOut` | Accepts ULID or reference | — |
| `POST` | `/api/v1/shipments/{shipment_id}/stage` | platform_admin, port_controller, weighbridge_operator, warehouse_manager, transporter_admin, dispatcher | `StageIn` (stage*, status, notes) | 200 `PassportOut` | Stage machine; `delivered` creates a DeliveryRecord | A L E |
| `POST` | `/api/v1/shipments/{shipment_id}/assign` | cargo_owner, transporter_admin, dispatcher, platform_admin | `AssignIn` (vehicle_id*, transporter_org_id, driver_id) | 200 `PassportOut` |  | A L |
| `POST` | `/api/v1/shipments/{shipment_id}/seal` | platform_admin, port_controller, weighbridge_operator, warehouse_manager, transporter_admin, dispatcher | `SealIn` (seal_id*, status*) | 200 `PassportOut` | Seal `breached`/`removed` makes the next weighing RED | L |
| `GET` | `/api/v1/shipments/warehouses/all` | any authenticated user | — | 200 `list[WarehouseOut]` |  | — |
| `POST` | `/api/v1/shipments/warehouses` | warehouse_manager, platform_admin | `WarehouseIn` (name*, lat*, lon*, dock_count) | 201 `WarehouseOut` |  | — |
| `POST` | `/api/v1/shipments/warehouses/{warehouse_id}/readiness` | warehouse_manager, platform_admin | `ReadinessIn` (readiness_status*) | 200 `WarehouseOut` |  | — |

### 3.8 `queue`

Observed and forecast queue state, 15-minute slot booking (`routers/queue.py`, `services/queue_forecast.py`, `TrafficForecastAgent`).

| Method | Path | Roles | Request | Response | Notes | Effects |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/queue/{station_id}/history` | any authenticated user | query: hours | 200 `list[QueueOut]` | Observed records only | — |
| `POST` | `/api/v1/queue/{station_id}/observe` | platform_admin, weighbridge_operator, port_controller | `ObservationIn` (queue_len*, avg_wait_s*, arrivals_per_hour*, source) | 201 `QueueOut` | `source` live | simulated | replay | E |
| `GET` | `/api/v1/queue/{station_id}/forecast` | any authenticated user | — | 200 `list[QueueOut]` | Runs TrafficForecastAgent; persists 4 forecast rows; `model_version` states the model used | — |
| `GET` | `/api/v1/queue/{station_id}/slots` | any authenticated user | query: hours | 200 `list[SlotOut]` | 15-min windows; capacity = capacity_per_hour/4 | — |
| `POST` | `/api/v1/queue/{station_id}/appointments` | transporter_admin, dispatcher, driver, platform_admin, port_controller | `BookIn` (vehicle_id*, slot_start*, shipment_id, priority) | 201 `AppointmentOut` | 409 when slot full or vehicle already booked; 400 if not aligned to 15 min; tenant-scoped vehicle | A E |
| `GET` | `/api/v1/queue/appointments/mine` | any authenticated user | query: station_id | 200 `list[AppointmentOut]` | Tenant-scoped | — |
| `POST` | `/api/v1/queue/appointments/{appointment_id}/status` | any authenticated user | `ApptStatusIn` (status*) | 200 `AppointmentOut` | Tenant-scoped; arrived | completed | missed | cancelled | — |

### 3.9 `backhaul`

Return-cargo marketplace with two-party acceptance (`routers/backhaul.py`, `BackhaulMatchingAgent`).

| Method | Path | Roles | Request | Response | Notes | Effects |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/backhaul/offers` | any authenticated user | query: status | 200 `list[OfferOut]` | Cargo owners see own offers; matches filtered to caller's org | — |
| `POST` | `/api/v1/backhaul/offers` | cargo_owner, platform_admin | `OfferIn` (title*, cargo_type, mass_kg*, volume_m3, length_m, requires_body_types, origin*, origin_lat*, origin_lon*, destination*, dest_lat*, dest_lon*, ready_from*, deadline*, offered_price_kes*, notes) | 201 `OfferOut` |  | A L E |
| `POST` | `/api/v1/backhaul/offers/{offer_id}/match` | cargo_owner, transporter_admin, dispatcher, platform_admin | — | 200 `OfferOut` | Runs BackhaulMatchingAgent; stores up to 10 PROPOSED matches; nothing assigned | — |
| `POST` | `/api/v1/backhaul/matches/{match_id}/transporter-decision` | transporter_admin, dispatcher, platform_admin | `DecisionIn` (accept*, reason) | 200 `MatchOut` | Tenant-scoped to the truck's org; assignment requires both parties (BKH-04) | A (L when assigned) |
| `POST` | `/api/v1/backhaul/matches/{match_id}/owner-decision` | cargo_owner, platform_admin | `DecisionIn` (accept*, reason) | 200 `MatchOut` | Tenant-scoped to offer owner | A (L when assigned) |
| `POST` | `/api/v1/backhaul/matches/{match_id}/deliver` | transporter_admin, dispatcher, platform_admin | `DeliverIn` (receiver_name, notes) | 200 `MatchOut` | Only `assigned` matches; creates DeliveryRecord | L E |
| `GET` | `/api/v1/backhaul/opportunities` | any authenticated user | — | 200 `list[OfferOut]` | Open/matched offers (transporter view) | — |

### 3.10 `notifications`

Inbox, mark-read, operator send (ws/sms/email), SMS templates (`routers/notifications.py`).

| Method | Path | Roles | Request | Response | Notes | Effects |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/notifications` | any authenticated user | query: unread_only | 200 `list[NotificationOut]` | Own and org-wide notifications | — |
| `POST` | `/api/v1/notifications/{notification_id}/read` | any authenticated user | — | 204 no content |  | — |
| `POST` | `/api/v1/notifications/send` | platform_admin, port_controller, dispatcher, transporter_admin | `SendIn` (user_id, org_id, template*, title*, body*, channels, payload) | 201 `list[NotificationOut]` | Channels ws | sms | email; SMS mock unless `sms` integration is `real` | E |
| `GET` | `/api/v1/notifications/templates/sms` | public (no authentication) | — | 200 JSON | 160-char templates | — |

### 3.11 `environment`

Modelled fuel/CO2/cost estimates — see `emissions-model.md` (`routers/environment.py`, `EnvironmentalAgent`).

| Method | Path | Roles | Request | Response | Notes | Effects |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/environment/report` | any authenticated user | query: hours, station_id | 200 `EnvReportOut` | Modelled; see emissions-model.md | — |
| `POST` | `/api/v1/environment/what-if` | any authenticated user | `WhatIfIn` (stops_avoided*, stops_made*, avg_queue_wait_s*, empty_km, empty_km_avoided, detour_km, factors) | 200 JSON | Modelled; factors overridable | — |
| `GET` | `/api/v1/environment/factors` | public (no authentication) | — | 200 JSON | Factors and formulas | — |

### 3.12 `integrations`

Adapter registry for KeNHA, KPA, KRA, NTSA, customs/seals, fleet, WMS, payment, SMS, email, maps, telematics. All default to `mock`; `real` requires a configured `base_url` and an environment token (`routers/integrations.py`).

| Method | Path | Roles | Request | Response | Notes | Effects |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/integrations` | any authenticated user | — | 200 `list[IntegrationOut]` | All adapters default `mode=mock` | — |
| `POST` | `/api/v1/integrations/{name}/mode` | platform_admin | `ModeIn` (mode*, base_url) | 200 `IntegrationOut` | `real` requires `base_url`; credentials from environment | A |
| `POST` | `/api/v1/integrations/{name}/health` | platform_admin, port_controller | — | 200 `IntegrationOut` |  | — |
| `GET` | `/api/v1/integrations/ntsa/vehicle/{plate}` | platform_admin, port_controller, weighbridge_operator, transporter_admin | — | 200 `LookupOut` | MOCK label unless real | — |
| `GET` | `/api/v1/integrations/kra/declaration/{reference}` | platform_admin, port_controller, cargo_owner, transporter_admin | — | 200 `LookupOut` | MOCK label unless real | — |
| `GET` | `/api/v1/integrations/maps/route` | any authenticated user | query: from_lat*, from_lon*, to_lat*, to_lon* | 200 JSON | Mock = great-circle × 1.25 | — |

### 3.13 `admin`

Users and roles, audit log, ledger tail and verification, incidents, system health, AI agent catalogue (`routers/admin.py`).

| Method | Path | Roles | Request | Response | Notes | Effects |
|---|---|---|---|---|---|---|
| `GET` | `/api/v1/admin/users` | platform_admin | — | 200 `list[UserOut]` |  | — |
| `POST` | `/api/v1/admin/users` | platform_admin | `UserIn` (email*, password*, full_name*, org_id, roles*, phone) | 201 `UserOut` | Any of the 10 roles; password ≥ 10 chars | A |
| `PATCH` | `/api/v1/admin/users/{user_id}` | platform_admin | `UserPatch` (roles, is_active, org_id) | 200 `UserOut` | roles / is_active / org_id; deactivation takes effect on the next request | A |
| `GET` | `/api/v1/admin/roles` | platform_admin | — | 200 JSON |  | — |
| `GET` | `/api/v1/admin/audit` | platform_admin, auditor, regulator_readonly | query: entity, limit | 200 `list[AuditOut]` | limit ≤ 1000; filter by entity | — |
| `GET` | `/api/v1/admin/ledger` | platform_admin, auditor, regulator_readonly | query: limit, type | 200 `list[LedgerOut]` | Newest first; filter by type | — |
| `GET` | `/api/v1/admin/ledger/verify` | platform_admin, auditor, regulator_readonly | — | 200 JSON | Walks the whole chain; returns head hash and public key | — |
| `GET` | `/api/v1/admin/incidents` | any authenticated user | query: status | 200 `list[IncidentOut]` | Default `status=open` | — |
| `POST` | `/api/v1/admin/incidents` | platform_admin, weighbridge_operator, port_controller | `IncidentIn` (station_id, severity, category*, title*, details) | 201 `IncidentOut` |  | E I |
| `POST` | `/api/v1/admin/incidents/{incident_id}/close` | platform_admin, weighbridge_operator, port_controller | — | 200 `IncidentOut` | Closing the last station_failure incident restores station to operational | A |
| `GET` | `/api/v1/admin/system/health` | platform_admin, port_controller, auditor | — | 200 JSON |  | — |
| `GET` | `/api/v1/admin/agents` | any authenticated user | — | 200 JSON | Orchestrator catalogue (10 agents, 5 pipelines, advisory policy) | — |

## 4. Schemas (request/response models)

Fields marked `*` are required. Types are abbreviated; see `openapi.json` for exact constraints (patterns, bounds).

**`AppointmentOut`** — `id*`: string; `station_id*`: string; `station_code*`: string; `vehicle_id*`: string; `plate*`: string; `shipment_id*`: string | null; `slot_start*`: string; `slot_end*`: string; `status*`: string; `priority*`: integer; `est_wait_s*`: integer | null; `assigned_by*`: string

**`ApptStatusIn`** — `status*`: string (pattern `^(arrived|completed|missed|cancelled)$`)

**`AssignIn`** — `vehicle_id*`: string; `transporter_org_id`: string | null; `driver_id`: string | null

**`AuditOut`** — `id*`: string; `actor_user_id*`: string | null; `action*`: string; `entity*`: string; `entity_id*`: string | null; `before*`: object | null; `after*`: object | null; `at*`: string

**`AxleOut`** — `axle_index*`: integer; `load_kg*`: integer; `uncertainty_kg*`: integer; `spacing_to_next_m*`: number | null; `group_no*`: integer

**`BookIn`** — `vehicle_id*`: string; `slot_start*`: string; `shipment_id`: string | null; `priority`: integer (minimum=1.0; maximum=9.0; default=5)

**`CalibrationIn`** — `method*`: string (pattern `^(reference_vehicle|static_scale_comparison|shunt|bench)$`); `reference_mass_kg`: integer | null; `gain`: number (default=1.0); `offset`: number (default=0.0); `temp_coeff_per_c`: number (default=0.0); `reference_temp_c`: number (default=25.0); `uncertainty_pct`: number (minimum=0.1; maximum=50.0; default=5.0); `valid_days`: integer (minimum=1.0; maximum=730.0; default=180); `notes`: string | null

**`CalibrationOut`** — `method*`: string (pattern `^(reference_vehicle|static_scale_comparison|shunt|bench)$`); `reference_mass_kg`: integer | null; `gain`: number (default=1.0); `offset`: number (default=0.0); `temp_coeff_per_c`: number (default=0.0); `reference_temp_c`: number (default=25.0); `uncertainty_pct`: number (minimum=0.1; maximum=50.0; default=5.0); `valid_days`: integer (minimum=1.0; maximum=730.0; default=180); `notes`: string | null; `id*`: string; `sensor_id*`: string; `valid_from*`: string; `valid_to*`: string

**`ContainerIn`** — `number*`: string (minLength=11; maxLength=11); `size_ft`: integer (minimum=10.0; maximum=53.0; default=40); `type`: string (default="GP")

**`DecisionIn`** — `accept*`: boolean; `reason`: string | null

**`DecisionOut`** — `id*`: string; `decision*`: string; `rules_fired*`: list; `margins*`: object; `limits_version*`: string; `engine_version*`: string; `audit_selected*`: boolean; `evidence_hash*`: string; `decided_at*`: string; `latency_ms*`: integer; `explanation*`: string; `static_verified_gvm_kg*`: integer | null; `override_reason*`: string | null; `ticket_id*`: string | null; `ticket_type*`: string | null; `qr_token*`: string | null

**`DeliverIn`** — `receiver_name`: string | null; `notes`: string | null

**`DriverIn`** — `full_name*`: string (minLength=2; maxLength=200); `phone`: string | null; `license_class`: string | null; `fleet_id`: string | null

**`DriverOut`** — `id*`: string; `org_id*`: string; `full_name*`: string; `license_class*`: string | null; `status*`: string

**`EdgeIngestIn`** — `device_id*`: string; `edge_event_id*`: string (minLength=26; maxLength=26); `occurred_at*`: string; `measurement*`: object; `anpr_plate`: string | null; `anpr_confidence`: number | null; `rfid_epc`: string | null; `rfid_confidence`: number | null; `raw_ref`: string | null; `ambient_temp_c`: number | null

**`EnvReportOut`** — `period_hours*`: integer; `station_id*`: string | null; `inputs*`: object; `baseline*`: object; `platform*`: object; `savings*`: object; `factors*`: object; `label*`: string; `assumptions*`: list[string]; `agent_confidence*`: number

**`FleetIn`** — `name*`: string (minLength=2; maxLength=120)

**`FleetOut`** — `name*`: string (minLength=2; maxLength=120); `id*`: string; `org_id*`: string; `vehicle_count*`: integer

**`IdentityOut`** — `anpr_plate*`: string | null; `anpr_confidence*`: number | null; `rfid_epc*`: string | null; `rfid_confidence*`: number | null; `confidence*`: number; `method*`: string; `explanation*`: string | null

**`IncidentIn`** — `station_id`: string | null; `severity`: string (pattern `^(low|medium|high|critical)$`; default="medium"); `category*`: string (pattern `^(station_failure|sensor_fault|security|traffic|cargo_anomaly|other)$`); `title*`: string; `details`: object

**`IncidentOut`** — `id*`: string; `station_id*`: string | null; `severity*`: string; `category*`: string; `title*`: string; `details*`: object; `status*`: string; `opened_at*`: string; `closed_at*`: string | null; `raised_by*`: string

**`IntegrationOut`** — `id*`: string; `name*`: string; `display_name*`: string; `mode*`: string; `contract*`: string; `base_url*`: string | null; `health_status*`: string; `last_ok_at*`: string | null; `last_error*`: string | null

**`LaneIn`** — `lane_no*`: integer (minimum=1.0; maximum=20.0); `type`: string (pattern `^(wim_highspeed|wim_lowspeed|static)$`; default="wim_highspeed"); `direction`: string (default="inbound"); `device_id`: string | null

**`LaneOut`** — `id*`: string; `lane_no*`: integer; `type*`: string; `direction*`: string; `status*`: string; `device_id*`: string | null; `calibration_valid_to*`: string | null; `sensors*`: list[SensorOut]

**`LedgerOut`** — `event_id*`: string; `seq*`: integer; `type*`: string; `payload*`: object; `station_id*`: string | null; `producer*`: string; `prev_hash*`: string; `hash*`: string; `signature*`: string; `occurred_at*`: string

**`LoginIn`** — `email*`: string (pattern `^[^@\s]+@[^@\s]+\.[^@\s]+$`; maxLength=254); `password*`: string; `totp_code`: string | null

**`LookupOut`** — `integration*`: string; `mode*`: string; `data*`: object; `label*`: string

**`MatchOut`** — `id*`: string; `offer_id*`: string; `vehicle_id*`: string; `plate*`: string; `transporter_org_id*`: string; `transporter_name*`: string | null; `score*`: number; `extra_km*`: number; `fuel_litres*`: number; `fuel_cost_kes*`: number; `revenue_kes*`: number; `co2_avoided_kg*`: number; `explanation*`: object; `status*`: string; `transporter_decided_at*`: string | null; `owner_decided_at*`: string | null; `assigned_at*`: string | null

**`MeOut`** — `user_id*`: string; `email*`: string; `full_name*`: string; `roles*`: list[string]; `org_id*`: string | null; `org_name*`: string | null; `org_type*`: string | null; `mfa_enabled*`: boolean; `mfa_verified*`: boolean

**`MfaCodeIn`** — `code*`: string (minLength=6; maxLength=8)

**`MfaSetupOut`** — `secret*`: string; `otpauth_uri*`: string

**`ModeIn`** — `mode*`: string (pattern `^(mock|real)$`); `base_url`: string | null

**`NotificationOut`** — `id*`: string; `channel*`: string; `template*`: string; `title*`: string; `body*`: string; `payload*`: object; `status*`: string; `created_at*`: string; `read_at*`: string | null

**`ObservationIn`** — `queue_len*`: integer (minimum=0.0; maximum=2000.0); `avg_wait_s*`: integer (minimum=0.0; maximum=86400.0); `arrivals_per_hour*`: number (minimum=0.0; maximum=2000.0); `source`: string (pattern `^(live|simulated|replay)$`; default="simulated")

**`OfferIn`** — `title*`: string (minLength=3; maxLength=160); `cargo_type`: string (pattern `^(general|container|bulk|liquid|reefer|hazardous)$`; default="general"); `mass_kg*`: integer (minimum=100.0; maximum=45000.0); `volume_m3`: number | null; `length_m`: number | null; `requires_body_types`: list[string]; `origin*`: string; `origin_lat*`: number; `origin_lon*`: number; `destination*`: string; `dest_lat*`: number; `dest_lon*`: number; `ready_from*`: string; `deadline*`: string; `offered_price_kes*`: number (minimum=0.0); `notes`: string | null

**`OfferOut`** — `title*`: string (minLength=3; maxLength=160); `cargo_type`: string (pattern `^(general|container|bulk|liquid|reefer|hazardous)$`; default="general"); `mass_kg*`: integer (minimum=100.0; maximum=45000.0); `volume_m3`: number | null; `length_m`: number | null; `requires_body_types`: list[string]; `origin*`: string; `origin_lat*`: number; `origin_lon*`: number; `destination*`: string; `dest_lat*`: number; `dest_lon*`: number; `ready_from*`: string; `deadline*`: string; `offered_price_kes*`: number (minimum=0.0); `notes`: string | null; `id*`: string; `cargo_owner_org_id*`: string; `cargo_owner_name*`: string | null; `status*`: string; `created_at*`: string; `matches*`: list[MatchOut]

**`OrgOut`** — `id*`: string; `name*`: string; `type*`: string; `status*`: string

**`OverrideIn`** — `reason*`: string (minLength=10; maxLength=300)

**`PassportOut`** — `id*`: string; `reference*`: string; `owner_org_id*`: string; `owner_org_name*`: string | null; `transporter_org_id*`: string | null; `transporter_org_name*`: string | null; `vehicle_id*`: string | null; `vehicle_plate*`: string | null; `vehicle_rfid*`: list[string]; `trailer_id*`: string | null; `warehouse_id*`: string | null; `description*`: string; `cargo_type*`: string; `origin*`: string; `destination*`: string; `origin_lat*`: number | null; `origin_lon*`: number | null; `dest_lat*`: number | null; `dest_lon*`: number | null; `declared_mass_kg*`: integer; `vgm_kg*`: integer | null; `stage*`: string; `status*`: string; `containers*`: list[object]; `declaration*`: object | null; `seals*`: list[object]; `processing_events*`: list[ProcessingEventOut]; `weighings*`: list[object]; `tickets*`: list[object]; `predicted_release_at*`: string | null; `predicted_release_p10*`: string | null; `predicted_release_p90*`: string | null; `prediction_explanation*`: object | null; `outstanding*`: list[string]; `created_at*`: string

**`PositionIn`** — `lat*`: number (minimum=-90.0; maximum=90.0); `lon*`: number (minimum=-180.0; maximum=180.0)

**`ProcessingEventOut`** — `id*`: string; `stage*`: string; `status*`: string; `occurred_at*`: string; `source*`: string; `notes*`: string | null

**`QueueOut`** — `station_id*`: string; `ts*`: string; `kind*`: string; `queue_len*`: integer; `avg_wait_s*`: integer; `utilisation*`: number; `arrivals_per_hour*`: number; `lower*`: integer | null; `upper*`: integer | null; `model_version*`: string | null; `source*`: string

**`ReadinessIn`** — `readiness_status*`: string (pattern `^(ready|busy|closed)$`)

**`RefreshIn`** — `refresh_token*`: string

**`RegisterIn`** — `email*`: string (pattern `^[^@\s]+@[^@\s]+\.[^@\s]+$`; maxLength=254); `password*`: string (minLength=10; maxLength=128); `full_name*`: string (minLength=2; maxLength=200); `phone`: string | null; `org_name`: string | null; `org_type`: string (pattern `^(transporter|cargo_owner|warehouse)$`; default="cargo_owner"); `role`: string (pattern `^(transporter_admin|cargo_owner|warehouse_manager|driver|dispatcher)$`; default="cargo_owner")

**`SealIn`** — `seal_id*`: string; `status*`: string (pattern `^(armed|breached|removed|unknown)$`)

**`SendIn`** — `user_id`: string | null; `org_id`: string | null; `template*`: string (pattern `^(slot_assigned|clearance|cargo_stage|backhaul|delivered|custom)$`); `title*`: string (maxLength=160); `body*`: string (maxLength=1000); `channels`: list[string] (default=["ws"]); `payload`: object

**`SensorHealthIn`** — `status*`: string (pattern `^(ok|degraded|fault)$`); `reason`: string | null

**`SensorOut`** — `id*`: string; `kind*`: string; `serial*`: string | null; `channel*`: integer | null; `install_position_m*`: number | null; `status*`: string; `health_reason*`: string | null; `last_reading_at*`: string | null; `calibration_valid_to*`: string | null

**`ShipmentIn`** — `description*`: string (minLength=3; maxLength=300); `cargo_type`: string (pattern `^(general|container|bulk|liquid|reefer|hazardous)$`; default="general"); `origin*`: string; `destination*`: string; `origin_lat`: number | null; `origin_lon`: number | null; `dest_lat`: number | null; `dest_lon`: number | null; `declared_mass_kg*`: integer (minimum=0.0; maximum=60000.0); `vgm_kg`: integer | null; `transporter_org_id`: string | null; `vehicle_id`: string | null; `warehouse_id`: string | null; `containers`: list[ContainerIn]; `declaration_reference`: string | null; `seal_id`: string | null

**`SimulateIn`** — `lane_id*`: string; `count`: integer (minimum=1.0; maximum=50.0; default=1); `overload_prob`: number (minimum=0.0; maximum=1.0; default=0.15); `sensor_fault_prob`: number (minimum=0.0; maximum=1.0; default=0.03); `anpr_misread_prob`: number (minimum=0.0; maximum=1.0; default=0.05); `rfid_missing_prob`: number (minimum=0.0; maximum=1.0; default=0.1); `clone_prob`: number (minimum=0.0; maximum=1.0; default=0.01); `unregistered_prob`: number (minimum=0.0; maximum=1.0; default=0.05); `pavement_temp_c`: number (minimum=-10.0; maximum=80.0; default=32.0); `vehicle_id`: string | null; `force_gvm_kg`: integer | null; `seed`: integer | null

**`SlotOut`** — `slot_start*`: string; `slot_end*`: string; `capacity*`: integer; `booked*`: integer; `available*`: integer

**`StageIn`** — `stage*`: string; `status`: string (pattern `^(started|completed|blocked)$`; default="completed"); `notes`: string | null

**`StaticVerifyIn`** — `static_gvm_kg*`: integer (minimum=500.0; maximum=90000.0); `axle_loads_kg`: list[integer] | null; `notes`: string | null

**`StationIn`** — `code*`: string (minLength=2; maxLength=16); `name*`: string; `lat*`: number; `lon*`: number; `capacity_per_hour`: integer (default=120); `static_capacity_per_hour`: integer (default=40); `alt_allowed`: boolean (default=false)

**`StationOut`** — `id*`: string; `code*`: string; `name*`: string; `lat*`: number; `lon*`: number; `capacity_per_hour*`: integer; `static_capacity_per_hour*`: integer; `alt_allowed*`: boolean; `status*`: string; `lanes*`: list[LaneOut]; `queue_len*`: integer; `avg_wait_s*`: integer; `utilisation*`: number; `decisions_last_hour*`: object

**`StationStatusIn`** — `status*`: string (pattern `^(operational|degraded|offline)$`); `reason`: string | null

**`StatsOut`** — `total*`: integer; `by_decision*`: object; `by_source*`: object; `mean_latency_ms*`: number; `green_rate*`: number; `stops_avoided*`: integer

**`TicketOut`** — `id*`: string; `type*`: string; `payload*`: object; `signature*`: string; `signer_key_id*`: string; `qr_token*`: string; `signature_valid*`: boolean

**`TokenOut`** — `access_token*`: string; `refresh_token*`: string; `token_type`: string (default="bearer"); `expires_in*`: integer; `mfa_required`: boolean (default=false); `roles*`: list[string]; `org_id*`: string | null; `user_id*`: string; `full_name*`: string

**`TrailerIn`** — `plate*`: string (minLength=4; maxLength=16); `axle_config`: string (pattern `^\d(\+\d)*$`; default="2"); `tare_kg*`: integer (minimum=500.0; maximum=20000.0)

**`TrailerOut`** — `plate*`: string (minLength=4; maxLength=16); `axle_config`: string (pattern `^\d(\+\d)*$`; default="2"); `tare_kg*`: integer (minimum=500.0; maximum=20000.0); `id*`: string; `org_id*`: string; `status*`: string

**`UserIn`** — `email*`: string (pattern `^[^@\s]+@[^@\s]+\.[^@\s]+$`; maxLength=254); `password*`: string (minLength=10); `full_name*`: string; `org_id`: string | null; `roles*`: list[string]; `phone`: string | null

**`UserOut`** — `id*`: string; `email*`: string; `full_name*`: string; `org_id*`: string | null; `org_name*`: string | null; `roles*`: list[string]; `is_active*`: boolean; `mfa_enabled*`: boolean; `last_login_at*`: string | null

**`UserPatch`** — `roles`: list[string] | null; `is_active`: boolean | null; `org_id`: string | null

**`VehicleIn`** — `plate*`: string (minLength=5; maxLength=16); `fleet_id`: string | null; `make`: string | null; `model`: string | null; `axle_config`: string (pattern `^\d(\+\d)*$`; default="1+1"); `tare_kg*`: integer (minimum=1000.0; maximum=30000.0); `max_gvm_kg`: integer (minimum=3500.0; maximum=56000.0; default=56000); `payload_capacity_kg`: integer (minimum=0.0; maximum=50000.0; default=28000); `body_type`: string (pattern `^(flatbed|container|tanker|box|tipper|reefer)$`; default="flatbed"); `rfid_epc`: string | null

**`VehicleOut`** — `id*`: string; `org_id*`: string; `fleet_id*`: string | null; `plate*`: string; `make*`: string | null; `model*`: string | null; `axle_config*`: string; `class_code*`: string; `tare_kg*`: integer; `max_gvm_kg*`: integer; `payload_capacity_kg*`: integer; `body_type*`: string; `status*`: string; `rfid_epcs*`: list[string]; `last_lat*`: number | null; `last_lon*`: number | null; `last_seen_at*`: string | null; `watchlisted*`: boolean

**`VerifyOut`** — `valid*`: boolean; `ticket_type`: string | null; `legal_status`: string | null; `plate`: string | null; `gvm_kg`: integer | null; `decision`: string | null; `occurred_at`: string | null; `station`: string | null; `source`: string | null; `evidence_hash`: string | null

**`WarehouseIn`** — `name*`: string; `lat*`: number; `lon*`: number; `dock_count`: integer (default=2)

**`WarehouseOut`** — `name*`: string; `lat*`: number; `lon*`: number; `dock_count`: integer (default=2); `id*`: string; `org_id*`: string; `readiness_status*`: string; `incoming*`: integer

**`WatchlistIn`** — `reason`: string | null

**`WeighingOut`** — `id*`: string; `station_id*`: string; `lane_id*`: string; `vehicle_id*`: string | null; `plate*`: string | null; `shipment_id*`: string | null; `occurred_at*`: string; `speed_mps*`: number; `gvm_kg*`: integer; `gvm_uncertainty_kg*`: integer; `axle_count*`: integer; `detected_axle_config*`: string | null; `class_code*`: string | null; `quality_flags*`: list; `sensor_health*`: object; `pavement_temp_c*`: number | null; `source*`: string; `kind*`: string; `axles*`: list[AxleOut]; `identity*`: IdentityOut | null; `decision*`: DecisionOut | null

**`WhatIfIn`** — `stops_avoided*`: integer (minimum=0.0); `stops_made*`: integer (minimum=0.0); `avg_queue_wait_s*`: integer (minimum=0.0; maximum=86400.0); `empty_km`: number (minimum=0.0; default=0); `empty_km_avoided`: number (minimum=0.0; default=0); `detour_km`: number (minimum=0.0; default=0); `factors`: object | null

## 5. Event catalogue

Source of truth: `apps/api/kifaru/events.py` (`EventType`, `make_event`, `EventBus`). Events are published in-process to WebSocket subscribers and, when `KIFARU_REDIS_URL` is set, on the Redis channel `kifaru.events` for fan-out across API instances. **Events on the bus are not persisted and not signed**; persistence and signing are the job of the ledger (`services/ledger.py`), which has its own type vocabulary (§5.3). The architecture document's envelope fields `prev_hash`, `hash`, `signature` apply to ledger rows, not to bus events.

### 5.1 Envelope

```json
{
  "event_id": "01JBZ…ULID",
  "type": "clearance.decided",
  "occurred_at": "2026-11-04T09:00:00.000000+00:00",
  "station_id": "01J…" ,            // null for non-station events
  "org_id": null,                    // tenant tag; null = visible to all authenticated subscribers
  "payload": { ... },                // type-specific, see 5.2
  "producer": "cloud-api",           // or "simulated" / "live" (the lane-pass source) / "edge"
  "schema_version": 1
}
```

### 5.2 Types

| Type | Emitted by | Payload keys | Tenant tag |
|---|---|---|---|
| `truck.detected` | `weighing_service.process_lane_pass` | `lane_id` | station |
| `truck.identified` | same | `weighing_event_id, plate, confidence, method` | station |
| `weighing.started` | same | `lane_id` | station |
| `weighing.completed` | same | `weighing_event_id, decision_id, decision, plate, gvm_kg, u_kg, axle_config, lane_id, latency_ms, source, rules_fired[]` | station |
| `clearance.decided` | same | same as `weighing.completed` | station |
| `truck.diverted` | same (AMBER/RED); `static_verify` when static GVM > legal max | lane-pass payload or `{weighing_event_id, static_gvm_kg, wim_error_pct}` | station |
| `truck.released` | same (GREEN); `static_verify` when static GVM ≤ legal max | as above | station |
| `cargo.verified` | `shipments.advance_stage` (stage `weighing_verification` completed) | `shipment_id, reference` | org |
| `cargo.status_changed` | `shipments.create_shipment`, `advance_stage` | `shipment_id, reference, stage, status?` | org |
| `queue.updated` | `queue.observe`, `queue.book` | `{station_id, code, queue_len, avg_wait_s, utilisation, source}` or `{station_id, appointment_id, slot_start, plate}` | station (+ org for bookings) |
| `station.failure` | `stations.set_station_status` (degraded/offline) | `station_id, code, status, reason, incident_id` | station |
| `backhaul.opportunity` | `backhaul.create_offer` | `offer_id, title, origin, destination, mass_kg, price_kes` | none (all) |
| `shipment.delivered` | `shipments.advance_stage` (delivered), `backhaul.deliver` | `{shipment_id, reference}` or `{backhaul_match_id, offer_id}` | org |
| `sensor.health` | `stations.set_sensor_health` | `sensor_id, lane_id, kind, status, reason` | station |
| `incident.opened` | `admin.open_incident` | `incident_id, title, severity, station_id` | station |
| `notification` *(ad hoc string, not in `EventType`)* | `notifications.notify` (ws channel) | `user_id, org_id, title, body, template, …payload` | org |

The 13 categories required by RTM RTC-02 are the first 13 rows; `sensor.health` and `incident.opened` are additions.

### 5.3 Ledger entry types (persisted, hash-chained, signed)

`weighing.completed`, `clearance.decided`, `static.verified`, `clearance.overridden`, `shipment.registered`, `shipment.assigned`, `cargo.status_changed`, `seal.status`, `backhaul.offer_created`, `backhaul.assigned`, `backhaul.delivered`. Each row: `event_id, seq, type, payload, station_id, producer, prev_hash, hash, signature, signer_key_id, occurred_at, received_at`; `hash = sha256(canonical_json({event_id, seq, type, payload, station_id, producer, prev_hash, occurred_at}))`, `signature = Ed25519(canonical_json({"hash": hash}))`. Verify with `GET /api/v1/admin/ledger/verify`.

## 6. WebSocket contract — `/ws/events`

Source: `apps/api/kifaru/routers/ws.py`.

| Item | Specification |
|---|---|
| URL | `wss://<host>/ws/events?token=<access JWT>[&station=<station_id>][&types=a,b,c]` |
| Authentication | Access token in the `token` query parameter (must be `type=access` and unexpired). Invalid token → close code **4401** before accept |
| Filters | `station`: deliver only events whose `station_id` is this station or null. `types`: comma-separated list of event types |
| Tenant scoping | Platform-wide roles (`platform_admin, port_controller, weighbridge_operator, auditor, regulator_readonly`) receive everything that passes the filters. Other roles receive events whose `org_id` is null (station-level operational events) or equals their own `org` claim |
| First message | `{"type": "hello", "recent": [ …up to 20 recent events passing the filter… ]}` |
| Stream | One JSON event per text frame (envelope §5.1) |
| Keep-alive | Server sends `{"type": "ping"}` after 25 s without events; clients need not reply (no pong handling) |
| Backpressure | Per-subscriber queue of 500 events; overflow drops silently for that subscriber |
| Multi-instance | With Redis configured, instances publish to `kifaru.events`; the subscribing side across instances is part of the realtime gateway design (not in this code base) |
| Close | Client disconnect unsubscribes; token expiry is **not** enforced after connect — clients should reconnect at least every 15 minutes with a fresh token |

Example (JavaScript):

```js
const ws = new WebSocket(`wss://api.example/ws/events?token=${access}&types=clearance.decided,station.failure`);
ws.onmessage = (m) => { const ev = JSON.parse(m.data); if (ev.type === "ping") return; render(ev); };
```

## 7. Integration adapter contracts (declared, mock by default)

| Name | Display | Declared contract (`routers/integrations.py ADAPTERS`) |
|---|---|---|
| `kenha` | KeNHA axle-load enforcement | `POST /v1/wim-events {plate, gvm_kg, axle_loads[], decision, station, ticket_id} -> {ack_id}; GET /v1/watchlist -> [{plate, reason}]` |
| `kpa` | Kenya Ports Authority gate / KWATOS | `GET /v1/trucks/{plate}/gate-status -> {stage, gate, eta}; POST /v1/appointments` |
| `kra` | KRA iCMS customs declarations | `GET /v1/declarations/{reference} -> {status, declared_mass_kg, items[]}; webhook status updates` |
| `ntsa` | NTSA vehicle registry (TIMS) | `GET /v1/vehicles/{plate} -> {owner_org, axle_config, tare_kg, class}` |
| `customs` | Authorised customs/ECTS seal provider | `GET /v1/seals/{seal_id} -> {status, armed_at, last_position}; webhook breach alerts` |
| `fleet` | Transporter fleet management platforms | `GET /vehicles, POST /positions (GPS), webhook trip events` |
| `wms` | Warehouse management systems | `GET /docks/availability, POST /inbound-appointments` |
| `payment` | Payment gateway (M-Pesa Daraja / card) | `POST /stkpush {phone, amount, ref}; callback /payments/callback` |
| `sms` | SMS (Africa's Talking) | `POST /version1/messaging {to, message}` |
| `email` | Email (SES/SMTP) | `SendEmail {to, subject, body}` |
| `maps` | Mapping and routing (OSRM / Google Routes) | `GET /route/v1/driving/{coords} -> {distance_m, duration_s}` |
| `telematics` | GPS / telematics providers | `GET /units, GET /positions?since=; webhook positions` |

These are the platform's *expected* interfaces, not confirmed government APIs (RTM PRL-02, INT-01). Real endpoints and credentials require authorisation from each institution.

## 8. Regenerating this document

```powershell
cd apps\api
..\..\.venv\Scripts\python.exe -c "import json; from kifaru.main import app; print(json.dumps(app.openapi()))" > ..\..\docs\06-operations\openapi.json
```

Then re-run the generator (kept outside the repository) or update §3 by hand; the role map must be re-read from `routers/*.py` whenever a `require_roles(...)` changes.

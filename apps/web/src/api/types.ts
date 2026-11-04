/**
 * Hand-written TypeScript types mirroring the FastAPI routers in apps/api/kifaru/routers/*.py.
 * Keep in sync with the backend; field names use the API snake_case.
 */

export type Role =
  | 'platform_admin'
  | 'port_controller'
  | 'weighbridge_operator'
  | 'transporter_admin'
  | 'dispatcher'
  | 'driver'
  | 'cargo_owner'
  | 'warehouse_manager'
  | 'auditor'
  | 'regulator_readonly';

export const ALL_ROLES: Role[] = [
  'platform_admin', 'port_controller', 'weighbridge_operator', 'transporter_admin', 'dispatcher',
  'driver', 'cargo_owner', 'warehouse_manager', 'auditor', 'regulator_readonly',
];

export type Source = 'live' | 'simulated' | 'replay' | 'static' | 'forecast' | string;
export type Decision = 'GREEN' | 'AMBER' | 'RED';

// ---------------------------------------------------------------- auth
export interface LoginIn { email: string; password: string; totp_code?: string | null }
export interface TokenOut {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  mfa_required: boolean;
  roles: Role[];
  org_id: string | null;
  user_id: string;
  full_name: string;
}
export interface MeOut {
  user_id: string;
  email: string;
  full_name: string;
  roles: Role[];
  org_id: string | null;
  org_name: string | null;
  org_type: string | null;
  mfa_enabled: boolean;
  mfa_verified: boolean;
}
export interface MfaSetupOut { secret: string; otpauth_uri: string }
export interface RegisterIn {
  email: string; password: string; full_name: string; phone?: string | null; org_name?: string | null;
  org_type?: 'transporter' | 'cargo_owner' | 'warehouse';
  role?: 'transporter_admin' | 'cargo_owner' | 'warehouse_manager' | 'driver' | 'dispatcher';
}

// ---------------------------------------------------------------- fleet
export interface OrgOut { id: string; name: string; type: string; status: string }
export interface FleetOut { id: string; org_id: string; name: string; vehicle_count: number }
export type BodyType = 'flatbed' | 'container' | 'tanker' | 'box' | 'tipper' | 'reefer';
export const BODY_TYPES: BodyType[] = ['flatbed', 'container', 'tanker', 'box', 'tipper', 'reefer'];
export interface VehicleIn {
  plate: string; fleet_id?: string | null; make?: string | null; model?: string | null; axle_config: string;
  tare_kg: number; max_gvm_kg: number; payload_capacity_kg: number; body_type: BodyType; rfid_epc?: string | null;
}
export interface VehicleOut {
  id: string; org_id: string; fleet_id: string | null; plate: string; make: string | null; model: string | null;
  axle_config: string; class_code: string; tare_kg: number; max_gvm_kg: number; payload_capacity_kg: number;
  body_type: string; status: string; rfid_epcs: string[]; last_lat: number | null; last_lon: number | null;
  last_seen_at: string | null; watchlisted: boolean;
}
export interface PositionIn { lat: number; lon: number }
export interface DriverOut { id: string; org_id: string; full_name: string; license_class: string | null; status: string }
export interface TrailerOut { id: string; org_id: string; plate: string; axle_config: string; tare_kg: number; status: string }

// ---------------------------------------------------------------- stations
export type SensorStatus = 'ok' | 'degraded' | 'fault' | string;
export interface SensorOut {
  id: string; kind: string; serial: string | null; channel: number | null; install_position_m: number | null;
  status: SensorStatus; health_reason: string | null; last_reading_at: string | null; calibration_valid_to: string | null;
}
export interface LaneOut {
  id: string; lane_no: number; type: 'wim_highspeed' | 'wim_lowspeed' | 'static' | string; direction: string; status: string;
  device_id: string | null; calibration_valid_to: string | null; sensors: SensorOut[];
}
export interface StationOut {
  id: string; code: string; name: string; lat: number; lon: number; capacity_per_hour: number; static_capacity_per_hour: number;
  alt_allowed: boolean; status: 'operational' | 'degraded' | 'offline' | string; lanes: LaneOut[]; queue_len: number; avg_wait_s: number;
  utilisation: number; decisions_last_hour: Record<Decision, number>;
}
export interface StationIn { code: string; name: string; lat: number; lon: number; capacity_per_hour: number; static_capacity_per_hour: number; alt_allowed: boolean }
export interface StationStatusIn { status: 'operational' | 'degraded' | 'offline'; reason?: string | null }
export interface LaneIn { lane_no: number; type: 'wim_highspeed' | 'wim_lowspeed' | 'static'; direction: string; device_id?: string | null }
export interface SensorHealthIn { status: 'ok' | 'degraded' | 'fault'; reason?: string | null }
export type CalibrationMethod = 'reference_vehicle' | 'static_scale_comparison' | 'shunt' | 'bench';
export interface CalibrationIn {
  method: CalibrationMethod; reference_mass_kg?: number | null; gain: number; offset: number; temp_coeff_per_c: number;
  reference_temp_c: number; uncertainty_pct: number; valid_days: number; notes?: string | null;
}
export interface CalibrationOut extends CalibrationIn { id: string; sensor_id: string; valid_from: string; valid_to: string }

// ---------------------------------------------------------------- weighing
export interface AxleOut { axle_index: number; load_kg: number; uncertainty_kg: number; spacing_to_next_m: number | null; group_no: number }
export interface IdentityOut {
  anpr_plate: string | null; anpr_confidence: number | null; rfid_epc: string | null; rfid_confidence: number | null;
  confidence: number; method: string; explanation: string | null;
}
export interface RuleFired { rule: string; severity: 'RED' | 'AMBER' | 'INFO'; fired: boolean; detail: string }
export interface GroupMargin {
  group_no: number; axles: number; measured_kg: number; u_kg: number; limit_kg: number; limit_with_tolerance_kg: number;
  status: 'over' | 'marginal' | 'ok';
}
export interface Margins {
  gvm?: Record<string, number | string | undefined>;
  groups?: GroupMargin[];
  declaration?: { expected_gvm_kg: number; diff_kg: number; tolerance_kg: number };
  [k: string]: unknown;
}
export interface DecisionOut {
  id: string; decision: Decision; rules_fired: RuleFired[]; margins: Margins; limits_version: string; engine_version: string;
  audit_selected: boolean; evidence_hash: string; decided_at: string; latency_ms: number; explanation: string;
  static_verified_gvm_kg: number | null; override_reason: string | null; ticket_id: string | null;
  ticket_type: 'prescreen' | 'static_certified' | null; qr_token: string | null;
}
export interface WeighingOut {
  id: string; station_id: string; lane_id: string; vehicle_id: string | null; plate: string | null; shipment_id: string | null;
  occurred_at: string; speed_mps: number; gvm_kg: number; gvm_uncertainty_kg: number; axle_count: number;
  detected_axle_config: string | null; class_code: string | null; quality_flags: string[]; sensor_health: Record<string, string>;
  pavement_temp_c: number | null; source: Source; kind: string; axles: AxleOut[]; identity: IdentityOut | null; decision: DecisionOut | null;
}
export interface StatsOut { total: number; by_decision: Record<Decision, number>; by_source: Record<string, number>; mean_latency_ms: number; green_rate: number; stops_avoided: number }
export interface SimulateIn {
  lane_id: string; count: number; overload_prob: number; sensor_fault_prob: number; anpr_misread_prob: number; rfid_missing_prob: number;
  clone_prob: number; unregistered_prob: number; pavement_temp_c: number; vehicle_id?: string | null; force_gvm_kg?: number | null; seed?: number | null;
}
export interface StaticVerifyIn { static_gvm_kg: number; axle_loads_kg?: number[] | null; notes?: string | null }
export interface OverrideIn { reason: string }
export interface LimitsOut {
  version: string; steering_single_kg: number; single_drive_kg: number; tandem_kg: number; tridem_kg: number; gvm_max_kg: number;
  axle_tolerance_pct: number; gvm_tolerance_pct: number; green_safety_margin_kg: number; identity_min_confidence: number;
  audit_sample_rate: number; notes: string;
}

// ---------------------------------------------------------------- tickets
export interface TicketPayload {
  ticket_type: string; legal_status: string; weighing_event_id: string; decision_id: string; station: string; lane_id: string; occurred_at: string;
  plate: string | null; vehicle_id: string | null; shipment_id: string | null; gvm_kg: number; gvm_uncertainty_kg: number | null;
  axles: { i: number; kg: number; u_kg: number; group: number }[]; axle_config: string | null; decision: Decision; limits_version: string;
  engine_version: string; evidence_hash: string; source: Source; signer_key_id: string; public_key: string;
}
export interface TicketOut { id: string; type: 'prescreen' | 'static_certified' | string; payload: TicketPayload; signature: string; signer_key_id: string; qr_token: string; signature_valid: boolean }
export interface VerifyOut {
  valid: boolean; ticket_type: string | null; legal_status: string | null; plate: string | null; gvm_kg: number | null; decision: Decision | null;
  occurred_at: string | null; station: string | null; source: Source | null; evidence_hash: string | null;
}

// ---------------------------------------------------------------- shipments / passport
export const SHIPMENT_STAGES = [
  'registered', 'declared', 'at_port', 'customs_processing', 'weighing_verification', 'gate_processing', 'released', 'in_transit', 'delivered', 'closed',
] as const;
export type ShipmentStage = (typeof SHIPMENT_STAGES)[number];
export type CargoType = 'general' | 'container' | 'bulk' | 'liquid' | 'reefer' | 'hazardous';
export const CARGO_TYPES: CargoType[] = ['general', 'container', 'bulk', 'liquid', 'reefer', 'hazardous'];
export interface ContainerIn { number: string; size_ft: number; type: string }
export interface ShipmentIn {
  description: string; cargo_type: CargoType; origin: string; destination: string; origin_lat?: number | null; origin_lon?: number | null;
  dest_lat?: number | null; dest_lon?: number | null; declared_mass_kg: number; vgm_kg?: number | null; transporter_org_id?: string | null;
  vehicle_id?: string | null; warehouse_id?: string | null; containers: ContainerIn[]; declaration_reference?: string | null; seal_id?: string | null;
}
export interface ProcessingEventOut { id: string; stage: string; status: 'started' | 'completed' | 'blocked' | string; occurred_at: string; source: string; notes: string | null }
export interface PassportWeighing { id: string; occurred_at: string; gvm_kg: number; u_kg: number; decision: Decision | null; station_id: string; source: Source }
export interface PassportTicket { id: string; type: string; qr_token: string; decision: Decision; gvm_kg: number; source: Source }
export interface PassportOut {
  id: string; reference: string; owner_org_id: string; owner_org_name: string | null; transporter_org_id: string | null; transporter_org_name: string | null;
  vehicle_id: string | null; vehicle_plate: string | null; vehicle_rfid: string[]; trailer_id: string | null; warehouse_id: string | null;
  description: string; cargo_type: string; origin: string; destination: string; origin_lat: number | null; origin_lon: number | null;
  dest_lat: number | null; dest_lon: number | null; declared_mass_kg: number; vgm_kg: number | null; stage: ShipmentStage | string; status: string;
  containers: { id: string; number: string; size_ft: number; type: string }[];
  declaration: { id: string; reference: string; source: string; status: string; declared_mass_kg: number } | null;
  seals: { id: string; seal_id: string; provider: string; status: string; armed_at: string | null; breached_at: string | null }[];
  processing_events: ProcessingEventOut[]; weighings: PassportWeighing[]; tickets: PassportTicket[];
  predicted_release_at: string | null; predicted_release_p10: string | null; predicted_release_p90: string | null;
  prediction_explanation: Record<string, unknown> | null; outstanding: string[]; created_at: string;
}
export interface StageIn { stage: ShipmentStage; status: 'started' | 'completed' | 'blocked'; notes?: string | null }
export interface AssignIn { vehicle_id: string; transporter_org_id?: string | null; driver_id?: string | null }
export interface WarehouseOut { id: string; org_id: string; name: string; lat: number; lon: number; dock_count: number; readiness_status: 'ready' | 'busy' | 'closed' | string; incoming: number }
export interface WarehouseIn { name: string; lat: number; lon: number; dock_count: number }

// ---------------------------------------------------------------- queue
export interface QueueOut {
  station_id: string; ts: string; kind: string; queue_len: number; avg_wait_s: number; utilisation: number; arrivals_per_hour: number;
  lower: number | null; upper: number | null; model_version: string | null; source: Source;
}
export interface ObservationIn { queue_len: number; avg_wait_s: number; arrivals_per_hour: number; source: 'live' | 'simulated' | 'replay' }
export interface SlotOut { slot_start: string; slot_end: string; capacity: number; booked: number; available: number }
export interface BookIn { vehicle_id: string; slot_start: string; shipment_id?: string | null; priority: number }
export interface AppointmentOut {
  id: string; station_id: string; station_code: string; vehicle_id: string; plate: string; shipment_id: string | null; slot_start: string; slot_end: string;
  status: 'booked' | 'arrived' | 'completed' | 'missed' | 'cancelled' | string; priority: number; est_wait_s: number | null; assigned_by: string;
}

// ---------------------------------------------------------------- backhaul
export interface OfferIn {
  title: string; cargo_type: CargoType; mass_kg: number; volume_m3?: number | null; length_m?: number | null; requires_body_types: string[];
  origin: string; origin_lat: number; origin_lon: number; destination: string; dest_lat: number; dest_lon: number; ready_from: string; deadline: string;
  offered_price_kes: number; notes?: string | null;
}
export interface MatchOut {
  id: string; offer_id: string; vehicle_id: string; plate: string; transporter_org_id: string; transporter_name: string | null; score: number; extra_km: number;
  fuel_litres: number; fuel_cost_kes: number; revenue_kes: number; co2_avoided_kg: number; explanation: Record<string, unknown>;
  status: 'proposed' | 'transporter_accepted' | 'owner_accepted' | 'assigned' | 'rejected' | 'cancelled' | 'delivered' | string;
  transporter_decided_at: string | null; owner_decided_at: string | null; assigned_at: string | null;
}
export interface OfferOut extends OfferIn { id: string; cargo_owner_org_id: string; cargo_owner_name: string | null; status: string; created_at: string; matches: MatchOut[] }
export interface DecisionIn { accept: boolean; reason?: string | null }

// ---------------------------------------------------------------- notifications
export interface NotificationOut {
  id: string; channel: string; template: string; title: string; body: string; payload: Record<string, unknown>; status: string; created_at: string; read_at: string | null;
}

// ---------------------------------------------------------------- environment
export interface EnvBundle { idle_l: number; stop_l: number; empty_l: number; detour_l: number; litres: number; co2_kg: number; cost_kes: number }
export interface EnvSavings { litres: number; co2_kg: number; cost_kes: number }
export interface EnvReportOut {
  period_hours: number; station_id: string | null; inputs: Record<string, number>; baseline: EnvBundle; platform: EnvBundle;
  savings: EnvSavings; factors: Record<string, number>; label: string; assumptions: string[]; agent_confidence: number;
}
export interface WhatIfIn { stops_avoided: number; stops_made: number; avg_queue_wait_s: number; empty_km?: number; empty_km_avoided?: number; detour_km?: number; factors?: Record<string, number> | null }
export interface WhatIfOut {
  ok: boolean; baseline: EnvBundle; platform: EnvBundle; savings: EnvSavings; factors: Record<string, number>;
  label: string; assumptions: string[]; agent_confidence: number; explanation: string;
}

// ---------------------------------------------------------------- integrations
export interface IntegrationOut {
  id: string; name: string; display_name: string; mode: 'mock' | 'real' | string; contract: string; base_url: string | null; health_status: string;
  last_ok_at: string | null; last_error: string | null;
}
export interface ModeIn { mode: 'mock' | 'real'; base_url?: string | null }

// ---------------------------------------------------------------- admin
export interface UserOut { id: string; email: string; full_name: string; org_id: string | null; org_name: string | null; roles: Role[]; is_active: boolean; mfa_enabled: boolean; last_login_at: string | null }
export interface UserIn { email: string; password: string; full_name: string; org_id?: string | null; roles: Role[]; phone?: string | null }
export interface UserPatch { roles?: Role[] | null; is_active?: boolean | null; org_id?: string | null }
export interface AuditOut { id: string; actor_user_id: string | null; action: string; entity: string; entity_id: string | null; before: Record<string, unknown> | null; after: Record<string, unknown> | null; at: string }
export interface LedgerOut { event_id: string; seq: number; type: string; payload: Record<string, unknown>; station_id: string | null; producer: string; prev_hash: string; hash: string; signature: string; occurred_at: string }
export interface LedgerVerifyOut { ok: boolean; checked: number; total?: number; head_hash?: string; error?: string; public_key: string; signer_key_id: string }
export interface IncidentOut {
  id: string; station_id: string | null; severity: 'low' | 'medium' | 'high' | 'critical' | string; category: string; title: string; details: Record<string, unknown>;
  status: 'open' | 'closed' | string; opened_at: string; closed_at: string | null; raised_by: string;
}
export type IncidentCategory = 'station_failure' | 'sensor_fault' | 'security' | 'traffic' | 'cargo_anomaly' | 'other';
export interface IncidentIn { station_id?: string | null; severity: 'low' | 'medium' | 'high' | 'critical'; category: IncidentCategory; title: string; details?: Record<string, unknown> }
export interface SystemHealthOut {
  env: string; version: string; database: string; database_kind: string; redis: string; mqtt: string; weighings_last_hour: number; ws_subscribers: number;
  events_recent: number; signing_key_id: string;
}
export interface AgentDescription { name: string; version: string; responsibilities: string; inputs: Record<string, string>; outputs: Record<string, string> }
export interface AgentCatalogue { agents: AgentDescription[]; pipelines: Record<string, string[]>; policy: string }

// ---------------------------------------------------------------- realtime
export type LiveEventType =
  | 'truck.detected' | 'truck.identified' | 'weighing.started' | 'weighing.completed' | 'clearance.decided' | 'truck.diverted' | 'truck.released'
  | 'cargo.verified' | 'cargo.status_changed' | 'queue.updated' | 'station.failure' | 'backhaul.opportunity' | 'shipment.delivered'
  | 'sensor.health' | 'incident.opened' | 'notification';
export interface LiveEvent {
  event_id: string; type: LiveEventType | string; occurred_at: string; station_id: string | null; org_id: string | null;
  payload: Record<string, unknown>; producer?: string; schema_version?: number;
}
export interface ClearancePayload {
  weighing_event_id: string; decision_id: string; decision: Decision; plate: string | null; gvm_kg: number; u_kg: number; axle_config: string | null;
  lane_id: string; latency_ms: number; source: Source; rules_fired: string[];
}

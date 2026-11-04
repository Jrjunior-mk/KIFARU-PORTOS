/** Typed API surface, one function per backend operation. Paths are relative to /api/v1. */
import { http, qs, API_PREFIX } from './client';
import type * as T from './types';

export const auth = {
  login: (body: T.LoginIn) => http.post<T.TokenOut>('/auth/login', body, { auth: false }),
  register: (body: T.RegisterIn) => http.post<T.TokenOut>('/auth/register', body, { auth: false }),
  refresh: (refresh_token: string) => http.post<T.TokenOut>('/auth/refresh', { refresh_token }, { auth: false }),
  logout: (refresh_token: string) => http.post<void>('/auth/logout', { refresh_token }),
  me: () => http.get<T.MeOut>('/auth/me'),
  mfaSetup: () => http.post<T.MfaSetupOut>('/auth/mfa/setup'),
  mfaEnable: (code: string) => http.post<void>('/auth/mfa/enable', { code }),
  mfaVerify: (code: string) => http.post<T.TokenOut>('/auth/mfa/verify', { code }),
};

export const fleet = {
  orgs: (type?: string) => http.get<T.OrgOut[]>(`/fleet/orgs${qs({ type })}`),
  fleets: () => http.get<T.FleetOut[]>('/fleet/fleets'),
  createFleet: (name: string) => http.post<T.FleetOut>('/fleet/fleets', { name }),
  vehicles: (org_id?: string) => http.get<T.VehicleOut[]>(`/fleet/vehicles${qs({ org_id })}`),
  vehicle: (id: string) => http.get<T.VehicleOut>(`/fleet/vehicles/${id}`),
  createVehicle: (body: T.VehicleIn) => http.post<T.VehicleOut>('/fleet/vehicles', body),
  position: (id: string, body: T.PositionIn) => http.post<T.VehicleOut>(`/fleet/vehicles/${id}/position`, body),
  watchlist: (id: string, reason: string | null) => http.post<T.VehicleOut>(`/fleet/vehicles/${id}/watchlist`, { reason }),
  drivers: () => http.get<T.DriverOut[]>('/fleet/drivers'),
  trailers: () => http.get<T.TrailerOut[]>('/fleet/trailers'),
};

export const stations = {
  list: () => http.get<T.StationOut[]>('/stations'),
  get: (id: string) => http.get<T.StationOut>(`/stations/${id}`),
  create: (body: T.StationIn) => http.post<T.StationOut>('/stations', body),
  setStatus: (id: string, body: T.StationStatusIn) => http.post<T.StationOut>(`/stations/${id}/status`, body),
  createLane: (stationId: string, body: T.LaneIn) => http.post<T.LaneOut>(`/stations/${stationId}/lanes`, body),
  sensorHealth: (sensorId: string, body: T.SensorHealthIn) => http.post<T.SensorOut>(`/stations/sensors/${sensorId}/health`, body),
  addCalibration: (sensorId: string, body: T.CalibrationIn) => http.post<T.CalibrationOut>(`/stations/sensors/${sensorId}/calibrations`, body),
  calibrations: (sensorId: string) => http.get<T.CalibrationOut[]>(`/stations/sensors/${sensorId}/calibrations`),
  sensorKinds: () => http.get<string[]>('/stations/meta/sensor-kinds'),
};

export const weighing = {
  events: (p: { station_id?: string; vehicle_id?: string; decision?: string; limit?: number } = {}) => http.get<T.WeighingOut[]>(`/weighing/events${qs(p)}`),
  event: (id: string) => http.get<T.WeighingOut>(`/weighing/events/${id}`),
  stats: (station_id?: string) => http.get<T.StatsOut>(`/weighing/stats${qs({ station_id })}`),
  simulate: (body: T.SimulateIn) => http.post<T.WeighingOut[]>('/weighing/simulate', body),
  staticVerify: (id: string, body: T.StaticVerifyIn) => http.post<T.WeighingOut>(`/weighing/events/${id}/static-verify`, body),
  overrideRelease: (id: string, body: T.OverrideIn) => http.post<T.WeighingOut>(`/weighing/events/${id}/override-release`, body),
  limits: () => http.get<T.LimitsOut>('/weighing/limits'),
};

export const tickets = {
  get: (id: string) => http.get<T.TicketOut>(`/tickets/${id}`),
  qrSvg: (id: string) => http.get<string>(`/tickets/${id}/qr.svg`, { raw: true }),
  qrUrl: (id: string) => `${API_PREFIX}/tickets/${id}/qr.svg`,
  verify: (qrToken: string) => http.get<T.VerifyOut>(`/tickets/verify/${encodeURIComponent(qrToken)}`, { auth: false }),
};

export const shipments = {
  list: (p: { stage?: string; warehouse_id?: string } = {}) => http.get<T.PassportOut[]>(`/shipments${qs(p)}`),
  get: (idOrRef: string) => http.get<T.PassportOut>(`/shipments/${encodeURIComponent(idOrRef)}`),
  create: (body: T.ShipmentIn) => http.post<T.PassportOut>('/shipments', body),
  stage: (id: string, body: T.StageIn) => http.post<T.PassportOut>(`/shipments/${id}/stage`, body),
  assign: (id: string, body: T.AssignIn) => http.post<T.PassportOut>(`/shipments/${id}/assign`, body),
  seal: (id: string, seal_id: string, status: 'armed' | 'breached' | 'removed' | 'unknown') => http.post<T.PassportOut>(`/shipments/${id}/seal`, { seal_id, status }),
  warehouses: () => http.get<T.WarehouseOut[]>('/shipments/warehouses/all'),
  createWarehouse: (body: T.WarehouseIn) => http.post<T.WarehouseOut>('/shipments/warehouses', body),
  readiness: (id: string, readiness_status: 'ready' | 'busy' | 'closed') => http.post<T.WarehouseOut>(`/shipments/warehouses/${id}/readiness`, { readiness_status }),
};

export const queue = {
  history: (stationId: string, hours = 24) => http.get<T.QueueOut[]>(`/queue/${stationId}/history${qs({ hours })}`),
  observe: (stationId: string, body: T.ObservationIn) => http.post<T.QueueOut>(`/queue/${stationId}/observe`, body),
  forecast: (stationId: string) => http.get<T.QueueOut[]>(`/queue/${stationId}/forecast`),
  slots: (stationId: string, hours = 6) => http.get<T.SlotOut[]>(`/queue/${stationId}/slots${qs({ hours })}`),
  book: (stationId: string, body: T.BookIn) => http.post<T.AppointmentOut>(`/queue/${stationId}/appointments`, body),
  mine: (station_id?: string) => http.get<T.AppointmentOut[]>(`/queue/appointments/mine${qs({ station_id })}`),
  setStatus: (id: string, status: 'arrived' | 'completed' | 'missed' | 'cancelled') => http.post<T.AppointmentOut>(`/queue/appointments/${id}/status`, { status }),
};

export const backhaul = {
  offers: (status?: string) => http.get<T.OfferOut[]>(`/backhaul/offers${qs({ status })}`),
  createOffer: (body: T.OfferIn) => http.post<T.OfferOut>('/backhaul/offers', body),
  match: (offerId: string) => http.post<T.OfferOut>(`/backhaul/offers/${offerId}/match`),
  transporterDecision: (matchId: string, body: T.DecisionIn) => http.post<T.MatchOut>(`/backhaul/matches/${matchId}/transporter-decision`, body),
  ownerDecision: (matchId: string, body: T.DecisionIn) => http.post<T.MatchOut>(`/backhaul/matches/${matchId}/owner-decision`, body),
  deliver: (matchId: string, body: { receiver_name?: string | null; notes?: string | null }) => http.post<T.MatchOut>(`/backhaul/matches/${matchId}/deliver`, body),
  opportunities: () => http.get<T.OfferOut[]>('/backhaul/opportunities'),
};

export const notifications = {
  inbox: (unread_only = false) => http.get<T.NotificationOut[]>(`/notifications${qs({ unread_only })}`),
  markRead: (id: string) => http.post<void>(`/notifications/${id}/read`),
};

export const environment = {
  report: (p: { hours?: number; station_id?: string } = {}) => http.get<T.EnvReportOut>(`/environment/report${qs(p)}`),
  whatIf: (body: T.WhatIfIn) => http.post<T.WhatIfOut>('/environment/what-if', body),
  factors: () => http.get<{ factors: Record<string, number>; formulas: Record<string, string>; label: string }>('/environment/factors'),
};

export const integrations = {
  list: () => http.get<T.IntegrationOut[]>('/integrations'),
  setMode: (name: string, body: T.ModeIn) => http.post<T.IntegrationOut>(`/integrations/${name}/mode`, body),
  health: (name: string) => http.post<T.IntegrationOut>(`/integrations/${name}/health`),
  route: (p: { from_lat: number; from_lon: number; to_lat: number; to_lon: number }) =>
    http.get<{ mode: string; distance_km: number; duration_min: number; label?: string }>(`/integrations/maps/route${qs(p)}`),
};

export const admin = {
  users: () => http.get<T.UserOut[]>('/admin/users'),
  createUser: (body: T.UserIn) => http.post<T.UserOut>('/admin/users', body),
  patchUser: (id: string, body: T.UserPatch) => http.patch<T.UserOut>(`/admin/users/${id}`, body),
  roles: () => http.get<string[]>('/admin/roles'),
  audit: (p: { entity?: string; limit?: number } = {}) => http.get<T.AuditOut[]>(`/admin/audit${qs(p)}`),
  ledger: (p: { limit?: number; type?: string } = {}) => http.get<T.LedgerOut[]>(`/admin/ledger${qs(p)}`),
  ledgerVerify: () => http.get<T.LedgerVerifyOut>('/admin/ledger/verify'),
  incidents: (status: 'open' | 'closed' | '' = 'open') => http.get<T.IncidentOut[]>(`/admin/incidents${qs({ status })}`),
  openIncident: (body: T.IncidentIn) => http.post<T.IncidentOut>('/admin/incidents', body),
  closeIncident: (id: string) => http.post<T.IncidentOut>(`/admin/incidents/${id}/close`),
  systemHealth: () => http.get<T.SystemHealthOut>('/admin/system/health'),
  agents: () => http.get<T.AgentCatalogue>('/admin/agents'),
};

export const api = { auth, fleet, stations, weighing, tickets, shipments, queue, backhaul, notifications, environment, integrations, admin };
export default api;

import type { Role } from '../api/types';

export interface RouteDef { path: string; label: string; roles: Role[]; description: string }

/** Route -> role map (platform_admin can open everything; see README). */
export const ROUTES: RouteDef[] = [
  { path: '/control', label: 'Control Centre', roles: ['port_controller', 'auditor', 'regulator_readonly'], description: 'Network view of stations, queues, clearance feed, incidents' },
  { path: '/operator', label: 'Weighbridge', roles: ['weighbridge_operator'], description: 'Lane console: readings, decisions, static verification, calibration' },
  { path: '/transporter', label: 'Transporter', roles: ['transporter_admin', 'dispatcher'], description: 'Fleet, shipments, slot booking, backhaul' },
  { path: '/driver', label: 'Driver', roles: ['driver'], description: 'Large-tile in-cab screen' },
  { path: '/owner', label: 'Cargo owner', roles: ['cargo_owner'], description: 'Shipment passport, alerts, backhaul offers' },
  { path: '/warehouse', label: 'Warehouse', roles: ['warehouse_manager'], description: 'Incoming shipments and readiness' },
  { path: '/twin', label: 'Digital twin', roles: ['port_controller', 'weighbridge_operator', 'auditor', 'regulator_readonly', 'transporter_admin', 'dispatcher'], description: '3D port scene driven by live events' },
  { path: '/admin', label: 'Admin', roles: [], description: 'Users, stations, integrations, ledger, agents' },
];

export function routesFor(roles: Role[]): RouteDef[] {
  if (roles.includes('platform_admin')) return ROUTES;
  return ROUTES.filter((r) => r.roles.some((x) => roles.includes(x)));
}

/** Landing route after login. */
export function homeFor(roles: Role[]): string {
  if (roles.includes('platform_admin')) return '/admin';
  const order: Role[] = ['port_controller', 'weighbridge_operator', 'transporter_admin', 'dispatcher', 'driver', 'cargo_owner', 'warehouse_manager', 'auditor', 'regulator_readonly'];
  for (const r of order) if (roles.includes(r)) return routesFor([r])[0]?.path ?? '/';
  return '/';
}

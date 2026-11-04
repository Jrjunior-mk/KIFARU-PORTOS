import { type FormEvent, useEffect, useMemo, useState } from 'react';
import { admin as adminApi, fleet as fleetApi, integrations as integrationsApi, stations as stationsApi } from '../api/endpoints';
import { ALL_ROLES, type IncidentIn, type LaneIn, type Role, type StationIn, type StationOut, type UserIn, type UserOut } from '../api/types';
import { Badge, Card, Confirm, Empty, ErrorBanner, Field, KV, Notice, Spinner, Stat, StatusDot, Table, Tabs, Toggle } from '../components/ui';
import { useLiveEvents } from '../hooks/useLiveEvents';
import { useMutation, useQuery } from '../hooks/useQuery';
import { fmtAgo, fmtDateTime, short, titleCase } from '../lib/format';

type Tab = 'users' | 'stations' | 'calibration' | 'integrations' | 'incidents' | 'audit' | 'ledger' | 'health' | 'agents';

export default function Admin() {
  const [tab, setTab] = useState<Tab>('users');
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Platform administration</h1>
      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'users', label: 'Users' }, { id: 'stations', label: 'Stations & lanes' }, { id: 'calibration', label: 'Calibration' }, { id: 'integrations', label: 'Integrations' }, { id: 'incidents', label: 'Incidents' }, { id: 'audit', label: 'Audit log' }, { id: 'ledger', label: 'Ledger' }, { id: 'health', label: 'System health' }, { id: 'agents', label: 'AI agents' }]} />
      {tab === 'users' && <Users />}
      {tab === 'stations' && <Stations />}
      {tab === 'calibration' && <Calibration />}
      {tab === 'integrations' && <Integrations />}
      {tab === 'incidents' && <IncidentsAdmin />}
      {tab === 'audit' && <Audit />}
      {tab === 'ledger' && <Ledger />}
      {tab === 'health' && <Health />}
      {tab === 'agents' && <Agents />}
    </div>
  );
}

function Users() {
  const usersQ = useQuery(() => adminApi.users(), []);
  const orgsQ = useQuery(() => fleetApi.orgs(), []);
  const rolesQ = useQuery(() => adminApi.roles(), []);
  const roles = (rolesQ.data as Role[] | undefined) ?? ALL_ROLES;
  const [form, setForm] = useState<UserIn>({ email: '', password: '', full_name: '', org_id: null, roles: ['cargo_owner'], phone: '' });
  const create = useMutation((b: UserIn) => adminApi.createUser(b));
  const patch = useMutation((a: { id: string; body: import('../api/types').UserPatch }) => adminApi.patchUser(a.id, a.body));
  const [editing, setEditing] = useState<UserOut | null>(null);
  const [editRoles, setEditRoles] = useState<Role[]>([]);
  const fe = create.error?.fieldErrors ?? {};
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (await create.run({ ...form, org_id: form.org_id || null, phone: form.phone || null })) { setForm({ ...form, email: '', password: '', full_name: '' }); void usersQ.refetch(); }
  };
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="Users" subtitle="GET /admin/users" className="lg:col-span-2">
        <ErrorBanner error={usersQ.error ?? patch.error} />
        {usersQ.loading ? <Spinner /> : (
          <Table head={['Email', 'Name', 'Organisation', 'Roles', 'MFA', 'Active', 'Last login', '']} dense>
            {(usersQ.data ?? []).map((u) => (
              <tr key={u.id} className="tr">
                <td className="td">{u.email}</td><td className="td">{u.full_name}</td><td className="td">{u.org_name ?? '—'}</td>
                <td className="td"><div className="flex flex-wrap gap-1">{u.roles.map((r) => <Badge key={r} tone={r === 'platform_admin' ? 'violet' : 'slate'}>{r}</Badge>)}</div></td>
                <td className="td">{u.mfa_enabled ? <Badge tone="green">on</Badge> : <Badge tone="slate">off</Badge>}</td>
                <td className="td"><Toggle checked={u.is_active} label={u.is_active ? 'active' : 'disabled'} onChange={async (v) => { if (await patch.run({ id: u.id, body: { is_active: v } })) void usersQ.refetch(); }} /></td>
                <td className="td text-xs">{u.last_login_at ? fmtAgo(u.last_login_at) : 'never'}</td>
                <td className="td"><button className="btn-secondary px-2 py-1 text-xs" onClick={() => { setEditing(u); setEditRoles(u.roles); }}>Roles</button></td>
              </tr>
            ))}
          </Table>
        )}
        {editing && (
          <div className="mt-3 rounded border border-slate-200 p-3 dark:border-slate-800">
            <div className="mb-2 text-sm font-medium">Roles for {editing.email} · PATCH /admin/users/{'{id}'}</div>
            <div className="flex flex-wrap gap-2">{roles.map((r) => <Toggle key={r} label={r} checked={editRoles.includes(r)} onChange={(v) => setEditRoles(v ? [...editRoles, r] : editRoles.filter((x) => x !== r))} />)}</div>
            <div className="mt-2 flex gap-2"><button className="btn-primary text-xs" disabled={patch.busy} onClick={async () => { if (await patch.run({ id: editing.id, body: { roles: editRoles } })) { setEditing(null); void usersQ.refetch(); } }}>Save roles</button><button className="btn-secondary text-xs" onClick={() => setEditing(null)}>Cancel</button></div>
          </div>
        )}
      </Card>
      <Card title="Create user" subtitle="POST /admin/users">
        <form onSubmit={submit} className="space-y-2">
          <Field label="Email" required error={fe.email}>{(id) => <input id={id} type="email" className="input" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />}</Field>
          <Field label="Full name" required error={fe.full_name}>{(id) => <input id={id} className="input" required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />}</Field>
          <Field label="Password (min 10)" required error={fe.password}>{(id) => <input id={id} type="password" className="input" required minLength={10} autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />}</Field>
          <Field label="Phone" error={fe.phone}>{(id) => <input id={id} className="input" value={form.phone ?? ''} onChange={(e) => setForm({ ...form, phone: e.target.value })} />}</Field>
          <Field label="Organisation" error={fe.org_id}>{(id) => <select id={id} className="input" value={form.org_id ?? ''} onChange={(e) => setForm({ ...form, org_id: e.target.value || null })}><option value="">none (platform)</option>{(orgsQ.data ?? []).map((o) => <option key={o.id} value={o.id}>{o.name} ({o.type})</option>)}</select>}</Field>
          <fieldset><legend className="label">Roles</legend><div className="flex flex-wrap gap-2">{roles.map((r) => <Toggle key={r} label={r} checked={form.roles.includes(r)} onChange={(v) => setForm({ ...form, roles: v ? [...form.roles, r] : form.roles.filter((x) => x !== r) })} />)}</div>{fe.roles && <p className="text-xs text-rose-700">{fe.roles}</p>}</fieldset>
          <button className="btn-primary w-full" type="submit" disabled={create.busy || form.roles.length === 0}>Create user</button>
          <ErrorBanner error={create.error} />
          {create.result && <Notice tone="ok">Created {create.result.email}</Notice>}
        </form>
      </Card>
    </div>
  );
}

function Stations() {
  const q = useQuery(() => stationsApi.list(), []);
  const [form, setForm] = useState<StationIn>({ code: '', name: '', lat: -3.86, lon: 39.47, capacity_per_hour: 120, static_capacity_per_hour: 40, alt_allowed: false });
  const create = useMutation((b: StationIn) => stationsApi.create(b));
  const [laneFor, setLaneFor] = useState<string>('');
  const [lane, setLane] = useState<LaneIn>({ lane_no: 3, type: 'wim_highspeed', direction: 'inbound', device_id: '' });
  const createLane = useMutation((a: { st: string; body: LaneIn }) => stationsApi.createLane(a.st, a.body));
  const fe = create.error?.fieldErrors ?? {};
  const fl = createLane.error?.fieldErrors ?? {};
  useEffect(() => { if (!laneFor && q.data?.[0]) setLaneFor(q.data[0].id); }, [q.data, laneFor]);
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="Stations, lanes and sensors" subtitle="GET /stations" className="lg:col-span-2">
        <ErrorBanner error={q.error} />
        {q.loading ? <Spinner /> : (q.data ?? []).map((s: StationOut) => (
          <details key={s.id} className="mb-2 rounded border border-slate-200 p-2 dark:border-slate-800">
            <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-sm"><StatusDot status={s.status} /><span className="font-semibold">{s.code}</span> {s.name} <span className="text-xs text-slate-500">{s.lat}, {s.lon} · {s.capacity_per_hour}/h WIM · {s.static_capacity_per_hour}/h static · {s.alt_allowed ? 'alt route allowed' : 'no alt route'} · {s.lanes.length} lanes</span></summary>
            <Table head={['Lane', 'Type', 'Direction', 'Status', 'Device', 'Calibration valid to', 'Sensors']} dense>
              {s.lanes.map((l) => <tr key={l.id} className="tr"><td className="td">{l.lane_no}</td><td className="td">{titleCase(l.type)}</td><td className="td">{l.direction}</td><td className="td"><StatusDot status={l.status} /> {l.status}</td><td className="td mono">{l.device_id ?? '—'}</td><td className="td">{l.calibration_valid_to ? fmtDateTime(l.calibration_valid_to) : <span className="text-rose-600">none</span>}</td><td className="td text-xs">{l.sensors.length} ({l.sensors.filter((x) => x.status !== 'ok').length} not ok)</td></tr>)}
            </Table>
          </details>
        ))}
      </Card>
      <div className="space-y-4">
        <Card title="Create station" subtitle="POST /stations">
          <form className="grid grid-cols-2 gap-2" onSubmit={async (e) => { e.preventDefault(); if (await create.run(form)) { void q.refetch(); } }}>
            <Field label="Code" required error={fe.code}>{(id) => <input id={id} className="input" required minLength={2} maxLength={16} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} />}</Field>
            <Field label="Name" required error={fe.name}>{(id) => <input id={id} className="input" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />}</Field>
            <Field label="Lat" error={fe.lat}>{(id) => <input id={id} type="number" step="any" className="input" value={form.lat} onChange={(e) => setForm({ ...form, lat: Number(e.target.value) })} />}</Field>
            <Field label="Lon" error={fe.lon}>{(id) => <input id={id} type="number" step="any" className="input" value={form.lon} onChange={(e) => setForm({ ...form, lon: Number(e.target.value) })} />}</Field>
            <Field label="WIM cap/h" error={fe.capacity_per_hour}>{(id) => <input id={id} type="number" className="input" value={form.capacity_per_hour} onChange={(e) => setForm({ ...form, capacity_per_hour: Number(e.target.value) })} />}</Field>
            <Field label="Static cap/h" error={fe.static_capacity_per_hour}>{(id) => <input id={id} type="number" className="input" value={form.static_capacity_per_hour} onChange={(e) => setForm({ ...form, static_capacity_per_hour: Number(e.target.value) })} />}</Field>
            <div className="col-span-2"><Toggle label="Alternate route allowed" checked={form.alt_allowed} onChange={(v) => setForm({ ...form, alt_allowed: v })} /></div>
            <div className="col-span-2"><button className="btn-primary w-full" type="submit" disabled={create.busy}>Create station</button><ErrorBanner error={create.error} className="mt-2" />{create.result && <Notice tone="ok" className="mt-2">Created {create.result.code}</Notice>}</div>
          </form>
        </Card>
        <Card title="Create lane" subtitle="POST /stations/{id}/lanes · WIM lanes get the default 13-sensor set">
          <form className="grid grid-cols-2 gap-2" onSubmit={async (e) => { e.preventDefault(); if (await createLane.run({ st: laneFor, body: { ...lane, device_id: lane.device_id || null } })) void q.refetch(); }}>
            <div className="col-span-2"><Field label="Station">{(id) => <select id={id} className="input" value={laneFor} onChange={(e) => setLaneFor(e.target.value)}>{(q.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}</select>}</Field></div>
            <Field label="Lane no" error={fl.lane_no}>{(id) => <input id={id} type="number" min={1} max={20} className="input" value={lane.lane_no} onChange={(e) => setLane({ ...lane, lane_no: Number(e.target.value) })} />}</Field>
            <Field label="Type" error={fl.type}>{(id) => <select id={id} className="input" value={lane.type} onChange={(e) => setLane({ ...lane, type: e.target.value as LaneIn['type'] })}><option value="wim_highspeed">WIM high-speed</option><option value="wim_lowspeed">WIM low-speed</option><option value="static">Static</option></select>}</Field>
            <Field label="Direction" error={fl.direction}>{(id) => <select id={id} className="input" value={lane.direction} onChange={(e) => setLane({ ...lane, direction: e.target.value })}><option>inbound</option><option>outbound</option></select>}</Field>
            <Field label="Device ID" error={fl.device_id}>{(id) => <input id={id} className="input" value={lane.device_id ?? ''} onChange={(e) => setLane({ ...lane, device_id: e.target.value })} placeholder="gw-xxx-l3" />}</Field>
            <div className="col-span-2"><button className="btn-primary w-full" type="submit" disabled={createLane.busy || !laneFor}>Create lane</button><ErrorBanner error={createLane.error} className="mt-2" />{createLane.result && <Notice tone="ok" className="mt-2">Lane {createLane.result.lane_no} created with {createLane.result.sensors.length} sensors</Notice>}</div>
          </form>
        </Card>
      </div>
    </div>
  );
}

function Calibration() {
  const q = useQuery(() => stationsApi.list(), []);
  const sensors = useMemo(() => (q.data ?? []).flatMap((s) => s.lanes.flatMap((l) => l.sensors.filter((x) => ['piezo_quartz', 'piezo_polymer', 'bending_plate', 'strain_gauge'].includes(x.kind)).map((x) => ({ ...x, station: s.code, lane: l.lane_no })))), [q.data]);
  const [sensorId, setSensorId] = useState('');
  useEffect(() => { if (!sensorId && sensors[0]) setSensorId(sensors[0].id); }, [sensors, sensorId]);
  const cal = useQuery(() => stationsApi.calibrations(sensorId), [sensorId], { enabled: !!sensorId });
  return (
    <Card title="Calibration records" subtitle="GET /stations/sensors/{id}/calibrations · records are added from the Weighbridge console" actions={<select className="input w-auto py-1 text-xs" aria-label="Load sensor" value={sensorId} onChange={(e) => setSensorId(e.target.value)}>{sensors.map((s) => <option key={s.id} value={s.id}>{s.station} L{s.lane} · {titleCase(s.kind)} ch{s.channel} {s.calibration_valid_to ? '' : '(no cal)'}</option>)}</select>}>
      <ErrorBanner error={q.error ?? cal.error} />
      <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Load sensors" value={sensors.length} /><Stat label="With valid calibration" value={sensors.filter((s) => s.calibration_valid_to && new Date(s.calibration_valid_to) > new Date()).length} tone="teal" /><Stat label="Expired" value={sensors.filter((s) => s.calibration_valid_to && new Date(s.calibration_valid_to) <= new Date()).length} /><Stat label="Never calibrated" value={sensors.filter((s) => !s.calibration_valid_to).length} />
      </div>
      {cal.loading ? <Spinner /> : (cal.data ?? []).length === 0 ? <Empty>No calibration records for this sensor</Empty> : (
        <Table head={['Valid from', 'Valid to', 'Method', 'Ref mass', 'Gain', 'Offset', 'Temp coeff', 'U %', 'Notes']} dense>
          {(cal.data ?? []).map((c) => <tr key={c.id} className="tr"><td className="td">{fmtDateTime(c.valid_from)}</td><td className="td">{fmtDateTime(c.valid_to)}</td><td className="td">{titleCase(c.method)}</td><td className="td">{c.reference_mass_kg ?? '—'}</td><td className="td">{c.gain}</td><td className="td">{c.offset}</td><td className="td">{c.temp_coeff_per_c}</td><td className="td">{c.uncertainty_pct}</td><td className="td text-xs">{c.notes ?? ''}</td></tr>)}
        </Table>
      )}
    </Card>
  );
}

function Integrations() {
  const q = useQuery(() => integrationsApi.list(), []);
  const mode = useMutation((a: { name: string; mode: 'mock' | 'real'; base_url: string | null }) => integrationsApi.setMode(a.name, { mode: a.mode, base_url: a.base_url }));
  const health = useMutation((name: string) => integrationsApi.health(name));
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [confirmReal, setConfirmReal] = useState<string | null>(null);
  return (
    <Card title="External integrations" subtitle="GET /integrations · mode mock/real per adapter · health check">
      <Notice tone="warn">No government endpoint is fabricated: adapters stay in <b>mock</b> mode until a base URL is configured here and credentials are supplied via environment (KIFARU_INT_&lt;NAME&gt;_TOKEN).</Notice>
      <ErrorBanner error={q.error ?? mode.error ?? health.error} className="mt-2" />
      {q.loading ? <Spinner /> : (
        <Table head={['Adapter', 'Contract', 'Mode', 'Base URL', 'Health', 'Actions']} dense>
          {(q.data ?? []).map((i) => (
            <tr key={i.id} className="tr">
              <td className="td font-medium">{i.display_name}<div className="mono text-slate-500">{i.name}</div></td>
              <td className="td max-w-xs text-xs text-slate-600 dark:text-slate-300">{i.contract}</td>
              <td className="td"><Badge tone={i.mode === 'real' ? 'teal' : 'slate'}>{i.mode}</Badge></td>
              <td className="td"><input className="input w-48 py-1 text-xs" aria-label={`Base URL for ${i.name}`} placeholder={i.base_url ?? 'https://…'} value={urls[i.name] ?? ''} onChange={(e) => setUrls({ ...urls, [i.name]: e.target.value })} /></td>
              <td className="td"><Badge tone={i.health_status === 'ok' || i.health_status === 'mock' ? 'green' : i.health_status === 'down' ? 'red' : 'amber'}>{i.health_status}</Badge><div className="text-[11px] text-slate-500">{i.last_ok_at ? `ok ${fmtAgo(i.last_ok_at)}` : ''}{i.last_error ? ` · ${i.last_error}` : ''}</div></td>
              <td className="td"><div className="flex flex-wrap gap-1">
                {i.mode === 'mock' ? <button className="btn-secondary px-2 py-1 text-xs" disabled={mode.busy} onClick={() => setConfirmReal(i.name)}>Switch to real</button> : <button className="btn-secondary px-2 py-1 text-xs" disabled={mode.busy} onClick={async () => { if (await mode.run({ name: i.name, mode: 'mock', base_url: null })) void q.refetch(); }}>Switch to mock</button>}
                <button className="btn-secondary px-2 py-1 text-xs" disabled={health.busy} onClick={async () => { if (await health.run(i.name)) void q.refetch(); }}>Health check</button>
              </div></td>
            </tr>
          ))}
        </Table>
      )}
      <Confirm open={!!confirmReal} title={`Switch ${confirmReal} to real mode?`} body={<span>Base URL: <span className="mono">{(confirmReal && urls[confirmReal]) || (q.data?.find((x) => x.name === confirmReal)?.base_url ?? 'none — the server will reject this')}</span>. Real calls will be made to this endpoint.</span>} confirmLabel="Switch to real" danger onCancel={() => setConfirmReal(null)}
        onConfirm={async () => { const n = confirmReal!; setConfirmReal(null); if (await mode.run({ name: n, mode: 'real', base_url: urls[n] || null })) void q.refetch(); }} />
    </Card>
  );
}

function IncidentsAdmin() {
  const [status, setStatus] = useState<'open' | 'closed'>('open');
  const q = useQuery(() => adminApi.incidents(status), [status]);
  const stationsQ = useQuery(() => stationsApi.list(), []);
  const close = useMutation((id: string) => adminApi.closeIncident(id));
  const [form, setForm] = useState<IncidentIn>({ severity: 'medium', category: 'other', title: '', station_id: null, details: {} });
  const create = useMutation((b: IncidentIn) => adminApi.openIncident(b));
  useLiveEvents(['incident.opened', 'station.failure'], null, 20, () => void q.refetch());
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card title="Incidents" subtitle="GET /admin/incidents" className="lg:col-span-2" actions={<select className="input w-auto py-1 text-xs" aria-label="Status filter" value={status} onChange={(e) => setStatus(e.target.value as 'open' | 'closed')}><option value="open">open</option><option value="closed">closed</option></select>}>
        <ErrorBanner error={q.error ?? close.error} />
        {q.loading ? <Spinner /> : (q.data ?? []).length === 0 ? <Empty>No {status} incidents</Empty> : (
          <Table head={['Opened', 'Severity', 'Category', 'Title', 'Station', 'By', 'Closed', '']} dense>
            {(q.data ?? []).map((i) => <tr key={i.id} className="tr"><td className="td">{fmtDateTime(i.opened_at)}</td><td className="td"><Badge tone={i.severity === 'critical' || i.severity === 'high' ? 'red' : i.severity === 'medium' ? 'amber' : 'slate'}>{i.severity}</Badge></td><td className="td">{titleCase(i.category)}</td><td className="td">{i.title}{Object.keys(i.details).length > 0 && <div className="mono text-slate-500">{JSON.stringify(i.details)}</div>}</td><td className="td">{stationsQ.data?.find((s) => s.id === i.station_id)?.code ?? '—'}</td><td className="td text-xs">{i.raised_by}</td><td className="td">{i.closed_at ? fmtDateTime(i.closed_at) : '—'}</td><td className="td">{i.status === 'open' && <button className="btn-secondary px-2 py-1 text-xs" disabled={close.busy} onClick={async () => { if (await close.run(i.id)) void q.refetch(); }}>Close</button>}</td></tr>)}
          </Table>
        )}
      </Card>
      <Card title="Open incident" subtitle="POST /admin/incidents">
        <form className="space-y-2" onSubmit={async (e) => { e.preventDefault(); if (await create.run({ ...form, station_id: form.station_id || null })) { setForm({ ...form, title: '' }); void q.refetch(); } }}>
          <Field label="Title" required error={create.error?.fieldErrors.title}>{(id) => <input id={id} className="input" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />}</Field>
          <Field label="Station">{(id) => <select id={id} className="input" value={form.station_id ?? ''} onChange={(e) => setForm({ ...form, station_id: e.target.value || null })}><option value="">Network</option>{(stationsQ.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}</select>}</Field>
          <Field label="Severity">{(id) => <select id={id} className="input" value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value as IncidentIn['severity'] })}>{['low', 'medium', 'high', 'critical'].map((s) => <option key={s}>{s}</option>)}</select>}</Field>
          <Field label="Category">{(id) => <select id={id} className="input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as IncidentIn['category'] })}>{['station_failure', 'sensor_fault', 'security', 'traffic', 'cargo_anomaly', 'other'].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}</select>}</Field>
          <button className="btn-primary w-full" type="submit" disabled={create.busy}>Open incident</button>
          <ErrorBanner error={create.error} />
        </form>
      </Card>
    </div>
  );
}

function Audit() {
  const [entity, setEntity] = useState('');
  const q = useQuery(() => adminApi.audit({ entity: entity || undefined, limit: 200 }), [entity]);
  return (
    <Card title="Audit log" subtitle="GET /admin/audit — every privileged write" actions={<input className="input w-40 py-1 text-xs" aria-label="Filter by entity" placeholder="entity e.g. user" value={entity} onChange={(e) => setEntity(e.target.value)} />}>
      <ErrorBanner error={q.error} />
      {q.loading ? <Spinner /> : (q.data ?? []).length === 0 ? <Empty>No audit events</Empty> : (
        <Table head={['At', 'Actor', 'Action', 'Entity', 'Entity id', 'Before → after']} dense>
          {(q.data ?? []).map((a) => <tr key={a.id} className="tr"><td className="td whitespace-nowrap">{fmtDateTime(a.at)}</td><td className="td mono">{short(a.actor_user_id, 10)}</td><td className="td">{a.action}</td><td className="td">{a.entity}</td><td className="td mono">{short(a.entity_id, 10)}</td><td className="td mono max-w-md truncate" title={JSON.stringify({ before: a.before, after: a.after })}>{a.before ? JSON.stringify(a.before) + ' → ' : ''}{a.after ? JSON.stringify(a.after) : ''}</td></tr>)}
        </Table>
      )}
    </Card>
  );
}

function Ledger() {
  const [type, setType] = useState('');
  const q = useQuery(() => adminApi.ledger({ limit: 100, type: type || undefined }), [type]);
  const verify = useMutation(() => adminApi.ledgerVerify());
  return (
    <Card title="Signed event ledger (tail)" subtitle="GET /admin/ledger · hash-chained, Ed25519-signed" actions={<><input className="input w-40 py-1 text-xs" aria-label="Filter by type" placeholder="type e.g. clearance.decided" value={type} onChange={(e) => setType(e.target.value)} /><button className="btn-primary text-xs" disabled={verify.busy} onClick={() => void verify.run()}>{verify.busy ? 'Verifying…' : 'Verify chain'}</button></>}>
      {verify.result && (
        <Notice tone={verify.result.ok ? 'ok' : 'warn'} className="mb-3">
          {verify.result.ok ? `Chain OK — ${verify.result.checked} of ${verify.result.total} events verified. Head ${short(verify.result.head_hash, 16)}` : `CHAIN BROKEN — ${verify.result.error} (checked ${verify.result.checked})`} · signer {verify.result.signer_key_id} · public key <span className="mono">{short(verify.result.public_key, 20)}</span>
        </Notice>
      )}
      <ErrorBanner error={q.error ?? verify.error} />
      {q.loading ? <Spinner /> : (q.data ?? []).length === 0 ? <Empty>Ledger is empty</Empty> : (
        <Table head={['Seq', 'Occurred', 'Type', 'Producer', 'Station', 'Payload', 'Hash']} dense>
          {(q.data ?? []).map((e) => <tr key={e.event_id} className="tr"><td className="td tabular-nums">{e.seq}</td><td className="td whitespace-nowrap">{fmtDateTime(e.occurred_at)}</td><td className="td">{e.type}</td><td className="td text-xs">{e.producer}</td><td className="td mono">{short(e.station_id, 8)}</td><td className="td mono max-w-sm truncate" title={JSON.stringify(e.payload)}>{JSON.stringify(e.payload)}</td><td className="td mono" title={`prev ${e.prev_hash}`}>{short(e.hash, 12)}</td></tr>)}
        </Table>
      )}
    </Card>
  );
}

function Health() {
  const q = useQuery(() => adminApi.systemHealth(), [], { pollMs: 15_000 });
  if (q.error) return <ErrorBanner error={q.error} />;
  if (!q.data) return <Spinner />;
  const h = q.data;
  return (
    <Card title="System health" subtitle="GET /admin/system/health · refreshes every 15 s">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Database" value={<span className="flex items-center gap-2"><StatusDot status={h.database === 'ok' ? 'ok' : 'fault'} />{h.database}</span>} hint={h.database_kind} />
        <Stat label="Weighings last hour" value={h.weighings_last_hour} />
        <Stat label="WS subscribers" value={h.ws_subscribers} />
        <Stat label="Recent events (bus)" value={h.events_recent} />
      </div>
      <div className="mt-3"><KV items={[['Environment', h.env], ['API version', h.version], ['Redis', h.redis], ['MQTT', h.mqtt], ['Signing key', <span className="mono">{h.signing_key_id}</span>]]} /></div>
    </Card>
  );
}

function Agents() {
  const q = useQuery(() => adminApi.agents(), []);
  if (q.error) return <ErrorBanner error={q.error} />;
  if (!q.data) return <Spinner />;
  return (
    <div className="space-y-4">
      <Notice>{q.data.policy}</Notice>
      <div className="grid gap-3 md:grid-cols-2">
        {q.data.agents.map((a) => (
          <Card key={a.name} title={<span>{a.name} <Badge tone="slate">v{a.version}</Badge></span>} subtitle={a.responsibilities}>
            <div className="grid gap-2 text-xs sm:grid-cols-2">
              <div><div className="label">Inputs</div><ul className="space-y-0.5">{Object.entries(a.inputs).map(([k, v]) => <li key={k}><span className="mono">{k}</span> — {v}</li>)}</ul></div>
              <div><div className="label">Outputs</div><ul className="space-y-0.5">{Object.entries(a.outputs).map(([k, v]) => <li key={k}><span className="mono">{k}</span> — {v}</li>)}</ul></div>
            </div>
          </Card>
        ))}
      </div>
      <Card title="Pipelines" subtitle="Agent compositions triggered by platform events">
        <Table head={['Pipeline', 'Agents in order']} dense>{Object.entries(q.data.pipelines).map(([k, v]) => <tr key={k} className="tr"><td className="td font-medium">{k}</td><td className="td">{v.join(' → ')}</td></tr>)}</Table>
      </Card>
    </div>
  );
}

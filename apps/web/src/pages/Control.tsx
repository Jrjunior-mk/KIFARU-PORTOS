import { lazy, Suspense, useEffect, useMemo, useState, type FormEvent } from 'react';
import { Area, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { admin as adminApi, environment as envApi, fleet as fleetApi, queue as queueApi, stations as stationsApi, weighing as weighingApi } from '../api/endpoints';
import type { IncidentCategory, IncidentIn, LiveEvent, QueueOut, StationOut } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Badge, Card, DecisionBadge, Empty, ErrorBanner, Field, Notice, SourceBadge, Spinner, Stat, StatusDot, Table } from '../components/ui';
import { eventSource, useLiveEvents } from '../hooks/useLiveEvents';
import { useMutation, useQuery } from '../hooks/useQuery';
import { chartTheme, DECISION_COLOR, SERIES, useDarkMode } from '../lib/chart';
import { fmtAgo, fmtDateTime, fmtDuration, fmtKg, fmtNum, fmtPct, fmtTime, titleCase } from '../lib/format';

const StationMap = lazy(() => import('../components/StationMap'));
const LIVE_TYPES = ['clearance.decided', 'queue.updated', 'station.failure', 'incident.opened', 'sensor.health', 'truck.diverted', 'truck.released'];

export default function Control() {
  const { hasRole } = useAuth();
  const canAct = hasRole('port_controller', 'platform_admin');
  const stationsQ = useQuery(() => stationsApi.list(), [], { pollMs: 30_000 });
  const vehiclesQ = useQuery(() => fleetApi.vehicles(), [], { pollMs: 60_000 });
  const statsQ = useQuery(() => weighingApi.stats(), [], { pollMs: 30_000 });
  const incidentsQ = useQuery(() => adminApi.incidents('open'), [], { pollMs: 60_000 });
  const envQ = useQuery(() => envApi.report({ hours: 24 }), [], { pollMs: 120_000 });
  const [selected, setSelected] = useState<string | null>(null);

  const live = useLiveEvents(LIVE_TYPES, null, 200, (ev: LiveEvent) => {
    if (ev.type === 'clearance.decided' || ev.type === 'queue.updated') { void stationsQ.refetch(); void statsQ.refetch(); }
    if (ev.type === 'station.failure' || ev.type === 'incident.opened') { void incidentsQ.refetch(); void stationsQ.refetch(); }
  });
  const feed = useMemo(() => live.events.filter((e) => e.type === 'clearance.decided').slice().reverse(), [live.events]);
  useEffect(() => { if (!selected && stationsQ.data?.length) setSelected(stationsQ.data[0].id); }, [stationsQ.data, selected]);
  const stations = stationsQ.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h1 className="text-xl font-semibold">Port Control Centre</h1><p className="text-sm text-slate-500">Network view · {stations.length} stations · live feed {live.status}</p></div>
        <div className="flex items-center gap-2 text-xs">
          <Badge tone={live.status === 'open' ? 'teal' : 'amber'}>WS {live.status}</Badge>
          <Badge tone={live.hasLive ? 'teal' : 'slate'}>{live.hasLive ? 'live measurements seen' : 'no live measurements — simulated data only'}</Badge>
        </div>
      </div>
      <ErrorBanner error={stationsQ.error} />

      <section aria-label="Stations" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {stationsQ.loading && <Spinner label="Loading stations" />}
        {stations.map((s) => <StationCard key={s.id} s={s} selected={selected === s.id} onSelect={() => setSelected(s.id)} canAct={canAct} onChanged={() => void stationsQ.refetch()} />)}
      </section>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title="Live clearance feed" subtitle="clearance.decided events over WebSocket" className="lg:col-span-1">
          {feed.length === 0 ? <Empty>No clearance events yet in this session. Trigger passes from the Weighbridge console.</Empty> : (
            <ul className="max-h-[420px] space-y-1 overflow-y-auto" aria-live="polite">
              {feed.slice(0, 60).map((e) => {
                const p = e.payload as { decision?: 'GREEN' | 'AMBER' | 'RED'; plate?: string | null; gvm_kg?: number; latency_ms?: number; rules_fired?: string[] };
                const st = stations.find((x) => x.id === e.station_id);
                return (
                  <li key={e.event_id} className="flex items-start gap-2 rounded border border-slate-100 px-2 py-1 text-xs dark:border-slate-800">
                    <DecisionBadge decision={p.decision} size="sm" />
                    <div className="min-w-0 flex-1">
                      <div className="flex justify-between gap-2"><span className="font-medium">{p.plate ?? 'unknown plate'}</span><span className="text-slate-400">{fmtTime(e.occurred_at)}</span></div>
                      <div className="text-slate-500">{st?.code ?? e.station_id} · {fmtKg(p.gvm_kg)} · {p.latency_ms} ms {p.rules_fired?.length ? `· ${p.rules_fired.join(', ')}` : ''}</div>
                    </div>
                    <SourceBadge source={eventSource(e)} />
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
        <Card title="Stations and vehicle positions" subtitle="OpenStreetMap tiles · vehicle markers are last reported telematics positions" className="lg:col-span-2">
          <Suspense fallback={<Spinner label="Loading map" />}>
            <StationMap stations={stations} vehicles={vehiclesQ.data ?? []} height={380} />
          </Suspense>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Queue forecast" subtitle="GET /queue/{station}/forecast · horizons +15/+30/+60/+120 min" actions={
          <select className="input w-auto py-1 text-xs" aria-label="Station for forecast" value={selected ?? ''} onChange={(e) => setSelected(e.target.value)}>
            {stations.map((s) => <option key={s.id} value={s.id}>{s.code} — {s.name}</option>)}
          </select>}>
          {selected ? <ForecastChart stationId={selected} refreshKey={live.events.length} /> : <Spinner />}
        </Card>
        <Card title="Weighing statistics" subtitle="GET /weighing/stats — all stations, all time">
          {statsQ.data ? <StatsPanel stats={statsQ.data} /> : <Spinner />}
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Incidents" subtitle="Open incidents across the network" actions={<Badge tone={(incidentsQ.data?.length ?? 0) ? 'red' : 'green'}>{incidentsQ.data?.length ?? 0} open</Badge>}>
          <Incidents stations={stations} canAct={canAct} q={incidentsQ} onChanged={() => { void incidentsQ.refetch(); void stationsQ.refetch(); }} />
        </Card>
        <Card title="Environmental summary (modelled)" subtitle="GET /environment/report · last 24 h · estimates from the environmental agent, not measurements">
          {envQ.error && <ErrorBanner error={envQ.error} />}
          {envQ.data ? (
            <div className="space-y-3">
              <Notice tone="warn">MODELLED ESTIMATE — {envQ.data.label}. Confidence {fmtPct(envQ.data.agent_confidence)}.</Notice>
              <div className="grid grid-cols-3 gap-2">
                <Stat label="Fuel avoided" value={`${fmtNum(envQ.data.savings.litres, 0)} L`} tone="teal" hint="modelled" />
                <Stat label="CO₂ avoided" value={`${fmtNum(envQ.data.savings.co2_kg, 0)} kg`} tone="teal" hint="modelled" />
                <Stat label="Cost avoided" value={`KES ${fmtNum(envQ.data.savings.cost_kes, 0)}`} tone="teal" hint="modelled" />
              </div>
              <EnvCompareChart baseline={envQ.data.baseline} platform={envQ.data.platform} />
              <details className="text-xs text-slate-600 dark:text-slate-300">
                <summary className="cursor-pointer">Inputs and assumptions</summary>
                <ul className="mt-1 list-inside list-disc">
                  {Object.entries(envQ.data.inputs).map(([k, v]) => <li key={k}>{titleCase(k)}: {fmtNum(v, 1)}</li>)}
                  {envQ.data.assumptions.map((a) => <li key={a}>{a}</li>)}
                </ul>
              </details>
            </div>
          ) : !envQ.error && <Spinner />}
        </Card>
      </div>
    </div>
  );
}

function StationCard({ s, selected, onSelect, canAct, onChanged }: { s: StationOut; selected: boolean; onSelect: () => void; canAct: boolean; onChanged: () => void }) {
  const setStatus = useMutation((status: 'operational' | 'degraded' | 'offline') => stationsApi.setStatus(s.id, { status, reason: status === 'operational' ? null : 'set from control centre' }));
  const d = s.decisions_last_hour;
  const total = d.GREEN + d.AMBER + d.RED;
  return (
    <article className={`card p-3 ${selected ? 'ring-2 ring-brand-500' : ''}`}>
      <button className="flex w-full items-start justify-between text-left" onClick={onSelect} aria-pressed={selected}>
        <div><div className="text-xs text-slate-500">{s.code}</div><div className="font-semibold leading-tight">{s.name}</div></div>
        <span className="flex items-center gap-1 text-xs"><StatusDot status={s.status} />{s.status}</span>
      </button>
      <div className="mt-2 grid grid-cols-3 gap-1 text-center">
        <div><div className="text-lg font-semibold tabular-nums">{s.queue_len}</div><div className="text-[10px] uppercase text-slate-500">queue</div></div>
        <div><div className="text-lg font-semibold tabular-nums">{fmtDuration(s.avg_wait_s)}</div><div className="text-[10px] uppercase text-slate-500">avg wait</div></div>
        <div><div className="text-lg font-semibold tabular-nums">{fmtPct(s.utilisation)}</div><div className="text-[10px] uppercase text-slate-500">utilisation</div></div>
      </div>
      <div className="mt-2">
        <div className="flex h-2 overflow-hidden rounded bg-slate-200 dark:bg-slate-800" aria-hidden="true">
          {total > 0 && (['GREEN', 'AMBER', 'RED'] as const).map((k) => <div key={k} style={{ width: `${(d[k] / total) * 100}%`, background: DECISION_COLOR[k] }} />)}
        </div>
        <div className="mt-1 flex justify-between text-[11px] text-slate-500"><span>last hour: <span className="text-decision-green">G {d.GREEN}</span> · <span className="text-decision-amber">A {d.AMBER}</span> · <span className="text-decision-red">R {d.RED}</span></span><span>{s.lanes.length} lanes</span></div>
      </div>
      {canAct && (
        <div className="mt-2 flex gap-1">
          {(['operational', 'degraded', 'offline'] as const).map((st) => (
            <button key={st} disabled={setStatus.busy || s.status === st} className="btn-secondary flex-1 px-1 py-1 text-[11px]" onClick={async () => { if (await setStatus.run(st)) onChanged(); }}>{st}</button>
          ))}
        </div>
      )}
      <ErrorBanner error={setStatus.error} className="mt-2" />
    </article>
  );
}

function ForecastChart({ stationId, refreshKey }: { stationId: string; refreshKey: number }) {
  const dark = useDarkMode();
  const t = chartTheme(dark);
  const fc = useQuery(() => queueApi.forecast(stationId), [stationId, Math.floor(refreshKey / 5)]);
  const hist = useQuery(() => queueApi.history(stationId, 6), [stationId, Math.floor(refreshKey / 5)]);
  if (fc.error) return <ErrorBanner error={fc.error} />;
  if (!fc.data || !hist.data) return <Spinner label="Forecasting" />;
  const rows = [
    ...hist.data.slice(-12).map((h: QueueOut) => ({ label: fmtTime(h.ts).slice(0, 5), observed: h.queue_len, kind: 'observed' })),
    ...fc.data.map((f) => ({ label: `+${f.kind.replace('forecast_', '')}m`, forecast: f.queue_len, band: [f.lower ?? f.queue_len, f.upper ?? f.queue_len], wait: f.avg_wait_s, kind: 'forecast' })),
  ];
  const model = fc.data[0]?.model_version ?? '—';
  return (
    <div>
      <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-slate-500"><Badge tone="violet">FORECAST</Badge> model {model} · band = lower/upper · observed points are {hist.data[0]?.source ?? 'n/a'}</div>
      <ResponsiveContainer width="100%" height={240}>
        <ComposedChart data={rows} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke={t.grid} vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11, fill: t.text }} stroke={t.axis} />
          <YAxis tick={{ fontSize: 11, fill: t.text }} stroke={t.axis} allowDecimals={false} />
          <Tooltip contentStyle={t.tooltip} formatter={(v: unknown, name: string) => (Array.isArray(v) ? [`${v[0]}–${v[1]}`, 'uncertainty band'] : [String(v), name === 'wait' ? 'wait (s)' : name])} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Area dataKey="band" name="band" fill={t.band} stroke="none" type="monotone" connectNulls={false} legendType="none" />
          <Line dataKey="observed" name="observed queue" stroke={SERIES.primary} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />
          <Line dataKey="forecast" name="forecast queue" stroke={SERIES.secondary} strokeWidth={2} strokeDasharray="5 3" dot={{ r: 4 }} connectNulls={false} />
        </ComposedChart>
      </ResponsiveContainer>
      <Table head={['Horizon', 'Queue', 'Band', 'Wait', 'Utilisation', 'Arrivals/h']} dense>
        {fc.data.map((f) => (
          <tr key={f.kind} className="tr"><td className="td">+{f.kind.replace('forecast_', '')} min</td><td className="td tabular-nums">{f.queue_len}</td><td className="td tabular-nums">{f.lower}–{f.upper}</td><td className="td">{fmtDuration(f.avg_wait_s)}</td><td className="td">{fmtPct(f.utilisation)}</td><td className="td tabular-nums">{fmtNum(f.arrivals_per_hour, 0)}</td></tr>
        ))}
      </Table>
    </div>
  );
}

function StatsPanel({ stats }: { stats: import('../api/types').StatsOut }) {
  const dark = useDarkMode();
  const t = chartTheme(dark);
  const data = (['GREEN', 'AMBER', 'RED'] as const).map((k) => ({ decision: k, count: stats.by_decision[k] ?? 0 }));
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Passes" value={stats.total} />
        <Stat label="GREEN rate" value={fmtPct(stats.green_rate)} tone="green" />
        <Stat label="Stops avoided" value={stats.stops_avoided} />
        <Stat label="Mean latency" value={`${fmtNum(stats.mean_latency_ms, 0)} ms`} hint="target ≤ 2000 ms" />
      </div>
      <ResponsiveContainer width="100%" height={160}>
        <BarChart data={data} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
          <CartesianGrid stroke={t.grid} vertical={false} />
          <XAxis dataKey="decision" tick={{ fontSize: 11, fill: t.text }} stroke={t.axis} />
          <YAxis tick={{ fontSize: 11, fill: t.text }} stroke={t.axis} allowDecimals={false} />
          <Tooltip contentStyle={t.tooltip} />
          <Bar dataKey="count" name="decisions" radius={[4, 4, 0, 0]} label={{ position: 'top', fontSize: 11, fill: t.text }}>
            {data.map((d) => <Cell key={d.decision} fill={DECISION_COLOR[d.decision]} />)}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <div className="flex flex-wrap gap-2 text-xs">by source: {Object.entries(stats.by_source).map(([s, c]) => <span key={s} className="inline-flex items-center gap-1"><SourceBadge source={s} /> {c}</span>)}{Object.keys(stats.by_source).length === 0 && <span className="text-slate-500">no records</span>}</div>
    </div>
  );
}

function EnvCompareChart({ baseline, platform }: { baseline: import('../api/types').EnvBundle; platform: import('../api/types').EnvBundle }) {
  const dark = useDarkMode();
  const t = chartTheme(dark);
  const rows = [
    { metric: 'Fuel (L)', baseline: baseline.litres, platform: platform.litres },
    { metric: 'CO₂ (kg)', baseline: baseline.co2_kg, platform: platform.co2_kg },
    { metric: 'Cost (kKES)', baseline: baseline.cost_kes / 1000, platform: platform.cost_kes / 1000 },
  ];
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={rows} margin={{ top: 8, right: 8, left: -12, bottom: 0 }} barGap={2}>
        <CartesianGrid stroke={t.grid} vertical={false} />
        <XAxis dataKey="metric" tick={{ fontSize: 11, fill: t.text }} stroke={t.axis} />
        <YAxis tick={{ fontSize: 11, fill: t.text }} stroke={t.axis} />
        <Tooltip contentStyle={t.tooltip} formatter={(v: number) => fmtNum(v, 1)} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        <Bar dataKey="baseline" name="baseline (all stop)" fill={SERIES.secondary} radius={[4, 4, 0, 0]} />
        <Bar dataKey="platform" name="with platform (modelled)" fill={SERIES.primary} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function Incidents({ stations, canAct, q, onChanged }: { stations: StationOut[]; canAct: boolean; q: ReturnType<typeof useQuery<import('../api/types').IncidentOut[]>>; onChanged: () => void }) {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<IncidentIn>({ severity: 'medium', category: 'traffic', title: '', station_id: null, details: {} });
  const create = useMutation((b: IncidentIn) => adminApi.openIncident(b));
  const close = useMutation((id: string) => adminApi.closeIncident(id));
  const [showClosed, setShowClosed] = useState(false);
  const closedQ = useQuery(() => adminApi.incidents('closed'), [showClosed], { enabled: showClosed });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (await create.run({ ...form, station_id: form.station_id || null })) { setShowForm(false); setForm({ ...form, title: '' }); onChanged(); }
  };
  const list = q.data ?? [];
  const fe = create.error?.fieldErrors ?? {};
  return (
    <div className="space-y-3">
      {q.error && <ErrorBanner error={q.error} />}
      {list.length === 0 && !q.loading && <Empty>No open incidents</Empty>}
      <ul className="space-y-1">
        {list.map((i) => (
          <li key={i.id} className="flex items-start justify-between gap-2 rounded border border-slate-100 px-2 py-1.5 text-sm dark:border-slate-800">
            <div>
              <div className="flex flex-wrap items-center gap-1"><Badge tone={i.severity === 'critical' || i.severity === 'high' ? 'red' : i.severity === 'medium' ? 'amber' : 'slate'}>{i.severity}</Badge><span className="font-medium">{i.title}</span></div>
              <div className="text-xs text-slate-500">{titleCase(i.category)} · {stations.find((s) => s.id === i.station_id)?.code ?? 'network'} · opened {fmtAgo(i.opened_at)} by {i.raised_by}</div>
            </div>
            {canAct && <button className="btn-secondary px-2 py-1 text-xs" disabled={close.busy} onClick={async () => { if (await close.run(i.id)) onChanged(); }}>Close</button>}
          </li>
        ))}
      </ul>
      <ErrorBanner error={close.error} />
      <div className="flex gap-2">
        {canAct && <button className="btn-secondary text-xs" onClick={() => setShowForm((s) => !s)}>{showForm ? 'Cancel' : 'Open incident'}</button>}
        <button className="btn-ghost text-xs" onClick={() => setShowClosed((s) => !s)}>{showClosed ? 'Hide closed' : 'Show closed'}</button>
      </div>
      {showForm && (
        <form onSubmit={submit} className="grid gap-2 rounded border border-slate-200 p-3 sm:grid-cols-2 dark:border-slate-800">
          <Field label="Title" required error={fe.title}>{(id) => <input id={id} className="input" required value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />}</Field>
          <Field label="Station">{(id) => <select id={id} className="input" value={form.station_id ?? ''} onChange={(e) => setForm({ ...form, station_id: e.target.value || null })}><option value="">Network-wide</option>{stations.map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}</select>}</Field>
          <Field label="Severity" error={fe.severity}>{(id) => <select id={id} className="input" value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value as IncidentIn['severity'] })}>{['low', 'medium', 'high', 'critical'].map((s) => <option key={s}>{s}</option>)}</select>}</Field>
          <Field label="Category" error={fe.category}>{(id) => <select id={id} className="input" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as IncidentCategory })}>{['station_failure', 'sensor_fault', 'security', 'traffic', 'cargo_anomaly', 'other'].map((s) => <option key={s} value={s}>{titleCase(s)}</option>)}</select>}</Field>
          <div className="sm:col-span-2 flex items-center gap-2"><button className="btn-primary" disabled={create.busy} type="submit">Open incident</button><ErrorBanner error={create.error} /></div>
        </form>
      )}
      {showClosed && (closedQ.data ? (
        <Table head={['Closed', 'Severity', 'Title', 'Station']} dense>
          {closedQ.data.slice(0, 20).map((i) => <tr key={i.id} className="tr"><td className="td">{fmtDateTime(i.closed_at)}</td><td className="td">{i.severity}</td><td className="td">{i.title}</td><td className="td">{stations.find((s) => s.id === i.station_id)?.code ?? '—'}</td></tr>)}
        </Table>
      ) : <Spinner />)}
    </div>
  );
}

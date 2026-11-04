import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { admin as adminApi, environment as envApi, stations as stationsApi, weighing as weighingApi } from '../api/endpoints';
import type { Decision, LiveEvent, StationOut, WeighingOut, WhatIfOut } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Badge, Card, Empty, ErrorBanner, Field, Notice, Spinner, Table } from '../components/ui';
import { eventSource, useLiveEvents } from '../hooks/useLiveEvents';
import { useMutation, useQuery } from '../hooks/useQuery';
import { fmtDuration, fmtNum, fmtPct, fmtTime } from '../lib/format';
import Scene, { type TwinIncident, type TwinStation, type TwinTruck } from '../twin/Scene';

const TWIN_TYPES = ['truck.detected', 'clearance.decided', 'queue.updated', 'incident.opened', 'station.failure'];
const MULTIPLIERS = [1, 1.2, 1.3, 1.5];

export default function Twin() {
  const { hasRole } = useAuth();
  const stationsQ = useQuery(() => stationsApi.list(), [], { pollMs: 30_000 });
  const incidentsQ = useQuery(() => adminApi.incidents('open'), [], { pollMs: 60_000 });
  const [trucks, setTrucks] = useState<TwinTruck[]>([]);
  const stations = stationsQ.data ?? [];
  const twinStations = useMemo<TwinStation[]>(() => stations.slice(0, 2).map((s, i) => ({ id: s.id, code: s.code, name: s.name, status: s.status, queue_len: s.queue_len, x: i, laneIds: s.lanes.map((l) => l.id) })), [stations]);
  const stationIdx = useCallback((stationId: string | null, laneId?: string | null) => {
    let i = twinStations.findIndex((s) => s.id === stationId);
    if (i < 0 && laneId) i = twinStations.findIndex((s) => s.laneIds.includes(laneId));
    return i < 0 ? 0 : i;
  }, [twinStations]);
  const stationsRef = useRef(stationIdx); stationsRef.current = stationIdx;

  const onEvent = useCallback((ev: LiveEvent) => {
    const p = ev.payload as { lane_id?: string; decision?: Decision; plate?: string | null; weighing_event_id?: string };
    if (ev.type === 'truck.detected') {
      setTrucks((ts) => [...ts.slice(-40), { id: ev.event_id, laneId: p.lane_id ?? null, stationIdx: stationsRef.current(ev.station_id, p.lane_id), decision: null, plate: null, spawnedAt: Date.now(), source: eventSource(ev) }]);
    } else if (ev.type === 'clearance.decided') {
      setTrucks((ts) => {
        const i = ts.findIndex((t) => t.decision === null && t.laneId === (p.lane_id ?? null));
        if (i >= 0) { const next = ts.slice(); next[i] = { ...next[i], decision: p.decision ?? null, plate: p.plate ?? null, source: eventSource(ev) }; return next; }
        return [...ts.slice(-40), { id: ev.event_id, laneId: p.lane_id ?? null, stationIdx: stationsRef.current(ev.station_id, p.lane_id), decision: p.decision ?? null, plate: p.plate ?? null, spawnedAt: Date.now(), source: eventSource(ev) }];
      });
    } else if (ev.type === 'queue.updated' || ev.type === 'station.failure') { void stationsQ.refetch(); if (ev.type === 'station.failure') void incidentsQ.refetch(); }
    else if (ev.type === 'incident.opened') void incidentsQ.refetch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const live = useLiveEvents(TWIN_TYPES, null, 200, onEvent);
  const onTruckDone = useCallback((id: string) => setTrucks((ts) => ts.filter((t) => t.id !== id)), []);
  const incidents = useMemo<TwinIncident[]>(() => (incidentsQ.data ?? []).map((i) => { const idx = twinStations.findIndex((s) => s.id === i.station_id); return { id: i.id, stationIdx: idx >= 0 ? idx : null, severity: i.severity, title: i.title }; }), [incidentsQ.data, twinStations]);
  const decidedCount = live.events.filter((e) => e.type === 'clearance.decided').length;

  return (
    <div className="space-y-3">
      <div role="status" className={`flex flex-wrap items-center justify-between gap-2 rounded-lg px-4 py-2 text-sm font-semibold ${live.hasLive ? 'bg-brand-600 text-white' : 'bg-amber-500 text-slate-950'}`}>
        <span>{live.hasLive ? 'LIVE — events carry source=live from station gateways' : 'SIMULATION MODE — data is simulated (no event with source=live has been received)'}</span>
        <span className="text-xs font-normal">WS {live.status} · {decidedCount} decisions this session · {trucks.length} trucks in scene · {twinStations.map((s) => `${s.code} q${s.queue_len}`).join(' · ')}</span>
      </div>
      <ErrorBanner error={stationsQ.error} />
      <div className="grid gap-3 xl:grid-cols-4">
        <div className="card overflow-hidden xl:col-span-3" style={{ height: 'min(70vh, 640px)' }} aria-label="3D digital twin of the port and weighing stations">
          {twinStations.length === 0 ? <div className="p-6"><Spinner label="Loading stations" /></div> : <Scene stations={twinStations} trucks={trucks} incidents={incidents} onTruckDone={onTruckDone} />}
        </div>
        <div className="space-y-3">
          <Card title="Legend">
            <ul className="space-y-1 text-xs">
              <li><span className="mr-2 inline-block h-3 w-3 rounded bg-slate-400" />Truck detected, awaiting decision</li>
              <li><span className="mr-2 inline-block h-3 w-3 rounded bg-decision-green" />GREEN — continues without stopping</li>
              <li><span className="mr-2 inline-block h-3 w-3 rounded bg-decision-amber" />AMBER — diverts to the static scale</li>
              <li><span className="mr-2 inline-block h-3 w-3 rounded bg-decision-red" />RED — diverts to inspection/holding</li>
              <li><span className="mr-2 inline-block h-3 w-3 rounded bg-slate-400 opacity-50" />Ghost trucks = observed queue length</li>
              <li>⚠ cone = open incident at the station</li>
            </ul>
            <p className="mt-2 text-[11px] text-slate-500">Scene shows the first two stations ({twinStations.map((s) => s.code).join(', ')}). Drag to orbit, wheel to zoom.</p>
          </Card>
          <Card title="Recent events">
            {live.events.length === 0 ? <Empty>No events yet</Empty> : (
              <ul className="max-h-48 space-y-0.5 overflow-y-auto text-[11px]">
                {live.events.slice(-30).reverse().map((e) => <li key={e.event_id} className="flex justify-between gap-2"><span>{e.type} {(e.payload as { decision?: string }).decision ?? ''} {(e.payload as { plate?: string }).plate ?? ''}</span><span className="text-slate-400">{fmtTime(e.occurred_at)}</span></li>)}
              </ul>
            )}
          </Card>
        </div>
      </div>
      {hasRole('port_controller', 'weighbridge_operator', 'platform_admin') ? <ScenarioPanel stations={stations} /> : <Notice>Scenario runs require the port controller or weighbridge operator role (they create simulated passes).</Notice>}
    </div>
  );
}

interface ScenarioRow { label: string; multiplier: number; count: number; mix: Record<Decision, number>; meanLatency: number; waitS: number; env: WhatIfOut | null; source: string }

function ScenarioPanel({ stations }: { stations: StationOut[] }) {
  const [stationId, setStationId] = useState('');
  const [laneId, setLaneId] = useState('');
  const [base, setBase] = useState(10);
  const [overload, setOverload] = useState(0.15);
  const [rows, setRows] = useState<ScenarioRow[]>([]);
  const [progress, setProgress] = useState<string | null>(null);
  const st = stations.find((s) => s.id === stationId);
  const lanes = (st?.lanes ?? []).filter((l) => l.type !== 'static');
  useEffect(() => { if (!stationId && stations[0]) setStationId(stations[0].id); }, [stations, stationId]);
  useEffect(() => { if (lanes.length && !lanes.some((l) => l.id === laneId)) setLaneId(lanes[0].id); }, [lanes, laneId]);

  const run = useMutation(async () => {
    const out: ScenarioRow[] = [];
    for (const m of MULTIPLIERS) {
      const count = Math.max(1, Math.min(50, Math.round(base * m)));
      setProgress(`Simulating ${count} passes at ×${m}…`);
      const evs: WeighingOut[] = await weighingApi.simulate({ lane_id: laneId, count, overload_prob: overload, sensor_fault_prob: 0.03, anpr_misread_prob: 0.05, rfid_missing_prob: 0.1, clone_prob: 0.01, unregistered_prob: 0.05, pavement_temp_c: 32, seed: 1000 + Math.round(m * 100) });
      const mix: Record<Decision, number> = { GREEN: 0, AMBER: 0, RED: 0 };
      let lat = 0, n = 0;
      for (const e of evs) { if (e.decision) { mix[e.decision.decision]++; lat += e.decision.latency_ms; n++; } }
      // Queue wait grows with arrivals: scale the observed average wait by the multiplier (modelled, not measured).
      const waitS = Math.round((st?.avg_wait_s ?? 900) * m);
      let env: WhatIfOut | null = null;
      try { env = await envApi.whatIf({ stops_avoided: mix.GREEN, stops_made: mix.AMBER + mix.RED, avg_queue_wait_s: waitS }); } catch { env = null; }
      out.push({ label: m === 1 ? 'baseline' : `+${Math.round((m - 1) * 100)} % arrivals`, multiplier: m, count, mix, meanLatency: n ? lat / n : 0, waitS, env, source: evs[0]?.source ?? 'simulated' });
      setRows(out.slice());
    }
    setProgress(null);
    return out;
  });

  return (
    <Card title="Scenario comparison (simulated)" subtitle="POST /weighing/simulate with arrival multipliers +20/30/50 % → decision mix and mean latency; POST /environment/what-if → modelled fuel">
      <div className="grid gap-2 sm:grid-cols-5">
        <Field label="Station">{(id) => <select id={id} className="input" value={stationId} onChange={(e) => setStationId(e.target.value)}>{stations.map((s) => <option key={s.id} value={s.id}>{s.code}</option>)}</select>}</Field>
        <Field label="Lane">{(id) => <select id={id} className="input" value={laneId} onChange={(e) => setLaneId(e.target.value)}>{lanes.map((l) => <option key={l.id} value={l.id}>Lane {l.lane_no}</option>)}</select>}</Field>
        <Field label="Baseline passes (≤ 33)">{(id) => <input id={id} type="number" min={1} max={33} className="input" value={base} onChange={(e) => setBase(Number(e.target.value))} />}</Field>
        <Field label={`Overload probability (${Math.round(overload * 100)} %)`}>{(id) => <input id={id} type="range" min={0} max={1} step={0.05} className="w-full accent-brand-600" value={overload} onChange={(e) => setOverload(Number(e.target.value))} />}</Field>
        <div className="flex items-end"><button className="btn-primary w-full" disabled={run.busy || !laneId} onClick={() => void run.run()}>{run.busy ? progress ?? 'Running…' : 'Run 4 scenarios'}</button></div>
      </div>
      <ErrorBanner error={run.error} className="mt-2" />
      <Notice tone="warn" className="mt-2">All scenario passes are generated by the simulator and tagged SIMULATED. Fuel/CO₂ figures are modelled estimates (what-if agent), not measurements.</Notice>
      {rows.length > 0 && (
        <div className="mt-3">
          <Table head={['Scenario', 'Passes', 'GREEN', 'AMBER', 'RED', 'GREEN rate', 'Mean latency', 'Assumed wait', 'Fuel baseline → platform (L)', 'Fuel saved (L)', 'CO₂ saved (kg)', 'Source']} dense>
            {rows.map((r) => {
              const total = r.mix.GREEN + r.mix.AMBER + r.mix.RED;
              return (
                <tr key={r.label} className="tr">
                  <td className="td font-medium">{r.label}</td><td className="td tabular-nums">{r.count}</td>
                  <td className="td tabular-nums text-decision-green">{r.mix.GREEN}</td><td className="td tabular-nums text-decision-amber">{r.mix.AMBER}</td><td className="td tabular-nums text-decision-red">{r.mix.RED}</td>
                  <td className="td tabular-nums">{fmtPct(total ? r.mix.GREEN / total : 0)}</td><td className="td tabular-nums">{fmtNum(r.meanLatency, 0)} ms</td><td className="td">{fmtDuration(r.waitS)}</td>
                  <td className="td tabular-nums">{r.env ? `${fmtNum(r.env.baseline.litres, 1)} → ${fmtNum(r.env.platform.litres, 1)}` : '—'}</td><td className="td tabular-nums">{r.env ? fmtNum(r.env.savings.litres, 1) : '—'}</td><td className="td tabular-nums">{r.env ? fmtNum(r.env.savings.co2_kg, 1) : '—'}</td>
                  <td className="td"><Badge tone="slate">{r.source.toUpperCase()}</Badge></td>
                </tr>
              );
            })}
          </Table>
        </div>
      )}
    </Card>
  );
}

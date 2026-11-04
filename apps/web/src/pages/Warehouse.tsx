import { useEffect, useMemo, useState } from 'react';
import { queue as queueApi, shipments as shipmentsApi, stations as stationsApi } from '../api/endpoints';
import type { PassportOut, ShipmentStage } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { PassportView, StageTimeline } from '../components/passport';
import { Badge, Card, Empty, ErrorBanner, Notice, Spinner, Stat, StatusDot, Table } from '../components/ui';
import { useLiveEvents } from '../hooks/useLiveEvents';
import { useMutation, useQuery } from '../hooks/useQuery';
import { fmtDateTime, fmtKg, titleCase } from '../lib/format';

export default function Warehouse() {
  const { me } = useAuth();
  const whQ = useQuery(() => shipmentsApi.warehouses(), [], { pollMs: 60_000 });
  const mine = useMemo(() => (whQ.data ?? []).filter((w) => !me?.org_id || w.org_id === me.org_id), [whQ.data, me]);
  const [whId, setWhId] = useState<string>('');
  useEffect(() => { if (!whId && mine[0]) setWhId(mine[0].id); }, [mine, whId]);
  const wh = mine.find((w) => w.id === whId) ?? null;
  const shipQ = useQuery(() => shipmentsApi.list({ warehouse_id: whId }), [whId], { enabled: !!whId, pollMs: 60_000 });
  const apptsQ = useQuery(() => queueApi.mine(), [], { pollMs: 60_000 });
  const stationsQ = useQuery(() => stationsApi.list(), []);
  const live = useLiveEvents(['cargo.status_changed', 'cargo.verified', 'shipment.delivered', 'queue.updated'], null, 50, (ev) => {
    if (ev.type !== 'queue.updated') void shipQ.refetch(); else void apptsQ.refetch();
  });
  const readiness = useMutation((s: 'ready' | 'busy' | 'closed') => shipmentsApi.readiness(whId, s));
  const [selected, setSelected] = useState<string | null>(null);
  const shipments = shipQ.data ?? [];
  const incoming = shipments.filter((s) => !['delivered', 'closed'].includes(s.stage));
  const current = shipments.find((s) => s.id === selected) ?? null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div><h1 className="text-xl font-semibold">Warehouse — {me?.org_name}</h1><p className="text-sm text-slate-500">live {live.status}</p></div>
        {mine.length > 1 && <select className="input w-auto" aria-label="Warehouse" value={whId} onChange={(e) => { setWhId(e.target.value); setSelected(null); }}>{mine.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select>}
      </div>
      <ErrorBanner error={whQ.error} />
      {whQ.loading && <Spinner />}
      {!whQ.loading && mine.length === 0 && <Empty>No warehouses are registered for your organisation.</Empty>}

      {wh && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title={wh.name} subtitle={`${wh.dock_count} docks · ${wh.lat.toFixed(4)}, ${wh.lon.toFixed(4)}`}>
            <div className="grid grid-cols-2 gap-2">
              <Stat label="Incoming" value={wh.incoming} tone="teal" />
              <Stat label="Readiness" value={<span className="flex items-center gap-2"><StatusDot status={wh.readiness_status} />{wh.readiness_status}</span>} />
            </div>
            <div className="mt-3">
              <div className="label">Set readiness · POST /shipments/warehouses/{'{id}'}/readiness</div>
              <div className="flex gap-1">{(['ready', 'busy', 'closed'] as const).map((s) => <button key={s} className={`btn-secondary flex-1 ${wh.readiness_status === s ? 'ring-2 ring-brand-500' : ''}`} disabled={readiness.busy || wh.readiness_status === s} aria-pressed={wh.readiness_status === s} onClick={async () => { if (await readiness.run(s)) void whQ.refetch(); }}>{s}</button>)}</div>
              <ErrorBanner error={readiness.error} className="mt-2" />
            </div>
          </Card>
          <Card title="Arrival predictions" subtitle="Predicted release windows from the passport (model output) and booked weighbridge slots" className="lg:col-span-2">
            <ArrivalTable shipments={incoming} appts={apptsQ.data ?? []} stations={stationsQ.data ?? []} />
          </Card>
        </div>
      )}

      {wh && (
        current ? (
          <Card actions={<button className="btn-secondary text-xs" onClick={() => setSelected(null)}>Back</button>}>
            <PassportView s={current} stations={stationsQ.data} />
            <CargoActions s={current} onChanged={() => void shipQ.refetch()} />
          </Card>
        ) : (
          <Card title="Incoming shipments" subtitle={`GET /shipments?warehouse_id=… · ${incoming.length} active, ${shipments.length - incoming.length} delivered/closed`}>
            <ErrorBanner error={shipQ.error} />
            {shipQ.loading ? <Spinner /> : shipments.length === 0 ? <Empty>No shipments are routed to this warehouse</Empty> : (
              <Table head={['Reference', 'Cargo', 'Truck', 'Stage', 'Declared', 'Predicted release', 'Outstanding', '']}>
                {shipments.map((s) => (
                  <tr key={s.id} className="tr">
                    <td className="td font-medium">{s.reference}</td><td className="td">{s.description}<div className="text-xs text-slate-500">{s.owner_org_name}</div></td><td className="td">{s.vehicle_plate ?? '—'}</td>
                    <td className="td"><Badge tone={['delivered', 'closed'].includes(s.stage) ? 'slate' : 'teal'}>{titleCase(s.stage)}</Badge><div className="mt-1 hidden xl:block"><StageTimeline s={s} /></div></td>
                    <td className="td tabular-nums">{fmtKg(s.declared_mass_kg)}</td><td className="td">{s.predicted_release_at ? fmtDateTime(s.predicted_release_at) : <span className="text-slate-400">not predicted</span>}</td>
                    <td className="td text-xs">{s.outstanding.length ? s.outstanding.slice(0, 2).map(titleCase).join(', ') + (s.outstanding.length > 2 ? '…' : '') : '—'}</td>
                    <td className="td"><button className="btn-secondary px-2 py-1 text-xs" onClick={() => setSelected(s.id)}>Open</button></td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        )
      )}
    </div>
  );
}

function ArrivalTable({ shipments, appts, stations }: { shipments: PassportOut[]; appts: import('../api/types').AppointmentOut[]; stations: import('../api/types').StationOut[] }) {
  if (!shipments.length) return <Empty>No active incoming shipments</Empty>;
  return (
    <Table head={['Reference', 'Truck', 'Stage', 'P10', 'P50 (predicted release)', 'P90', 'Weighbridge slot']} dense>
      {shipments.map((s) => {
        const a = appts.find((x) => x.shipment_id === s.id) ?? (s.vehicle_id ? appts.find((x) => x.vehicle_id === s.vehicle_id && x.status === 'booked') : undefined);
        return (
          <tr key={s.id} className="tr">
            <td className="td font-medium">{s.reference}</td><td className="td">{s.vehicle_plate ?? '—'}</td><td className="td">{titleCase(s.stage)}</td>
            <td className="td">{fmtDateTime(s.predicted_release_p10)}</td><td className="td">{s.predicted_release_at ? <span className="font-medium">{fmtDateTime(s.predicted_release_at)}</span> : <span className="text-slate-400">no prediction</span>}</td><td className="td">{fmtDateTime(s.predicted_release_p90)}</td>
            <td className="td">{a ? `${stations.find((st) => st.id === a.station_id)?.code ?? a.station_code} ${fmtDateTime(a.slot_start)} (${a.status})` : <span className="text-slate-400">none visible</span>}</td>
          </tr>
        );
      })}
    </Table>
  );
}

function CargoActions({ s, onChanged }: { s: PassportOut; onChanged: () => void }) {
  const stage = useMutation((st: ShipmentStage) => shipmentsApi.stage(s.id, { stage: st, status: 'completed', notes: 'recorded at warehouse' }));
  const blocked = useMutation(() => shipmentsApi.stage(s.id, { stage: s.stage as ShipmentStage, status: 'blocked', notes: 'blocked at warehouse' }));
  return (
    <div className="mt-4 space-y-2 border-t border-slate-200 pt-3 dark:border-slate-800">
      <div className="label">Cargo status · POST /shipments/{'{id}'}/stage</div>
      <div className="flex flex-wrap gap-2">
        {s.stage === 'in_transit' || s.stage === 'released' ? <button className="btn-primary" disabled={stage.busy} onClick={async () => { if (await stage.run('delivered')) onChanged(); }}>Confirm delivered</button> : null}
        {s.stage === 'delivered' && <button className="btn-secondary" disabled={stage.busy} onClick={async () => { if (await stage.run('closed')) onChanged(); }}>Close shipment</button>}
        {!['delivered', 'closed'].includes(s.stage) && <button className="btn-secondary" disabled={blocked.busy} onClick={async () => { if (await blocked.run()) onChanged(); }}>Flag blocked at {titleCase(s.stage)}</button>}
      </div>
      {['delivered', 'closed'].includes(s.stage) ? <Notice tone="ok">Shipment {s.stage}.</Notice> : !['in_transit', 'released'].includes(s.stage) && <p className="text-xs text-slate-500">Delivery can be confirmed once the shipment is released or in transit (current: {titleCase(s.stage)}).</p>}
      <ErrorBanner error={stage.error ?? blocked.error} />
    </div>
  );
}

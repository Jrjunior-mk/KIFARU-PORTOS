import { type FormEvent, lazy, Suspense, useEffect, useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { ApiError } from '../api/client';
import { backhaul as backhaulApi, environment as envApi, fleet as fleetApi, queue as queueApi, shipments as shipmentsApi, stations as stationsApi, weighing as weighingApi } from '../api/endpoints';
import { BODY_TYPES, type AppointmentOut, type BodyType, type FleetOut, type MatchOut, type OfferOut, type PassportOut, type SlotOut, type StationOut, type VehicleIn, type VehicleOut, type WeighingOut } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Badge, Card, Empty, ErrorBanner, Field, Notice, Spinner, Stat, Table, Tabs } from '../components/ui';
import { DecisionPanel, TicketCard, WeighingHistoryTable } from '../components/weighing';
import { useLiveEvents } from '../hooks/useLiveEvents';
import { useMutation, useQuery } from '../hooks/useQuery';
import { chartTheme, SERIES, useDarkMode } from '../lib/chart';
import { fmtAgo, fmtClock, fmtDateTime, fmtDuration, fmtKes, fmtKg, fmtNum, fmtPct, titleCase } from '../lib/format';
import { StageTimeline } from '../components/passport';
import { MatchCard } from '../components/backhaul';

const StationMap = lazy(() => import('../components/StationMap'));

export default function Transporter() {
  const { me } = useAuth();
  const vehiclesQ = useQuery(() => fleetApi.vehicles(), [], { pollMs: 60_000 });
  const fleetsQ = useQuery(() => fleetApi.fleets(), []);
  const stationsQ = useQuery(() => stationsApi.list(), [], { pollMs: 60_000 });
  const shipmentsQ = useQuery(() => shipmentsApi.list(), [], { pollMs: 60_000 });
  const eventsQ = useQuery(() => weighingApi.events({ limit: 200 }), [], { pollMs: 60_000 });
  const apptsQ = useQuery(() => queueApi.mine(), [], { pollMs: 60_000 });
  const oppsQ = useQuery(() => backhaulApi.opportunities(), [], { pollMs: 60_000 });
  const live = useLiveEvents(['clearance.decided', 'queue.updated', 'backhaul.opportunity', 'cargo.status_changed', 'shipment.delivered'], null, 100, (ev) => {
    if (ev.type === 'clearance.decided') void eventsQ.refetch();
    if (ev.type === 'queue.updated') void apptsQ.refetch();
    if (ev.type === 'backhaul.opportunity') void oppsQ.refetch();
    if (ev.type === 'cargo.status_changed' || ev.type === 'shipment.delivered') void shipmentsQ.refetch();
  });
  const [tab, setTab] = useState<'fleet' | 'shipments' | 'clearance' | 'slots' | 'backhaul' | 'analytics'>('fleet');
  const vehicles = vehiclesQ.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h1 className="text-xl font-semibold">Transporter — {me?.org_name ?? 'fleet'}</h1><p className="text-sm text-slate-500">{vehicles.length} vehicles · {shipmentsQ.data?.length ?? 0} shipments · live {live.status}</p></div>
        <Badge tone={live.hasLive ? 'teal' : 'slate'}>{live.hasLive ? 'live measurements seen' : 'simulated data only'}</Badge>
      </div>
      <Tabs value={tab} onChange={setTab} tabs={[{ id: 'fleet', label: 'Fleet & map' }, { id: 'shipments', label: 'Shipments' }, { id: 'clearance', label: 'Tickets & clearance' }, { id: 'slots', label: 'Slot booking' }, { id: 'backhaul', label: 'Backhaul' }, { id: 'analytics', label: 'Fuel & cost' }]} />

      {tab === 'fleet' && (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card title="Fleet" subtitle="GET /fleet/vehicles (scoped to your organisation)" className="lg:col-span-2">
            <ErrorBanner error={vehiclesQ.error} />
            {vehicles.length === 0 && !vehiclesQ.loading ? <Empty>No vehicles registered yet</Empty> : (
              <Table head={['Plate', 'Config', 'Body', 'Tare', 'Max GVM', 'Payload', 'RFID', 'Last seen', 'Status']} dense>
                {vehicles.map((v) => (
                  <tr key={v.id} className="tr">
                    <td className="td font-medium">{v.plate} {v.watchlisted && <Badge tone="red">watch-list</Badge>}</td><td className="td">{v.axle_config} <span className="text-slate-400">{v.class_code}</span></td><td className="td">{v.body_type}</td>
                    <td className="td tabular-nums">{fmtKg(v.tare_kg)}</td><td className="td tabular-nums">{fmtKg(v.max_gvm_kg)}</td><td className="td tabular-nums">{fmtKg(v.payload_capacity_kg)}</td>
                    <td className="td mono">{v.rfid_epcs.length ? v.rfid_epcs.join(', ') : '—'}</td><td className="td">{v.last_seen_at ? fmtAgo(v.last_seen_at) : 'never'}</td><td className="td"><Badge tone={v.status === 'active' ? 'green' : 'slate'}>{v.status}</Badge></td>
                  </tr>
                ))}
              </Table>
            )}
            <div className="mt-4"><Suspense fallback={<Spinner label="Loading map" />}><StationMap stations={stationsQ.data ?? []} vehicles={vehicles} height={320} /></Suspense></div>
          </Card>
          <AddVehicle fleets={fleetsQ.data ?? []} onCreated={() => void vehiclesQ.refetch()} />
        </div>
      )}

      {tab === 'shipments' && (
        <Card title="Shipments assigned to your trucks" subtitle="GET /shipments — visible when your organisation is the transporter">
          <ErrorBanner error={shipmentsQ.error} />
          {shipmentsQ.loading ? <Spinner /> : (shipmentsQ.data ?? []).length === 0 ? <Empty>No shipments are assigned to your organisation</Empty> : (
            <ul className="space-y-3">{(shipmentsQ.data ?? []).map((s) => <ShipmentRow key={s.id} s={s} stations={stationsQ.data ?? []} />)}</ul>
          )}
        </Card>
      )}

      {tab === 'clearance' && <ClearanceTab events={eventsQ.data ?? []} loading={eventsQ.loading} error={eventsQ.error} />}
      {tab === 'slots' && <SlotBooking stations={stationsQ.data ?? []} vehicles={vehicles} shipments={shipmentsQ.data ?? []} appts={apptsQ.data ?? []} onChanged={() => void apptsQ.refetch()} />}
      {tab === 'backhaul' && <BackhaulTab offers={oppsQ.data ?? []} loading={oppsQ.loading} error={oppsQ.error} orgId={me?.org_id ?? null} onChanged={() => void oppsQ.refetch()} />}
      {tab === 'analytics' && <Analytics offers={oppsQ.data ?? []} events={eventsQ.data ?? []} stations={stationsQ.data ?? []} orgId={me?.org_id ?? null} />}
    </div>
  );
}

function AddVehicle({ fleets, onCreated }: { fleets: FleetOut[]; onCreated: () => void }) {
  const [form, setForm] = useState<VehicleIn>({ plate: '', fleet_id: null, make: '', model: '', axle_config: '1+2+3', tare_kg: 16000, max_gvm_kg: 50000, payload_capacity_kg: 33000, body_type: 'flatbed', rfid_epc: '' });
  useEffect(() => { if (!form.fleet_id && fleets[0]) setForm((f) => ({ ...f, fleet_id: fleets[0].id })); }, [fleets, form.fleet_id]);
  const create = useMutation((b: VehicleIn) => fleetApi.createVehicle(b));
  const fe = create.error?.fieldErrors ?? {};
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const r = await create.run({ ...form, plate: form.plate.toUpperCase().trim(), make: form.make || null, model: form.model || null, rfid_epc: form.rfid_epc || null, fleet_id: form.fleet_id || null });
    if (r) { setForm({ ...form, plate: '', rfid_epc: '' }); onCreated(); }
  };
  const num = (k: 'tare_kg' | 'max_gvm_kg' | 'payload_capacity_kg', label: string, hint: string) => (
    <Field key={k} label={label} error={fe[k]} hint={hint}>{(id) => <input id={id} type="number" className="input" value={form[k]} onChange={(e) => setForm({ ...form, [k]: Number(e.target.value) })} required />}</Field>
  );
  return (
    <Card title="Add vehicle" subtitle="POST /fleet/vehicles">
      <form onSubmit={submit} className="space-y-2">
        <Field label="Plate" required error={fe.plate}>{(id) => <input id={id} className="input uppercase" required minLength={5} maxLength={16} value={form.plate} onChange={(e) => setForm({ ...form, plate: e.target.value })} placeholder="KDA 123B" />}</Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Axle config" required error={fe.axle_config} hint="e.g. 1+2+3">{(id) => <input id={id} className="input" required pattern="^\d(\+\d)*$" value={form.axle_config} onChange={(e) => setForm({ ...form, axle_config: e.target.value })} />}</Field>
          <Field label="Body type" error={fe.body_type}>{(id) => <select id={id} className="input" value={form.body_type} onChange={(e) => setForm({ ...form, body_type: e.target.value as BodyType })}>{BODY_TYPES.map((b) => <option key={b}>{b}</option>)}</select>}</Field>
          {num('tare_kg', 'Tare (kg)', '1 000–30 000')}{num('max_gvm_kg', 'Max GVM (kg)', '3 500–56 000')}{num('payload_capacity_kg', 'Payload (kg)', '0–50 000')}
          <Field label="Fleet" error={fe.fleet_id}>{(id) => <select id={id} className="input" value={form.fleet_id ?? ''} onChange={(e) => setForm({ ...form, fleet_id: e.target.value || null })}><option value="">none</option>{fleets.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}</select>}</Field>
          <Field label="Make" error={fe.make}>{(id) => <input id={id} className="input" value={form.make ?? ''} onChange={(e) => setForm({ ...form, make: e.target.value })} />}</Field>
          <Field label="Model" error={fe.model}>{(id) => <input id={id} className="input" value={form.model ?? ''} onChange={(e) => setForm({ ...form, model: e.target.value })} />}</Field>
        </div>
        <Field label="RFID EPC" error={fe.rfid_epc} hint="Optional tag EPC (hex)">{(id) => <input id={id} className="input font-mono" value={form.rfid_epc ?? ''} onChange={(e) => setForm({ ...form, rfid_epc: e.target.value })} />}</Field>
        <button className="btn-primary w-full" type="submit" disabled={create.busy}>Register vehicle</button>
        <ErrorBanner error={create.error} />
        {create.result && <Notice tone="ok">Registered {create.result.plate} (class {create.result.class_code}).</Notice>}
      </form>
    </Card>
  );
}

function ShipmentRow({ s, stations }: { s: PassportOut; stations: StationOut[] }) {
  return (
    <li className="rounded border border-slate-200 p-3 dark:border-slate-800">
      <div className="flex flex-wrap items-center justify-between gap-2"><div><span className="font-semibold">{s.reference}</span> · {s.description}</div><Badge tone="teal">{titleCase(s.stage)}</Badge></div>
      <div className="text-xs text-slate-500">{s.origin} → {s.destination} · {s.vehicle_plate ?? 'truck not assigned'} · owner {s.owner_org_name} · declared {fmtKg(s.declared_mass_kg)}</div>
      <div className="mt-2"><StageTimeline s={s} /></div>
      {s.weighings.length > 0 && <div className="mt-1 text-xs text-slate-500">Weighings: {s.weighings.map((w) => `${stations.find((st) => st.id === w.station_id)?.code ?? w.station_id} ${w.decision ?? '?'} ${fmtKg(w.gvm_kg)} [${w.source}]`).join(' · ')}</div>}
    </li>
  );
}

function ClearanceTab({ events, loading, error }: { events: WeighingOut[]; loading: boolean; error: ApiError | null }) {
  const [sel, setSel] = useState<WeighingOut | null>(null);
  const current = sel ?? events[0] ?? null;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Weighing tickets & clearance history" subtitle="GET /weighing/events scoped to your vehicles">
        <ErrorBanner error={error} />
        {loading ? <Spinner /> : <WeighingHistoryTable events={events} onSelect={setSel} selectedId={current?.id} />}
      </Card>
      <Card title={current ? `Pass ${current.plate ?? ''} · ${fmtDateTime(current.occurred_at)}` : 'Pass detail'}>
        {!current ? <Empty>Select a pass</Empty> : (
          <div className="space-y-4">
            <DecisionPanel d={current.decision} />
            {current.decision?.ticket_id ? <TicketCard ticketId={current.decision.ticket_id} /> : <Empty>No ticket</Empty>}
          </div>
        )}
      </Card>
    </div>
  );
}

function SlotBooking({ stations, vehicles, shipments, appts, onChanged }: { stations: StationOut[]; vehicles: VehicleOut[]; shipments: PassportOut[]; appts: AppointmentOut[]; onChanged: () => void }) {
  const [stationId, setStationId] = useState('');
  const [vehicleId, setVehicleId] = useState('');
  const [shipmentId, setShipmentId] = useState('');
  const [priority, setPriority] = useState(5);
  const [slot, setSlot] = useState<SlotOut | null>(null);
  useEffect(() => { if (!stationId && stations[0]) setStationId(stations[0].id); }, [stations, stationId]);
  useEffect(() => { if (!vehicleId && vehicles[0]) setVehicleId(vehicles[0].id); }, [vehicles, vehicleId]);
  const slotsQ = useQuery(() => queueApi.slots(stationId, 6), [stationId], { enabled: !!stationId, pollMs: 60_000 });
  const book = useMutation(() => queueApi.book(stationId, { vehicle_id: vehicleId, slot_start: slot!.slot_start, shipment_id: shipmentId || null, priority }));
  const status = useMutation((a: { id: string; s: 'arrived' | 'completed' | 'missed' | 'cancelled' }) => queueApi.setStatus(a.id, a.s));
  const st = stations.find((s) => s.id === stationId);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Book a weighing slot" subtitle="GET /queue/{station}/slots → POST /queue/{station}/appointments · 15-minute windows">
        <div className="grid grid-cols-2 gap-2">
          <Field label="Station">{(id) => <select id={id} className="input" value={stationId} onChange={(e) => { setStationId(e.target.value); setSlot(null); }}>{stations.map((s) => <option key={s.id} value={s.id}>{s.code} — queue {s.queue_len}, wait {fmtDuration(s.avg_wait_s)}</option>)}</select>}</Field>
          <Field label="Vehicle">{(id) => <select id={id} className="input" value={vehicleId} onChange={(e) => setVehicleId(e.target.value)}>{vehicles.map((v) => <option key={v.id} value={v.id}>{v.plate}</option>)}</select>}</Field>
          <Field label="Shipment (optional)">{(id) => <select id={id} className="input" value={shipmentId} onChange={(e) => setShipmentId(e.target.value)}><option value="">none</option>{shipments.map((s) => <option key={s.id} value={s.id}>{s.reference} · {s.vehicle_plate ?? 'unassigned'}</option>)}</select>}</Field>
          <Field label="Priority (1 high – 9 low)">{(id) => <input id={id} type="number" min={1} max={9} className="input" value={priority} onChange={(e) => setPriority(Number(e.target.value))} />}</Field>
        </div>
        {st && <p className="mt-2 text-xs text-slate-500">Capacity {st.capacity_per_hour}/h → {Math.max(1, Math.floor(st.capacity_per_hour / 4))} per window. Current utilisation {fmtPct(st.utilisation)}.</p>}
        <ErrorBanner error={slotsQ.error} className="mt-2" />
        {slotsQ.loading ? <Spinner label="Loading slots" /> : (
          <div className="mt-3 grid grid-cols-3 gap-1 sm:grid-cols-4 md:grid-cols-6" role="radiogroup" aria-label="Available slots">
            {(slotsQ.data ?? []).map((s) => {
              const full = s.available === 0;
              const active = slot?.slot_start === s.slot_start;
              return (
                <button key={s.slot_start} role="radio" aria-checked={active} disabled={full} onClick={() => setSlot(s)}
                  className={`rounded border px-1 py-1.5 text-xs ${active ? 'border-brand-600 bg-brand-50 dark:bg-brand-900/40' : 'border-slate-200 dark:border-slate-800'} ${full ? 'opacity-40' : 'hover:border-brand-400'}`}>
                  <div className="font-medium tabular-nums">{fmtClock(s.slot_start)}</div><div className="text-slate-500">{s.available}/{s.capacity} free</div>
                </button>
              );
            })}
          </div>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <button className="btn-primary" disabled={!slot || !vehicleId || book.busy} onClick={async () => { if (await book.run()) { setSlot(null); void slotsQ.refetch(); onChanged(); } }}>{slot ? `Book ${fmtClock(slot.slot_start)}` : 'Select a slot'}</button>
          {book.result && <Notice tone="ok">Booked {book.result.plate} at {book.result.station_code} {fmtClock(book.result.slot_start)} · est. wait {fmtDuration(book.result.est_wait_s)}</Notice>}
        </div>
        <ErrorBanner error={book.error} className="mt-2" />
      </Card>
      <Card title="My appointments" subtitle="GET /queue/appointments/mine">
        {appts.length === 0 ? <Empty>No appointments</Empty> : (
          <Table head={['Slot', 'Station', 'Plate', 'Status', 'Est. wait', 'Actions']} dense>
            {appts.slice(0, 30).map((a) => (
              <tr key={a.id} className="tr">
                <td className="td whitespace-nowrap">{fmtDateTime(a.slot_start)}</td><td className="td">{a.station_code}</td><td className="td">{a.plate}</td>
                <td className="td"><Badge tone={a.status === 'booked' ? 'teal' : a.status === 'arrived' ? 'blue' : a.status === 'completed' ? 'green' : 'slate'}>{a.status}</Badge></td><td className="td">{fmtDuration(a.est_wait_s)}</td>
                <td className="td">
                  {a.status === 'booked' && <span className="flex gap-1">{(['arrived', 'cancelled'] as const).map((s) => <button key={s} className="btn-secondary px-1.5 py-0.5 text-[11px]" disabled={status.busy} onClick={async () => { if (await status.run({ id: a.id, s })) onChanged(); }}>{s}</button>)}</span>}
                  {a.status === 'arrived' && <button className="btn-secondary px-1.5 py-0.5 text-[11px]" disabled={status.busy} onClick={async () => { if (await status.run({ id: a.id, s: 'completed' })) onChanged(); }}>completed</button>}
                </td>
              </tr>
            ))}
          </Table>
        )}
        <ErrorBanner error={status.error} className="mt-2" />
      </Card>
    </div>
  );
}

function BackhaulTab({ offers, loading, error, orgId, onChanged }: { offers: OfferOut[]; loading: boolean; error: ApiError | null; orgId: string | null; onChanged: () => void }) {
  const match = useMutation((id: string) => backhaulApi.match(id));
  return (
    <Card title="Backhaul opportunities" subtitle="GET /backhaul/opportunities — open/matched return loads; accept proposals for your trucks (two-party acceptance)">
      <ErrorBanner error={error} />
      {loading ? <Spinner /> : offers.length === 0 ? <Empty>No open return-load offers right now</Empty> : (
        <ul className="space-y-3">
          {offers.map((o) => (
            <li key={o.id} className="rounded border border-slate-200 p-3 dark:border-slate-800">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div><div className="font-semibold">{o.title} <Badge tone="slate">{o.cargo_type}</Badge></div><div className="text-xs text-slate-500">{o.origin} → {o.destination} · {fmtKg(o.mass_kg)} · ready {fmtDateTime(o.ready_from)} · deadline {fmtDateTime(o.deadline)} · {o.cargo_owner_name}</div></div>
                <div className="text-right"><div className="text-lg font-semibold">{fmtKes(o.offered_price_kes)}</div><Badge tone={o.status === 'open' ? 'teal' : 'blue'}>{o.status}</Badge></div>
              </div>
              {o.requires_body_types.length > 0 && <div className="mt-1 text-xs">Requires body: {o.requires_body_types.join(', ')}</div>}
              <div className="mt-2 flex items-center gap-2"><button className="btn-secondary text-xs" disabled={match.busy} onClick={async () => { if (await match.run(o.id)) onChanged(); }}>Run matching agent</button><span className="text-xs text-slate-500">{o.matches.length} proposal(s) visible to you</span></div>
              {match.error && <ErrorBanner error={match.error} className="mt-1" />}
              <div className="mt-2 space-y-1">{o.matches.map((m) => <MatchCard key={m.id} m={m} side="transporter" orgId={orgId} onChanged={onChanged} />)}</div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Analytics({ offers, events, stations, orgId }: { offers: OfferOut[]; events: WeighingOut[]; stations: StationOut[]; orgId: string | null }) {
  const dark = useDarkMode();
  const t = chartTheme(dark);
  const myMatches = useMemo(() => offers.flatMap((o) => o.matches).filter((m) => m.transporter_org_id === orgId), [offers, orgId]);
  const assigned = myMatches.filter((m) => m.status === 'assigned' || m.status === 'delivered');
  const agg = (ms: MatchOut[]) => ms.reduce((a, m) => ({ fuel: a.fuel + m.fuel_litres, cost: a.cost + m.fuel_cost_kes, rev: a.rev + m.revenue_kes, co2: a.co2 + m.co2_avoided_kg, km: a.km + m.extra_km, loaded: a.loaded + Number((m.explanation as { km_loaded?: number }).km_loaded ?? 0) }), { fuel: 0, cost: 0, rev: 0, co2: 0, km: 0, loaded: 0 });
  const A = agg(assigned);
  const green = events.filter((e) => e.decision?.decision === 'GREEN').length;
  const stops = events.filter((e) => e.decision && e.decision.decision !== 'GREEN').length;
  const avgWait = stations.length ? Math.round(stations.reduce((a, s) => a + s.avg_wait_s, 0) / stations.length) : 900;
  const [emptyKm, setEmptyKm] = useState(500);
  const whatIf = useQuery(() => envApi.whatIf({ stops_avoided: green, stops_made: stops, avg_queue_wait_s: avgWait, empty_km: emptyKm, empty_km_avoided: Math.min(emptyKm, A.loaded) }), [green, stops, avgWait, emptyKm, A.loaded]);
  const rows = whatIf.data ? [
    { metric: 'Fuel (L)', baseline: whatIf.data.baseline.litres, platform: whatIf.data.platform.litres },
    { metric: 'CO₂ (kg)', baseline: whatIf.data.baseline.co2_kg, platform: whatIf.data.platform.co2_kg },
    { metric: 'Cost (kKES)', baseline: whatIf.data.baseline.cost_kes / 1000, platform: whatIf.data.platform.cost_kes / 1000 },
  ] : [];
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card title="Backhaul economics (from matches)" subtitle={`${myMatches.length} proposals for your trucks · ${assigned.length} assigned/delivered`}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          <Stat label="Revenue (assigned)" value={fmtKes(A.rev)} tone="teal" /><Stat label="Fuel cost" value={fmtKes(A.cost)} /><Stat label="Net" value={fmtKes(A.rev - A.cost)} tone={A.rev - A.cost >= 0 ? 'teal' : 'default'} />
          <Stat label="Extra km" value={`${fmtNum(A.km, 0)} km`} /><Stat label="Fuel" value={`${fmtNum(A.fuel, 0)} L`} /><Stat label="CO₂ avoided (modelled)" value={`${fmtNum(A.co2, 0)} kg`} />
        </div>
        {myMatches.length === 0 && <Empty>No backhaul matches yet. Run matching on an offer in the Backhaul tab.</Empty>}
      </Card>
      <Card title="Fuel & cost what-if (modelled)" subtitle="POST /environment/what-if using your clearance history (GREEN = stop avoided) and backhaul empty-km">
        <Notice tone="warn">Modelled estimates from published factors — not measured consumption.</Notice>
        <div className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
          <Stat label="Stops avoided" value={green} tone="green" /><Stat label="Stops made" value={stops} /><Stat label="Avg wait used" value={fmtDuration(avgWait)} />
          <Field label={`Empty km baseline (${emptyKm})`}>{(id) => <input id={id} type="range" min={0} max={5000} step={50} className="w-full accent-brand-600" value={emptyKm} onChange={(e) => setEmptyKm(Number(e.target.value))} />}</Field>
        </div>
        <ErrorBanner error={whatIf.error} className="mt-2" />
        {whatIf.data && (
          <>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={rows} margin={{ top: 8, right: 8, left: -12, bottom: 0 }} barGap={2}>
                <CartesianGrid stroke={t.grid} vertical={false} /><XAxis dataKey="metric" tick={{ fontSize: 11, fill: t.text }} stroke={t.axis} /><YAxis tick={{ fontSize: 11, fill: t.text }} stroke={t.axis} />
                <Tooltip contentStyle={t.tooltip} formatter={(v: number) => fmtNum(v, 1)} /><Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="baseline" name="baseline (all stop, all empty km)" fill={SERIES.secondary} radius={[4, 4, 0, 0]} /><Bar dataKey="platform" name="with platform (modelled)" fill={SERIES.primary} radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
            <p className="text-xs text-slate-600 dark:text-slate-300">Savings: {fmtNum(whatIf.data.savings.litres, 0)} L · {fmtNum(whatIf.data.savings.co2_kg, 0)} kg CO₂ · {fmtKes(whatIf.data.savings.cost_kes)} — {whatIf.data.explanation}</p>
          </>
        )}
      </Card>
    </div>
  );
}

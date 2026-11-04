import { type FormEvent, useEffect, useMemo, useState } from 'react';
import { backhaul as backhaulApi, fleet as fleetApi, notifications as notifApi, shipments as shipmentsApi, stations as stationsApi } from '../api/endpoints';
import { CARGO_TYPES, type CargoType, type ContainerIn, type OfferIn, type OfferOut, type PassportOut, type ShipmentIn } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { PassportView, StageTimeline } from '../components/passport';
import { Badge, Card, Empty, ErrorBanner, Field, Notice, Spinner, Tabs } from '../components/ui';
import { useLiveEvents } from '../hooks/useLiveEvents';
import { useMutation, useQuery } from '../hooks/useQuery';
import { fmtAgo, fmtDateTime, fmtKes, fmtKg, isoToLocalInput, localToIso, titleCase } from '../lib/format';
import { validateContainerNumber } from '../lib/iso6346';
import { MatchCard } from '../components/backhaul';

export default function Owner() {
  const { me } = useAuth();
  const shipmentsQ = useQuery(() => shipmentsApi.list(), [], { pollMs: 60_000 });
  const stationsQ = useQuery(() => stationsApi.list(), []);
  const inboxQ = useQuery(() => notifApi.inbox(false), [], { pollMs: 60_000 });
  const offersQ = useQuery(() => backhaulApi.offers(), [], { pollMs: 60_000 });
  const live = useLiveEvents(['cargo.status_changed', 'cargo.verified', 'shipment.delivered', 'notification', 'backhaul.opportunity'], null, 100, (ev) => {
    if (ev.type.startsWith('cargo.') || ev.type === 'shipment.delivered') void shipmentsQ.refetch();
    if (ev.type === 'notification') void inboxQ.refetch();
    if (ev.type === 'backhaul.opportunity') void offersQ.refetch();
  });
  const [tab, setTab] = useState<'shipments' | 'new' | 'alerts' | 'backhaul'>('shipments');
  const [selected, setSelected] = useState<string | null>(null);
  const list = shipmentsQ.data ?? [];
  const current = useMemo(() => list.find((s) => s.id === selected) ?? null, [list, selected]);
  const unread = (inboxQ.data ?? []).filter((n) => !n.read_at).length;

  return (
    <div className="mx-auto max-w-3xl space-y-3">
      <div>
        <h1 className="text-lg font-semibold">{me?.org_name ?? 'Cargo owner'}</h1>
        <p className="text-xs text-slate-500">{list.length} shipments · {unread} unread alerts · live {live.status}</p>
      </div>
      <Tabs value={tab} onChange={(t) => { setTab(t); setSelected(null); }} tabs={[{ id: 'shipments', label: 'Shipments' }, { id: 'new', label: 'Register' }, { id: 'alerts', label: `Alerts${unread ? ` (${unread})` : ''}` }, { id: 'backhaul', label: 'Backhaul' }]} />

      {tab === 'shipments' && (
        current ? (
          <Card actions={<button className="btn-secondary text-xs" onClick={() => setSelected(null)}>Back to list</button>}>
            <PassportView s={current} stations={stationsQ.data} />
          </Card>
        ) : (
          <div className="space-y-2">
            <ErrorBanner error={shipmentsQ.error} />
            {shipmentsQ.loading && <Spinner />}
            {!shipmentsQ.loading && list.length === 0 && <Empty>No shipments yet — register one.</Empty>}
            {list.map((s) => (
              <button key={s.id} className="card w-full p-3 text-left hover:border-brand-400" onClick={() => setSelected(s.id)}>
                <div className="flex items-center justify-between gap-2"><span className="font-semibold">{s.reference}</span><Badge tone="teal">{titleCase(s.stage)}</Badge></div>
                <div className="truncate text-sm">{s.description}</div>
                <div className="text-xs text-slate-500">{s.origin} → {s.destination} · {s.vehicle_plate ?? 'no truck'} · {fmtAgo(s.created_at)}</div>
                <div className="mt-2"><StageTimeline s={s} /></div>
                {s.outstanding.length > 0 && <div className="mt-1 text-xs text-amber-700 dark:text-amber-300">{s.outstanding.length} outstanding item(s)</div>}
              </button>
            ))}
          </div>
        )
      )}

      {tab === 'new' && <RegisterShipment onCreated={(s) => { void shipmentsQ.refetch(); setTab('shipments'); setSelected(s.id); }} />}

      {tab === 'alerts' && (
        <Card title="Alerts & notifications" subtitle="GET /notifications — delay alerts, stage changes, backhaul news">
          <ErrorBanner error={inboxQ.error} />
          {(inboxQ.data ?? []).length === 0 ? <Empty>No notifications</Empty> : (
            <ul className="divide-y divide-slate-100 dark:divide-slate-800">
              {(inboxQ.data ?? []).map((n) => (
                <li key={n.id} className={`py-2 ${n.read_at ? 'opacity-60' : ''}`}>
                  <div className="flex items-center justify-between gap-2"><span className="font-medium">{n.title}</span><Badge tone={n.template === 'cargo_stage' ? 'teal' : 'slate'}>{n.template}</Badge></div>
                  <div className="text-sm">{n.body}</div>
                  <div className="flex items-center justify-between text-xs text-slate-500"><span>{fmtDateTime(n.created_at)} · {n.channel}</span>{!n.read_at && <button className="btn-ghost px-2 py-0.5 text-xs" onClick={async () => { await notifApi.markRead(n.id); void inboxQ.refetch(); }}>Mark read</button>}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {tab === 'backhaul' && <OwnerBackhaul offers={offersQ.data ?? []} loading={offersQ.loading} onChanged={() => void offersQ.refetch()} />}
    </div>
  );
}

function RegisterShipment({ onCreated }: { onCreated: (s: PassportOut) => void }) {
  const transportersQ = useQuery(() => fleetApi.orgs('transporter'), []);
  const warehousesQ = useQuery(() => shipmentsApi.warehouses(), []);
  const [form, setForm] = useState<ShipmentIn>({ description: '', cargo_type: 'container', origin: 'Port of Mombasa', destination: 'Nairobi ICD', declared_mass_kg: 20000, vgm_kg: null, transporter_org_id: null, vehicle_id: null, warehouse_id: null, containers: [], declaration_reference: '', seal_id: '' });
  const [containers, setContainers] = useState<ContainerIn[]>([{ number: '', size_ft: 40, type: 'GP' }]);
  const create = useMutation((b: ShipmentIn) => shipmentsApi.create(b));
  const fe = create.error?.fieldErrors ?? {};
  const localErrors = containers.map((c) => (c.number ? validateContainerNumber(c.number) : null));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body: ShipmentIn = {
      ...form, containers: containers.filter((c) => c.number.trim()).map((c) => ({ ...c, number: c.number.toUpperCase().trim() })),
      declaration_reference: form.declaration_reference || null, seal_id: form.seal_id || null, vgm_kg: form.vgm_kg || null,
      transporter_org_id: form.transporter_org_id || null, warehouse_id: form.warehouse_id || null, vehicle_id: null,
    };
    const r = await create.run(body);
    if (r) onCreated(r);
  };
  return (
    <Card title="Register shipment" subtitle="POST /shipments — creates the digital cargo passport">
      <form onSubmit={submit} className="space-y-3">
        <Field label="Description" required error={fe.description}>{(id) => <input id={id} className="input" required minLength={3} maxLength={300} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />}</Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Cargo type" error={fe.cargo_type}>{(id) => <select id={id} className="input" value={form.cargo_type} onChange={(e) => setForm({ ...form, cargo_type: e.target.value as CargoType })}>{CARGO_TYPES.map((c) => <option key={c}>{c}</option>)}</select>}</Field>
          <Field label="Declared mass (kg)" required error={fe.declared_mass_kg} hint="0–60 000">{(id) => <input id={id} type="number" min={0} max={60000} className="input" required value={form.declared_mass_kg} onChange={(e) => setForm({ ...form, declared_mass_kg: Number(e.target.value) })} />}</Field>
          <Field label="Origin" required error={fe.origin}>{(id) => <input id={id} className="input" required value={form.origin} onChange={(e) => setForm({ ...form, origin: e.target.value })} />}</Field>
          <Field label="Destination" required error={fe.destination}>{(id) => <input id={id} className="input" required value={form.destination} onChange={(e) => setForm({ ...form, destination: e.target.value })} />}</Field>
          <Field label="VGM (kg)" error={fe.vgm_kg}>{(id) => <input id={id} type="number" min={0} max={60000} className="input" value={form.vgm_kg ?? ''} onChange={(e) => setForm({ ...form, vgm_kg: e.target.value ? Number(e.target.value) : null })} />}</Field>
          <Field label="Declaration ref (KRA)" error={fe.declaration_reference} hint="Moves the shipment to 'declared'">{(id) => <input id={id} className="input" value={form.declaration_reference ?? ''} onChange={(e) => setForm({ ...form, declaration_reference: e.target.value })} />}</Field>
          <Field label="Seal ID" error={fe.seal_id}>{(id) => <input id={id} className="input" value={form.seal_id ?? ''} onChange={(e) => setForm({ ...form, seal_id: e.target.value })} />}</Field>
          <Field label="Transporter" error={fe.transporter_org_id}>{(id) => <select id={id} className="input" value={form.transporter_org_id ?? ''} onChange={(e) => setForm({ ...form, transporter_org_id: e.target.value || null })}><option value="">not yet chosen</option>{(transportersQ.data ?? []).map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}</select>}</Field>
          <Field label="Destination warehouse" error={fe.warehouse_id}>{(id) => <select id={id} className="input" value={form.warehouse_id ?? ''} onChange={(e) => setForm({ ...form, warehouse_id: e.target.value || null })}><option value="">none</option>{(warehousesQ.data ?? []).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select>}</Field>
        </div>
        <fieldset className="space-y-2">
          <legend className="label">Containers (ISO 6346)</legend>
          {containers.map((c, i) => {
            const serverErr = fe[`containers.${i}.number`];
            const err = serverErr ?? localErrors[i] ?? undefined;
            return (
              <div key={i} className="grid grid-cols-[1fr_auto_auto_auto] items-end gap-2">
                <Field label={`Number ${i + 1}`} error={err ?? undefined} hint={!c.number ? 'e.g. MSKU1234565' : !err ? 'check digit OK' : undefined}>{(id) => <input id={id} className={`input font-mono uppercase ${err ? 'border-rose-500' : c.number ? 'border-green-500' : ''}`} maxLength={11} value={c.number} aria-invalid={!!err} onChange={(e) => setContainers(containers.map((x, j) => (j === i ? { ...x, number: e.target.value.toUpperCase() } : x)))} />}</Field>
                <Field label="ft">{(id) => <select id={id} className="input w-20" value={c.size_ft} onChange={(e) => setContainers(containers.map((x, j) => (j === i ? { ...x, size_ft: Number(e.target.value) } : x)))}>{[20, 40, 45].map((f) => <option key={f}>{f}</option>)}</select>}</Field>
                <Field label="Type">{(id) => <select id={id} className="input w-20" value={c.type} onChange={(e) => setContainers(containers.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)))}>{['GP', 'HC', 'RF', 'OT', 'TK'].map((t) => <option key={t}>{t}</option>)}</select>}</Field>
                <button type="button" className="btn-ghost px-2" aria-label="Remove container" onClick={() => setContainers(containers.filter((_, j) => j !== i))}>×</button>
              </div>
            );
          })}
          <button type="button" className="btn-secondary text-xs" onClick={() => setContainers([...containers, { number: '', size_ft: 40, type: 'GP' }])}>Add container</button>
        </fieldset>
        <button className="btn-primary w-full" type="submit" disabled={create.busy || localErrors.some(Boolean)}>Create passport</button>
        <ErrorBanner error={create.error} />
      </form>
    </Card>
  );
}

function OwnerBackhaul({ offers, loading, onChanged }: { offers: OfferOut[]; loading: boolean; onChanged: () => void }) {
  const { me } = useAuth();
  const [show, setShow] = useState(false);
  const now = new Date();
  const [form, setForm] = useState<OfferIn>({ title: '', cargo_type: 'general', mass_kg: 10000, requires_body_types: [], origin: 'Nairobi', origin_lat: -1.2921, origin_lon: 36.8219, destination: 'Mombasa', dest_lat: -4.0435, dest_lon: 39.6682, ready_from: new Date(now.getTime() + 3600_000).toISOString(), deadline: new Date(now.getTime() + 48 * 3600_000).toISOString(), offered_price_kes: 60000, notes: '' });
  const create = useMutation((b: OfferIn) => backhaulApi.createOffer(b));
  const match = useMutation((id: string) => backhaulApi.match(id));
  const fe = create.error?.fieldErrors ?? {};
  useEffect(() => { if (create.result) { setShow(false); onChanged(); create.reset(); } }, [create.result, onChanged, create]);
  const num = (k: 'mass_kg' | 'origin_lat' | 'origin_lon' | 'dest_lat' | 'dest_lon' | 'offered_price_kes', label: string, step = 'any') => (
    <Field key={k} label={label} error={fe[k]}>{(id) => <input id={id} type="number" step={step} className="input" required value={form[k]} onChange={(e) => setForm({ ...form, [k]: Number(e.target.value) })} />}</Field>
  );
  return (
    <Card title="Return-load offers" subtitle="POST /backhaul/offers → run matching → accept a proposed truck (transporter must also accept)" actions={<button className="btn-primary text-xs" onClick={() => setShow((s) => !s)}>{show ? 'Cancel' : 'New offer'}</button>}>
      {show && (
        <form className="mb-4 grid grid-cols-2 gap-2 rounded border border-slate-200 p-3 dark:border-slate-800" onSubmit={async (e) => { e.preventDefault(); await create.run({ ...form, notes: form.notes || null }); }}>
          <div className="col-span-2"><Field label="Title" required error={fe.title}>{(id) => <input id={id} className="input" required minLength={3} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />}</Field></div>
          <Field label="Cargo type" error={fe.cargo_type}>{(id) => <select id={id} className="input" value={form.cargo_type} onChange={(e) => setForm({ ...form, cargo_type: e.target.value as CargoType })}>{CARGO_TYPES.map((c) => <option key={c}>{c}</option>)}</select>}</Field>
          {num('mass_kg', 'Mass (kg)', '1')}
          <Field label="Origin" required error={fe.origin}>{(id) => <input id={id} className="input" required value={form.origin} onChange={(e) => setForm({ ...form, origin: e.target.value })} />}</Field>
          <Field label="Destination" required error={fe.destination}>{(id) => <input id={id} className="input" required value={form.destination} onChange={(e) => setForm({ ...form, destination: e.target.value })} />}</Field>
          {num('origin_lat', 'Origin lat')}{num('origin_lon', 'Origin lon')}{num('dest_lat', 'Dest lat')}{num('dest_lon', 'Dest lon')}
          <Field label="Ready from" error={fe.ready_from}>{(id) => <input id={id} type="datetime-local" className="input" value={isoToLocalInput(form.ready_from)} onChange={(e) => setForm({ ...form, ready_from: localToIso(e.target.value) })} />}</Field>
          <Field label="Deadline" error={fe.deadline}>{(id) => <input id={id} type="datetime-local" className="input" value={isoToLocalInput(form.deadline)} onChange={(e) => setForm({ ...form, deadline: localToIso(e.target.value) })} />}</Field>
          {num('offered_price_kes', 'Offered price (KES)', '1')}
          <Field label="Required body types" hint="comma separated, optional">{(id) => <input id={id} className="input" value={form.requires_body_types.join(',')} onChange={(e) => setForm({ ...form, requires_body_types: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) })} />}</Field>
          <div className="col-span-2 flex items-center gap-2"><button className="btn-primary" type="submit" disabled={create.busy}>Publish offer</button><ErrorBanner error={create.error} /></div>
        </form>
      )}
      {loading ? <Spinner /> : offers.length === 0 ? <Empty>No offers yet</Empty> : (
        <ul className="space-y-3">
          {offers.map((o) => (
            <li key={o.id} className="rounded border border-slate-200 p-3 dark:border-slate-800">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div><div className="font-semibold">{o.title}</div><div className="text-xs text-slate-500">{o.origin} → {o.destination} · {fmtKg(o.mass_kg)} · deadline {fmtDateTime(o.deadline)}</div></div>
                <div className="text-right"><div className="font-semibold">{fmtKes(o.offered_price_kes)}</div><Badge tone={o.status === 'assigned' || o.status === 'delivered' ? 'green' : 'teal'}>{o.status}</Badge></div>
              </div>
              {(o.status === 'open' || o.status === 'matched') && <button className="btn-secondary mt-2 text-xs" disabled={match.busy} onClick={async () => { if (await match.run(o.id)) onChanged(); }}>Run matching</button>}
              {match.error && <ErrorBanner error={match.error} className="mt-1" />}
              {o.matches.length === 0 ? <p className="mt-2 text-xs text-slate-500">No proposals yet. Matching requires trucks with a known position.</p> : <div className="mt-2 space-y-1">{o.matches.map((m) => <MatchCard key={m.id} m={m} side="owner" orgId={me?.org_id ?? null} onChanged={onChanged} />)}</div>}
            </li>
          ))}
        </ul>
      )}
      <Notice className="mt-3">Assignment happens only after both the transporter and you accept the same proposal.</Notice>
    </Card>
  );
}

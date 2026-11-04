/**
 * Driver in-cab screen: large tiles, high contrast, no interaction needed while driving.
 * Polling + WebSocket keep it fresh; clearance decisions are announced with the Web Speech API;
 * one geolocation fix is sent on load (POST /fleet/vehicles/{id}/position).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fleet as fleetApi, queue as queueApi, shipments as shipmentsApi, stations as stationsApi, weighing as weighingApi } from '../api/endpoints';
import type { ClearancePayload, Decision, LiveEvent, VehicleOut, WeighingOut } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { Badge, SourceBadge, Spinner } from '../components/ui';
import { eventSource, useLiveEvents } from '../hooks/useLiveEvents';
import { useQuery } from '../hooks/useQuery';
import { fmtAgo, fmtClock, fmtDuration, fmtKg, titleCase } from '../lib/format';

const VEHICLE_KEY = 'kifaru.driver.vehicle';

const DECISION_STYLE: Record<Decision, { bg: string; title: string; instruction: string; speech: string }> = {
  GREEN: { bg: 'bg-decision-green', title: 'GREEN — PROCEED', instruction: 'Keep driving. No stop required.', speech: 'Green. Proceed. No stop required.' },
  AMBER: { bg: 'bg-decision-amber', title: 'AMBER — STATIC SCALE', instruction: 'Divert to the static weighbridge lane for verification.', speech: 'Amber. Divert to the static scale for verification.' },
  RED: { bg: 'bg-decision-red', title: 'RED — INSPECTION', instruction: 'Divert to the inspection bay and wait for an officer.', speech: 'Red. Divert to the inspection bay and wait for an officer.' },
};

export default function Driver() {
  const { me } = useAuth();
  const vehiclesQ = useQuery(() => fleetApi.vehicles(), []);
  const [vehicleId, setVehicleId] = useState<string | null>(() => { try { return localStorage.getItem(VEHICLE_KEY); } catch { return null; } });
  const vehicles = vehiclesQ.data ?? [];
  useEffect(() => {
    if (vehicles.length && (!vehicleId || !vehicles.some((v) => v.id === vehicleId))) {
      if (vehicles.length === 1) setVehicleId(vehicles[0].id);
    }
  }, [vehicles, vehicleId]);
  const vehicle = vehicles.find((v) => v.id === vehicleId) ?? null;
  const choose = (v: VehicleOut) => { setVehicleId(v.id); try { localStorage.setItem(VEHICLE_KEY, v.id); } catch { /* ignore */ } };

  if (vehiclesQ.loading) return <div className="p-8"><Spinner label="Loading your vehicles" /></div>;
  if (!vehicle) {
    return (
      <div className="mx-auto max-w-xl space-y-4 p-4">
        <h1 className="text-2xl font-bold">Which truck are you driving today?</h1>
        <p className="text-slate-500">Tap once. Your choice is remembered on this device.</p>
        {vehicles.length === 0 && <p className="rounded-lg bg-amber-100 p-4 text-lg text-amber-900">No vehicles are registered for {me?.org_name ?? 'your organisation'}. Ask your dispatcher.</p>}
        <div className="grid gap-3">
          {vehicles.map((v) => <button key={v.id} className="rounded-2xl bg-slate-800 p-6 text-left text-white shadow-lg hover:bg-slate-700 focus:ring-4 focus:ring-brand-400" onClick={() => choose(v)}><div className="text-3xl font-bold">{v.plate}</div><div className="text-slate-300">{v.body_type} · {v.axle_config}</div></button>)}
        </div>
      </div>
    );
  }
  return <DriverScreen vehicle={vehicle} onChangeVehicle={() => { setVehicleId(null); try { localStorage.removeItem(VEHICLE_KEY); } catch { /* ignore */ } }} />;
}

function DriverScreen({ vehicle, onChangeVehicle }: { vehicle: VehicleOut; onChangeVehicle: () => void }) {
  const apptsQ = useQuery(() => queueApi.mine(), [], { pollMs: 30_000 });
  const stationsQ = useQuery(() => stationsApi.list(), [], { pollMs: 30_000 });
  const eventsQ = useQuery(() => weighingApi.events({ vehicle_id: vehicle.id, limit: 5 }), [vehicle.id], { pollMs: 20_000 });
  const shipmentsQ = useQuery(() => shipmentsApi.list(), [], { pollMs: 60_000 });
  const [liveDecision, setLiveDecision] = useState<{ payload: ClearancePayload; at: string; source: string | null } | null>(null);
  const spokenRef = useRef<string | null>(null);
  const [speechOn, setSpeechOn] = useState(true);
  const [posStatus, setPosStatus] = useState<string>('locating…');

  // Live decisions for my plate → update instantly and announce.
  const live = useLiveEvents(['clearance.decided', 'queue.updated'], null, 50, (ev: LiveEvent) => {
    if (ev.type === 'clearance.decided') {
      const p = ev.payload as unknown as ClearancePayload;
      if (p.plate && p.plate.replace(/\s/g, '').toUpperCase() === vehicle.plate.replace(/\s/g, '').toUpperCase()) {
        setLiveDecision({ payload: p, at: ev.occurred_at, source: eventSource(ev) });
        void eventsQ.refetch();
      }
    }
    if (ev.type === 'queue.updated') void stationsQ.refetch();
  });

  const latest: WeighingOut | null = eventsQ.data?.[0] ?? null;
  const decision: Decision | null = liveDecision?.payload.decision ?? latest?.decision?.decision ?? null;
  const decisionAt = liveDecision?.at ?? latest?.occurred_at ?? null;
  const decisionSource = liveDecision?.source ?? latest?.source ?? null;
  const decisionKey = liveDecision ? liveDecision.payload.weighing_event_id : latest?.id ?? null;

  const speak = useCallback((text: string) => {
    if (!speechOn || !('speechSynthesis' in window)) return;
    try { window.speechSynthesis.cancel(); const u = new SpeechSynthesisUtterance(text); u.lang = 'en-KE'; u.rate = 0.95; window.speechSynthesis.speak(u); } catch { /* unsupported */ }
  }, [speechOn]);

  useEffect(() => {
    if (!decision || !decisionKey) return;
    if (spokenRef.current === null) { spokenRef.current = decisionKey; return; } // do not announce the historical result on load
    if (spokenRef.current !== decisionKey) { spokenRef.current = decisionKey; speak(`${DECISION_STYLE[decision].speech}`); }
  }, [decision, decisionKey, speak]);

  // One geolocation fix on load → telematics position.
  useEffect(() => {
    if (!('geolocation' in navigator)) { setPosStatus('geolocation unavailable'); return; }
    navigator.geolocation.getCurrentPosition(async (pos) => {
      try { await fleetApi.position(vehicle.id, { lat: pos.coords.latitude, lon: pos.coords.longitude }); setPosStatus(`position sent ${pos.coords.latitude.toFixed(4)}, ${pos.coords.longitude.toFixed(4)}`); }
      catch (e) { setPosStatus(`position not sent: ${(e as Error).message}`); }
    }, (err) => setPosStatus(`position not available: ${err.message}`), { enableHighAccuracy: false, timeout: 15_000, maximumAge: 60_000 });
  }, [vehicle.id]);

  const appt = useMemo(() => (apptsQ.data ?? []).filter((a) => a.vehicle_id === vehicle.id && (a.status === 'booked' || a.status === 'arrived')).sort((a, b) => a.slot_start.localeCompare(b.slot_start))[0] ?? null, [apptsQ.data, vehicle.id]);
  const station = useMemo(() => stationsQ.data?.find((s) => s.id === (appt?.station_id ?? latest?.station_id)) ?? null, [stationsQ.data, appt, latest]);
  const shipment = useMemo(() => (shipmentsQ.data ?? []).find((s) => s.vehicle_id === vehicle.id && !['delivered', 'closed'].includes(s.stage)) ?? null, [shipmentsQ.data, vehicle.id]);
  const d = decision ? DECISION_STYLE[decision] : null;

  return (
    <div className="mx-auto max-w-3xl space-y-4 text-lg">
      <div className="flex items-center justify-between">
        <div><div className="text-sm uppercase tracking-wide text-slate-500">Driver screen</div><div className="text-3xl font-bold">{vehicle.plate}</div></div>
        <div className="text-right text-xs text-slate-500">
          <div>live {live.status} · {posStatus}</div>
          <div className="mt-1 flex justify-end gap-2">
            <button className="btn-secondary px-2 py-1 text-xs" onClick={() => setSpeechOn((s) => !s)} aria-pressed={speechOn}>{speechOn ? 'Voice on' : 'Voice off'}</button>
            <button className="btn-ghost px-2 py-1 text-xs" onClick={onChangeVehicle}>Change truck</button>
          </div>
        </div>
      </div>

      <section aria-live="assertive" aria-atomic="true" className={`rounded-3xl p-8 text-white shadow-xl ${d ? d.bg : 'bg-slate-700'}`}>
        <div className="text-sm font-semibold uppercase tracking-widest opacity-90">Latest clearance</div>
        <div className="mt-2 text-5xl font-black leading-none sm:text-6xl">{d ? d.title : 'NO RESULT YET'}</div>
        <div className="mt-4 text-2xl font-semibold">{d ? d.instruction : 'Your truck has not been weighed yet. Drive to your booked lane.'}</div>
        {decisionAt && (
          <div className="mt-4 flex flex-wrap items-center gap-3 text-base opacity-95">
            <span>{fmtAgo(decisionAt)} · {station?.code ?? ''}</span>
            {(liveDecision?.payload.gvm_kg ?? latest?.gvm_kg) !== undefined && <span>GVM {fmtKg(liveDecision?.payload.gvm_kg ?? latest!.gvm_kg)}</span>}
            <SourceBadge source={decisionSource} />
          </div>
        )}
      </section>

      <div className="grid gap-4 sm:grid-cols-2">
        <section className="rounded-2xl bg-slate-900 p-6 text-white dark:bg-slate-800">
          <div className="text-sm uppercase tracking-wide text-slate-400">Your appointment</div>
          {appt ? (
            <>
              <div className="mt-1 text-4xl font-bold">{fmtClock(appt.slot_start)}</div>
              <div className="text-xl">{station?.name ?? appt.station_code}</div>
              <div className="mt-2 text-slate-300">slot {fmtClock(appt.slot_start)}–{fmtClock(appt.slot_end)} · {appt.status}</div>
            </>
          ) : <div className="mt-2 text-xl text-slate-300">No booked slot. Your dispatcher books slots.</div>}
        </section>
        <section className="rounded-2xl bg-slate-900 p-6 text-white dark:bg-slate-800">
          <div className="text-sm uppercase tracking-wide text-slate-400">Queue at {station?.code ?? 'station'}</div>
          {station ? (
            <>
              <div className="mt-1 text-4xl font-bold">{station.queue_len} trucks</div>
              <div className="text-xl">about {fmtDuration(station.avg_wait_s)} wait</div>
              <div className="mt-2 flex items-center gap-2 text-slate-300"><Badge tone={station.status === 'operational' ? 'green' : station.status === 'degraded' ? 'amber' : 'red'}>{station.status}</Badge>{station.alt_allowed && <span>alternate route allowed</span>}</div>
            </>
          ) : <div className="mt-2 text-xl text-slate-300">No station selected yet.</div>}
        </section>
      </div>

      <section className="rounded-2xl border-2 border-slate-300 p-6 dark:border-slate-700">
        <div className="text-sm uppercase tracking-wide text-slate-500">Shipment</div>
        {shipment ? (
          <>
            <div className="mt-1 text-2xl font-bold">{shipment.reference} <Badge tone="teal">{titleCase(shipment.stage)}</Badge></div>
            <div className="text-xl">{shipment.description}</div>
            <div className="mt-1 text-slate-600 dark:text-slate-300">{shipment.origin} → {shipment.destination} · declared {fmtKg(shipment.declared_mass_kg)}{shipment.seals.length ? ` · seal ${shipment.seals.map((s) => `${s.seal_id} ${s.status}`).join(', ')}` : ''}</div>
            {shipment.outstanding.length > 0 && <div className="mt-2 text-amber-700 dark:text-amber-300">Still needed: {shipment.outstanding.map(titleCase).join(', ')}</div>}
          </>
        ) : <div className="mt-2 text-xl text-slate-500">No active shipment assigned to this truck.</div>}
      </section>
      <p className="text-center text-xs text-slate-500">Screen refreshes automatically. Decisions are spoken aloud when voice is on.</p>
    </div>
  );
}

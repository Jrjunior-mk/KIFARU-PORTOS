import { useState } from 'react';
import { type PassportOut, SHIPMENT_STAGES } from '../api/types';
import { fmtDateTime, fmtKg, titleCase } from '../lib/format';
import { TicketCard } from './weighing';
import { Badge, DecisionBadge, Empty, KV, Notice, SourceBadge, Table } from './ui';

/** Compact stage progress bar. Completed stages filled, current highlighted, blocked marked. */
export function StageTimeline({ s }: { s: PassportOut }) {
  const idx = SHIPMENT_STAGES.indexOf(s.stage as (typeof SHIPMENT_STAGES)[number]);
  const blocked = new Set(s.processing_events.filter((e) => e.status === 'blocked').map((e) => e.stage));
  return (
    <ol className="flex flex-wrap gap-1" aria-label="Shipment stages">
      {SHIPMENT_STAGES.map((st, i) => {
        const done = i < idx; const cur = i === idx;
        const cls = cur ? 'bg-brand-600 text-white' : done ? 'bg-brand-100 text-brand-800 dark:bg-brand-900/50 dark:text-brand-200' : 'bg-slate-100 text-slate-500 dark:bg-slate-800 dark:text-slate-400';
        return <li key={st} className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${cls} ${blocked.has(st) ? 'ring-2 ring-rose-500' : ''}`} aria-current={cur ? 'step' : undefined}>{titleCase(st)}{blocked.has(st) ? ' !' : ''}</li>;
      })}
    </ol>
  );
}

export function PassportView({ s, stations }: { s: PassportOut; stations?: { id: string; code: string }[] }) {
  const [ticketId, setTicketId] = useState<string | null>(null);
  const code = (id: string) => stations?.find((x) => x.id === id)?.code ?? id.slice(0, 8);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div><div className="text-xs text-slate-500">Digital cargo passport</div><h2 className="text-lg font-semibold">{s.reference}</h2><p className="text-sm">{s.description}</p></div>
        <div className="text-right"><Badge tone="teal">{titleCase(s.stage)}</Badge><div className="text-xs text-slate-500">{s.status}</div></div>
      </div>
      <StageTimeline s={s} />

      {s.outstanding.length > 0 && (
        <Notice tone="warn"><span className="font-medium">Outstanding:</span> {s.outstanding.map((o) => titleCase(o)).join(' · ')}</Notice>
      )}

      {(s.predicted_release_at || s.predicted_release_p10 || s.predicted_release_p90) ? (
        <div className="rounded-lg border border-violet-300 bg-violet-50 p-3 text-sm dark:border-violet-800 dark:bg-violet-950/40">
          <div className="flex items-center gap-2"><Badge tone="violet">PREDICTED</Badge> release window (model output, not a commitment)</div>
          <div className="mt-1 grid grid-cols-3 gap-2 text-xs">
            <div><div className="text-slate-500">P10 (early)</div><div className="font-medium">{fmtDateTime(s.predicted_release_p10)}</div></div>
            <div><div className="text-slate-500">P50</div><div className="font-medium">{fmtDateTime(s.predicted_release_at)}</div></div>
            <div><div className="text-slate-500">P90 (late)</div><div className="font-medium">{fmtDateTime(s.predicted_release_p90)}</div></div>
          </div>
          {s.prediction_explanation && <details className="mt-1 text-xs"><summary className="cursor-pointer">Why</summary><pre className="overflow-x-auto">{JSON.stringify(s.prediction_explanation, null, 1)}</pre></details>}
        </div>
      ) : <p className="text-xs text-slate-500">No release prediction has been computed for this shipment yet.</p>}

      <div className="grid gap-4 md:grid-cols-2">
        <KV items={[
          ['Owner', s.owner_org_name ?? s.owner_org_id], ['Transporter', s.transporter_org_name ?? 'not assigned'],
          ['Truck', s.vehicle_plate ? <span>{s.vehicle_plate} {s.vehicle_rfid.length > 0 && <span className="mono text-slate-500">RFID {s.vehicle_rfid.join(', ')}</span>}</span> : 'not assigned'],
          ['Route', `${s.origin} → ${s.destination}`], ['Cargo', `${titleCase(s.cargo_type)} · declared ${fmtKg(s.declared_mass_kg)}${s.vgm_kg ? ` · VGM ${fmtKg(s.vgm_kg)}` : ''}`],
          ['Declaration', s.declaration ? <span>{s.declaration.reference} <Badge tone="slate">{s.declaration.source}</Badge> {s.declaration.status}</span> : <span className="text-amber-700 dark:text-amber-300">missing</span>],
          ['Created', fmtDateTime(s.created_at)],
        ]} />
        <div className="space-y-2">
          <h4 className="label">Containers</h4>
          {s.containers.length === 0 ? <p className="text-sm text-slate-500">none</p> : <ul className="text-sm">{s.containers.map((c) => <li key={c.id}><span className="mono">{c.number}</span> · {c.size_ft} ft {c.type}</li>)}</ul>}
          <h4 className="label">Seals</h4>
          {s.seals.length === 0 ? <p className="text-sm text-slate-500">none</p> : <ul className="text-sm">{s.seals.map((e) => <li key={e.id} className="flex items-center gap-2"><span className="mono">{e.seal_id}</span><Badge tone={e.status === 'armed' ? 'green' : e.status === 'breached' ? 'red' : 'slate'}>{e.status}</Badge><span className="text-xs text-slate-500">{e.provider}</span></li>)}</ul>}
        </div>
      </div>

      <div>
        <h4 className="label">Processing timeline</h4>
        {s.processing_events.length === 0 ? <Empty>No processing events</Empty> : (
          <ol className="relative ml-2 border-l border-slate-200 pl-4 dark:border-slate-800">
            {s.processing_events.map((e) => (
              <li key={e.id} className="relative mb-2 text-sm">
                <span className={`absolute -left-[21px] top-1.5 h-2.5 w-2.5 rounded-full ${e.status === 'blocked' ? 'bg-rose-600' : e.status === 'started' ? 'bg-amber-500' : 'bg-brand-500'}`} aria-hidden="true" />
                <span className="font-medium">{titleCase(e.stage)}</span> <Badge tone="slate">{e.status}</Badge> <span className="text-xs text-slate-500">{fmtDateTime(e.occurred_at)} · {e.source}</span>
                {e.notes && <div className="text-xs text-slate-600 dark:text-slate-300">{e.notes}</div>}
              </li>
            ))}
          </ol>
        )}
      </div>

      <div>
        <h4 className="label">Weighings</h4>
        {s.weighings.length === 0 ? <Empty>No weighings linked to this shipment yet</Empty> : (
          <Table head={['Time', 'Station', 'GVM', 'Decision', 'Source']} dense>
            {s.weighings.map((w) => <tr key={w.id} className="tr"><td className="td">{fmtDateTime(w.occurred_at)}</td><td className="td">{code(w.station_id)}</td><td className="td tabular-nums">{fmtKg(w.gvm_kg)} ± {w.u_kg}</td><td className="td"><DecisionBadge decision={w.decision} size="sm" /></td><td className="td"><SourceBadge source={w.source} /></td></tr>)}
          </Table>
        )}
      </div>

      <div>
        <h4 className="label">Tickets</h4>
        {s.tickets.length === 0 ? <Empty>No tickets</Empty> : (
          <ul className="flex flex-wrap gap-2">
            {s.tickets.map((t) => (
              <li key={t.id}><button className={`btn-secondary text-xs ${ticketId === t.id ? 'ring-2 ring-brand-500' : ''}`} onClick={() => setTicketId(ticketId === t.id ? null : t.id)}><Badge tone={t.type === 'static_certified' ? 'green' : 'amber'}>{t.type}</Badge> <DecisionBadge decision={t.decision} size="sm" /> {fmtKg(t.gvm_kg)} <SourceBadge source={t.source} /></button></li>
            ))}
          </ul>
        )}
        {ticketId && <div className="mt-3"><TicketCard ticketId={ticketId} /></div>}
      </div>
    </div>
  );
}

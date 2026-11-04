import { useState } from 'react';
import { tickets as ticketsApi } from '../api/endpoints';
import type { DecisionOut, GroupMargin, TicketOut, WeighingOut } from '../api/types';
import { useQuery } from '../hooks/useQuery';
import { fmtDateTime, fmtKg, fmtPct, kmh, titleCase } from '../lib/format';
import { Badge, DecisionBadge, Empty, ErrorBanner, KV, SourceBadge, Spinner, Table } from './ui';

export function AxleTable({ ev }: { ev: WeighingOut }) {
  if (!ev.axles.length) return <Empty>No axle readings on this event</Empty>;
  return (
    <Table head={['Axle', 'Load', '± U (k=2)', 'Group', 'Spacing to next']} dense>
      {ev.axles.map((a) => (
        <tr key={a.axle_index} className="tr">
          <td className="td tabular-nums">{a.axle_index + 1}</td>
          <td className="td tabular-nums font-medium">{fmtKg(a.load_kg)}</td>
          <td className="td tabular-nums text-slate-500">± {fmtKg(a.uncertainty_kg)}</td>
          <td className="td">G{a.group_no}</td>
          <td className="td tabular-nums">{a.spacing_to_next_m !== null ? `${a.spacing_to_next_m.toFixed(2)} m` : '—'}</td>
        </tr>
      ))}
      <tr className="tr bg-slate-50 dark:bg-slate-950/60">
        <td className="td font-semibold">GVM</td>
        <td className="td font-semibold tabular-nums">{fmtKg(ev.gvm_kg)}</td>
        <td className="td tabular-nums text-slate-500">± {fmtKg(ev.gvm_uncertainty_kg)}</td>
        <td className="td" colSpan={2}>{ev.detected_axle_config ?? '—'} · class {ev.class_code ?? '—'} · {kmh(ev.speed_mps)}</td>
      </tr>
    </Table>
  );
}

export function GroupMargins({ groups }: { groups: GroupMargin[] | undefined }) {
  if (!groups?.length) return null;
  const tone = (s: string) => (s === 'over' ? 'red' : s === 'marginal' ? 'amber' : 'green');
  return (
    <Table head={['Group', 'Axles', 'Measured', '± U', 'Limit (+tol.)', 'Status']} dense>
      {groups.map((g) => (
        <tr key={g.group_no} className="tr">
          <td className="td">G{g.group_no}</td><td className="td">{g.axles}</td>
          <td className="td tabular-nums">{fmtKg(g.measured_kg)}</td><td className="td tabular-nums">± {fmtKg(g.u_kg)}</td>
          <td className="td tabular-nums">{fmtKg(g.limit_kg)} <span className="text-slate-500">({fmtKg(g.limit_with_tolerance_kg)})</span></td>
          <td className="td"><Badge tone={tone(g.status)}>{g.status}</Badge></td>
        </tr>
      ))}
    </Table>
  );
}

export function DecisionPanel({ d, compact }: { d: DecisionOut | null; compact?: boolean }) {
  if (!d) return <Empty>No clearance decision recorded</Empty>;
  const instruction = d.decision === 'GREEN' ? 'Proceed — no stop required' : d.decision === 'AMBER' ? 'Divert to static scale for verification' : 'Divert to inspection bay';
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <DecisionBadge decision={d.decision} size="lg" />
        <div>
          <div className="font-medium">{instruction}</div>
          <div className="text-xs text-slate-500">{d.latency_ms} ms · engine {d.engine_version} · limits {d.limits_version}{d.audit_selected && ' · random audit'}</div>
        </div>
      </div>
      {d.explanation && <p className="text-sm text-slate-700 dark:text-slate-300">{d.explanation}</p>}
      {!compact && (
        <>
          <div>
            <h4 className="label">Rules fired</h4>
            {d.rules_fired.length === 0 ? <p className="text-sm text-slate-500">None — all rules clear.</p> : (
              <ul className="space-y-1">
                {d.rules_fired.map((r) => (
                  <li key={r.rule} className="flex items-start gap-2 text-sm">
                    <Badge tone={r.severity === 'RED' ? 'red' : r.severity === 'AMBER' ? 'amber' : 'slate'}>{r.severity}</Badge>
                    <span><span className="font-mono text-xs">{r.rule}</span> — {r.detail}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <h4 className="label">Margins</h4>
            <GroupMargins groups={d.margins.groups} />
            {d.margins.gvm && (
              <div className="mt-2 text-xs text-slate-600 dark:text-slate-300">GVM margin: {Object.entries(d.margins.gvm).map(([k, v]) => `${k}=${typeof v === 'number' ? v.toLocaleString() : String(v)}`).join(' · ')}</div>
            )}
            {d.margins.declaration && (
              <div className="mt-1 text-xs text-slate-600 dark:text-slate-300">Declaration: expected {fmtKg(d.margins.declaration.expected_gvm_kg)}, diff {d.margins.declaration.diff_kg > 0 ? '+' : ''}{fmtKg(d.margins.declaration.diff_kg)}, tolerance {fmtKg(d.margins.declaration.tolerance_kg)}</div>
            )}
          </div>
          <KV items={[
            ['Evidence hash', <span className="mono break-all">{d.evidence_hash}</span>],
            ['Static verified GVM', d.static_verified_gvm_kg !== null ? fmtKg(d.static_verified_gvm_kg) : 'not yet'],
            ['Override', d.override_reason ?? 'none'],
            ['Ticket', d.ticket_type ? <span>{d.ticket_type === 'static_certified' ? 'Static certified (legal)' : 'Pre-screen (not legal)'} · <span className="mono">{d.ticket_id}</span></span> : '—'],
          ]} />
        </>
      )}
    </div>
  );
}

export function IdentityPanel({ ev }: { ev: WeighingOut }) {
  const i = ev.identity;
  if (!i) return <Empty>No identity event</Empty>;
  const tone = i.method === 'conflict' ? 'red' : i.confidence >= 0.9 ? 'green' : 'amber';
  return (
    <KV items={[
      ['Resolved plate', <span className="font-semibold">{ev.plate ?? 'unregistered / unknown'}</span>],
      ['Method', <Badge tone={tone}>{i.method}</Badge>],
      ['Fused confidence', fmtPct(i.confidence)],
      ['ANPR', i.anpr_plate ? `${i.anpr_plate} (${fmtPct(i.anpr_confidence)})` : 'no read'],
      ['RFID', i.rfid_epc ? <span className="mono">{i.rfid_epc} ({fmtPct(i.rfid_confidence)})</span> : 'no tag read'],
      ['Explanation', i.explanation ?? '—'],
    ]} />
  );
}

export function SensorHealthGrid({ health }: { health: Record<string, string> }) {
  const entries = Object.entries(health);
  if (!entries.length) return <Empty>No sensor health snapshot</Empty>;
  return (
    <ul className="grid grid-cols-2 gap-1 sm:grid-cols-3">
      {entries.map(([k, v]) => (
        <li key={k} className="flex items-center justify-between rounded border border-slate-200 px-2 py-1 text-xs dark:border-slate-800">
          <span className="truncate">{titleCase(k)}</span><Badge tone={v === 'ok' ? 'green' : v === 'degraded' ? 'amber' : 'red'}>{v}</Badge>
        </li>
      ))}
    </ul>
  );
}

export function TicketCard({ ticketId }: { ticketId: string }) {
  const t = useQuery<TicketOut>(() => ticketsApi.get(ticketId), [ticketId]);
  const qr = useQuery<string>(() => ticketsApi.qrSvg(ticketId), [ticketId]);
  if (t.loading) return <Spinner label="Loading ticket" />;
  if (t.error) return <ErrorBanner error={t.error} />;
  const tk = t.data!;
  const legal = tk.type === 'static_certified';
  return (
    <div className="flex flex-col gap-3 sm:flex-row">
      <div className="shrink-0">
        {qr.data ? (
          <div className="w-36 rounded bg-white p-1 [&>svg]:h-auto [&>svg]:w-full" aria-label="Ticket QR code" dangerouslySetInnerHTML={{ __html: qr.data }} />
        ) : <div className="h-36 w-36 animate-pulse rounded bg-slate-200 dark:bg-slate-800" />}
        <a className="mt-1 block text-center text-xs text-brand-700 underline dark:text-brand-300" href={`/verify/${tk.qr_token}`} target="_blank" rel="noreferrer">Open public verify page</a>
      </div>
      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={legal ? 'green' : 'amber'}>{legal ? 'LEGAL WEIGHT CERTIFICATE' : 'PRE-SCREEN ONLY'}</Badge>
          <SourceBadge source={tk.payload.source} />
          <Badge tone={tk.signature_valid ? 'green' : 'red'}>{tk.signature_valid ? 'signature valid' : 'SIGNATURE INVALID'}</Badge>
        </div>
        <p className="text-xs text-slate-600 dark:text-slate-300">{tk.payload.legal_status}</p>
        <KV items={[
          ['Plate', tk.payload.plate ?? '—'], ['Station', tk.payload.station], ['GVM', fmtKg(tk.payload.gvm_kg)], ['Decision', <DecisionBadge decision={tk.payload.decision} size="sm" />],
          ['Issued', fmtDateTime(tk.payload.occurred_at)], ['Signer', <span className="mono">{tk.signer_key_id}</span>],
        ]} />
      </div>
    </div>
  );
}

/** Compact one-line weighing row used in feeds and history tables. */
export function WeighingRow({ ev, onSelect, selected }: { ev: WeighingOut; onSelect?: (ev: WeighingOut) => void; selected?: boolean }) {
  return (
    <tr className={`tr ${onSelect ? 'cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/60' : ''} ${selected ? 'bg-brand-50 dark:bg-brand-900/30' : ''}`} onClick={() => onSelect?.(ev)} tabIndex={onSelect ? 0 : undefined} onKeyDown={(e) => { if (onSelect && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); onSelect(ev); } }}>
      <td className="td whitespace-nowrap tabular-nums">{fmtDateTime(ev.occurred_at)}</td>
      <td className="td font-medium">{ev.plate ?? <span className="text-slate-400">unknown</span>}</td>
      <td className="td tabular-nums">{fmtKg(ev.gvm_kg)} <span className="text-slate-400">± {ev.gvm_uncertainty_kg}</span></td>
      <td className="td">{ev.detected_axle_config ?? '—'}</td>
      <td className="td"><DecisionBadge decision={ev.decision?.decision} size="sm" /></td>
      <td className="td"><SourceBadge source={ev.source} /></td>
    </tr>
  );
}

export function WeighingHistoryTable({ events, onSelect, selectedId }: { events: WeighingOut[]; onSelect?: (ev: WeighingOut) => void; selectedId?: string | null }) {
  const [limit, setLimit] = useState(25);
  if (!events.length) return <Empty>No weighing records</Empty>;
  return (
    <>
      <Table head={['Time', 'Plate', 'GVM', 'Axles', 'Decision', 'Source']}>
        {events.slice(0, limit).map((ev) => <WeighingRow key={ev.id} ev={ev} onSelect={onSelect} selected={selectedId === ev.id} />)}
      </Table>
      {events.length > limit && <button className="btn-ghost mt-2 text-xs" onClick={() => setLimit((l) => l + 25)}>Show more ({events.length - limit} more)</button>}
    </>
  );
}

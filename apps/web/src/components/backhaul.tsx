import { backhaul as backhaulApi } from '../api/endpoints';
import type { MatchOut } from '../api/types';
import { useMutation } from '../hooks/useQuery';
import { fmtKes, fmtNum, titleCase } from '../lib/format';
import { Badge, ErrorBanner } from './ui';

/** One proposed backhaul match with the side-specific accept/reject (two-party acceptance) and delivery action. */
export function MatchCard({ m, side, orgId, onChanged }: { m: MatchOut; side: 'transporter' | 'owner'; orgId: string | null; onChanged: () => void }) {
  const decide = useMutation((accept: boolean) => (side === 'transporter' ? backhaulApi.transporterDecision(m.id, { accept }) : backhaulApi.ownerDecision(m.id, { accept })));
  const deliver = useMutation(() => backhaulApi.deliver(m.id, {}));
  const mine = side === 'owner' || m.transporter_org_id === orgId;
  const canDecide = mine && (side === 'transporter' ? ['proposed', 'owner_accepted'].includes(m.status) : ['proposed', 'transporter_accepted'].includes(m.status));
  const tone = m.status === 'assigned' || m.status === 'delivered' ? 'green' : m.status === 'rejected' || m.status === 'cancelled' ? 'slate' : 'teal';
  return (
    <div className="rounded border border-slate-200 p-2 text-xs dark:border-slate-800">
      <div className="flex flex-wrap items-center justify-between gap-1"><span className="font-medium">{m.plate} · {m.transporter_name ?? m.transporter_org_id}</span><Badge tone={tone}>{titleCase(m.status)}</Badge></div>
      <div className="mt-1 grid grid-cols-3 gap-1 text-slate-600 dark:text-slate-300 sm:grid-cols-6">
        <span>score <b>{fmtNum(m.score, 2)}</b></span><span>extra <b>{fmtNum(m.extra_km, 0)} km</b></span><span>fuel <b>{fmtNum(m.fuel_litres, 0)} L</b></span><span>fuel cost <b>{fmtKes(m.fuel_cost_kes)}</b></span><span>revenue <b>{fmtKes(m.revenue_kes)}</b></span><span>CO₂ avoided <b>{fmtNum(m.co2_avoided_kg, 0)} kg</b></span>
      </div>
      <details className="mt-1"><summary className="cursor-pointer text-slate-500">Agent explanation (advisory)</summary><pre className="mt-1 overflow-x-auto rounded bg-slate-50 p-2 text-[11px] dark:bg-slate-950">{JSON.stringify(m.explanation, null, 1)}</pre></details>
      {canDecide && (
        <div className="mt-2 flex gap-1">
          <button className="btn-primary px-2 py-1 text-xs" disabled={decide.busy} onClick={async () => { if (await decide.run(true)) onChanged(); }}>Accept</button>
          <button className="btn-secondary px-2 py-1 text-xs" disabled={decide.busy} onClick={async () => { if (await decide.run(false)) onChanged(); }}>Reject</button>
        </div>
      )}
      {side === 'transporter' && mine && m.status === 'assigned' && <button className="btn-secondary mt-2 px-2 py-1 text-xs" disabled={deliver.busy} onClick={async () => { if (await deliver.run()) onChanged(); }}>Mark delivered</button>}
      <ErrorBanner error={decide.error ?? deliver.error} className="mt-1" />
    </div>
  );
}

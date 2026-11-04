import { type FormEvent, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { tickets as ticketsApi } from '../api/endpoints';
import type { VerifyOut } from '../api/types';
import { DecisionBadge, ErrorBanner, Field, KV, SourceBadge, Spinner } from '../components/ui';
import { useQuery } from '../hooks/useQuery';
import { fmtDateTime, fmtKg } from '../lib/format';

/** Public, unauthenticated ticket verification: GET /api/v1/tickets/verify/{qr_token}. */
export default function Verify() {
  const { qrToken } = useParams<{ qrToken: string }>();
  const nav = useNavigate();
  const [manual, setManual] = useState('');
  const q = useQuery<VerifyOut>(() => ticketsApi.verify(qrToken!), [qrToken], { enabled: !!qrToken });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const t = manual.trim();
    // Accept either the raw token or a full verify URL pasted from a QR reader.
    const m = t.match(/\/verify\/([^/?#]+)/);
    nav(`/verify/${encodeURIComponent(m ? m[1] : t)}`);
  };

  return (
    <main className="mx-auto min-h-screen max-w-lg px-4 py-6">
      <header className="mb-4 flex items-center gap-2">
        <img src="/favicon.svg" alt="" width="28" height="28" />
        <div><h1 className="text-lg font-semibold">Weighing ticket verification</h1><p className="text-xs text-slate-500">KIFARU PORTOS · public check · no sign-in required</p></div>
      </header>

      {!qrToken && (
        <form onSubmit={submit} className="card space-y-3 p-4">
          <Field label="QR token or verify URL" required>{(id) => <input id={id} className="input" value={manual} onChange={(e) => setManual(e.target.value)} placeholder="Scan the QR code or paste its link" required />}</Field>
          <button className="btn-primary" type="submit">Verify</button>
        </form>
      )}

      {qrToken && q.loading && <Spinner label="Checking ticket" />}
      {qrToken && q.error && <ErrorBanner error={q.error} />}
      {qrToken && q.data && <Result r={q.data} />}

      {qrToken && <a className="btn-ghost mt-4 text-sm" href="/verify">Check another ticket</a>}
      <p className="mt-6 text-xs text-slate-500">A pre-screen ticket is produced by a weigh-in-motion pass and is informational only. Only a static-scale ticket is a legal weight certificate. Tickets are Ed25519-signed by the platform; the signature is validated server-side on every check.</p>
    </main>
  );
}

function Result({ r }: { r: VerifyOut }) {
  if (!r.valid) {
    return (
      <div role="alert" className="rounded-xl border-2 border-rose-600 bg-rose-50 p-5 text-rose-900 dark:bg-rose-950/50 dark:text-rose-100">
        <div className="text-2xl font-bold">NOT VALID</div>
        <p className="mt-1 text-sm">{r.ticket_type ? 'The ticket exists but its signature does not verify — treat as tampered.' : 'No ticket matches this QR token.'}</p>
      </div>
    );
  }
  const legal = r.ticket_type === 'static_certified';
  return (
    <div className="space-y-4">
      <div className={`rounded-xl border-2 p-5 ${legal ? 'border-green-600 bg-green-50 dark:bg-green-950/40' : 'border-amber-500 bg-amber-50 dark:bg-amber-950/40'}`}>
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-600 dark:text-slate-300">Signature valid · legal status</div>
        <div className="mt-1 text-xl font-bold leading-tight">{legal ? 'LEGAL WEIGHT CERTIFICATE' : 'PRE-SCREEN ONLY'}</div>
        <p className="mt-1 text-sm">{r.legal_status}</p>
      </div>
      <div className="card p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <DecisionBadge decision={r.decision} size="lg" />
          <SourceBadge source={r.source} />
          {r.source !== 'live' && <span className="text-xs text-slate-500">This record was produced by the simulator, not by a real weighing.</span>}
        </div>
        <KV items={[
          ['Plate', <span className="text-base font-semibold">{r.plate ?? '—'}</span>],
          ['Gross vehicle mass', fmtKg(r.gvm_kg)],
          ['Station', r.station ?? '—'],
          ['Weighed at', fmtDateTime(r.occurred_at)],
          ['Ticket type', r.ticket_type ?? '—'],
          ['Evidence hash', <span className="mono break-all">{r.evidence_hash ?? '—'}</span>],
        ]} />
      </div>
    </div>
  );
}

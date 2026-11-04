import { Fragment, type ReactNode, useEffect, useId, useState } from 'react';
import { ApiError } from '../api/client';
import type { Decision, Source } from '../api/types';
import { titleCase } from '../lib/format';

export function Card({ title, subtitle, actions, children, className = '', id }: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; id?: string }) {
  return (
    <section className={`card ${className}`} id={id} aria-label={typeof title === 'string' ? title : undefined}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-2 border-b border-slate-100 px-4 py-3 dark:border-slate-800">
          <div>
            {title && <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">{title}</h2>}
            {subtitle && <p className="text-xs text-slate-500 dark:text-slate-400">{subtitle}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, tone = 'default' }: { label: string; value: ReactNode; hint?: ReactNode; tone?: 'default' | 'green' | 'amber' | 'red' | 'teal' }) {
  const tones: Record<string, string> = {
    default: 'text-slate-900 dark:text-slate-50',
    green: 'text-decision-green', amber: 'text-decision-amber', red: 'text-decision-red', teal: 'text-brand-700 dark:text-brand-300',
  };
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 dark:border-slate-800 dark:bg-slate-950">
      <div className="text-[11px] font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</div>
      <div className={`text-xl font-semibold tabular-nums ${tones[tone]}`}>{value}</div>
      {hint && <div className="text-xs text-slate-500 dark:text-slate-400">{hint}</div>}
    </div>
  );
}

export function Badge({ children, tone = 'slate', title }: { children: ReactNode; tone?: 'slate' | 'teal' | 'green' | 'amber' | 'red' | 'blue' | 'violet'; title?: string }) {
  const t: Record<string, string> = {
    slate: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200',
    teal: 'bg-brand-100 text-brand-800 dark:bg-brand-900/50 dark:text-brand-200',
    green: 'bg-green-100 text-green-800 dark:bg-green-900/50 dark:text-green-200',
    amber: 'bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200',
    red: 'bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-200',
    blue: 'bg-sky-100 text-sky-800 dark:bg-sky-900/50 dark:text-sky-200',
    violet: 'bg-violet-100 text-violet-800 dark:bg-violet-900/50 dark:text-violet-200',
  };
  return <span title={title} className={`inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${t[tone]}`}>{children}</span>;
}

/** Shown on every weighing record. LIVE only when source === "live". */
export function SourceBadge({ source }: { source: Source | null | undefined }) {
  if (!source) return <Badge tone="slate">unknown source</Badge>;
  if (source === 'live') return <Badge tone="teal" title="Measured by a station gateway">LIVE</Badge>;
  if (source === 'forecast') return <Badge tone="violet" title="Model output">FORECAST</Badge>;
  return <Badge tone="slate" title="Synthetic data from the simulator — not a real measurement">{source.toUpperCase()}</Badge>;
}

export function DecisionBadge({ decision, size = 'md' }: { decision: Decision | null | undefined; size?: 'sm' | 'md' | 'lg' }) {
  const cls: Record<string, string> = { GREEN: 'bg-decision-green text-white', AMBER: 'bg-decision-amber text-white', RED: 'bg-decision-red text-white' };
  const sz = size === 'lg' ? 'px-4 py-2 text-xl' : size === 'sm' ? 'px-1.5 py-0.5 text-[11px]' : 'px-2 py-1 text-xs';
  if (!decision) return <span className={`inline-flex rounded font-bold bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-100 ${sz}`}>PENDING</span>;
  return <span className={`inline-flex rounded font-bold tracking-wide ${cls[decision] ?? 'bg-slate-500 text-white'} ${sz}`} aria-label={`Decision ${decision}`}>{decision}</span>;
}

export function StatusDot({ status }: { status: string }) {
  const map: Record<string, string> = { operational: 'bg-brand-500', ok: 'bg-brand-500', ready: 'bg-brand-500', degraded: 'bg-amber-500', busy: 'bg-amber-500', offline: 'bg-rose-600', fault: 'bg-rose-600', closed: 'bg-slate-400', open: 'bg-rose-600' };
  return <span className={`inline-block h-2.5 w-2.5 rounded-full ${map[status] ?? 'bg-slate-400'}`} aria-hidden="true" />;
}

export function ErrorBanner({ error, className = '' }: { error: ApiError | Error | string | null | undefined; className?: string }) {
  if (!error) return null;
  const msg = typeof error === 'string' ? error : error.message;
  const status = error instanceof ApiError ? error.status : undefined;
  const label = status === 401 ? 'Not authenticated' : status === 403 ? 'Forbidden' : status === 409 ? 'Conflict' : status === 422 ? 'Validation error' : status ? `Error ${status}` : 'Error';
  return (
    <div role="alert" className={`rounded-md border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-900 dark:border-rose-800 dark:bg-rose-950/50 dark:text-rose-100 ${className}`}>
      <span className="font-semibold">{label}: </span>{msg}
    </div>
  );
}

export function Notice({ children, tone = 'info', className = '' }: { children: ReactNode; tone?: 'info' | 'warn' | 'ok'; className?: string }) {
  const t = { info: 'border-sky-300 bg-sky-50 text-sky-900 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-100', warn: 'border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-100', ok: 'border-green-300 bg-green-50 text-green-900 dark:border-green-800 dark:bg-green-950/40 dark:text-green-100' };
  return <div role="status" className={`rounded-md border px-3 py-2 text-sm ${t[tone]} ${className}`}>{children}</div>;
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-brand-600" aria-hidden="true" />{label}…
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-md border border-dashed border-slate-300 px-3 py-4 text-center text-sm text-slate-500 dark:border-slate-700">{children}</p>;
}

/** Labelled input/select/textarea with optional field-level 422 message. */
export function Field({ label, error, hint, children, required }: { label: string; error?: string; hint?: string; children: (id: string) => ReactNode; required?: boolean }) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="label">{label}{required && <span className="text-rose-600"> *</span>}</label>
      {children(id)}
      {hint && !error && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
      {error && <p className="mt-1 text-xs text-rose-700 dark:text-rose-300" role="alert">{error}</p>}
    </div>
  );
}

export function Table({ head, children, dense }: { head: ReactNode[]; children: ReactNode; dense?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className={`min-w-full ${dense ? 'text-xs' : 'text-sm'}`}>
        <thead className="bg-slate-50 dark:bg-slate-950/60"><tr>{head.map((h, i) => <th key={i} scope="col" className="th">{h}</th>)}</tr></thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1 border-b border-slate-200 dark:border-slate-800">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${value === t.id ? 'border-brand-600 text-brand-700 dark:text-brand-300' : 'border-transparent text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'}`}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
      {items.map(([k, v]) => (<Fragment key={k}><dt className="text-slate-500 dark:text-slate-400">{k}</dt><dd className="break-words">{v}</dd></Fragment>))}
    </dl>
  );
}

export function Pill({ value }: { value: string }) { return <Badge tone="slate">{titleCase(value)}</Badge>; }

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="inline-flex cursor-pointer items-center gap-2 text-sm">
      <input type="checkbox" className="h-4 w-4 rounded border-slate-300 text-brand-600 focus:ring-brand-500" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  );
}

/** Confirm dialog driven by state; avoids window.confirm so it is keyboard accessible and styled. */
export function Confirm({ open, title, body, onConfirm, onCancel, confirmLabel = 'Confirm', danger }: { open: boolean; title: string; body?: ReactNode; onConfirm: () => void; onCancel: () => void; confirmLabel?: string; danger?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [open, onCancel]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 p-4" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
      <div className="card w-full max-w-md p-5">
        <h3 id="confirm-title" className="text-base font-semibold">{title}</h3>
        {body && <div className="mt-2 text-sm text-slate-600 dark:text-slate-300">{body}</div>}
        <div className="mt-4 flex justify-end gap-2">
          <button className="btn-secondary" onClick={onCancel}>Cancel</button>
          <button className={danger ? 'btn-danger' : 'btn-primary'} onClick={onConfirm} autoFocus>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}

/** Small helper to show "x s ago" updating each second. */
export function useTick(ms = 1000): number {
  const [t, setT] = useState(Date.now());
  useEffect(() => { const id = window.setInterval(() => setT(Date.now()), ms); return () => window.clearInterval(id); }, [ms]);
  return t;
}

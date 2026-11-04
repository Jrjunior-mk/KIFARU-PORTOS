/** Display helpers. Storage is UTC/SI; UI shows Africa/Nairobi and tonnes where appropriate. */
const TZ = 'Africa/Nairobi';

export function fmtTime(iso: string | null | undefined, withDate = false): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString('en-KE', withDate
    ? { timeZone: TZ, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }
    : { timeZone: TZ, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}
export function fmtDateTime(iso: string | null | undefined): string { return fmtTime(iso, true); }
export function fmtClock(iso: string | null | undefined): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleTimeString('en-KE', { timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false });
}
export function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return '—';
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)} s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${(s / 3600).toFixed(1)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}
export function fmtKg(kg: number | null | undefined, digits = 0): string {
  if (kg === null || kg === undefined) return '—';
  return `${kg.toLocaleString('en-KE', { maximumFractionDigits: digits })} kg`;
}
export function fmtTonnes(kg: number | null | undefined, digits = 2): string {
  if (kg === null || kg === undefined) return '—';
  return `${(kg / 1000).toFixed(digits)} t`;
}
export function fmtPct(x: number | null | undefined, digits = 0): string {
  if (x === null || x === undefined) return '—';
  return `${(x * 100).toFixed(digits)} %`;
}
export function fmtDuration(s: number | null | undefined): string {
  if (s === null || s === undefined) return '—';
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  return `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min`;
}
export function fmtKes(x: number | null | undefined): string {
  if (x === null || x === undefined) return '—';
  return `KES ${Math.round(x).toLocaleString('en-KE')}`;
}
export function fmtNum(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined) return '—';
  return x.toLocaleString('en-KE', { maximumFractionDigits: digits });
}
export function kmh(mps: number): string { return `${(mps * 3.6).toFixed(0)} km/h`; }
export function titleCase(s: string): string { return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()); }
export function short(id: string | null | undefined, n = 8): string { return id ? `${id.slice(0, n)}…` : '—'; }

/** Local datetime-input value (YYYY-MM-DDTHH:mm) -> ISO string. */
export function localToIso(v: string): string { return new Date(v).toISOString(); }
export function isoToLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

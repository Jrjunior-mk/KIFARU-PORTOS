/** Client-side ISO 6346 container number check (mirrors apps/api/kifaru/routers/shipments.py). The server remains authoritative (422). */
const LETTER_VALUES: Record<string, number> = (() => {
  const out: Record<string, number> = {};
  let v = 10;
  for (const ch of 'ABCDEFGHIJKLMNOPQRSTUVWXYZ') {
    if (v % 11 === 0) v += 1;
    out[ch] = v;
    v += 1;
  }
  return out;
})();

export function iso6346CheckDigit(number: string): number {
  let total = 0;
  for (let i = 0; i < 10; i++) {
    const ch = number[i];
    const val = /[A-Z]/.test(ch) ? LETTER_VALUES[ch] : Number(ch);
    total += val * 2 ** i;
  }
  return (total % 11) % 10;
}

export function validateContainerNumber(raw: string): string | null {
  const v = raw.toUpperCase().trim();
  if (v.length !== 11) return 'Must be 11 characters (4 letters + 7 digits)';
  if (!/^[A-Z]{4}\d{7}$/.test(v)) return 'Format: 4 letters then 7 digits, e.g. MSKU1234565';
  if (iso6346CheckDigit(v) !== Number(v[10])) return `ISO 6346 check digit invalid (expected ${iso6346CheckDigit(v)})`;
  return null;
}

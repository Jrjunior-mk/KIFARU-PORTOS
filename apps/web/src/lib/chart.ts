/**
 * Chart tokens (validated with the dataviz palette validator in light and dark mode).
 * Series: teal (primary) + magenta (secondary). Decision colours are status colours and are never used for ordinary series.
 */
import { useEffect, useState } from 'react';

export const SERIES = { primary: '#0d9488', secondary: '#c026d3' } as const;
export const DECISION_COLOR: Record<string, string> = { GREEN: '#16a34a', AMBER: '#d97706', RED: '#dc2626' };

export function useDarkMode(): boolean {
  const [dark, setDark] = useState(() => window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const h = (e: MediaQueryListEvent) => setDark(e.matches);
    mq.addEventListener('change', h);
    return () => mq.removeEventListener('change', h);
  }, []);
  return dark;
}

export function chartTheme(dark: boolean) {
  return {
    grid: dark ? '#1e293b' : '#e2e8f0',
    axis: dark ? '#64748b' : '#94a3b8',
    text: dark ? '#cbd5e1' : '#475569',
    tooltip: { backgroundColor: dark ? '#0f172a' : '#ffffff', border: `1px solid ${dark ? '#334155' : '#e2e8f0'}`, borderRadius: 6, color: dark ? '#e2e8f0' : '#0f172a', fontSize: 12 },
    band: dark ? 'rgba(13,148,136,0.25)' : 'rgba(13,148,136,0.18)',
  };
}

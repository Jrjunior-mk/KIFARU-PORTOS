import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { notifications as notifApi } from '../api/endpoints';
import type { LiveEvent, NotificationOut } from '../api/types';
import { useAuth } from '../auth/AuthContext';
import { useLiveEvents } from '../hooks/useLiveEvents';
import { useQuery } from '../hooks/useQuery';
import { fmtAgo } from '../lib/format';
import { routesFor } from '../lib/roles';
import { Badge, Empty, Spinner } from './ui';

export default function Shell() {
  const { me, session, roles, logout } = useAuth();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const routes = routesFor(roles);

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <div className="mx-auto flex max-w-screen-2xl items-center gap-3 px-4 py-2">
          <button className="btn-ghost p-2 md:hidden" aria-label="Toggle navigation" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M3 5h14M3 10h14M3 15h14" /></svg>
          </button>
          <NavLink to="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <img src="/favicon.svg" alt="" width="24" height="24" />
            <span>KIFARU <span className="text-brand-600 dark:text-brand-400">PORTOS</span></span>
          </NavLink>
          <nav aria-label="Primary" className="ml-4 hidden items-center gap-1 md:flex">
            {routes.map((r) => (
              <NavLink key={r.path} to={r.path} className={({ isActive }) => `rounded-md px-3 py-1.5 text-sm font-medium ${isActive ? 'bg-brand-50 text-brand-800 dark:bg-brand-900/40 dark:text-brand-200' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'}`}>
                {r.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <Bell />
            <div className="hidden text-right text-xs leading-tight sm:block">
              <div className="font-medium">{me?.full_name ?? session?.full_name}</div>
              <div className="text-slate-500">{me?.org_name ?? roles.join(', ')}</div>
            </div>
            <button className="btn-secondary px-2 py-1 text-xs" onClick={async () => { await logout(); nav('/login'); }}>Sign out</button>
          </div>
        </div>
        {open && (
          <nav aria-label="Primary mobile" className="border-t border-slate-200 px-4 py-2 md:hidden dark:border-slate-800">
            {routes.map((r) => (
              <NavLink key={r.path} to={r.path} onClick={() => setOpen(false)} className={({ isActive }) => `block rounded-md px-3 py-2 text-sm ${isActive ? 'bg-brand-50 text-brand-800 dark:bg-brand-900/40 dark:text-brand-200' : 'text-slate-700 dark:text-slate-200'}`}>
                {r.label}<span className="block text-xs text-slate-500">{r.description}</span>
              </NavLink>
            ))}
          </nav>
        )}
      </header>
      <main className="mx-auto w-full max-w-screen-2xl flex-1 px-4 py-4">
        <Outlet />
      </main>
      <footer className="border-t border-slate-200 px-4 py-2 text-center text-[11px] text-slate-500 dark:border-slate-800">
        Times shown in Africa/Nairobi. Records tagged SIMULATED are synthetic and never presented as live measurements. The static scale remains the legal reference.
      </footer>
    </div>
  );
}

function Bell() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const q = useQuery(() => notifApi.inbox(false), [], { pollMs: 60_000 });
  // Live push: refresh inbox when a notification event arrives for this user/org.
  useLiveEvents(['notification'], null, 50, (ev: LiveEvent) => { if (ev.type === 'notification') void q.refetch(); });
  const unread = (q.data ?? []).filter((n) => !n.read_at).length;

  useEffect(() => {
    if (!open) return;
    const h = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, [open]);

  const markRead = async (n: NotificationOut) => {
    if (n.read_at) return;
    await notifApi.markRead(n.id);
    q.setData((prev) => (prev ?? []).map((x) => (x.id === n.id ? { ...x, read_at: new Date().toISOString() } : x)));
  };

  return (
    <div className="relative" ref={ref}>
      <button className="btn-ghost relative p-2" aria-label={`Notifications, ${unread} unread`} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" /></svg>
        {unread > 0 && <span className="absolute -right-0.5 -top-0.5 min-w-[18px] rounded-full bg-brand-600 px-1 text-center text-[10px] font-bold text-white">{unread}</span>}
      </button>
      {open && (
        <div role="dialog" aria-label="Notifications" className="card absolute right-0 mt-1 w-80 max-w-[90vw] overflow-hidden">
          <div className="flex items-center justify-between border-b border-slate-100 px-3 py-2 text-sm font-semibold dark:border-slate-800">Inbox <Badge tone={unread ? 'teal' : 'slate'}>{unread} unread</Badge></div>
          <ul className="max-h-80 overflow-y-auto divide-y divide-slate-100 dark:divide-slate-800">
            {q.loading && <li className="p-3"><Spinner /></li>}
            {!q.loading && (q.data ?? []).length === 0 && <li className="p-3"><Empty>No notifications</Empty></li>}
            {(q.data ?? []).map((n) => (
              <li key={n.id}>
                <button className={`w-full px-3 py-2 text-left hover:bg-slate-50 dark:hover:bg-slate-800 ${n.read_at ? 'opacity-60' : ''}`} onClick={() => void markRead(n)}>
                  <div className="flex items-center justify-between gap-2 text-sm font-medium"><span>{n.title}</span><Badge tone="slate">{n.channel}</Badge></div>
                  <div className="text-xs text-slate-600 dark:text-slate-300">{n.body}</div>
                  <div className="text-[11px] text-slate-400">{fmtAgo(n.created_at)}{n.read_at ? ' · read' : ' · tap to mark read'}</div>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

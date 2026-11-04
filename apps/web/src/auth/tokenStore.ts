/** Token persistence (sessionStorage by default; localStorage when "remember this device" is chosen, needed for installed PWA). */
import type { Role, TokenOut } from '../api/types';

const KEY = 'kifaru.auth.v1';

export interface StoredSession {
  access_token: string;
  refresh_token: string;
  roles: Role[];
  org_id: string | null;
  user_id: string;
  full_name: string;
  mfa_required: boolean;
  access_exp: number; // epoch seconds
}

function decodeExp(jwt: string): number {
  try {
    const payload = JSON.parse(atob(jwt.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return Number(payload.exp) || 0;
  } catch {
    return 0;
  }
}

class TokenStore {
  private session: StoredSession | null = null;
  private persistent = false;
  private listeners = new Set<() => void>();

  constructor() {
    try {
      const local = localStorage.getItem(KEY);
      const sess = sessionStorage.getItem(KEY);
      if (local) { this.session = JSON.parse(local); this.persistent = true; }
      else if (sess) this.session = JSON.parse(sess);
    } catch { this.session = null; }
  }

  get current(): StoredSession | null { return this.session; }
  get access(): string | null { return this.session?.access_token ?? null; }
  get refresh(): string | null { return this.session?.refresh_token ?? null; }

  setPersistent(v: boolean) { this.persistent = v; }

  set(t: TokenOut) {
    this.session = {
      access_token: t.access_token, refresh_token: t.refresh_token, roles: t.roles, org_id: t.org_id, user_id: t.user_id,
      full_name: t.full_name, mfa_required: t.mfa_required, access_exp: decodeExp(t.access_token),
    };
    this.save();
  }

  clear() {
    this.session = null;
    try { localStorage.removeItem(KEY); sessionStorage.removeItem(KEY); } catch { /* ignore */ }
    this.emit();
  }

  isAccessExpiring(withinSeconds = 60): boolean {
    if (!this.session) return true;
    return this.session.access_exp - Date.now() / 1000 < withinSeconds;
  }

  subscribe(fn: () => void) { this.listeners.add(fn); return () => { this.listeners.delete(fn); }; }

  private save() {
    try {
      const raw = JSON.stringify(this.session);
      if (this.persistent) { localStorage.setItem(KEY, raw); sessionStorage.removeItem(KEY); }
      else { sessionStorage.setItem(KEY, raw); localStorage.removeItem(KEY); }
    } catch { /* storage unavailable (private mode) — session stays in memory */ }
    this.emit();
  }
  private emit() { for (const l of this.listeners) l(); }
}

export const tokenStore = new TokenStore();

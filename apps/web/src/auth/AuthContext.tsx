import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { auth as authApi } from '../api/endpoints';
import type { MeOut, Role, TokenOut } from '../api/types';
import { tokenStore, type StoredSession } from './tokenStore';

export interface AuthState {
  session: StoredSession | null;
  me: MeOut | null;
  loading: boolean;
  roles: Role[];
  hasRole: (...roles: Role[]) => boolean;
  login: (email: string, password: string, totp?: string, remember?: boolean) => Promise<TokenOut>;
  verifyMfa: (code: string) => Promise<TokenOut>;
  logout: () => Promise<void>;
  reloadMe: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<StoredSession | null>(tokenStore.current);
  const [me, setMe] = useState<MeOut | null>(null);
  const [loading, setLoading] = useState<boolean>(!!tokenStore.current);

  useEffect(() => tokenStore.subscribe(() => setSession(tokenStore.current)), []);

  const reloadMe = useCallback(async () => {
    if (!tokenStore.access) { setMe(null); setLoading(false); return; }
    try { setMe(await authApi.me()); } catch { setMe(null); } finally { setLoading(false); }
  }, []);

  useEffect(() => { void reloadMe(); }, [reloadMe, session?.user_id]);

  // Forced logout when a refresh fails (client.ts dispatches this).
  useEffect(() => {
    const h = () => { setMe(null); setSession(null); };
    window.addEventListener('kifaru:unauthorized', h);
    return () => window.removeEventListener('kifaru:unauthorized', h);
  }, []);

  // Silent refresh: renew the access token ~1 min before it expires while the tab is open.
  useEffect(() => {
    if (!session) return;
    const ms = Math.max(5_000, (session.access_exp - Date.now() / 1000 - 60) * 1000);
    const id = window.setTimeout(async () => {
      const rt = tokenStore.refresh;
      if (!rt) return;
      try { tokenStore.set(await authApi.refresh(rt)); } catch { tokenStore.clear(); }
    }, ms);
    return () => window.clearTimeout(id);
  }, [session]);

  const login = useCallback(async (email: string, password: string, totp?: string, remember = false) => {
    tokenStore.setPersistent(remember);
    const t = await authApi.login({ email, password, totp_code: totp || null });
    tokenStore.set(t);
    return t;
  }, []);

  const verifyMfa = useCallback(async (code: string) => {
    const t = await authApi.mfaVerify(code);
    tokenStore.set(t);
    return t;
  }, []);

  const logout = useCallback(async () => {
    const rt = tokenStore.refresh;
    try { if (rt) await authApi.logout(rt); } catch { /* best effort */ }
    tokenStore.clear();
    setMe(null);
  }, []);

  const roles = useMemo<Role[]>(() => me?.roles ?? session?.roles ?? [], [me, session]);
  const hasRole = useCallback((...rs: Role[]) => roles.includes('platform_admin') || rs.some((r) => roles.includes(r)), [roles]);

  const value = useMemo<AuthState>(() => ({ session, me, loading, roles, hasRole, login, verifyMfa, logout, reloadMe }), [session, me, loading, roles, hasRole, login, verifyMfa, logout, reloadMe]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error('useAuth outside AuthProvider');
  return v;
}

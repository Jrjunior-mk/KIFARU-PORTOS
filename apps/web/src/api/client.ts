/**
 * Fetch wrapper with bearer auth, silent refresh (rotating refresh tokens) and normalised API errors.
 * Access tokens last 15 minutes; on 401 the client refreshes once and retries the request.
 */
import { tokenStore } from '../auth/tokenStore';
import type { TokenOut } from './types';

export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? '';
export const API_PREFIX = `${API_BASE}/api/v1`;

export function wsUrl(path: string): string {
  const explicit = import.meta.env.VITE_WS_BASE as string | undefined;
  if (explicit) return explicit.replace(/\/$/, '') + path;
  if (API_BASE) return API_BASE.replace(/^http/, 'ws') + path;
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}${path}`;
}

export interface ValidationItem { loc: (string | number)[]; msg: string; type: string }

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? ApiError.describe(status, detail));
    this.status = status;
    this.detail = detail;
  }
  /** 422 detail list from pydantic, keyed by field path (e.g. "containers.0.number"). */
  get fieldErrors(): Record<string, string> {
    const out: Record<string, string> = {};
    if (Array.isArray(this.detail)) {
      for (const it of this.detail as ValidationItem[]) {
        const loc = (it.loc ?? []).filter((p) => p !== 'body').join('.');
        out[loc || '_'] = it.msg.replace(/^Value error, /, '');
      }
    }
    return out;
  }
  static describe(status: number, detail: unknown): string {
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) {
      return (detail as ValidationItem[])
        .map((d) => `${(d.loc ?? []).filter((p) => p !== 'body').join('.')}: ${d.msg.replace(/^Value error, /, '')}`)
        .join('; ');
    }
    switch (status) {
      case 401: return 'Not authenticated';
      case 403: return 'You do not have permission for this action';
      case 404: return 'Not found';
      case 409: return 'Conflict';
      case 423: return 'Account locked';
      case 429: return 'Too many requests';
      default: return `Request failed (${status})`;
    }
  }
}

let refreshing: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    const rt = tokenStore.refresh;
    if (!rt) return false;
    try {
      const r = await fetch(`${API_PREFIX}/auth/refresh`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: rt }),
      });
      if (!r.ok) { tokenStore.clear(); return false; }
      const t = (await r.json()) as TokenOut;
      tokenStore.set(t);
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

export interface RequestOpts { auth?: boolean; signal?: AbortSignal; raw?: boolean }

export async function request<T>(method: string, path: string, body?: unknown, opts: RequestOpts = {}): Promise<T> {
  const auth = opts.auth !== false;
  const doFetch = async (): Promise<Response> => {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (auth && tokenStore.access) headers.Authorization = `Bearer ${tokenStore.access}`;
    return fetch(`${API_PREFIX}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal: opts.signal });
  };
  let res = await doFetch();
  if (res.status === 401 && auth && tokenStore.refresh && !path.startsWith('/auth/login') && !path.startsWith('/auth/refresh')) {
    if (await refreshTokens()) res = await doFetch();
  }
  if (res.status === 401 && auth) {
    tokenStore.clear();
    window.dispatchEvent(new CustomEvent('kifaru:unauthorized'));
  }
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try { detail = (await res.json()).detail; } catch { /* no body */ }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  if (opts.raw) return (await res.text()) as unknown as T;
  return (await res.json()) as T;
}

export const http = {
  get: <T>(path: string, opts?: RequestOpts) => request<T>('GET', path, undefined, opts),
  post: <T>(path: string, body?: unknown, opts?: RequestOpts) => request<T>('POST', path, body ?? {}, opts),
  patch: <T>(path: string, body?: unknown, opts?: RequestOpts) => request<T>('PATCH', path, body ?? {}, opts),
  del: <T>(path: string, opts?: RequestOpts) => request<T>('DELETE', path, undefined, opts),
};

/** Ensure the access token is valid before opening a WebSocket (which cannot retry on 401). */
export async function ensureFreshAccessToken(): Promise<string | null> {
  if (tokenStore.isAccessExpiring(60)) await refreshTokens();
  return tokenStore.access;
}

export function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') p.set(k, String(v));
  const s = p.toString();
  return s ? `?${s}` : '';
}

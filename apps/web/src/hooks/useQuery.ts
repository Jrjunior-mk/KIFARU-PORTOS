/** Minimal data hook: fetch, refetch, optional polling, error surfaced as ApiError. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../api/client';

export interface QueryState<T> {
  data: T | undefined;
  error: ApiError | null;
  loading: boolean;
  refetch: () => Promise<void>;
  setData: (updater: T | ((prev: T | undefined) => T)) => void;
}

export function useQuery<T>(fn: () => Promise<T>, deps: unknown[] = [], opts: { pollMs?: number; enabled?: boolean } = {}): QueryState<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState<boolean>(opts.enabled !== false);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const alive = useRef(true);

  const refetch = useCallback(async () => {
    if (opts.enabled === false) return;
    try {
      const d = await fnRef.current();
      if (alive.current) { setData(d); setError(null); }
    } catch (e) {
      if (alive.current) setError(e instanceof ApiError ? e : new ApiError(0, (e as Error).message));
    } finally {
      if (alive.current) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opts.enabled, ...deps]);

  useEffect(() => {
    alive.current = true;
    setLoading(true);
    void refetch();
    let id: number | undefined;
    if (opts.pollMs && opts.enabled !== false) {
      id = window.setInterval(() => { if (document.visibilityState === 'visible') void refetch(); }, opts.pollMs);
    }
    return () => { alive.current = false; if (id) window.clearInterval(id); };
  }, [refetch, opts.pollMs, opts.enabled]);

  const set = useCallback((u: T | ((prev: T | undefined) => T)) => {
    setData((prev) => (typeof u === 'function' ? (u as (p: T | undefined) => T)(prev) : u));
  }, []);

  return { data, error, loading, refetch, setData: set };
}

/** Wraps a mutating call: tracks busy state and the last error for display next to the form. */
export function useMutation<A extends unknown[], R>(fn: (...args: A) => Promise<R>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  const [result, setResult] = useState<R | undefined>(undefined);
  const run = useCallback(async (...args: A): Promise<R | undefined> => {
    setBusy(true); setError(null);
    try {
      const r = await fn(...args);
      setResult(r);
      return r;
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, (e as Error).message));
      return undefined;
    } finally {
      setBusy(false);
    }
  }, [fn]);
  const reset = useCallback(() => { setError(null); setResult(undefined); }, []);
  return { run, busy, error, result, reset };
}

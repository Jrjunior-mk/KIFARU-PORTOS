/**
 * useLiveEvents(types?, station?) — live event subscription.
 *
 * Primary transport: WebSocket /ws/events with exponential-backoff reconnect. The server sends
 * {type:"hello", recent:[...]} on connect, {type:"ping"} keep-alives, and event envelopes.
 *
 * Fallback transport: polling GET /api/v1/events/recent every few seconds. Used when VITE_WS_DISABLED=1 (hosting
 * without WebSocket support, e.g. serverless platforms) or after the WebSocket fails repeatedly. Events from both
 * transports are merged by event_id so nothing is duplicated.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { API_PREFIX, ensureFreshAccessToken, wsUrl } from '../api/client';
import type { LiveEvent } from '../api/types';
import { tokenStore } from '../auth/tokenStore';

export type LiveStatus = 'connecting' | 'open' | 'closed' | 'error' | 'polling';

export interface LiveEventsState {
  events: LiveEvent[];
  latest: LiveEvent | null;
  status: LiveStatus;
  /** true once any received event carries source==="live" (payload.source or producer). */
  hasLive: boolean;
  clear: () => void;
}

const WS_DISABLED = (import.meta.env.VITE_WS_DISABLED as string | undefined) === '1';
const POLL_MS = 5000;
const WS_FAILURES_BEFORE_POLLING = 2;

export function eventSource(ev: LiveEvent): string | null {
  const p = ev.payload as { source?: unknown } | undefined;
  if (p && typeof p.source === 'string') return p.source;
  if (ev.producer === 'live' || ev.producer === 'simulated' || ev.producer === 'replay') return ev.producer;
  return null;
}

export function useLiveEvents(types?: string[], station?: string | null, max = 300, onEvent?: (ev: LiveEvent) => void): LiveEventsState {
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [latest, setLatest] = useState<LiveEvent | null>(null);
  const [status, setStatus] = useState<LiveStatus>('connecting');
  const [hasLive, setHasLive] = useState(false);
  const typesKey = types?.slice().sort().join(',') ?? '';
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;
  const seenRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let attempt = 0;
    let failures = 0;
    let timer: number | undefined;
    let pollTimer: number | undefined;
    let polling = false;
    const seen = seenRef.current;

    const push = (incoming: LiveEvent[], announce: boolean) => {
      const fresh = incoming.filter((e) => e.event_id && !seen.has(e.event_id));
      if (!fresh.length) return;
      for (const e of fresh) seen.add(e.event_id);
      if (seen.size > max * 4) {
        // keep the dedupe set bounded
        const keep = Array.from(seen).slice(-max * 2);
        seen.clear();
        for (const id of keep) seen.add(id);
      }
      if (fresh.some((e) => eventSource(e) === 'live')) setHasLive(true);
      setEvents((prev) => {
        const next = prev.concat(fresh);
        return next.length > max ? next.slice(next.length - max) : next;
      });
      setLatest(fresh[fresh.length - 1]);
      if (announce) for (const e of fresh) handlerRef.current?.(e);
    };

    const poll = async () => {
      if (closed) return;
      const token = await ensureFreshAccessToken();
      if (token) {
        const params = new URLSearchParams({ minutes: '30', limit: '100' });
        if (typesKey) params.set('types', typesKey);
        if (station) params.set('station', station);
        try {
          const r = await fetch(`${API_PREFIX}/events/recent?${params.toString()}`, { headers: { Authorization: `Bearer ${token}` } });
          if (r.ok) {
            const list = (await r.json()) as LiveEvent[];
            push(list, true);
            setStatus('polling');
          } else if (r.status === 401) {
            tokenStore.clear();
          }
        } catch {
          setStatus('error');
        }
      }
      if (!closed) pollTimer = window.setTimeout(() => void poll(), POLL_MS);
    };

    const startPolling = () => {
      if (polling || closed) return;
      polling = true;
      setStatus('polling');
      void poll();
    };

    const connect = async () => {
      if (closed) return;
      const token = await ensureFreshAccessToken();
      if (!token) { setStatus('closed'); return; }
      const params = new URLSearchParams({ token });
      if (typesKey) params.set('types', typesKey);
      if (station) params.set('station', station);
      setStatus('connecting');
      ws = new WebSocket(wsUrl(`/ws/events?${params.toString()}`));
      ws.onopen = () => { attempt = 0; failures = 0; setStatus('open'); };
      ws.onmessage = (m) => {
        let data: unknown;
        try { data = JSON.parse(m.data as string); } catch { return; }
        const d = data as { type?: string; recent?: LiveEvent[] };
        if (d.type === 'ping') return;
        if (d.type === 'hello') { push((d.recent ?? []).slice(-max), false); return; }
        const ev = data as LiveEvent;
        if (!ev.event_id) return;
        push([ev], true);
      };
      ws.onerror = () => setStatus('error');
      ws.onclose = (e) => {
        if (closed) return;
        setStatus('closed');
        if (e.code === 4401) { tokenStore.clear(); return; }
        failures += 1;
        if (failures >= WS_FAILURES_BEFORE_POLLING) { startPolling(); return; }
        const delay = Math.min(30_000, 1000 * 2 ** attempt++) + Math.random() * 500;
        timer = window.setTimeout(() => void connect(), delay);
      };
    };

    if (WS_DISABLED) startPolling();
    else void connect();

    return () => {
      closed = true;
      if (timer) window.clearTimeout(timer);
      if (pollTimer) window.clearTimeout(pollTimer);
      ws?.close();
    };
  }, [typesKey, station, max]);

  const clear = useCallback(() => { setEvents([]); setLatest(null); seenRef.current.clear(); }, []);
  return { events, latest, status, hasLive, clear };
}

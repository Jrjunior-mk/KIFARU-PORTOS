/**
 * useLiveEvents(types?, station?) — WebSocket subscription to /ws/events with exponential-backoff reconnect.
 * The server sends {type:"hello", recent:[...]} on connect, {type:"ping"} keep-alives, and event envelopes.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { ensureFreshAccessToken, wsUrl } from '../api/client';
import type { LiveEvent } from '../api/types';
import { tokenStore } from '../auth/tokenStore';

export type LiveStatus = 'connecting' | 'open' | 'closed' | 'error';

export interface LiveEventsState {
  events: LiveEvent[];
  latest: LiveEvent | null;
  status: LiveStatus;
  /** true once any received event carries source==="live" (payload.source or producer). */
  hasLive: boolean;
  clear: () => void;
}

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

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let attempt = 0;
    let timer: number | undefined;

    const connect = async () => {
      if (closed) return;
      const token = await ensureFreshAccessToken();
      if (!token) { setStatus('closed'); return; }
      const params = new URLSearchParams({ token });
      if (typesKey) params.set('types', typesKey);
      if (station) params.set('station', station);
      setStatus('connecting');
      ws = new WebSocket(wsUrl(`/ws/events?${params.toString()}`));
      ws.onopen = () => { attempt = 0; setStatus('open'); };
      ws.onmessage = (m) => {
        let data: unknown;
        try { data = JSON.parse(m.data as string); } catch { return; }
        const d = data as { type?: string; recent?: LiveEvent[] };
        if (d.type === 'ping') return;
        if (d.type === 'hello') {
          const recent = (d.recent ?? []).slice(-max);
          setEvents(recent);
          if (recent.some((e) => eventSource(e) === 'live')) setHasLive(true);
          if (recent.length) setLatest(recent[recent.length - 1]);
          return;
        }
        const ev = data as LiveEvent;
        if (!ev.event_id) return;
        if (eventSource(ev) === 'live') setHasLive(true);
        setEvents((prev) => {
          const next = prev.length >= max ? prev.slice(prev.length - max + 1) : prev.slice();
          next.push(ev);
          return next;
        });
        setLatest(ev);
        handlerRef.current?.(ev);
      };
      ws.onerror = () => setStatus('error');
      ws.onclose = (e) => {
        if (closed) return;
        setStatus('closed');
        if (e.code === 4401) tokenStore.clear();
        const delay = Math.min(30_000, 1000 * 2 ** attempt++) + Math.random() * 500;
        timer = window.setTimeout(connect, delay);
      };
    };
    void connect();
    return () => {
      closed = true;
      if (timer) window.clearTimeout(timer);
      ws?.close();
    };
  }, [typesKey, station, max]);

  const clear = useCallback(() => { setEvents([]); setLatest(null); }, []);
  return { events, latest, status, hasLive, clear };
}

"""Event catalogue (RTC-02) and the in-process event bus with optional Redis fan-out.

Publishing an event: (1) persists nothing by itself (the ledger service does that where required), (2) pushes to all
WebSocket subscribers of this process, (3) if Redis is configured, publishes on channel `kifaru.events` so other API
instances fan out to their own WebSocket clients.
"""
from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import structlog

from .config import get_settings
from .ids import new_id

log = structlog.get_logger(__name__)


class EventType(StrEnum):
    TRUCK_DETECTED = "truck.detected"
    TRUCK_IDENTIFIED = "truck.identified"
    WEIGHING_STARTED = "weighing.started"
    WEIGHING_COMPLETED = "weighing.completed"
    CLEARANCE_DECIDED = "clearance.decided"
    TRUCK_DIVERTED = "truck.diverted"
    TRUCK_RELEASED = "truck.released"
    CARGO_VERIFIED = "cargo.verified"
    CARGO_STATUS_CHANGED = "cargo.status_changed"
    QUEUE_UPDATED = "queue.updated"
    STATION_FAILURE = "station.failure"
    BACKHAUL_OPPORTUNITY = "backhaul.opportunity"
    SHIPMENT_DELIVERED = "shipment.delivered"
    SENSOR_HEALTH = "sensor.health"
    INCIDENT_OPENED = "incident.opened"


def make_event(type_: EventType | str, payload: dict[str, Any], station_id: str | None = None, org_id: str | None = None, source: str = "cloud-api") -> dict:
    return {
        "event_id": new_id(),
        "type": str(type_),
        "occurred_at": datetime.now(UTC).isoformat(),
        "station_id": station_id,
        "org_id": org_id,
        "payload": payload,
        "producer": source,
        "schema_version": 1,
    }


class EventBus:
    """Thread-safe publish; async subscribers receive via asyncio queues."""

    def __init__(self) -> None:
        self._subs: dict[int, tuple[asyncio.Queue, asyncio.AbstractEventLoop, Callable[[dict], bool]]] = {}
        self._lock = threading.Lock()
        self._next = 1
        self._redis = None
        self._history: list[dict] = []

    def subscribe(self, filter_fn: Callable[[dict], bool] | None = None) -> tuple[int, asyncio.Queue]:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        loop = asyncio.get_event_loop()
        with self._lock:
            sid = self._next
            self._next += 1
            self._subs[sid] = (q, loop, filter_fn or (lambda _e: True))
        return sid, q

    def unsubscribe(self, sid: int) -> None:
        with self._lock:
            self._subs.pop(sid, None)

    def _local_dispatch(self, event: dict) -> None:
        with self._lock:
            subs = list(self._subs.values())
            self._history.append(event)
            if len(self._history) > 200:
                self._history = self._history[-200:]
        for q, loop, flt in subs:
            try:
                if flt(event):
                    loop.call_soon_threadsafe(q.put_nowait, event)
            except Exception:  # pragma: no cover - queue full / closed loop
                pass

    def publish(self, event: dict, remote: bool = True) -> None:
        self._local_dispatch(event)
        s = get_settings()
        if remote and s.redis_url:
            try:
                if self._redis is None:
                    import redis

                    self._redis = redis.Redis.from_url(s.redis_url)
                self._redis.publish("kifaru.events", json.dumps(event, default=str))
            except Exception as exc:  # pragma: no cover
                log.warning("redis_publish_failed", error=str(exc))

    def recent(self, n: int = 50) -> list[dict]:
        with self._lock:
            return list(self._history[-n:])


bus = EventBus()


def publish(type_: EventType | str, payload: dict[str, Any], station_id: str | None = None, org_id: str | None = None, source: str = "cloud-api") -> dict:
    ev = make_event(type_, payload, station_id, org_id, source)
    bus.publish(ev)
    return ev

"""MQTT ingest worker (CLD-04 / RTC-01): edge gateway events -> validated -> ``process_lane_pass`` -> commit -> ack.

Topics (one per lane; the gateway publishes with QoS 1 and keeps an SQLite outbox for store-and-forward):

    kifaru/stations/{station_code}/lanes/{lane_no}/events   JSON  = EdgeIngestIn (routers/weighing.py)
    kifaru/stations/{station_code}/lanes/{lane_no}/health   JSON  = EdgeHealthIn (below)

Design rules
  * The handler functions are pure w.r.t. the broker (take a dict / bytes and a DB session) so they are unit-testable
    and shared with the SQS variant.
  * Idempotency: ``edge_event_id`` (ULID from the gateway) is unique on ``weighing_events``; a replayed message returns
    the existing event and is acked again.
  * Malformed / unresolvable messages are dead-lettered as JSON lines under ``<KIFARU_LOCAL_OBJECT_DIR>/dead-letter/``
    (one file per UTC day) and acked so they do not block the queue. The worker never crashes on a bad message.
  * Messages are acked manually AFTER the DB commit (paho ``manual_ack``), so a crash between receive and commit lets
    the broker redeliver.
  * TLS / mTLS is enabled when ``KIFARU_MQTT_TLS_CA`` (and cert/key) are configured; AWS IoT Core requires mTLS.

Run:  python -m kifaru.workers.mqtt_ingest  [--host ... --port ...]
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import ssl
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_sessionmaker
from ..events import EventType, publish
from ..models import Lane, Sensor, WeighingEvent, utcnow
from ..routers.weighing import EdgeIngestIn
from ..services.weighing_service import process_lane_pass

log = structlog.get_logger("kifaru.workers.mqtt_ingest")

TOPIC_EVENTS = "kifaru/stations/+/lanes/+/events"
TOPIC_HEALTH = "kifaru/stations/+/lanes/+/health"
TOPIC_ALL = "kifaru/stations/+/lanes/+/+"


class SensorHealthItem(BaseModel):
    status: str = Field(pattern="^(ok|degraded|fault)$")
    reason: str | None = Field(default=None, max_length=200)


class EdgeHealthIn(BaseModel):
    """Lane health report. ``sensors`` is keyed by sensor serial, by DAQ channel index (as a string) or by the
    pipeline channel name (P1, P2, P3, BP, L1..L3) — resolution tries them in that order."""

    device_id: str
    reported_at: datetime | None = None
    sensors: dict[str, SensorHealthItem]
    gateway: dict[str, Any] | None = None  # free-form: uptime, outbox depth, firmware version


# pipeline channel names -> (sensor kind, install position) as created by routers.stations.DEFAULT_LANE_SENSORS
CHANNEL_NAME_MAP: dict[str, tuple[str, float]] = {
    "L1": ("inductive_loop", 0.0),
    "P1": ("piezo_quartz", 4.0),
    "P2": ("piezo_quartz", 7.0),
    "BP": ("bending_plate", 10.0),
    "L2": ("inductive_loop", 12.0),
    "P3": ("piezo_quartz", 16.0),
    "L3": ("inductive_loop", 19.0),
}


@dataclass
class HandleResult:
    status: str  # processed | duplicate | dead_letter | health_updated
    detail: str = ""
    weighing_event_id: str | None = None
    decision: str | None = None

    @property
    def ok(self) -> bool:
        return self.status != "dead_letter"


# ------------------------------------------------------------------------------------------------- dead letter
def dead_letter_dir(directory: str | Path | None = None) -> Path:
    base = Path(directory) if directory else Path(get_settings().local_object_dir) / "dead-letter"
    base.mkdir(parents=True, exist_ok=True)
    return base


def dead_letter(topic: str, raw: bytes | str | dict, reason: str, directory: str | Path | None = None) -> Path:
    """Append one JSON line; never raises (a failure to dead-letter is logged, not propagated)."""
    try:
        d = dead_letter_dir(directory)
        path = d / f"{datetime.now(UTC):%Y-%m-%d}.jsonl"
        if isinstance(raw, bytes):
            try:
                raw_s: Any = raw.decode("utf-8")
            except UnicodeDecodeError:
                raw_s = raw.hex()
        else:
            raw_s = raw
        rec = {"received_at": datetime.now(UTC).isoformat(), "topic": topic, "reason": reason, "raw": raw_s}
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str) + "\n")
        log.warning("dead_letter", topic=topic, reason=reason, path=str(path))
        return path
    except Exception as exc:  # pragma: no cover - last resort
        log.error("dead_letter_failed", error=str(exc))
        return Path("")


def _parse_json(raw: bytes | str | dict) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("payload is not a JSON object")
    return data


# ------------------------------------------------------------------------------------------------- handlers
def handle_event_message(db: Session, raw: bytes | str | dict, topic: str = TOPIC_EVENTS, dead_letter_directory: str | Path | None = None) -> HandleResult:
    """Validate + process one lane-pass message. Commits on success; rolls back and dead-letters on any failure."""
    try:
        data = _parse_json(raw)
        # AWS IoT rule envelopes may wrap the payload: {"topic": "...", "payload": {...}}
        if "payload" in data and "device_id" not in data and isinstance(data["payload"], dict):
            topic = data.get("topic", topic)
            data = data["payload"]
        body = EdgeIngestIn.model_validate(data)
    except (ValueError, ValidationError) as exc:
        dead_letter(topic, raw, f"validation: {exc}", dead_letter_directory)
        return HandleResult("dead_letter", f"validation: {exc}")

    try:
        lane = db.execute(select(Lane).where(Lane.device_id == body.device_id)).scalar_one_or_none()
        if lane is None:
            dead_letter(topic, raw, f"unknown device_id {body.device_id}", dead_letter_directory)
            return HandleResult("dead_letter", f"unknown device_id {body.device_id}")
        existing = db.execute(select(WeighingEvent).where(WeighingEvent.edge_event_id == body.edge_event_id)).scalar_one_or_none()
        if existing is not None:  # store-and-forward replay: already persisted, just ack again
            log.info("edge_event", status="duplicate", weighing_event_id=existing.id, edge_event_id=body.edge_event_id)
            return HandleResult("duplicate", weighing_event_id=existing.id, decision=existing.decision.decision if existing.decision else None)
        ev = process_lane_pass(
            db, lane, body.measurement, body.anpr_plate, body.anpr_confidence, body.rfid_epc, body.rfid_confidence,
            occurred_at=body.occurred_at, source="live", edge_event_id=body.edge_event_id, raw_ref=body.raw_ref, ambient_temp_c=body.ambient_temp_c,
        )
        db.commit()
        decision = ev.decision.decision if ev.decision else None
        log.info("edge_event", status="processed", weighing_event_id=ev.id, decision=decision, lane_id=lane.id, edge_event_id=body.edge_event_id)
        return HandleResult("processed", weighing_event_id=ev.id, decision=decision)
    except Exception as exc:  # noqa: BLE001 - the worker must never die on one message
        db.rollback()
        log.exception("edge_event_failed")
        dead_letter(topic, raw, f"processing: {type(exc).__name__}: {exc}", dead_letter_directory)
        return HandleResult("dead_letter", f"processing: {type(exc).__name__}: {exc}")


def _resolve_sensor(lane: Lane, key: str) -> Sensor | None:
    for s in lane.sensors:
        if s.serial and s.serial == key:
            return s
    if key.isdigit():
        for s in lane.sensors:
            if s.channel is not None and s.channel == int(key):
                return s
    if key in CHANNEL_NAME_MAP:
        kind, pos = CHANNEL_NAME_MAP[key]
        for s in lane.sensors:
            if s.kind == kind and s.install_position_m is not None and abs(s.install_position_m - pos) < 0.01:
                return s
    return None


def handle_health_message(db: Session, raw: bytes | str | dict, topic: str = TOPIC_HEALTH, dead_letter_directory: str | Path | None = None) -> HandleResult:
    """Update Sensor.status / health_reason from a lane health report and publish ``sensor.health`` events."""
    try:
        data = _parse_json(raw)
        if "payload" in data and "device_id" not in data and isinstance(data["payload"], dict):
            data = data["payload"]
        body = EdgeHealthIn.model_validate(data)
    except (ValueError, ValidationError) as exc:
        dead_letter(topic, raw, f"validation: {exc}", dead_letter_directory)
        return HandleResult("dead_letter", f"validation: {exc}")
    try:
        lane = db.execute(select(Lane).where(Lane.device_id == body.device_id)).scalar_one_or_none()
        if lane is None:
            dead_letter(topic, raw, f"unknown device_id {body.device_id}", dead_letter_directory)
            return HandleResult("dead_letter", f"unknown device_id {body.device_id}")
        updated, unresolved = 0, []
        now = utcnow()
        for key, item in body.sensors.items():
            s = _resolve_sensor(lane, key)
            if s is None:
                unresolved.append(key)
                continue
            changed = s.status != item.status or s.health_reason != item.reason
            s.status, s.health_reason, s.last_reading_at = item.status, item.reason, body.reported_at or now
            updated += 1
            if changed:
                publish(EventType.SENSOR_HEALTH, {"sensor_id": s.id, "lane_id": lane.id, "kind": s.kind, "status": item.status, "reason": item.reason, "channel": key},
                        station_id=lane.station_id, source="live")
        if any(x.status == "fault" for x in lane.sensors) and lane.status == "operational":
            lane.status = "degraded"
        elif all(x.status == "ok" for x in lane.sensors) and lane.status == "degraded":
            lane.status = "operational"
        db.commit()
        detail = f"{updated} sensors updated" + (f"; unresolved keys {unresolved}" if unresolved else "")
        log.info("lane_health", lane_id=lane.id, detail=detail)
        return HandleResult("health_updated", detail)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("lane_health_failed")
        dead_letter(topic, raw, f"processing: {type(exc).__name__}: {exc}", dead_letter_directory)
        return HandleResult("dead_letter", f"processing: {type(exc).__name__}: {exc}")


def dispatch(db: Session, topic: str, raw: bytes | str | dict, dead_letter_directory: str | Path | None = None) -> HandleResult:
    """Route by topic suffix."""
    leaf = topic.rsplit("/", 1)[-1]
    if leaf == "events":
        return handle_event_message(db, raw, topic, dead_letter_directory)
    if leaf == "health":
        return handle_health_message(db, raw, topic, dead_letter_directory)
    dead_letter(topic, raw, f"unsupported topic leaf '{leaf}'", dead_letter_directory)
    return HandleResult("dead_letter", f"unsupported topic leaf '{leaf}'")


# ------------------------------------------------------------------------------------------------- worker
class MqttIngestWorker:
    def __init__(self, host: str | None = None, port: int | None = None, client_id: str | None = None, qos: int = 1) -> None:
        import paho.mqtt.client as mqtt

        s = get_settings()
        self.host = host or s.mqtt_host
        self.port = port or s.mqtt_port
        self.qos = qos
        if not self.host:
            raise SystemExit("KIFARU_MQTT_HOST is not configured (set it, or pass --host). Nothing to subscribe to.")
        self.Session = get_sessionmaker()
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id or s.mqtt_client_id, protocol=mqtt.MQTTv311, manual_ack=True)
        if s.mqtt_tls_ca or s.mqtt_tls_cert:
            self.client.tls_set(ca_certs=s.mqtt_tls_ca, certfile=s.mqtt_tls_cert, keyfile=s.mqtt_tls_key, cert_reqs=ssl.CERT_REQUIRED, tls_version=ssl.PROTOCOL_TLS_CLIENT)
            log.info("mqtt_tls", mtls=bool(s.mqtt_tls_cert))
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(min_delay=1, max_delay=60)
        self.stats = {"processed": 0, "duplicate": 0, "dead_letter": 0, "health_updated": 0}
        self._stop = threading.Event()

    # paho v2 callback signatures
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("mqtt_connect_failed", reason=str(reason_code))
            return
        client.subscribe([(TOPIC_EVENTS, self.qos), (TOPIC_HEALTH, self.qos)])
        log.info("mqtt_subscribed", host=self.host, port=self.port, topics=[TOPIC_EVENTS, TOPIC_HEALTH])

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        log.warning("mqtt_disconnected", reason=str(reason_code))

    def _on_message(self, client, userdata, msg):
        t0 = time.perf_counter()
        with self.Session() as db:
            res = dispatch(db, msg.topic, msg.payload)
        self.stats[res.status] = self.stats.get(res.status, 0) + 1
        # ack only after the transaction is closed; dead-lettered messages are acked too (they are persisted on disk)
        if msg.qos > 0:
            client.ack(msg.mid, msg.qos)
        log.debug("mqtt_message", topic=msg.topic, status=res.status, ms=int((time.perf_counter() - t0) * 1000))

    def run_forever(self) -> None:
        signal.signal(signal.SIGINT, lambda *_: self.stop())
        signal.signal(signal.SIGTERM, lambda *_: self.stop())
        log.info("mqtt_ingest_starting", host=self.host, port=self.port)
        self.client.connect_async(self.host, self.port, keepalive=60)
        self.client.loop_start()
        try:
            while not self._stop.is_set():
                self._stop.wait(5.0)
        finally:
            self.client.loop_stop()
            self.client.disconnect()
            log.info("mqtt_ingest_stopped", **self.stats)

    def stop(self) -> None:
        self._stop.set()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="KIFARU PORTOS MQTT ingest worker")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--client-id", default=None)
    p.add_argument("--qos", type=int, default=1, choices=(0, 1, 2))
    a = p.parse_args(argv)
    logging.basicConfig(level=get_settings().log_level, stream=sys.stdout)
    MqttIngestWorker(a.host, a.port, a.client_id, a.qos).run_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

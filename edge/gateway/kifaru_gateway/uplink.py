"""Uplinks: MQTT 5 over TLS (mTLS) via paho-mqtt, HTTP fallback posting `EdgeIngestIn` to /api/v1/weighing/ingest,
a composite that prefers MQTT, and an in-memory uplink for tests. All implement `publish(topic, payload, event_id) -> bool`
and may raise `PoisonMessage` for undeliverable payloads.
"""
from __future__ import annotations

import json
import logging
import ssl
import time
from datetime import datetime
from typing import Protocol

from .config import GatewayConfig, HttpConfig, MqttConfig
from .identity import AnprRead, RfidRead
from .outbox import PoisonMessage

log = logging.getLogger(__name__)


class Uplink(Protocol):
    def publish(self, topic: str, payload: dict, event_id: str) -> bool: ...

    def publish_retained(self, topic: str, payload: dict) -> bool: ...

    @property
    def connected(self) -> bool: ...


# ------------------------------------------------------------------------------------------------ payload builders
def build_ingest_body(device_id: str, event_id: str, occurred_at: datetime, measurement: dict, anpr: AnprRead | None, rfid: RfidRead | None,
                      raw_ref: str | None = None, ambient_temp_c: float | None = None) -> dict:
    """Exactly the `EdgeIngestIn` schema of apps/api/kifaru/routers/weighing.py."""
    return {
        "device_id": device_id,
        "edge_event_id": event_id,
        "occurred_at": occurred_at.isoformat(),
        "measurement": measurement,
        "anpr_plate": anpr.plate if anpr else None,
        "anpr_confidence": round(anpr.confidence, 4) if anpr else None,
        "rfid_epc": rfid.epc if rfid else None,
        "rfid_confidence": round(rfid.confidence, 4) if rfid else None,
        "raw_ref": raw_ref,
        "ambient_temp_c": ambient_temp_c,
    }


def build_event(event_id: str, type_: str, occurred_at: datetime, cfg: GatewayConfig, payload: dict) -> dict:
    """Envelope published on the events topic (communications.md §3); mirrors kifaru.events.make_event."""
    return {
        "event_id": event_id,
        "type": type_,
        "occurred_at": occurred_at.isoformat(),
        "station_id": cfg.station,
        "lane_id": cfg.lane,
        "org_id": None,
        "payload": payload,
        "producer": cfg.mqtt.client_id,
        "schema_version": 1,
    }


# ------------------------------------------------------------------------------------------------ memory (tests)
class MemoryUplink:
    def __init__(self):
        self.down = False
        self.published: list[tuple[str, dict, str]] = []
        self.retained: dict[str, dict] = {}
        self.poison_ids: set[str] = set()

    @property
    def connected(self) -> bool:
        return not self.down

    def publish(self, topic: str, payload: dict, event_id: str) -> bool:
        if event_id in self.poison_ids:
            raise PoisonMessage("rejected by schema")
        if self.down:
            return False
        self.published.append((topic, payload, event_id))
        return True

    def publish_retained(self, topic: str, payload: dict) -> bool:
        if self.down:
            return False
        self.retained[topic] = payload
        return True


# ------------------------------------------------------------------------------------------------ MQTT
class MqttUplink:
    def __init__(self, cfg: MqttConfig, will_topic: str | None = None):
        import paho.mqtt.client as mqtt
        from paho.mqtt.packettypes import PacketTypes
        from paho.mqtt.properties import Properties

        self.cfg = cfg
        self._mqtt = mqtt
        self._Properties, self._PacketTypes = Properties, PacketTypes
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=cfg.client_id, protocol=mqtt.MQTTv5)
        if cfg.tls:
            ctx = ssl.create_default_context(cafile=cfg.ca_cert)
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            if cfg.client_cert and cfg.client_key:
                ctx.load_cert_chain(cfg.client_cert, cfg.client_key)  # mTLS device certificate
            self.client.tls_set_context(ctx)
        if will_topic:
            self.client.will_set(will_topic, json.dumps({"status": "offline", "client_id": cfg.client_id}), qos=1, retain=True)
        self._connected = False
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.on_message = None

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = reason_code == 0 or getattr(reason_code, "is_failure", lambda: True)() is False
        log.info("mqtt connected rc=%s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = False
        log.warning("mqtt disconnected rc=%s", reason_code)

    def connect(self) -> None:
        props = self._Properties(self._PacketTypes.CONNECT)
        props.SessionExpiryInterval = self.cfg.session_expiry_s
        self.client.connect_async(self.cfg.host, self.cfg.port, keepalive=self.cfg.keepalive_s, clean_start=False, properties=props)
        self.client.loop_start()

    def subscribe(self, topic: str, handler) -> None:
        def _on_msg(client, userdata, msg):
            try:
                handler(msg.topic, json.loads(msg.payload.decode()))
            except Exception:  # noqa: BLE001
                log.exception("bad cmd message")

        self.client.message_callback_add(topic, _on_msg)
        self.client.subscribe(topic, qos=1)

    @property
    def connected(self) -> bool:
        return self._connected

    def _props(self):
        p = self._Properties(self._PacketTypes.PUBLISH)
        p.MessageExpiryInterval = self.cfg.message_expiry_s
        p.UserProperty = [("schema", "1"), ("producer", self.cfg.client_id)]
        return p

    def publish(self, topic: str, payload: dict, event_id: str) -> bool:
        if not self._connected:
            return False
        info = self.client.publish(topic, json.dumps(payload, default=str), qos=1, retain=False, properties=self._props())
        try:
            info.wait_for_publish(timeout=self.cfg.publish_timeout_s)
        except (RuntimeError, ValueError):
            return False
        return info.is_published()

    def publish_retained(self, topic: str, payload: dict) -> bool:
        if not self._connected:
            return False
        info = self.client.publish(topic, json.dumps(payload, default=str), qos=1, retain=True, properties=self._props())
        try:
            info.wait_for_publish(timeout=self.cfg.publish_timeout_s)
        except (RuntimeError, ValueError):
            return False
        return info.is_published()

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


# ------------------------------------------------------------------------------------------------ HTTP fallback
class HttpUplink:
    """POSTs weighing events to /api/v1/weighing/ingest. Only events whose payload carries an `ingest` body are
    deliverable this way; other event types return True (dropped here, they are reconstructed by the cloud from the
    weighing event) so they never block the queue."""

    INGEST_PATH = "/api/v1/weighing/ingest"

    def __init__(self, cfg: HttpConfig, client=None):
        import httpx

        self.cfg = cfg
        self._httpx = httpx
        self.client = client or httpx.Client(base_url=cfg.base_url or "", timeout=cfg.timeout_s, headers={"Authorization": f"Bearer {cfg.token}"} if cfg.token else {})
        self._last_ok = 0.0

    @property
    def connected(self) -> bool:
        return bool(self.cfg.base_url)

    def publish(self, topic: str, payload: dict, event_id: str) -> bool:
        body = payload.get("payload", {}).get("ingest") if isinstance(payload, dict) else None
        if body is None:
            return True
        try:
            r = self.client.post(self.INGEST_PATH, json=body)
        except self._httpx.HTTPError as e:
            log.warning("http ingest transport error: %s", e)
            return False
        if r.status_code in (200, 201, 409):
            self._last_ok = time.time()
            return True
        if r.status_code == 429 or r.status_code >= 500:
            return False
        raise PoisonMessage(f"HTTP {r.status_code}: {r.text[:200]}")

    def publish_retained(self, topic: str, payload: dict) -> bool:
        return True  # no retained semantics over HTTP


# ------------------------------------------------------------------------------------------------ composite
class CompositeUplink:
    """Prefer MQTT; fall back to HTTP after `fallback_after_s` without an MQTT connection."""

    def __init__(self, primary, fallback=None, fallback_after_s: float = 60.0):
        self.primary, self.fallback, self.fallback_after_s = primary, fallback, fallback_after_s
        self._primary_down_since: float | None = None

    @property
    def connected(self) -> bool:
        return self.primary.connected or (self.fallback is not None and self.fallback.connected)

    def _use_fallback(self) -> bool:
        if self.primary.connected:
            self._primary_down_since = None
            return False
        if self._primary_down_since is None:
            self._primary_down_since = time.time()
        return self.fallback is not None and (time.time() - self._primary_down_since) >= self.fallback_after_s

    def publish(self, topic: str, payload: dict, event_id: str) -> bool:
        if self._use_fallback():
            return self.fallback.publish(topic, payload, event_id)
        return self.primary.publish(topic, payload, event_id)

    def publish_retained(self, topic: str, payload: dict) -> bool:
        if self.primary.connected:
            return self.primary.publish_retained(topic, payload)
        return False

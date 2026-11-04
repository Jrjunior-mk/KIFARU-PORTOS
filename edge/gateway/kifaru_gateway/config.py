"""Gateway configuration: dataclass with environment-variable loading (KIFARU_GW_*)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class MqttConfig:
    host: str = "localhost"
    port: int = 8883
    client_id: str = ""
    ca_cert: str | None = None
    client_cert: str | None = None
    client_key: str | None = None
    tls: bool = True
    keepalive_s: int = 60
    session_expiry_s: int = 7 * 24 * 3600
    message_expiry_s: int = 7 * 24 * 3600
    publish_timeout_s: float = 5.0


@dataclass
class HttpConfig:
    base_url: str | None = None  # e.g. https://api.kifaru.example
    token: str | None = None
    timeout_s: float = 5.0


@dataclass
class GatewayConfig:
    station: str = "MARIAKANI"
    lane: str = "L1"
    device_id: str = "daq-MARIAKANI-L1"
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("KIFARU_GW_DATA_DIR", "./gateway-data")))
    outbox_path: Path | None = None
    snapshot_path: Path | None = None
    udp_bind: str = "0.0.0.0:5010"
    daq_addr: str | None = None  # host:port of the DAQ for TIME_SYNC (port 5011)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    http: HttpConfig = field(default_factory=HttpConfig)
    identity_min_confidence: float = 0.90
    audit_rate: float = 0.02
    vms_port: str | None = None  # serial device; None -> mock
    load_shed_soc_pct: float = 30.0
    drain_interval_s: float = 1.0
    health_period_s: float = 30.0
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        if self.outbox_path is None:
            self.outbox_path = self.data_dir / "outbox.sqlite3"
        if self.snapshot_path is None:
            self.snapshot_path = self.data_dir / "snapshot.json"
        if not self.mqtt.client_id:
            self.mqtt.client_id = f"gw-{self.station}-{self.lane}"

    @property
    def topic_events(self) -> str:
        return f"kifaru/stations/{self.station}/lanes/{self.lane}/events"

    @property
    def topic_health(self) -> str:
        return f"kifaru/stations/{self.station}/lanes/{self.lane}/health"

    @property
    def topic_cmd(self) -> str:
        return f"kifaru/stations/{self.station}/lanes/{self.lane}/cmd"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> GatewayConfig:
        env = dict(os.environ if env is None else env)
        p = "KIFARU_GW_"
        kw: dict = {}
        for f in fields(cls):
            key = p + f.name.upper()
            if key in env and f.name not in ("mqtt", "http"):
                raw = env[key]
                if f.type in ("float", float):
                    kw[f.name] = float(raw)
                elif f.type in ("Path", Path, "Path | None"):
                    kw[f.name] = Path(raw)
                else:
                    kw[f.name] = raw
        mqtt = MqttConfig(
            host=env.get(p + "MQTT_HOST", "localhost"),
            port=int(env.get(p + "MQTT_PORT", "8883")),
            ca_cert=env.get(p + "MQTT_CA"),
            client_cert=env.get(p + "MQTT_CERT"),
            client_key=env.get(p + "MQTT_KEY"),
            tls=env.get(p + "MQTT_TLS", "1") not in ("0", "false", "no"),
        )
        http = HttpConfig(base_url=env.get(p + "HTTP_URL"), token=env.get(p + "HTTP_TOKEN"))
        return cls(mqtt=mqtt, http=http, **kw)

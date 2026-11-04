"""Gateway CLI.

  python -m kifaru_gateway.main --simulate --rate 2            # 2 synthetic passes/s, in-memory uplink, local outbox
  python -m kifaru_gateway.main --simulate --count 20 --seed 1 --uplink memory
  python -m kifaru_gateway.main --udp 0.0.0.0:5010 --uplink mqtt --mqtt-host iot.example --mqtt-ca ca.pem --mqtt-cert gw.pem --mqtt-key gw.key
  python -m kifaru_gateway.main --simulate --uplink http --http-url http://localhost:8000 --http-token <jwt>
"""
from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import GATEWAY_VERSION
from .clearance_mirror import ClearanceMirror, Snapshot, VehicleRecord
from .config import GatewayConfig, HttpConfig, MqttConfig
from .daq_client import DaqMeasurement, Env, Health, SimulatedDaq, UdpDaqClient
from .identity import AnprAdapter, MockAnpr, MockRfid, RfidAdapter
from .outbox import Outbox, new_event_id
from .uplink import CompositeUplink, HttpUplink, MemoryUplink, MqttUplink, build_event, build_ingest_body
from .vms import MockModbusBackend, SerialModbusBackend, VmsController

log = logging.getLogger("kifaru_gateway")


def demo_snapshot() -> Snapshot:
    """Small registry used by --simulate when no snapshot file exists (clearly synthetic)."""
    vehicles = [
        VehicleRecord("01SIMVEH00000000000000001", "KCA 123A", "1+1+2", 14500, 42000, epcs=["E2801160600002050B2B0001"]),
        VehicleRecord("01SIMVEH00000000000000002", "KDB 456B", "1+2+2", 16000, 48000, epcs=["E2801160600002050B2B0002"]),
        VehicleRecord("01SIMVEH00000000000000003", "KCE 789C", "1+1", 7500, 18000, epcs=["E2801160600002050B2B0003"]),
        VehicleRecord("01SIMVEH00000000000000004", "KDD 321D", "1+2+3", 18000, 56000, epcs=["E2801160600002050B2B0004"], watchlist_reason="unpaid penalties (simulated)"),
    ]
    return Snapshot(version="demo-snapshot-v1", vehicles=vehicles, calibration_valid_until=(datetime.now(UTC) + timedelta(days=180)).isoformat())


class Gateway:
    def __init__(self, cfg: GatewayConfig, mirror: ClearanceMirror, outbox: Outbox, uplink, anpr: AnprAdapter, rfid: RfidAdapter, vms: VmsController):
        self.cfg, self.mirror, self.outbox, self.uplink, self.anpr, self.rfid, self.vms = cfg, mirror, outbox, uplink, anpr, rfid, vms
        self.last_env: Env | None = None
        self.last_health: Health | None = None
        self.counters = {"passes": 0, "GREEN": 0, "AMBER": 0, "RED": 0}

    # ------------------------------------------------------------------ one pass
    def handle_pass(self, dm: DaqMeasurement) -> dict:
        t0 = time.perf_counter()
        event_id = new_event_id()
        window_start, window_end = dm.occurred_at - timedelta(seconds=1.5), dm.occurred_at + timedelta(seconds=1.5)
        anpr = self.anpr.read_window(window_start, window_end)
        rfid = self.rfid.read_window(window_start, window_end)
        result, ident = self.mirror.decide(dm.measurement, anpr, rfid, event_id, dm.occurred_at, source=dm.source)
        self.vms.show(result.decision, plate=anpr.plate if anpr else None)

        ambient = self.last_env.ambient_c_x100 / 100 if self.last_env else None
        ingest = build_ingest_body(dm.device_id, event_id, dm.occurred_at, dm.measurement, anpr, rfid, raw_ref=f"pass:{dm.device_id}:{dm.pass_id}", ambient_temp_c=ambient)
        edge_decision = self.mirror.decision_payload(result, ident)
        topic = self.cfg.topic_events
        # one durable event per pass with everything the cloud needs (idempotent on edge_event_id), plus the decision event
        self.outbox.enqueue(event_id, topic, build_event(event_id, "weighing.completed", dm.occurred_at, self.cfg, {"ingest": ingest, "edge_decision": edge_decision, "source": dm.source, "truth": dm.truth}))
        dec_id = new_event_id()
        self.outbox.enqueue(dec_id, topic, build_event(dec_id, "clearance.decided", datetime.now(UTC), self.cfg, {"weighing_edge_event_id": event_id, **edge_decision}))
        latency_ms = (time.perf_counter() - t0) * 1000
        self.counters["passes"] += 1
        self.counters[result.decision] = self.counters.get(result.decision, 0) + 1
        summary = {
            "event_id": event_id, "pass_id": dm.pass_id, "decision": result.decision, "gvm_kg": dm.measurement["gvm_kg"], "gvm_u_kg": dm.measurement["gvm_u_kg"],
            "axles": len(dm.measurement["axles"]), "axle_config": dm.measurement["axle_config"], "speed_mps": dm.measurement["speed_mps"],
            "identity": ident.method, "plate": anpr.plate if anpr else None, "epc": rfid.epc if rfid else None,
            "flags": dm.measurement["quality_flags"], "latency_ms": round(latency_ms, 1), "source": dm.source,
            "truth_gvm_kg": dm.truth["gvm_kg"] if dm.truth else None,
        }
        log.info("pass %s", json.dumps(summary, default=str))
        return summary

    # ------------------------------------------------------------------ health
    def publish_health(self) -> None:
        payload = {
            "status": "online", "gateway": GATEWAY_VERSION, "ts": datetime.now(UTC).isoformat(), "outbox": self.outbox.stats(),
            "uplink_connected": self.uplink.connected, "vms": self.vms.state, "counters": self.counters,
            "env": self.last_env.to_dict() if self.last_env else None,
            "daq_health": None if self.last_health is None else [{"ch": self.last_health.first_channel + i, "noise_rms_kg": c.noise_rms_kg_x10 / 10, "baseline_kg": c.baseline_kg,
                                                                    "status": {0: "ok", 1: "degraded", 2: "fault"}.get(c.status, "fault"), "flags": c.flags} for i, c in enumerate(self.last_health.channels)],
        }
        self.uplink.publish_retained(self.cfg.topic_health, payload)

    def drain(self) -> None:
        res = self.outbox.drain(self.uplink.publish)
        if res.sent or res.failed or res.parked:
            log.debug("outbox drain sent=%d failed=%d parked=%d pending=%d", res.sent, res.failed, res.parked, self.outbox.pending_count())

    # ------------------------------------------------------------------ loops
    def run_simulated(self, rate_hz: float, count: int | None, seed: int | None, overload_prob: float, fault_prob: float) -> None:
        daq = SimulatedDaq(self.cfg.device_id, seed=seed, overload_prob=overload_prob, sensor_fault_prob=fault_prob)
        plates = [v.plate for v in self.mirror.snapshot.vehicles]
        epc_of = {v.plate: (v.epcs[0] if v.epcs else None) for v in self.mirror.snapshot.vehicles}
        period = 1.0 / rate_hz if rate_hz > 0 else 0.0
        n = 0
        last_health = 0.0
        while count is None or n < count:
            t = time.perf_counter()
            dm = daq.next_pass()
            # choose which registered (or unknown) vehicle this pass "is", so identity mocks are coherent
            if isinstance(self.anpr, MockAnpr) and isinstance(self.rfid, MockRfid):
                if plates and daq.rng.random() > 0.08:
                    plate = str(daq.rng.choice(plates))
                    self.anpr.expect(plate)
                    self.rfid.expect(epc_of.get(plate))
                else:
                    self.anpr.expect(None)
                    self.rfid.expect(None)
            self.handle_pass(dm)
            self.drain()
            if time.time() - last_health > self.cfg.health_period_s:
                self.publish_health()
                last_health = time.time()
            n += 1
            sleep = period - (time.perf_counter() - t)
            if sleep > 0:
                time.sleep(sleep)
        log.info("done: %s outbox=%s", self.counters, self.outbox.stats())

    def run_udp(self, bind: str) -> None:
        client = UdpDaqClient(bind, self.cfg.device_id, on_health=self._on_health, on_env=self._on_env, daq_addr=self.cfg.daq_addr)
        log.info("listening for DAQ frames on %s", bind)
        last_health = last_sync = 0.0
        try:
            while True:
                dm = client.poll()
                if dm is not None:
                    self.handle_pass(dm)
                self.drain()
                now = time.time()
                if now - last_sync > 1.0:
                    # TIME_SYNC: whole-second UTC of the last PPS (gateway disciplined by chrony/gpsd); pps_count mirrors seconds
                    client.send_time_sync(int(now) * 1_000_000, int(now) & 0xFFFFFFFF)
                    last_sync = now
                if now - last_health > self.cfg.health_period_s:
                    self.publish_health()
                    self.vms.heartbeat()
                    last_health = now
        finally:
            client.close()

    def _on_health(self, h: Health) -> None:
        self.last_health = h

    def _on_env(self, e: Env) -> None:
        self.last_env = e


# ---------------------------------------------------------------------------------------------- CLI
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kifaru-gateway", description="KIFARU PORTOS edge gateway")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--simulate", action="store_true", help="generate synthetic passes with kifaru_wim_dsp (source=simulated)")
    src.add_argument("--udp", metavar="HOST:PORT", help="listen for DAQ UDP frames (e.g. 0.0.0.0:5010)")
    p.add_argument("--rate", type=float, default=1.0, help="simulated passes per second")
    p.add_argument("--count", type=int, default=None, help="stop after N simulated passes")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--overload-prob", type=float, default=0.15)
    p.add_argument("--fault-prob", type=float, default=0.03)
    p.add_argument("--station", default="MARIAKANI")
    p.add_argument("--lane", default="L1")
    p.add_argument("--device-id", default=None)
    p.add_argument("--data-dir", default="./gateway-data")
    p.add_argument("--snapshot", default=None, help="limits/registry snapshot JSON (default: <data-dir>/snapshot.json or a demo snapshot)")
    p.add_argument("--uplink", choices=["memory", "mqtt", "http", "auto"], default="memory")
    p.add_argument("--mqtt-host", default="localhost")
    p.add_argument("--mqtt-port", type=int, default=8883)
    p.add_argument("--mqtt-ca")
    p.add_argument("--mqtt-cert")
    p.add_argument("--mqtt-key")
    p.add_argument("--mqtt-no-tls", action="store_true")
    p.add_argument("--http-url")
    p.add_argument("--http-token")
    p.add_argument("--daq-addr", help="DAQ host:port for TIME_SYNC (default: reply to sender on 5011)")
    p.add_argument("--vms-port", help="serial port of the RS-485 VMS (default: mock)")
    p.add_argument("--log-level", default="INFO")
    return p


def build_gateway(args) -> Gateway:
    cfg = GatewayConfig(
        station=args.station, lane=args.lane, device_id=args.device_id or f"daq-{args.station}-{args.lane}", data_dir=Path(args.data_dir),
        mqtt=MqttConfig(host=args.mqtt_host, port=args.mqtt_port, ca_cert=args.mqtt_ca, client_cert=args.mqtt_cert, client_key=args.mqtt_key, tls=not args.mqtt_no_tls),
        http=HttpConfig(base_url=args.http_url, token=args.http_token), daq_addr=args.daq_addr, vms_port=args.vms_port, log_level=args.log_level,
    )
    snapshot_path = Path(args.snapshot) if args.snapshot else cfg.snapshot_path
    if snapshot_path.exists():
        mirror = ClearanceMirror(snapshot_path=snapshot_path)
    else:
        mirror = ClearanceMirror(demo_snapshot() if args.simulate else Snapshot(), snapshot_path=snapshot_path)
        if args.simulate:
            mirror.update_snapshot(mirror.snapshot)
    outbox = Outbox(cfg.outbox_path)
    if args.uplink == "memory":
        uplink = MemoryUplink()
    elif args.uplink == "mqtt":
        uplink = MqttUplink(cfg.mqtt, will_topic=cfg.topic_health)
        uplink.connect()
    elif args.uplink == "http":
        uplink = HttpUplink(cfg.http)
    else:
        m = MqttUplink(cfg.mqtt, will_topic=cfg.topic_health)
        m.connect()
        uplink = CompositeUplink(m, HttpUplink(cfg.http) if cfg.http.base_url else None)
    anpr, rfid = MockAnpr(seed=args.seed), MockRfid(seed=None if args.seed is None else args.seed + 1)
    vms = VmsController(SerialModbusBackend(args.vms_port) if args.vms_port else MockModbusBackend())
    return Gateway(cfg, mirror, outbox, uplink, anpr, rfid, vms)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    gw = build_gateway(args)
    log.info("%s station=%s lane=%s device=%s uplink=%s outbox=%s", GATEWAY_VERSION, gw.cfg.station, gw.cfg.lane, gw.cfg.device_id, args.uplink, gw.cfg.outbox_path)
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    if args.simulate:
        gw.run_simulated(args.rate, args.count, args.seed, args.overload_prob, args.fault_prob)
    elif args.udp:
        gw.run_udp(args.udp)
    else:
        build_parser().print_help()
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

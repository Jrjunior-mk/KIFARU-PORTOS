"""End-to-end: simulated DAQ -> identity mocks -> mirror decision -> VMS -> outbox -> uplink (EdgeIngestIn shape)."""
import time
from pathlib import Path

from kifaru_gateway.clearance_mirror import ClearanceMirror
from kifaru_gateway.config import GatewayConfig
from kifaru_gateway.daq_client import SimulatedDaq
from kifaru_gateway.identity import MockAnpr, MockRfid
from kifaru_gateway.main import Gateway, demo_snapshot
from kifaru_gateway.outbox import Outbox
from kifaru_gateway.uplink import MemoryUplink
from kifaru_gateway.vms import MockModbusBackend, VmsController
from ulid import ULID


def _gateway(tmp_path: Path, seed=3):
    cfg = GatewayConfig(station="TEST", lane="L9", device_id="daq-TEST-L9", data_dir=tmp_path)
    gw = Gateway(cfg, ClearanceMirror(demo_snapshot()), Outbox(cfg.outbox_path), MemoryUplink(), MockAnpr(seed=seed, misread_prob=0.0, miss_prob=0.0), MockRfid(seed=seed, missing_prob=0.0),
                 VmsController(MockModbusBackend()))
    return gw


def test_simulated_daq_produces_api_shaped_measurements():
    daq = SimulatedDaq("daq-x", seed=11, sensor_fault_prob=0.0)
    dm = daq.next_pass()
    m = dm.measurement
    assert dm.source == "simulated" and dm.truth and dm.truth["gvm_kg"] > 0
    assert set(m) >= {"gvm_kg", "gvm_u_kg", "axles", "axle_config", "quality_flags", "sensor_health", "speed_mps", "pavement_temp_c"}
    assert len(m["axles"]) == len(dm.truth["axle_loads_kg"])
    assert abs(m["gvm_kg"] - dm.truth["gvm_kg"]) / dm.truth["gvm_kg"] < 0.06
    frames = daq.frames_for(dm)
    assert len(frames) == len(m["axles"]) + 1


def test_pipeline_end_to_end_with_outage(tmp_path):
    gw = _gateway(tmp_path)
    daq = SimulatedDaq(gw.cfg.device_id, seed=5, sensor_fault_prob=0.0)
    gw.uplink.down = True
    summaries = []
    for _ in range(6):
        dm = daq.next_pass()
        gw.anpr.expect("KCA 123A")
        gw.rfid.expect("E2801160600002050B2B0001")
        summaries.append(gw.handle_pass(dm))
        gw.drain()
    assert gw.outbox.pending_count() == 12 and gw.uplink.published == []  # 2 events per pass, nothing lost
    assert all(s["decision"] in ("GREEN", "AMBER", "RED") for s in summaries)
    assert all(len(s["event_id"]) == 26 and ULID.from_str(s["event_id"]) for s in summaries)
    assert gw.vms.state["signal"] in ("GREEN", "AMBER", "RED") and gw.vms.state["plate"] == "KCA 123A"

    gw.uplink.down = False
    t = time.time() + 3600.0  # backoff deadlines were set against the real clock; jump past them
    for _ in range(5):
        gw.outbox.drain(gw.uplink.publish, now=t)
        t += 120
    assert gw.outbox.pending_count() == 0 and len(gw.uplink.published) == 12

    weighing = [p for _, p, _ in gw.uplink.published if p["type"] == "weighing.completed"]
    assert len(weighing) == 6
    body = weighing[0]["payload"]["ingest"]
    assert set(body) == {"device_id", "edge_event_id", "occurred_at", "measurement", "anpr_plate", "anpr_confidence", "rfid_epc", "rfid_confidence", "raw_ref", "ambient_temp_c"}
    assert body["device_id"] == "daq-TEST-L9" and body["edge_event_id"] == weighing[0]["event_id"] and body["anpr_plate"] == "KCA 123A"
    assert weighing[0]["payload"]["edge_decision"]["engine_version"].startswith("clr-")
    assert weighing[0]["station_id"] == "TEST" and weighing[0]["lane_id"] == "L9" and weighing[0]["producer"] == "gw-TEST-L9"
    # ULID order == publish order (strict replay)
    ids = [e for _, _, e in gw.uplink.published]
    assert ids == sorted(ids)
    gw.outbox.close()


def test_health_retained_message(tmp_path):
    gw = _gateway(tmp_path)
    gw.publish_health()
    h = gw.uplink.retained[gw.cfg.topic_health]
    assert h["status"] == "online" and "outbox" in h and h["vms"]["signal"] == "off"
    gw.outbox.close()

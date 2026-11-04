"""The edge mirror must produce exactly the API engine's decision (same inputs, same seed -> same evidence hash)."""
from datetime import UTC, datetime, timedelta

from kifaru_gateway.clearance_mirror import ClearanceMirror, Snapshot, VehicleRecord, audit_seed_for, measurement_input
from kifaru_gateway.identity import AnprRead, RfidRead

from kifaru.services import clearance_engine as ce
from kifaru.services.limits import DEFAULT_LIMITS

VEH = VehicleRecord("01TESTVEH0000000000000001", "KCA 123A", "1+1+2", 14500, 42000, epcs=["E2801160600002050B2B0001"])
WATCH = VehicleRecord("01TESTVEH0000000000000002", "KDB 456B", "1+2+2", 16000, 48000, epcs=["E2801160600002050B2B0002"], watchlist_reason="stolen")
FIXED_MEASUREMENT = {
    "pipeline_version": "wim-dsp-0.3", "fs_hz": 8000.0, "speed_mps": 19.5, "speed_u_mps": 0.1,
    "axles": [
        {"index": 0, "load_kg": 6400, "u_kg": 420, "spacing_to_next_m": 3.6, "group_no": 1, "per_row_kg": {}},
        {"index": 1, "load_kg": 9100, "u_kg": 500, "spacing_to_next_m": 5.8, "group_no": 2, "per_row_kg": {}},
        {"index": 2, "load_kg": 8300, "u_kg": 480, "spacing_to_next_m": 1.35, "group_no": 3, "per_row_kg": {}},
        {"index": 3, "load_kg": 8400, "u_kg": 480, "spacing_to_next_m": None, "group_no": 3, "per_row_kg": {}},
    ],
    "gvm_kg": 32200, "gvm_u_kg": 950, "axle_config": "1+1+2", "class_code": "HGV4", "quality_flags": [],
    "sensor_health": {"P1": {"status": "ok", "reasons": []}, "P2": {"status": "ok", "reasons": []}, "P3": {"status": "ok", "reasons": []}, "BP": {"status": "ok", "reasons": []}},
    "pavement_temp_c": 33.4, "coverage_factor": 2.0,
}


def _snapshot(valid=True):
    until = (datetime.now(UTC) + timedelta(days=90)).isoformat() if valid else (datetime.now(UTC) - timedelta(days=1)).isoformat()
    return Snapshot(version="test", vehicles=[VEH, WATCH], calibration_valid_until=until)


def test_mirror_matches_api_engine_exactly():
    mirror = ClearanceMirror(_snapshot())
    event_id = "01J9ZK4Q8W1N3M5R7T9V2X4Z6B"
    at = datetime.now(UTC)
    anpr, rfid = AnprRead("KCA 123A", 0.93), RfidRead("E2801160600002050B2B0001", -52.0, 6, 1, 0.99)
    result, ident = mirror.decide(FIXED_MEASUREMENT, anpr, rfid, event_id, at)

    # the same call made the way weighing_service.process_lane_pass makes it
    m_in = measurement_input(FIXED_MEASUREMENT, "live")
    conf = 1.0 - (1.0 - 0.93) * (1.0 - 0.99)
    id_in = ce.IdentityInput(conf, VEH.vehicle_id, "rfid+anpr", "KCA 123A", "E2801160600002050B2B0001")
    v_in = ce.VehicleInput(VEH.vehicle_id, VEH.plate, VEH.axle_config, VEH.tare_kg, VEH.max_gvm_kg, None, None)
    direct = ce.decide(m_in, id_in, v_in, None, limits=DEFAULT_LIMITS, identity_min_confidence=0.90, audit_rate=0.02,
                       audit_seed=audit_seed_for(event_id), lane_calibration_valid=True)

    assert ident.method == "rfid+anpr" and abs(ident.confidence - conf) < 1e-12
    assert result.decision == direct.decision == "GREEN"
    assert result.evidence_hash == direct.evidence_hash
    assert result.rules_fired == direct.rules_fired
    assert result.margins == direct.margins
    assert result.engine_version == ce.ENGINE_VERSION and result.limits_version == DEFAULT_LIMITS.version


def test_identity_conflict_is_red_and_watchlist_is_red():
    mirror = ClearanceMirror(_snapshot())
    at = datetime.now(UTC)
    # plate of vehicle 1 with the tag of vehicle 2 -> cloning suspicion
    r, ident = mirror.decide(FIXED_MEASUREMENT, AnprRead("KCA 123A", 0.95), RfidRead("E2801160600002050B2B0002", -50, 5, 1, 0.98), "01J9ZK4Q8W1N3M5R7T9V2X4Z6C", at)
    assert ident.method == "conflict" and r.decision == "RED"
    assert any(x["rule"] == "IDENTITY_CONFLICT" for x in r.rules_fired)
    r, _ = mirror.decide(FIXED_MEASUREMENT, AnprRead("KDB 456B", 0.95), None, "01J9ZK4Q8W1N3M5R7T9V2X4Z6D", at)
    assert r.decision == "RED" and any(x["rule"] == "WATCHLIST" for x in r.rules_fired)


def test_unknown_vehicle_and_expired_calibration_block_green():
    at = datetime.now(UTC)
    r, ident = ClearanceMirror(_snapshot()).decide(FIXED_MEASUREMENT, AnprRead("KZZ 999Z", 0.9), None, "01J9ZK4Q8W1N3M5R7T9V2X4Z6E", at)
    assert ident.method == "none" and r.decision == "AMBER" and any(x["rule"] == "VEHICLE_UNKNOWN" for x in r.rules_fired)
    r, _ = ClearanceMirror(_snapshot(valid=False)).decide(FIXED_MEASUREMENT, AnprRead("KCA 123A", 0.95), RfidRead("E2801160600002050B2B0001", -50, 5, 1, 0.98), "01J9ZK4Q8W1N3M5R7T9V2X4Z6F", at)
    assert r.decision == "AMBER" and "calibration_expired" in r.margins["quality_flags"]


def test_certain_overload_is_red_without_cloud():
    heavy = dict(FIXED_MEASUREMENT, gvm_kg=47000, gvm_u_kg=1200, axles=[dict(a, load_kg=a["load_kg"] + 3700) for a in FIXED_MEASUREMENT["axles"]])
    r, _ = ClearanceMirror(_snapshot()).decide(heavy, AnprRead("KCA 123A", 0.95), RfidRead("E2801160600002050B2B0001", -50, 5, 1, 0.98), "01J9ZK4Q8W1N3M5R7T9V2X4Z6G", datetime.now(UTC))
    assert r.decision == "RED" and any(x["rule"] in ("GVM_OVER_CERTAIN", "AXLE_GROUP_OVER_CERTAIN") for x in r.rules_fired)


def test_snapshot_round_trip(tmp_path):
    s = _snapshot()
    s.save(tmp_path / "snap.json")
    s2 = Snapshot.load(tmp_path / "snap.json")
    assert s2.version == "test" and [v.plate for v in s2.vehicles] == ["KCA 123A", "KDB 456B"]
    assert s2.limit_set() == DEFAULT_LIMITS

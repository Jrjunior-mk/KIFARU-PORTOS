from datetime import UTC, datetime, timedelta

import numpy as np

from kifaru_ai_agents import (
    BackhaulMatchingAgent,
    CargoVerificationAgent,
    EnvironmentalAgent,
    OperationalIncidentAgent,
    Orchestrator,
    QueueOptimizationAgent,
    ReleasePredictionAgent,
    SecurityAnomalyAgent,
    TrafficForecastAgent,
    VehicleIdentityAgent,
    WeighingIntelligenceAgent,
)

NOW = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


def test_every_agent_has_catalogue_entry_and_handles_bad_input():
    o = Orchestrator()
    cat = o.catalogue()
    assert len(cat["agents"]) == 10
    for a in o.agents.values():
        r = a.run({})  # missing/empty inputs must never raise
        assert isinstance(r.ok, bool) and 0.0 <= r.confidence <= 1.0
        required = [k for k, v in a.inputs.items() if not v.startswith("optional")]
        if required:
            assert r.ok is False and "missing input" in (r.error or "")


def test_traffic_forecast_persistence_holt_and_hgb():
    a = TrafficForecastAgent()
    series = [{"ts": NOW + timedelta(minutes=15 * i), "queue_len": 10 + (i % 4), "arrivals_per_hour": 80 + 5 * (i % 3), "avg_wait_s": 600} for i in range(3)]
    r = a.run({"series": series, "horizons_min": [15, 30, 60, 120], "capacity_per_hour": 120})
    assert r.ok and r.output["model_version"] == "persistence"
    series = [{"ts": NOW + timedelta(minutes=15 * i), "queue_len": 10 + (i % 4), "arrivals_per_hour": 80, "avg_wait_s": 600} for i in range(12)]
    r = a.run({"series": series, "horizons_min": [15, 30, 60, 120], "capacity_per_hour": 120})
    assert r.ok and r.output["model_version"] == "holt-v1"
    rng = np.random.default_rng(0)
    series = [{"ts": NOW + timedelta(minutes=15 * i), "queue_len": 10 + 5 * np.sin(i / 8) + rng.normal(0, 1), "arrivals_per_hour": 80 + 10 * np.sin(i / 8), "avg_wait_s": 600} for i in range(96)]
    r = a.run({"series": series, "horizons_min": [15, 30, 60, 120], "capacity_per_hour": 120})
    assert r.ok and r.output["model_version"] == "hgb-lags-v1"
    for h in ("15", "30", "60", "120"):
        f = r.output["forecasts"][h]
        assert f["queue_len_lower"] <= f["queue_len"] <= f["queue_len_upper"]


def test_backhaul_matcher_ranks_feasible_first_and_explains():
    a = BackhaulMatchingAgent()
    offer = {"mass_kg": 20000, "cargo_type": "general", "origin_lat": -1.29, "origin_lon": 36.82, "dest_lat": -4.04, "dest_lon": 39.67,
             "ready_from": NOW, "deadline": NOW + timedelta(days=2), "offered_price_kes": 120000}
    trucks = [
        {"vehicle_id": "near_ok", "payload_capacity_kg": 28000, "body_type": "flatbed", "lat": -1.3, "lon": 36.8, "home_lat": -4.04, "home_lon": 39.67},
        {"vehicle_id": "too_small", "payload_capacity_kg": 10000, "body_type": "flatbed", "lat": -1.3, "lon": 36.8, "home_lat": -4.04, "home_lon": 39.67},
        {"vehicle_id": "tanker", "payload_capacity_kg": 30000, "body_type": "tanker", "lat": -1.3, "lon": 36.8, "home_lat": -4.04, "home_lon": 39.67},
        # Malindi: 120 km from home, but the Nairobi pickup adds ~900 km of detour
        {"vehicle_id": "far", "payload_capacity_kg": 28000, "body_type": "flatbed", "lat": -3.22, "lon": 40.12, "home_lat": -4.04, "home_lon": 39.67},
    ]
    r = a.run({"offer": offer, "trucks": trucks})
    assert r.ok
    m = r.output["matches"]
    assert m[0]["vehicle_id"] == "near_ok" and m[0]["feasible"]
    assert {x["vehicle_id"] for x in m if not x["feasible"]} == {"too_small", "tanker"}
    assert m[0]["co2_avoided_kg"] > 0 and "score_components" in m[0]["explanation"]


def test_release_predictor_quantiles_and_reasons():
    r = ReleasePredictionAgent().run({"stage": "at_port", "now": NOW, "has_declaration": False, "seal_status": "unknown", "station_utilisation": 0.9, "warehouse_ready": False, "last_decision": "AMBER"})
    assert r.ok
    p10, p50, p90 = (datetime.fromisoformat(r.output[k]) for k in ("p10", "p50", "p90"))
    assert p10 < p50 < p90 and p50 > NOW + timedelta(hours=24)
    assert any("declaration" in x for x in r.output["reasons"])


def test_environmental_savings_positive_and_labelled():
    r = EnvironmentalAgent().run({"stops_avoided": 100, "stops_made": 20, "avg_queue_wait_s": 1800, "empty_km": 500, "empty_km_avoided": 200})
    assert r.ok and r.output["savings"]["litres"] > 0 and "modelled" in r.output["label"]


def test_identity_cargo_security_incident_queue_agents():
    assert VehicleIdentityAgent().run({"anpr_vehicle_id": "a", "rfid_vehicle_id": "b", "anpr_confidence": 0.9, "rfid_confidence": 0.9}).output["method"] == "conflict"
    assert VehicleIdentityAgent().run({"anpr_vehicle_id": "a", "rfid_vehicle_id": "a", "anpr_confidence": 0.9, "rfid_confidence": 0.9}).output["confidence"] > 0.98
    c = CargoVerificationAgent().run({"gvm_kg": 40000, "tare_kg": 14000, "declared_mass_kg": 10000, "seal_status": "breached"})
    assert c.output["anomaly_score"] >= 0.8
    s = SecurityAnomalyAgent().run({"events": [
        {"type": "weighing", "ts": NOW, "epc": "E1", "lat": -4.0, "lon": 39.6},
        {"type": "weighing", "ts": NOW + timedelta(minutes=30), "epc": "E1", "lat": -1.3, "lon": 36.8},
    ]})
    assert any(a["kind"] == "impossible_travel" for a in s.output["alerts"])
    i = OperationalIncidentAgent().run({"sensor_health": {"P1": "fault"}, "station_status": "operational", "queue_len": 200, "capacity_per_hour": 120})
    assert len(i.output["incidents"]) == 2
    q = QueueOptimizationAgent().run({"stations": [{"station_id": "s1", "code": "MRK", "alt_allowed": False, "capacity_per_hour": 4, "forecast": {}, "distance_km": 0},
                                                   {"station_id": "s2", "code": "ATH", "alt_allowed": True, "capacity_per_hour": 100, "forecast": {}, "distance_km": 20}],
                                      "requests": [{"vehicle_id": f"v{i}", "priority": 5} for i in range(3)]})
    assert all(a["station_id"] for a in q.output["assignments"])


def test_weighing_intelligence_flags_row_bias():
    m = {"gvm_kg": 30000, "speed_mps": 15, "pavement_temp_c": 30, "axles": [{"load_kg": 10000, "per_row_kg": {"P1": 11500, "P2": 10000, "BP": 10000}}] * 3}
    r = WeighingIntelligenceAgent().run({"measurement": m})
    assert "row_bias:P1" in r.output["suggested_flags"] and r.output["plausible"] is False


def test_pipeline_runs_and_collects_results():
    o = Orchestrator()
    out = o.run_pipeline("lane_pass", {"measurement": {"gvm_kg": 30000, "axles": []}, "anpr_vehicle_id": "a", "rfid_vehicle_id": "a", "anpr_confidence": .9, "rfid_confidence": .9,
                                       "gvm_kg": 30000, "tare_kg": 14000})
    assert out["pipeline"] == "lane_pass" and len(out["results"]) == 3 and out["ok"]

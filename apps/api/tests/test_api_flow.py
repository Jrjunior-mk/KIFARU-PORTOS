"""End-to-end API tests over the seeded SQLite database: auth, RBAC, simulator -> clearance -> ticket -> ledger,
passport, queue slots, backhaul two-party acceptance, environment report, integrations in mock mode."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .conftest import h

API = "/api/v1"


# ------------------------------------------------------------------ auth & security
def test_health_and_openapi(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").json()["status"] == "ready"
    spec = client.get("/openapi.json").json()
    assert "/api/v1/weighing/simulate" in spec["paths"]


def test_login_rejects_bad_password_and_locks_after_5(client):
    client.post(f"{API}/auth/register", json={"email": "lockme@example.com", "password": "Lock#Me2026xx", "full_name": "Lock Me"})
    for _ in range(5):
        r = client.post(f"{API}/auth/login", json={"email": "lockme@example.com", "password": "wrong-password-xx"})
        assert r.status_code == 401
    r = client.post(f"{API}/auth/login", json={"email": "lockme@example.com", "password": "wrong-password-xx"})
    assert r.status_code == 423


def test_refresh_rotation_and_me(client, cargo_owner):
    r = client.post(f"{API}/auth/refresh", json={"refresh_token": cargo_owner["_refresh"]})
    assert r.status_code == 200
    r2 = client.post(f"{API}/auth/refresh", json={"refresh_token": cargo_owner["_refresh"]})
    assert r2.status_code == 401  # old refresh token revoked (rotation)
    me = client.get(f"{API}/auth/me", headers=h(cargo_owner)).json()
    assert me["roles"] == ["cargo_owner"] and me["org_type"] == "cargo_owner"


def test_rbac_blocks_cargo_owner_from_admin_and_simulator(client, cargo_owner):
    assert client.get(f"{API}/admin/users", headers=h(cargo_owner)).status_code == 403
    assert client.post(f"{API}/weighing/simulate", headers=h(cargo_owner), json={"lane_id": "x"}).status_code == 403
    assert client.get(f"{API}/admin/users").status_code == 401


def test_register_new_cargo_owner(client):
    r = client.post(f"{API}/auth/register", json={"email": "new.owner@example.com", "password": "Str0ngPassw0rd!", "full_name": "New Owner", "org_name": "New Owner Ltd"})
    assert r.status_code == 201 and r.json()["roles"] == ["cargo_owner"]
    assert client.post(f"{API}/auth/register", json={"email": "new.owner@example.com", "password": "Str0ngPassw0rd!", "full_name": "Dup"}).status_code == 409


def test_mfa_setup_and_privileged_override_requires_mfa(client, operator):
    import pyotp

    setup = client.post(f"{API}/auth/mfa/setup", headers=h(operator)).json()
    code = pyotp.TOTP(setup["secret"]).now()
    assert client.post(f"{API}/auth/mfa/enable", headers=h(operator), json={"code": code}).status_code == 204
    # token without MFA claim can no longer perform MFA-gated actions
    r = client.post(f"{API}/weighing/events/XXXXXXXXXXXXXXXXXXXXXXXXXX/override-release", headers=h(operator), json={"reason": "testing mfa gate here"})
    assert r.status_code == 403
    ver = client.post(f"{API}/auth/mfa/verify", headers=h(operator), json={"code": pyotp.TOTP(setup["secret"]).now()})
    assert ver.status_code == 200 and ver.json()["mfa_required"] is False
    operator["Authorization"] = f"Bearer {ver.json()['access_token']}"


# ------------------------------------------------------------------ stations & simulator -> clearance
def test_stations_seeded_with_lanes_and_sensors(client, operator):
    sts = client.get(f"{API}/stations", headers=h(operator)).json()
    codes = {s["code"] for s in sts}
    assert {"MRK", "ATH", "MBS-GATE18", "GLG"} <= codes
    mrk = next(s for s in sts if s["code"] == "MRK")
    assert len(mrk["lanes"]) == 3 and len(mrk["lanes"][0]["sensors"]) == 13


def _lane(client, auth, code="MRK"):
    sts = client.get(f"{API}/stations", headers=h(auth)).json()
    st = next(s for s in sts if s["code"] == code)
    return st, next(ln for ln in st["lanes"] if ln["type"] == "wim_highspeed")


def test_simulate_pass_produces_decision_ticket_and_ledger(client, operator, auditor):
    _st, lane = _lane(client, operator)
    r = client.post(f"{API}/weighing/simulate", headers=h(operator), json={"lane_id": lane["id"], "count": 12, "seed": 7, "sensor_fault_prob": 0.0, "unregistered_prob": 0.0, "clone_prob": 0.0, "anpr_misread_prob": 0.0, "rfid_missing_prob": 0.0})
    assert r.status_code == 201, r.text
    evs = r.json()
    assert len(evs) == 12
    for ev in evs:
        assert ev["source"] == "simulated"
        assert ev["decision"]["decision"] in ("GREEN", "AMBER", "RED")
        assert ev["decision"]["latency_ms"] < 2000
        assert len(ev["decision"]["evidence_hash"]) == 64
        assert ev["decision"]["ticket_type"] == "prescreen"
        assert ev["identity"]["confidence"] > 0.5 and ev["identity"]["method"] in ("rfid+anpr", "anpr")  # one seeded truck has no tag
        assert ev["axle_count"] >= 2 and ev["gvm_uncertainty_kg"] > 0
    decisions = {e["decision"]["decision"] for e in evs}
    assert "GREEN" in decisions
    # ticket verification (public) + QR
    ev = evs[0]
    t = client.get(f"{API}/tickets/{ev['decision']['ticket_id']}", headers=h(operator)).json()
    assert t["signature_valid"] is True and "not a legal weight certificate" in t["payload"]["legal_status"]
    v = client.get(f"{API}/tickets/verify/{t['qr_token']}").json()
    assert v["valid"] is True and v["source"] == "simulated"
    assert client.get(f"{API}/tickets/verify/not-a-token").json()["valid"] is False
    assert client.get(f"{API}/tickets/{t['id']}/qr.svg", headers=h(operator)).headers["content-type"].startswith("image/svg")
    # ledger chain verifies
    chain = client.get(f"{API}/admin/ledger/verify", headers=h(auditor)).json()
    assert chain["ok"] is True and chain["checked"] >= 24
    # stats
    s = client.get(f"{API}/weighing/stats", headers=h(operator)).json()
    assert s["total"] >= 12 and s["by_source"].get("simulated", 0) >= 12


def test_forced_overload_is_red_and_static_verify_issues_certified_ticket(client, operator):
    _st, lane = _lane(client, operator)
    vehicles = client.get(f"{API}/fleet/vehicles", headers=h(operator)).json()
    v = next(x for x in vehicles if x["axle_config"] == "1+1+2")
    r = client.post(f"{API}/weighing/simulate", headers=h(operator), json={"lane_id": lane["id"], "vehicle_id": v["id"], "force_gvm_kg": 52000, "seed": 3, "sensor_fault_prob": 0.0, "anpr_misread_prob": 0.0, "rfid_missing_prob": 0.0, "clone_prob": 0.0})
    ev = r.json()[0]
    assert ev["decision"]["decision"] == "RED"
    rules = {x["rule"] for x in ev["decision"]["rules_fired"]}
    assert "GVM_OVER_CERTAIN" in rules or "AXLE_GROUP_OVER_CERTAIN" in rules
    # operator records the static scale result -> certified ticket
    r = client.post(f"{API}/weighing/events/{ev['id']}/static-verify", headers=h(operator), json={"static_gvm_kg": 51500, "notes": "static bridge 2"})
    assert r.status_code == 200, r.text
    assert r.json()["decision"]["ticket_type"] == "static_certified"
    assert r.json()["decision"]["static_verified_gvm_kg"] == 51500
    # override now allowed (operator has MFA token from earlier test)
    r = client.post(f"{API}/weighing/events/{ev['id']}/override-release", headers=h(operator), json={"reason": "redistributed load verified on static scale"})
    assert r.status_code == 200 and r.json()["decision"]["override_reason"]


def test_sensor_fault_never_green(client, operator):
    _st, lane = _lane(client, operator)
    r = client.post(f"{API}/weighing/simulate", headers=h(operator), json={"lane_id": lane["id"], "count": 6, "seed": 11, "sensor_fault_prob": 1.0, "unregistered_prob": 0.0})
    for ev in r.json():
        assert ev["decision"]["decision"] != "GREEN"
        assert "sensor_fault" in ev["quality_flags"] or "sensor_degraded" in ev["quality_flags"]


def test_unregistered_vehicle_is_amber(client, operator):
    _st, lane = _lane(client, operator)
    r = client.post(f"{API}/weighing/simulate", headers=h(operator), json={"lane_id": lane["id"], "count": 3, "seed": 5, "unregistered_prob": 1.0, "sensor_fault_prob": 0.0, "overload_prob": 0.0})
    for ev in r.json():
        assert ev["vehicle_id"] is None and ev["decision"]["decision"] in ("AMBER", "RED")
        assert any(x["rule"] == "VEHICLE_UNKNOWN" for x in ev["decision"]["rules_fired"])


def test_edge_ingest_is_idempotent(client, operator):
    _st, lane = _lane(client, operator)
    from ulid import ULID

    eid = str(ULID())
    payload = {"device_id": lane["device_id"], "edge_event_id": eid, "occurred_at": datetime.now(UTC).isoformat(),
               "measurement": {"speed_mps": 18.0, "gvm_kg": 34400, "gvm_u_kg": 900, "axle_config": "1+1+2", "class_code": "HGV4", "quality_flags": [],
                               "sensor_health": {"P1": {"status": "ok", "reasons": []}}, "pavement_temp_c": 31.0,
                               "axles": [{"index": 0, "load_kg": 7700, "u_kg": 300, "group_no": 1}, {"index": 1, "load_kg": 9500, "u_kg": 400, "group_no": 2},
                                         {"index": 2, "load_kg": 8600, "u_kg": 400, "group_no": 3}, {"index": 3, "load_kg": 8600, "u_kg": 400, "group_no": 3}]},
               "anpr_plate": "KDA 412B", "anpr_confidence": 0.95, "rfid_epc": "E2000017221101441890A001", "rfid_confidence": 0.99}
    r1 = client.post(f"{API}/weighing/ingest", headers=h(operator), json=payload)
    r2 = client.post(f"{API}/weighing/ingest", headers=h(operator), json=payload)
    assert r1.status_code == 201 and r2.status_code == 201 and r1.json()["id"] == r2.json()["id"]
    assert r1.json()["source"] == "live" and r1.json()["decision"]["decision"] == "GREEN"


def test_tenant_isolation_on_weighing_events(client, transporter, other_transporter, operator):
    mine = client.get(f"{API}/weighing/events", headers=h(transporter)).json()
    theirs = client.get(f"{API}/weighing/events", headers=h(other_transporter)).json()
    all_ = client.get(f"{API}/weighing/events", headers=h(operator)).json()
    assert all(e["vehicle_id"] for e in mine) and not ({e["id"] for e in mine} & {e["id"] for e in theirs})
    assert len(all_) >= len(mine)


# ------------------------------------------------------------------ fleet
def test_fleet_crud_and_watchlist_red(client, transporter, admin, operator):
    r = client.post(f"{API}/fleet/vehicles", headers=h(transporter), json={"plate": "KDH 777Z", "axle_config": "1+2+3", "tare_kg": 16000, "max_gvm_kg": 50000, "payload_capacity_kg": 34000, "body_type": "flatbed", "rfid_epc": "E20000172211014418900099"})
    assert r.status_code == 201, r.text
    v = r.json()
    assert client.post(f"{API}/fleet/vehicles", headers=h(transporter), json={"plate": "kdh777z", "axle_config": "1+2+3", "tare_kg": 16000}).status_code == 409
    assert client.post(f"{API}/fleet/vehicles/{v['id']}/watchlist", headers=h(admin), json={"reason": "KRA alert 2026/11"}).json()["watchlisted"] is True
    _st, lane = _lane(client, operator)
    ev = client.post(f"{API}/weighing/simulate", headers=h(operator), json={"lane_id": lane["id"], "vehicle_id": v["id"], "seed": 1, "overload_prob": 0.0, "sensor_fault_prob": 0.0, "anpr_misread_prob": 0.0, "rfid_missing_prob": 0.0}).json()[0]
    assert ev["decision"]["decision"] == "RED" and any(x["rule"] == "WATCHLIST" for x in ev["decision"]["rules_fired"])
    assert client.post(f"{API}/fleet/vehicles/{v['id']}/position", headers=h(transporter), json={"lat": -3.9, "lon": 39.5}).json()["last_lat"] == -3.9


# ------------------------------------------------------------------ cargo passport
def test_cargo_passport_flow(client, cargo_owner, transporter, admin):
    vehicles = client.get(f"{API}/fleet/vehicles", headers=h(transporter)).json()
    r = client.post(f"{API}/shipments", headers=h(cargo_owner), json={"description": "Rice 20 t", "cargo_type": "general", "origin": "Mombasa", "destination": "Nairobi",
                                                                      "declared_mass_kg": 20000, "containers": [{"number": "MSKU9070323"}], "declaration_reference": "KRA-TEST-1", "seal_id": "SEAL-T1"})
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["stage"] == "declared" and s["containers"][0]["number"] == "MSKU9070323" and s["seals"][0]["status"] == "armed"
    bad = client.post(f"{API}/shipments", headers=h(cargo_owner), json={"description": "x", "origin": "a", "destination": "b", "declared_mass_kg": 1, "containers": [{"number": "MSKU9070320"}]})
    assert bad.status_code == 422  # ISO 6346 check digit
    r = client.post(f"{API}/shipments/{s['id']}/assign", headers=h(cargo_owner), json={"vehicle_id": vehicles[0]["id"]})
    assert r.json()["vehicle_plate"] == vehicles[0]["plate"]
    r = client.post(f"{API}/shipments/{s['id']}/stage", headers=h(admin), json={"stage": "at_port"})
    assert r.json()["stage"] == "at_port" and "customs_processing" in r.json()["outstanding"]
    assert client.get(f"{API}/shipments/{s['reference']}", headers=h(cargo_owner)).json()["id"] == s["id"]
    # other cargo owner cannot see it
    other = client.post(f"{API}/auth/login", json={"email": "owner@cargo-b.invalid", "password": "***REMOVED***"}).json()
    assert client.get(f"{API}/shipments/{s['id']}", headers={"Authorization": f"Bearer {other['access_token']}"}).status_code == 404
    # seal breach -> next weighing RED
    client.post(f"{API}/shipments/{s['id']}/seal", headers=h(admin), json={"seal_id": "SEAL-T1", "status": "breached"})


# ------------------------------------------------------------------ queue & slots
def test_queue_observation_forecast_and_slot_capacity(client, operator, transporter):
    st, lane = _lane(client, operator)
    for i in range(10):
        client.post(f"{API}/queue/{st['id']}/observe", headers=h(operator), json={"queue_len": 10 + i, "avg_wait_s": 600 + 60 * i, "arrivals_per_hour": 90})
    f = client.get(f"{API}/queue/{st['id']}/forecast", headers=h(operator)).json()
    assert [x["kind"] for x in f] == ["forecast_15", "forecast_30", "forecast_60", "forecast_120"]
    assert all(x["source"] == "forecast" and x["model_version"] for x in f)
    slots = client.get(f"{API}/queue/{st['id']}/slots", headers=h(transporter)).json()
    assert slots and slots[0]["capacity"] == 40
    vehicles = client.get(f"{API}/fleet/vehicles", headers=h(transporter)).json()
    slot = slots[2]["slot_start"]
    r = client.post(f"{API}/queue/{st['id']}/appointments", headers=h(transporter), json={"vehicle_id": vehicles[0]["id"], "slot_start": slot})
    assert r.status_code == 201, r.text
    dup = client.post(f"{API}/queue/{st['id']}/appointments", headers=h(transporter), json={"vehicle_id": vehicles[0]["id"], "slot_start": slots[3]["slot_start"]})
    assert dup.status_code == 409
    misaligned = client.post(f"{API}/queue/{st['id']}/appointments", headers=h(transporter), json={"vehicle_id": vehicles[1]["id"], "slot_start": (datetime.fromisoformat(slot) + timedelta(minutes=7)).isoformat()})
    assert misaligned.status_code == 400
    mine = client.get(f"{API}/queue/appointments/mine", headers=h(transporter)).json()
    assert any(a["plate"] == vehicles[0]["plate"] for a in mine)


# ------------------------------------------------------------------ backhaul marketplace
def test_backhaul_two_party_acceptance(client, cargo_owner, transporter, other_transporter):
    now = datetime.now(UTC)
    r = client.post(f"{API}/backhaul/offers", headers=h(cargo_owner), json={"title": "Return load: maize 18 t Nairobi->Mombasa", "cargo_type": "general", "mass_kg": 18000, "origin": "Nairobi ICD", "origin_lat": -1.32, "origin_lon": 36.89,
                                                                            "destination": "Mombasa", "dest_lat": -4.04, "dest_lon": 39.67, "ready_from": now.isoformat(), "deadline": (now + timedelta(days=3)).isoformat(), "offered_price_kes": 110000})
    assert r.status_code == 201, r.text
    offer = r.json()
    r = client.post(f"{API}/backhaul/offers/{offer['id']}/match", headers=h(cargo_owner))
    assert r.status_code == 200, r.text
    matches = r.json()["matches"]
    assert matches and all(m["score"] > 0 and m["co2_avoided_kg"] >= 0 and "score_components" in m["explanation"] for m in matches)
    m = matches[0]
    # the transporter that owns the truck accepts
    owner_tr = transporter if m["transporter_org_id"] == transporter["_org"] else other_transporter
    wrong_tr = other_transporter if owner_tr is transporter else transporter
    assert client.post(f"{API}/backhaul/matches/{m['id']}/transporter-decision", headers=h(wrong_tr), json={"accept": True}).status_code == 404
    r = client.post(f"{API}/backhaul/matches/{m['id']}/transporter-decision", headers=h(owner_tr), json={"accept": True})
    assert r.json()["status"] == "transporter_accepted"  # not assigned yet: owner must accept too (BKH-04)
    r = client.post(f"{API}/backhaul/matches/{m['id']}/owner-decision", headers=h(cargo_owner), json={"accept": True})
    assert r.json()["status"] == "assigned" and r.json()["assigned_at"]
    r = client.post(f"{API}/backhaul/matches/{m['id']}/deliver", headers=h(owner_tr), json={"receiver_name": "Gate 3"})
    assert r.json()["status"] == "delivered"
    assert client.get(f"{API}/backhaul/offers", headers=h(cargo_owner)).json()[0]["status"] == "delivered"


# ------------------------------------------------------------------ environment, integrations, admin
def test_environment_report_is_labelled_modelled(client, operator):
    r = client.get(f"{API}/environment/report?hours=24", headers=h(operator)).json()
    assert "modelled" in r["label"] and r["savings"]["co2_kg"] >= 0 and r["factors"]["co2_kg_per_l"] == 2.68
    f = client.get(f"{API}/environment/factors").json()
    assert "formulas" in f


def test_integrations_default_mock_and_mode_guard(client, admin, operator):
    ints = client.get(f"{API}/integrations", headers=h(operator)).json()
    assert {i["name"] for i in ints} >= {"kenha", "kpa", "kra", "ntsa", "sms", "maps", "telematics"}
    assert all(i["mode"] == "mock" for i in ints)
    assert client.post(f"{API}/integrations/kra/mode", headers=h(admin), json={"mode": "real"}).status_code == 400  # needs base_url
    look = client.get(f"{API}/integrations/ntsa/vehicle/KDA412B", headers=h(operator)).json()
    assert look["mode"] == "mock" and "MOCK" in look["label"]
    route = client.get(f"{API}/integrations/maps/route?from_lat=-4.04&from_lon=39.67&to_lat=-1.29&to_lon=36.82", headers=h(operator)).json()
    assert route["mode"] == "mock" and 500 < route["distance_km"] < 700


def test_admin_users_audit_incidents_agents(client, admin):
    users = client.get(f"{API}/admin/users", headers=h(admin)).json()
    assert any(u["email"] == "operator@demo.invalid" and u["mfa_enabled"] for u in users)
    r = client.post(f"{API}/admin/users", headers=h(admin), json={"email": "regulator@kenha.local", "password": "Regulat0r#2026", "full_name": "KeNHA Observer", "roles": ["regulator_readonly"]})
    assert r.status_code == 201 and r.json()["roles"] == ["regulator_readonly"]
    audit_ = client.get(f"{API}/admin/audit?entity=user", headers=h(admin)).json()
    assert any(a["action"] == "create" for a in audit_)
    sts = client.get(f"{API}/stations", headers=h(admin)).json()
    glg = next(s for s in sts if s["code"] == "GLG")
    r = client.post(f"{API}/stations/{glg['id']}/status", headers=h(admin), json={"status": "offline", "reason": "power failure"})
    assert r.json()["status"] == "offline"
    inc = client.get(f"{API}/admin/incidents", headers=h(admin)).json()
    assert any(i["category"] == "station_failure" and i["station_id"] == glg["id"] for i in inc)
    inc_id = next(i["id"] for i in inc if i["station_id"] == glg["id"])
    assert client.post(f"{API}/admin/incidents/{inc_id}/close", headers=h(admin)).json()["status"] == "closed"
    assert next(s for s in client.get(f"{API}/stations", headers=h(admin)).json() if s["code"] == "GLG")["status"] == "operational"
    cat = client.get(f"{API}/admin/agents", headers=h(admin)).json()
    assert len(cat["agents"]) == 10 and "advisory" in cat["policy"]
    health = client.get(f"{API}/admin/system/health", headers=h(admin)).json()
    assert health["database"] == "ok"


def test_calibration_expiry_blocks_green(client, admin, operator):
    """An expired lane calibration must block GREEN (QUALITY_BLOCKING) even when the measurement itself is clean."""
    from datetime import timedelta

    from kifaru.db import get_sessionmaker
    from kifaru.models import Lane, utcnow

    sts = client.get(f"{API}/stations", headers=h(admin)).json()
    ath = next(s for s in sts if s["code"] == "ATH")
    lane = next(ln for ln in ath["lanes"] if ln["type"] == "wim_highspeed")
    piezo = next(s for s in lane["sensors"] if s["kind"] == "piezo_quartz")
    r = client.post(f"{API}/stations/sensors/{piezo['id']}/calibrations", headers=h(operator), json={"method": "reference_vehicle", "reference_mass_kg": 30000, "gain": 1.01, "valid_days": 90})
    assert r.status_code == 201
    with get_sessionmaker()() as db:  # expire the lane calibration (no API path may do this: it is a maintenance fact)
        ln = db.get(Lane, lane["id"])
        saved = ln.calibration_valid_to
        ln.calibration_valid_to = utcnow() - timedelta(days=1)
        db.commit()
    try:
        r = client.post(f"{API}/weighing/simulate", headers=h(operator), json={"lane_id": lane["id"], "count": 4, "seed": 2, "overload_prob": 0.0, "sensor_fault_prob": 0.0, "unregistered_prob": 0.0})
        for ev in r.json():
            assert ev["decision"]["decision"] != "GREEN"
            assert any(x["rule"] == "QUALITY_BLOCKING" for x in ev["decision"]["rules_fired"])
    finally:
        with get_sessionmaker()() as db:
            db.get(Lane, lane["id"]).calibration_valid_to = saved
            db.commit()


def test_websocket_receives_live_events(client, operator):
    _st, lane = _lane(client, operator)
    token = operator["Authorization"].split(" ")[1]
    with client.websocket_connect(f"/ws/events?token={token}&types=clearance.decided") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        client.post(f"{API}/weighing/simulate", headers=h(operator), json={"lane_id": lane["id"], "count": 1, "seed": 99})
        msg = ws.receive_json()
        assert msg["type"] == "clearance.decided" and msg["payload"]["source"] == "simulated"

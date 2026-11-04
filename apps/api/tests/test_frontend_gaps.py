"""Regression tests for gaps reported by the frontend and mobile integration work."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .conftest import _login, h

API = "/api/v1"


def test_second_calibration_on_same_sensor_does_not_500(client, operator):
    sts = client.get(f"{API}/stations", headers=h(operator)).json()
    mrk = next(s for s in sts if s["code"] == "MRK")
    lane = next(ln for ln in mrk["lanes"] if ln["type"] == "wim_highspeed")
    sensor = next(s for s in lane["sensors"] if s["kind"] == "bending_plate")
    for gain in (1.00, 1.01):
        r = client.post(f"{API}/stations/sensors/{sensor['id']}/calibrations", headers=h(operator), json={"method": "bench", "gain": gain, "valid_days": 30})
        assert r.status_code == 201, r.text
    recs = client.get(f"{API}/stations/sensors/{sensor['id']}/calibrations", headers=h(operator)).json()
    assert len(recs) >= 2
    assert client.get(f"{API}/stations/{mrk['id']}", headers=h(operator)).status_code == 200


def test_predict_release_populates_passport(client, cargo_owner):
    s = client.post(f"{API}/shipments", headers=h(cargo_owner), json={"description": "Predict me", "origin": "Mombasa", "destination": "Nairobi", "declared_mass_kg": 5000, "declaration_reference": "KRA-P1"}).json()
    r = client.post(f"{API}/shipments/{s['id']}/predict-release", headers=h(cargo_owner))
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["predicted_release_at"] and p["predicted_release_p10"] and p["predicted_release_p90"]
    assert p["prediction_explanation"]["label"] == "advisory prediction"


def test_clearance_and_stage_changes_create_org_notifications(client, operator, transporter, cargo_owner, admin):
    sts = client.get(f"{API}/stations", headers=h(operator)).json()
    lane = next(ln for s in sts for ln in s["lanes"] if ln["type"] == "wim_highspeed")
    v = client.get(f"{API}/fleet/vehicles", headers=h(transporter)).json()[0]
    client.post(f"{API}/weighing/simulate", headers=h(operator), json={"lane_id": lane["id"], "vehicle_id": v["id"], "seed": 31, "sensor_fault_prob": 0.0})
    inbox = client.get(f"{API}/notifications", headers=h(transporter)).json()
    assert any(n["template"] == "clearance" and n["payload"].get("vehicle_id") == v["id"] for n in inbox)
    s = client.post(f"{API}/shipments", headers=h(cargo_owner), json={"description": "Notify me", "origin": "Mombasa", "destination": "Nairobi", "declared_mass_kg": 5000}).json()
    client.post(f"{API}/shipments/{s['id']}/stage", headers=h(admin), json={"stage": "at_port"})
    inbox = client.get(f"{API}/notifications", headers=h(cargo_owner)).json()
    assert any(n["template"] == "cargo_stage" and n["payload"].get("shipment_id") == s["id"] for n in inbox)


def test_warehouse_manager_sees_inbound_appointments(client, cargo_owner, transporter):
    wh_auth = _login(client, "wh@warehouse-a.invalid")
    whs = client.get(f"{API}/shipments/warehouses/all", headers=h(wh_auth)).json()
    wh = next(w for w in whs if w["org_id"] == wh_auth["_org"])
    v = client.get(f"{API}/fleet/vehicles", headers=h(transporter)).json()[-1]
    s = client.post(f"{API}/shipments", headers=h(cargo_owner), json={"description": "Inbound to ICD", "origin": "Mombasa", "destination": "Nairobi ICD", "declared_mass_kg": 9000, "warehouse_id": wh["id"], "vehicle_id": v["id"]}).json()
    sts = client.get(f"{API}/stations", headers=h(transporter)).json()
    st = next(x for x in sts if x["code"] == "ATH")
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    slot = (now - timedelta(minutes=now.minute % 15) + timedelta(hours=3)).isoformat()
    r = client.post(f"{API}/queue/{st['id']}/appointments", headers=h(transporter), json={"vehicle_id": v["id"], "slot_start": slot, "shipment_id": s["id"]})
    assert r.status_code in (201, 409), r.text
    mine = client.get(f"{API}/queue/appointments/mine", headers=h(wh_auth)).json()
    assert any(a["shipment_id"] == s["id"] for a in mine)
    # a different warehouse org must not see it
    other_wh = client.post(f"{API}/auth/register", json={"email": "other.wh@example.com", "password": "Other#Wh2026xx", "full_name": "Other WH", "org_type": "warehouse", "role": "warehouse_manager"}).json()
    theirs = client.get(f"{API}/queue/appointments/mine", headers={"Authorization": f"Bearer {other_wh['access_token']}"}).json()
    assert not any(a["shipment_id"] == s["id"] for a in theirs)

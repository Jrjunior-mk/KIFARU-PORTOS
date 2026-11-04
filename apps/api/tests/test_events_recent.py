"""Polling fallback for the live feed (used where WebSockets are unavailable)."""
from __future__ import annotations

from .conftest import h

API = "/api/v1"


def test_recent_events_rebuilt_from_db_and_tenant_scoped(client, operator, transporter, other_transporter):
    sts = client.get(f"{API}/stations", headers=h(operator)).json()
    lane = next(ln for s in sts for ln in s["lanes"] if ln["type"] == "wim_highspeed")
    mine = client.get(f"{API}/fleet/vehicles", headers=h(transporter)).json()[0]
    client.post(f"{API}/weighing/simulate", headers=h(operator), json={"lane_id": lane["id"], "vehicle_id": mine["id"], "seed": 909, "sensor_fault_prob": 0.0})
    client.post(f"{API}/queue/{sts[0]['id']}/observe", headers=h(operator), json={"queue_len": 5, "avg_wait_s": 300, "arrivals_per_hour": 40})
    all_ = client.get(f"{API}/events/recent?minutes=60", headers=h(operator)).json()
    types = {e["type"] for e in all_}
    assert {"clearance.decided", "weighing.completed", "queue.updated"} <= types
    assert all(e["event_id"] and e["occurred_at"] for e in all_)
    assert len({e["event_id"] for e in all_}) == len(all_)  # deterministic, unique ids
    dec = next(e for e in all_ if e["type"] == "clearance.decided" and e["payload"]["vehicle_id"] == mine["id"])
    assert dec["payload"]["instruction"] and dec["payload"]["station_code"] and dec["payload"]["ticket_qr_token"]
    filtered = client.get(f"{API}/events/recent?types=queue.updated", headers=h(operator)).json()
    assert filtered and all(e["type"] == "queue.updated" for e in filtered)
    theirs = client.get(f"{API}/events/recent?types=clearance.decided", headers=h(other_transporter)).json()
    assert not any(e["payload"]["vehicle_id"] == mine["id"] for e in theirs)
    ours = client.get(f"{API}/events/recent?types=clearance.decided", headers=h(transporter)).json()
    assert any(e["payload"]["vehicle_id"] == mine["id"] for e in ours)

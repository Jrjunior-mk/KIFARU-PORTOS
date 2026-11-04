"""Security tests: token tampering/expiry, role gates, tenant isolation across contexts, WebSocket auth, headers, rate limit."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from kifaru.config import get_settings

from .conftest import h

API = "/api/v1"


def test_tampered_and_expired_tokens_rejected(client, cargo_owner):
    s = get_settings()
    token = cargo_owner["Authorization"].split(" ")[1]
    claims = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    # escalate roles with the wrong key
    forged = jwt.encode({**claims, "roles": ["platform_admin"]}, "not-the-secret-xxxxxxxx", algorithm="HS256")
    assert client.get(f"{API}/admin/users", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    expired = jwt.encode({**claims, "exp": int((datetime.now(UTC) - timedelta(minutes=1)).timestamp())}, s.jwt_secret, algorithm=s.jwt_algorithm)
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    refresh_as_access = jwt.encode({**claims, "type": "refresh"}, s.jwt_secret, algorithm=s.jwt_algorithm)
    assert client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {refresh_as_access}"}).status_code == 401
    assert client.get(f"{API}/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff" and r.headers["X-Frame-Options"] == "DENY"
    assert "X-Response-Time-ms" in r.headers


def test_role_gates_matrix(client, cargo_owner, transporter, operator, auditor):
    cases = [
        (f"{API}/admin/users", "get", cargo_owner, 403),
        (f"{API}/admin/users", "get", transporter, 403),
        (f"{API}/admin/users", "get", operator, 403),
        (f"{API}/admin/audit", "get", auditor, 200),
        (f"{API}/admin/ledger/verify", "get", auditor, 200),
        (f"{API}/admin/ledger/verify", "get", transporter, 403),
        (f"{API}/weighing/simulate", "post", transporter, 403),
        (f"{API}/stations", "post", operator, 403),
        (f"{API}/integrations/kra/mode", "post", operator, 403),
        (f"{API}/backhaul/offers", "post", transporter, 403),  # only cargo owners create offers
    ]
    for url, method, auth, expected in cases:
        r = client.request(method.upper(), url, headers=h(auth), json={} if method == "post" else None)
        assert r.status_code == expected, (url, method, r.status_code, r.text)


def test_tenant_isolation_fleet_shipments_appointments(client, transporter, other_transporter, cargo_owner):
    mine = {v["id"] for v in client.get(f"{API}/fleet/vehicles", headers=h(transporter)).json()}
    theirs = {v["id"] for v in client.get(f"{API}/fleet/vehicles", headers=h(other_transporter)).json()}
    assert mine and theirs and not (mine & theirs)
    other_vehicle = next(iter(theirs))
    assert client.get(f"{API}/fleet/vehicles/{other_vehicle}", headers=h(transporter)).status_code == 404
    assert client.post(f"{API}/fleet/vehicles/{other_vehicle}/position", headers=h(transporter), json={"lat": 0, "lon": 0}).status_code == 404
    # cannot book a slot with another org's vehicle
    sts = client.get(f"{API}/stations", headers=h(transporter)).json()
    slots = client.get(f"{API}/queue/{sts[0]['id']}/slots", headers=h(transporter)).json()
    r = client.post(f"{API}/queue/{sts[0]['id']}/appointments", headers=h(transporter), json={"vehicle_id": other_vehicle, "slot_start": slots[5]["slot_start"]})
    assert r.status_code == 404
    # cargo owner sees only own shipments
    for s in client.get(f"{API}/shipments", headers=h(cargo_owner)).json():
        assert s["owner_org_id"] == cargo_owner["_org"] or s["transporter_org_id"] == cargo_owner["_org"]


def test_public_verify_leaks_no_pii(client, operator):
    evs = client.get(f"{API}/weighing/events?limit=1", headers=h(operator)).json()
    if not evs or not evs[0]["decision"]:
        pytest.skip("no events")
    v = client.get(f"{API}/tickets/verify/{evs[0]['decision']['qr_token']}").json()
    assert set(v.keys()) <= {"valid", "ticket_type", "legal_status", "plate", "gvm_kg", "decision", "occurred_at", "station", "source", "evidence_hash"}


def test_websocket_rejects_bad_token(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/events?token=bad") as ws:
        ws.receive_text()


def test_websocket_tenant_filter(client, transporter, other_transporter, cargo_owner):
    """An org-tagged event for one transporter must not reach another transporter's socket."""
    token_other = other_transporter["Authorization"].split(" ")[1]
    sts = client.get(f"{API}/stations", headers=h(transporter)).json()
    vehicles = client.get(f"{API}/fleet/vehicles", headers=h(transporter)).json()
    slots = client.get(f"{API}/queue/{sts[1]['id']}/slots", headers=h(transporter)).json()
    with client.websocket_connect(f"/ws/events?token={token_other}&types=queue.updated") as ws:
        ws.receive_json()  # hello
        r = client.post(f"{API}/queue/{sts[1]['id']}/appointments", headers=h(transporter), json={"vehicle_id": vehicles[-1]["id"], "slot_start": slots[10]["slot_start"]})
        assert r.status_code in (201, 409)
        # produce an event visible to everyone so the socket has something to return
        client.post(f"{API}/queue/{sts[1]['id']}/observe", headers=h(client_admin(client)), json={"queue_len": 3, "avg_wait_s": 100, "arrivals_per_hour": 10})
        msg = ws.receive_json()
        assert msg["type"] == "queue.updated" and msg.get("org_id") in (None, other_transporter["_org"])


def client_admin(client):
    from .conftest import _login

    return _login(client, "control@demo.invalid")


def test_rate_limit_enforced(client, monkeypatch):
    from kifaru import deps

    s = get_settings()
    monkeypatch.setattr(s, "rate_limit_per_minute", 3)
    deps._windows.clear()
    codes = [client.post(f"{API}/auth/login", json={"email": "x@example.com", "password": "nope-nope-nope"}).status_code for _ in range(5)]
    assert 429 in codes
    monkeypatch.setattr(s, "rate_limit_per_minute", 100000)
    deps._windows.clear()

"""Tests for the hardening introduced after the security review (threat-model findings F1, F3, F5, F9, F10, two-source identity)."""
from __future__ import annotations

import base64

from nacl.signing import SigningKey
from sqlalchemy import select

from kifaru.db import get_sessionmaker
from kifaru.models import AuditEvent, DigitalTicket, User, UserPII
from kifaru.pii import decrypt, is_encrypted
from kifaru.security import canonical_json
from kifaru.services import tickets as svc
from kifaru.services.clearance_engine import AxleInput, IdentityInput, MeasurementInput, VehicleInput, decide

from .conftest import h

API = "/api/v1"


def test_prescreen_ticket_is_superseded_not_deleted(client, operator):
    sts = client.get(f"{API}/stations", headers=h(operator)).json()
    lane = next(ln for s in sts for ln in s["lanes"] if ln["type"] == "wim_highspeed")
    ev = client.post(f"{API}/weighing/simulate", headers=h(operator), json={"lane_id": lane["id"], "seed": 777, "force_gvm_kg": 60000, "sensor_fault_prob": 0.0}).json()[0]
    pre_token = ev["decision"]["qr_token"]
    r = client.post(f"{API}/weighing/events/{ev['id']}/static-verify", headers=h(operator), json={"static_gvm_kg": 59000})
    assert r.status_code == 200 and r.json()["decision"]["ticket_type"] == "static_certified"
    old = client.get(f"{API}/tickets/verify/{pre_token}").json()
    assert old["valid"] is True and old["status"] == "superseded" and old["note"]
    new = client.get(f"{API}/tickets/verify/{r.json()['decision']['qr_token']}").json()
    assert new["valid"] is True and new["status"] == "active" and new["ticket_type"] == "static_certified"


def test_forged_ticket_with_embedded_attacker_key_does_not_verify():
    attacker = SigningKey.generate()
    payload = {"ticket_type": "static_certified", "gvm_kg": 1, "public_key": base64.b64encode(bytes(attacker.verify_key)).decode()}
    sig = base64.b64encode(attacker.sign(canonical_json(payload)).signature).decode()
    forged = DigitalTicket(decision_id="x", type="static_certified", payload=payload, signature=sig, signer_key_id="platform-dev-key", qr_token="forged")
    assert svc.verify(forged) is False
    unknown_key = DigitalTicket(decision_id="x", type="prescreen", payload=payload, signature=sig, signer_key_id="someone-else", qr_token="forged2")
    assert svc.verify(unknown_key) is False


def test_pii_encrypted_at_rest_and_failed_login_audited(client, admin):
    r = client.post(f"{API}/admin/users", headers=h(admin), json={"email": "pii.check@example.com", "password": "Pii#Check2026", "full_name": "PII Check", "roles": ["cargo_owner"], "phone": "+254711222333"})
    assert r.status_code == 201
    with get_sessionmaker()() as db:
        u = db.execute(select(User).where(User.email == "pii.check@example.com")).scalar_one()
        pii = db.get(UserPII, u.id)
        assert is_encrypted(pii.phone_enc) and "+254711222333" not in pii.phone_enc and decrypt(pii.phone_enc) == "+254711222333"
    client.post(f"{API}/auth/login", json={"email": "pii.check@example.com", "password": "wrong-password-x"})
    with get_sessionmaker()() as db:
        assert db.execute(select(AuditEvent).where(AuditEvent.action == "login_failed", AuditEvent.entity_id == u.id)).scalars().first() is not None


def test_two_source_identity_rule():
    m = MeasurementInput(29000, 600, [AxleInput(0, 6000, 200, 1), AxleInput(1, 8000, 200, 2), AxleInput(2, 7500, 200, 3), AxleInput(3, 7500, 200, 3)], "1+1+2")
    v = VehicleInput("v", "KAA 000A", "1+1+2", 14000, 56000)
    assert decide(m, IdentityInput(0.95, "v", "rfid"), v, audit_rate=0.0).decision == "GREEN"
    r = decide(m, IdentityInput(0.95, "v", "rfid"), v, audit_rate=0.0, require_two_sources=True)
    assert r.decision == "AMBER" and any(x["rule"] == "IDENTITY_SINGLE_SOURCE" for x in r.rules_fired)
    assert decide(m, IdentityInput(0.99, "v", "rfid+anpr"), v, audit_rate=0.0, require_two_sources=True).decision == "GREEN"


def test_deployed_config_rejects_dev_defaults():
    from kifaru.config import Settings

    s = Settings(env="prod", database_url="postgresql+psycopg://x:y@h/db", jwt_secret="CHANGE-ME-dev-only-secret-not-for-production")
    try:
        s.validate_for_deployment()
        raise AssertionError("expected RuntimeError")
    except RuntimeError as exc:
        assert "KIFARU_JWT_SECRET" in str(exc) and "SIGNING_SEED" in str(exc) and "PII_KEY" in str(exc)


def test_security_agent_job_opens_incident_for_login_burst(client, admin):
    from kifaru.workers.jobs import refresh_security

    for _ in range(11):
        client.post(f"{API}/auth/login", json={"email": "admin@demo.invalid", "password": "definitely-wrong-pw"})
    with get_sessionmaker()() as db:
        created = refresh_security(db)
        db.commit()
        kinds = {i.details["alert"]["kind"] for i in created}
    assert "credential_stuffing" in kinds
    # unlock the admin account for the remaining tests
    with get_sessionmaker()() as db:
        u = db.execute(select(User).where(User.email == "admin@demo.invalid")).scalar_one()
        u.failed_logins, u.locked_until = 0, None
        db.commit()

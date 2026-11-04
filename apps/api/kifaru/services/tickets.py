"""Digital weighing tickets: signed JSON + QR (Module 5, RCS-11, DCP-02).

Ticket types:
  prescreen        — produced from a WIM pass; informational, NOT a legal weight certificate.
  static_certified — produced when a weighbridge operator records the static scale result (legal reference).
"""
from __future__ import annotations

import io
import secrets

import segno
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ClearanceDecision, DigitalTicket, WeighingEvent
from ..security import public_key_b64, sign_payload, verify_signature


def build_payload(ev: WeighingEvent, dec: ClearanceDecision, ticket_type: str, plate: str | None, station_code: str) -> dict:
    s = get_settings()
    return {
        "ticket_type": ticket_type,
        "legal_status": "LEGAL WEIGHT CERTIFICATE (static scale)" if ticket_type == "static_certified" else
        "PRE-SCREEN ONLY — not a legal weight certificate; static weighing remains the reference",
        "weighing_event_id": ev.id,
        "decision_id": dec.id,
        "station": station_code,
        "lane_id": ev.lane_id,
        "occurred_at": ev.occurred_at.isoformat(),
        "plate": plate,
        "vehicle_id": ev.vehicle_id,
        "shipment_id": ev.shipment_id,
        "gvm_kg": ev.gvm_kg if ticket_type == "prescreen" else (dec.static_verified_gvm_kg or ev.gvm_kg),
        "gvm_uncertainty_kg": ev.gvm_uncertainty_kg if ticket_type == "prescreen" else None,
        "axles": [{"i": a.axle_index, "kg": a.load_kg, "u_kg": a.uncertainty_kg, "group": a.group_no} for a in ev.axles],
        "axle_config": ev.detected_axle_config,
        "decision": dec.decision,
        "limits_version": dec.limits_version,
        "engine_version": dec.engine_version,
        "evidence_hash": dec.evidence_hash,
        "source": ev.source,
        "signer_key_id": s.signing_key_id,
        "public_key": public_key_b64(),
    }


def issue(db: Session, ev: WeighingEvent, dec: ClearanceDecision, ticket_type: str, plate: str | None, station_code: str) -> DigitalTicket:
    payload = build_payload(ev, dec, ticket_type, plate, station_code)
    t = DigitalTicket(
        decision_id=dec.id,
        type=ticket_type,
        payload=payload,
        signature=sign_payload(payload),
        signer_key_id=get_settings().signing_key_id,
        qr_token=secrets.token_urlsafe(24),
    )
    db.add(t)
    db.flush()
    return t


def verify(t: DigitalTicket) -> bool:
    """Server-side verification uses the platform's known key for `signer_key_id`, never the key embedded in the
    payload (a forged payload could embed the forger's key). The embedded key is for offline verifiers only."""
    known = {get_settings().signing_key_id: public_key_b64()}
    key = known.get(t.signer_key_id)
    if key is None:
        return False
    return verify_signature(t.payload, t.signature, key)


def qr_svg(t: DigitalTicket) -> str:
    url = f"{get_settings().public_base_url}/verify/{t.qr_token}"
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=4, dark="#0f172a", light=None)
    return buf.getvalue().decode()

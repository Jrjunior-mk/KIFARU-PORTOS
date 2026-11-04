"""Hash-chained, Ed25519-signed event ledger (Module 5, DCP-03).

Each appended event stores prev_hash (hash of the previous event), hash = sha256(canonical(event core)), and a signature
over the hash. `verify_chain` walks the chain and reports the first break. This gives tamper-evidence equivalent to a
permissioned blockchain for a single-operator system, with none of the operational cost.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..ids import new_id
from ..models import LedgerEvent, utcnow
from ..security import canonical_json, sha256_hex, sign_payload, verify_signature

GENESIS_HASH = "0" * 64


def _core(event_id: str, seq: int, type_: str, payload: dict, station_id: str | None, producer: str, prev_hash: str, occurred_at: datetime) -> dict:
    # Normalise to an aware UTC timestamp so the hash is identical whether the value comes from Python or from a
    # database that drops the timezone (SQLite).
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=UTC)
    occurred_at = occurred_at.astimezone(UTC)
    return {
        "event_id": event_id,
        "seq": seq,
        "type": type_,
        "payload": payload,
        "station_id": station_id,
        "producer": producer,
        "prev_hash": prev_hash,
        "occurred_at": occurred_at.isoformat(),
    }


def append(
    db: Session,
    type_: str,
    payload: dict,
    station_id: str | None = None,
    producer: str = "cloud-api",
    occurred_at: datetime | None = None,
    event_id: str | None = None,
) -> LedgerEvent:
    s = get_settings()
    occurred_at = occurred_at or utcnow()
    last = db.execute(select(LedgerEvent).order_by(LedgerEvent.seq.desc()).limit(1)).scalar_one_or_none()
    seq = (last.seq + 1) if last else 1
    prev_hash = last.hash if last else GENESIS_HASH
    eid = event_id or new_id()
    core = _core(eid, seq, type_, payload, station_id, producer, prev_hash, occurred_at)
    h = sha256_hex(canonical_json(core))
    sig = sign_payload({"hash": h})
    ev = LedgerEvent(
        event_id=eid,
        seq=seq,
        type=type_,
        payload=payload,
        station_id=station_id,
        producer=producer,
        prev_hash=prev_hash,
        hash=h,
        signature=sig,
        signer_key_id=s.signing_key_id,
        occurred_at=occurred_at,
        received_at=utcnow(),
    )
    db.add(ev)
    db.flush()
    return ev


def verify_chain(db: Session, limit: int | None = None) -> dict:
    q = select(LedgerEvent).order_by(LedgerEvent.seq.asc())
    if limit:
        q = q.limit(limit)
    events = db.execute(q).scalars().all()
    prev = GENESIS_HASH
    for ev in events:
        core = _core(ev.event_id, ev.seq, ev.type, ev.payload, ev.station_id, ev.producer, ev.prev_hash, ev.occurred_at)
        expected = sha256_hex(canonical_json(core))
        if ev.prev_hash != prev:
            return {"ok": False, "checked": ev.seq, "error": f"prev_hash mismatch at seq {ev.seq}"}
        if ev.hash != expected:
            return {"ok": False, "checked": ev.seq, "error": f"hash mismatch at seq {ev.seq}"}
        if not verify_signature({"hash": ev.hash}, ev.signature):
            return {"ok": False, "checked": ev.seq, "error": f"signature invalid at seq {ev.seq}"}
        prev = ev.hash
    total = db.execute(select(func.count()).select_from(LedgerEvent)).scalar_one()
    return {"ok": True, "checked": len(events), "total": total, "head_hash": prev}
